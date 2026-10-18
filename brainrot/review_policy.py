"""Shared acceptance rules for production, resume and startup recovery."""

from . import config
from .speech import validate_decimal_speech

AV_VERSION = 3
AUDIO_VERSION = 1
FRAME_VERSION = 4


def reviews_current(artifacts):
    av = artifacts.get("quality", {})
    audio = artifacts.get("audio_review", {})
    frames = artifacts.get("review", {})
    checksum = av.get("video_sha256")
    return bool(
        checksum
        and av.get("version") == AV_VERSION
        and audio.get("version") == AUDIO_VERSION
        and audio.get("model") == config.AUDIO_REVIEW_MODEL
        and frames.get("version") == FRAME_VERSION
        and frames.get("model") == config.VISION_MODEL
        and audio.get("video_sha256") == checksum
        and frames.get("video_sha256") == checksum
    )


def accepted(artifacts):
    try:
        for scene in artifacts.get("script", {}).get("scenes", []):
            validate_decimal_speech(scene.get("text", ""))
    except ValueError:
        return False
    script_hash = artifacts.get("script_hash")
    return bool(
        artifacts.get("video")
        and not artifacts.get("script_revision")
        and not artifacts.get("visual_revision")
        and not artifacts.get("revision_plan", {}).get("pending")
        and script_hash
        and artifacts.get("audio_complete") == script_hash
        and artifacts.get("visual_complete") == script_hash
        and reviews_current(artifacts)
        and all(artifacts[name].get("passed") for name in ("quality", "audio_review", "review"))
    )
