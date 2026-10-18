import json

import pytest

from brainrot import audio_review


@pytest.mark.parametrize("invalid_first", [False, True])
async def test_audio_review_rejects_impossible_timestamps(tmp_path, monkeypatch, invalid_first):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    (tmp_path / "review-audio.mp3").write_bytes(b"audio")

    async def command(*args, **kwargs):
        pass

    async def probe(*args):
        return {"duration": 10}

    monkeypatch.setattr(audio_review.media, "command", command)
    monkeypatch.setattr(audio_review.media, "probe", probe)

    class Gateway:
        calls = 0

        async def chat(self, model, messages, purpose, **kwargs):
            self.calls += 1
            assert messages[0]["content"][1]["type"] == "input_audio"
            return {
                "content": json.dumps(
                    {
                        "passed": True,
                        "transcript": "Actual speech",
                        "summary": "Review",
                        "issues": [
                            {
                                "time": 20 if invalid_first and self.calls == 1 else 2,
                                "description": "Wrong stress on a specific word",
                            }
                        ],
                    }
                )
            }

    gateway = Gateway()
    result = await audio_review.review(gateway, video, "en", "Expected")
    assert gateway.calls == (2 if invalid_first else 1)
    assert result["passed"] is False
    assert len(result["video_sha256"]) == 64


async def test_audio_review_fails_closed_after_two_bad_responses(tmp_path, monkeypatch):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    (tmp_path / "review-audio.mp3").write_bytes(b"audio")

    async def command(*args, **kwargs):
        pass

    async def probe(*args):
        return {"duration": 10}

    monkeypatch.setattr(audio_review.media, "command", command)
    monkeypatch.setattr(audio_review.media, "probe", probe)

    class Gateway:
        calls = 0

        async def chat(self, *args, **kwargs):
            self.calls += 1
            return {"content": "not json"}

    gateway = Gateway()
    with pytest.raises(RuntimeError, match="отчёт"):
        await audio_review.review(gateway, video, "ru", "Expected")
    assert gateway.calls == 2
