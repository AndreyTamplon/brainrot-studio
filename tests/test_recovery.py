import asyncio
import importlib
import json

import httpx
import pytest

from brainrot import assets, config, engine, store
from brainrot.engine import Production
from brainrot.provider import reconcile_charges


def make_production(revision=""):
    assets.save_catalog({"backgrounds": [], "speakers": [{"id": "n", "name": "Narrator"}]})
    return Production(
        store.create_job(
            {
                "topic": "A new topic",
                "speaker_ids": ["n"],
                "language": "en",
                "duration": 15,
                "budget": 1,
                "subtitles": True,
                "revision": revision,
            }
        )
    )


def script(word="hello"):
    return {
        "title": "Title",
        "hook": "Hook",
        "scenes": [
            {"id": "s1", "speaker_id": "n", "text": f"{word} " * 15},
            {"id": "s2", "speaker_id": "n", "text": "world " * 15},
        ],
    }


async def test_resume_protects_script_and_explicit_repair_survives_restart():
    p = make_production()
    p.artifacts["research"] = {"summary": "Evidence"}
    assert (await p.save_script(json.dumps(script())))["saved"]
    p = Production(p.id)
    assert (await p.get_project())["script_state"] == "ready"
    assert "error" in await p.save_script(json.dumps(script("changed")))
    assert p.writes == 0
    await p.request_script_revision("Replace the fact contradicted by the source")
    p = Production(p.id)
    assert (await p.get_project())["script_state"] == "needs_revision"
    assert "error" in await p.start_audio()
    assert (await p.save_script(json.dumps(script("changed"))))["saved"]
    assert (await p.get_project())["script_state"] == "ready"


async def test_revision_plan_is_durable_and_editing_preserves_expensive_artifacts():
    p = make_production("Remove subtitles")
    p.artifacts["research"] = {"summary": "Evidence"}
    await p.save_script(json.dumps(script()))
    assert (await p.get_project())["revision_state"] == "needs_plan"
    assert "error" in await p.render_video("{}")
    before = json.loads(store.dumps(p.artifacts))
    await p.plan_revision(["editing"], "Only subtitles changed")
    p = Production(p.id)
    assert (await p.plan_revision(["script"], "Accidental duplicate"))["stages"] == ["editing"]
    assert p.artifacts["script"] == before["script"]
    assert "error" in await p.save_script(json.dumps(script("changed")))


async def test_revision_dependencies_cannot_be_skipped_or_reapplied():
    p = make_production("Change the explanation")
    p.artifacts["research"] = {"summary": "Evidence"}
    await p.save_script(json.dumps(script()))
    await p.plan_revision(["script"], "User asks for a different explanation")
    assert set(p.revision_pending()) == {"script", "visuals"}
    assert "error" in await p.start_audio()
    await p.save_script(json.dumps(script("new")))
    p = Production(p.id)
    assert p.revision_pending() == ["visuals"]
    assert "error" in await p.render_video("{}")
    await p.select_image("s1", "none", "No relevant image")
    await p.select_image("s2", "none", "No relevant image")
    await p.complete_visuals()
    assert Production(p.id).revision_pending() == []


async def test_reconciliation_backoff_does_not_starve_later_records(monkeypatch):
    monkeypatch.setattr(config, "api_key", lambda: "test-key")
    monkeypatch.setattr(store.time, "time", lambda: 1000)
    charges = [store.reserve("test", "m", "test", 0.01, 1) for _ in range(20)]
    for index, charge in enumerate(charges):
        store.settle(charge, request_id=f"gen-{index}")
    monkeypatch.setattr(store.time, "time", lambda: 1020)
    seen = []

    def handler(request):
        rid = request.url.params["id"]
        seen.append(rid)
        return (
            httpx.Response(200, json={"data": {"total_cost": 0.001}})
            if int(rid[4:]) >= 16
            else httpx.Response(404)
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )
    await reconcile_charges()
    await reconcile_charges()
    await reconcile_charges()
    assert len(seen) == 20
    assert store.usage()["held"] == pytest.approx(0.16)
    assert store.usage()["spent"] == pytest.approx(0.004)
    assert store.claim_charge_rechecks() == []
    monkeypatch.setattr(store.time, "time", lambda: 1051)
    assert len(store.claim_charge_rechecks()) == 16


