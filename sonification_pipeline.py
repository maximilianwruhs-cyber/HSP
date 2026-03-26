import argparse
import subprocess
import time
from collections import deque
from typing import Dict, Tuple

import mido
import psutil
from mido import Message

from machine_inputs import MachineInputTracker

BPM = 120
NOTE_LENGTH_SECONDS = 0.1
BEAT_DURATION = 60 / BPM
BASE_SAMPLE_HZ = 1.0 / BEAT_DURATION
MIN_SAMPLE_HZ = 2.4
MAX_SAMPLE_HZ = 9.5
MIN_NOTE_LENGTH_SECONDS = 0.035
MAX_NOTE_LENGTH_SECONDS = 0.16
DROID_MIDI_PROGRAM = 103  # GM FX 8 (Sci-Fi)
DROID_SWEEP_MIN = 1200
DROID_SWEEP_MAX = 6200
SCALE_NOTES = [60, 62, 63, 65, 67, 68, 70]  # C natural minor
SMOOTH_WINDOW = 5


class Smoother:
    """Simple moving-average smoother for hardware metrics."""

    def __init__(self, window: int = SMOOTH_WINDOW):
        self.window = window
        self.queues = {
            "cpu": deque(maxlen=window),
            "ram": deque(maxlen=window),
            "gpu": deque(maxlen=window),
        }

    def smooth(self, metric: str, value: float) -> float:
        if metric not in self.queues:
            raise ValueError(f"Unknown metric: {metric}")
        self.queues[metric].append(value)
        return sum(self.queues[metric]) / len(self.queues[metric])


def clamp(value: int, min_value: int, max_value: int) -> int:
    return max(min_value, min(value, max_value))


def clamp_float(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(value, max_value))


def extract_cpu_ram() -> Tuple[float, float]:
    cpu = psutil.cpu_percent(interval=None)
    ram = psutil.virtual_memory().percent
    return cpu, ram


def extract_gpu() -> float:
    """
    Extract GPU utilization using the multi-GPU detector.
    Returns average utilization across all GPUs (0-100).
    """
    try:
        from gpu_detector import extract_gpu
        return extract_gpu()
    except Exception:
        # Fallback to original nvidia-smi method if import fails
        try:
            output = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
            # Multi-GPU systems can return multiple lines. Use the average.
            values = [float(line) for line in output.splitlines() if line.strip()]
            return sum(values) / len(values) if values else 0.0
        except Exception:
            return 0.0


def extract_iowait_percent() -> float:
    try:
        times = psutil.cpu_times_percent(interval=None)
        return float(getattr(times, "iowait", 0.0))
    except Exception:
        return 0.0


class ThroughputTracker:
    """Tracks disk/network/system event throughput for cadence control."""

    def __init__(self) -> None:
        self.last_time = time.monotonic()
        self.last_net_packets = self._read_net_packets_total()
        self.last_disk_ops = self._read_disk_ops_total()
        self.last_ctx_switches = self._read_ctx_switches_total()
        self.last_interrupts = self._read_interrupts_total()

    @staticmethod
    def _read_net_packets_total() -> float:
        io = psutil.net_io_counters()
        if io is None:
            return 0.0
        return float(io.packets_sent + io.packets_recv)

    @staticmethod
    def _read_disk_ops_total() -> float:
        io = psutil.disk_io_counters()
        if io is None:
            return 0.0
        return float(io.read_count + io.write_count)

    @staticmethod
    def _read_ctx_switches_total() -> float:
        stats = psutil.cpu_stats()
        return float(stats.ctx_switches)

    @staticmethod
    def _read_interrupts_total() -> float:
        stats = psutil.cpu_stats()
        return float(stats.interrupts)

    def sample(self) -> Dict[str, float]:
        now = time.monotonic()
        elapsed = max(now - self.last_time, 1e-6)

        net_packets_total = self._read_net_packets_total()
        disk_ops_total = self._read_disk_ops_total()
        ctx_switches_total = self._read_ctx_switches_total()
        interrupts_total = self._read_interrupts_total()

        net_pps = max(0.0, (net_packets_total - self.last_net_packets) / elapsed)
        disk_iops = max(0.0, (disk_ops_total - self.last_disk_ops) / elapsed)
        ctx_switches_ps = max(0.0, (ctx_switches_total - self.last_ctx_switches) / elapsed)
        interrupts_ps = max(0.0, (interrupts_total - self.last_interrupts) / elapsed)

        self.last_time = now
        self.last_net_packets = net_packets_total
        self.last_disk_ops = disk_ops_total
        self.last_ctx_switches = ctx_switches_total
        self.last_interrupts = interrupts_total

        return {
            "net_pps": net_pps,
            "disk_iops": disk_iops,
            "ctx_switches_ps": ctx_switches_ps,
            "interrupts_ps": interrupts_ps,
        }


