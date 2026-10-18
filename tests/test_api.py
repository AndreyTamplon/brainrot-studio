import asyncio
import importlib
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from brainrot import assets, config, media, store
from brainrot.app import app


@pytest.fixture
def client(isolated_data, monkeypatch):
    async def probe(_):
        return {"duration": 120}

    monkeypatch.setattr(media, "probe", probe)
    monkeypatch.setattr(config, "api_key", lambda: "test-key-not-returned")
    (isolated_data / "media" / "background.mp4").write_bytes(b"fixture")
    assets.save_catalog(
        {
            "backgrounds": [{"id": "bg", "path": "media/background.mp4"}],
            "speakers": [{"id": "narrator", "name": "Narrator"}],
        }
    )
    # No lifespan: queue stays idle, so API tests cannot make paid model calls.
    return TestClient(app)


def brief(**changes):
    return {
        "topic": "Why is the sky blue?",
        "background_id": "bg",
        "speaker_ids": ["narrator"],
        **changes,
    }


def test_short_background_rejected_before_spending(client, monkeypatch):
    async def probe(_):
        return {"duration": 16}

    monkeypatch.setattr(media, "probe", probe)
    response = client.post("/api/jobs", json=brief(duration=30))
    assert response.status_code == 400
    assert "16.0" in response.json()["detail"]
    assert store.list_jobs() == []


async def test_shutdown_preserves_pending_queue(monkeypatch):
    from brainrot import engine

    module = importlib.import_module("brainrot.app")
    pending = asyncio.Queue()
    monkeypatch.setattr(module, "queue", pending)
    monkeypatch.setattr(module, "active", {})
    first, second = store.create_job(brief()), store.create_job(brief())
    await pending.put(first)
    await pending.put(second)
    started = asyncio.Event()

    async def produce(job_id):
        store.update(job_id, status="running")
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(engine, "produce", produce)
    worker = asyncio.create_task(module.worker())
    await started.wait()
    worker.cancel()
    await asyncio.gather(worker, return_exceptions=True)
    assert store.get_job(first)["status"] == "queued"
    assert store.get_job(first)["stage"] == "recovering"
    assert store.get_job(second)["status"] == "queued"
    assert pending.qsize() == 1


@pytest.mark.parametrize("status", ["ready", "needs_review", "failed", "cancelled"])
async def test_shutdown_does_not_resurrect_terminal_job(monkeypatch, status):
    from brainrot import engine

    module = importlib.import_module("brainrot.app")
    pending = asyncio.Queue()
    monkeypatch.setattr(module, "queue", pending)
    monkeypatch.setattr(module, "active", {})
    job_id = store.create_job(brief())
    await pending.put(job_id)
    started = asyncio.Event()

    async def produce(job):
        store.update(job, status="running")
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(engine, "produce", produce)
    worker = asyncio.create_task(module.worker())
    await started.wait()
    store.update(job_id, status=status, stage=status)
    worker.cancel()
    await asyncio.gather(worker, return_exceptions=True)
    assert store.get_job(job_id)["status"] == status
    assert store.get_job(job_id)["stage"] == status


@pytest.mark.parametrize("failure", ["validation", "network", "provider"])
async def test_worker_recovery_is_bounded_and_keeps_artifacts(monkeypatch, failure):
    from brainrot import engine
    from brainrot.provider import ProviderError

    module = importlib.import_module("brainrot.app")
    pending = asyncio.Queue()
    monkeypatch.setattr(module, "queue", pending)
    monkeypatch.setattr(module, "active", {})
    monkeypatch.setattr(module, "RETRY_DELAYS", (0, 0))
    job_id = store.create_job(brief())
    charge = store.reserve(job_id, "test", "unknown_request", 0.15, 1.5)
    store.settle(charge, uncertain=True)
    calls = []
    transient = failure != "validation"

    async def produce(job):
        calls.append(job)
        artifacts = store.get_job(job)["artifacts"]
        artifacts["saved_audio"] = "keep-this.mp3"
        store.update(job, status="running", artifacts=artifacts)
        if failure == "provider":
            raise ProviderError("HTTP 503", retryable=True)
        raise TimeoutError() if transient else ValueError("Invalid media")

    monkeypatch.setattr(engine, "produce", produce)
    await pending.put(job_id)
    worker = asyncio.create_task(module.worker())
    await asyncio.wait_for(pending.join(), timeout=2)
    worker.cancel()
    await asyncio.gather(worker, return_exceptions=True)
    job = store.get_job(job_id)
    assert job["status"] == "failed"
    assert len(calls) == (3 if transient else 1)
    assert job["artifacts"]["saved_audio"] == "keep-this.mp3"
    assert job["artifacts"].get("recovery_attempts", 0) == (2 if transient else 0)
    assert store.usage(job_id)["held"] == pytest.approx(0.15)


def test_retired_background_rejected_before_spending(client):
    catalog = assets.catalog()
    catalog["backgrounds"][0]["retired"] = True
    assets.save_catalog(catalog)
    response = client.post("/api/jobs", json=brief())
    assert response.status_code == 400
    assert store.list_jobs() == []


def test_english_character_voice_cannot_be_used_for_russian(client):
    catalog = assets.catalog()
    catalog["speakers"][0]["languages"] = ["en"]
    assets.save_catalog(catalog)
    assert client.post("/api/jobs", json=brief(language="ru")).status_code == 400
    assert store.list_jobs() == []


