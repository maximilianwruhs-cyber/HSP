pub type Permille = u16;
pub type MilliHz = u16;
pub type DeciC = i16;
pub type DeciW = i16;
pub type Rate32 = u32;
pub type SeqNo = u32;

#[repr(u8)]
#[derive(Copy, Clone, Debug, Eq, PartialEq, Default)]
pub enum MetricsSource {
    #[default]
    Local = 0,
    External = 1,
}

impl MetricsSource {
    pub fn from_str(value: &str) -> Result<Self, crate::config::ConfigError> {
        match value.trim().to_ascii_lowercase().as_str() {
            "local" => Ok(Self::Local),
            "external" => Ok(Self::External),
            other => Err(crate::config::ConfigError::InvalidValue(format!(
                "unknown metrics source: {other}"
            ))),
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Self::Local => "local",
            Self::External => "external",
        }
    }
}

#[repr(u8)]
#[derive(Copy, Clone, Debug, Eq, PartialEq, Default)]
pub enum ProfileId {
    #[default]
    NightPatrolTechno = 0,
    CalmObservatoryAmbient = 1,
    HighLoadAlarmIndustrial = 2,
    ChaosFestivalDnb = 3,
    DroidHorrorEscalation = 4,
    HtopObserver = 5,
}

impl ProfileId {
    pub fn from_str(value: &str) -> Result<Self, crate::config::ConfigError> {
        match value.trim().to_ascii_lowercase().as_str() {
            "night-patrol-techno" | "night-patrol" => Ok(Self::NightPatrolTechno),
            "calm-observatory-ambient" | "calm-observatory" => Ok(Self::CalmObservatoryAmbient),
            "high-load-alarm-industrial" | "high-load-alarm" => Ok(Self::HighLoadAlarmIndustrial),
            "chaos-festival-dnb" | "chaos-festival" => Ok(Self::ChaosFestivalDnb),
            "droid-horror-escalation" => Ok(Self::DroidHorrorEscalation),
            "htop-observer" => Ok(Self::HtopObserver),
            other => Err(crate::config::ConfigError::InvalidValue(format!(
                "unknown experience profile: {other}"
            ))),
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Self::NightPatrolTechno => "night-patrol-techno",
            Self::CalmObservatoryAmbient => "calm-observatory-ambient",
            Self::HighLoadAlarmIndustrial => "high-load-alarm-industrial",
            Self::ChaosFestivalDnb => "chaos-festival-dnb",
            Self::DroidHorrorEscalation => "droid-horror-escalation",
            Self::HtopObserver => "htop-observer",
        }
    }
}

#[repr(u8)]
#[derive(Copy, Clone, Debug, Eq, PartialEq, Default)]
pub enum AudioStyle {
    #[default]
    Droid = 0,
    Classic = 1,
}

#[repr(C)]
#[derive(Copy, Clone, Debug, Default)]
pub struct TelemetryFrame {
    pub seq: SeqNo,
    pub now_ms: u32,

    pub cpu_permille: Permille,
    pub ram_permille: Permille,
    pub gpu_permille: Permille,
    pub swap_permille: Permille,
    pub iowait_permille: Permille,
    pub load1_permille: Permille,
    pub disk_busy_permille: Permille,
    pub gpu_mem_permille: Permille,

    pub cpu_temp_deci_c: DeciC,
    pub gpu_temp_deci_c: DeciC,
    pub storage_temp_deci_c: DeciC,

    pub cpu_freq_mhz: u16,
    pub proc_count: u16,

    pub power_deci_w: DeciW,
    pub gpu_power_deci_w: DeciW,
    pub battery_power_deci_w: DeciW,

    pub disk_kib_s: Rate32,
    pub net_kib_s: Rate32,
    pub net_pps: Rate32,
    pub disk_iops: Rate32,
    pub ctx_switches_ps: Rate32,
    pub interrupts_ps: Rate32,

    pub net_errors_ps: u16,
    pub net_drops_ps: u16,