class NaturalSamplingClock:
    """Adaptive sampling clock that follows machine activity within safe bounds."""

    def __init__(
        self,
        base_hz: float = BASE_SAMPLE_HZ,
        min_hz: float = MIN_SAMPLE_HZ,
        max_hz: float = MAX_SAMPLE_HZ,
        escalation_regulator: float = 1.0,
    ) -> None:
        self.base_hz = max(min_hz, min(base_hz, max_hz))
        self.min_hz = min_hz
        self.max_hz = max_hz
        self.escalation_regulator = clamp_float(escalation_regulator, 0.35, 2.5)
        self.current_hz = self.base_hz
        self.last_metrics = {"cpu": 0.0, "ram": 0.0, "gpu": 0.0}
        self.last_activity_score = 0.0

    @staticmethod
    def _clamp01(value: float) -> float:
        return max(0.0, min(value, 1.0))

    def update(
        self,
        metrics: Dict[str, float],
        rates: Dict[str, float],
        extra: Dict[str, float],
    ) -> Tuple[float, float]:
        cpu = float(metrics.get("cpu", 0.0))
        ram = float(metrics.get("ram", 0.0))
        gpu = float(metrics.get("gpu", 0.0))

        delta_cpu = abs(cpu - self.last_metrics["cpu"]) / 100.0
        delta_ram = abs(ram - self.last_metrics["ram"]) / 100.0
        delta_gpu = abs(gpu - self.last_metrics["gpu"]) / 100.0
        delta_score = self._clamp01((delta_cpu + delta_ram + delta_gpu) / 3.0)

        io_score = self._clamp01(
            ((rates.get("net_pps", 0.0) / 40000.0) + (rates.get("disk_iops", 0.0) / 3000.0)) / 2.0
        )
        scheduler_score = self._clamp01(
            ((rates.get("ctx_switches_ps", 0.0) / 160000.0) + (rates.get("interrupts_ps", 0.0) / 50000.0)) / 2.0
        )
        reliability_score = self._clamp01(
            (extra.get("net_errors_ps", 0.0) + extra.get("net_drops_ps", 0.0)) / 20.0
        )
        pressure_score = self._clamp01(
            max(extra.get("disk_busy_pct", 0.0) / 100.0, extra.get("power_w", 0.0) / 120.0)
        )

        motion_score = self._clamp01(
            (delta_score * 0.35)
            + (io_score * 0.25)
            + (scheduler_score * 0.20)
            + (reliability_score * 0.10)
            + (pressure_score * 0.10)
        )

        load_score = self._clamp01(
            ((cpu / 100.0) * 0.50)
            + ((ram / 100.0) * 0.18)
            + ((gpu / 100.0) * 0.20)
            + (pressure_score * 0.12)
        )

        load_weight = self._clamp01(0.55 + ((self.escalation_regulator - 1.0) * 0.18))
        motion_weight = 1.0 - load_weight

        activity_score = self._clamp01((motion_score * motion_weight) + (load_score * load_weight))
        if load_score > 0.70:
            activity_score = self._clamp01(
                activity_score + ((load_score - 0.70) * (0.50 * self.escalation_regulator))
            )
        if activity_score > 0.55:
            activity_score = self._clamp01(
                activity_score + ((activity_score - 0.55) * (0.35 * self.escalation_regulator))
            )

        target_hz = self.min_hz + (self.max_hz - self.min_hz) * activity_score
        rise_alpha = self._clamp01(0.55 + ((self.escalation_regulator - 1.0) * 0.18))
        fall_alpha = self._clamp01(0.22 + ((self.escalation_regulator - 1.0) * 0.06))
        alpha = rise_alpha if target_hz > self.current_hz else fall_alpha
        self.current_hz = (self.current_hz * (1.0 - alpha)) + (target_hz * alpha)

        self.last_metrics = {"cpu": cpu, "ram": ram, "gpu": gpu}
        self.last_activity_score = activity_score

        interval_seconds = 1.0 / max(self.current_hz, 1e-6)
        return interval_seconds, activity_score


