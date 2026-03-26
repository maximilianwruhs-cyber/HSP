import glob
import os
import time
from typing import Dict, List, Optional

import psutil


class MachineInputTracker:
    """Collects optional machine telemetry beyond CPU/RAM/GPU for musical routing."""

    def __init__(self) -> None:
        self.last_time = time.monotonic()
        self.last_net_errors = self._read_net_errors_total()
        self.last_net_drops = self._read_net_drops_total()
        self.last_disk_busy_ms = self._read_disk_busy_ms_total()
        self.rapl_energy_paths = self._discover_rapl_energy_paths()
        self.last_energy_j_total = self._read_rapl_energy_j_total()

    @staticmethod
    def _read_net_errors_total() -> float:
        io = psutil.net_io_counters()
        if io is None:
            return 0.0
        return float(io.errin + io.errout)

    @staticmethod
    def _read_net_drops_total() -> float:
        io = psutil.net_io_counters()
        if io is None:
            return 0.0
        return float(io.dropin + io.dropout)

    @staticmethod
    def _read_disk_busy_ms_total() -> float:
        io = psutil.disk_io_counters()
        if io is None:
            return 0.0
        busy_time = getattr(io, "busy_time", 0)
        return float(busy_time or 0.0)

    @staticmethod
    def _discover_rapl_energy_paths() -> List[str]:
        patterns = [
            "/sys/class/powercap/*/energy_uj",
            "/sys/class/powercap/*/*/energy_uj",
            "/sys/devices/virtual/powercap/*/energy_uj",
            "/sys/devices/virtual/powercap/*/*/energy_uj",
        ]
        paths: List[str] = []
        for pattern in patterns:
            paths.extend(glob.glob(pattern))
        # Preserve order while deduplicating.
        return list(dict.fromkeys(paths))

    def _read_rapl_energy_j_total(self) -> float:
        total = 0.0
        for path in self.rapl_energy_paths:
            try:
                with open(path, "r", encoding="ascii") as f:
                    value_uj = float(f.read().strip())
                    total += value_uj / 1_000_000.0
            except Exception:
                continue
        return total

    @staticmethod
    def _read_storage_temp_c() -> float:
        max_temp_c = 0.0
        hwmon_names = glob.glob("/sys/class/hwmon/hwmon*/name")
        for name_path in hwmon_names:
            try:
                with open(name_path, "r", encoding="ascii") as f:
                    name = f.read().strip().lower()
            except Exception:
                continue

            if name not in {"nvme", "drivetemp"}:
                continue

            hwmon_dir = os.path.dirname(name_path)
            temp_inputs = glob.glob(os.path.join(hwmon_dir, "temp*_input"))
            for temp_path in temp_inputs:
                try:
                    with open(temp_path, "r", encoding="ascii") as f:
                        raw = float(f.read().strip())
                    # Most hwmon values are in millidegrees Celsius.
                    temp_c = raw / 1000.0 if raw > 400 else raw
                    max_temp_c = max(max_temp_c, temp_c)
                except Exception:
                    continue

        return max_temp_c

    @staticmethod
    def _read_battery_power_w() -> float:
        battery_dirs = glob.glob("/sys/class/power_supply/BAT*")
        for bdir in battery_dirs:
            power_path = os.path.join(bdir, "power_now")
            if not os.path.exists(power_path):
                continue
            try:
                with open(power_path, "r", encoding="ascii") as f:
                    # power_now is typically in microwatts.
                    uw = float(f.read().strip())
                return max(0.0, uw / 1_000_000.0)
            except Exception:
                continue
        return 0.0

    def sample(self) -> Dict[str, float]:
        now = time.monotonic()
        elapsed = max(now - self.last_time, 1e-6)

        net_errors_total = self._read_net_errors_total()
        net_drops_total = self._read_net_drops_total()
        disk_busy_ms_total = self._read_disk_busy_ms_total()
        energy_j_total = self._read_rapl_energy_j_total()

        net_errors_ps = max(0.0, (net_errors_total - self.last_net_errors) / elapsed)
        net_drops_ps = max(0.0, (net_drops_total - self.last_net_drops) / elapsed)

        busy_delta_ms = max(0.0, disk_busy_ms_total - self.last_disk_busy_ms)
        disk_busy_pct = max(0.0, min((busy_delta_ms / (elapsed * 1000.0)) * 100.0, 100.0))

        power_w = 0.0
        if self.last_energy_j_total > 0.0 and energy_j_total > 0.0:
            delta_j = energy_j_total - self.last_energy_j_total
            if delta_j >= 0.0:
                power_w = max(0.0, delta_j / elapsed)

        self.last_time = now
        self.last_net_errors = net_errors_total
        self.last_net_drops = net_drops_total
        self.last_disk_busy_ms = disk_busy_ms_total
        self.last_energy_j_total = energy_j_total

        return {
            "net_errors_ps": net_errors_ps,
            "net_drops_ps": net_drops_ps,
            "disk_busy_pct": disk_busy_pct,
            "storage_temp_c": self._read_storage_temp_c(),
            "power_w": power_w,
            "energy_j_total": energy_j_total,
            "battery_power_w": self._read_battery_power_w(),
        }
