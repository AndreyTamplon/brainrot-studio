"""Independent checks of the encoded deliverable, not the renderer's success flag."""

import asyncio
import difflib
import hashlib
import json
import math

import av
import numpy as np
from PIL import Image

from . import media
from .review_policy import AV_VERSION as VERSION


def longest_run(values):
    longest = current = 0
    for value in values:
        current = current + 1 if value else 0
        longest = max(longest, current)
    return longest


def frame_audit(path, timeline, subtitles):
    checks = []
    if subtitles:
        for scene in timeline:
            for index, word in enumerate(scene["words"]):
                if word["end"] - word["start"] >= 0.1:
                    checks.append(
                        {
                            "time": (word["start"] + word["end"]) / 2,
                            "scene": scene["scene_id"],
                            "index": index,
                        }
                    )
    pts, motion, blacks, coverage = [], [], [], []
    previous, cursor = None, 0
    with av.open(str(path)) as container:
        for frame in container.decode(video=0):
            pts.append(float(frame.time))
            gray = frame.reformat(width=270, height=480, format="gray").to_ndarray()
            blacks.append(float(np.mean(gray < 12)) > 0.985)
            edge = np.concatenate((gray[:, :8], gray[:, -8:]), axis=1).astype(np.float32)
            if previous is not None:
                motion.append(float(np.mean(np.abs(edge - previous))))
            previous = edge
            while cursor < len(checks) and checks[cursor]["time"] <= frame.time:
                check = checks[cursor]
                png = path.parent / check["scene"] / f"word-{check['index']:03d}.png"
                if png.exists():
                    expected = np.asarray(Image.open(png).convert("RGBA"))
                    mask = (expected[:, :, 3] > 240) & (expected[:, :, :3].max(axis=2) > 200)
                    actual = frame.to_ndarray(format="rgb24")[830:1070, 40:1040]
                    difference = np.max(np.abs(actual.astype(int) - expected[:, :, :3]), axis=2)
                    score = float(np.mean(difference[mask] < 65)) if mask.any() else 0
                    coverage.append({**check, "coverage": round(score, 3)})
                cursor += 1
    intervals = np.diff(pts)
    frozen = longest_run([value < 0.12 for value in motion]) / media.FPS
    failures = [item for item in coverage if item["coverage"] < 0.8]
    issues = []
    if not len(intervals) or np.max(np.abs(intervals - 1 / media.FPS)) > 0.002:
        issues.append("Video frame timestamps are not continuous 30 fps")
    if any(blacks):
        issues.append("Encoded video contains black frames")
    if frozen > 0.5:
        issues.append(f"Background freezes for {frozen:.2f}s")
    if subtitles and (failures or len(coverage) != len(checks)):
        issues.append(f"Caption pixels do not match the timeline ({len(failures)} words)")
    return {
        "frames": len(pts),
        "fps": media.FPS,
        "max_frame_gap": round(float(max(intervals, default=0)), 6),
        "black_frames": sum(blacks),
        "longest_freeze": round(frozen, 3),
        "caption_checks": len(coverage),
        "caption_failures": failures,
        "minimum_caption_coverage": min((c["coverage"] for c in coverage), default=None),
        "issues": issues,
    }


