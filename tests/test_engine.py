import json

import pytest
from PIL import Image

from brainrot import assets, config, frame_review, media, review_policy, store
from brainrot.engine import Production, digest


@pytest.mark.parametrize("repeated_failure", [False, True])
async def test_review_retry_preserves_checked_frames(
    production, isolated_data, monkeypatch, repeated_failure
):
    from brainrot import quality

    Image.new("RGB", (24, 24), "red").save(isolated_data / "frame.jpg")
    production.artifacts.update(
        {
            "video": "video.mp4",
            "visual_complete": "current",
            "quality": {"version": quality.VERSION, "passed": True, "issues": []},
            "audio_review": {
                "version": 1,
                "model": config.AUDIO_REVIEW_MODEL,
                "passed": True,
                "issues": [],
            },
            "frames": [{"scene_id": s, "path": "frame.jpg"} for s in ("s1", "s2")],
            "technical": {
                "has_audio": True,
                "decoded": True,
                "width": 1080,
                "height": 1920,
                "duration": 15,
            },
            "script": {"title": "Review fixture", "scenes": [{"id": s} for s in ("s1", "s2")]},
            "audio": {s: {"similarity": 1} for s in ("s1", "s2")},
        }
    )
    valid = json.dumps({"passed": True, "summary": "Visible frame is correct", "issues": []})
    responses = iter([valid, "{malformed", "{malformed" if repeated_failure else valid])
    calls = []

    async def chat(*args, **kwargs):
        calls.append(args)
        return {"content": next(responses)}

    monkeypatch.setattr(production.gateway, "chat", chat)
    first = await production.inspect_video()
    assert "error" in first
    assert [f["scene_id"] for f in production.artifacts["frame_reviews"]] == ["s1"]
    second = await production.inspect_video()
    assert second["passed"] is not repeated_failure
    assert bool(production.artifacts.get("visual_revision")) is repeated_failure
    assert (production.artifacts.get("visual_complete") == "current") is not repeated_failure
    assert len(calls) == 3
    assert (await production.inspect_video()) == second
    assert len(calls) == 3


@pytest.fixture
def production():
    assets.save_catalog({"backgrounds": [], "speakers": [{"id": "n", "name": "Narrator"}]})
    job = store.create_job(
        {
            "topic": "Topic",
            "speaker_ids": ["n"],
            "budget": 1,
            "duration": 15,
            "language": "en",
            "subtitles": True,
        }
    )
    return Production(job)


async def test_sources_must_be_observed(production, monkeypatch):
    research = {
        "summary": "Facts",
        "facts": ["one", "two"],
        "sources": [{"title": "Source", "url": "https://example.org/real"}],
    }
    assert "error" in await production.save_research(json.dumps(research))
    production.artifacts["search_results"] = [{"text": "https://example.org/real"}]
    assert "error" in await production.save_research(json.dumps(research))
    production.artifacts["search_results"].append(
        {"annotations": [{"url": "https://example.org/real", "excerpt": "one and two"}]}
    )
    calls = []

    async def chat(model, messages, purpose, **kwargs):
        calls.append(purpose)
        assert "one and two" in messages[0]["content"]
        return {"content": json.dumps({"passed": True, "issues": []})}

    monkeypatch.setattr(production.gateway, "chat", chat)
    assert (await production.save_research(json.dumps(research)))["saved"]
    assert (await production.save_research(json.dumps(research)))["saved"]
    assert calls == ["research_review"]
    research["sources"][0]["url"] = "javascript:alert(1)"
    assert "error" in await production.save_research(json.dumps(research))


async def test_search_without_provider_evidence_discards_hallucinated_prose(
    production, monkeypatch
):
    async def chat(*args, **kwargs):
        return {"content": "Invented fact: https://example.org/fake", "annotations": []}

    monkeypatch.setattr(production.gateway, "chat", chat)
    result = await production.search_web("Fact")
    assert "error" in result
    assert "Invented fact" not in store.dumps(production.artifacts)


