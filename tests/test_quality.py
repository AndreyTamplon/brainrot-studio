import shutil

import av
import numpy as np
import pytest
from PIL import Image

from brainrot import media, quality
from brainrot.schemas import RenderPlan


def test_short_caption_is_not_advanced_by_frame_conversion(isolated_data):
    words = [
        {"word": "Почему", "start": 0, "end": 0.272436},
        {"word": "Луна", "start": 0.272436, "end": 0.689103},
        {"word": "не", "start": 0.689103, "end": 0.801282},
        {"word": "падает", "start": 0.801282, "end": 1},
    ]
    directory = isolated_data / "captions"
    entries = media.caption_frames(words, 1, RenderPlan(caption_color="white"), directory)
    output = directory / "captions.mov"
    media.encode_captions(entries, 1, output)
    expected = np.asarray(Image.open(directory / "word-002.png").convert("RGBA"))
    with av.open(str(output)) as container:
        frames = list(container.decode(video=0))
        assert len(frames) == 30
        assert np.array_equal(frames[23].to_ndarray(format="rgba"), expected)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg unavailable")
async def test_audit_rejects_black_and_frozen_video(isolated_data):
    path = isolated_data / "black.mp4"
    await media.command(
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=black:s=1080x1920:r=30:d=1",
        "-c:v",
        "libx264",
        path,
    )
    report = quality.frame_audit(path, [], False)
    assert report["black_frames"] == 30
    assert report["longest_freeze"] > 0.5
    assert len(report["issues"]) == 2


def test_longest_freeze_run():
    assert quality.longest_run([False, True, True, False, True]) == 2


def test_speech_audit_detects_offset_and_missing_speech(monkeypatch):
    from faster_whisper import audio

    words = [{"word": "Hello", "start": 0, "end": 0.5}, {"word": "world", "start": 0.5, "end": 1}]
    monkeypatch.setattr(
        media,
        "transcribe",
        lambda *a: {
            "similarity": 0.6,
            "transcript": "wrong",
            "asr_words": [{**w, "start": w["start"] + 0.7} for w in words],
        },
    )
    monkeypatch.setattr(audio, "decode_audio", lambda *a, **kw: np.ones(48000, dtype=np.float32))
    result = quality.speech_audit(
        "test",
        [{"scene_id": "s1", "start": 0, "end": 1, "text": "Hello world", "words": words}],
        "en",
    )
    assert result["word_offset_p95"] == 0.7
    assert len(result["issues"]) == 3
