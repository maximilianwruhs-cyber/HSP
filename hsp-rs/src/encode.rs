use std::fmt::Write;

use crate::state::UiFrame;

pub fn encode_ui_snapshot(frame: &UiFrame, out: &mut [u8]) -> usize {
    let mut json = String::with_capacity(256);
    let _ = write!(
        json,
        "{{\"seq\":{},\"state_version\":{},\"cpu_permille\":{},\"ram_permille\":{},\"gpu_permille\":{},\"sample_millihz\":{},\"activity_permille\":{},\"escalation_permille\":{},\"note\":{},\"velocity\":{},\"modulation\":{},\"metrics_source\":\"{}\",\"experience_profile\":\"{}\"}}",
        frame.seq,
        frame.state_version,
        frame.cpu_permille,
        frame.ram_permille,
        frame.gpu_permille,
        frame.sample_millihz,
        frame.activity_permille,
        frame.escalation_permille,
        frame.note,
        frame.velocity,
        frame.modulation,
        frame.source.as_str(),
        frame.profile_id.as_str(),
    );

    let bytes = json.as_bytes();
    let len = bytes.len().min(out.len());
    out[..len].copy_from_slice(&bytes[..len]);
    len
}
