#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
uv sync --frozen
npm --prefix frontend ci --no-audit --no-fund
npm --prefix frontend run build
exec .venv/bin/python -m uvicorn brainrot.app:app --host 127.0.0.1 --port "${PORT:-8000}" --no-access-log --timeout-graceful-shutdown 10
