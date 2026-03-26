#!/usr/bin/env bash
set -euo pipefail

# Install host dependencies for sonification, audio routing and container GPU support.
sudo apt update
sudo apt install -y \
  fluidsynth \
  fluid-soundfont-gm \
  pulseaudio \
  pipewire \
  alsa-utils \
  libportaudio2 \
  portaudio19-dev \
  python3 \
  python3-pip

# Configure Docker runtime for NVIDIA GPUs (Commented out as it might fail without proper repos)
# sudo nvidia-ctk runtime configure --runtime=docker
# sudo systemctl restart docker

SOUNDFONT="/usr/share/sounds/sf2/FluidR3_GM.sf2"
if [[ ! -f "$SOUNDFONT" ]]; then
  echo "SoundFont not found at $SOUNDFONT"
  exit 1
fi

supports_audio_driver() {
  local driver="$1"
  fluidsynth -a help 2>&1 | grep -Fq "'${driver}'"
}

pick_audio_driver() {
  local candidate
  for candidate in "$@"; do
    if supports_audio_driver "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

# Start FluidSynth in daemon mode if it is not already running.
if pgrep -x fluidsynth >/dev/null 2>&1; then
  echo "FluidSynth already running"
else
  # Use server mode (-s) so FluidSynth stays alive in the background.
  # Default to PortAudio driver for cross-platform support.
  # Override: AUDIO_DRIVER=pulseaudio ./setup_host.sh
  AUDIO_DRIVER="${AUDIO_DRIVER:-portaudio}"
  if ! supports_audio_driver "$AUDIO_DRIVER"; then
    FALLBACK_AUDIO_DRIVER="$(pick_audio_driver portaudio pulseaudio pipewire alsa sdl2 file || true)"
    if [[ -z "$FALLBACK_AUDIO_DRIVER" ]]; then
      echo "No usable FluidSynth audio driver found. Available drivers:" >&2
      fluidsynth -a help >&2 || true
      exit 1
    fi
    echo "Audio driver '$AUDIO_DRIVER' unavailable; using '$FALLBACK_AUDIO_DRIVER'" >&2
    AUDIO_DRIVER="$FALLBACK_AUDIO_DRIVER"
  fi
  AUDIO_BUFSIZE="${AUDIO_BUFSIZE:-64}"
  fluidsynth -a "$AUDIO_DRIVER" -m alsa_seq -z "$AUDIO_BUFSIZE" -s -i "$SOUNDFONT" \
    >/tmp/fluidsynth.log 2>&1 &
  sleep 1
  if ! pgrep -x fluidsynth >/dev/null 2>&1; then
    echo "FluidSynth failed to start. Tail of /tmp/fluidsynth.log:" >&2
    tail -n 40 /tmp/fluidsynth.log >&2 || true
    exit 1
  fi
fi

echo "Available ALSA sequencer output ports:"
aconnect -o || true

echo "Host setup complete."
