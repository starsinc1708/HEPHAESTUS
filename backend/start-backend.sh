#!/usr/bin/env bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
# Load .env if present (Python-dotenv style one-var-per-line)
if [ -f .env ]; then
  set -a; . .env; set +a
fi
exec uvicorn app.main:app --host "${HEPHAESTUS_DASHBOARD_HOST:-127.0.0.1}" --port "${HEPHAESTUS_DASHBOARD_PORT:-8766}"
