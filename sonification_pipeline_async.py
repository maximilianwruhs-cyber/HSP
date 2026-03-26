import argparse
import asyncio
import json
import math
import subprocess
import time
from collections import OrderedDict, deque
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Tuple

import mido
import psutil
from mido import Message
from fastapi import Body, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn
import os

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
DEFAULT_EXPERIENCE_PROFILE = "night-patrol-techno"
EXPERIENCE_PROFILE_CONFIG: Dict[str, Dict[str, Any]] = {
    "night-patrol-techno": {
        "scale_notes": [60, 62, 63, 65, 67, 68, 70],
        "phrase_high": [0, 3, 5, 2, -2, 4],
        "phrase_mid": [0, 2, -1, 3, -2, 1],
        "phrase_low": [0, 2, -2, 3, -1, 4, -3, 1],
        "disk_busy_trigger": 70.0,
        "disk_phrase_push": 1,
        "iowait_trigger": 20.0,
        "iowait_phrase_push": -1,
        "octave_up_interval": 12,
        "octave_down_interval": -12,
        "octave_drop_activity_threshold": 0.50,
        "disk_jump_interval": 7,
        "vibrato_depth": 0.14,
        "disk_vibrato_cap": 0.06,
        "velocity_bias": 0,
        "velocity_activity_boost": 8.0,
        "modulation_bias": 0,
    },
    "calm-observatory-ambient": {
        "scale_notes": [48, 50, 52, 55, 57, 59, 62],
        "phrase_high": [0, 2, 3, 1, 0, -1],
        "phrase_mid": [0, 1, 0, 2, -1, 1],
        "phrase_low": [0, 1, -1, 2, 0, -2],
        "disk_busy_trigger": 80.0,
        "disk_phrase_push": 0,
        "iowait_trigger": 28.0,
        "iowait_phrase_push": -1,
        "octave_up_interval": 7,
        "octave_down_interval": -12,
        "octave_drop_activity_threshold": 0.42,
        "disk_jump_interval": 5,
        "vibrato_depth": 0.08,
        "disk_vibrato_cap": 0.03,
        "velocity_bias": -12,
        "velocity_activity_boost": 4.0,
        "modulation_bias": -10,
    },
    "high-load-alarm-industrial": {
        "scale_notes": [50, 51, 53, 55, 56, 58, 60],
        "phrase_high": [0, 4, 6, 3, -3, 5],
        "phrase_mid": [0, 3, -2, 4, -3, 2],
        "phrase_low": [0, 2, -3, 4, -2, 5, -4, 2],
        "disk_busy_trigger": 62.0,
        "disk_phrase_push": 2,
        "iowait_trigger": 15.0,
        "iowait_phrase_push": -2,
        "octave_up_interval": 12,
        "octave_down_interval": -12,
        "octave_drop_activity_threshold": 0.58,
        "disk_jump_interval": 8,
        "vibrato_depth": 0.20,
        "disk_vibrato_cap": 0.09,
        "velocity_bias": 8,
        "velocity_activity_boost": 12.0,
        "modulation_bias": 16,
    },
    "chaos-festival-dnb": {
        "scale_notes": [62, 63, 65, 67, 68, 70, 72],
        "phrase_high": [0, 5, 2, 6, -3, 4],
        "phrase_mid": [0, 3, -1, 4, -2, 2],
        "phrase_low": [0, 2, -2, 3, -1, 4, -3, 1],
        "disk_busy_trigger": 58.0,
        "disk_phrase_push": 2,
        "iowait_trigger": 14.0,
        "iowait_phrase_push": -1,
        "octave_up_interval": 12,
        "octave_down_interval": -12,
        "octave_drop_activity_threshold": 0.55,
        "disk_jump_interval": 9,
        "vibrato_depth": 0.18,
        "disk_vibrato_cap": 0.09,
        "velocity_bias": 10,
        "velocity_activity_boost": 10.0,
        "modulation_bias": 10,
    },
    "droid-horror-escalation": {
        "scale_notes": [48, 50, 51, 54, 55, 57, 60],
        "phrase_high": [0, 4, 7, 3, -4, 5],
        "phrase_mid": [0, 2, -2, 4, -3, 2],
        "phrase_low": [0, 1, -3, 2, -2, 4, -5, 1],
        "disk_busy_trigger": 55.0,
        "disk_phrase_push": 2,
        "iowait_trigger": 12.0,
        "iowait_phrase_push": -2,
        "octave_up_interval": 12,
        "octave_down_interval": -12,
        "octave_drop_activity_threshold": 0.60,
        "disk_jump_interval": 10,
        "vibrato_depth": 0.22,
        "disk_vibrato_cap": 0.10,
        "velocity_bias": 12,
        "velocity_activity_boost": 12.0,
        "modulation_bias": 18,
    },
    "htop-observer": {
        "scale_notes": [59, 60, 62, 64, 65, 67, 69],
        "phrase_high": [0, 2, 4, 1, -1, 3],
        "phrase_mid": [0, 1, -1, 2, -2, 1],
        "phrase_low": [0, 1, -2, 2, -1, 3, -3, 0],
        "disk_busy_trigger": 68.0,
        "disk_phrase_push": 1,
        "iowait_trigger": 18.0,
        "iowait_phrase_push": -1,
        "octave_up_interval": 12,
        "octave_down_interval": -12,
        "octave_drop_activity_threshold": 0.48,
        "disk_jump_interval": 7,
        "vibrato_depth": 0.10,
        "disk_vibrato_cap": 0.05,
        "velocity_bias": -4,
        "velocity_activity_boost": 6.0,
        "modulation_bias": 6,
    },
}
EXPERIENCE_PROFILE_ALIASES = {
    "night-patrol": "night-patrol-techno",
    "calm-observatory": "calm-observatory-ambient",
    "high-load-alarm": "high-load-alarm-industrial",
    "chaos-festival": "chaos-festival-dnb",
}
SMOOTH_WINDOW = 5
EXTERNAL_FRAME_MAX_AGE_SECONDS = 5.0
WS_CONTROL_MAX_FRAME_BYTES = 4096
WS_INGEST_MAX_FRAME_BYTES = 16384
GPU_POLL_MIN_INTERVAL_SECONDS = 0.5
PROC_COUNT_POLL_MIN_INTERVAL_SECONDS = 0.5
CONTROL_COMMAND_ID_MAX_LENGTH = 96
CONTROL_COMMAND_CACHE_MAX_ENTRIES = 1024
CONTROL_ALLOWED_FIELDS = {"command_id", "escalation_regulator", "metrics_source", "experience_profile"}
CONTROL_ALLOWED_SOURCES = {"local", "external"}
DEFAULT_WS_MAX_SIZE_BYTES = 65536
DEFAULT_WS_MAX_QUEUE = 8