async def test_unsupported_research_is_rejected_and_rejection_cached(production, monkeypatch):
    production.artifacts["search_results"] = [
        {
            "annotations": [
                {
                    "url": "https://example.org/source",
                    "excerpt": "The documented event was in June.",
                }
            ]
        }
    ]
    research = {
        "summary": "History",
        "facts": ["July", "Another invented claim"],
        "sources": [{"title": "Source", "url": "https://example.org/source"}],
    }
    calls = []

    async def chat(*args, **kwargs):
        calls.append(1)
        return {"content": json.dumps({"passed": False, "issues": ["Wrong month"]})}

    monkeypatch.setattr(production.gateway, "chat", chat)
    for _ in range(2):
        result = await production.save_research(json.dumps(research))
        assert result["issues"] == ["Wrong month"]
    assert "research" not in production.artifacts
    assert len(calls) == 2


async def test_research_false_positive_is_independently_adjudicated(production, monkeypatch):
    from brainrot.schemas import Research

    research = Research(
        summary="Research",
        facts=["One", "Two"],
        sources=[{"title": "Source", "url": "https://example.org/source"}],
    )
    responses = iter(
        [
            {"passed": False, "issues": ["Supported but not the exact wording"]},
            {"passed": True, "issues": []},
        ]
    )
    calls = []

    async def chat(model, messages, purpose, **kwargs):
        calls.append((model, purpose))
        return {"content": json.dumps(next(responses))}

    monkeypatch.setattr(production.gateway, "chat", chat)
    assert (await production.review_research(research, [])).passed
    assert calls == [
        (config.ORCHESTRATOR_MODEL, "research_review"),
        (config.VISION_MODEL, "research_adjudication"),
    ]


async def test_saved_search_excerpts_survive_specialist_reentry(production):
    evidence = {
        "url": "https://example.org/verified",
        "title": "Source",
        "excerpt": "Real evidence",
    }
    production.artifacts["search_results"] = [{"annotations": [evidence]}]
    production.persist()
    resumed = Production(production.id)
    project = await resumed.get_project()
    assert project["saved_searches"] == [
        {"index": 0, "sources": [{"url": evidence["url"], "title": evidence["title"]}]}
    ]
    assert (await resumed.read_search_results(0))["annotations"] == [evidence]
    assert "error" in await resumed.read_search_results(-1)
    assert store.usage(production.id)["calls"] == 0


@pytest.mark.parametrize("repeat_failure", [False, True])
@pytest.mark.parametrize("failure", ["malformed", "oversized"])
async def test_research_review_format_retry_is_bounded(
    production, monkeypatch, repeat_failure, failure
):
    from brainrot.schemas import Research

    research = Research(
        summary="Research",
        facts=["One", "Two"],
        sources=[{"title": "Source", "url": "https://example.org/source"}],
    )
    invalid = (
        '{"passed": false, "issues": ["truncated'
        if failure == "malformed"
        else json.dumps({"passed": False, "issues": ["x" * 241]})
    )
    responses = iter([invalid, invalid if repeat_failure else '{"passed": true, "issues": []}'])
    calls = []

    async def chat(*args, **kwargs):
        calls.append(1)
        return {"content": next(responses)}

    monkeypatch.setattr(production.gateway, "chat", chat)
    if repeat_failure:
        with pytest.raises(ValueError):
            await production.review_research(research, [])
    else:
        assert (await production.review_research(research, [])).passed
    assert len(calls) == 2


async def test_specialist_prose_without_artifact_is_not_completion(production):
    from types import SimpleNamespace

    response = await production.after_agent(SimpleNamespace(agent_name="researcher", state={}))
    result = json.loads(response.parts[0].text)
    assert result["blocked_agent"] == "researcher"
    assert "error" in result


async def test_writer_cannot_run_before_research_is_saved(production):
    from types import SimpleNamespace

    result = await production.before_tool(
        SimpleNamespace(name="writer"), {}, SimpleNamespace(agent_name="producer")
    )
    assert "error" in result
    assert store.usage(production.id)["calls"] == 0


