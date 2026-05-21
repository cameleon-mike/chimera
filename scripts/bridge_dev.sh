#!/usr/bin/env bash
# Start/stop the uvicorn bridge in the Codespace dev environment.
# Production uses infra/systemd/scraper-bridge.service (Step 1.5).

set -euo pipefail

SCRAPER_HOME="${SCRAPER_HOME:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$SCRAPER_HOME"

PIDFILE="$SCRAPER_HOME/.bridge.pid"
# bridge.log is owned by structlog's FileHandler (structured JSON).
# uvicorn.log captures uvicorn's own stdout/stderr (startup, errors).
UVICORN_LOG="$SCRAPER_HOME/logs/uvicorn.log"
VENV_PY="$SCRAPER_HOME/.venv/bin/python"

# Load env so PORT etc. resolve
set -a; [[ -f scraper.env ]] && . scraper.env; set +a
HOST="${BRIDGE_HOST:-127.0.0.1}"
PORT="${BRIDGE_PORT:-8080}"

start() {
  if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "Bridge already running (PID $(cat "$PIDFILE")) on $HOST:$PORT."
    return 0
  fi
  mkdir -p logs
  nohup "$VENV_PY" -m uvicorn bridge.app:app \
    --host "$HOST" --port "$PORT" --log-level info \
    >> "$UVICORN_LOG" 2>&1 &
  local pid=$!
  echo "$pid" > "$PIDFILE"
  # Wait up to 5s for /health to respond
  for _ in {1..25}; do
    sleep 0.2
    if curl -fsS "http://$HOST:$PORT/health" >/dev/null 2>&1; then
      echo "Bridge started (PID $pid) on http://$HOST:$PORT"
      echo "  app log:     $SCRAPER_HOME/logs/bridge.log"
      echo "  uvicorn log: $UVICORN_LOG"
      return 0
    fi
  done
  echo "Bridge failed to come up — see $UVICORN_LOG" >&2
  exit 1
}

stop() {
  if [[ -f "$PIDFILE" ]]; then
    local pid; pid=$(cat "$PIDFILE")
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" && echo "Bridge stopped (PID $pid)."
    fi
    rm -f "$PIDFILE"
  else
    echo "No PID file — nothing to stop."
  fi
}

status() {
  if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "Bridge running (PID $(cat "$PIDFILE")) on http://$HOST:$PORT"
    curl -fsS "http://$HOST:$PORT/health" && echo
  else
    echo "Bridge not running."
  fi
}

case "${1:-start}" in
  start) start ;;
  stop)  stop ;;
  status) status ;;
  *) echo "usage: $0 {start|stop|status}" >&2; exit 1 ;;
esac
