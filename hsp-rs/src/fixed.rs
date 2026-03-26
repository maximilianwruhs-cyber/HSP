pub fn clamp_u16(value: u16, min_value: u16, max_value: u16) -> u16 {
    value.max(min_value).min(max_value)
}

pub fn clamp_i16(value: i16, min_value: i16, max_value: i16) -> i16 {
    value.max(min_value).min(max_value)
}

pub fn clamp_u32(value: u32, min_value: u32, max_value: u32) -> u32 {
    value.max(min_value).min(max_value)
}

pub fn lerp_u16(min_value: u16, max_value: u16, ratio_permille: u16) -> u16 {
    let span = max_value.saturating_sub(min_value) as u32;
    let offset = (span * ratio_permille as u32) / 1_000;
    min_value.saturating_add(offset as u16)
}

pub fn average_u16<I>(iter: I) -> u16
where
    I: Iterator<Item = u16>,
{
    let mut sum = 0u32;
    let mut count = 0u32;
    for value in iter {
        sum += value as u32;
        count += 1;
    }
    if count == 0 {
        0
    } else {
        (sum / count) as u16
    }
}