async def test_delayed_retry_does_not_block_other_jobs_and_cancel_prevents_retry(monkeypatch):
    module = importlib.import_module("brainrot.app")
    monkeypatch.setattr(module, "queue", asyncio.Queue())
    monkeypatch.setattr(module, "active", {})
    monkeypatch.setattr(module, "delayed", {})
    monkeypatch.setattr(module, "RETRY_DELAYS", (60,))
    first, second = store.create_job({}), store.create_job({})
    calls = []
    done = asyncio.Event()

    async def produce(job_id):
        calls.append(job_id)
        if job_id == first:
            raise TimeoutError()
        store.update(job_id, status="ready")
        done.set()

    monkeypatch.setattr(engine, "produce", produce)
    module.enqueue(first)
    module.enqueue(second)
    worker = asyncio.create_task(module.worker())
    try:
        await asyncio.wait_for(done.wait(), 1)
        assert calls == [first, second]
        assert first in module.delayed
        assert store.get_job(first)["artifacts"]["retry_after"] > 0
        timer = module.delayed[first]
        await module.cancel_job(first)
        await asyncio.gather(timer, return_exceptions=True)
        assert first not in module.delayed
        assert store.get_job(first)["status"] == "cancelled"
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


def test_startup_recovers_all_queued_jobs_beyond_ui_history_limit():
    first = store.create_job({})
    store.update(first, status="running", artifacts={"checkpoint": "keep"})
    cancelled = store.create_job({})
    store.update(cancelled, status="cancelled")
    for _ in range(105):
        store.create_job({})
    store.init()
    assert len(store.list_jobs()) == 100
    assert len(store.queued_jobs()) == 106
    assert store.queued_jobs()[0]["id"] == first
    assert store.get_job(first)["artifacts"]["checkpoint"] == "keep"
    assert store.get_job(cancelled)["status"] == "cancelled"


@pytest.mark.parametrize("metadata", ["{broken", '{"hash":"wrong"}', "[]"])
async def test_corrupt_speech_metadata_recovers_without_another_paid_call(monkeypatch, metadata):
    p = make_production()
    p.artifacts["research"] = {"summary": "Evidence"}
    await p.save_script(json.dumps(script()))
    for scene in p.artifacts["script"]["scenes"]:
        fingerprint = engine.digest(
            {
                "text": scene["text"],
                "speaker": p.speakers["n"],
                "language": "en",
            }
        )
        path = config.DATA / "cache" / f"speech-{fingerprint}.mp3"
        path.write_bytes(b"complete audio")
        path.with_suffix(".json").write_text(metadata)

    async def no_payment(*args):
        pytest.fail("Existing complete audio must not be purchased again")

    async def probe(path):
        return {"duration": 7.5}

    monkeypatch.setattr(p.gateway, "speech", no_payment)
    monkeypatch.setattr(engine.media, "probe", probe)
    monkeypatch.setattr(
        engine.media,
        "transcribe",
        lambda *args: {
            "words": [{"word": "hello", "start": 0, "end": 1}],
            "asr_words": [],
            "similarity": 1,
            "alignment": engine.media.alignment_version(),
        },
    )
    await p.make_audio()
    assert p.artifacts["audio_complete"] == p.artifacts["script_hash"]
    assert p.artifacts["audio_duration"] == 15
    assert store.usage(p.id)["calls"] == 0
    assert not list((config.DATA / "cache").glob("*.tmp"))


async def test_media_timeout_kills_a_process_that_ignores_termination():
    import os
    import sys

    marker = config.DATA / "pid"
    command = (
        "import os,signal,time; from pathlib import Path; "
        "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        f"Path({str(marker)!r}).write_text(str(os.getpid())); time.sleep(60)"
    )
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(engine.media.command(sys.executable, "-c", command, timeout=0.5), 5)
    with pytest.raises(ProcessLookupError):
        os.kill(int(marker.read_text()), 0)


def test_second_worker_cannot_recover_another_workers_jobs():
    job = store.create_job({})
    store.update(job, status="running")
    with store.worker_lease():
        with pytest.raises(RuntimeError, match="уже запущен"), store.worker_lease():
            store.init()
        assert store.get_job(job)["status"] == "running"
        store.init(recover=False)
        assert store.get_job(job)["status"] == "running"
    with store.worker_lease():
        store.init()
        assert store.get_job(job)["status"] == "queued"