@pytest.mark.parametrize("substantiated", [False, True])
async def test_disputed_script_review_is_adjudicated(production, monkeypatch, substantiated):
    production.artifacts.update(
        {
            "research": {"summary": "Evidence"},
            "script": {
                "title": "Title",
                "hook": "Hook",
                "scenes": [
                    {"id": "s1", "speaker_id": "n", "text": "The correct explanation."},
                    {"id": "s2", "speaker_id": "n", "text": "The conclusion."},
                ],
            },
            "script_hash": "current",
            "audio_complete": "current",
            "audio_duration": 15,
        }
    )
    responses = iter(
        [
            {"passed": False, "issues": ["Alleged error"]},
            {"passed": not substantiated, "issues": ["Confirmed error"] if substantiated else []},
        ]
    )
    purposes = []

    async def chat(model, messages, purpose, **kwargs):
        purposes.append(purpose)
        assert model == (
            config.SCRIPT_REVIEW_MODEL if purpose == "script_review" else config.WRITER_MODEL
        )
        assert "Brief:" in messages[0]["content"]
        assert production.request["topic"] in messages[0]["content"]
        return {"content": json.dumps(next(responses))}

    monkeypatch.setattr(production.gateway, "chat", chat)
    result = await production.start_audio()
    assert purposes == ["script_review", "script_adjudication"]
    assert ("error" in result) is substantiated
    assert production.artifacts["script_review"]["passed"] is not substantiated
    if not substantiated:
        assert (await production.start_audio())["state"] == "cached"
        assert len(purposes) == 2
        monkeypatch.setattr(config, "SCRIPT_REVIEW_MODEL", "different-reviewer")

        async def accept_again(model, messages, purpose, **kwargs):
            purposes.append(purpose)
            return {"content": '{"passed": true, "issues": []}'}

        monkeypatch.setattr(production.gateway, "chat", accept_again)
        assert (await production.start_audio())["state"] == "cached"
        assert len(purposes) == 3


async def test_script_revisions_invalidate_downstream(production):
    production.artifacts.update(
        {
            "research": {},
            "video": "old",
            "review": {},
            "audio_complete": "old",
            "visual_complete": "old",
        }
    )
    script = {
        "title": "Title",
        "hook": "Hook",
        "scenes": [
            {"id": "s1", "speaker_id": "n", "text": "a " * 15},
            {"id": "s2", "speaker_id": "n", "text": "b " * 15},
        ],
    }
    assert "error" in await production.save_script(json.dumps(script))
    production.artifacts["research"] = {"summary": "Accepted"}
    assert (await production.save_script(json.dumps(script)))["saved"]
    assert "video" not in production.artifacts
    assert "audio_complete" not in production.artifacts
    assert "visual_complete" not in production.artifacts
    assert "error" in await production.render_video("{}")
    assert (await production.finish_project("Done"))["status"] == "needs_review"


async def test_visual_change_invalidates_review(production):
    production.artifacts.update(
        {
            "script": {"scenes": [{"id": "s1", "speaker_id": "n", "text": "Hello"}]},
            "script_hash": "hash",
            "video": "old",
            "review": {"passed": True},
        }
    )
    assert "error" in await production.complete_visuals()
    production.candidates["123"] = {"id": "123", "title": "Test image", "path": "picture.png"}
    assert (await production.select_image("s1", "123", "Relevant"))["saved"]
    assert "video" not in production.artifacts
    assert "review" not in production.artifacts
    assert (await production.complete_visuals())["image_count"] == 1


@pytest.fixture
def reviewed_artifacts():
    return {
        "video": "accepted.mp4",
        "script_hash": "current",
        "audio_complete": "current",
        "visual_complete": "current",
        "review": {
            "passed": True,
            "version": review_policy.FRAME_VERSION,
            "model": config.VISION_MODEL,
            "video_sha256": "checked",
        },
        "quality": {
            "passed": True,
            "version": review_policy.AV_VERSION,
            "video_sha256": "checked",
        },
        "audio_review": {
            "passed": True,
            "version": review_policy.AUDIO_VERSION,
            "model": config.AUDIO_REVIEW_MODEL,
            "video_sha256": "checked",
        },
    }


