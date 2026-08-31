#!/usr/bin/env bash
# Start Pit Box. First run creates the venv and installs dependencies.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
  ./.venv/bin/python -m pip install --upgrade pip
  ./.venv/bin/python -m pip install -r requirements.txt
fi

echo "Pit Box running at http://127.0.0.1:8000"
exec ./.venv/bin/python -m uvicorn app.main:app --reload --port 8000
