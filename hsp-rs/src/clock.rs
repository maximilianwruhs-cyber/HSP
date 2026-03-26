use crate::fixed::{clamp_u16, clamp_u32, lerp_u16};
use crate::state::{ClockState, TelemetryFrame, TickPlan};

pub fn update_clock(clock: &mut ClockState, frame: &TelemetryFrame) -> TickPlan {
    let cpu = frame.cpu_permille as u32;
    let ram = frame.ram_permille as u32;
    let gpu = frame.gpu_permille as u32;
    let pressure = frame.disk_busy_permille as u32;

    let delta_cpu = cpu.abs_diff(clock.last_cpu_permille as u32);
    let delta_ram = ram.abs_diff(clock.last_ram_permille as u32);
    let delta_gpu = gpu.abs_diff(clock.last_gpu_permille as u32);

    let delta_score = ((delta_cpu + delta_ram + delta_gpu) / 3).min(1_000);
    let motion_score = ((delta_score * 35) + (pressure * 10)) / 45;
    let load_score = ((cpu * 50) + (ram * 18) + (gpu * 20) + (pressure * 12)) / 100;

    let escalation_bias = clock.escalation_permille.saturating_sub(1_000) as u32;
    let load_weight = clamp_u32(550 + ((escalation_bias * 180) / 1_500), 350, 850);
    let motion_weight = 1_000u32.saturating_sub(load_weight);
    let mut activity = ((motion_score * motion_weight) + (load_score * load_weight)) / 1_000;

    if load_score > 700 {
        activity = activity.saturating_add(((load_score - 700) * clock.escalation_permille as u32) / 2_000);
    }
    activity = clamp_u32(activity, 0, 1_000);

    let target_millihz = lerp_u16(clock.min_millihz, clock.max_millihz, activity as u16);
    let rise_alpha = clamp_u32(550 + ((escalation_bias * 180) / 1_500), 250, 900);
    let fall_alpha = clamp_u32(220 + ((escalation_bias * 60) / 1_500), 120, 500);
    let alpha = if target_millihz > clock.current_millihz {
        rise_alpha
    } else {
        fall_alpha
    };

    let current = clock.current_millihz as u32;
    let next = (((current * (1_000 - alpha)) + (target_millihz as u32 * alpha)) / 1_000)
        .clamp(clock.min_millihz as u32, clock.max_millihz as u32);
    clock.current_millihz = next as u16;
    clock.last_cpu_permille = frame.cpu_permille;
    clock.last_ram_permille = frame.ram_permille;
    clock.last_gpu_permille = frame.gpu_permille;
    clock.last_activity_permille = activity as u16;

    let interval_ms = clamp_u16((1_000_000u32 / clock.current_millihz as u32) as u16, 25, 1_000);
    let note_length_ms = clamp_u16(
        ((interval_ms as u32 * (320 + ((activity * 180) / 1_000))) / 1_000) as u16,
        35,
        160,
    );

    TickPlan {
        interval_ms,
        note_length_ms,
        activity_permille: activity as u16,
    }
}