async def test_failed_quality_gate_never_ready(production, reviewed_artifacts):
    production.artifacts.update({"video": "video.mp4", "review": {"passed": False}})
    assert "error" in await production.finish_project("Not inspected yet")
    production.artifacts.update(reviewed_artifacts)
    production.artifacts["review"]["passed"] = False
    assert (await production.finish_project("Needs review"))["status"] == "needs_review"
    production.artifacts["review"]["passed"] = True
    assert (await production.finish_project("Ready"))["status"] == "ready"
    production.artifacts["audio_review"]["video_sha256"] = "old-video"
    assert "error" in await production.finish_project("Wrong soundtrack")
    assert not production.accepted()


async def test_invalid_decimal_in_saved_script_requires_revision_before_tts(
    production, reviewed_artifacts
):
    production.artifacts.update(reviewed_artifacts)
    production.artifacts["script"] = {
        "title": "Density",
        "hook": "Density",
        "scenes": [
            {"id": "s1", "speaker_id": "n", "text": "Одна целая двадцать четыре десятых."},
            {"id": "s2", "speaker_id": "n", "text": "Конец."},
        ],
    }
    assert not production.accepted()
    store.update(production.id, status="ready", artifacts=production.artifacts)
    store.init()
    assert store.get_job(production.id)["status"] == "needs_review"
    resumed = Production(production.id)
    assert (await resumed.get_project())["script_state"] == "needs_revision"
    assert "Invalid spoken decimal" in resumed.artifacts["script_revision"]
    assert "error" in await production.start_audio()
    assert production.artifacts["script_revision"]
    assert production.audio_task is None


async def test_accepted_render_cannot_be_overwritten(production, monkeypatch, reviewed_artifacts):
    production.artifacts.update(reviewed_artifacts)
    assert (await production.render_video("{}"))["accepted"]
    assert production.artifacts["video"] == "accepted.mp4"
    assert "render_count" not in production.artifacts
    monkeypatch.setattr(config, "VISION_MODEL", "a-different-reviewer")
    assert not production.accepted()
    assert (await production.get_project())["review_state"] == "needs_inspection"


def test_legacy_ready_without_av_report_is_not_accepted(production):
    store.update(production.id, status="ready", artifacts={"review": {"passed": True}})
    store.init()
    assert store.get_job(production.id)["status"] == "needs_review"


async def test_identical_failed_render_is_not_repeated(production, reviewed_artifacts):
    from brainrot.schemas import RenderPlan

    production.artifacts.update(reviewed_artifacts)
    production.artifacts.update(
        {
            "script_hash": "current",
            "audio_complete": "current",
            "visual_complete": "current",
            "video": "already-rendered.mp4",
            "render_plan": RenderPlan().model_dump(),
            "render_count": 1,
            "review": {
                "passed": False,
                "version": frame_review.VERSION,
                "model": config.VISION_MODEL,
                "video_sha256": "checked",
                "issues": ["Speech mismatch"],
            },
        }
    )
    result = await production.render_video("{}")
    assert "already rendered" in result["error"]
    assert result["issues"] == ["Speech mismatch"]
    assert production.artifacts["render_count"] == 1


@pytest.mark.parametrize(
    "report,key,value",
    [
        (name, key, value)
        for name in ("quality", "audio_review", "review")
        for key, value in (("version", 0), ("passed", False), ("video_sha256", "stale"))
    ]
    + [
        ("audio_review", "model", "old"),
        ("review", "model", "old"),
        (None, "audio_complete", "stale"),
        (None, "visual_complete", "stale"),
    ],
)
def test_startup_and_runtime_share_acceptance_policy(
    production, reviewed_artifacts, report, key, value
):
    production.artifacts.update(reviewed_artifacts)
    assert production.accepted()
    store.update(production.id, status="ready", artifacts=production.artifacts)
    store.init()
    assert store.get_job(production.id)["status"] == "ready"
    target = production.artifacts[report] if report else production.artifacts
    target[key] = value
    assert not production.accepted()
    store.update(production.id, status="ready", artifacts=production.artifacts)
    store.init()
    assert store.get_job(production.id)["status"] == "needs_review"


