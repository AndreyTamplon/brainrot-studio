"""OpenRouter transport and the ADK model adapter; no provider key leaves this module."""

import asyncio
import base64
import json
import math
import time
import uuid
from pathlib import Path

import httpx
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import Field

from . import config, store

BASE = "https://openrouter.ai/api/v1"


class ProviderError(RuntimeError):
    def __init__(self, message, *, retryable=False):
        super().__init__(message)
        self.retryable = retryable


async def reconcile_charges(job_id=None):
    """TTS billing records can arrive after the audio; settle known generation IDs later."""
    if not config.api_key():
        return
    pending = store.claim_charge_rechecks(job_id)
    if not pending:
        return
    async with httpx.AsyncClient(timeout=10) as client:
        for entry in pending:
            try:
                response = await client.get(
                    BASE + "/generation",
                    params={"id": entry["request_id"]},
                    headers={"Authorization": "Bearer " + config.api_key()},
                )
                if response.is_success:
                    cost = response.json().get("data", {}).get("total_cost")
                    if cost is not None and math.isfinite(float(cost)) and float(cost) >= 0:
                        store.settle(entry["id"], float(cost), entry["request_id"], entry["tokens"])
            except (httpx.HTTPError, ValueError, TypeError, AttributeError):
                continue


def extract_json(text: str):
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(stripped)


