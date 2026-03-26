use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};

use crate::protocol::{
    ControlAck, ControlCommand, ControlError, ControlErrorCode, APPLY_ESCALATION, APPLY_METRICS_SOURCE,
    APPLY_PROFILE,
};
use crate::ring::RingBuffer;
use crate::state::{DedupeEntry, MetricsSource, ProfileId, RuntimeState};

pub const DEDUPE_CAPACITY: usize = 128;

#[derive(Debug, Default)]
pub struct DedupeCache {
    entries: RingBuffer<DedupeEntry, DEDUPE_CAPACITY>,
}

impl DedupeCache {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn find(&self, digest: u64) -> Option<DedupeEntry> {
        let mut found = None;
        for entry in self.entries.iter() {
            if entry.digest == digest && entry.state_version != 0 {
                found = Some(entry);
            }
        }
        found
    }

    pub fn remember(&mut self, entry: DedupeEntry) {
        self.entries.push(entry);
    }
}

pub fn parse_control_frame(buf: &[u8]) -> Result<ControlCommand<'_>, ControlError> {
    let text = std::str::from_utf8(buf).map_err(|_| {
        ControlError::new(ControlErrorCode::InvalidUtf8, "control frame must be valid UTF-8")
    })?;
    let body = text.trim();
    if !(body.starts_with('{') && body.ends_with('}')) {
        return Err(ControlError::new(
            ControlErrorCode::InvalidJsonShape,
            "control frame must be a flat JSON object",
        ));
    }

    let inner = body[1..body.len() - 1].trim();
    let mut command_id = None;
    let mut escalation_permille = None;
    let mut metrics_source = None;
    let mut experience_profile = None;

    if !inner.is_empty() {
        for pair in inner.split(',') {
            let mut parts = pair.splitn(2, ':');
            let key = trim_json_string(parts.next().unwrap_or(""))?;
            let raw_value = parts.next().ok_or_else(|| {
                ControlError::new(ControlErrorCode::InvalidJsonShape, "missing value in control frame")
            })?;

            match key {
                "command_id" => {
                    ensure_absent(command_id.is_some(), key)?;
                    let parsed = trim_json_string(raw_value)?;
                    if parsed.is_empty() {
                        return Err(ControlError::new(
                            ControlErrorCode::MissingCommandId,
                            "command_id must be a non-empty string",
                        ));
                    }
                    command_id = Some(parsed);
                }
                "escalation_regulator" => {
                    ensure_absent(escalation_permille.is_some(), key)?;
                    escalation_permille = Some(parse_escalation(raw_value)?);
                }
                "metrics_source" => {
                    ensure_absent(metrics_source.is_some(), key)?;
                    metrics_source = Some(parse_metrics_source(raw_value)?);
                }
                "experience_profile" => {
                    ensure_absent(experience_profile.is_some(), key)?;
                    experience_profile = Some(parse_profile(raw_value)?);
                }
                other => {
                    return Err(ControlError::new(
                        ControlErrorCode::UnknownField,
                        format!("unknown control field: {other}"),
                    ))
                }
            }
        }
    }

    let command_id = command_id.ok_or_else(|| {
        ControlError::new(ControlErrorCode::MissingCommandId, "command_id is required")
    })?;

    if escalation_permille.is_none() && metrics_source.is_none() && experience_profile.is_none() {
        return Err(ControlError::new(
            ControlErrorCode::NoMutationFields,
            "at least one mutable control field is required",
        ));
    }

    Ok(ControlCommand {
        command_id,
        escalation_permille,
        metrics_source,
        experience_profile,
    })
}

pub fn apply_control_command(
    command: &ControlCommand<'_>,
    state: &mut RuntimeState,
    dedupe: &mut DedupeCache,
) -> ControlAck {
    let digest = hash_command_id(command.command_id);
    if let Some(entry) = dedupe.find(digest) {
        return ControlAck {
            command_id: command.command_id.to_owned(),
            state_version: entry.state_version,
            deduplicated: true,
            applied_mask: entry.applied_mask,
        };
    }

    let mut applied_mask = 0u8;
    if let Some(value) = command.escalation_permille {
        state.escalation_permille = value;
        applied_mask |= APPLY_ESCALATION;
    }
    if let Some(value) = command.metrics_source {
        state.metrics_source = value;
        applied_mask |= APPLY_METRICS_SOURCE;
    }
    if let Some(value) = command.experience_profile {
        state.profile_id = value;
        applied_mask |= APPLY_PROFILE;
    }

    state.state_version = state.state_version.saturating_add(1).max(1);

    dedupe.remember(DedupeEntry {
        digest,
        state_version: state.state_version,
        escalation_permille: state.escalation_permille,
        profile_id: state.profile_id,
        metrics_source: state.metrics_source,
        applied_mask,
        reserved: [0; 5],
    });

    ControlAck {
        command_id: command.command_id.to_owned(),
        state_version: state.state_version,
        deduplicated: false,
        applied_mask,
    }
}

