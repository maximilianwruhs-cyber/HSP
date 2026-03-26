use std::fmt;

use crate::state::{MetricsSource, ProfileId};

pub const APPLY_ESCALATION: u8 = 0b001;
pub const APPLY_METRICS_SOURCE: u8 = 0b010;
pub const APPLY_PROFILE: u8 = 0b100;

#[derive(Debug, Clone, Copy)]
pub struct ControlCommand<'a> {
    pub command_id: &'a str,
    pub escalation_permille: Option<u16>,
    pub metrics_source: Option<MetricsSource>,
    pub experience_profile: Option<ProfileId>,
}

#[derive(Debug, Clone)]
pub struct ControlAck {
    pub command_id: String,
    pub state_version: u32,
    pub deduplicated: bool,
    pub applied_mask: u8,
}

impl ControlAck {
    pub fn to_json(&self) -> String {
        format!(
            "{{\"type\":\"control_ack\",\"ok\":true,\"command_id\":\"{}\",\"state_version\":{},\"deduplicated\":{},\"applied_mask\":{}}}",
            self.command_id,
            self.state_version,
            if self.deduplicated { "true" } else { "false" },
            self.applied_mask,
        )
    }
}

#[derive(Debug, Clone, Copy)]
pub enum ControlErrorCode {
    InvalidUtf8,
    InvalidJsonShape,
    MissingCommandId,
    DuplicateField,
    UnknownField,
    InvalidMetricsSource,
    InvalidExperienceProfile,
    InvalidEscalation,
    NoMutationFields,
}

impl ControlErrorCode {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::InvalidUtf8 => "invalid_utf8",
            Self::InvalidJsonShape => "invalid_json_shape",
            Self::MissingCommandId => "missing_command_id",
            Self::DuplicateField => "duplicate_field",
            Self::UnknownField => "unknown_field",
            Self::InvalidMetricsSource => "invalid_metrics_source",
            Self::InvalidExperienceProfile => "invalid_experience_profile",
            Self::InvalidEscalation => "invalid_escalation_regulator",
            Self::NoMutationFields => "no_mutation_fields",
        }
    }
}

#[derive(Debug, Clone)]
pub struct ControlError {
    pub code: ControlErrorCode,
    pub message: String,
}

impl ControlError {
    pub fn new(code: ControlErrorCode, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }

    pub fn to_json(&self) -> String {
        format!(
            "{{\"type\":\"control_error\",\"ok\":false,\"code\":\"{}\",\"message\":\"{}\"}}",
            self.code.as_str(),
            self.message.replace('"', "'")
        )
    }
}

impl fmt::Display for ControlError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.code.as_str(), self.message)
    }
}

impl std::error::Error for ControlError {}