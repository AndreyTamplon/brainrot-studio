import asyncio
import json
import logging
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, SecretStr
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import assets, config, media, store
from .schemas import JobRequest, Revision

logger = logging.getLogger("brainrot")
queue = asyncio.Queue()
active = {}
delayed = {}
RETRY_DELAYS = (15, 45)


def enqueue(job_id):
    previous = delayed.pop(job_id, None)
    if previous:
        previous.cancel()
    job = store.get_job(job_id)
    delay = max(0, job["artifacts"].get("retry_after", 0) - time.time())
    if not delay:
        queue.put_nowait(job_id)
        return

    async def later():
        try:
            await asyncio.sleep(delay)
            if store.get_job(job_id)["status"] == "queued":
                queue.put_nowait(job_id)
        finally:
            if delayed.get(job_id) is asyncio.current_task():
                delayed.pop(job_id, None)

    delayed[job_id] = asyncio.create_task(later())


async def billing_worker():
    from .provider import reconcile_charges

    while True:
        try:
            await reconcile_charges()
        except Exception as exc:  # noqa: BLE001 - billing must recover independently
            logger.warning("Billing reconciliation failed (%s)", type(exc).__name__)
        await asyncio.sleep(30)


async def worker():
    from .engine import produce
    from .provider import ProviderError

    while True:
        job_id = await queue.get()
        try:
            job = store.get_job(job_id)
            if job and job["status"] == "queued":
                task = asyncio.create_task(produce(job_id))
                active[job_id] = task
                await task
        except asyncio.CancelledError:
            stopping = asyncio.current_task().cancelling()
            status = store.get_job(job_id)["status"]
            if job_id in active and status not in {"ready", "needs_review", "failed", "cancelled"}:
                if stopping:
                    store.update(
                        job_id,
                        status="queued",
                        stage="recovering",
                        error=None,
                    )
                else:
                    store.update(job_id, status="cancelled", stage="cancelled")
            if stopping:
                raise
        except Exception as exc:  # noqa: BLE001 - isolate failures at the job boundary
            logger.error("Job %s failed (%s)", job_id, type(exc).__name__)
            transient = isinstance(exc, (TimeoutError, httpx.RequestError)) or (
                isinstance(exc, ProviderError) and exc.retryable
            )
            job = store.get_job(job_id)
            artifacts = job["artifacts"]
            retries = artifacts.get("recovery_attempts", 0)
            if transient and retries < len(RETRY_DELAYS):
                artifacts["recovery_attempts"] = retries + 1
                delay = RETRY_DELAYS[retries]
                artifacts["retry_after"] = time.time() + delay
                store.update(
                    job_id, artifacts=artifacts, status="queued", stage="retrying", error=None
                )
                store.event(
                    job_id,
                    "producer",
                    "retry_scheduled",
                    {
                        "text": "Внешний сервис прервал запрос. Продолжение с сохранённых этапов.",
                        "attempt": retries + 1,
                        "delay_seconds": delay,
                        "cause": type(exc).__name__,
                    },
                )
                enqueue(job_id)
                continue
            message = (
                "Внешний сервис недоступен после повторных попыток. Этапы сохранены; можно продолжить. "
                "Неопределённые списания остаются в резерве бюджета."
                if transient
                else str(exc)[:500] or type(exc).__name__
            )
            store.update(job_id, status="failed", error=message)
        finally:
            active.pop(job_id, None)
            queue.task_done()


@asynccontextmanager
async def lifespan(app):
    global queue
    with store.worker_lease():
        store.init()
        queue = asyncio.Queue()
        billing = asyncio.create_task(billing_worker())
        task = asyncio.create_task(worker())
        for job in store.queued_jobs():
            enqueue(job["id"])
        try:
            yield
        finally:
            task.cancel()
            billing.cancel()
            timers = list(delayed.values())
            for timer in timers:
                timer.cancel()
            await asyncio.gather(task, billing, *timers, return_exceptions=True)


app = FastAPI(title="Brainrot Studio", lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])


@app.middleware("http")
async def local_security(request: Request, call_next):
    origin = request.headers.get("origin")
    if request.method not in {"GET", "HEAD", "OPTIONS"} and origin:
        from urllib.parse import urlparse

        source = urlparse(origin)
        if source.hostname not in {"localhost", "127.0.0.1"}:
            return HTMLResponse("Cross-origin writes forbidden", status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    return response


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "configured": bool(config.api_key()),
    }