async def test_current_inspection_required_before_rerender(production):
    production.artifacts.update(
        {
            "video": "saved.mp4",
            "script_hash": "hash",
            "audio_complete": "hash",
            "visual_complete": "hash",
            "review": {"passed": False, "version": 1},
        }
    )
    assert (await production.get_project())["review_state"] == "needs_inspection"
    assert "inspection first" in (await production.render_video('{"image_seconds": 4.6}'))["error"]
    assert "render_count" not in production.artifacts
    assert "outdated" in (await production.finish_project("Done"))["error"]


@pytest.mark.parametrize("duration,similarity", [(30, 1), (15, 0.7)])
async def test_render_preflight_rejects_known_audio_defects_without_spending_attempts(
    production, duration, similarity
):
    production.artifacts.update(
        {
            "script_hash": "hash",
            "audio_complete": "hash",
            "visual_complete": "hash",
            "script": {"scenes": [{"id": "s1", "text": "Original words"}]},
            "audio": {
                "s1": {"duration": duration, "similarity": similarity, "transcript": "Actual words"}
            },
        }
    )
    result = await production.render_video("{}")
    assert "preflight failed" in result["error"]
    assert "render_count" not in production.artifacts
    assert bool(result["speech_mismatches"]) is (similarity < 0.9)


async def test_preflight_hands_script_repair_back_to_producer(production):
    from types import SimpleNamespace

    repair = {"error": "Wrong duration", "requires_script_revision": True}
    production.artifacts["review"] = {"passed": True, "summary": "Old report"}
    context = SimpleNamespace(
        agent_name="editor", actions=SimpleNamespace(skip_summarization=False), state={}
    )
    await production.after_tool(SimpleNamespace(name="render_video"), {}, context, repair)
    assert context.actions.skip_summarization
    response = await production.after_agent(context)
    assert json.loads(response.parts[0].text) == repair
    next_result = json.loads((await production.after_agent(context)).parts[0].text)
    assert next_result["blocked_agent"] == "editor"
    assert "requires_script_revision" not in next_result


def test_legacy_ready_without_audio_review_is_not_accepted(production):
    store.update(production.id, status="ready", artifacts={"quality": {"passed": True}})
    store.init()
    assert store.get_job(production.id)["status"] == "needs_review"


def test_legacy_ready_without_source_image_comparison_needs_review(production):
    store.update(
        production.id,
        status="ready",
        artifacts={
            "quality": {"passed": True},
            "audio_review": {"passed": True},
            "review": {"passed": True, "version": frame_review.VERSION - 1},
        },
    )
    store.init()
    assert store.get_job(production.id)["status"] == "needs_review"


def test_visual_review_uses_real_source_and_expected_overlay(isolated_data):
    Image.new("RGB", (24, 24), "red").save(isolated_data / "frame.jpg")
    Image.new("RGB", (24, 24), "blue").save(isolated_data / "source.png")
    content = frame_review.evidence(
        {"path": "frame.jpg", "image": "arbitrary-name.jpg", "caption": None},
        {"visual_caption": "An intentional fact label"},
        {
            "path": "source.png",
            "title": "Soyuz 28 at Salyut 6",
            "description": "Different mission",
            "source": "https://commons.wikimedia.org/wiki/File:example.jpg",
        },
        {"topic": "Salyut 7 rescue"},
    )
    images = [p for p in content if p["type"] == "image_url"]
    assert len(images) == 2 and images[0] != images[1]
    assert "An intentional fact label" in content[0]["text"]
    assert "Salyut 7 rescue" in content[0]["text"]
    assert "Soyuz 28 at Salyut 6" in content[0]["text"]
    assert "Different mission" in content[0]["text"]
    assert "https://commons.wikimedia.org/wiki/File:example.jpg" in content[0]["text"]
    assert len(frame_review.evidence({"path": "frame.jpg", "image": None}, {}, None)) == 2
    with pytest.raises(ValueError, match="no source image"):
        frame_review.evidence({"path": "frame.jpg", "image": "missing"}, {}, None)