def map_to_midi(
    cpu: float,
    ram: float,
    gpu: float,
    use_pitch_bend: bool = False,
    activity_score: float = 0.0,
    phrase_step: int = 0,
    iowait_pct: float = 0.0,
    disk_busy_pct: float = 0.0,
) -> Tuple[int, int, int, int]:
    cpu = clamp(int(cpu), 0, 100)
    ram = clamp(int(ram), 0, 100)
    gpu = clamp(int(gpu), 0, 100)
    activity_score = clamp_float(activity_score, 0.0, 1.0)

    scaled_index = (cpu / 100) * (len(SCALE_NOTES) - 1)
    index = int(scaled_index)

    if activity_score >= 0.65:
        phrase = [0, 3, 5, 2, -2, 4]
    elif activity_score >= 0.35:
        phrase = [0, 2, -1, 3, -2, 1]
    else:
        phrase = [0, 2, -2, 3, -1, 4, -3, 1]

    phrase_offset = phrase[phrase_step % len(phrase)]
    if disk_busy_pct > 70.0 and (phrase_step % 4 == 3):
        phrase_offset += 1
    if iowait_pct > 20.0 and (phrase_step % 4 == 1):
        phrase_offset -= 1

    note = SCALE_NOTES[clamp(index + phrase_offset, 0, len(SCALE_NOTES) - 1)]
    if phrase_step % 6 == 2:
        note = clamp(note + 12, 0, 127)
    elif phrase_step % 6 == 5 and activity_score < 0.50:
        note = clamp(note - 12, 0, 127)

    if activity_score > 0.72 and (phrase_step % 5 in (1, 3)):
        note = clamp(note + 12, 0, 127)
    elif activity_score < 0.20 and (phrase_step % 8 == 7):
        note = clamp(note - 12, 0, 127)

    if disk_busy_pct > 85.0 and (phrase_step % 6 == 4):
        note = clamp(note + 7, 0, 127)

    pitch_bend = 0
    if use_pitch_bend:
        fractional = scaled_index - index
        vibrato = (activity_score * 0.14) + min(disk_busy_pct / 1000.0, 0.06)
        if phrase_step % 2 == 1:
            vibrato *= -1.0
        # Pitchwheel range is -8192..8191.
        pitch_bend = clamp(int((fractional + vibrato) * 4096), -8192, 8191)

    velocity = clamp(int((ram / 100) * 127 + activity_score * 8), 0, 127)
    modulation = clamp(int((gpu / 100) * 104 + (disk_busy_pct / 100.0) * 23), 0, 127)

    return note, velocity, modulation, pitch_bend


