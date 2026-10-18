import asyncio
import difflib
import hashlib
import json
import math
import os
import re
import signal
from fractions import Fraction
from functools import lru_cache
from pathlib import Path

from num2words import num2words
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .config import DATA, ROOT

WIDTH, HEIGHT, FPS = 1080, 1920, 30


async def command(*args, timeout=600):
    process = await asyncio.create_subprocess_exec(
        *map(str, args),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
    except (TimeoutError, asyncio.CancelledError):
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.communicate(), 3)
        except TimeoutError:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.communicate()
        raise
    if process.returncode:
        raise RuntimeError(
            f"{Path(str(args[0])).name} exited {process.returncode}: "
            + stderr.decode(errors="replace")[-1400:]
        )
    return stdout.decode(errors="replace")


async def probe(path):
    data = json.loads(
        await command(
            "ffprobe",
            "-protocol_whitelist",
            "file,pipe",
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            path,
            timeout=30,
        )
    )
    streams = data.get("streams", [])
    video = next((s for s in streams if s["codec_type"] == "video"), {})
    return {
        "duration": float(data.get("format", {}).get("duration", 0)),
        "width": video.get("width"),
        "height": video.get("height"),
        "has_video": bool(video),
        "has_audio": any(s["codec_type"] == "audio" for s in streams),
        "codec": video.get("codec_name"),
        "size": int(data.get("format", {}).get("size", 0)),
    }


async def thumbnail(path, output, seconds=1, width=360):
    await command(
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        seconds,
        "-protocol_whitelist",
        "file,pipe",
        "-i",
        path,
        "-frames:v",
        1,
        "-vf",
        f"scale={width}:-2",
        output,
        timeout=40,
    )


@lru_cache(maxsize=1)
def recognizer():
    from faster_whisper import WhisperModel

    return WhisperModel(
        os.getenv("WHISPER_MODEL", "small"),
        device="cpu",
        compute_type="int8",
        download_root=str(DATA / "cache" / "whisper"),
        cpu_threads=4,
    )


def normalize(text):
    return re.sub(r"[^\w]+", " ", text.lower().replace("ё", "е")).strip()


def normalize_speech(text, language):
    """Compare spoken numbers with ASR digits without changing the independent transcript."""
    text = re.sub(r"(?<=\d)\s+([,.])(?=\d)", r"\1", text)
    if language == "en":
        text = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", text)

    def expand(match):
        number = match[1].replace(",", ".")
        if len(number) > 16:
            return match[0]
        try:
            words = num2words(number, lang=language)
        except (ValueError, NotImplementedError, OverflowError):
            return match[0]
        if match[2]:
            suffix = "percent"
            if language == "ru":
                value = abs(int(number.split(".")[0]))
                suffix = (
                    "процента"
                    if "." in number
                    else "процент"
                    if value % 10 == 1 and value % 100 != 11
                    else "процента"
                    if 2 <= value % 10 <= 4 and not 12 <= value % 100 <= 14
                    else "процентов"
                )
            words += " " + suffix
        return words

    text = re.sub(r"(?<!\w)(-?\d+(?:[.,]\d+)?)(\s*%)?(?!\w)", expand, text)
    return normalize(text)


def align_caption_text(original, words):
    """Align script tokens to independent ASR anchors, including split/merged words."""
    if not words:
        return []
    expected = [token for token in original.split() if normalize(token)]
    heard = [word["word"] for word in words]
    matcher = difflib.SequenceMatcher(
        None, [normalize(w) for w in expected], [normalize(w) for w in heard], autojunk=False
    )
    captions = []
    for kind, a, b, c, d in matcher.get_opcodes():
        if kind == "equal" or (kind == "replace" and b - a == d - c):
            captions.extend(
                {**word, "word": label}
                for label, word in zip(expected[a:b], words[c:d], strict=True)
            )
        elif b > a:
            start = words[c]["start"] if d > c else words[c - 1]["end"] if c else 0
            end = words[d - 1]["end"] if d > c else words[c]["start"] if c < len(words) else start
            weights = [max(1, len(normalize(label))) for label in expected[a:b]]
            total = sum(weights)
            cursor = start
            for label, weight in zip(expected[a:b], weights, strict=True):
                next_time = cursor + (end - start) * weight / total
                if next_time > cursor:
                    captions.append(
                        {"word": label, "start": round(cursor, 3), "end": round(next_time, 3)}
                    )
                cursor = next_time
    return captions


def alignment_version():
    return "whisper-independent-v5:" + os.getenv("WHISPER_MODEL", "small")