@pytest.mark.parametrize(
    "role_name,tool_name,result",
    [
        ("editor", "inspect_video", {"passed": False, "issues": ["Replace an image"]}),
        ("editor", "inspect_video", {"passed": True, "issues": []}),
        ("researcher", "save_research", {"saved": True, "facts": ["Evidence"]}),
        ("writer", "save_script", {"saved": True, "script_hash": "abc"}),
        ("visual_producer", "complete_visuals", {"saved": True, "image_count": 3}),
    ],
)
async def test_adk_specialist_returns_completed_artifact_without_extra_model_calls(
    production, monkeypatch, role_name, tool_name, result
):
    from google.adk.agents import LlmAgent
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.adk.tools import AgentTool
    from google.genai import types

    calls = []

    async def chat(model, messages, role, **kwargs):
        calls.append(role)
        if calls == ["producer", role_name, "producer"]:
            assert next(iter(result)) in str(messages)
            return {"content": "Done"}
        assert calls in (["producer"], ["producer", role_name])
        name, args = (
            (role_name, {"request": "Complete the artifact"})
            if role == "producer"
            else (tool_name, {})
        )
        return {
            "tool_calls": [
                {"id": "call-" + role, "function": {"name": name, "arguments": json.dumps(args)}}
            ]
        }

    async def terminal_tool() -> dict:
        """Return a completed artifact."""
        if tool_name == "inspect_video":
            production.artifacts["review"] = result
        return result

    terminal_tool.__name__ = tool_name

    monkeypatch.setattr(production.gateway, "chat", chat)
    child = LlmAgent(
        name=role_name,
        model=production.model(role_name, "test"),
        tools=[terminal_tool],
        after_tool_callback=production.after_tool,
        after_agent_callback=production.after_agent,
    )
    parent = LlmAgent(
        name="producer",
        model=production.model("producer", "test"),
        tools=[AgentTool(agent=child)],
        after_tool_callback=production.after_tool,
    )
    sessions = InMemorySessionService()
    await sessions.create_session(app_name="test", user_id="u", session_id="s")
    async with Runner(app_name="test", agent=parent, session_service=sessions) as runner:
        events = [
            event
            async for event in runner.run_async(
                user_id="u",
                session_id="s",
                new_message=types.Content(role="user", parts=[types.Part(text="Test")]),
            )
        ]
    assert events[-1].content.parts[0].text == "Done"
    assert calls == ["producer", role_name, "producer"]


def test_audio_cache_key_changes_on_text_and_voice():
    assert digest({"text": "one", "voice": "a"}) != digest({"text": "two", "voice": "a"})
    assert digest({"text": "one", "voice": "a"}) != digest({"text": "one", "voice": "b"})


@pytest.mark.parametrize("failure_at", ["model", "tool"])
async def test_subagent_network_failure_is_not_hidden(production, monkeypatch, failure_at):
    from google.adk.agents import LlmAgent
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.adk.tools import AgentTool
    from google.genai import types

    async def network_tool() -> dict:
        """Simulate a failed network operation."""
        raise TimeoutError("Service timed out")

    async def chat(model, messages, role, **kwargs):
        if role == "researcher" and failure_at == "model":
            raise TimeoutError("Service timed out")
        if role == "producer" and any(m["role"] == "tool" for m in messages):
            return {"content": "The failure was hidden"}
        name, args = (
            ("researcher", {"request": "Research"}) if role == "producer" else ("network_tool", {})
        )
        return {
            "tool_calls": [{"id": role, "function": {"name": name, "arguments": json.dumps(args)}}]
        }

    monkeypatch.setattr(production.gateway, "chat", chat)
    child = LlmAgent(
        name="researcher",
        model=production.model("researcher", "test"),
        tools=[network_tool],
        before_tool_callback=production.before_tool,
        after_tool_callback=production.after_tool,
        after_agent_callback=production.after_agent,
    )
    parent = LlmAgent(
        name="producer", model=production.model("producer", "test"), tools=[AgentTool(agent=child)]
    )
    sessions = InMemorySessionService()
    await sessions.create_session(app_name="test", user_id="u", session_id="s")
    async with Runner(app_name="test", agent=parent, session_service=sessions) as runner:
        with pytest.raises(TimeoutError, match="Service timed out"):
            async for _ in runner.run_async(
                user_id="u",
                session_id="s",
                new_message=types.Content(role="user", parts=[types.Part(text="Test")]),
            ):
                pass


