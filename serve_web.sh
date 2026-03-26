#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8001}"
METRICS_SOURCE="${METRICS_SOURCE:-local}"
EXTERNAL_MAX_AGE_S="${EXTERNAL_MAX_AGE_S:-5}"
MIDI_PORT_HINT="${MIDI_PORT_HINT:-FLUID}"

log() {
  printf '[serve-web] %s\n' "$*"
}

log "bootstrapping environment"
"$ROOT_DIR/bootstrap.sh"

log "starting foreground server on $HOST:$PORT (metrics source: $METRICS_SOURCE)"
exec "$ROOT_DIR/venv/bin/python" "$ROOT_DIR/sonification_pipeline_async.py" \
  --host "$HOST" \
  --port "$PORT" \
  --metrics-source "$METRICS_SOURCE" \
  --external-max-age-s "$EXTERNAL_MAX_AGE_S" \
  --midi-port-hint "$MIDI_PORT_HINT"
