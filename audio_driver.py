"""audio_driver — FluidSynth audio driver initialisation (Ubuntu/Linux).

The module attempts the programmatic *pyfluidsynth* path first; if that
binding library is not installed it falls back to launching FluidSynth as
an external process with the correct audio-driver and buffer-size flags.
"""

import os
import subprocess
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Platform-specific period sizes (samples per period / audio buffer size).
# Source: PortAudio integration spec §3 — Platform-Specific Considerations.
# ---------------------------------------------------------------------------

_PERIOD_SIZE_DEFAULT = 64  # Linux — optimal for direct ALSA / PortAudio path

_DEFAULT_SOUNDFONT = "/usr/share/sounds/sf2/FluidR3_GM.sf2"


def period_size() -> int:
    """Return the recommended audio period size (samples)."""
    return _PERIOD_SIZE_DEFAULT


def initialize_audio_driver(
    soundfont: Optional[str] = None,
    device: Optional[str] = None,
) -> Any:
    """Initialise a FluidSynth instance configured to use PortAudio output.

    Tries the programmatic *pyfluidsynth* path first (spec §3 Python Layer).
    Falls back to launching FluidSynth as an external process when the
    binding library is not installed.

    Args:
        soundfont: Path to the SF2 soundfont file.  Uses the system default
            when ``None``.
        device: Optional PortAudio device string in FluidSynth format:
            ``"<device_index>:<host_api_name>:<host_device_name>"``.
            When ``None`` FluidSynth uses its own default device.

    Returns:
        A ``fluidsynth.Synth`` instance (pyfluidsynth path), or a
        ``subprocess.Popen`` handle (external-process path).

    Raises:
        RuntimeError: if neither path succeeds, or no audio device can be
            opened.
    """
    result = _try_pyfluidsynth(soundfont, device)
    if result is not None:
        return result
    return _launch_fluidsynth_process(soundfont, device)


# ---------------------------------------------------------------------------
# Programmatic path — pyfluidsynth bindings (spec §3 Python Layer)
# ---------------------------------------------------------------------------

def _try_pyfluidsynth(
    soundfont: Optional[str],
    device: Optional[str],
) -> Any:
    """Return an initialised ``fluidsynth.Synth``, or ``None`` if unavailable."""
    try:
        import fluidsynth  # type: ignore[import]
    except ImportError:
        return None

    synth = fluidsynth.Synth()

    # Replace ALSA with PortAudio for cross-platform support (spec §3).
    synth.setting("audio.driver", "portaudio")

    # Optional: target a specific PortAudio device.
    # Format: "<device_index>:<host_api_name>:<host_device_name>"
    if device:
        synth.setting("audio.portaudio.device", device)

    # Platform-specific buffer tuning — Hybrid Approach (spec §3).
    synth.setting("audio.period-size", period_size())

    try:
        synth.start(driver="portaudio")
    except Exception as exc:
        raise RuntimeError(
            f"Failed to start PortAudio driver via pyfluidsynth: {exc}"
        ) from exc

    if soundfont:
        sfid = synth.sfload(soundfont, update_midi_pitch=True)
        if sfid == -1:
            raise RuntimeError(
                f"FluidSynth could not load soundfont: {soundfont}"
            )
        synth.sfont_select(0, sfid)

    return synth


# ---------------------------------------------------------------------------
# External-process fallback — FluidSynth CLI with PortAudio flag
# ---------------------------------------------------------------------------

def _launch_fluidsynth_process(
    soundfont: Optional[str],
    device: Optional[str],  # noqa: ARG001 — reserved for future PortAudio device pass-through
) -> "subprocess.Popen[bytes]":
    """Start FluidSynth as an external process using the PortAudio driver.

    Reads ``$AUDIO_DRIVER`` (default: ``portaudio``) and ``$AUDIO_BUFSIZE``
    (default: platform-specific) to allow operator-level overrides without
    code changes.  Corresponds to the shell invocation managed by
    ``run_live.sh``.
    """
    audio_driver_name = os.environ.get("AUDIO_DRIVER", "portaudio")
    buf_size = int(os.environ.get("AUDIO_BUFSIZE", str(period_size())))
    sf = soundfont or _DEFAULT_SOUNDFONT

    cmd = [
        "fluidsynth",
        "-a", audio_driver_name,
        "-m", "alsa_seq",
        "-z", str(buf_size),
        "-s", "-i",
        sf,
    ]

    try:
        proc: "subprocess.Popen[bytes]" = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "FluidSynth executable not found.\n"
            "  Install: sudo apt install fluidsynth"
        ) from exc
    except OSError as exc:
        raise RuntimeError(f"Failed to launch FluidSynth: {exc}") from exc

    return proc
