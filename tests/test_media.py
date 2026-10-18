import math
import shutil
from itertools import pairwise

import pytest
from PIL import Image

from brainrot import media
from brainrot.schemas import RenderPlan


def test_background_window_is_continuous_bounded_and_repeatable():
    starts = [media.background_start(600, 45, f"job-{i}") for i in range(10)]
    assert len(set(starts)) > 1
    for i, start in enumerate(starts):
        assert 0 <= start <= 555
        assert start * 30 == pytest.approx(round(start * 30))
        assert start == media.background_start(600, 45, f"job-{i}")
    assert media.background_start(45, 45, "same-length") == 0
    assert media.background_start(10, 45, "too-short") == 0


def test_caption_layout_and_timing(isolated_data):
    words = [
        {"word": "Сверхпроводимость", "start": 0.1, "end": 0.4},
        {"word": "существует", "start": 0.4, "end": 0.9},
    ]
    directory = isolated_data / "captions"
    entries = media.caption_frames(words, 1, RenderPlan(), directory)
    assert entries[1][1] == pytest.approx(0.3)
    for image in directory.glob("word-*.png"):
        box = Image.open(image).getbbox()
        assert box and 0 < box[0] < box[2] < 1000
    assert media.srt_time(62.345) == "00:01:02,345"


def test_caption_spelling_keeps_observed_timing():
    words = [
        {"word": "Нейросейт", "start": 0.1, "end": 0.9},
        {"word": "думает", "start": 1, "end": 2},
    ]
    assert media.align_caption_text("Нейросеть думает", words) == [
        {"word": "Нейросеть", "start": 0.1, "end": 0.9},
        words[1],
    ]


@pytest.mark.parametrize(
    "spoken,numeric,language",
    [
        ("ноль целых девятьсот семнадцать тысячных", "0 ,917", "ru"),
        ("девять процентов", "9%", "ru"),
        ("двадцать один процент", "21 %", "ru"),
        ("двенадцать процентов", "12%", "ru"),
        ("тридцать два процента", "32%", "ru"),
        ("минус пять", "-5", "ru"),
        ("one point five percent", "1.5%", "en"),
        ("one thousand", "1,000", "en"),
    ],
)
def test_speech_numbers_are_equivalent(spoken, numeric, language):
    assert media.normalize_speech(spoken, language) == media.normalize_speech(numeric, language)


def test_speech_number_values_are_not_erased():
    assert media.normalize_speech("9%", "ru") != media.normalize_speech("90%", "ru")
    assert media.normalize_speech("0,917", "ru") != media.normalize_speech("917", "ru")


def test_caption_alignment_handles_split_and_merged_words():
    words = [
        {"word": "Чат", "start": 0, "end": 0.3},
        {"word": "бот", "start": 0.3, "end": 0.6},
        {"word": "уверенно", "start": 0.6, "end": 1},
        {"word": "вретнам", "start": 1, "end": 2},
    ]
    result = media.align_caption_text("Чат-бот уверенно врёт нам", words)
    assert [w["word"] for w in result] == ["Чат-бот", "уверенно", "врёт", "нам"]
    assert result[0]["start"] == 0 and result[0]["end"] == 0.6
    assert result[-1]["end"] == 2
    assert all(a["end"] <= b["start"] for a, b in pairwise(result))


def test_caption_alignment_does_not_speak_punctuation():
    words = [
        {"word": "Летит", "start": 0, "end": 0.2},
        {"word": "в", "start": 0.2, "end": 0.4},
        {"word": "бок", "start": 0.4, "end": 0.6},
        {"word": "и", "start": 0.6, "end": 0.8},
    ]
    result = media.align_caption_text("Летит вбок — и", words)
    assert [w["word"] for w in result] == ["Летит", "вбок", "и"]
    assert result[1]["start"] == 0.2 and result[1]["end"] == 0.6


