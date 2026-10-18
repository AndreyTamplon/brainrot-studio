"""Listen to local voice auditions through the project's metered audio-capable model."""

import argparse
import asyncio
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from brainrot import config, media, store
from brainrot.provider import Gateway


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=config.ORCHESTRATOR_MODEL)
    parser.add_argument("files", nargs="+")
    args = parser.parse_args()
    gateway = Gateway("voice-audition-review", 1.5)
    for name in args.files:
        path = Path(name).resolve()
        duration = (await media.probe(path))["duration"]
        content = [
            {
                "type": "text",
                "text": f"This audio is exactly {duration:.2f} seconds long. "
                "Listen to the actual audio. Evaluate Russian pronunciation, word stress, "
                "foreign accent, unnatural pauses and synthetic defects. Do not infer quality from "
                "intelligibility alone. First transcribe exactly what you heard WITHOUT being given "
                "a reference text. Then give specific timestamped audible issues, stressed syllables "
                "where wrong, and a 1-5 native pronunciation score. It is fine to find no issues. "
                "Do not invent defects. Do not give timestamps beyond the actual duration. "
                "Do not claim a particular character identity. Answer in Russian.",
            },
            {
                "type": "input_audio",
                "input_audio": {
                    "data": base64.b64encode(path.read_bytes()).decode(),
                    "format": path.suffix.lstrip("."),
                },
            },
        ]
        response = await gateway.chat(
            args.model,
            [{"role": "user", "content": content}],
            "voice_audition_review",
            max_tokens=2200,
        )
        report = {"file": path.name, "model": args.model, **response}
        suffix = args.model.split("/")[-1]
        path.with_suffix(f".{suffix}.review.json").write_text(store.dumps(report))
        print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
