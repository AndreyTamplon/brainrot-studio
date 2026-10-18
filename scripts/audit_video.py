"""Re-audit an existing MP4 for free; --save can reject but never promote a job."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from brainrot import config, quality, store


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id")
    parser.add_argument(
        "--save", action="store_true", help="Save evidence and downgrade failed acceptance"
    )
    args = parser.parse_args()
    job = store.get_job(args.job_id)
    if not job or not job["artifacts"].get("timeline"):
        parser.error("Job needs a video rendered by the frame-aligned renderer")
    if args.save and job["status"] in {"queued", "running"}:
        parser.error("Cannot update a running job")
    artifacts = job["artifacts"]
    report = await quality.audit(
        config.DATA / artifacts["video"],
        artifacts["timeline"],
        job["request"]["language"],
        job["request"]["subtitles"],
        artifacts["technical"],
    )
    if args.save:
        artifacts["quality"] = report
        changes = {"artifacts": artifacts}
        if not report["passed"] and job["status"] == "ready":
            changes.update(status="needs_review", error="; ".join(report["issues"]))
        store.update(job["id"], **changes)
        (config.DATA / "jobs" / job["id"] / "artifacts.json").write_text(store.dumps(artifacts))
        store.event(job["id"], "editor", "independent_audit", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