def test_long_transcript_similarity_does_not_drop_common_letters(monkeypatch):
    from types import SimpleNamespace

    text = "Металлическая кабина с закрытыми дверями ослабляет радиоволны. " * 8
    heard = text.replace("ослабляет", "экранирует")
    words = [
        SimpleNamespace(word=w, start=i * 0.3, end=(i + 1) * 0.3)
        for i, w in enumerate(heard.split())
    ]
    monkeypatch.setattr(
        media,
        "recognizer",
        lambda: SimpleNamespace(
            transcribe=lambda *args, **kwargs: ([SimpleNamespace(words=words)], None)
        ),
    )
    assert media.transcribe("ignored.mp3", "ru", text)["similarity"] > 0.85


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg unavailable")
@pytest.mark.parametrize("speed", [0.85, 0.953, 1.25])
async def test_normalized_audio_has_exact_sample_count(isolated_data, speed):
    import av

    source = isolated_data / "media" / "source.mp3"
    target = isolated_data / "media" / "normalized.wav"
    await media.command(
        "ffmpeg",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=330:sample_rate=44100",
        "-t",
        6.123,
        "-c:a",
        "libmp3lame",
        source,
    )
    duration = math.ceil((await media.probe(source))["duration"] / speed * 30) / 30
    await media.prepare_audio(source, target, duration, speed)
    with av.open(str(target)) as container:
        assert sum(frame.samples for frame in container.decode(audio=0)) == round(duration * 48000)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg unavailable")
@pytest.mark.parametrize("subtitles", [True, False])
async def test_real_render(isolated_data, subtitles):
    bg = isolated_data / "media" / "background.mp4"
    speech = isolated_data / "media" / "speech.wav"
    portrait = isolated_data / "media" / "portrait.png"
    Image.new("RGBA", (200, 300), (235, 40, 70, 220)).save(portrait)
    await media.command(
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=640x360:rate=30",
        "-t",
        "3",
        "-c:v",
        "libx264",
        bg,
    )
    await media.command(
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=48000",
        "-t",
        "1.5",
        speech,
    )
    from faster_whisper.audio import decode_audio

    assert len(decode_audio(str(speech))) > 1000
    script = {
        "scenes": [
            {"id": "s1", "speaker_id": "a", "text": "Тест титров"},
            {"id": "s2", "speaker_id": "a", "text": "Тест титров"},
        ]
    }
    audio = {
        "s1": {
            "duration": 1.5,
            "path": "media/speech.wav",
            "words": [
                {"word": "Тест", "start": 0.1, "end": 0.6},
                {"word": "титров", "start": 0.6, "end": 1.4},
            ],
        }
    }
    audio["s2"] = audio["s1"].copy()
    target = isolated_data / "jobs" / "render"
    target.mkdir()
    result = await media.render(
        script,
        {"a": {"name": "Тест", "portrait": "media/portrait.png"}},
        {"s1": {"path": "media/portrait.png"}},
        audio,
        bg,
        RenderPlan(layout="split", playback_speed=1.2),
        target,
        subtitles,
    )
    assert result["technical"]["width"] == 1080
    assert result["technical"]["height"] == 1920
    assert result["technical"]["has_audio"]
    assert abs(result["technical"]["duration"] - 76 / 30) < 0.04
    assert len(result["frames"]) == 2
    assert result["timeline"][1]["start"] == 38 / 30
    assert result["technical"]["background_loops"] == 0
    assert 0 <= result["technical"]["background_start"]
    assert result["technical"]["background_end"] <= 3
    assert result["frames"][0]["scene_id"] == "s1"
    assert bool(result["frames"][0]["caption"]) == subtitles
    assert (target / "s1" / "captions.mov").exists() == subtitles
    from brainrot.quality import frame_audit

    audit = frame_audit(target / "video.mp4", result["timeline"], subtitles)
    assert audit["issues"] == []
    assert audit["frames"] == 76
    with pytest.raises(ValueError, match="never looped"):
        await media.render(
            script,
            {"a": {"name": "Test"}},
            {},
            audio,
            bg,
            RenderPlan(playback_speed=0.85),
            target,
            subtitles,
        )
