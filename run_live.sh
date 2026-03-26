#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOUNDFONT="${SOUNDFONT:-/usr/share/sounds/sf2/FluidR3_GM.sf2}"
MIDI_HINT="${MIDI_HINT:-FLUID}"
ESCALATION_REGULATOR="${ESCALATION_REGULATOR:-1.0}"

# Audio driver — default to PortAudio for cross-platform support.
# Override with AUDIO_DRIVER=pulseaudio (or alsa) for legacy Linux setups.
REQUESTED_AUDIO_DRIVER="${AUDIO_DRIVER:-portaudio}"
AUDIO_DRIVER="$REQUESTED_AUDIO_DRIVER"

# MIDI backend for the FluidSynth daemon itself (not mido/python-rtmidi).
# Linux default is ALSA sequencer; script auto-falls back if unavailable.
REQUESTED_MIDI_DRIVER="${MIDI_DRIVER:-alsa_seq}"
MIDI_DRIVER="$REQUESTED_MIDI_DRIVER"

# Audio buffer size (samples per period).  Platform defaults from spec §3.
# Override with AUDIO_BUFSIZE=<n> for custom latency tuning.
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) AUDIO_BUFSIZE="${AUDIO_BUFSIZE:-512}" ;; # Windows
  Darwin) AUDIO_BUFSIZE="${AUDIO_BUFSIZE:-256}" ;;   # macOS CoreAudio
  *)      AUDIO_BUFSIZE="${AUDIO_BUFSIZE:-64}" ;;    # Linux / other
esac

supports_fluidsynth_driver() {
  local kind="$1"  # audio|midi
  local value="$2"
  local help_output
  help_output="$(fluidsynth "-${kind}" help 2>&1 || true)"
  grep -Fq "'${value}'" <<<"$help_output"
}

pick_supported_driver() {
  local kind="$1"
  shift
  local candidate
  for candidate in "$@"; do
    if supports_fluidsynth_driver "$kind" "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

print_driver_help() {
  local kind="$1"
  while IFS= read -r line; do
    printf '[live] %s\n' "$line"
  done < <(fluidsynth "-${kind}" help 2>&1 || true)
}

log() {
  printf '[live] %s\n' "$*"
}

if [[ ! -f "$SOUNDFONT" ]]; then
  printf '[live] soundfont not found: %s\n' "$SOUNDFONT" >&2
  printf '[live] install package fluid-soundfont-gm or set SOUNDFONT env var\n' >&2
  exit 1
fi

if ! command -v fluidsynth >/dev/null 2>&1; then
  printf '[live] fluidsynth binary not found in PATH\n' >&2
  printf '[live] install package fluidsynth and retry\n' >&2
  exit 1
fi

if ! supports_fluidsynth_driver a "$AUDIO_DRIVER"; then
  fallback_audio="$(pick_supported_driver a portaudio pulseaudio pipewire alsa sdl2 file || true)"
  if [[ -n "$fallback_audio" ]]; then
    log "audio driver '$AUDIO_DRIVER' unavailable; falling back to '$fallback_audio'"
    AUDIO_DRIVER="$fallback_audio"
  else
    printf '[live] no usable FluidSynth audio driver detected\n' >&2
    print_driver_help a
    exit 1
  fi
fi

if ! supports_fluidsynth_driver m "$MIDI_DRIVER"; then
  fallback_midi="$(pick_supported_driver m alsa_seq alsa_raw jack oss coremidi winmidi || true)"
  if [[ -n "$fallback_midi" ]]; then
    log "MIDI driver '$MIDI_DRIVER' unavailable; falling back to '$fallback_midi'"
    MIDI_DRIVER="$fallback_midi"
  else
    printf '[live] no usable FluidSynth MIDI driver detected\n' >&2
    print_driver_help m
    exit 1
  fi
fi

"$ROOT_DIR/bootstrap.sh"

if ! pgrep -x fluidsynth >/dev/null 2>&1; then
  log "starting fluidsynth (audio=$AUDIO_DRIVER midi=$MIDI_DRIVER bufsize=$AUDIO_BUFSIZE)"
  fluidsynth -a "$AUDIO_DRIVER" -m "$MIDI_DRIVER" -z "$AUDIO_BUFSIZE" -s -i "$SOUNDFONT" \
    >/tmp/fluidsynth.log 2>&1 &
  sleep 1
  if ! pgrep -x fluidsynth >/dev/null 2>&1; then
    printf '[live] FluidSynth failed to stay running\n' >&2
    printf '[live] tail of /tmp/fluidsynth.log:\n' >&2
    tail -n 40 /tmp/fluidsynth.log >&2 || true
    printf '[live] available audio drivers:\n' >&2
    print_driver_help a >&2
    printf '[live] available MIDI drivers:\n' >&2
    print_driver_help m >&2
    exit 1
  fi
else
  log "fluidsynth already running (leave as-is; stop manually to change driver settings)"
fi

log "starting live sonification"
exec "$ROOT_DIR/venv/bin/python" "$ROOT_DIR/sonification_pipeline.py" \
  --pitch-bend \
  --midi-port "$MIDI_HINT" \
  --escalation-regulator "$ESCALATION_REGULATOR"
