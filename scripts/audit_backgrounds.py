"""Decode installed presets and screen for embedded short loops without any paid calls."""

import hashlib
import json
import sys
from pathlib import Path

import av
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from brainrot import assets, config, quality, store


def audit(path):
    report = quality.frame_audit(path, [], False)
    samples = []
    next_time = 0
    with av.open(str(path)) as container:
        for frame in container.decode(video=0):
            if frame.time >= next_time:
                samples.append(frame.reformat(width=32, height=32, format="gray").to_ndarray())
                next_time += 0.5
    samples = np.asarray(samples, dtype=np.float32)
    longest, lag_seconds = 0, None
    for lag in range(2, min(121, len(samples) // 2)):
        distance = np.mean(np.abs(samples[lag:] - samples[:-lag]), axis=(1, 2))
        run = quality.longest_run(distance < 0.8) / 2
        if run > longest:
            longest, lag_seconds = run, lag / 2
    report["short_loop_screen"] = {
        "sample_fps": 2,
        "lag_range_seconds": [1, 60],
        "longest_repeated_seconds": longest,
        "repeat_lag_seconds": lag_seconds,
        "method": "32x32 grayscale MAE < 0.8; flag at 4 consecutive seconds",
    }
    if longest >= 4:
        report["issues"].append("Repeated short segment in background source")
    with path.open("rb") as handle:
        report["sha256"] = hashlib.file_digest(handle, "sha256").hexdigest()
    report["passed"] = not report["issues"]
    return report


def main():
    reports = {}
    for preset in assets.catalog()["backgrounds"]:
        if preset.get("retired"):
            continue
        reports[preset["id"]] = audit(config.DATA / preset["path"])
        print(
            json.dumps({"id": preset["id"], **reports[preset["id"]]}, ensure_ascii=False),
            flush=True,
        )
    (config.DATA / "background-quality.json").write_text(store.dumps(reports))
    if not reports or any(not r["passed"] for r in reports.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
