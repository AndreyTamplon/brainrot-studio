import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
DATA = Path(os.getenv("DATA_DIR", str(ROOT / "data"))).resolve()
DATA.mkdir(parents=True, exist_ok=True)
for directory in ("jobs", "media", "cache"):
    (DATA / directory).mkdir(exist_ok=True)

ORCHESTRATOR_MODEL = os.getenv("ORCHESTRATOR_MODEL", "xiaomi/mimo-v2.6-pro")
WRITER_MODEL = os.getenv("WRITER_MODEL", ORCHESTRATOR_MODEL)
SPECIALIST_MODEL = os.getenv("SPECIALIST_MODEL", "xiaomi/mimo-v2.6-flash")
AUDIO_REVIEW_MODEL = os.getenv("AUDIO_REVIEW_MODEL", "google/gemini-3.8-flash")
VISION_MODEL = os.getenv("VISION_MODEL", AUDIO_REVIEW_MODEL)
SCRIPT_REVIEW_MODEL = os.getenv("SCRIPT_REVIEW_MODEL", VISION_MODEL)
TTS_MODEL = os.getenv("TTS_MODEL", "fish-audio/s2.1-pro")
TOTAL_BUDGET = min(float(os.getenv("TOTAL_BUDGET_USD", "10")), 10.0)
RUN_BUDGET = min(float(os.getenv("MAX_RUN_COST_USD", "1.5")), TOTAL_BUDGET)


def api_key() -> str:
    # Re-read the local key after UI setup; never include it in a response or log.
    load_dotenv(ROOT / ".env", override=True)
    return os.getenv("OPENROUTER_API_KEY", "")


def save_key(key: str) -> None:
    if not key.startswith("sk-or-") or len(key) < 25 or any(c.isspace() for c in key):
        raise ValueError("Некорректный ключ OpenRouter")
    target = ROOT / ".env"
    lines = target.read_text().splitlines() if target.exists() else []
    lines = [line for line in lines if not line.startswith("OPENROUTER_API_KEY=")]
    lines.append(f"OPENROUTER_API_KEY={key}")
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write("\n".join(lines) + "\n")
    os.environ["OPENROUTER_API_KEY"] = key