async def test_real_lifespan_recovers_checkpoint_after_shutdown(monkeypatch):
    module = importlib.import_module("brainrot.app")
    monkeypatch.setattr(module, "active", {})
    monkeypatch.setattr(module, "delayed", {})
    monkeypatch.setattr(config, "api_key", lambda: "")
    job = store.create_job({})
    started = asyncio.Event()
    finished = asyncio.Event()
    calls = []

    async def produce(job_id):
        calls.append(job_id)
        saved = store.get_job(job_id)["artifacts"]
        if saved.get("checkpoint"):
            store.update(job_id, status="ready")
            finished.set()
            return
        store.update(job_id, status="running", artifacts={"checkpoint": "audio-complete"})
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(engine, "produce", produce)
    async with module.lifespan(module.app):
        await asyncio.wait_for(started.wait(), 1)
    assert store.get_job(job)["status"] == "queued"
    async with module.lifespan(module.app):
        await asyncio.wait_for(finished.wait(), 1)
    assert calls == [job, job]
    assert store.get_job(job)["status"] == "ready"
    assert store.get_job(job)["artifacts"]["checkpoint"] == "audio-complete"


async def test_misrouted_delegations_are_rejected_before_paying_a_specialist():
    from types import SimpleNamespace

    p = make_production()
    p.artifacts["research"] = {"summary": "Evidence"}
    await p.save_script(json.dumps(script()))
    context = SimpleNamespace(agent_name="producer")
    assert "error" in await p.before_tool(SimpleNamespace(name="writer"), {}, context)
    result = await p.before_tool(SimpleNamespace(name="editor"), {}, context)
    assert result["missing"] == ["audio", "visual"]
    await p.request_script_revision("A new material finding")
    assert await p.before_tool(SimpleNamespace(name="writer"), {}, context) is None
    assert store.usage(p.id)["calls"] == 0


@pytest.mark.parametrize("user_cancelled", [False, True])
async def test_real_produce_wrapper_leaves_cancellation_status_to_queue(
    monkeypatch, user_cancelled
):
    import asyncio
    import importlib

    module = importlib.import_module("brainrot.app")
    p = make_production()
    started = asyncio.Event()

    async def run(self):
        store.update(self.id, status="running")
        started.set()
        await asyncio.Event().wait()

    async def billing():
        await asyncio.Event().wait()

    monkeypatch.setattr(Production, "run", run)
    monkeypatch.setattr(module, "billing_worker", billing)
    async with module.lifespan(module.app):
        await asyncio.wait_for(started.wait(), 1)
        if user_cancelled:
            await module.cancel_job(p.id)
    assert store.get_job(p.id)["status"] == ("cancelled" if user_cancelled else "queued")
    assert not module.active


async def test_batch_visual_choices_validate_before_any_mutation():
    p = make_production()
    p.artifacts["research"] = {"summary": "Evidence"}
    await p.save_script(json.dumps(script()))
    p.candidates["image"] = {"id": "image", "title": "A real candidate"}
    choices = [
        {"scene_id": "s1", "candidate_id": "image", "reason": "Relevant"},
        {"scene_id": "s2", "candidate_id": "missing", "reason": "Invalid"},
    ]
    assert "error" in await p.select_images(choices)
    assert not p.artifacts.get("visuals")
    choices[1]["candidate_id"] = "none"
    assert (await p.select_images(choices))["saved"]
    assert (await p.complete_visuals())["image_count"] == 1


@pytest.mark.parametrize("change_visual_intent", [True, False])
@pytest.mark.parametrize("rejected_visuals", [True, False])
async def test_speech_repairs_reuse_only_an_unchanged_confirmed_storyboard(
    change_visual_intent, rejected_visuals
):
    p = make_production()
    p.artifacts["research"] = {"summary": "Evidence"}
    await p.save_script(json.dumps(script()))
    await p.select_images(
        [{"scene_id": sid, "candidate_id": "none", "reason": "No insert"} for sid in ("s1", "s2")]
    )
    await p.complete_visuals()
    if rejected_visuals:
        p.artifacts.pop("visual_complete")
        p.artifacts["visual_revision"] = ["s1: Picture shows a different spacecraft"]
    await p.request_script_revision("Shorten a spoken phrase")
    new = script("different")
    if change_visual_intent:
        new["scenes"][0]["visual_query"] = "A different visual subject"
    await p.save_script(json.dumps(new))
    assert (
        p.artifacts.get("visual_complete") == p.artifacts["script_hash"]
    ) is (not change_visual_intent and not rejected_visuals)
    assert "audio_complete" not in p.artifacts
    if rejected_visuals:
        assert p.artifacts["visual_revision"]
        p.persist()
        resumed = Production(p.id)
        assert (await resumed.get_project())["visual_state"] == "needs_confirmation"
        assert resumed.artifacts["visual_revision"]
        await resumed.complete_visuals()
        assert "visual_revision" not in resumed.artifacts
