#!/usr/bin/env python3
"""
netdata_bridge.py — Poll Netdata's local HTTP API and forward normalized metrics
to the HSP /ingest WebSocket endpoint.

Usage:
    python3 netdata_bridge.py [--netdata-url URL] [--ingest-url URL] [--interval S]

Dependencies: websockets (already installed by bootstrap.sh), stdlib only otherwise.
"""

import argparse
import asyncio
import json
import logging
import urllib.request
from typing import Any, Dict, List, Optional

try:
    import websockets
except ImportError:
    raise SystemExit(
        "websockets package is required. Run:  ./venv/bin/pip install websockets"
    )

LOG = logging.getLogger("netdata_bridge")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dim(chart: Dict, *names: str) -> Optional[float]:
    """Return the first matching dimension value from a Netdata chart dict."""
    dims = chart.get("dimensions", {})
    for name in names:
        raw = dims.get(name, {}).get("value")
        if raw is None:
            continue
        try:
            v = float(raw)
            if v == v:  # NaN guard
                return v
        except (TypeError, ValueError):
            pass
    return None


def _dim_sum(chart: Dict, *names: str) -> Optional[float]:
    """Sum named dimensions, skipping any that are absent."""
    total = 0.0
    found = False
    dims = chart.get("dimensions", {})
    for name in names:
        raw = dims.get(name, {}).get("value")
        if raw is None:
            continue
        try:
            v = float(raw)
            if v == v:
                total += v
                found = True
        except (TypeError, ValueError):
            pass
    return total if found else None


def _first_dim_value(chart: Dict, min_v: float = -1e9, max_v: float = 1e9) -> Optional[float]:
    """Return the value of the first dimension whose value is in [min_v, max_v]."""
    for dv in chart.get("dimensions", {}).values():
        try:
            v = float(dv.get("value", "nan"))
            if v == v and min_v < v < max_v:
                return v
        except (TypeError, ValueError):
            pass
    return None


def _avg_dim_values(chart: Dict, min_v: float = 0.0, max_v: float = 1e9) -> Optional[float]:
    """Average all dimension values that pass the range filter."""
    vals: List[float] = []
    for dv in chart.get("dimensions", {}).values():
        try:
            v = float(dv.get("value", "nan"))
            if v == v and min_v <= v <= max_v:
                vals.append(v)
        except (TypeError, ValueError):
            pass
    return sum(vals) / len(vals) if vals else None


# ---------------------------------------------------------------------------
# Netdata fetch
# ---------------------------------------------------------------------------

def fetch_all_metrics(netdata_url: str) -> Dict[str, Any]:
    url = f"{netdata_url}/api/v1/allmetrics?format=json"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=4) as resp:
        return json.loads(resp.read().decode())


# ---------------------------------------------------------------------------
# Frame builder — converts Netdata chart tree → HSP DIRECT_KEYS dict
# ---------------------------------------------------------------------------