def play_note(
    port: mido.ports.BaseOutput,
    note: int,
    velocity: int,
    modulation: int,
    pitch_bend: int,
    note_length_seconds: float = NOTE_LENGTH_SECONDS,
    activity_score: float = 0.0,
    phrase_step: int = 0,
    net_pps: float = 0.0,
    droid_mode: bool = True,
) -> None:
    port.send(Message("control_change", control=1, value=modulation))
    note_length_seconds = max(note_length_seconds, 0.01)

    if not droid_mode:
        if pitch_bend != 0:
            port.send(Message("pitchwheel", pitch=pitch_bend))
        port.send(Message("note_on", note=note, velocity=velocity))
        time.sleep(note_length_seconds)
        port.send(Message("note_off", note=note, velocity=0))
        if pitch_bend != 0:
            port.send(Message("pitchwheel", pitch=0))
        return

    cutoff = clamp(int(50 + (activity_score * 54) + (min(net_pps / 15000.0, 1.0) * 18)), 0, 127)
    resonance = clamp(int(45 + activity_score * 42), 0, 127)
    expression = clamp(int(36 + velocity * 0.72), 0, 127)
    port.send(Message("control_change", control=74, value=cutoff))
    port.send(Message("control_change", control=71, value=resonance))
    port.send(Message("control_change", control=11, value=expression))

    sweep_activity = max(activity_score, min(net_pps / 25000.0, 1.0) * 0.8)
    sweep_span = int(DROID_SWEEP_MIN + (DROID_SWEEP_MAX - DROID_SWEEP_MIN) * sweep_activity)
    sweep_span = clamp(sweep_span, DROID_SWEEP_MIN, DROID_SWEEP_MAX)
    if phrase_step % 2 == 1:
        sweep_span *= -1

    sweep_start = clamp(pitch_bend - (sweep_span // 2), -8192, 8191)
    sweep_end = clamp(pitch_bend + (sweep_span // 2), -8192, 8191)

    port.send(Message("pitchwheel", pitch=sweep_start))
    port.send(Message("note_on", note=note, velocity=velocity))

    primary_len = max(note_length_seconds * (0.55 + (activity_score * 0.2)), 0.01)
    time.sleep(primary_len)
    port.send(Message("pitchwheel", pitch=sweep_end))
    port.send(Message("note_off", note=note, velocity=0))

    accent_budget = max(note_length_seconds - primary_len, 0.0)
    accent_trigger = activity_score > 0.22 or (phrase_step % 3 == 1)
    if accent_trigger and accent_budget > 0.015:
        chirp_step = 2 if (phrase_step % 4 in (0, 3)) else -2
        chirp_note = clamp(note + chirp_step, 0, 127)
        chirp_velocity = clamp(int(velocity * (0.58 + 0.28 * activity_score)), 1, 127)
        port.send(Message("note_on", note=chirp_note, velocity=chirp_velocity))
        time.sleep(max(accent_budget * 0.75, 0.01))
        port.send(Message("note_off", note=chirp_note, velocity=0))
        tail = accent_budget * 0.25
        if tail > 0.005:
            time.sleep(tail)
    elif accent_budget > 0.0:
        time.sleep(accent_budget)

    port.send(Message("pitchwheel", pitch=0))


def resolve_midi_port(preferred_name: str = "") -> mido.ports.BaseOutput:
    names = mido.get_output_names()
    if not names:
        raise IOError("No MIDI output ports available")

    if preferred_name:
        for name in names:
            if preferred_name in name:
                return mido.open_output(name)

    # Prefer synth ports to avoid selecting the silent Midi Through endpoint.
    for name in names:
        if "fluid" in name.lower():
            return mido.open_output(name)

    for name in names:
        if "midi through" not in name.lower():
            return mido.open_output(name)

    return mido.open_output(names[0])


def initialize_midi_voice(
    port: mido.ports.BaseOutput,
    midi_program: int = DROID_MIDI_PROGRAM,
    droid_mode: bool = True,
) -> None:
    program = clamp(int(midi_program), 0, 127)
    try:
        port.send(Message("program_change", program=program))
        if droid_mode:
            port.send(Message("control_change", control=74, value=88))
            port.send(Message("control_change", control=71, value=76))
            port.send(Message("control_change", control=11, value=100))
            port.send(Message("pitchwheel", pitch=0))
    except Exception as exc:
        print(f"MIDI voice init warning: {exc}")


def gather_metrics(smoother: Smoother) -> Dict[str, float]:
    cpu_raw, ram_raw = extract_cpu_ram()
    gpu_raw = extract_gpu()
    return {
        "cpu_usage": smoother.smooth("cpu", cpu_raw),
        "ram_usage": smoother.smooth("ram", ram_raw),
        "gpu_usage": smoother.smooth("gpu", gpu_raw),
    }


def run_self_check(midi_port_hint: str = "") -> bool:
    checks_ok = True

    cpu, ram = extract_cpu_ram()
    print(f"CPU metric available: {cpu:.1f}%")
    print(f"RAM metric available: {ram:.1f}%")

    names = mido.get_output_names()
    if not names:
        print("MIDI check failed: no MIDI output ports available")
        checks_ok = False
    else:
        selected_name = names[0]
        if midi_port_hint:
            matched = [name for name in names if midi_port_hint in name]
            if not matched:
                print(
                    f"MIDI check failed: no output matches hint '{midi_port_hint}' (available: {names})"
                )
                checks_ok = False
            else:
                selected_name = matched[0]
        else:
            fluid_match = next((name for name in names if "fluid" in name.lower()), None)
            non_through_match = next(
                (name for name in names if "midi through" not in name.lower()),
                None,
            )
            selected_name = fluid_match or non_through_match or names[0]

        if checks_ok:
            try:
                port = mido.open_output(selected_name)
                port.close()
                print(f"MIDI check passed: output '{selected_name}' is usable")
            except Exception as exc:
                print(f"MIDI check failed: unable to open output '{selected_name}': {exc}")
                checks_ok = False

    try:
        # Use the cached multi-GPU detector (probes once, caches result).
        import gpu_detector as _gd
        from gpu_detector import MultiGPUDetector
        if _gd._gpu_detector is None:
            _gd._gpu_detector = MultiGPUDetector()
        gpu_metrics = _gd._gpu_detector.detect_gpus()
        
        if gpu_metrics.is_available():
            print(f"GPU check passed: {gpu_metrics.vendor.value} GPU detected ({gpu_metrics.device_count} devices, avg {gpu_metrics.utilization:.1f}% utilization)")
        else:
            print("GPU check: no supported GPU hardware detected - Continuing without GPU")
    except Exception as exc:
        # Fallback to original nvidia-smi method
        try:
            output = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
            values = [float(line) for line in output.splitlines() if line.strip()]
            if not values:
                print("GPU check: nvidia-smi returned no utilization values - Continuing without GPU")
                # checks_ok stays True
            else:
                avg = sum(values) / len(values)
                print(f"GPU check passed: utilization readout available (avg {avg:.1f}%)")
        except Exception as exc:
            print(f"GPU check failed: unable to read metrics with nvidia-smi ({exc}) - Continuing without GPU")
            # Optimization: Do not set checks_ok = False to allow CPU/RAM-only operation

    if checks_ok:
        print("Self-check passed.")
    else:
        print("Self-check failed.")

    return checks_ok


def main(
    use_pitch_bend: bool = False,
    midi_port_hint: str = "",
    base_hz: float = BASE_SAMPLE_HZ,
    min_hz: float = MIN_SAMPLE_HZ,
    max_hz: float = MAX_SAMPLE_HZ,
    midi_program: int = DROID_MIDI_PROGRAM,
    droid_mode: bool = True,
    escalation_regulator: float = 1.0,
) -> None:
    smoother = Smoother(SMOOTH_WINDOW)
    throughput = ThroughputTracker()
    machine_inputs = MachineInputTracker()
    sampling_clock = NaturalSamplingClock(
        base_hz=base_hz,
        min_hz=min_hz,
        max_hz=max_hz,
        escalation_regulator=escalation_regulator,
    )
    phrase_step = 0
    try:
        port = resolve_midi_port(midi_port_hint)
    except IOError as exc:
        print(f"MIDI output not available: {exc}")
        print("Start FluidSynth first and check: aconnect -o")
        return

    print(f"Using MIDI output: {port.name}")
    initialize_midi_voice(port, midi_program=midi_program, droid_mode=droid_mode)

    try:
        while True:
            rates = throughput.sample()
            extra = machine_inputs.sample()
            iowait_pct = extract_iowait_percent()

            metrics = gather_metrics(smoother)
            sample_interval_s, activity_score = sampling_clock.update(
                {
                    "cpu": metrics["cpu_usage"],
                    "ram": metrics["ram_usage"],
                    "gpu": metrics["gpu_usage"],
                },
                rates,
                extra,
            )
            note_length_seconds = clamp_float(
                sample_interval_s * (0.32 + activity_score * 0.18),
                MIN_NOTE_LENGTH_SECONDS,
                MAX_NOTE_LENGTH_SECONDS,
            )

            note, velocity, modulation, pitch_bend = map_to_midi(
                metrics["cpu_usage"],
                metrics["ram_usage"],
                metrics["gpu_usage"],
                use_pitch_bend=use_pitch_bend,
                activity_score=activity_score,
                phrase_step=phrase_step,
                iowait_pct=iowait_pct,
                disk_busy_pct=extra.get("disk_busy_pct", 0.0),
            )
            play_note(
                port,
                note,
                velocity,
                modulation,
                pitch_bend,
                note_length_seconds=note_length_seconds,
                activity_score=activity_score,
                phrase_step=phrase_step,
                net_pps=rates.get("net_pps", 0.0),
                droid_mode=droid_mode,
            )
            phrase_step += 1
            
            # Diagnostic output for SSH testing
            print(
                f"Metric: CPU={metrics['cpu_usage']:4.1f}% RAM={metrics['ram_usage']:4.1f}% "
                f"GPU={metrics['gpu_usage']:4.1f}% IOwait={iowait_pct:4.1f}% "
                f"DiskBusy={extra.get('disk_busy_pct', 0.0):4.1f}% Hz={sampling_clock.current_hz:3.2f} "
                f"Act={activity_score:3.2f} EscReg={sampling_clock.escalation_regulator:3.2f} "
                f"| MIDI: Note={note} Vel={velocity} Mod={modulation} Bend={pitch_bend}"
            )

            remaining = sample_interval_s - note_length_seconds
            if remaining > 0:
                time.sleep(remaining)
    except KeyboardInterrupt:
        print("Stopping sonification pipeline.")
    finally:
        port.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Hardware sonification pipeline")
    parser.add_argument(
        "--pitch-bend",
        action="store_true",
        help="Enable microtonal pitchwheel messages",
    )
    parser.add_argument(
        "--midi-port",
        default="",
        help="Optional substring to match MIDI output port name",
    )
    parser.add_argument(
        "--base-hz",
        type=float,
        default=BASE_SAMPLE_HZ,
        help="Baseline sample rate in Hz before activity adaptation.",
    )
    parser.add_argument(
        "--min-hz",
        type=float,
        default=MIN_SAMPLE_HZ,
        help="Minimum adaptive sample rate in Hz.",
    )
    parser.add_argument(
        "--max-hz",
        type=float,
        default=MAX_SAMPLE_HZ,
        help="Maximum adaptive sample rate in Hz.",
    )
    parser.add_argument(
        "--midi-program",
        type=int,
        default=DROID_MIDI_PROGRAM,
        help="MIDI program number (0-127), default is Sci-Fi voice.",
    )
    parser.add_argument(
        "--classic-voice",
        action="store_true",
        help="Disable droid chirp articulation and use plain note playback.",
    )
    parser.add_argument(
        "--escalation-regulator",
        type=float,
        default=1.0,
        help="Escalation intensity multiplier for load-driven rate increases (0.35-2.5).",
    )
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="Validate CPU/RAM, MIDI, and GPU prerequisites and exit",
    )
    parser.add_argument(
        "--no-startup-check",
        action="store_true",
        help="Skip automatic prerequisite check before realtime startup",
    )
    args = parser.parse_args()

    if args.self_check:
        raise SystemExit(0 if run_self_check(midi_port_hint=args.midi_port) else 1)

    if not args.no_startup_check:
        print("Running startup self-check...")
        if not run_self_check(midi_port_hint=args.midi_port):
            print("Aborting startup because prerequisite checks failed.")
            raise SystemExit(1)

    main(
        use_pitch_bend=args.pitch_bend,
        midi_port_hint=args.midi_port,
        base_hz=args.base_hz,
        min_hz=args.min_hz,
        max_hz=args.max_hz,
        midi_program=args.midi_program,
        droid_mode=not args.classic_voice,
        escalation_regulator=args.escalation_regulator,
    )
