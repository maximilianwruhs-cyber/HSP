#!/usr/bin/env python3
"""Hosted-safe MIDI smoke checks for HSP.

This script is intentionally hardware-agnostic:
- It validates MIDI mapping logic and message construction.
- It probes output-port enumeration and (optionally) open/close behavior.
- In default mode it does not fail when no MIDI endpoints exist.

Use --strict for self-hosted or local environments where at least one
usable output port is expected.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

import mido
from mido import Message

# Allow running as `python scripts/midi_smoke.py` from repo root and CI.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from sonification_pipeline import map_to_midi


def _validate_mapping() -> Dict[str, Any]:
    scenarios = [
        (0, 0, 0, False),
        (50, 30, 10, True),
        (100, 100, 100, True),
        (-20, 140, 250, True),
    ]

    checks: List[Dict[str, Any]] = []
    for cpu, ram, gpu, pitch in scenarios:
        note, velocity, modulation, bend = map_to_midi(
            cpu,
            ram,
            gpu,
            use_pitch_bend=pitch,
            activity_score=0.55,
            phrase_step=3,
            iowait_pct=7.0,
            disk_busy_pct=35.0,
        )
        checks.append(
            {
                "input": {"cpu": cpu, "ram": ram, "gpu": gpu, "pitch": pitch},
                "output": {
                    "note": note,
                    "velocity": velocity,
                    "modulation": modulation,
                    "bend": bend,
                },
                "ok": (0 <= note <= 127)
                and (0 <= velocity <= 127)
                and (0 <= modulation <= 127)
                and (-8192 <= bend <= 8191),
            }
        )

    ok = all(item["ok"] for item in checks)
    return {"ok": ok, "checks": checks}


def _validate_message_encoding() -> Dict[str, Any]:
    try:
        note_on = Message("note_on", note=60, velocity=100)
        note_off = Message("note_off", note=60, velocity=0)
        cc = Message("control_change", control=1, value=64)
        pitch = Message("pitchwheel", pitch=512)
        ok = True
        detail = {
            "note_on": note_on.bytes(),
            "note_off": note_off.bytes(),
            "cc": cc.bytes(),
            "pitch": pitch.bytes(),
        }
    except Exception as exc:  # pragma: no cover - defensive
        ok = False
        detail = {"error": str(exc)}

    return {"ok": ok, "detail": detail}


def _probe_outputs(strict: bool) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "ok": True,
        "ports": [],
        "open_test": None,
        "warning": None,
        "error": None,
    }

    try:
        names = mido.get_output_names()
        result["ports"] = names
    except Exception as exc:
        result["ok"] = not strict
        result["warning" if not strict else "error"] = (
            f"Output-port enumeration failed: {exc}"
        )
        return result

    if not result["ports"]:
        result["ok"] = not strict
        result["warning" if not strict else "error"] = (
            "No MIDI output ports detected"
        )
        return result

    selected = result["ports"][0]
    try:
        port = mido.open_output(selected)
        port.close()
        result["open_test"] = {"port": selected, "ok": True}
    except Exception as exc:
        result["ok"] = not strict
        result["open_test"] = {"port": selected, "ok": False, "error": str(exc)}
        if strict:
            result["error"] = f"Unable to open '{selected}': {exc}"
        else:
            result["warning"] = f"Unable to open '{selected}': {exc}"

    return result


def run(strict: bool = False) -> Dict[str, Any]:
    mapping = _validate_mapping()
    encoding = _validate_message_encoding()
    outputs = _probe_outputs(strict=strict)

    ok = mapping["ok"] and encoding["ok"] and outputs["ok"]
    return {
        "ok": ok,
        "strict": strict,
        "mapping": mapping,
        "encoding": encoding,
        "outputs": outputs,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run hosted-safe MIDI smoke checks")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Require at least one openable MIDI output endpoint",
    )
    args = parser.parse_args(argv)

    report = run(strict=args.strict)
    print(json.dumps(report, indent=2))

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
