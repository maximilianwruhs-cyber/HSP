use crate::state::{AudioStyle, MidiEvent, ProfileId, RuntimeState, TelemetryFrame, TickPlan};

#[derive(Copy, Clone)]
struct ProfileMap {
    scale_notes: &'static [i16],
    phrase_high: &'static [i16],
    phrase_mid: &'static [i16],
    phrase_low: &'static [i16],
    disk_busy_trigger_permille: u16,
    disk_phrase_push: i16,
    iowait_trigger_permille: u16,
    iowait_phrase_push: i16,
    octave_up_interval: i16,
    octave_down_interval: i16,
    octave_drop_activity_permille: u16,
    disk_jump_interval: i16,
    vibrato_depth_permille: u16,
    disk_vibrato_cap_permille: u16,
    velocity_bias: i16,
    velocity_activity_boost_milli: u16,
    modulation_bias: i16,
}

const SCALE_NIGHT: [i16; 7] = [60, 62, 63, 65, 67, 68, 70];
const SCALE_AMBIENT: [i16; 7] = [48, 50, 52, 55, 57, 59, 62];
const SCALE_INDUSTRIAL: [i16; 7] = [50, 51, 53, 55, 56, 58, 60];
const SCALE_DNB: [i16; 7] = [62, 63, 65, 67, 68, 70, 72];
const SCALE_HORROR: [i16; 7] = [48, 50, 51, 54, 55, 57, 60];
const SCALE_HTOP: [i16; 7] = [59, 60, 62, 64, 65, 67, 69];

const NIGHT_PHRASE_HIGH: [i16; 6] = [0, 3, 5, 2, -2, 4];
const NIGHT_PHRASE_MID: [i16; 6] = [0, 2, -1, 3, -2, 1];
const NIGHT_PHRASE_LOW: [i16; 8] = [0, 2, -2, 3, -1, 4, -3, 1];

const AMBIENT_PHRASE_HIGH: [i16; 6] = [0, 2, 3, 1, 0, -1];
const AMBIENT_PHRASE_MID: [i16; 6] = [0, 1, 0, 2, -1, 1];
const AMBIENT_PHRASE_LOW: [i16; 6] = [0, 1, -1, 2, 0, -2];

const INDUSTRIAL_PHRASE_HIGH: [i16; 6] = [0, 4, 6, 3, -3, 5];
const INDUSTRIAL_PHRASE_MID: [i16; 6] = [0, 3, -2, 4, -3, 2];
const INDUSTRIAL_PHRASE_LOW: [i16; 8] = [0, 2, -3, 4, -2, 5, -4, 2];

const DNB_PHRASE_HIGH: [i16; 6] = [0, 5, 2, 6, -3, 4];
const DNB_PHRASE_MID: [i16; 6] = [0, 3, -1, 4, -2, 2];
const DNB_PHRASE_LOW: [i16; 8] = [0, 2, -2, 3, -1, 4, -3, 1];

const HORROR_PHRASE_HIGH: [i16; 6] = [0, 4, 7, 3, -4, 5];
const HORROR_PHRASE_MID: [i16; 6] = [0, 2, -2, 4, -3, 2];
const HORROR_PHRASE_LOW: [i16; 8] = [0, 1, -3, 2, -2, 4, -5, 1];

const HTOP_PHRASE_HIGH: [i16; 6] = [0, 2, 4, 1, -1, 3];
const HTOP_PHRASE_MID: [i16; 6] = [0, 1, -1, 2, -2, 1];
const HTOP_PHRASE_LOW: [i16; 8] = [0, 1, -2, 2, -1, 3, -3, 0];

