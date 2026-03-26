#!/usr/bin/env bash
set -euo pipefail

IMAGE_NAME="sonification-container"

PULSE_DIR="/run/user/$(id -u)/pulse"
if [[ ! -d "$PULSE_DIR" ]]; then
  echo "PulseAudio runtime dir not found: $PULSE_DIR"
  echo "Ensure PulseAudio or PipeWire-Pulse is running on the host."
  exit 1
fi

docker run --rm \
  --gpus all \
  --device /dev/snd \
  --ipc=host \
  -e PULSE_RUNTIME_PATH="$PULSE_DIR" \
  -v "$PULSE_DIR":"$PULSE_DIR" \
  "$IMAGE_NAME"