class Gateway:
    def __init__(self, job_id: str, limit: float = config.RUN_BUDGET):
        self.job_id, self.limit = job_id, limit
        self.semaphore = asyncio.Semaphore(3)
        self.cancelled = False
        self.last_reconcile = 0
        self.speech_rates = {}
        self.agent_calls = 0

    def begin_agent_call(self):
        self.check()
        if self.agent_calls >= 65:
            raise ProviderError("Общий лимит вызовов агентов достигнут")
        self.agent_calls += 1

    async def reconcile(self):
        if time.time() - self.last_reconcile >= 15:
            self.last_reconcile = time.time()
            await reconcile_charges(self.job_id)

    def headers(self):
        key = config.api_key()
        if not key:
            raise ProviderError("Добавьте ключ OpenRouter в настройках")
        return {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "X-Title": "Brainrot Studio",
            "HTTP-Referer": "http://localhost:8000",
        }

    def check(self):
        if self.cancelled:
            raise asyncio.CancelledError()

    async def chat(
        self, model, messages, purpose, tools=None, schema=None, search=False, max_tokens=4500
    ):
        self.check()
        await self.reconcile()
        headers = self.headers()
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0 if schema else 0.6,
            "reasoning": {"enabled": False},
            "provider": {"max_price": {"prompt": 1, "completion": 2}},
        }
        audio_parts = [
            part
            for message in messages
            if isinstance(message.get("content"), list)
            for part in message["content"]
            if part.get("type") == "input_audio"
        ]
        if sum(len(p.get("input_audio", {}).get("data", "")) for p in audio_parts) > 25_000_000:
            raise ProviderError("Audio review input exceeds limit")
        if model == config.AUDIO_REVIEW_MODEL:
            # Native media QA has a separate, bounded rate; producer/writer pricing is unchanged.
            payload["provider"]["max_price"] = {"prompt": 1, "completion": 4}
            payload["max_tokens"] = min(max_tokens, 2400)
            payload["reasoning"] = {"effort": "low"}
        all_tools = list(tools or [])
        if search:
            # A search tool must actually search, not let the model skip an optional tool.
            payload["plugins"] = [{"id": "web", "engine": "exa", "max_results": 5}]
        if all_tools:
            payload["tools"] = all_tools
            if not search:
                payload["parallel_tool_calls"] = False
        if schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "result", "strict": False, "schema": schema},
            }
        # Reject runaway contexts before reserving any paid call. Image bytes do not count as text.
        text_chars = 0
        for message in messages:
            content = message.get("content") or ""
            if isinstance(content, str):
                text_chars += len(content)
            else:
                text_chars += sum(len(part.get("text", "")) for part in content)
            text_chars += len(json.dumps(message.get("tool_calls", []), ensure_ascii=False))
        if text_chars > 100_000:
            raise ProviderError("Контекст превысил лимит проекта")
        async with self.semaphore:
            charge = store.reserve(self.job_id, model, purpose, 0.15, self.limit)
            store.event(self.job_id, purpose, "model_start", {"model": model})
            try:
                async with asyncio.timeout(240), httpx.AsyncClient(timeout=240) as client:
                    response = await client.post(
                        BASE + "/chat/completions", headers=headers, json=payload
                    )
                if response.status_code >= 400:
                    store.settle(
                        charge,
                        0 if response.status_code < 500 else None,
                        uncertain=response.status_code >= 500,
                    )
                    raise ProviderError(
                        f"OpenRouter HTTP {response.status_code}: " + self.safe_error(response),
                        retryable=response.status_code == 429 or response.status_code >= 500,
                    )
                result = response.json()
                if "error" in result or not result.get("choices"):
                    store.settle(charge, uncertain=True)
                    raise ProviderError("OpenRouter вернул ошибку генерации")
                usage = result.get("usage", {})
                store.settle(
                    charge, usage.get("cost"), result.get("id"), usage.get("total_tokens", 0)
                )
                store.event(
                    self.job_id,
                    purpose,
                    "model_end",
                    {
                        "model": model,
                        "cost": usage.get("cost"),
                        "tokens": usage.get("total_tokens", 0),
                    },
                )
                return {**result["choices"][0]["message"], "_usage": usage}
            except (httpx.RequestError, asyncio.CancelledError, TimeoutError):
                store.settle(charge, uncertain=True)
                raise

    @staticmethod
    def safe_error(response):
        try:
            error = response.json().get("error", {})
            return str(error.get("message", "Provider rejected request"))[:250]
        except (ValueError, AttributeError):
            return "Provider unavailable"

    async def speech_reserve(self, model, text, reference_text=""):
        if model != "fish-audio/s2.1-pro":
            return 0.15
        cached = self.speech_rates.get(model)
        if not cached or time.time() - cached[0] > 900:
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    response = await client.get(BASE + "/models/" + model + "/endpoints")
                    response.raise_for_status()
                endpoints = response.json()["data"]["endpoints"]
                rates = [float(e["pricing"]["prompt"]) for e in endpoints]
                if not rates or any(not math.isfinite(r) or r <= 0 or r > 0.00003 for r in rates):
                    raise ValueError("Unexpected speech input rate")
                if any(float(e["pricing"]["completion"]) != 0 for e in endpoints):
                    raise ValueError("Unexpected speech output billing")
                cached = (time.time(), max(rates))
                self.speech_rates[model] = cached
            except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
                raise ProviderError(
                    "Не удалось подтвердить безопасный тариф Fish TTS. Попробуйте продолжить позже."
                ) from exc
        # Fish bills UTF-8 bytes, not Unicode characters. Keep a 2x rate margin plus $0.005.
        amount = max(0.02, len((text + reference_text).encode("utf-8")) * cached[1] * 2 + 0.005)
        return round(amount, 6)

    async def speech(self, text: str, speaker: dict, output: Path):
        self.check()
        await self.reconcile()
        model = speaker.get("tts_model") or config.TTS_MODEL
        pcm = model.startswith("google/gemini-")
        payload = {"model": model, "input": text, "response_format": "pcm" if pcm else "mp3"}
        reference = speaker.get("voice_reference")
        if reference:
            audio = (config.DATA / reference).read_bytes()
            if len(audio) > 10_000_000:
                raise ProviderError("Образец голоса слишком большой")
            payload["input_references"] = [
                {"type": "input_audio", "input_audio": {"data": base64.b64encode(audio).decode()}}
            ]
            if speaker.get("reference_text"):
                payload["input_references"].append(
                    {"type": "text", "text": speaker["reference_text"]}
                )
        elif speaker.get("voice"):
            payload["voice"] = speaker["voice"]
        async with self.semaphore:
            headers = self.headers()
            reservation = await self.speech_reserve(model, text, speaker.get("reference_text", ""))
            charge = store.reserve(self.job_id, model, "speech", reservation, self.limit)
            try:
                async with asyncio.timeout(240), httpx.AsyncClient(timeout=240) as client:
                    response = await client.post(
                        BASE + "/audio/speech", headers=headers, json=payload
                    )
                    if response.status_code >= 400:
                        store.settle(
                            charge,
                            0 if response.status_code < 500 else None,
                            uncertain=response.status_code >= 500,
                        )
                        raise ProviderError(
                            f"TTS HTTP {response.status_code}: " + self.safe_error(response),
                            retryable=response.status_code == 429 or response.status_code >= 500,
                        )
                    content_type = response.headers.get("content-type", "")
                    if not (
                        content_type.startswith("audio/")
                        or (pcm and content_type.startswith("application/octet-stream"))
                    ):
                        store.settle(charge, uncertain=True)
                        raise ProviderError("TTS не вернул аудио")
                    temporary = output.with_suffix(".pcm" if pcm else ".pending.mp3")
                    temporary.write_bytes(response.content)
                    if pcm:
                        from .media import command

                        encoded = output.with_suffix(".pending.mp3")
                        input_args = (
                            []
                            if response.content.startswith(b"RIFF")
                            else ["-f", "s16le", "-ar", "24000", "-ac", "1"]
                        )
                        await command(
                            "ffmpeg",
                            "-v",
                            "error",
                            "-y",
                            *input_args,
                            "-i",
                            temporary,
                            "-c:a",
                            "libmp3lame",
                            "-q:a",
                            "2",
                            encoded,
                        )
                        temporary.unlink(missing_ok=True)
                        temporary = encoded
                    temporary.replace(output)
                    generation_id = response.headers.get("x-generation-id")
                    store.settle(charge, request_id=generation_id)
                    if generation_id:
                        for delay in (0.5, 1, 2):
                            await asyncio.sleep(delay)
                            cost_response = await client.get(
                                BASE + "/generation", params={"id": generation_id}, headers=headers
                            )
                            if cost_response.is_success:
                                cost = cost_response.json().get("data", {}).get("total_cost")
                                if cost is not None:
                                    store.settle(charge, float(cost), generation_id)
                                    break
                return output
            except (httpx.RequestError, asyncio.CancelledError, TimeoutError):
                store.settle(charge, uncertain=True)
                raise


