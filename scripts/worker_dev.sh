#!/usr/bin/env bash
# Start/stop an RQ worker in the Codespace dev environment.
# Production uses infra/systemd/scraper-worker@.service (Step 1.5).

set -euo pipefail

SCRAPER_HOME="${SCRAPER_HOME:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$SCRAPER_HOME"

PIDFILE="$SCRAPER_HOME/.worker.pid"
LOGFILE="$SCRAPER_HOME/logs/worker.log"
VENV="$SCRAPER_HOME/.venv/bin"

set -a; [[ -f scraper.env ]] && . scraper.env; set +a
REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6379/0}"

start() {
  if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "Worker already running (PID $(cat "$PIDFILE"))."
    return 0
  fi
  mkdir -p logs
  # rq picks queues in the listed order — high first, then normal, then low.
  nohup "$VENV/rq" worker --url "$REDIS_URL" --with-scheduler high normal low \
    >> "$LOGFILE" 2>&1 &
  local pid=$!
  echo "$pid" > "$PIDFILE"
  sleep 0.4
  if kill -0 "$pid" 2>/dev/null; then
    echo "Worker started (PID $pid) — log: $LOGFILE"
  else
    echo "Worker failed to start — see $LOGFILE" >&2
    exit 1
  fi
}

stop() {
  if [[ -f "$PIDFILE" ]]; then
    local pid; pid=$(cat "$PIDFILE")
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" && echo "Worker stopped (PID $pid)."
    fi
    rm -f "$PIDFILE"
  else
    echo "No PID file — nothing to stop."
  fi
}

status() {
  if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "Worker running (PID $(cat "$PIDFILE"))"
  else
    echo "Worker not running."
  fi
  "$VENV/rq" info --url "$REDIS_URL" 2>/dev/null || true
}

case "${1:-start}" in
  start) start ;;
  stop)  stop ;;
  status) status ;;
  *) echo "usage: $0 {start|stop|status}" >&2; exit 1 ;;
esac
