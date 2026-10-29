#!/usr/bin/env bash
# Install dependencies and initialise the material index.
set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-python3}"

if [ ! -d .venv ]; then
  "$PYTHON" -m venv .venv
fi
# shellcheck disable=SC1091
. .venv/bin/activate

python -m pip install --upgrade pip >/dev/null
python -m pip install -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo "created .env from .env.example — set MINIMAX_API_KEY before running 'task plan'"
fi

echo "--- doctor ---"
python -m sdd_context doctor || true

echo "--- ingest ---"
python -m sdd_context ingest
