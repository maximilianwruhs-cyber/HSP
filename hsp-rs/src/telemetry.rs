use std::fmt;
use std::fs;
use std::io;

use crate::fixed::average_u16;
use crate::ring::RingBuffer;
use crate::state::{MetricsSource, Permille, TelemetryFrame};
use crate::gpu;

const EXTERNAL_OVERLAY_TIMEOUT_MS: u32 = 3_000;

#[derive(Debug, Default)]
pub struct TelemetryState {
    seq: u32,
    last_slow_ms: u32,
    cpu_window: RingBuffer<Permille, 5>,
    ram_window: RingBuffer<Permille, 5>,
    gpu_window: RingBuffer<Permille, 5>,
    external_overlay: Option<TelemetryFrame>,
    last_external_update_ms: u32,
}

#[derive(Debug)]
pub enum TelemetryError {
    Io(io::Error),
}

impl fmt::Display for TelemetryError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Io(error) => write!(f, "telemetry io error: {error}"),
        }
    }
}

impl std::error::Error for TelemetryError {}

impl From<io::Error> for TelemetryError {
    fn from(value: io::Error) -> Self {
        Self::Io(value)
    }
}

pub fn sample_fast(
    now_ms: u32,
    out: &mut TelemetryFrame,
    state: &mut TelemetryState,
    use_external_overlay: bool,
) -> Result<(), TelemetryError> {
    state.seq = state.seq.wrapping_add(1);

    if use_external_overlay {
        if now_ms.saturating_sub(state.last_external_update_ms) > EXTERNAL_OVERLAY_TIMEOUT_MS {
            state.external_overlay = None;
        }

        if let Some(mut overlay) = state.external_overlay {
            overlay.seq = state.seq;
            overlay.now_ms = now_ms;
            overlay.source = MetricsSource::External;
            *out = overlay;
            return Ok(());
        }
    }

    let ram_permille = read_ram_permille().unwrap_or(0);
    let load1_permille = read_load1_permille().unwrap_or(0);
    let proc_count = read_proc_count().unwrap_or(0);

    state.cpu_window.push(load1_permille);
    state.ram_window.push(ram_permille);
    
    // Get GPU utilization using multi-GPU detector
    let gpu_util_permille = gpu::get_gpu_utilization_permille();
    state.gpu_window.push(gpu_util_permille);

    *out = TelemetryFrame {
        seq: state.seq,
        now_ms,
        cpu_permille: average_u16(state.cpu_window.iter()),
        ram_permille: average_u16(state.ram_window.iter()),
        gpu_permille: average_u16(state.gpu_window.iter()),
        load1_permille,
        proc_count,
        source: MetricsSource::Local,
        ..TelemetryFrame::default()
    };

    Ok(())
}

pub fn sample_slow(now_ms: u32, out: &mut TelemetryFrame, state: &mut TelemetryState) -> Result<(), TelemetryError> {
    state.last_slow_ms = now_ms;
    out.cpu_temp_deci_c = 0;
    out.gpu_temp_deci_c = 0;
    out.storage_temp_deci_c = 0;
    out.power_deci_w = 0;
    out.gpu_power_deci_w = 0;
    out.battery_power_deci_w = 0;
    Ok(())
}

pub fn update_external_overlay(state: &mut TelemetryState, frame: TelemetryFrame, now_ms: u32) {
    state.external_overlay = Some(frame);
    state.last_external_update_ms = now_ms;
}

fn read_ram_permille() -> io::Result<u16> {
    let text = fs::read_to_string("/proc/meminfo")?;
    let mut total_kib = 0u64;
    let mut available_kib = 0u64;

    for line in text.lines() {
        if let Some(rest) = line.strip_prefix("MemTotal:") {
            total_kib = parse_first_u64(rest).unwrap_or(0);
        }
        if let Some(rest) = line.strip_prefix("MemAvailable:") {
            available_kib = parse_first_u64(rest).unwrap_or(0);
        }
    }

    if total_kib == 0 {
        return Ok(0);
    }

    let used_kib = total_kib.saturating_sub(available_kib);
    Ok(((used_kib * 1_000) / total_kib) as u16)
}

fn read_load1_permille() -> io::Result<u16> {
    let text = fs::read_to_string("/proc/loadavg")?;
    let load = text
        .split_whitespace()
        .next()
        .and_then(|value| value.parse::<f32>().ok())
        .unwrap_or(0.0);
    let scaled = (load * 1_000.0).round();
    Ok(scaled.clamp(0.0, 1_000.0) as u16)
}

fn read_proc_count() -> io::Result<u16> {
    let mut count = 0u16;
    for entry in fs::read_dir("/proc")? {
        let entry = entry?;
        let name = entry.file_name();
        let text = name.to_string_lossy();
        if text.bytes().all(|byte| byte.is_ascii_digit()) {
            count = count.saturating_add(1);
        }
    }
    Ok(count)
}

fn parse_first_u64(text: &str) -> Option<u64> {
    text.split_whitespace().next()?.parse::<u64>().ok()
}
