"""Bounded perceptual screening of the actual encoded soundtrack, not an ASR score."""

import base64
import hashlib
from pathlib import Path

from pydantic import BaseModel, Field

from . import config, media
from .provider import extract_json
from .review_policy import AUDIO_VERSION as VERSION


class AudibleIssue(BaseModel):
    time: float = Field(ge=0)
    description: str


class AudioReview(BaseModel):
    passed: bool
    transcript: str
    summary: str
    issues: list[AudibleIssue] = []


async def review(gateway, video: Path, language: str, expected: str):
    audio = video.with_name("review-audio.mp3")
    await media.command(
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-i",
        video,
        "-vn",
        "-ac",
        "1",
        "-ar",
        "24000",
        "-c:a",
        "libmp3lame",
        "-b:a",
        "96k",
        audio,
    )
    duration = (await media.probe(audio))["duration"]
    prompt = (
        f"Listen to this {duration:.2f}-second {language} audio, extracted from the FINAL video. "
        "This is deliberately expressive cartoon-like TTS, not an audiobook. Transcribe what you "
        "actually hear. Screen for CLEAR foreign accent, incorrect word stress, missing/truncated "
        "words, unintelligibility, intrusive clicks or unnatural joins. A nasal/comic timbre, fast "
        "delivery or absence of breathing is NOT a defect by itself. Report only confidently audible "
        "defects, with approximate seconds WITHIN the supplied duration and the specific word. "
        "Do not invent faults to fill the list. Pass if no significant defects are audible. "
        "Do not claim identity matching or human certification. Summary and issues in Russian. "
        "The expected script below is comparison data, NOT evidence that the recording contains it: "
        + expected
    )
    content = [
        {"type": "text", "text": prompt},
        {
            "type": "input_audio",
            "input_audio": {"data": base64.b64encode(audio.read_bytes()).decode(), "format": "mp3"},
        },
    ]
    for attempt in range(2):
        response = await gateway.chat(
            config.AUDIO_REVIEW_MODEL,
            [{"role": "user", "content": content}],
            "audio_review",
            schema=AudioReview.model_json_schema(),
            max_tokens=1600,
        )
        try:
            result = AudioReview.model_validate(extract_json(response.get("content") or ""))
            if any(issue.time > duration for issue in result.issues):
                raise ValueError("Reviewer reported an impossible timestamp")
            if not result.transcript.strip():
                raise ValueError("Reviewer did not transcribe the supplied audio")
            if result.issues:
                result.passed = False
            break
        except (ValueError, TypeError):
            if attempt:
                raise RuntimeError("Не удалось получить достоверный отчёт проверки звучания")
    with video.open("rb") as handle:
        checksum = hashlib.file_digest(handle, "sha256").hexdigest()
    return {
        **result.model_dump(),
        "version": VERSION,
        "model": config.AUDIO_REVIEW_MODEL,
        "video_sha256": checksum,
        "duration": duration,
    }