def test_resume_waits_for_cancellation_cleanup(client, monkeypatch):
    import importlib

    module = importlib.import_module("brainrot.app")
    job = client.post("/api/jobs", json=brief()).json()
    store.update(job["id"], status="cancelled")
    monkeypatch.setitem(module.active, job["id"], object())
    assert client.post(f"/api/jobs/{job['id']}/resume").status_code == 409
    assert (
        client.post(f"/api/jobs/{job['id']}/revisions", json={"instructions": "Revise"}).status_code
        == 409
    )


def test_job_cancel_resume_and_revision(client):
    response = client.post("/api/jobs", json=brief())
    assert response.status_code == 201
    job = response.json()
    assert job["request"]["subtitles"] is True
    assert client.post(f"/api/jobs/{job['id']}/cancel").status_code == 200
    assert client.post(f"/api/jobs/{job['id']}/resume").status_code == 200
    assert client.post(f"/api/jobs/{job['id']}/resume").status_code == 409
    store.update(
        job["id"],
        status="ready",
        artifacts={
            "audio": {"s1": "cached"},
            "video": "old.mp4",
            "review": {"passed": True},
            "render_count": 2,
        },
    )
    child = client.post(
        f"/api/jobs/{job['id']}/revisions",
        json={"instructions": "Remove subtitles", "subtitles": False},
    ).json()
    assert child["parent_id"] == job["id"]
    assert child["request"]["subtitles"] is False
    assert child["artifacts"] == {"audio": {"s1": "cached"}}


def test_api_validation_and_secret_boundary(client, isolated_data):
    assert client.post("/api/jobs", json=brief(background_id="missing")).status_code == 400
    assert client.post("/api/jobs", json=brief(speaker_ids=[])).status_code == 422
    assert client.get("/api/jobs/missing").status_code == 404
    assert "test-key" not in client.get("/api/settings").text
    (isolated_data / "media" / "secret.env").write_text("secret")
    assert client.get("/media/media/secret.env").status_code == 404
    assert client.get("/media/studio.sqlite").status_code == 404
    assert (
        client.post(
            "/api/jobs", json=brief(), headers={"Origin": "https://malicious.example"}
        ).status_code
        == 403
    )
    assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 400
    assert (
        client.post("/api/speakers", json={"name": "X", "portrait": "../../.env"}).status_code
        == 400
    )
    assert (
        client.post(
            "/api/speakers", json={"name": "X", "voice_reference": "studio.sqlite"}
        ).status_code
        == 400
    )


def test_quality_download_includes_audio_and_attribution(client):
    job = client.post("/api/jobs", json=brief()).json()
    store.update(
        job["id"],
        artifacts={
            "quality": {"passed": True},
            "audio_review": {"passed": True},
            "visuals": {
                "s1": {
                    "source": "https://commons.wikimedia.org/test",
                    "license": "CC BY 4.0",
                    "path": "private-local-path",
                }
            },
        },
    )
    result = client.get(f"/api/jobs/{job['id']}/quality")
    assert result.status_code == 200
    assert result.json()["audio"]["passed"]
    assert result.json()["credits"]["background"]["id"] == "bg"
    assert result.json()["credits"]["images"]["s1"]["license"] == "CC BY 4.0"
    assert "private-local-path" not in result.text


def test_history_and_settings_have_compact_responses(client):
    job = client.post("/api/jobs", json=brief()).json()
    store.update(
        job["id"],
        artifacts={"script": {"title": "Generated title"}, "search_results": ["x" * 10000]},
    )
    summary = client.get("/api/jobs?summary=true")
    assert len(summary.content) < 1500
    assert summary.json()[0]["title"] == "Generated title"
    assert "artifacts" not in summary.json()[0]
    assert client.get(f"/api/jobs/{job['id']}").json()["artifacts"]["search_results"]
    assert "entries" not in client.get("/api/settings").json()["usage"]


def test_retried_submission_does_not_duplicate_paid_work(client):
    headers = {"Idempotency-Key": "same-network-request"}
    first = client.post("/api/jobs", json=brief(), headers=headers)
    second = client.post("/api/jobs", json=brief(), headers=headers)
    assert first.json()["id"] == second.json()["id"]
    assert len(store.list_jobs()) == 1
    assert (
        client.post("/api/jobs", json=brief(topic="Different topic"), headers=headers).status_code
        == 409
    )
    store.update(first.json()["id"], status="ready")
    assert client.post("/api/jobs", json=brief(), headers=headers).json()["status"] == "ready"
    revision_headers = {"Idempotency-Key": "same-revision-request"}
    url = f"/api/jobs/{first.json()['id']}/revisions"
    one = client.post(
        url, json={"instructions": "Remove subtitles", "subtitles": False}, headers=revision_headers
    )
    two = client.post(
        url, json={"instructions": "Remove subtitles", "subtitles": False}, headers=revision_headers
    )
    assert one.json()["id"] == two.json()["id"]
    assert len(store.list_jobs()) == 2


def test_portrait_upload_and_custom_speaker(client):
    raw = io.BytesIO()
    Image.new("RGB", (40, 40), "green").save(raw, format="PNG")
    upload = client.post(
        "/api/uploads",
        data={"kind": "portrait"},
        files={"file": ("portrait.png", raw.getvalue(), "image/png")},
    )
    assert upload.status_code == 200
    response = client.post(
        "/api/speakers",
        json={"name": "Рассказчик", "portrait": upload.json()["path"], "voice": "Puck"},
    )
    assert response.status_code == 200
    assert response.json()["tts_model"] == "google/gemini-3.8-flash-lite-tts"
    assert (
        client.post(
            "/api/uploads",
            data={"kind": "portrait"},
            files={"file": ("broken.png", b"not an image")},
        ).status_code
        == 400
    )