async def test_project_observation_is_compact_snapshot(production):
    production.artifacts.update(
        {
            "search_results": ["large raw search"],
            "script": {"title": "Old"},
            "script_hash": "hash",
            "audio_complete": "hash",
            "audio": {"s1": {"words": ["many"], "duration": 3}},
        }
    )
    observed = await production.get_project()
    production.artifacts["script"]["title"] = "New"
    assert observed["artifacts"]["script"]["title"] == "Old"
    assert "search_results" not in observed["artifacts"]
    assert "words" not in observed["artifacts"]["audio"]["s1"]
    assert "entries" not in observed["usage"]


async def test_image_search_limits_prevent_unbounded_network(production, monkeypatch):
    calls = []

    async def search(query):
        calls.append(query)
        return []

    monkeypatch.setattr(assets, "commons_search", search)
    production.artifacts["script"] = {"scenes": [{"id": "s1"}]}
    for _ in range(20):
        await production.find_images("s1", "books")
    assert len(calls) == 2


async def test_nested_tools_share_one_limit(production):
    from types import SimpleNamespace

    production.tool_calls = 99
    tool = SimpleNamespace(name="find_images")
    context = SimpleNamespace(agent_name="visual_producer")
    await production.before_tool(tool, {}, context)
    with pytest.raises(RuntimeError, match="Лимит действий"):
        await production.before_tool(tool, {}, context)


async def test_rejected_tool_result_is_visible_without_overriding(production):
    from types import SimpleNamespace

    result = await production.after_tool(
        SimpleNamespace(name="save_script"),
        {},
        SimpleNamespace(agent_name="writer"),
        {"error": "Too long"},
    )
    assert result is None
    event = store.events(production.id)[-1]
    assert event["kind"] == "validation" and event["detail"]["text"] == "Too long"


async def test_repeated_specialist_failure_hands_back_and_escalates_persistently(production):
    from types import SimpleNamespace

    production.agents()
    context = SimpleNamespace(
        agent_name="visual_producer", actions=SimpleNamespace(skip_summarization=False), state={}
    )
    tool = SimpleNamespace(name="find_images")
    error = {"error": "Search limit reached"}
    assert await production.after_tool(tool, {}, context, error) is None
    result = await production.after_tool(tool, {}, context, error)
    assert result["blocked_agent"] == "visual_producer"
    assert context.actions.skip_summarization
    assert production.specialist_agents["visual_producer"].model.model == config.ORCHESTRATOR_MODEL
    assert json.loads((await production.after_agent(context)).parts[0].text) == result
    resumed = Production(production.id)
    resumed.agents()
    assert resumed.specialist_agents["visual_producer"].model.model == config.ORCHESTRATOR_MODEL


async def test_saved_images_can_be_reinspected_without_search(
    production, isolated_data, monkeypatch
):
    Image.new("RGB", (24, 24), "blue").save(isolated_data / "candidate.png")
    production.candidates["img"] = {"id": "img", "path": "candidate.png", "title": "Subject"}
    production.artifacts["script"] = {"scenes": [{"id": "s1", "text": "An explanation"}]}
    calls = []

    async def chat(model, messages, purpose, **kwargs):
        calls.append(purpose)
        assert model == config.VISION_MODEL
        assert len(messages[0]["content"]) == 3
        return {"content": "img is useful"}

    monkeypatch.setattr(production.gateway, "chat", chat)
    result = await production.inspect_saved_images("s1", ["img"])
    assert result["inspection"] == "img is useful"
    assert await production.inspect_saved_images("s1", ["img"]) == result
    assert "error" in await production.inspect_saved_images("s1", ["unknown"])
    assert calls == ["visual_inspection"]
    assert production.image_searches == 0
    assert "image_inspections" not in (await production.get_project())["artifacts"]


