#!/usr/bin/env bash
# Start both dev servers: FastAPI on :8000 and Vite on :5173.
#
# Open http://localhost:5173 — Vite serves the UI with hot reload and proxies
# /api straight through to FastAPI, so there is no CORS setup and no base URL
# to configure.
#
# The macOS / Linux counterpart to dev.ps1. Node is looked for on PATH first,
# then nvm, then a portable unpacked copy under ~/.local/nodejs — nothing is
# installed system-wide and nothing outside this shell is changed.

set -euo pipefail
cd "$(dirname "$0")"

if [ -t 1 ]; then
  dim=$'\e[90m'; green=$'\e[32m'; cyan=$'\e[36m'; red=$'\e[31m'; yellow=$'\e[33m'; off=$'\e[0m'
else
  dim=''; green=''; cyan=''; red=''; yellow=''; off=''
fi

# --- locate Node --------------------------------------------------------------
if ! command -v node >/dev/null 2>&1; then
  # nvm installs into the shell, not the system, so a script has to source it.
  if [ -s "${NVM_DIR:-$HOME/.nvm}/nvm.sh" ]; then
    # shellcheck disable=SC1091
    . "${NVM_DIR:-$HOME/.nvm}/nvm.sh" >/dev/null 2>&1 || true
  fi
fi

if ! command -v node >/dev/null 2>&1; then
  # Portable tarball unpacked as ~/.local/nodejs/node-v24.19.0-darwin-arm64/
  node_root="${NODE_ROOT:-$HOME/.local/nodejs}"
  if [ -d "$node_root" ]; then
    node_dir=$(find "$node_root" -maxdepth 1 -type d -name 'node-*' | sort -r | head -n 1)
    if [ -n "$node_dir" ] && [ -x "$node_dir/bin/node" ]; then
      PATH="$node_dir/bin:$PATH"
      export PATH
    fi
  fi
fi

if ! command -v node >/dev/null 2>&1; then
  printf '%sNode not found.%s\n' "$red" "$off"
  printf '%sInstall it with:  brew install node        (macOS)%s\n' "$yellow" "$off"
  printf '%s                  sudo apt install nodejs  (Debian/Ubuntu)%s\n' "$yellow" "$off"
  printf '%sor unpack a portable build into ~/.local/nodejs — see docs/FRONTEND.md.%s\n' "$yellow" "$off"
  exit 1
fi

printf '%snode %s  npm %s%s\n' "$dim" "$(node --version)" "$(npm --version)" "$off"

# --- Python env ---------------------------------------------------------------
if [ ! -d .venv ]; then
  printf '%sCreating virtual environment...%s\n' "$cyan" "$off"
  python3 -m venv .venv
  ./.venv/bin/python -m pip install --upgrade pip
  ./.venv/bin/python -m pip install -r requirements.txt
fi

# --- frontend deps ------------------------------------------------------------
if [ ! -d frontend/node_modules ]; then
  printf '%sInstalling frontend dependencies...%s\n' "$cyan" "$off"
  (cd frontend && npm install)
fi

# --- run both -----------------------------------------------------------------
api_pid=""
cleanup() {
  if [ -n "$api_pid" ] && kill -0 "$api_pid" 2>/dev/null; then
    printf '%sStopping API...%s\n' "$dim" "$off"
    kill "$api_pid" 2>/dev/null || true
    # Give uvicorn's reloader a moment to take its worker down with it.
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      kill -0 "$api_pid" 2>/dev/null || break
      sleep 0.2
    done
    kill -9 "$api_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

./.venv/bin/python -m uvicorn app.main:app --port 8000 --reload &
api_pid=$!

printf '\n'
printf '%s  API  http://127.0.0.1:8000/docs%s\n' "$dim" "$off"
printf '%s  UI   http://localhost:5173%s\n' "$green" "$off"
printf '%s  Ctrl+C stops both.%s\n' "$dim" "$off"
printf '\n'

cd frontend
npm run dev