def normalize_experience_profile_name(profile_name: Any) -> str:
    key = str(profile_name or "").strip().lower()
    if not key:
        key = DEFAULT_EXPERIENCE_PROFILE
    key = EXPERIENCE_PROFILE_ALIASES.get(key, key)
    if key not in EXPERIENCE_PROFILE_CONFIG:
        return DEFAULT_EXPERIENCE_PROFILE
    return key


def resolve_experience_profile(profile_name: Any) -> Dict[str, Any]:
    return EXPERIENCE_PROFILE_CONFIG[normalize_experience_profile_name(profile_name)]


def initialize_app_runtime_state(target_app: FastAPI) -> None:
    target_app.state.ws_token = str(
        getattr(target_app.state, "ws_token", os.getenv("HSP_WS_TOKEN", ""))
    ).strip()
    target_app.state.ingest_token = str(
        getattr(
            target_app.state,
            "ingest_token",
            os.getenv("HSP_INGEST_TOKEN", target_app.state.ws_token),
        )
    ).strip()
    target_app.state.control_lock = asyncio.Lock()
    target_app.state.control_command_results = OrderedDict()
    target_app.state.control_state_version = int(getattr(target_app.state, "control_state_version", 0))
    target_app.state.experience_profile = str(
        getattr(target_app.state, "experience_profile", DEFAULT_EXPERIENCE_PROFILE)
    )
    target_app.state.latest_payload = dict(getattr(target_app.state, "latest_payload", {}))