def build_hsp_frame(all_metrics: Dict[str, Any]) -> Dict[str, float]:
    charts: Dict[str, Dict] = all_metrics.get("charts", {})
    frame: Dict[str, float] = {}

    def c(name: str) -> Dict:
        return charts.get(name, {})

    # ---- CPU active % -------------------------------------------------------
    cpu_chart = c("system.cpu")
    cpu_active = _dim_sum(
        cpu_chart, "user", "system", "nice", "iowait", "irq", "softirq", "steal"
    )
    if cpu_active is not None:
        frame["cpu"] = max(0.0, min(100.0, cpu_active))

    # ---- IOWait % -----------------------------------------------------------
    iowait = _dim(cpu_chart, "iowait")
    if iowait is not None:
        frame["iowait_pct"] = max(0.0, iowait)

    # ---- RAM % --------------------------------------------------------------
    ram_chart = c("system.ram")
    ram_used = _dim(ram_chart, "used")
    ram_free = _dim(ram_chart, "free")
    ram_cached = _dim(ram_chart, "cached")
    ram_buffers = _dim(ram_chart, "buffers")
    if ram_used is not None:
        total = (
            (ram_used or 0.0)
            + (ram_free or 0.0)
            + (ram_cached or 0.0)
            + (ram_buffers or 0.0)
        )
        if total > 0:
            frame["ram"] = max(0.0, min(100.0, ram_used / total * 100.0))

    # ---- Swap % -------------------------------------------------------------
    swap_chart = c("system.swap")
    swap_used = _dim(swap_chart, "used")
    swap_free = _dim(swap_chart, "free")
    if swap_used is not None:
        swap_total = (swap_used or 0.0) + (swap_free or 0.0)
        if swap_total > 0:
            frame["swap_pct"] = max(0.0, min(100.0, swap_used / swap_total * 100.0))

    # ---- Load 1-min (normalised to CPU count) -------------------------------
    load1 = _dim(c("system.load"), "load1")
    if load1 is not None:
        cpu_count = int(all_metrics.get("cpu_count", 1) or 1)
        frame["load1_pct"] = max(0.0, min(100.0, load1 / cpu_count * 100.0))

    # ---- Process / thread count ---------------------------------------------
    proc_val = _dim(c("system.active_processes"), "active")
    if proc_val is None:
        proc_val = _dim(c("system.processes"), "running", "processes", "active")
    if proc_val is not None:
        frame["proc_count"] = max(0.0, abs(proc_val))

    # ---- Context switches / s -----------------------------------------------
    ctxt = _dim(c("system.ctxt"), "switches")
    if ctxt is not None:
        frame["ctx_switches_ps"] = max(0.0, abs(ctxt))

    # ---- Interrupts / s -----------------------------------------------------
    intr = _dim(c("system.intr"), "interrupts")
    if intr is not None:
        frame["interrupts_ps"] = max(0.0, abs(intr))

    # ---- Disk throughput (bytes/s) — Netdata reports KB/s -------------------
    io_in = _dim(c("system.io"), "in")
    io_out = _dim(c("system.io"), "out")
    if io_in is not None or io_out is not None:
        frame["disk_bps"] = abs((io_in or 0.0) + (io_out or 0.0)) * 1024.0

    # ---- Disk IOPS ----------------------------------------------------------
    disk_ops: Optional[float] = None
    # Try aggregate chart first
    r = _dim(c("system.io_ops"), "reads")
    w = _dim(c("system.io_ops"), "writes")
    if r is not None or w is not None:
        disk_ops = abs(r or 0.0) + abs(w or 0.0)
    else:
        # Fall back to first individual disk_ops.* chart
        for k, v in charts.items():
            if k.startswith("disk_ops."):
                r2 = _dim(v, "reads")
                w2 = _dim(v, "writes")
                if r2 is not None or w2 is not None:
                    disk_ops = abs(r2 or 0.0) + abs(w2 or 0.0)
                break
    if disk_ops is not None:
        frame["disk_iops"] = disk_ops

    # ---- Disk busy % --------------------------------------------------------
    for k, v in charts.items():
        if k.startswith("disk_util.") or "disk" in k and "busy" in k:
            util = _dim(v, "utilization", "busy")
            if util is None:
                util = _first_dim_value(v, 0.0, 100.0)
            if util is not None:
                frame["disk_busy_pct"] = max(0.0, min(100.0, abs(util)))
                break

    # ---- Network throughput (bytes/s) — Netdata reports kbit/s -------------
    net_rx = _dim(c("system.net"), "received")
    net_tx = _dim(c("system.net"), "sent")
    if net_rx is not None or net_tx is not None:
        frame["net_bps"] = abs((net_rx or 0.0) + (net_tx or 0.0)) * 125.0  # kbps→B/s

    # ---- Net packets/s (first interface) ------------------------------------
    for k, v in charts.items():
        if k.startswith("net.") and not k.startswith("net_"):
            p_rx = _dim(v, "received")
            p_tx = _dim(v, "sent")
            if p_rx is not None or p_tx is not None:
                frame["net_pps"] = abs(p_rx or 0.0) + abs(p_tx or 0.0)
                break

    # ---- Net errors / drops / s ---------------------------------------------
    err_total = 0.0
    drop_total = 0.0
    for k, v in charts.items():
        if k.startswith("net_errors."):
            e = _dim_sum(v, "inbound", "outbound")
            if e is not None:
                err_total += abs(e)
        elif k.startswith("net_drops."):
            d = _dim_sum(v, "inbound", "outbound")
            if d is not None:
                drop_total += abs(d)
    if err_total > 0:
        frame["net_errors_ps"] = err_total
    if drop_total > 0:
        frame["net_drops_ps"] = drop_total

    # ---- CPU temperature ----------------------------------------------------
    cpu_temp_keywords = ("coretemp", "k10temp", "nct", "cpu_thermal", "acpitz", "cpu")
    for k, v in charts.items():
        k_lower = k.lower()
        if ("temp" in k_lower or "temperature" in k_lower) and any(
            kw in k_lower for kw in cpu_temp_keywords
        ):
            temp = _dim(
                v,
                "temp1",
                "Tctl",
                "Tdie",
                "Package id 0",
                "Physical id 0",
                "temp",
            )
            if temp is None:
                temp = _first_dim_value(v, 10.0, 120.0)
            if temp is not None and 10 < temp < 120:
                frame["cpu_temp_c"] = temp
                break

    # ---- CPU frequency (MHz) ------------------------------------------------
    for k, v in charts.items():
        if k.startswith("cpufreq.") or k == "cpu.cpufreq":
            freq = _avg_dim_values(v, 100.0, 10_000.0)
            if freq is not None:
                frame["cpu_freq_mhz"] = freq
            break

    # ---- Storage temperature ------------------------------------------------
    storage_keywords = ("nvme", "hdd", "sda", "sdb", "sdc", "ahci", "drivetemp")
    for k, v in charts.items():
        k_lower = k.lower()
        if ("temp" in k_lower or "temperature" in k_lower) and any(
            kw in k_lower for kw in storage_keywords
        ):
            t = _dim(v, "temp1", "temperature", "temp")
            if t is None:
                t = _first_dim_value(v, 10.0, 90.0)
            if t is not None and 10 < t < 90:
                frame["storage_temp_c"] = t
                break

    return {k: round(v, 4) for k, v in frame.items()}


