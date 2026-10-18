"""Opt-in paid black-box acceptance runs against the running local server.

Uses ordinary public endpoints and durable reports; never modifies jobs, budgets or artifacts.
Rerun with the same report to observe existing jobs without submitting duplicates.
"""

import argparse
import asyncio
import hashlib
import json
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
CASES = {
    "ru-solo-15": {
        "topic": "Почему мыльные пузыри переливаются разными цветами?",
        "background_id": "minecraft-coast",
        "speaker_ids": ["stewie"],
        "duration": 15,
        "language": "ru",
        "subtitles": True,
    },
    "ru-dialogue-30": {
        "topic": "Почему в космосе не слышно взрывов?",
        "background_id": "cs-surf",
        "speaker_ids": ["peter", "stewie"],
        "duration": 30,
        "language": "ru",
        "subtitles": False,
    },
    "en-trio-45": {
        "topic": "Why does a cat always seem to land on its feet? Explain the righting reflex and its limits.",
        "background_id": "subway",
        "speaker_ids": ["peter", "stewie", "brian"],
        "duration": 45,
        "language": "en",
        "subtitles": True,
    },
    "ru-dialogue-60": {
        "topic": "Как воздушный шар летит вверх, если у него нет крыльев?",
        "background_id": "minecraft-caves",
        "speaker_ids": ["stewie", "peter"],
        "duration": 60,
        "language": "ru",
        "subtitles": True,
    },
    "ru-solo-90": {
        "topic": "Почему море солёное, а реки обычно пресные? Откуда берётся соль и куда она уходит?",
        "background_id": "cs-surf",
        "speaker_ids": ["peter"],
        "duration": 90,
        "language": "ru",
        "subtitles": True,
    },
}


def save(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    temporary.replace(path)


async def main(args):
    path = args.report.resolve()
    report = (
        json.loads(path.read_text()) if path.exists() else {"started": time.time(), "cases": {}}
    )
    async with httpx.AsyncClient(base_url=args.url, timeout=30) as client:

        async def api(method, url, **kw):
            result = await client.request(method, url, **kw)
            result.raise_for_status()
            return result.json()

        settings = await api("GET", "/api/settings")
        report.setdefault(
            "starting_usage", {k: v for k, v in settings["usage"].items() if k != "entries"}
        )
        digest = hashlib.sha256()
        for source in sorted((ROOT / "brainrot").glob("*.py")):
            digest.update(source.name.encode() + source.read_bytes())
        source_hash = digest.hexdigest()
        for name in args.cases.split(","):
            if name not in CASES:
                raise ValueError(f"Unknown case: {name}")
            entry = report["cases"].get(name)
            if not entry:
                usage = (await api("GET", "/api/settings"))["usage"]
                used = usage["spent"] + usage["held"]
                baseline = report["starting_usage"]
                if (
                    used - baseline["spent"] - baseline["held"] >= args.max_cost
                    or used + 0.3 > usage["limit"]
                ):
                    raise RuntimeError("Acceptance budget exhausted; existing report is preserved")
                request = {**CASES[name], "budget": 1.5}
                key = hashlib.sha256((str(path) + name).encode()).hexdigest()
                job = await api("POST", "/api/jobs", json=request, headers={"Idempotency-Key": key})
                entry = {"id": job["id"], "request": request, "source_sha256": source_hash}
                report["cases"][name] = entry
                save(path, report)
            previous = None
            deadline = time.monotonic() + args.timeout
            while True:
                try:
                    job = await api("GET", f"/api/jobs/{entry['id']}")
                except httpx.TransportError:
                    if time.monotonic() > deadline:
                        raise
                    await asyncio.sleep(5)
                    continue
                state = (job["status"], job["stage"])
                if state != previous:
                    print(name, entry["id"], *state, flush=True)
                    previous = state
                entry.update(
                    {
                        "status": job["status"],
                        "stage": job["stage"],
                        "error": job["error"],
                        "usage": {k: v for k, v in job["usage"].items() if k != "entries"},
                        "render_count": job["artifacts"].get("render_count", 0),
                        "recovery_attempts": job["artifacts"].get("recovery_attempts", 0),
                        "video": job["artifacts"].get("video"),
                        "updated": job["updated"],
                    }
                )
                save(path, report)
                if job["status"] not in {"queued", "running"}:
                    if job["artifacts"].get("quality"):
                        entry["quality"] = await api("GET", f"/api/jobs/{entry['id']}/quality")
                        save(path, report)
                    break
                if time.monotonic() > deadline:
                    raise TimeoutError(
                        f"{name} still running; rerun with the same --report to observe it"
                    )
                await asyncio.sleep(10)
        report["finished"] = time.time()
        report["passed"] = all(c["status"] == "ready" for c in report["cases"].values())
        save(path, report)
        print(
            json.dumps({"passed": report["passed"], "report": str(path)}, ensure_ascii=False),
            flush=True,
        )
        return 0 if report["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--cases", default=",".join(CASES))
    parser.add_argument("--max-cost", type=float, default=1.5)
    parser.add_argument("--timeout", type=int, default=3600)
    raise SystemExit(asyncio.run(main(parser.parse_args())))