@app.get("/api/settings")
def settings():
    return {
        "has_key": bool(config.api_key()),
        "usage": store.usage(include_entries=False),
        "models": {
            "producer": config.ORCHESTRATOR_MODEL,
            "writer": config.WRITER_MODEL,
            "specialist": config.SPECIALIST_MODEL,
            "vision": config.VISION_MODEL,
            "audio_review": config.AUDIO_REVIEW_MODEL,
            "script_review": config.SCRIPT_REVIEW_MODEL,
            "tts": config.TTS_MODEL,
        },
        "max_run_budget": config.RUN_BUDGET,
    }


class KeyInput(BaseModel):
    key: SecretStr


@app.post("/api/settings/key")
async def set_key(body: KeyInput):
    key = body.key.get_secret_value()
    if not key.isascii() or not key.startswith("sk-or-") or any(c.isspace() for c in key):
        raise HTTPException(400, "Нужен полный ключ из кнопки Copy key, не скрытая строка")
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                "https://openrouter.ai/api/v1/key", headers={"Authorization": f"Bearer {key}"}
            )
    except httpx.RequestError as exc:
        raise HTTPException(502, "OpenRouter временно недоступен") from exc
    if not response.is_success:
        raise HTTPException(400, "OpenRouter не принял ключ")
    data = response.json().get("data", {})
    if data.get("limit") is None or data["limit"] > 10 or data.get("limit_reset"):
        raise HTTPException(400, "Нужен ключ с суммарным лимитом не выше $10, без сброса")
    try:
        config.save_key(key)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "limit": data.get("limit"), "remaining": data.get("limit_remaining")}


@app.get("/api/catalog")
async def get_catalog():
    catalog = assets.catalog()
    for background in catalog["backgrounds"]:
        if "duration" not in background:
            background["duration"] = (await media.probe(config.DATA / background["path"]))[
                "duration"
            ]
    return catalog


@app.get("/api/jobs")
def jobs(summary: bool = False):
    jobs = store.list_jobs()
    if not summary:
        return jobs
    return [
        {
            **{key: value for key, value in job.items() if key != "artifacts"},
            "title": job["artifacts"].get("script", {}).get("title") or job["request"]["topic"],
        }
        for job in jobs
    ]


def require_job(job_id):
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(404, "Ролик не найден")
    return job


async def validate_assets(body):
    bg = assets.get_asset("backgrounds", body.background_id)
    if not bg or not (config.DATA / bg["path"]).is_file():
        raise HTTPException(400, "Выберите доступный фон")
    if bg.get("retired"):
        raise HTTPException(400, "Этот фон снят с пресетов. Выберите запись геймплея.")
    info = await media.probe(config.DATA / bg["path"])
    if info["duration"] < body.duration:
        raise HTTPException(
            400,
            f"Фон длится {info['duration']:.1f} с, нужно {body.duration} с. "
            "Выберите более длинный фон или уменьшите длительность.",
        )
    for speaker_id in body.speaker_ids:
        speaker = assets.get_asset("speakers", speaker_id)
        if not speaker:
            raise HTTPException(400, "Рассказчик не найден")
        if body.language not in speaker.get("languages", ["ru", "en"]):
            raise HTTPException(400, "Этот голос недоступен для выбранного языка")
    if not config.api_key():
        raise HTTPException(400, "Добавьте ключ OpenRouter")


@app.post("/api/jobs", status_code=201)
async def new_job(
    body: JobRequest, idempotency_key: Annotated[str | None, Header(max_length=128)] = None
):
    await validate_assets(body)
    body.budget = min(body.budget, config.RUN_BUDGET)
    try:
        job_id = store.create_job(body.model_dump(), submission_key=idempotency_key)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    enqueue(job_id)
    return require_job(job_id)


@app.get("/api/jobs/{job_id}")
def job_detail(job_id: str):
    return {
        **require_job(job_id),
        "events": store.events(job_id),
        "usage": store.usage(job_id, include_entries=False),
    }


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    job = require_job(job_id)
    if job["status"] not in {"queued", "running"}:
        raise HTTPException(409, "Задание уже завершено")
    store.update(job_id, status="cancelled", stage="cancelled")
    timer = delayed.pop(job_id, None)
    if timer:
        timer.cancel()
    if job_id in active:
        active[job_id].cancel()
    return {"ok": True}