const NIGHT_PROFILE: ProfileMap = ProfileMap {
    scale_notes: &SCALE_NIGHT,
    phrase_high: &NIGHT_PHRASE_HIGH,
    phrase_mid: &NIGHT_PHRASE_MID,
    phrase_low: &NIGHT_PHRASE_LOW,
    disk_busy_trigger_permille: 700,
    disk_phrase_push: 1,
    iowait_trigger_permille: 200,
    iowait_phrase_push: -1,
    octave_up_interval: 12,
    octave_down_interval: -12,
    octave_drop_activity_permille: 500,
    disk_jump_interval: 7,
    vibrato_depth_permille: 140,
    disk_vibrato_cap_permille: 60,
    velocity_bias: 0,
    velocity_activity_boost_milli: 8_000,
    modulation_bias: 0,
};

const AMBIENT_PROFILE: ProfileMap = ProfileMap {
    scale_notes: &SCALE_AMBIENT,
    phrase_high: &AMBIENT_PHRASE_HIGH,
    phrase_mid: &AMBIENT_PHRASE_MID,
    phrase_low: &AMBIENT_PHRASE_LOW,
    disk_busy_trigger_permille: 800,
    disk_phrase_push: 0,
    iowait_trigger_permille: 280,
    iowait_phrase_push: -1,
    octave_up_interval: 7,
    octave_down_interval: -12,
    octave_drop_activity_permille: 420,
    disk_jump_interval: 5,
    vibrato_depth_permille: 80,
    disk_vibrato_cap_permille: 30,
    velocity_bias: -12,
    velocity_activity_boost_milli: 4_000,
    modulation_bias: -10,
};

const INDUSTRIAL_PROFILE: ProfileMap = ProfileMap {
    scale_notes: &SCALE_INDUSTRIAL,
    phrase_high: &INDUSTRIAL_PHRASE_HIGH,
    phrase_mid: &INDUSTRIAL_PHRASE_MID,
    phrase_low: &INDUSTRIAL_PHRASE_LOW,
    disk_busy_trigger_permille: 620,
    disk_phrase_push: 2,
    iowait_trigger_permille: 150,
    iowait_phrase_push: -2,
    octave_up_interval: 12,
    octave_down_interval: -12,
    octave_drop_activity_permille: 580,
    disk_jump_interval: 8,
    vibrato_depth_permille: 200,
    disk_vibrato_cap_permille: 90,
    velocity_bias: 8,
    velocity_activity_boost_milli: 12_000,
    modulation_bias: 16,
};

const DNB_PROFILE: ProfileMap = ProfileMap {
    scale_notes: &SCALE_DNB,
    phrase_high: &DNB_PHRASE_HIGH,
    phrase_mid: &DNB_PHRASE_MID,
    phrase_low: &DNB_PHRASE_LOW,
    disk_busy_trigger_permille: 580,
    disk_phrase_push: 2,
    iowait_trigger_permille: 140,
    iowait_phrase_push: -1,
    octave_up_interval: 12,
    octave_down_interval: -12,
    octave_drop_activity_permille: 550,
    disk_jump_interval: 9,
    vibrato_depth_permille: 180,
    disk_vibrato_cap_permille: 90,
    velocity_bias: 10,
    velocity_activity_boost_milli: 10_000,
    modulation_bias: 10,
};

const HORROR_PROFILE: ProfileMap = ProfileMap {
    scale_notes: &SCALE_HORROR,
    phrase_high: &HORROR_PHRASE_HIGH,
    phrase_mid: &HORROR_PHRASE_MID,
    phrase_low: &HORROR_PHRASE_LOW,
    disk_busy_trigger_permille: 550,
    disk_phrase_push: 2,
    iowait_trigger_permille: 120,
    iowait_phrase_push: -2,
    octave_up_interval: 12,
    octave_down_interval: -12,
    octave_drop_activity_permille: 600,
    disk_jump_interval: 10,
    vibrato_depth_permille: 220,
    disk_vibrato_cap_permille: 100,
    velocity_bias: 12,
    velocity_activity_boost_milli: 12_000,
    modulation_bias: 18,
};

