import json
import socket
from concurrent.futures import ThreadPoolExecutor

import pytest
from google.adk.models.llm_request import LlmRequest
from google.genai import types
from pydantic import ValidationError

from brainrot import assets, store
from brainrot.provider import adk_messages, extract_json, schema_dict
from brainrot.schemas import JobRequest, RenderPlan, Scene, Script


def test_store_lifecycle():
    job_id = store.create_job({"topic": "Hello"})
    assert store.get_job(job_id)["status"] == "queued"
    store.update(job_id, status="running", artifacts={"script": {"title": "Test"}})
    store.event(job_id, "writer", "saved", {"version": 1})
    assert store.events(job_id)[0]["detail"] == {"version": 1}
    store.init()
    assert store.get_job(job_id)["status"] == "queued"
    assert store.get_job(job_id)["artifacts"]["script"]["title"] == "Test"


def test_atomic_budget(monkeypatch):
    monkeypatch.setattr(store, "TOTAL_BUDGET", 0.25)

    def spend(_):
        try:
            store.reserve("job", "test", "test", 0.1, 1)
            return True
        except store.BudgetExceeded:
            return False

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(spend, range(5)))
    assert sum(results) == 2
    assert store.usage()["held"] == pytest.approx(0.2)


def test_settlement_and_job_limit():
    charge = store.reserve("job", "test", "test", 0.15, 0.2)
    with pytest.raises(store.BudgetExceeded):
        store.reserve("job", "test", "test", 0.1, 0.2)
    store.settle(charge, 0.01, "generation", 20)
    assert store.usage()["spent"] == 0.01
    store.reserve("job", "test", "test", 0.15, 0.2)


def test_uncertain_charge_not_freed():
    charge = store.reserve("job", "test", "test", 0.15, 0.2)
    store.settle(charge, uncertain=True)
    assert store.usage()["held"] == 0.15


def test_schemas_reject_bad_inputs():
    with pytest.raises(ValidationError):
        JobRequest(topic="Topic", background_id="bg", speaker_ids=["a", "a"])
    with pytest.raises(ValidationError):
        RenderPlan(playback_speed=10)
    with pytest.raises(ValidationError, match="production notes"):
        Scene(id="s1", speaker_id="a", text="Hello", visual_caption="Луна (File:Moon.jpg)")
    with pytest.raises(ValidationError):
        Script(
            title="Title",
            hook="Hook",
            scenes=[
                {"id": "s1", "speaker_id": "a", "text": "x"},
                {"id": "s1", "speaker_id": "a", "text": "y"},
            ],
        )


@pytest.mark.parametrize(
    "text",
    [
        "Плотность одна целая двадцать четыре десятых килограмма на литр.",
        "Одна целая сто двадцать сотых.",
        "Две целых десять десятых.",
        "Одной целой двадцати четырёх десятых.",
        "Одна целая тысяча двести тысячных.",
        "ОДНА ЦЕЛАЯ 24 ДЕСЯТЫХ.",
    ],
)
def test_scene_rejects_improper_spoken_decimal(text):
    with pytest.raises(ValidationError, match="Invalid spoken decimal"):
        Scene(id="s1", speaker_id="a", text=text)


@pytest.mark.parametrize(
    "text",
    [
        "Одна целая двадцать четыре сотых.",
        "Ноль целых девятьсот семнадцать тысячных.",
        "Две целых одна десятая.",
        "Одной целой двадцати четырёх сотых.",
        "Двадцать четыре десятых равны двум целым четырём десятым.",
        "One point twenty-four. 1.24.",
        "Целая история про сотых зрителей.",
    ],
)
def test_scene_preserves_valid_decimals_and_unrelated_speech(text):
    assert Scene(id="s1", speaker_id="a", text=text).text == text


def test_path_traversal(isolated_data):
    with pytest.raises(ValueError):
        assets.local_path("../../.env")


@pytest.mark.parametrize("description", ["", "<b>Viktor Savinykh</b> and Vladimir Dzhanibekov"])
async def test_commons_preserves_clean_identity_metadata(monkeypatch, description):
    import httpx

    def respond(request):
        assert "extmetadata" in request.url.params["iiprop"]
        return httpx.Response(
            200,
            json={
                "query": {
                    "pages": {
                        "7": {
                            "pageid": 7,
                            "title": "File:Meeting with film crew.jpg",
                            "imageinfo": [
                                {
                                    "url": "https://upload.wikimedia.org/test.jpg",
                                    "width": 400,
                                    "descriptionurl": "https://commons.wikimedia.org/wiki/File:Meeting.jpg",
                                    "extmetadata": {"ImageDescription": {"value": description}},
                                }
                            ],
                        }
                    }
                }
            },
        )

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        assets.httpx,
        "AsyncClient",
        lambda **kwargs: client_type(transport=httpx.MockTransport(respond), **kwargs),
    )
    result = await assets.commons_search("film crew")
    assert result[0]["description"] == (
        "Viktor Savinykh and Vladimir Dzhanibekov" if description else ""
    )


def test_ssrf(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a: [(2, 1, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(ValueError):
        assets.safe_url("https://internal.test/file.png")
    with pytest.raises(ValueError):
        assets.safe_url("file:///etc/passwd")


def test_adk_function_roundtrip():
    request = LlmRequest(
        contents=[
            types.Content(role="user", parts=[types.Part(text="Run")]),
            types.Content(
                role="model",
                parts=[
                    types.Part(
                        function_call=types.FunctionCall(
                            id="call_1", name="tool", args={"value": "a"}
                        )
                    )
                ],
            ),
            types.Content(
                role="user",
                parts=[
                    types.Part(
                        function_response=types.FunctionResponse(
                            id="call_1", name="tool", response={"ok": True}
                        )
                    )
                ],
            ),
        ],
        config=types.GenerateContentConfig(system_instruction="Instructions"),
    )
    messages = adk_messages(request)
    assert messages[0]["role"] == "system"
    assert messages[2]["tool_calls"][0]["id"] == "call_1"
    assert messages[3] == {"role": "tool", "tool_call_id": "call_1", "content": '{"ok": true}'}


def test_tool_schema_and_json():
    assert (
        schema_dict({"type": "OBJECT", "properties": {"q": {"type": "STRING"}}})["type"] == "object"
    )
    assert extract_json('```json\n{"ok": true}\n```') == {"ok": True}
    with pytest.raises(json.JSONDecodeError):
        extract_json("not json")
