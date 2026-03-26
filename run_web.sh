#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8001}"
METRICS_SOURCE="${METRICS_SOURCE:-local}"
EXTERNAL_MAX_AGE_S="${EXTERNAL_MAX_AGE_S:-5}"
ESCALATION_REGULATOR="${ESCALATION_REGULATOR:-1.0}"
REUSE_RUNNING_SERVER="${REUSE_RUNNING_SERVER:-0}"
ENABLE_MIDI="${ENABLE_MIDI:-0}"
SERVER_PATTERN="sonification_pipeline_async.py --host $HOST --port $PORT"

log() {
  printf '[web] %s\n' "$*"
}

find_server_pids() {
  pgrep -f "$SERVER_PATTERN" || true
}

stop_existing_server() {
  local pids pid
  pids="$(find_server_pids)"
  [[ -n "$pids" ]] || return 0

  log "restarting existing server on $HOST:$PORT to pick up latest code/config"
  while read -r pid; do
    [[ -n "$pid" ]] || continue
    kill "$pid" >/dev/null 2>&1 || true
  done <<< "$pids"

  for _ in $(seq 1 25); do
    if [[ -z "$(find_server_pids)" ]]; then
      return 0
    fi
    sleep 0.2
  done

  pids="$(find_server_pids)"
  if [[ -n "$pids" ]]; then
    log "forcing shutdown for stale server on $HOST:$PORT"
    while read -r pid; do
      [[ -n "$pid" ]] || continue
      kill -9 "$pid" >/dev/null 2>&1 || true
    done <<< "$pids"
  fi
}

start_server() {
  local midi_args=()
  if [[ "$ENABLE_MIDI" == "1" ]]; then
    midi_args+=(--enable-midi)
    log "backend MIDI output enabled"
  else
    log "backend MIDI output disabled (web monitor mode)"
  fi

  log "starting server on $HOST:$PORT (metrics source: $METRICS_SOURCE)"
  "$ROOT_DIR/venv/bin/python" "$ROOT_DIR/sonification_pipeline_async.py" \
    --host "$HOST" \
    --port "$PORT" \
    --metrics-source "$METRICS_SOURCE" \
    --external-max-age-s "$EXTERNAL_MAX_AGE_S" \
    --escalation-regulator "$ESCALATION_REGULATOR" \
    "${midi_args[@]}" &
  sleep 1
}

"$ROOT_DIR/bootstrap.sh"

if [[ "$REUSE_RUNNING_SERVER" == "1" ]] && [[ -n "$(find_server_pids)" ]]; then
  log "server already running on $HOST:$PORT (reuse enabled)"
else
  stop_existing_server
  start_server
fi

log "open http://localhost:$PORT/"
