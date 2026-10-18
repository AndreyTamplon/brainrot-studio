"""Explicit paid integration checks. Every call uses the normal budget ledger."""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from brainrot import assets, config, media, store
from brainrot.provider import Gateway, OpenRouterLlm


async def main():
    store.init(recover=False)
    gateway = Gateway("smoke-integrations", 1.5)
    calls = []

    async def confirm_tool(value: str) -> dict:
        """Echo a value to verify function calling."""
        calls.append(value)
        return {"echo": value}

    agent = LlmAgent(
        name="smoke",
        model=OpenRouterLlm(
            model=config.SPECIALIST_MODEL, gateway=gateway, role_name="smoke_tools"
        ),
        tools=[confirm_tool],
        instruction="Call confirm_tool with value='brainrot', then answer 'ok'.",
    )
    sessions = InMemorySessionService()
    await sessions.create_session(app_name="smoke", user_id="local", session_id="check")
    runner = Runner(app_name="smoke", agent=agent, session_service=sessions)
    async for _ in runner.run_async(
        user_id="local",
        session_id="check",
        new_message=types.Content(role="user", parts=[types.Part(text="Run the tool check")]),
    ):
        pass
    print("ADK tool calling:", calls, flush=True)
    if calls != ["brainrot"]:
        raise RuntimeError("Tool check failed")
    search = await gateway.chat(
        config.SPECIALIST_MODEL,
        [
            {
                "role": "user",
                "content": "Search the web for one primary source explaining why language models hallucinate. "
                "Give the title, link and one sentence in Russian.",
            }
        ],
        "smoke_search",
        search=True,
        max_tokens=600,
    )
    print("Search:", search.get("content"), flush=True)
    output = config.DATA / "media" / "voice-smoke.mp3"
    speaker = dict(assets.get_asset("speakers", "stewie"))
    speaker["voice"] = speaker["voices_by_language"]["ru"]
    await gateway.speech(
        "Брайан, нейросеть не знает всё на свете. Она предсказывает продолжение текста.",
        speaker,
        output,
    )
    print("Speech:", await media.probe(output), flush=True)
    transcript = await asyncio.to_thread(
        media.transcribe,
        output,
        "ru",
        "Брайан, нейросеть не знает всё на свете. Она предсказывает продолжение текста.",
    )
    print("Transcript:", transcript, flush=True)
    print("Usage:", json.dumps(store.usage("smoke-integrations"), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