@app.post("/api/jobs/{job_id}/resume")
async def resume_job(job_id: str):
    job = require_job(job_id)
    if job_id in active:
        raise HTTPException(409, "Остановка ещё выполняется. Повторите через несколько секунд.")
    if job["status"] not in {"failed", "interrupted", "cancelled", "needs_review"}:
        raise HTTPException(409, "Это задание нельзя продолжить")
    store.update(job_id, status="queued", stage="queued", error=None)
    enqueue(job_id)
    return {"ok": True}


@app.post("/api/jobs/{job_id}/revisions", status_code=201)
async def revision(
    job_id: str,
    body: Revision,
    idempotency_key: Annotated[str | None, Header(max_length=128)] = None,
):
    parent = require_job(job_id)
    if parent["status"] in {"queued", "running"} or job_id in active:
        raise HTTPException(409, "Дождитесь завершения текущего задания")
    request = {**parent["request"], "revision": body.instructions}
    if body.subtitles is not None:
        request["subtitles"] = body.subtitles
    if body.background_id:
        request["background_id"] = body.background_id
    await validate_assets(JobRequest.model_validate(request))
    inherited = {
        k: v
        for k, v in parent["artifacts"].items()
        if k
        not in {
            "video",
            "review",
            "frames",
            "technical",
            "final",
            "render_count",
            "quality",
            "timeline",
            "frame_reviews",
            "review_failures",
            "audio_review",
            "recovery_attempts",
            "retry_after",
            "revision_plan",
            "script_revision",
        }
    }
    try:
        new_id = store.create_job(request, job_id, inherited, submission_key=idempotency_key)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    enqueue(new_id)
    return require_job(new_id)


@app.get("/api/jobs/{job_id}/events")
async def events_stream(job_id: str, request: Request, after: int = 0):
    require_job(job_id)

    async def stream():
        cursor = after
        while not await request.is_disconnected():
            for event in store.events(job_id, cursor):
                cursor = event["id"]
                yield f"id: {cursor}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
            job = require_job(job_id)
            if job["status"] not in {"queued", "running"}:
                yield "event: done\ndata: {}\n\n"
                break
            yield ": keepalive\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
    )


@app.get("/api/jobs/{job_id}/download")
def download(job_id: str):
    job = require_job(job_id)
    video = job["artifacts"].get("video")
    if not video:
        raise HTTPException(404, "Видео ещё не готово")
    return FileResponse(assets.local_path(video), filename=f"brainrot-{job_id}.mp4")


@app.get("/api/jobs/{job_id}/quality")
def quality_report(job_id: str):
    job = require_job(job_id)
    artifacts = job["artifacts"]
    if not artifacts.get("quality"):
        raise HTTPException(404, "Проверка ещё не выполнена")
    from fastapi.responses import JSONResponse

    background = assets.get_asset("backgrounds", job["request"]["background_id"])
    return JSONResponse(
        {
            "av": artifacts["quality"],
            "audio": artifacts.get("audio_review"),
            "frames": artifacts.get("frame_reviews", []),
            "technical": artifacts.get("technical"),
            "credits": {
                "background": {
                    k: v for k, v in background.items() if k not in {"path", "thumbnail"}
                },
                "images": {
                    scene: {
                        k: value[k] for k in ("title", "source", "artist", "license") if k in value
                    }
                    for scene, value in artifacts.get("visuals", {}).items()
                    if value
                },
                "research": artifacts.get("research", {}).get("sources", []),
            },
        },
        headers={"Content-Disposition": f'attachment; filename="quality-{job_id}.json"'},
    )