# ---------------------------------------------------------------------------
# Async bridge loop
# ---------------------------------------------------------------------------

async def bridge_loop(
    netdata_url: str, ingest_url: str, interval: float
) -> None:
    LOG.info("Netdata bridge starting. Netdata: %s  →  HSP: %s", netdata_url, ingest_url)
    while True:
        try:
            async with websockets.connect(
                ingest_url, ping_interval=20, ping_timeout=10
            ) as ws:
                LOG.info("Connected to HSP /ingest. Polling every %.1fs.", interval)
                while True:
                    try:
                        loop = asyncio.get_event_loop()
                        data = await loop.run_in_executor(
                            None, fetch_all_metrics, netdata_url
                        )
                        frame = build_hsp_frame(data)
                        if frame:
                            await ws.send(json.dumps(frame))
                            LOG.debug("→ %s", frame)
                        else:
                            LOG.warning("build_hsp_frame returned empty dict — check Netdata charts")
                    except Exception as exc:  # noqa: BLE001
                        LOG.warning("Fetch/parse error: %s", exc)
                    await asyncio.sleep(interval)
        except (OSError, websockets.exceptions.WebSocketException) as exc:
            LOG.warning("WebSocket error (%s). Retrying in 5 s …", exc)
            await asyncio.sleep(5)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Netdata → HSP /ingest bridge",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--netdata-url",
        default="http://localhost:19999",
        help="Base URL of the Netdata agent",
    )
    parser.add_argument(
        "--ingest-url",
        default="ws://127.0.0.1:8001/ingest",
        help="HSP WebSocket ingest endpoint",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Poll interval in seconds",
    )
    parser.add_argument("--debug", action="store_true", help="Verbose debug logging")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        asyncio.run(bridge_loop(args.netdata_url, args.ingest_url, args.interval))
    except KeyboardInterrupt:
        LOG.info("Netdata bridge stopped.")


if __name__ == "__main__":
    main()
