#!/usr/bin/env bash
# Manage a foreground/background redis-server for the Codespace dev environment.
# In production we use the systemd unit at infra/systemd/, not this script.

set -euo pipefail

SCRAPER_HOME="${SCRAPER_HOME:-$(cd "$(dirname "$0")/.." && pwd)}"
PIDFILE="$SCRAPER_HOME/.redis.pid"
LOGFILE="$SCRAPER_HOME/logs/redis.log"
CONF="$SCRAPER_HOME/.redis.conf"

write_conf() {
  cat > "$CONF" <<EOF
port 6379
bind 127.0.0.1 -::1
protected-mode yes
daemonize no
dir $SCRAPER_HOME
pidfile $PIDFILE
logfile $LOGFILE
save ""
appendonly no
EOF
}

start() {
  if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "Redis already running (PID $(cat "$PIDFILE"))."
    return 0
  fi
  write_conf
  mkdir -p "$SCRAPER_HOME/logs"
  nohup redis-server "$CONF" >/dev/null 2>&1 &
  local pid=$!
  echo "$pid" > "$PIDFILE"
  sleep 0.5
  if redis-cli ping >/dev/null 2>&1; then
    echo "Redis started (PID $pid). Log: $LOGFILE"
  else
    echo "Redis failed to start — see $LOGFILE" >&2
    exit 1
  fi
}

stop() {
  if [[ -f "$PIDFILE" ]]; then
    local pid; pid=$(cat "$PIDFILE")
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" && echo "Redis stopped (PID $pid)."
    fi
    rm -f "$PIDFILE"
  else
    echo "No PID file — nothing to stop."
  fi
}

case "${1:-start}" in
  start) start ;;
  stop)  stop ;;
  *)     echo "usage: $0 {start|stop}" >&2; exit 1 ;;
esac
