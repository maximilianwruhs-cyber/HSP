#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$ROOT_DIR/venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"

log() {
  printf '[bootstrap] %s\n' "$*"
}

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf '[bootstrap] missing required command: %s\n' "$1" >&2
    return 1
  fi
}

need_cmd "$PYTHON_BIN"

if [[ ! -d "$VENV_DIR" ]]; then
  log "creating virtual environment in $VENV_DIR"
  if "$PYTHON_BIN" -m venv "$VENV_DIR" >/dev/null 2>&1; then
    :
  else
    log "python venv module unavailable, trying virtualenv fallback"
    "$PYTHON_BIN" -m pip install --user --break-system-packages virtualenv
    "$HOME/.local/bin/virtualenv" "$VENV_DIR"
  fi
fi

log "installing python dependencies"
"$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
"$VENV_DIR/bin/python" -m pip install -r "$ROOT_DIR/requirements.txt"

log "bootstrap complete"