const HTOP_PROFILE: ProfileMap = ProfileMap {
    scale_notes: &SCALE_HTOP,
    phrase_high: &HTOP_PHRASE_HIGH,
    phrase_mid: &HTOP_PHRASE_MID,
    phrase_low: &HTOP_PHRASE_LOW,
    disk_busy_trigger_permille: 680,
    disk_phrase_push: 1,
    iowait_trigger_permille: 180,
    iowait_phrase_push: -1,
    octave_up_interval: 12,
    octave_down_interval: -12,
    octave_drop_activity_permille: 480,
    disk_jump_interval: 7,
    vibrato_depth_permille: 100,
    disk_vibrato_cap_permille: 50,
    velocity_bias: -4,
    velocity_activity_boost_milli: 6_000,
    modulation_bias: 6,
};

fn profile_map(profile_id: ProfileId) -> &'static ProfileMap {
    match profile_id {
        ProfileId::NightPatrolTechno => &NIGHT_PROFILE,
        ProfileId::CalmObservatoryAmbient => &AMBIENT_PROFILE,
        ProfileId::HighLoadAlarmIndustrial => &INDUSTRIAL_PROFILE,
        ProfileId::ChaosFestivalDnb => &DNB_PROFILE,
        ProfileId::DroidHorrorEscalation => &HORROR_PROFILE,
        ProfileId::HtopObserver => &HTOP_PROFILE,
    }
}

fn clamp_i32(value: i32, min_value: i32, max_value: i32) -> i32 {
    value.max(min_value).min(max_value)
}

pub fn map_frame(frame: &TelemetryFrame, state: &RuntimeState, tick: &TickPlan, out: &mut MidiEvent) {
    let profile = profile_map(state.profile_id);
    let scale_len = profile.scale_notes.len().max(1);
    let scale_span = (scale_len.saturating_sub(1)) as i32;

    // Keep three decimal places of the scale index to preserve micro-motion for pitch bend.
    let scaled_index_milli = frame.cpu_permille as i32 * scale_span;
    let index = clamp_i32(scaled_index_milli / 1_000, 0, scale_span);

    let phrase = if tick.activity_permille >= 650 {
        profile.phrase_high
    } else if tick.activity_permille >= 350 {
        profile.phrase_mid
    } else {
        profile.phrase_low
    };

    let mut phrase_offset = phrase[(state.phrase_step as usize) % phrase.len()];
    if frame.disk_busy_permille > profile.disk_busy_trigger_permille && state.phrase_step % 4 == 3 {
        phrase_offset += profile.disk_phrase_push;
    }
    if frame.iowait_permille > profile.iowait_trigger_permille && state.phrase_step % 4 == 1 {
        phrase_offset += profile.iowait_phrase_push;
    }

    let note_index = clamp_i32(index + phrase_offset as i32, 0, scale_span) as usize;
    let mut note = profile.scale_notes[note_index] as i32;

    if state.phrase_step % 6 == 2 {
        note += profile.octave_up_interval as i32;
    } else if state.phrase_step % 6 == 5 && tick.activity_permille < profile.octave_drop_activity_permille {
        note += profile.octave_down_interval as i32;
    }

    if tick.activity_permille > 720 && matches!(state.phrase_step % 5, 1 | 3) {
        note += 12;
    } else if tick.activity_permille < 200 && state.phrase_step % 8 == 7 {
        note -= 12;
    }

    if frame.disk_busy_permille > 850 && state.phrase_step % 6 == 4 {
        note += profile.disk_jump_interval as i32;
    }

    out.note = clamp_i32(note, 0, 127) as u8;

    let velocity_base = (frame.ram_permille as i32 * 127) / 1_000;
    let activity_boost = (tick.activity_permille as i32 * profile.velocity_activity_boost_milli as i32) / 1_000_000;
    out.velocity = clamp_i32(velocity_base + activity_boost + profile.velocity_bias as i32, 0, 127) as u8;

    let modulation_base =
        ((frame.gpu_permille as i32 * 104) + (frame.disk_busy_permille as i32 * 23)) / 1_000;
    out.modulation = clamp_i32(modulation_base + profile.modulation_bias as i32, 0, 127) as u8;

    let fractional_permille = scaled_index_milli - (index * 1_000);
    let activity_vibrato_permille = (tick.activity_permille as i32 * profile.vibrato_depth_permille as i32) / 1_000;
    let disk_vibrato_permille = frame
        .disk_busy_permille
        .min(profile.disk_vibrato_cap_permille) as i32;
    let mut vibrato_permille = activity_vibrato_permille + disk_vibrato_permille;
    if state.phrase_step % 2 == 1 {
        vibrato_permille = -vibrato_permille;
    }

    out.pitch_bend = clamp_i32(
        ((fractional_permille + vibrato_permille) * 4_096) / 1_000,
        -8_192,
        8_191,
    ) as i16;
    out.duration_ms = tick.note_length_ms;
    out.flags = match state.audio_style {
        AudioStyle::Droid => 1,
        AudioStyle::Classic => 0,
    };
}