@asynccontextmanager
async def app_lifespan(target_app: FastAPI):
    initialize_app_runtime_state(target_app)
    target_app.state.sonification_task = asyncio.create_task(
        sonification_loop(
            use_pitch_bend=bool(getattr(target_app.state, "use_pitch_bend", True)),
            midi_port_hint=str(getattr(target_app.state, "midi_port_hint", "FLUID")),
            enable_midi=bool(getattr(target_app.state, "enable_midi", False)),
            metrics_source=str(getattr(target_app.state, "metrics_source", "local")),
            external_max_age_s=float(
                getattr(target_app.state, "external_max_age_s", EXTERNAL_FRAME_MAX_AGE_SECONDS)
            ),
            midi_program=int(getattr(target_app.state, "midi_program", DROID_MIDI_PROGRAM)),
            droid_mode=bool(getattr(target_app.state, "droid_mode", True)),
            escalation_regulator=float(getattr(target_app.state, "escalation_regulator", 1.0)),
        )
    )

    try:
        yield
    finally:
        task = getattr(target_app.state, "sonification_task", None)
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(lifespan=app_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"Client connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        print(f"Client disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        stale: List[WebSocket] = []
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                stale.append(connection)
        for connection in stale:
            self.disconnect(connection)

manager = ConnectionManager()


class ExternalTelemetryState:
    """Stores latest external telemetry frame for overlay ingestion."""

    DIRECT_KEYS = (
        "cpu",
        "ram",
        "gpu",
        "disk_bps",
        "net_bps",
        "net_pps",
        "disk_iops",
        "ctx_switches_ps",
        "interrupts_ps",
        "disk_busy_pct",
        "net_errors_ps",
        "net_drops_ps",
        "gpu_temp_c",
        "gpu_power_w",
        "gpu_mem_pct",
        "storage_temp_c",
        "power_w",
        "energy_j_total",
        "battery_power_w",
        "cpu_temp_c",
        "cpu_freq_mhz",
        "load1_pct",
        "swap_pct",
        "iowait_pct",
        "proc_count",
    )

    def __init__(self) -> None:
        self.latest: Dict[str, float] = {}
        self.last_update = 0.0

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def ingest_frame(self, raw_frame: str) -> bool:
        try:
            payload = json.loads(raw_frame)
        except json.JSONDecodeError:
            return False
        return self.ingest_payload(payload)

    def ingest_payload(self, payload: Any) -> bool:
        normalized = self._normalize_payload(payload)
        if not normalized:
            return False
        self.latest.update(normalized)
        self.last_update = time.monotonic()
        return True

    def snapshot(self, max_age_seconds: float) -> Optional[Dict[str, float]]:
        if self.last_update <= 0.0:
            return None
        if (time.monotonic() - self.last_update) > max_age_seconds:
            return None
        return dict(self.latest)

    def _normalize_payload(self, payload: Any) -> Dict[str, float]:
        if isinstance(payload, list):
            merged: Dict[str, float] = {}
            for item in payload:
                merged.update(self._normalize_payload(item))
            return merged

        if not isinstance(payload, dict):
            return {}

        if "fields" in payload and "name" in payload:
            return self._normalize_telegraf_metric(payload)

        return self._normalize_direct_metric_map(payload)

    def _normalize_direct_metric_map(self, payload: Dict[str, Any]) -> Dict[str, float]:
        normalized: Dict[str, float] = {}
        for key in self.DIRECT_KEYS:
            if key not in payload:
                continue
            value = self._to_float(payload.get(key))
            if value is not None:
                normalized[key] = value
        return normalized

    def _normalize_telegraf_metric(self, payload: Dict[str, Any]) -> Dict[str, float]:
        fields = payload.get("fields", {})
        if not isinstance(fields, dict):
            return {}

        tags = payload.get("tags", {})
        if not isinstance(tags, dict):
            tags = {}

        measurement = str(payload.get("name", "")).lower()
        normalized: Dict[str, float] = {}

        def read_first(*candidates: str) -> Optional[float]:
            for candidate in candidates:
                value = self._to_float(fields.get(candidate))
                if value is not None:
                    return value
            return None

        if measurement == "cpu":
            cpu_tag = str(tags.get("cpu", "")).lower()
            if cpu_tag in {"", "cpu-total", "all"}:
                active = read_first("usage_active")
                if active is None:
                    idle = read_first("usage_idle")
                    if idle is not None:
                        active = 100.0 - idle
                if active is not None:
                    normalized["cpu"] = max(0.0, min(100.0, active))

                iowait = read_first("usage_iowait")
                if iowait is not None:
                    normalized["iowait_pct"] = max(0.0, iowait)

        elif measurement in {"mem", "memory"}:
            used_pct = read_first("used_percent")
            if used_pct is not None:
                normalized["ram"] = max(0.0, min(100.0, used_pct))

        elif measurement == "swap":
            used_pct = read_first("used_percent")
            if used_pct is not None:
                normalized["swap_pct"] = max(0.0, min(100.0, used_pct))

        elif measurement == "system":
            load1 = read_first("load1")
            if load1 is not None:
                cores = float(max(psutil.cpu_count() or 1, 1))
                normalized["load1_pct"] = max(0.0, min((load1 / cores) * 100.0, 100.0))

        elif measurement in {"nvidia_smi", "gpu"}:
            gpu = read_first("utilization_gpu", "gpu_util", "gpu_utilization")
            if gpu is not None:
                normalized["gpu"] = max(0.0, min(100.0, gpu))

            gpu_temp = read_first("temperature_gpu", "gpu_temp", "gpu_temp_c")
            if gpu_temp is not None:
                normalized["gpu_temp_c"] = max(0.0, gpu_temp)

            gpu_power = read_first("power_draw", "gpu_power_w")
            if gpu_power is not None:
                normalized["gpu_power_w"] = max(0.0, gpu_power)

            mem_pct = read_first("memory_used_percent", "gpu_mem_pct")
            if mem_pct is None:
                memory_used = read_first("memory_used")
                memory_total = read_first("memory_total")
                if memory_used is not None and memory_total is not None and memory_total > 0.0:
                    mem_pct = (memory_used / memory_total) * 100.0
            if mem_pct is not None:
                normalized["gpu_mem_pct"] = max(0.0, min(100.0, mem_pct))

        elif measurement == "intel_powerstat":
            power = read_first("package_current_power", "power_w")
            if power is not None:
                normalized["power_w"] = max(0.0, power)

        return normalized


external_telemetry = ExternalTelemetryState()


@app.get("/health")
async def health_check():
    return {"ok": True}

@app.get("/", response_class=HTMLResponse)
async def get_index():
    path = os.path.join(os.path.dirname(__file__), "index.html")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


@app.get("/state")
async def get_state():
    snapshot = getattr(app.state, "latest_payload", None)
    if isinstance(snapshot, dict) and snapshot:
        return dict(snapshot)

    return {
        "status": "warming_up",
        "metrics_source": str(getattr(app.state, "metrics_source", "local")),
        "escalation_regulator": float(getattr(app.state, "escalation_regulator", 1.0)),
        "experience_profile": str(
            getattr(app.state, "experience_profile", DEFAULT_EXPERIENCE_PROFILE)
        ),
    }


@app.post("/control")
async def control_http(payload: Any = Body(...)):
    command, error = validate_control_payload(payload)
    if error is not None:
        return JSONResponse(status_code=400, content=error)

    ack = await apply_control_command(command)
    return ack

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    if not await authorize_websocket(websocket, "control"):
        return
    await manager.connect(websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            if len(raw.encode("utf-8", errors="ignore")) > WS_CONTROL_MAX_FRAME_BYTES:
                await websocket.close(code=1009, reason="control frame too large")
                break

            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json(
                    control_error("invalid_json", "Control payload is not valid JSON.", retryable=False)
                )
                continue

            command, error = validate_control_payload(payload)
            if error is not None:
                await websocket.send_json(error)
                continue

            ack = await apply_control_command(command)
            await websocket.send_json(ack)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        manager.disconnect(websocket)


@app.websocket("/ingest")
async def ingest_endpoint(websocket: WebSocket):
    if not await authorize_websocket(websocket, "ingest"):
        return
    await websocket.accept()
    print("Telemetry producer connected.")
    try:
        while True:
            event = await websocket.receive()
            if event.get("type") == "websocket.disconnect":
                break

            frame_text = event.get("text")
            if frame_text is None:
                frame_bytes = event.get("bytes")
                if isinstance(frame_bytes, (bytes, bytearray)):
                    if len(frame_bytes) > WS_INGEST_MAX_FRAME_BYTES:
                        await websocket.close(code=1009, reason="ingest frame too large")
                        break
                    frame_text = frame_bytes.decode("utf-8", errors="ignore")

            if not frame_text:
                continue

            if len(frame_text.encode("utf-8", errors="ignore")) > WS_INGEST_MAX_FRAME_BYTES:
                await websocket.close(code=1009, reason="ingest frame too large")
                break

            external_telemetry.ingest_frame(frame_text)
    except WebSocketDisconnect:
        pass
    finally:
        print("Telemetry producer disconnected.")

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


def parse_escalation_regulator(value: Any) -> Optional[float]:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return clamp_float(numeric, 0.35, 2.5)


def websocket_auth_token(websocket: WebSocket) -> str:
    authorization = websocket.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    query_token = websocket.query_params.get("token")
    return str(query_token or "").strip()


def required_websocket_token(scope_name: str) -> str:
    if scope_name == "ingest":
        return str(
            getattr(
                app.state,
                "ingest_token",
                os.getenv("HSP_INGEST_TOKEN", os.getenv("HSP_WS_TOKEN", "")),
            )
        ).strip()
    return str(getattr(app.state, "ws_token", os.getenv("HSP_WS_TOKEN", ""))).strip()


async def authorize_websocket(websocket: WebSocket, scope_name: str) -> bool:
    required_token = required_websocket_token(scope_name)
    if not required_token:
        return True
    if websocket_auth_token(websocket) == required_token:
        return True
    await websocket.close(code=1008, reason="unauthorized")
    return False


def control_error(
    code: str,
    message: str,
    command_id: Optional[str] = None,
    retryable: bool = False,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "type": "control_error",
        "ok": False,
        "code": code,
        "message": message,
        "retryable": retryable,
    }
    if command_id:
        payload["command_id"] = command_id
    if details:
        payload["details"] = details
    return payload


def validate_control_payload(payload: Any) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    if not isinstance(payload, dict):
        return None, control_error("invalid_payload_type", "Control payload must be a JSON object.")

    unknown_fields = sorted(set(payload.keys()) - CONTROL_ALLOWED_FIELDS)
    if unknown_fields:
        return None, control_error(
            "unknown_fields",
            "Control payload contains unknown fields.",
            details={"unknown_fields": unknown_fields},
        )

    command_raw = payload.get("command_id")
    if not isinstance(command_raw, str) or not command_raw.strip():
        return None, control_error("missing_command_id", "command_id must be a non-empty string.")

    command_id = command_raw.strip()
    if len(command_id) > CONTROL_COMMAND_ID_MAX_LENGTH:
        return None, control_error(
            "command_id_too_long",
            "command_id exceeds maximum length.",
            command_id=command_id[:CONTROL_COMMAND_ID_MAX_LENGTH],
        )

    updates: Dict[str, Any] = {}

    if "escalation_regulator" in payload:
        parsed = parse_escalation_regulator(payload.get("escalation_regulator"))
        if parsed is None:
            return None, control_error(
                "invalid_escalation_regulator",
                "escalation_regulator must be a finite number.",
                command_id=command_id,
            )
        updates["escalation_regulator"] = parsed

    if "metrics_source" in payload:
        raw_source = payload.get("metrics_source")
        if not isinstance(raw_source, str):
            return None, control_error(
                "invalid_metrics_source",
                "metrics_source must be one of: local, external.",
                command_id=command_id,
            )
        source = raw_source.strip().lower()
        if source not in CONTROL_ALLOWED_SOURCES:
            return None, control_error(
                "invalid_metrics_source",
                "metrics_source must be one of: local, external.",
                command_id=command_id,
            )
        updates["metrics_source"] = source

    if "experience_profile" in payload:
        raw_profile = payload.get("experience_profile")
        if not isinstance(raw_profile, str) or not raw_profile.strip():
            return None, control_error(
                "invalid_experience_profile",
                "experience_profile must be a non-empty string.",
                command_id=command_id,
            )
        profile = raw_profile.strip().lower()
        if len(profile) > 128:
            return None, control_error(
                "experience_profile_too_long",
                "experience_profile exceeds maximum length.",
                command_id=command_id,
            )
        updates["experience_profile"] = profile

    if not updates:
        return None, control_error(
            "no_mutation_fields",
            "At least one mutable field is required.",
            command_id=command_id,
        )

    return {"command_id": command_id, "updates": updates}, None


def control_ack(command_id: str, state_version: int, updates: Dict[str, Any], deduplicated: bool) -> Dict[str, Any]:
    return {
        "type": "control_ack",
        "ok": True,
        "command_id": command_id,
        "state_version": state_version,
        "deduplicated": deduplicated,
        "applied": dict(updates),
    }


async def apply_control_command(command: Dict[str, Any]) -> Dict[str, Any]:
    command_id = str(command["command_id"])
    updates = dict(command.get("updates") or {})

    lock = getattr(app.state, "control_lock", None)
    if lock is None:
        lock = asyncio.Lock()
        app.state.control_lock = lock

    async with lock:
        cache = getattr(app.state, "control_command_results", None)
        if not isinstance(cache, OrderedDict):
            cache = OrderedDict()
            app.state.control_command_results = cache

        cached = cache.get(command_id)
        if isinstance(cached, dict):
            cache.move_to_end(command_id)
            dedup_ack = dict(cached)
            dedup_ack["deduplicated"] = True
            return dedup_ack

        if "escalation_regulator" in updates:
            app.state.escalation_regulator = float(updates["escalation_regulator"])
        if "metrics_source" in updates:
            app.state.metrics_source = str(updates["metrics_source"])
        if "experience_profile" in updates:
            normalized_profile = normalize_experience_profile_name(updates["experience_profile"])
            app.state.experience_profile = normalized_profile
            updates["experience_profile"] = normalized_profile

        state_version = int(getattr(app.state, "control_state_version", 0)) + 1
        app.state.control_state_version = state_version

        ack = control_ack(command_id, state_version, updates, deduplicated=False)
        cache[command_id] = ack
        while len(cache) > CONTROL_COMMAND_CACHE_MAX_ENTRIES:
            cache.popitem(last=False)
        return dict(ack)


def extract_cpu_ram() -> Tuple[float, float]:
    cpu = psutil.cpu_percent(interval=None)
    ram = psutil.virtual_memory().percent
    return cpu, ram


def extract_gpu_stats() -> Dict[str, float]:
    """Extract GPU stats using multi-GPU detector with fallback to nvidia-smi."""
    try:
        # Reuse the module-level cached detector (probes once, caches result).
        from gpu_detector import _gpu_detector, MultiGPUDetector
        import gpu_detector as _gd
        if _gd._gpu_detector is None:
            _gd._gpu_detector = MultiGPUDetector()
        metrics = _gd._gpu_detector.detect_gpus()
        
        if metrics.is_available():
            return {
                "gpu_util": metrics.utilization,
                "gpu_temp_c": metrics.temperature,
                "gpu_power_w": metrics.power_usage,
                "gpu_mem_pct": metrics.memory_usage,
            }
    except Exception:
        pass
        
    # Fallback to original nvidia-smi method
    try:
        output = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,temperature.gpu,power.draw,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        values = []
        temps = []
        powers = []
        mem_pcts = []
        for line in output.splitlines():
            if not line.strip():
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 5:
                continue
            util = float(parts[0])
            temp = float(parts[1])
            power = float(parts[2])
            mem_used = float(parts[3])
            mem_total = float(parts[4])
            mem_pct = (mem_used / mem_total * 100.0) if mem_total > 0 else 0.0
            values.append(util)
            temps.append(temp)
            powers.append(power)
            mem_pcts.append(mem_pct)
        if not values:
            return {"gpu_util": 0.0, "gpu_temp_c": 0.0, "gpu_power_w": 0.0, "gpu_mem_pct": 0.0}
        return {
            "gpu_util": sum(values) / len(values),
            "gpu_temp_c": sum(temps) / len(temps),
            "gpu_power_w": sum(powers) / len(powers),
            "gpu_mem_pct": sum(mem_pcts) / len(mem_pcts),
        }
    except Exception:
        return {"gpu_util": 0.0, "gpu_temp_c": 0.0, "gpu_power_w": 0.0, "gpu_mem_pct": 0.0}


def extract_cpu_temp() -> float:
    try:
        temps = psutil.sensors_temperatures(fahrenheit=False)
        if not temps:
            return 0.0
        candidates = []
        for entries in temps.values():
            for entry in entries:
                current = getattr(entry, "current", None)
                if current is not None:
                    candidates.append(float(current))
        return max(candidates) if candidates else 0.0
    except Exception:
        return 0.0


def extract_load1_percent() -> float:
    try:
        if not hasattr(os, "getloadavg"):
            return 0.0
        load1, _, _ = os.getloadavg()
        cores = max(psutil.cpu_count() or 1, 1)
        return max(0.0, min((load1 / cores) * 100.0, 100.0))
    except Exception:
        return 0.0


def extract_cpu_freq_mhz() -> float:
    try:
        freq = psutil.cpu_freq()
        return float(freq.current) if freq else 0.0
    except Exception:
        return 0.0


def extract_iowait_percent() -> float:
    try:
        times = psutil.cpu_times_percent(interval=None)
        return float(getattr(times, "iowait", 0.0))
    except Exception:
        return 0.0


class ThroughputTracker:
    """Tracks disk and network throughput in bytes per second."""

    def __init__(self) -> None:
        self.last_time = time.monotonic()
        self.last_disk_total = self._read_disk_total()
        self.last_net_total = self._read_net_total()
        self.last_net_packets = self._read_net_packets_total()
        self.last_disk_ops = self._read_disk_ops_total()
        self.last_ctx_switches = self._read_ctx_switches_total()
        self.last_interrupts = self._read_interrupts_total()

    @staticmethod
    def _read_disk_total() -> float:
        io = psutil.disk_io_counters()
        if io is None:
            return 0.0
        return float(io.read_bytes + io.write_bytes)

    @staticmethod
    def _read_net_total() -> float:
        io = psutil.net_io_counters()
        if io is None:
            return 0.0
        return float(io.bytes_sent + io.bytes_recv)

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

        disk_total = self._read_disk_total()
        net_total = self._read_net_total()
        net_packets_total = self._read_net_packets_total()
        disk_ops_total = self._read_disk_ops_total()
        ctx_switches_total = self._read_ctx_switches_total()
        interrupts_total = self._read_interrupts_total()

        disk_bps = max(0.0, (disk_total - self.last_disk_total) / elapsed)
        net_bps = max(0.0, (net_total - self.last_net_total) / elapsed)
        net_pps = max(0.0, (net_packets_total - self.last_net_packets) / elapsed)
        disk_iops = max(0.0, (disk_ops_total - self.last_disk_ops) / elapsed)
        ctx_switches_ps = max(0.0, (ctx_switches_total - self.last_ctx_switches) / elapsed)
        interrupts_ps = max(0.0, (interrupts_total - self.last_interrupts) / elapsed)

        self.last_time = now
        self.last_disk_total = disk_total
        self.last_net_total = net_total
        self.last_net_packets = net_packets_total
        self.last_disk_ops = disk_ops_total
        self.last_ctx_switches = ctx_switches_total
        self.last_interrupts = interrupts_total
        return {
            "disk_bps": disk_bps,
            "net_bps": net_bps,
            "net_pps": net_pps,
            "disk_iops": disk_iops,
            "ctx_switches_ps": ctx_switches_ps,
            "interrupts_ps": interrupts_ps,
        }


class NaturalSamplingClock:
    """Adaptive sampling clock that tracks machine activity with bounded cadence."""

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
        # Escalate quickly under load and decay more gradually to preserve tension.
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
    experience_profile: str = DEFAULT_EXPERIENCE_PROFILE,
) -> Tuple[int, int, int, int]:
    profile = resolve_experience_profile(experience_profile)
    scale_notes = profile["scale_notes"]

    cpu = clamp(int(cpu), 0, 100)
    ram = clamp(int(ram), 0, 100)
    gpu = clamp(int(gpu), 0, 100)
    activity_score = clamp_float(activity_score, 0.0, 1.0)

    scaled_index = (cpu / 100) * (len(scale_notes) - 1)

    index = int(scaled_index)

    if activity_score >= 0.65:
        phrase = profile["phrase_high"]
    elif activity_score >= 0.35:
        phrase = profile["phrase_mid"]
    else:
        phrase = profile["phrase_low"]

    phrase_offset = phrase[phrase_step % len(phrase)]
    if disk_busy_pct > profile["disk_busy_trigger"] and (phrase_step % 4 == 3):
        phrase_offset += profile["disk_phrase_push"]
    if iowait_pct > profile["iowait_trigger"] and (phrase_step % 4 == 1):
        phrase_offset += profile["iowait_phrase_push"]

    note = scale_notes[clamp(index + phrase_offset, 0, len(scale_notes) - 1)]
    if phrase_step % 6 == 2:
        note += profile["octave_up_interval"]
    elif phrase_step % 6 == 5 and activity_score < profile["octave_drop_activity_threshold"]:
        note += profile["octave_down_interval"]

    if activity_score > 0.72 and (phrase_step % 5 in (1, 3)):
        note += 12
    elif activity_score < 0.20 and (phrase_step % 8 == 7):
        note -= 12

    if disk_busy_pct > 85.0 and (phrase_step % 6 == 4):
        note += profile["disk_jump_interval"]

    note = clamp(note, 0, 127)

    pitch_bend = 0
    if use_pitch_bend:
        fractional = scaled_index - index
        vibrato = (activity_score * profile["vibrato_depth"]) + min(
            disk_busy_pct / 1000.0,
            profile["disk_vibrato_cap"],
        )
        if phrase_step % 2 == 1:
            vibrato *= -1.0
        # Pitchwheel range is -8192..8191.
        pitch_bend = clamp(int((fractional + vibrato) * 4096), -8192, 8191)

    velocity = clamp(
        int((ram / 100) * 127 + (activity_score * profile["velocity_activity_boost"]) + profile["velocity_bias"]),
        0,
        127,
    )
    modulation = clamp(
        int((gpu / 100) * 104 + (disk_busy_pct / 100.0) * 23 + profile["modulation_bias"]),
        0,
        127,
    )

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


async def sonification_loop(
    use_pitch_bend: bool = False,
    midi_port_hint: str = "",
    enable_midi: bool = False,
    metrics_source: str = "local",
    external_max_age_s: float = EXTERNAL_FRAME_MAX_AGE_SECONDS,
    midi_program: int = DROID_MIDI_PROGRAM,
    droid_mode: bool = True,
    escalation_regulator: float = 1.0,
):
    smoother = Smoother(SMOOTH_WINDOW)
    throughput = ThroughputTracker()
    machine_inputs = MachineInputTracker()
    sampling_clock = NaturalSamplingClock(escalation_regulator=escalation_regulator)
    phrase_step = 0
    port = None
    cached_gpu_stats = {"gpu_util": 0.0, "gpu_temp_c": 0.0, "gpu_power_w": 0.0, "gpu_mem_pct": 0.0}
    cached_process_count = 0.0
    last_gpu_poll_t = 0.0
    last_proc_poll_t = 0.0
    if enable_midi:
        try:
            names = mido.get_output_names()
            if names:
                if midi_port_hint:
                    for name in names:
                        if midi_port_hint in name:
                            port = mido.open_output(name)
                            break
                if not port:
                    fluid_name = next((name for name in names if "fluid" in name.lower()), None)
                    non_through_name = next(
                        (name for name in names if "midi through" not in name.lower()),
                        None,
                    )
                    port = mido.open_output(fluid_name or non_through_name or names[0])
                print(f"Using MIDI output: {port.name}")
                initialize_midi_voice(port, midi_program=midi_program, droid_mode=droid_mode)
        except Exception as exc:
            print(f"MIDI output initialization failed: {exc}. Continuing with WebSocket only.")
    else:
        print("MIDI output disabled; continuing with WebSocket only.")

    try:
        while True:
            sampling_clock.escalation_regulator = clamp_float(
                float(getattr(app.state, "escalation_regulator", sampling_clock.escalation_regulator)),
                0.35,
                2.5,
            )

            now = time.monotonic()
            cpu_raw, ram_raw = extract_cpu_ram()
            if (now - last_gpu_poll_t) >= GPU_POLL_MIN_INTERVAL_SECONDS:
                cached_gpu_stats = extract_gpu_stats()
                last_gpu_poll_t = now
            gpu_stats = dict(cached_gpu_stats)
            rates = throughput.sample()
            extra = machine_inputs.sample()
            swap_percent = float(psutil.swap_memory().percent)
            if (now - last_proc_poll_t) >= PROC_COUNT_POLL_MIN_INTERVAL_SECONDS:
                cached_process_count = float(len(psutil.pids()))
                last_proc_poll_t = now
            process_count = cached_process_count
            cpu_temp_c = extract_cpu_temp()
            load1_pct = extract_load1_percent()
            cpu_freq_mhz = extract_cpu_freq_mhz()
            iowait_pct = extract_iowait_percent()

            source_state = "local"
            external_snapshot: Optional[Dict[str, float]] = None
            if metrics_source == "external":
                external_snapshot = external_telemetry.snapshot(external_max_age_s)
                source_state = "external" if external_snapshot else "local-fallback"

            def overlay(current: float, key: str) -> float:
                if not external_snapshot:
                    return current
                candidate = external_snapshot.get(key)
                return current if candidate is None else float(candidate)

            cpu_input = overlay(cpu_raw, "cpu")
            ram_input = overlay(ram_raw, "ram")
            gpu_input = overlay(gpu_stats["gpu_util"], "gpu")

            for key in ("disk_bps", "net_bps", "net_pps", "disk_iops", "ctx_switches_ps", "interrupts_ps"):
                rates[key] = overlay(rates[key], key)

            for key in (
                "disk_busy_pct",
                "net_errors_ps",
                "net_drops_ps",
                "storage_temp_c",
                "power_w",
                "energy_j_total",
                "battery_power_w",
            ):
                extra[key] = overlay(extra[key], key)

            swap_percent = overlay(swap_percent, "swap_pct")
            process_count = overlay(process_count, "proc_count")
            cpu_temp_c = overlay(cpu_temp_c, "cpu_temp_c")
            load1_pct = overlay(load1_pct, "load1_pct")
            cpu_freq_mhz = overlay(cpu_freq_mhz, "cpu_freq_mhz")
            iowait_pct = overlay(iowait_pct, "iowait_pct")

            gpu_stats["gpu_temp_c"] = overlay(gpu_stats["gpu_temp_c"], "gpu_temp_c")
            gpu_stats["gpu_power_w"] = overlay(gpu_stats["gpu_power_w"], "gpu_power_w")
            gpu_stats["gpu_mem_pct"] = overlay(gpu_stats["gpu_mem_pct"], "gpu_mem_pct")
            
            metrics = {
                "cpu": smoother.smooth("cpu", cpu_input),
                "ram": smoother.smooth("ram", ram_input),
                "gpu": smoother.smooth("gpu", gpu_input),
            }

            sample_interval_s, activity_score = sampling_clock.update(metrics, rates, extra)

            note_length_seconds = clamp_float(
                sample_interval_s * (0.32 + activity_score * 0.18),
                MIN_NOTE_LENGTH_SECONDS,
                MAX_NOTE_LENGTH_SECONDS,
            )

            experience_profile = normalize_experience_profile_name(
                getattr(app.state, "experience_profile", DEFAULT_EXPERIENCE_PROFILE)
            )

            note, velocity, modulation, pitch_bend = map_to_midi(
                metrics["cpu"],
                metrics["ram"],
                metrics["gpu"],
                use_pitch_bend,
                activity_score=activity_score,
                phrase_step=phrase_step,
                iowait_pct=iowait_pct,
                disk_busy_pct=extra["disk_busy_pct"],
                experience_profile=experience_profile,
            )
            phrase_step += 1
            
            # Broadcast to Web Dashboard
            payload = {
                "cpu": metrics["cpu"],
                "ram": metrics["ram"],
                "gpu": metrics["gpu"],
                "disk_bps": rates["disk_bps"],
                "net_bps": rates["net_bps"],
                "net_pps": rates["net_pps"],
                "disk_iops": rates["disk_iops"],
                "disk_busy_pct": extra["disk_busy_pct"],
                "ctx_switches_ps": rates["ctx_switches_ps"],
                "interrupts_ps": rates["interrupts_ps"],
                "net_errors_ps": extra["net_errors_ps"],
                "net_drops_ps": extra["net_drops_ps"],
                "gpu_temp_c": gpu_stats["gpu_temp_c"],
                "gpu_power_w": gpu_stats["gpu_power_w"],
                "gpu_mem_pct": gpu_stats["gpu_mem_pct"],
                "storage_temp_c": extra["storage_temp_c"],
                "power_w": extra["power_w"],
                "energy_j_total": extra["energy_j_total"],
                "battery_power_w": extra["battery_power_w"],
                "cpu_temp_c": cpu_temp_c,
                "cpu_freq_mhz": cpu_freq_mhz,
                "load1_pct": load1_pct,
                "swap_pct": swap_percent,
                "iowait_pct": iowait_pct,
                "proc_count": process_count,
                "tension": clamp(int((metrics["cpu"] * 0.45) + (metrics["ram"] * 0.30) + (metrics["gpu"] * 0.25)), 0, 100),
                "sample_hz": sampling_clock.current_hz,
                "sample_interval_ms": sample_interval_s * 1000.0,
                "note_length_ms": note_length_seconds * 1000.0,
                "activity_score": activity_score,
                "escalation_regulator": sampling_clock.escalation_regulator,
                "metrics_source": source_state,
                "experience_profile": experience_profile,
                "audio_style": "droid" if droid_mode else "classic",
                "midi": {
                    "note": note,
                    "velocity": velocity,
                    "modulation": modulation,
                    "pitch_bend": pitch_bend,
                    "program": clamp(int(midi_program), 0, 127),
                }
            }
            app.state.latest_payload = dict(payload)
            # Diagnostic: Print a summary of broadcasted data every 10 beats
            if int(time.time() * 2) % 20 == 0:
                print(
                    f"[SONIC] CPU:{payload['cpu']:.1f}% RAM:{payload['ram']:.1f}% "
                      f"GPU:{payload['gpu']:.1f}% Note:{note} Hz:{payload['sample_hz']:.2f} "
                                            f"Act:{activity_score:.2f} EscReg:{sampling_clock.escalation_regulator:.2f} Source:{source_state}"
                )
                
            await manager.broadcast(payload)
            
            # MIDI Playback
            if port:
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

            remaining = sample_interval_s - note_length_seconds
            if remaining > 0:
                await asyncio.sleep(remaining)

    except asyncio.CancelledError:
        print("Sonification loop stopping.")
    finally:
        if port:
            port.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Hardware Sonification WebSocket Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8001, help="Port to bind to")
    parser.add_argument(
        "--metrics-source",
        choices=["local", "external"],
        default="local",
        help="Telemetry source mode: local collectors or external websocket ingest overlay.",
    )
    parser.add_argument(
        "--external-max-age-s",
        type=float,
        default=EXTERNAL_FRAME_MAX_AGE_SECONDS,
        help="Maximum age in seconds for external telemetry before falling back to local values.",
    )
    parser.add_argument("--midi-port-hint", default="FLUID", help="Preferred MIDI output port name hint.")
    parser.add_argument(
        "--enable-midi",
        action="store_true",
        help="Enable backend MIDI output. Leave off for web monitor mode or browser-audio-only use.",
    )
    parser.add_argument(
        "--no-pitch-bend",
        action="store_true",
        help="Disable pitch bend for systems or synths that do not handle pitchwheel smoothly.",
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
        "--ws-max-size-bytes",
        type=int,
        default=DEFAULT_WS_MAX_SIZE_BYTES,
        help="Maximum accepted websocket frame size for uvicorn/websockets transport.",
    )
    parser.add_argument(
        "--ws-max-queue",
        type=int,
        default=DEFAULT_WS_MAX_QUEUE,
        help="Maximum queued websocket messages per connection inside uvicorn.",
    )
    args = parser.parse_args()

    app.state.metrics_source = args.metrics_source
    app.state.external_max_age_s = max(0.2, float(args.external_max_age_s))
    app.state.midi_port_hint = args.midi_port_hint
    app.state.enable_midi = args.enable_midi
    app.state.use_pitch_bend = not args.no_pitch_bend
    app.state.midi_program = args.midi_program
    app.state.droid_mode = not args.classic_voice
    app.state.escalation_regulator = args.escalation_regulator
    app.state.ws_token = os.getenv("HSP_WS_TOKEN", "")
    app.state.ingest_token = os.getenv("HSP_INGEST_TOKEN", app.state.ws_token)
    app.state.control_command_results = OrderedDict()
    app.state.control_state_version = 0
    app.state.experience_profile = DEFAULT_EXPERIENCE_PROFILE
    
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        ws_max_size=max(4096, int(args.ws_max_size_bytes)),
        ws_max_queue=max(1, int(args.ws_max_queue)),
        ws_per_message_deflate=False,
    )