async def test_stale_audio_duration_is_hidden(production):
    production.artifacts.update(
        {
            "script_hash": "new",
            "audio_complete": "old",
            "audio_duration": 70,
            "audio": {"s1": {"duration": 70}},
        }
    )
    observed = await production.get_project()
    assert observed["audio_state"] == "needs_generation"
    assert "audio_duration" not in observed["artifacts"]
    assert "audio" not in observed["artifacts"]


async def test_measured_voice_tempo_guides_length_without_fixed_speech_rate(production):
    production.artifacts.update(
        {
            "research": {"summary": "Evidence"},
            "script_hash": "hash",
            "audio_complete": "hash",
            "audio_duration": 10,
            "script": {"scenes": [{"id": "s1", "speaker_id": "n", "text": "word " * 40}]},
        }
    )
    project = await production.get_project()
    assert project["timing_guidance"]["target_words"] == 60
    assert project["timing_guidance"]["measured_words_per_second"] == 4
    await production.request_script_revision(
        "10 seconds of speech cannot fill the requested 15 seconds"
    )
    result = await production.save_script(
        json.dumps(
            {
                "title": "Expanded",
                "hook": "Hook",
                "scenes": [
                    {"id": "s1", "speaker_id": "n", "text": "word " * 30},
                    {"id": "s2", "speaker_id": "n", "text": "word " * 30},
                ],
            }
        )
    )
    assert result["saved"]
    assert "timing_guidance" not in await production.get_project()


async def test_timing_within_speed_range_does_not_require_rewrite(production):
    production.request["duration"] = 45
    production.artifacts.update(
        {"script_hash": "hash", "audio_complete": "hash", "audio_duration": 55.5, "audio": {}}
    )
    result = await production.await_audio()
    assert result["requires_script_revision"] is False
    assert result["recommended_speed"] == 1.233


@pytest.mark.parametrize("audio_duration,needs_rewrite", [(39, False), (44, True)])
async def test_duration_tolerance_matches_final_quality_gate(
    production, audio_duration, needs_rewrite
):
    production.request["duration"] = 30
    production.artifacts.update(
        {
            "script_hash": "hash",
            "audio_complete": "hash",
            "audio_duration": audio_duration,
            "audio": {"s1": {"duration": audio_duration, "similarity": 1}},
            "script": {"scenes": [{"id": "s1"}]},
        }
    )
    result = await production.await_audio()
    assert result["recommended_speed"] == 1.25
    assert result["requires_script_revision"] is needs_rewrite


async def test_resume_keeps_image_candidates_and_invalidates_old_alignment(production):
    candidate = {"id": "123", "title": "Saved image", "path": "image.png"}
    production.artifacts.update(
        {
            "script": {"scenes": [{"id": "s1", "speaker_id": "n", "text": "Hello"}]},
            "script_hash": "hash",
            "audio_complete": "hash",
            "audio": {"s1": {"alignment": "old"}},
            "visuals": {"s1": candidate},
            "video": "old.mp4",
            "review": {"passed": True},
            "audio_review": {"passed": True},
        }
    )
    production.persist()
    resumed = Production(production.id)
    assert "audio_complete" not in resumed.artifacts
    assert "video" not in resumed.artifacts
    assert "review" not in resumed.artifacts
    assert "audio_review" not in resumed.artifacts
    assert (await resumed.select_image("s1", "123", "Reuse"))["image"] == "Saved image"
    assert (await resumed.select_image("s1", "none", "Remove"))["image"] is None
    assert resumed.artifacts["visuals"]["s1"] is None
    resumed.artifacts["audio"]["s1"]["alignment"] = media.alignment_version()
    resumed.artifacts["audio"]["s1"]["hash"] = digest(
        {
            "text": "Hello",
            "speaker": resumed.speakers["n"],
            "language": "en",
        }
    )
    resumed.artifacts["audio_complete"] = "hash"
    resumed.persist()
    assert Production(production.id).artifacts["audio_complete"] == "hash"
    catalog = assets.catalog()
    catalog["speakers"][0]["voice"] = "new-voice"
    assets.save_catalog(catalog)
    assert "audio_complete" not in Production(production.id).artifacts