#[cfg(test)]
mod tests {
    use super::map_frame;
    use crate::state::{AudioStyle, MetricsSource, MidiEvent, ProfileId, RuntimeState, TelemetryFrame, TickPlan};

    fn test_frame() -> TelemetryFrame {
        TelemetryFrame {
            cpu_permille: 810,
            ram_permille: 670,
            gpu_permille: 730,
            disk_busy_permille: 880,
            iowait_permille: 240,
            ..TelemetryFrame::default()
        }
    }

    fn test_tick() -> TickPlan {
        TickPlan {
            interval_ms: 260,
            note_length_ms: 96,
            activity_permille: 740,
        }
    }

    fn test_state(profile_id: ProfileId) -> RuntimeState {
        RuntimeState {
            profile_id,
            metrics_source: MetricsSource::Local,
            audio_style: AudioStyle::Droid,
            reserved0: 0,
            escalation_permille: 1_000,
            ui_publish_hz: 4,
            state_version: 0,
            phrase_step: 11,
        }
    }

    #[test]
    fn profile_mapping_changes_output() {
        let frame = test_frame();
        let tick = test_tick();

        let mut ambient = MidiEvent::default();
        map_frame(
            &frame,
            &test_state(ProfileId::CalmObservatoryAmbient),
            &tick,
            &mut ambient,
        );

        let mut industrial = MidiEvent::default();
        map_frame(
            &frame,
            &test_state(ProfileId::HighLoadAlarmIndustrial),
            &tick,
            &mut industrial,
        );

        let mut htop = MidiEvent::default();
        map_frame(&frame, &test_state(ProfileId::HtopObserver), &tick, &mut htop);

        assert_ne!(ambient.note, industrial.note);
        assert_ne!(ambient.velocity, industrial.velocity);
        assert_ne!(industrial.modulation, htop.modulation);
        assert_ne!(ambient.pitch_bend, htop.pitch_bend);
    }

    #[test]
    fn mapper_clamps_ranges() {
        let frame = TelemetryFrame {
            cpu_permille: 1_000,
            ram_permille: 1_000,
            gpu_permille: 1_000,
            disk_busy_permille: 1_000,
            iowait_permille: 1_000,
            ..TelemetryFrame::default()
        };
        let tick = TickPlan {
            interval_ms: 100,
            note_length_ms: 100,
            activity_permille: 1_000,
        };

        let mut event = MidiEvent::default();
        map_frame(
            &frame,
            &test_state(ProfileId::DroidHorrorEscalation),
            &tick,
            &mut event,
        );

        assert!(event.note <= 127);
        assert!(event.velocity <= 127);
        assert!(event.modulation <= 127);
        assert!((-8_192..=8_191).contains(&event.pitch_bend));
    }
}