def transcribe(path, language, original):
    segments, _ = recognizer().transcribe(
        str(path),
        language=language,
        word_timestamps=True,
        beam_size=3,
        vad_filter=True,
        condition_on_previous_text=False,
    )
    words = [
        {
            "word": word.word.strip(),
            "start": round(float(word.start), 3),
            "end": round(float(word.end), 3),
        }
        for segment in segments
        for word in segment.words or []
        if word.word.strip() and word.end - word.start >= 0.01
    ]
    spoken = " ".join(word["word"] for word in words)
    similarity = difflib.SequenceMatcher(
        None,
        normalize_speech(original, language),
        normalize_speech(spoken, language),
        autojunk=False,
    ).ratio()
    return {
        "words": align_caption_text(original, words) if similarity >= 0.75 else words,
        "asr_words": words,
        "transcript": spoken,
        "similarity": round(similarity, 3),
        "alignment": alignment_version(),
    }


def font_path():
    for path in (
        ROOT / "assets" / "fonts" / "DejaVuSans-Bold.ttf",
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ):
        if path.is_file():
            return str(path)
    raise RuntimeError("Не найден шрифт с кириллицей")


def fit_font(text, max_width, size):
    while size > 8:
        font = ImageFont.truetype(font_path(), size)
        if font.getlength(text) <= max_width:
            return font
        size -= 2
    return ImageFont.truetype(font_path(), max(1, size))