fn hash_command_id(value: &str) -> u64 {
    let mut hasher = DefaultHasher::new();
    value.hash(&mut hasher);
    hasher.finish()
}

fn ensure_absent(already_present: bool, field_name: &str) -> Result<(), ControlError> {
    if already_present {
        Err(ControlError::new(
            ControlErrorCode::DuplicateField,
            format!("duplicate control field: {field_name}"),
        ))
    } else {
        Ok(())
    }
}

fn trim_json_string(raw: &str) -> Result<&str, ControlError> {
    let trimmed = raw.trim();
    if !(trimmed.starts_with('"') && trimmed.ends_with('"') && trimmed.len() >= 2) {
        return Err(ControlError::new(
            ControlErrorCode::InvalidJsonShape,
            "expected JSON string value",
        ));
    }
    Ok(&trimmed[1..trimmed.len() - 1])
}

fn parse_escalation(raw: &str) -> Result<u16, ControlError> {
    let value = raw.trim().trim_matches('"').parse::<f32>().map_err(|_| {
        ControlError::new(
            ControlErrorCode::InvalidEscalation,
            "escalation_regulator must be a finite number",
        )
    })?;
    if !value.is_finite() {
        return Err(ControlError::new(
            ControlErrorCode::InvalidEscalation,
            "escalation_regulator must be finite",
        ));
    }

    let permille = (value * 1_000.0).round() as i32;
    if !(350..=2_500).contains(&permille) {
        return Err(ControlError::new(
            ControlErrorCode::InvalidEscalation,
            "escalation_regulator out of range",
        ));
    }
    Ok(permille as u16)
}

fn parse_metrics_source(raw: &str) -> Result<MetricsSource, ControlError> {
    match trim_json_string(raw)?.trim() {
        "local" => Ok(MetricsSource::Local),
        "external" => Ok(MetricsSource::External),
        _ => Err(ControlError::new(
            ControlErrorCode::InvalidMetricsSource,
            "metrics_source must be local or external",
        )),
    }
}

fn parse_profile(raw: &str) -> Result<ProfileId, ControlError> {
    ProfileId::from_str(trim_json_string(raw)?.trim()).map_err(|_| {
        ControlError::new(
            ControlErrorCode::InvalidExperienceProfile,
            "experience_profile is unknown",
        )
    })
}

#[cfg(test)]
mod tests {
    use super::{apply_control_command, parse_control_frame, DedupeCache};
    use crate::state::{AudioStyle, MetricsSource, ProfileId, RuntimeState};

    #[test]
    fn rejects_unknown_control_fields() {
        let error = parse_control_frame(br#"{"command_id":"c1","unknown":true}"#).unwrap_err();
        assert_eq!(error.code.as_str(), "unknown_field");
    }

    #[test]
    fn parses_and_applies_control_command() {
        let command = parse_control_frame(
            br#"{"command_id":"c2","metrics_source":"external","experience_profile":"chaos-festival-dnb","escalation_regulator":1.7}"#,
        )
        .unwrap();
        let mut state = RuntimeState::new(
            ProfileId::NightPatrolTechno,
            MetricsSource::Local,
            AudioStyle::Droid,
            1_000,
            4,
        );
        let mut dedupe = DedupeCache::new();

        let ack = apply_control_command(&command, &mut state, &mut dedupe);

        assert_eq!(ack.state_version, 1);
        assert!(!ack.deduplicated);
        assert_eq!(state.metrics_source, MetricsSource::External);
        assert_eq!(state.profile_id, ProfileId::ChaosFestivalDnb);
        assert_eq!(state.escalation_permille, 1_700);
    }

    #[test]
    fn deduplicates_replayed_command_ids() {
        let command = parse_control_frame(br#"{"command_id":"c3","escalation_regulator":1.2}"#).unwrap();
        let mut state = RuntimeState::new(
            ProfileId::NightPatrolTechno,
            MetricsSource::Local,
            AudioStyle::Droid,
            1_000,
            4,
        );
        let mut dedupe = DedupeCache::new();

        let first = apply_control_command(&command, &mut state, &mut dedupe);
        let second = apply_control_command(&command, &mut state, &mut dedupe);

        assert!(!first.deduplicated);
        assert!(second.deduplicated);
        assert_eq!(first.state_version, second.state_version);
        assert_eq!(state.state_version, 1);
    }

    #[test]
    fn accepts_htop_profile_and_aliases() {
        let htop = parse_control_frame(br#"{"command_id":"c4","experience_profile":"htop-observer"}"#).unwrap();
        assert_eq!(htop.experience_profile, Some(ProfileId::HtopObserver));

        let alias = parse_control_frame(br#"{"command_id":"c5","experience_profile":"night-patrol"}"#).unwrap();
        assert_eq!(alias.experience_profile, Some(ProfileId::NightPatrolTechno));
    }
}