    pub source: MetricsSource,
    pub flags: u8,
    pub reserved: u16,
}

#[repr(C)]
#[derive(Copy, Clone, Debug, Default)]
pub struct ClockState {
    pub current_millihz: MilliHz,
    pub base_millihz: MilliHz,
    pub min_millihz: MilliHz,
    pub max_millihz: MilliHz,
    pub escalation_permille: u16,
    pub last_cpu_permille: Permille,
    pub last_ram_permille: Permille,
    pub last_gpu_permille: Permille,
    pub last_activity_permille: Permille,
}

impl ClockState {
    pub fn new(base_millihz: u16, min_millihz: u16, max_millihz: u16, escalation_permille: u16) -> Self {
        let clamped_base = base_millihz.max(min_millihz).min(max_millihz);
        Self {
            current_millihz: clamped_base,
            base_millihz: clamped_base,
            min_millihz,
            max_millihz,
            escalation_permille,
            ..Self::default()
        }
    }
}

#[repr(C)]
#[derive(Copy, Clone, Debug, Default)]
pub struct MidiEvent {
    pub note: u8,
    pub velocity: u8,
    pub modulation: u8,
    pub flags: u8,
    pub pitch_bend: i16,
    pub duration_ms: u16,
}

#[repr(C)]
#[derive(Copy, Clone, Debug, Default)]
pub struct RuntimeState {
    pub profile_id: ProfileId,
    pub metrics_source: MetricsSource,
    pub audio_style: AudioStyle,
    pub reserved0: u8,
    pub escalation_permille: u16,
    pub ui_publish_hz: u16,
    pub state_version: u32,
    pub phrase_step: u32,
}

impl RuntimeState {
    pub fn new(
        profile_id: ProfileId,
        metrics_source: MetricsSource,
        audio_style: AudioStyle,
        escalation_permille: u16,
        ui_publish_hz: u16,
    ) -> Self {
        Self {
            profile_id,
            metrics_source,
            audio_style,
            reserved0: 0,
            escalation_permille,
            ui_publish_hz,
            state_version: 0,
            phrase_step: 0,
        }
    }
}

#[repr(C)]
#[derive(Copy, Clone, Debug, Default)]
pub struct DedupeEntry {
    pub digest: u64,
    pub state_version: u32,
    pub escalation_permille: u16,
    pub profile_id: ProfileId,
    pub metrics_source: MetricsSource,
    pub applied_mask: u8,
    pub reserved: [u8; 5],
}

#[derive(Copy, Clone, Debug, Default)]
pub struct TickPlan {
    pub interval_ms: u16,
    pub note_length_ms: u16,
    pub activity_permille: u16,
}

#[derive(Copy, Clone, Debug, Default)]
pub struct UiFrame {
    pub seq: SeqNo,
    pub state_version: u32,
    pub cpu_permille: Permille,
    pub ram_permille: Permille,
    pub gpu_permille: Permille,
    pub sample_millihz: MilliHz,
    pub activity_permille: Permille,
    pub escalation_permille: u16,
    pub note: u8,
    pub velocity: u8,
    pub modulation: u8,
    pub source: MetricsSource,
    pub profile_id: ProfileId,
}

impl UiFrame {
    pub fn from_runtime(
        frame: &TelemetryFrame,
        state: &RuntimeState,
        tick: &TickPlan,
        event: &MidiEvent,
        current_millihz: MilliHz,
    ) -> Self {
        Self {
            seq: frame.seq,
            state_version: state.state_version,
            cpu_permille: frame.cpu_permille,
            ram_permille: frame.ram_permille,
            gpu_permille: frame.gpu_permille,
            sample_millihz: current_millihz,
            activity_permille: tick.activity_permille,
            escalation_permille: state.escalation_permille,
            note: event.note,
            velocity: event.velocity,
            modulation: event.modulation,
            source: state.metrics_source,
            profile_id: state.profile_id,
        }
    }
}