def speech_audit(path, timeline, language):
    from faster_whisper.audio import decode_audio

    expected = [w for scene in timeline for w in scene["words"]]
    original = " ".join(scene["text"] for scene in timeline)
    heard = media.transcribe(path, language, original)
    matcher = difflib.SequenceMatcher(
        None,
        [media.normalize(w["word"]) for w in expected],
        [media.normalize(w["word"]) for w in heard["asr_words"]],
        autojunk=False,
    )
    offsets = []
    for block in matcher.get_matching_blocks():
        for i in range(block.size):
            offsets.append(
                heard["asr_words"][block.b + i]["start"] - expected[block.a + i]["start"]
            )
    sound = decode_audio(str(path), sampling_rate=48000)
    scene_audio = []
    for scene in timeline:
        start, end = round(scene["start"] * 48000), round(scene["end"] * 48000)
        section = sound[start:end]
        active = section[np.abs(section) > 0.01]
        level = math.sqrt(float(np.mean(active**2))) if active.size else 1e-9
        join = sound[max(0, start - 480) : start + 480]
        jump = float(np.max(np.abs(np.diff(join)), initial=0)) if start else 0
        scene_audio.append(
            {
                "scene_id": scene["scene_id"],
                "active_rms_dbfs": round(20 * math.log10(max(level, 1e-9)), 2),
                "join_sample_jump": round(jump, 4),
            }
        )
    levels = [s["active_rms_dbfs"] for s in scene_audio]
    spread = max(levels) - min(levels) if levels else 0
    absolute = np.abs(sound)
    peak = float(absolute.max(initial=0))
    rms = math.sqrt(float(np.mean(sound**2))) if sound.size else 0
    # 20 ms windows distinguish actual silence from individual waveform zero crossings.
    chunks = sound[: len(sound) // 960 * 960].reshape(-1, 960)
    silent = np.sqrt(np.mean(chunks**2, axis=1)) < 0.003
    leading = next((i for i, value in enumerate(silent) if not value), len(silent)) * 0.02
    trailing = (
        next((i for i, value in enumerate(reversed(silent)) if not value), len(silent)) * 0.02
    )
    p95 = float(np.percentile(np.abs(offsets), 95)) if offsets else 999
    median = float(np.median(offsets)) if offsets else 999
    issues = []
    if heard["similarity"] < 0.82:
        issues.append(f"Final speech differs from script (similarity {heard['similarity']})")
    if not offsets or p95 > 0.3 or abs(median) > 0.12:
        issues.append(f"Independent word timing check failed (p95 {p95:.3f}s, bias {median:.3f}s)")
    if peak > 0.995 or rms < 0.015:
        issues.append("Final audio clips or is too quiet")
    if leading > 0.7 or trailing > 0.9:
        issues.append("Excess silence at video start/end")
    if spread > 7:
        issues.append(f"Dialogue volume is inconsistent ({spread:.1f} dB spread)")
    if any(s["join_sample_jump"] > 0.3 for s in scene_audio):
        issues.append("Possible audio discontinuity at a scene boundary")
    return {
        "similarity": heard["similarity"],
        "transcript": heard["transcript"],
        "matched_words": len(offsets),
        "expected_words": len(expected),
        "word_offset_p95": round(p95, 3),
        "word_offset_median": round(median, 3),
        "word_offset_max": round(max(map(abs, offsets), default=999), 3),
        "peak_dbfs": round(20 * math.log10(max(peak, 1e-9)), 2),
        "rms_dbfs": round(20 * math.log10(max(rms, 1e-9)), 2),
        "leading_silence": round(leading, 3),
        "trailing_silence": round(trailing, 3),
        "longest_silence": round(longest_run(silent) * 0.02, 3),
        "scene_audio": scene_audio,
        "scene_level_spread_db": round(spread, 2),
        "issues": issues,
    }


async def audit(path, timeline, language, subtitles, technical):
    actual = await media.probe(path)
    frames = await asyncio.to_thread(frame_audit, path, timeline, subtitles)
    speech = await asyncio.to_thread(speech_audit, path, timeline, language)
    issues = frames["issues"] + speech["issues"]
    if abs(actual["duration"] - technical["expected_duration"]) > 0.06:
        issues.append("Muxed duration differs from frame-aligned timeline")
    if not actual["has_audio"] or (actual["width"], actual["height"]) != (1080, 1920):
        issues.append("Missing audio or incorrect output dimensions")
    if technical.get("background_loops") != 0:
        issues.append("Background repetition is not allowed")
    with path.open("rb") as file:
        checksum = hashlib.file_digest(file, "sha256").hexdigest()
    report = {
        "version": VERSION,
        "video_sha256": checksum,
        "passed": not issues,
        "issues": issues,
        "video": frames,
        "speech": speech,
        "background_loops": 0,
    }
    (path.parent / "quality.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report