def scene_overlay(scene, speaker, image, plan, target):
    canvas = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    if image and (DATA / image["path"]).is_file():
        if plan.layout == "split":
            draw.rectangle((0, 0, WIDTH, 790), fill=(15, 16, 18, 255))
        with Image.open(DATA / image["path"]) as source:
            illustration = ImageOps.contain(source.convert("RGBA"), (920, 640))
            x, y = (WIDTH - illustration.width) // 2, 120
            draw.rounded_rectangle(
                (x - 12, y - 12, x + illustration.width + 12, y + illustration.height + 12),
                radius=12,
                fill=(12, 12, 14, 235),
            )
            canvas.alpha_composite(illustration, (x, y))
            label = scene.get("visual_caption", "")
            if label:
                font = fit_font(label, 890, 35)
                draw.text(
                    (WIDTH // 2, y + illustration.height + 35),
                    label,
                    font=font,
                    fill="white",
                    stroke_width=3,
                    stroke_fill="black",
                    anchor="mt",
                )
    portrait = speaker.get("portrait")
    if portrait and (DATA / portrait).is_file():
        with Image.open(DATA / portrait) as source:
            avatar = source.convert("RGBA")
            box = avatar.getbbox()
            if box:
                avatar = avatar.crop(box)
            avatar = ImageOps.contain(avatar, (plan.character_size, 730))
            side = 70 if speaker.get("side") == "left" else WIDTH - avatar.width - 70
            canvas.alpha_composite(avatar, (side, HEIGHT - avatar.height - 190))
    name = speaker["name"]
    font = fit_font(name, 700, 32)
    draw.text(
        (70, HEIGHT - 125), name, font=font, fill="white", stroke_width=3, stroke_fill="black"
    )
    canvas.save(target)


def caption_frames(words, duration, plan, directory):
    directory.mkdir(exist_ok=True)
    entries, cursor = [], 0.0
    blank = directory / "blank.png"
    Image.new("RGBA", (1000, 240)).save(blank)
    colors = {"yellow": "#f9ef36", "white": "#ffffff", "mint": "#85f8bc"}
    for index, word in enumerate(words):
        start = max(cursor, min(float(word["start"]), duration))
        end = max(start, min(float(word["end"]), duration))
        if index + 1 < len(words) and 0 <= words[index + 1]["start"] - end <= 0.18:
            end = min(duration, words[index + 1]["start"])
        if start > cursor:
            entries.append((blank, start - cursor))
        if end <= start:
            continue
        group_start = (index // 3) * 3
        group = words[group_start : group_start + 3]
        labels = [w["word"].upper() for w in group]
        font = fit_font(" ".join(labels), 930, plan.caption_size)
        image = Image.new("RGBA", (1000, 240))
        draw = ImageDraw.Draw(image)
        widths = [font.getlength(label) for label in labels]
        space = font.getlength(" ")
        x = (1000 - sum(widths) - space * (len(labels) - 1)) / 2
        for j, label in enumerate(labels):
            active = group_start + j == index
            draw.text(
                (x, 80),
                label,
                font=font,
                fill=colors[plan.caption_color] if active else "white",
                stroke_width=7,
                stroke_fill="black",
            )
            x += widths[j] + space
        path = directory / f"word-{index:03d}.png"
        image.save(path)
        entries.append((path, end - start))
        cursor = end
    if cursor < duration:
        entries.append((blank, duration - cursor))
    (directory / "captions.json").write_text(
        json.dumps([{"image": p.name, "duration": seconds} for p, seconds in entries])
    )
    return entries


def encode_captions(entries, duration, output):
    import av
    import numpy as np

    # Explicit frame PTS avoid concat-demuxer/CFR rounding advancing short words.
    with av.open(str(output), "w") as container:
        stream = container.add_stream("qtrle", rate=FPS)
        stream.width, stream.height, stream.pix_fmt = 1000, 240, "argb"
        cursor, boundary = 0, entries[0][1]
        cached = {}
        for index in range(math.ceil(duration * FPS)):
            while index / FPS >= boundary - 1e-9 and cursor + 1 < len(entries):
                cursor += 1
                boundary += entries[cursor][1]
            path = entries[cursor][0]
            if path not in cached:
                with Image.open(path) as source:
                    cached[path] = source.convert("RGBA")
            frame = av.VideoFrame.from_ndarray(np.asarray(cached[path]), format="rgba")
            frame.pts, frame.time_base = index, Fraction(1, FPS)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


async def render_scene(
    scene, speaker, image, audio, background, plan, directory, subtitles, offset
):
    scene_dir = directory / scene["id"]
    scene_dir.mkdir(exist_ok=True)
    duration = math.ceil(audio["duration"] / plan.playback_speed * FPS) / FPS
    words = [
        {**w, "start": w["start"] / plan.playback_speed, "end": w["end"] / plan.playback_speed}
        for w in audio.get("words", [])
    ]
    overlay = scene_dir / "overlay.png"
    await asyncio.to_thread(scene_overlay, scene, speaker, None, plan, overlay)
    normalized = scene_dir / "speech.wav"
    await prepare_audio(DATA / audio["path"], normalized, duration, plan.playback_speed)
    inputs = [
        "-protocol_whitelist",
        "file,pipe",
        "-ss",
        str(offset),
        "-i",
        str(background),
        "-loop",
        "1",
        "-i",
        str(overlay),
        "-i",
        str(normalized),
    ]
    filters = [
        (
            f"[0:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={WIDTH}:{HEIGHT},setsar=1,fps={FPS}[bg]"
        ),
        "[bg][1:v]overlay=0:0:shortest=1[composite]",
    ]
    output_label = "composite"
    next_input = 3
    if image:
        inset = scene_dir / "inset.png"
        await asyncio.to_thread(scene_overlay, scene, {"name": ""}, image, plan, inset)
        inputs.extend(["-loop", "1", "-i", str(inset)])
        filters.append(
            f"[{output_label}][{next_input}:v]overlay=0:0:"
            f"enable='lt(t,{plan.image_seconds})'[illustrated]"
        )
        output_label = "illustrated"
        next_input += 1
    if subtitles and audio.get("words"):
        entries = await asyncio.to_thread(caption_frames, words, duration, plan, scene_dir)
        captions = scene_dir / "captions.mov"
        await asyncio.to_thread(encode_captions, entries, duration, captions)
        inputs.extend(["-i", str(captions)])
        filters.append(f"[{output_label}][{next_input}:v]overlay=40:830:eof_action=pass[captioned]")
        output_label = "captioned"
    # PCM intermediates avoid AAC encoder padding at every dialogue boundary.
    output = scene_dir / "scene.mov"
    await command(
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-threads",
        "2",
        *inputs,
        "-filter_complex_threads",
        "1",
        "-filter_complex",
        ";".join(filters),
        "-map",
        f"[{output_label}]",
        "-map",
        "2:a:0",
        "-t",
        duration,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "22",
        "-pix_fmt",
        "yuv420p",
        "-r",
        FPS,
        "-c:a",
        "pcm_s16le",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        output,
    )
    return output


async def prepare_audio(source, target, duration, speed):
    # Finish loudnorm/resampling before video muxing. Pad at the FINAL sample rate.
    # Otherwise -t can truncate delayed resampler output and accumulate gaps at joins.
    samples = round(duration * 48000)
    await command(
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-i",
        source,
        "-af",
        f"atempo={speed},loudnorm=I=-16:TP=-1.5:LRA=7,"
        "aformat=sample_rates=48000:channel_layouts=stereo,"
        f"apad,atrim=end_sample={samples},asetpts=N/SR/TB",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-c:a",
        "pcm_s16le",
        target,
    )
    actual = await probe(target)
    if abs(actual["duration"] - duration) > 1 / 48000:
        raise RuntimeError("Normalized audio length does not match the sample-aligned timeline")


def srt_time(seconds):
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{milliseconds:03}"


def background_start(source_duration, needed_duration, seed):
    """Choose one frame-aligned continuous window, stable across render retries."""
    available_frames = max(0, math.floor((source_duration - needed_duration) * FPS))
    if not available_frames:
        return 0.0
    digest = hashlib.sha256(str(seed).encode()).digest()
    return (int.from_bytes(digest[:8], "big") % (available_frames + 1)) / FPS


async def render(script, speakers, visuals, audio, background, plan, directory, subtitles=True):
    total = sum(
        math.ceil(audio[s["id"]]["duration"] / plan.playback_speed * FPS) / FPS
        for s in script["scenes"]
    )
    background_info = await probe(background)
    if background_info["duration"] + 1 / FPS < total:
        raise ValueError(
            f"Background is {background_info['duration']:.1f}s; video needs {total:.1f}s. "
            "Short backgrounds are never looped. Choose a longer source or shorten the script."
        )
    bg_start = background_start(background_info["duration"], total, directory.parent.name)
    clips, offset, captions, samples, timeline = [], 0.0, [], [], []
    for scene in script["scenes"]:
        speaker = speakers[scene["speaker_id"]]
        clip = await render_scene(
            scene,
            speaker,
            visuals.get(scene["id"]),
            audio[scene["id"]],
            background,
            plan,
            directory,
            subtitles,
            bg_start + offset,
        )
        clips.append(clip)
        scene_duration = math.ceil(audio[scene["id"]]["duration"] / plan.playback_speed * FPS) / FPS
        words = [
            {**w, "start": w["start"] / plan.playback_speed, "end": w["end"] / plan.playback_speed}
            for w in audio[scene["id"]].get("words", [])
        ]
        local_time = min(scene_duration / 2, plan.image_seconds / 2, 1.5)
        active_index = next(
            (i for i, w in enumerate(words) if w["start"] <= local_time <= w["end"]), None
        )
        if active_index is None and words:
            active_index = min(range(len(words)), key=lambda i: abs(words[i]["start"] - local_time))
            local_time = (words[active_index]["start"] + words[active_index]["end"]) / 2
        group = (active_index // 3) * 3 if active_index is not None else 0
        samples.append(
            {
                "time": offset + local_time,
                "scene_id": scene["id"],
                "speaker": speaker["name"],
                "caption": " ".join(w["word"] for w in words[group : group + 3])
                if subtitles
                else None,
                "image": visuals.get(scene["id"], {}).get("title")
                if visuals.get(scene["id"]) and local_time < plan.image_seconds
                else None,
            }
        )
        for word in words:
            start = offset + word["start"]
            end = offset + word["end"]
            captions.append(
                f"{len(captions) + 1}\n{srt_time(start)} --> {srt_time(end)}\n{word['word']}\n"
            )
        timeline.append(
            {
                "scene_id": scene["id"],
                "start": offset,
                "end": offset + scene_duration,
                "text": scene["text"],
                "words": [
                    {**w, "start": offset + w["start"], "end": offset + w["end"]} for w in words
                ],
            }
        )
        offset += scene_duration
    listing = directory / "clips.txt"
    listing.write_text("\n".join(f"file '{clip.relative_to(directory)}'" for clip in clips))
    output = directory / "video.mp4"
    await command(
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        listing,
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-af",
        "loudnorm=I=-16:TP=-1.5:LRA=11,aformat=sample_rates=48000:channel_layouts=stereo,"
        f"apad,atrim=end_sample={round(offset * 48000)},asetpts=N/SR/TB",
        "-ar",
        "48000",
        "-movflags",
        "+faststart",
        output,
    )
    (directory / "captions.srt").write_text("\n".join(captions))
    (directory / "timeline.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=2))
    info = await probe(output)
    frames = []
    for index, sample in enumerate(samples):
        seconds = max(0.1, sample["time"])
        frame = directory / f"review-{index}.jpg"
        await thumbnail(output, frame, seconds, width=720)
        frames.append({**sample, "path": str(frame.relative_to(DATA)), "time": round(seconds, 2)})
    await command("ffmpeg", "-v", "error", "-i", output, "-f", "null", "-", timeout=180)
    return {
        "video": str(output.relative_to(DATA)),
        "frames": frames,
        "technical": {
            **info,
            "decoded": True,
            "expected_duration": round(offset, 3),
            "background_duration": background_info["duration"],
            "background_start": bg_start,
            "background_end": bg_start + offset,
            "background_loops": 0,
        },
        "timeline": timeline,
    }
