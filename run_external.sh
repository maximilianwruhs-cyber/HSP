#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8001}"
EXTERNAL_MAX_AGE_S="${EXTERNAL_MAX_AGE_S:-5}"
TELEGRAF_CONFIG="${TELEGRAF_CONFIG:-$ROOT_DIR/telegraf_hsp.conf}"

log() {
  printf '[external] %s\n' "$*"
}

if ! command -v telegraf >/dev/null 2>&1; then
  printf '[external] missing telegraf binary\n' >&2
  printf '[external] install telegraf, then re-run this script\n' >&2
  exit 1
fi

if [[ ! -f "$TELEGRAF_CONFIG" ]]; then
  printf '[external] telegraf config not found: %s\n' "$TELEGRAF_CONFIG" >&2
  exit 1
fi

METRICS_SOURCE=external EXTERNAL_MAX_AGE_S="$EXTERNAL_MAX_AGE_S" HOST="$HOST" PORT="$PORT" "$ROOT_DIR/run_web.sh"

if pgrep -f "telegraf --config $TELEGRAF_CONFIG" >/dev/null 2>&1; then
  log "telegraf already running with $TELEGRAF_CONFIG"
else
  log "starting telegraf with $TELEGRAF_CONFIG"
  telegraf --config "$TELEGRAF_CONFIG" >/tmp/telegraf_hsp.log 2>&1 &
  sleep 1
fi

log "open http://localhost:$PORT/"
log "telegraf log at /tmp/telegraf_hsp.log"
