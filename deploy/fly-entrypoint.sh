#!/usr/bin/env bash
# Container entrypoint. Runs the tunnel and the app side by side, and makes sure
# that if either one dies the whole container dies with it.
#
# That last part matters more than it looks. If cloudflared exits and uvicorn
# keeps running, Fly sees a healthy machine while the site is unreachable --
# the worst kind of outage, because nothing alerts. Exiting non-zero instead
# makes Fly restart the machine, which fixes it.
set -euo pipefail

HOST="${PITBOX_HOST:-127.0.0.1}"
PORT="${PITBOX_PORT:-8000}"

pids=()

if [[ -n "${TUNNEL_TOKEN:-}" ]]; then
  echo "[entrypoint] starting cloudflared"
  # --no-autoupdate because the container is the unit of upgrade here: a binary
  # that rewrites itself at runtime undoes the point of a reproducible image.
  cloudflared tunnel --no-autoupdate --loglevel info run --token "$TUNNEL_TOKEN" &
  pids+=("$!")
else
  echo "[entrypoint] TUNNEL_TOKEN is not set -- no tunnel."
  echo "[entrypoint] The app is only reachable if fly.toml publishes a port."
  if [[ "$HOST" == "127.0.0.1" ]]; then
    echo "[entrypoint] WARNING: listening on 127.0.0.1 with no tunnel means"
    echo "[entrypoint] nothing can reach this container. Set TUNNEL_TOKEN, or"
    echo "[entrypoint] set PITBOX_HOST=0.0.0.0 and expose a port in fly.toml."
  fi
fi

echo "[entrypoint] starting CarHub on ${HOST}:${PORT}"
python -m uvicorn app.main:app --host "$HOST" --port "$PORT" --log-level info &
pids+=("$!")

# Block until the first one exits, then take the rest down with it.
wait -n
status=$?
echo "[entrypoint] a process exited (status ${status}); shutting down the rest"
kill "${pids[@]}" 2>/dev/null || true
wait || true
exit 1
