#!/usr/bin/env bash
set -euo pipefail

pkill -f "sonification_pipeline_async.py" || true
pkill -f "sonification_pipeline.py" || true
pkill -f "python3 -m http.server" || true
pkill -f "telegraf --config .*telegraf_hsp.conf" || true
pkill -x fluidsynth || true

echo "stopped sonification processes"