def schema_dict(schema):
    if schema is None:
        return {"type": "object", "properties": {}}
    raw = schema if isinstance(schema, dict) else schema.model_dump(exclude_none=True)

    def normalize(value):
        if isinstance(value, dict):
            return {
                k: (str(v).lower() if k == "type" else normalize(v))
                for k, v in value.items()
                if k not in {"property_ordering"}
            }
        if isinstance(value, list):
            return [normalize(v) for v in value]
        return value

    return normalize(raw)


def adk_messages(request):
    messages, pending = [], {}
    instruction = request.config.system_instruction
    if instruction:
        if not isinstance(instruction, str):
            instruction = "\n".join(p.text for p in instruction.parts if p.text)
        messages.append({"role": "system", "content": instruction})
    for content in request.contents:
        role = "assistant" if content.role == "model" else "user"
        parts, calls, responses = [], [], []
        for part in content.parts or []:
            if part.thought:
                continue
            if part.text:
                parts.append({"type": "text", "text": part.text})
            if part.inline_data:
                blob = part.inline_data
                parts.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{blob.mime_type};base64,{base64.b64encode(blob.data).decode()}"
                        },
                    }
                )
            if part.function_call:
                call = part.function_call
                call_id = call.id or "call_" + uuid.uuid4().hex[:16]
                pending.setdefault(call.name, []).append(call_id)
                calls.append(
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(call.args or {}, ensure_ascii=False),
                        },
                    }
                )
            if part.function_response:
                response = part.function_response
                ids = pending.get(response.name, [])
                call_id = response.id or (ids[0] if ids else None)
                if call_id in ids:
                    ids.remove(call_id)
                if call_id:
                    responses.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": store.dumps(response.response),
                        }
                    )
        if parts or calls:
            message = {"role": role, "content": parts or None}
            if calls:
                message["tool_calls"] = calls
            messages.append(message)
        messages.extend(responses)
    return messages


class OpenRouterLlm(BaseLlm):
    gateway: Gateway = Field(exclude=True)
    role_name: str

    async def generate_content_async(self, llm_request, stream=False):
        self.gateway.begin_agent_call()
        functions = []
        for tool in llm_request.config.tools or []:
            for declaration in tool.function_declarations or []:
                functions.append(
                    {
                        "type": "function",
                        "function": {
                            "name": declaration.name,
                            "description": declaration.description or "",
                            "parameters": schema_dict(
                                declaration.parameters_json_schema or declaration.parameters
                            ),
                        },
                    }
                )
        response = await self.gateway.chat(
            self.model, adk_messages(llm_request), self.role_name, tools=functions
        )
        parts = []
        if response.get("content"):
            parts.append(types.Part(text=response["content"]))
        # One deliberate action per turn; audio/visual concurrency is managed by the producer.
        for call in response.get("tool_calls", [])[:1]:
            function = call["function"]
            parts.append(
                types.Part(
                    function_call=types.FunctionCall(
                        id=call["id"], name=function["name"], args=json.loads(function["arguments"])
                    )
                )
            )
        if not parts:
            raise ProviderError("Модель вернула пустой ответ")
        usage = response.get("_usage", {})
        yield LlmResponse(
            content=types.Content(role="model", parts=parts),
            partial=False,
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=usage.get("prompt_tokens", 0),
                candidates_token_count=usage.get("completion_tokens", 0),
                total_token_count=usage.get("total_tokens", 0),
            ),
        )
