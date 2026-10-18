"""Offline UI/API and real renderer smoke test. Requires an empty DATA_DIR."""

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from PIL import Image

from brainrot import config, media, quality, store
from brainrot.app import app
from brainrot.schemas import RenderPlan


async def main():
    if (config.DATA / "studio.sqlite").exists() or any((config.DATA / "jobs").iterdir()):
        raise RuntimeError("Use a fresh isolated DATA_DIR, never the user's workspace")
    with TestClient(app) as client:
        assert client.get("/api/health").json()["ok"]
        assert client.get("/").status_code == 200
        assert client.get("/media/studio.sqlite").status_code == 404
        try:
            with store.worker_lease():
                raise AssertionError("Second worker was not rejected")
        except RuntimeError:
            pass
    bg, speech = config.DATA / "media/bg.mp4", config.DATA / "media/speech.wav"
    Image.new("RGBA", (200, 300), (235, 40, 70, 220)).save(config.DATA / "media/portrait.png")
    await media.command(
        "ffmpeg",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=640x360:rate=30",
        "-t",
        3,
        "-c:v",
        "libx264",
        bg,
    )
    await media.command(
        "ffmpeg",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=48000",
        "-t",
        1.5,
        speech,
    )
    script = {
        "scenes": [{"id": sid, "speaker_id": "a", "text": "Caption test"} for sid in ("s1", "s2")]
    }
    audio = {
        sid: {
            "path": "media/speech.wav",
            "duration": 1.5,
            "words": [
                {"word": "Caption", "start": 0.1, "end": 0.6},
                {"word": "test", "start": 0.6, "end": 1.4},
            ],
        }
        for sid in ("s1", "s2")
    }
    target = config.DATA / "jobs/render"
    target.mkdir()
    result = await media.render(
        script,
        {"a": {"name": "Test", "portrait": "media/portrait.png"}},
        {},
        audio,
        bg,
        RenderPlan(playback_speed=1.2),
        target,
        True,
    )
    check = quality.frame_audit(target / "video.mp4", result["timeline"], True)
    assert not check["issues"] and check["frames"] == 76
    assert result["technical"]["background_loops"] == 0
    assert store.usage()["calls"] == 0
    print(
        json.dumps({"uid": os.getuid(), "technical": result["technical"], "video": check}, indent=2)
    )


if __name__ == "__main__":
    asyncio.run(main())