@app.post("/api/uploads")
async def upload(
    file: Annotated[UploadFile, File()],
    kind: Annotated[str, Form()],
    name: Annotated[str, Form()] = "",
):
    if kind not in {"background", "portrait", "voice"}:
        raise HTTPException(400, "Неизвестный тип файла")
    limits = {"background": 250_000_000, "portrait": 12_000_000, "voice": 10_000_000}
    suffixes = {
        "background": {".mp4", ".mov", ".webm"},
        "portrait": {".png", ".jpg", ".jpeg", ".webp"},
        "voice": {".wav", ".mp3", ".m4a", ".ogg"},
    }
    from pathlib import Path

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in suffixes[kind]:
        raise HTTPException(400, "Неподдерживаемый формат")
    asset_id = uuid.uuid4().hex[:12]
    relative = f"media/upload-{asset_id}{suffix}"
    path = config.DATA / relative
    size = 0
    try:
        with path.open("wb") as target:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > limits[kind]:
                    raise ValueError("Файл слишком большой")
                target.write(chunk)
        from .media import probe, thumbnail

        if kind == "portrait":
            from PIL import Image

            with Image.open(path) as image:
                if image.width * image.height > 40_000_000:
                    raise ValueError("Изображение превышает 40 мегапикселей")
                image.verify()
        else:
            info = await probe(path)
            if kind == "voice" and (not info["has_audio"] or not 3 <= info["duration"] <= 45):
                raise ValueError("Образец голоса: от 3 до 45 секунд с аудиодорожкой")
            if kind == "background" and not info["has_video"]:
                raise ValueError("В файле нет видео")
    except Exception as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(400, str(exc)[:200]) from exc
    if kind == "background":
        thumb = path.with_suffix(".jpg")
        await thumbnail(path, thumb)
        data = assets.catalog()
        data["backgrounds"].append(
            {
                "id": asset_id,
                "name": name or "Мой фон",
                "path": relative,
                "thumbnail": assets.public_url(str(thumb.relative_to(config.DATA))),
                "source": "User upload",
                "license": "User supplied",
            }
        )
        assets.save_catalog(data)
    return {"id": asset_id, "path": relative, "url": assets.public_url(relative)}


class SpeakerInput(BaseModel):
    name: str
    personality: str = ""
    portrait: str = ""
    voice_reference: str = ""
    reference_text: str = ""
    voice: str = "Puck"


@app.post("/api/speakers")
def add_speaker(body: SpeakerInput):
    if not 1 <= len(body.name) <= 60 or len(body.personality) > 800:
        raise HTTPException(400, "Проверьте имя и описание")
    for path, suffixes in (
        (body.portrait, {".png", ".jpg", ".jpeg", ".webp"}),
        (body.voice_reference, {".mp3", ".wav", ".m4a", ".ogg"}),
    ):
        if path:
            try:
                if assets.local_path(path).suffix.lower() not in suffixes:
                    raise ValueError("Неподходящий формат медиафайла")
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
    if body.voice not in {"Puck", "Charon", "Kore", "Fenrir", "Leda", "Aoede"}:
        raise HTTPException(400, "Неизвестный стандартный голос")
    speaker = {
        **body.model_dump(),
        "id": uuid.uuid4().hex[:12],
        "tts_model": config.TTS_MODEL
        if body.voice_reference
        else "google/gemini-3.8-flash-lite-tts",
        "source": "User supplied",
    }
    data = assets.catalog()
    data["speakers"].append(speaker)
    assets.save_catalog(data)
    return speaker


@app.get("/media/{path:path}")
def media_file(path: str):
    try:
        file_path = assets.local_path(path)
    except ValueError as exc:
        raise HTTPException(404, "Файл не найден") from exc
    if file_path.suffix.lower() not in {
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".mp4",
        ".mov",
        ".webm",
        ".mp3",
        ".wav",
        ".m4a",
        ".ogg",
        ".srt",
    }:
        raise HTTPException(404, "Файл не найден")
    return FileResponse(file_path)


dist = config.ROOT / "frontend" / "dist"
if dist.exists():
    app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
else:

    @app.get("/", response_class=HTMLResponse)
    def setup():
        return """<!doctype html><html lang="ru"><meta charset="utf-8"><title>Brainrot Studio</title>
        <body><h1>Brainrot Studio</h1><form id="keyform"><label>OpenRouter API key
        <input name="key" type="password" autocomplete="off" required></label>
        <button>Сохранить ключ</button></form><p id="result"></p>
        <script>document.querySelector('form').onsubmit=async e=>{e.preventDefault();
        const input=document.querySelector('input');const r=await fetch('/api/settings/key',
        {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key:input.value})});
        const data=await r.json();input.value='';document.querySelector('#result').textContent=
        r.ok?'Ключ сохранён. Лимит: $'+data.limit:data.detail;};</script></body></html>"""
