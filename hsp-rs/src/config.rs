use std::fmt;
use std::path::PathBuf;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};

use crate::state::{MetricsSource, ProfileId};

pub const DEFAULT_BASE_SAMPLE_MILLIHZ: u16 = 2_400;
pub const DEFAULT_MIN_SAMPLE_MILLIHZ: u16 = 2_400;
pub const DEFAULT_MAX_SAMPLE_MILLIHZ: u16 = 9_500;
pub const DEFAULT_WS_MAX_SIZE_BYTES: usize = 65_536;
pub const DEFAULT_WS_MAX_QUEUE: usize = 8;
pub const DEFAULT_UI_PUBLISH_HZ: u16 = 4;
pub const DEFAULT_ESCALATION_PERMILLE: u16 = 1_000;

#[derive(Clone, Debug)]
pub struct Config {
    pub host: String,
    pub port: u16,
    pub metrics_source: MetricsSource,
    pub experience_profile: ProfileId,
    pub escalation_permille: u16,
    pub ui_publish_hz: u16,
    pub ws_max_size_bytes: usize,
    pub ws_max_queue: usize,
    pub index_html: Option<PathBuf>,
    pub midi_port_hint: Option<String>,
    pub base_sample_millihz: u16,
    pub min_sample_millihz: u16,
    pub max_sample_millihz: u16,
    pub dry_run: bool,
    /// When set, the live loop exits as soon as this flag is raised. Intended
    /// for integration tests only; leave as `None` in production.
    pub stop_flag: Option<Arc<AtomicBool>>,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            host: String::from("0.0.0.0"),
            port: 8_001,
            metrics_source: MetricsSource::Local,
            experience_profile: ProfileId::NightPatrolTechno,
            escalation_permille: DEFAULT_ESCALATION_PERMILLE,
            ui_publish_hz: DEFAULT_UI_PUBLISH_HZ,
            ws_max_size_bytes: DEFAULT_WS_MAX_SIZE_BYTES,
            ws_max_queue: DEFAULT_WS_MAX_QUEUE,
            index_html: None,
            midi_port_hint: None,
            base_sample_millihz: DEFAULT_BASE_SAMPLE_MILLIHZ,
            min_sample_millihz: DEFAULT_MIN_SAMPLE_MILLIHZ,
            max_sample_millihz: DEFAULT_MAX_SAMPLE_MILLIHZ,
            dry_run: true,
            stop_flag: None,
        }
    }
}

impl Config {
    /// Returns true when the stop flag has been raised.
    pub fn should_stop(&self) -> bool {
        self.stop_flag
            .as_ref()
            .map_or(false, |f| f.load(Ordering::Relaxed))
    }
}

#[derive(Debug)]
pub enum ConfigError {
    Help(String),
    MissingValue(&'static str),
    UnknownFlag(String),
    InvalidValue(String),
}

impl fmt::Display for ConfigError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Help(text) => write!(f, "{text}"),
            Self::MissingValue(flag) => write!(f, "missing value for {flag}"),
            Self::UnknownFlag(flag) => write!(f, "unknown flag: {flag}"),
            Self::InvalidValue(msg) => write!(f, "invalid value: {msg}"),
        }
    }
}

impl std::error::Error for ConfigError {}

impl Config {
    pub fn usage() -> String {
        String::from(
            "hsp-rs starter skeleton\n\n\
usage:\n\
  hsp-rs [--host HOST] [--port PORT] [--metrics-source local|external]\n\
         [--experience-profile PROFILE] [--escalation-regulator FLOAT]\n\
         [--ui-publish-hz HZ] [--ws-max-size-bytes BYTES] [--ws-max-queue N]\n\
         [--index-html PATH] [--midi-port-hint TEXT] [--live]\n",
        )
    }

    pub fn from_env_args<I>(args: I) -> Result<Self, ConfigError>
    where
        I: IntoIterator<Item = String>,
    {
        let mut config = Self::default();
        let mut iter = args.into_iter();
        let _program_name = iter.next();

        while let Some(arg) = iter.next() {
            match arg.as_str() {
                "--help" | "-h" => return Err(ConfigError::Help(Self::usage())),
                "--host" => config.host = next_value(&mut iter, "--host")?,
                "--port" => config.port = parse_u16(next_value(&mut iter, "--port")?, "--port")?,
                "--metrics-source" => {
                    config.metrics_source = MetricsSource::from_str(&next_value(&mut iter, "--metrics-source")?)?
                }
                "--experience-profile" => {
                    config.experience_profile =
                        ProfileId::from_str(&next_value(&mut iter, "--experience-profile")?)?
                }
                "--escalation-regulator" => {
                    config.escalation_permille = parse_escalation_permille(
                        &next_value(&mut iter, "--escalation-regulator")?,
                    )?
                }
                "--ui-publish-hz" => {
                    config.ui_publish_hz =
                        parse_u16(next_value(&mut iter, "--ui-publish-hz")?, "--ui-publish-hz")?
                }
                "--ws-max-size-bytes" => {
                    config.ws_max_size_bytes =
                        parse_usize(next_value(&mut iter, "--ws-max-size-bytes")?, "--ws-max-size-bytes")?
                }
                "--ws-max-queue" => {
                    config.ws_max_queue =
                        parse_usize(next_value(&mut iter, "--ws-max-queue")?, "--ws-max-queue")?
                }
                "--index-html" => {
                    config.index_html = Some(PathBuf::from(next_value(&mut iter, "--index-html")?))
                }
                "--midi-port-hint" => {
                    config.midi_port_hint = Some(next_value(&mut iter, "--midi-port-hint")?)
                }
                "--live" => config.dry_run = false,
                "--dry-run" => config.dry_run = true,
                other => return Err(ConfigError::UnknownFlag(other.to_owned())),
            }
        }

        if config.min_sample_millihz > config.max_sample_millihz {
            return Err(ConfigError::InvalidValue(String::from(
                "min sample rate exceeds max sample rate",
            )));
        }

        Ok(config)
    }
}

fn next_value<I>(iter: &mut I, flag: &'static str) -> Result<String, ConfigError>
where
    I: Iterator<Item = String>,
{
    iter.next().ok_or(ConfigError::MissingValue(flag))
}

fn parse_u16(value: String, flag: &'static str) -> Result<u16, ConfigError> {
    value
        .parse::<u16>()
        .map_err(|_| ConfigError::InvalidValue(format!("{flag} expects u16, got {value}")))
}

fn parse_usize(value: String, flag: &'static str) -> Result<usize, ConfigError> {
    value
        .parse::<usize>()
        .map_err(|_| ConfigError::InvalidValue(format!("{flag} expects usize, got {value}")))
}

fn parse_escalation_permille(value: &str) -> Result<u16, ConfigError> {
    let parsed = value
        .parse::<f32>()
        .map_err(|_| ConfigError::InvalidValue(format!("--escalation-regulator expects float, got {value}")))?;
    if !parsed.is_finite() {
        return Err(ConfigError::InvalidValue(String::from(
            "--escalation-regulator must be finite",
        )));
    }
    let permille = (parsed * 1_000.0).round() as i32;
    if !(350..=2_500).contains(&permille) {
        return Err(ConfigError::InvalidValue(format!(
            "--escalation-regulator out of range: {value}"
        )));
    }
    Ok(permille as u16)
}
