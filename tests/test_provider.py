import httpx
import pytest

from brainrot import config, store
from brainrot.provider import Gateway, ProviderError


def test_agent_limit_is_shared_across_model_roles():
    from brainrot.provider import OpenRouterLlm

    gateway = Gateway("test", 1)
    producer = OpenRouterLlm(model="test", gateway=gateway, role_name="producer")
    child = OpenRouterLlm(model="test", gateway=gateway, role_name="researcher")
    for index in range(65):
        (producer if index % 2 else child).gateway.begin_agent_call()
    with pytest.raises(ProviderError, match="Общий лимит"):
        producer.gateway.begin_agent_call()
    assert gateway.agent_calls == 65


@pytest.fixture
def transport(monkeypatch):
    original = httpx.AsyncClient
    monkeypatch.setattr(config, "api_key", lambda: "sk-or-test-only")

    def install(handler):
        monkeypatch.setattr(
            httpx,
            "AsyncClient",
            lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
        )

    return install


async def test_chat_cost_and_limits(transport):
    seen = []

    def handler(request):
        import json

        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "gen-test",
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"cost": 0.002, "total_tokens": 10},
            },
        )

    transport(handler)
    result = await Gateway("test", 1).chat(
        "test-model", [{"role": "user", "content": "Hi"}], "test"
    )
    assert result["content"] == "ok"
    assert store.usage("test")["spent"] == 0.002
    assert store.usage("test")["held"] == 0
    assert seen[0]["max_tokens"] == 4500
    assert seen[0]["provider"]["max_price"]["completion"] == 2


async def test_rejected_request_releases_reserve(transport):
    transport(lambda request: httpx.Response(400, json={"error": {"message": "bad model"}}))
    with pytest.raises(ProviderError, match="HTTP 400"):
        await Gateway("test", 1).chat("test", [], "test")
    assert store.usage("test")["held"] == 0
    assert store.usage("test")["spent"] == 0


async def test_search_always_runs_plugin_instead_of_optional_tool(transport):
    import json

    def handler(request):
        body = json.loads(request.content)
        assert body["plugins"] == [{"id": "web", "engine": "exa", "max_results": 5}]
        assert "tools" not in body
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "Grounded search", "annotations": []}}],
                "usage": {"cost": 0.001},
            },
        )

    transport(handler)
    await Gateway("test", 1).chat("test", [], "research_search", search=True)


async def test_timeout_preserves_unknown_charge(transport):
    def handler(request):
        raise httpx.ReadTimeout("timed out")

    transport(handler)
    with pytest.raises(httpx.ReadTimeout):
        await Gateway("test", 1).chat("test", [], "test")
    assert store.usage("test")["held"] == 0.15


async def test_structured_content_limit_before_payment(transport):
    transport(lambda request: pytest.fail("Must not send oversized content"))
    with pytest.raises(ProviderError, match="Контекст"):
        await Gateway("test", 1).chat(
            "test", [{"role": "user", "content": [{"type": "text", "text": "x" * 100_001}]}], "test"
        )
    assert store.usage("test")["calls"] == 0


async def test_audio_review_has_separate_bounded_price(transport):
    import json

    def handler(request):
        body = json.loads(request.content)
        assert body["provider"]["max_price"] == {"prompt": 1, "completion": 4}
        assert body["max_tokens"] == 2400
        assert body["reasoning"] == {"effort": "low"}
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "ok"}}], "usage": {"cost": 0.001}}
        )

    transport(handler)
    await Gateway("test", 1).chat(
        config.AUDIO_REVIEW_MODEL,
        [
            {
                "role": "user",
                "content": [
                    {"type": "input_audio", "input_audio": {"data": "AAAA", "format": "mp3"}}
                ],
            }
        ],
        "audio_review",
        max_tokens=9000,
    )


def test_known_cost_not_replaced_by_late_uncertainty():
    charge = store.reserve("test", "model", "purpose", 0.15, 1)
    store.settle(charge, 0.003, "gen-test")
    store.settle(charge, uncertain=True)
    assert store.usage("test")["spent"] == 0.003
    assert store.usage("test")["held"] == 0


async def test_fish_reservation_uses_utf8_bytes_and_cached_live_price(transport):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(
            200,
            json={"data": {"endpoints": [{"pricing": {"prompt": "0.000015", "completion": "0"}}]}},
        )

    transport(handler)
    gateway = Gateway("test", 1)
    assert await gateway.speech_reserve("fish-audio/s2.1-pro", "я" * 650) == pytest.approx(0.044)
    assert await gateway.speech_reserve("fish-audio/s2.1-pro", "Short") == 0.02
    assert len(calls) == 1
    assert store.usage("test")["calls"] == 0


@pytest.mark.parametrize(
    "pricing",
    [
        {"prompt": "0.01", "completion": "0"},
        {"prompt": "NaN", "completion": "0"},
        {"prompt": "0.000015", "completion": "0.5"},
    ],
)
async def test_unknown_tts_price_is_rejected_before_spending(transport, pricing):
    transport(
        lambda request: httpx.Response(200, json={"data": {"endpoints": [{"pricing": pricing}]}})
    )
    with pytest.raises(ProviderError, match="тариф"):
        await Gateway("test", 1).speech_reserve("fish-audio/s2.1-pro", "test")
    assert store.usage("test")["calls"] == 0
