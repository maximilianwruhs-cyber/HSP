// Multi-GPU detection for Rust backend
// Supports NVIDIA, AMD ROCm, Intel, and generic detection

use std::process::{Command, Stdio};
use std::str;
use std::path::Path;
use std::fs;
use std::thread;
use std::time::{Duration, Instant};

use crate::state::Permille;

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum GPUVendor {
    Nvidia,
    AMD,
    Intel,
    Generic,
    Unknown,
}

impl Default for GPUVendor {
    fn default() -> Self {
        GPUVendor::Unknown
    }
}

#[derive(Debug, Default)]
pub struct GPUMetrics {
    pub vendor: GPUVendor,
    pub utilization_permille: Permille,  // 0-1000
    pub temperature_deci_c: i16,        // Celsius * 10
    pub power_deci_w: i16,              // Watts * 10
    pub memory_permille: Permille,      // 0-1000
    pub device_count: u8,
}

impl GPUMetrics {
    pub fn is_available(&self) -> bool {
        self.vendor != GPUVendor::Unknown && self.device_count > 0
    }
}

const COMMAND_TIMEOUT: Duration = Duration::from_millis(1500);

fn run_command(cmd: &str, args: &[&str]) -> Option<String> {
    let mut child = Command::new(cmd)
        .args(args)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .ok()?;

    let start = Instant::now();

    loop {
        match child.try_wait() {
            Ok(Some(_)) => {
                let output = child.wait_with_output().ok()?;
                if output.status.success() {
                    return str::from_utf8(&output.stdout).ok().map(|s| s.trim().to_string());
                }
                return None;
            }
            Ok(None) => {
                if start.elapsed() >= COMMAND_TIMEOUT {
                    let _ = child.kill();
                    let _ = child.wait();
                    return None;
                }
                thread::sleep(Duration::from_millis(10));
            }
            Err(_) => {
                let _ = child.kill();
                let _ = child.wait();
                return None;
            }
        }
    }
}

pub fn detect_nvidia_gpu() -> GPUMetrics {
    let mut metrics = GPUMetrics {
        vendor: GPUVendor::Nvidia,
        ..Default::default()
    };

    // Check if nvidia-smi is available
    if run_command("nvidia-smi", &["--version"]).is_none() {
        return metrics;
    }

    // Get GPU count
    if let Some(count_str) = run_command("nvidia-smi", &["--query-gpu=count", "--format=csv,noheader"]) {
        if let Ok(count) = count_str.parse::<u8>() {
            metrics.device_count = count;
        }
    }

    if metrics.device_count == 0 {
        return metrics;
    }

    // Get utilization (average across all GPUs)
    if let Some(util_output) = run_command("nvidia-smi", &["--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"]) {
        let values: Vec<f32> = util_output
            .lines()
            .filter_map(|line| line.trim().parse::<f32>().ok())
            .collect();
        
        if !values.is_empty() {
            let avg_util = values.iter().sum::<f32>() / values.len() as f32;
            metrics.utilization_permille = (avg_util * 10.0) as Permille;  // Convert to permille
        }
    }

    // Get temperature (average)
    if let Some(temp_output) = run_command("nvidia-smi", &["--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"]) {
        let values: Vec<f32> = temp_output
            .lines()
            .filter_map(|line| line.trim().parse::<f32>().ok())
            .collect();
        
        if !values.is_empty() {
            let avg_temp = values.iter().sum::<f32>() / values.len() as f32;
            metrics.temperature_deci_c = (avg_temp * 10.0) as i16;  // Convert to decicelsius
        }
    }

    // Get power usage (average)
    if let Some(power_output) = run_command("nvidia-smi", &["--query-gpu=power.draw", "--format=csv,noheader,nounits"]) {
        let values: Vec<f32> = power_output
            .lines()
            .filter_map(|line| line.trim().parse::<f32>().ok())
            .collect();
        
        if !values.is_empty() {
            let avg_power = values.iter().sum::<f32>() / values.len() as f32;
            metrics.power_deci_w = (avg_power * 10.0) as i16;  // Convert to deciwatts
        }
    }

    // Get memory usage
    if let Some(mem_output) = run_command("nvidia-smi", &["--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"]) {
        let mut total_used = 0u32;
        let mut total_total = 0u32;
        
        for line in mem_output.lines() {
            if let Some((used_str, total_str)) = line.split_once(',') {
                if let (Ok(used), Ok(total)) = (used_str.trim().parse::<u32>(), total_str.trim().parse::<u32>()) {
                    total_used += used;
                    total_total += total;
                }
            }
        }

        if total_total > 0 {
            let mem_percentage = (total_used as f32 / total_total as f32) * 100.0;
            metrics.memory_permille = (mem_percentage * 10.0) as Permille;
        }
    }

    metrics
}

pub fn detect_amd_gpu() -> GPUMetrics {
    let mut metrics = GPUMetrics {
        vendor: GPUVendor::AMD,
        ..Default::default()
    };

    // Check if rocm-smi is available
    if run_command("rocm-smi", &["--version"]).is_none() {
        return metrics;
    }

    // Get GPU metrics
    if let Some(output) = run_command("rocm-smi", &["--showproductname", "--showuse", "--showtemp", "--showpower"]) {
        // Parse rocm-smi output - this is simplified parsing
        // In production, you'd want more robust parsing
        let lines: Vec<&str> = output.lines().collect();
        
        // Count GPU sections (simplified)
        let gpu_sections = lines.split(|line| line.contains("==========")).count().saturating_sub(1);
        metrics.device_count = gpu_sections as u8;
        
        if metrics.device_count == 0 {
            return metrics;
        }

        // Parse metrics (simplified - real parsing would be more complex)
        let mut total_util = 0f32;
        let mut total_temp = 0f32;
        let mut total_power = 0f32;
        let mut gpu_count = 0u32;

        for line in lines {
            // GPU Use: XX%
            if let Some(cap) = line.find("GPU Use:") {
                if let Some(percent_str) = line[cap..].split('%').next() {
                    if let Ok(util) = percent_str.replace("GPU Use:", "").trim().parse::<f32>() {
                        total_util += util;
                        gpu_count += 1;
                    }
                }
            }
            
            // Temperature: XX
            if line.contains("Temperature") {
                if let Some(temp_str) = line.split(':').nth(1) {
                    if let Ok(temp) = temp_str.trim().parse::<f32>() {
                        total_temp += temp;
                    }
                }
            }
            
            // Power: XX
            if line.contains("Power") {
                if let Some(power_str) = line.split(':').nth(1) {
                    if let Ok(power) = power_str.trim().parse::<f32>() {
                        total_power += power;
                    }
                }
            }
        }

        if gpu_count > 0 {
            metrics.utilization_permille = (total_util / gpu_count as f32 * 10.0) as Permille;
            metrics.temperature_deci_c = (total_temp / gpu_count as f32 * 10.0) as i16;
            metrics.power_deci_w = (total_power / gpu_count as f32 * 10.0) as i16;
        }
    }

    metrics
}

pub fn detect_intel_gpu() -> GPUMetrics {
    let mut metrics = GPUMetrics {
        vendor: GPUVendor::Intel,
        ..Default::default()
    };

    // Check if intel_gpu_top is available
    if run_command("intel_gpu_top", &["--version"]).is_none() {
        return metrics;
    }

    // Run intel_gpu_top with JSON output
    if let Some(output) = run_command("intel_gpu_top", &["-J", "-s", "1"]) {
        // Parse JSON output (simplified - would use serde_json in real implementation)
        if output.contains("engines") {
            metrics.device_count = 1;  // intel_gpu_top typically shows one device
            
            // Very simplified parsing - in real code use proper JSON parsing
            if let Some(busy_start) = output.find("\"busy\":") {
                if let Some(busy_end) = output[busy_start..].find(',') {
                    let busy_str = &output[busy_start + 7..busy_start + busy_end];
                    if let Ok(util) = busy_str.trim().parse::<f32>() {
                        metrics.utilization_permille = (util * 10.0) as Permille;
                    }
                }
            }
            
            // Temperature
            if let Some(temp_start) = output.find("\"temperature\":") {
                if let Some(temp_end) = output[temp_start..].find(',') {
                    let temp_str = &output[temp_start + 15..temp_start + temp_end];
                    if let Ok(temp) = temp_str.trim().parse::<f32>() {
                        metrics.temperature_deci_c = (temp * 10.0) as i16;
                    }
                }
            }
            
            // Power
            if let Some(power_start) = output.find("\"power\":") {
                if let Some(power_end) = output[power_start..].find(',') {
                    let power_str = &output[power_start + 8..power_start + power_end];
                    if let Ok(power) = power_str.trim().parse::<f32>() {
                        metrics.power_deci_w = (power * 10.0) as i16;
                    }
                }
            }
        }
    }

    metrics
}

pub fn detect_generic_gpu() -> GPUMetrics {
    let mut metrics = GPUMetrics {
        vendor: GPUVendor::Generic,
        ..Default::default()
    };

    // Look for GPU devices in sysfs
    let sysfs_paths = ["/sys/class/drm", "/sys/class/hwmon"];
    
    for base_path in &sysfs_paths {
        if Path::new(base_path).exists() {
            if let Ok(entries) = fs::read_dir(base_path) {
                for entry in entries.flatten() {
                    let name_path = entry.path().join("name");
                    if name_path.exists() {
                        if let Ok(name) = fs::read_to_string(name_path) {
                            let name_lower = name.to_lowercase();
                            if name_lower.contains("gpu") || 
                               name_lower.contains("amd") || 
                               name_lower.contains("intel") || 
                               name_lower.contains("nvidia") {
                                metrics.device_count += 1;
                                
                                // Try to read temperature
                                if let Ok(temp_entries) = fs::read_dir(entry.path()) {
                                    for temp_entry in temp_entries.flatten() {
                                        let temp_path = temp_entry.path();
                                        if let Some(temp_file) = temp_path.file_name() {
                                            if let Some(temp_str) = temp_file.to_string_lossy().strip_prefix("temp") {
                                                if temp_str.ends_with("input") {
                                                    if let Ok(temp_content) = fs::read_to_string(temp_path) {
                                                        if let Ok(temp_millidegrees) = temp_content.trim().parse::<i32>() {
                                                            let temp_celsius = temp_millidegrees as f32 / 1000.0;
                                                            metrics.temperature_deci_c = (temp_celsius * 10.0) as i16;
                                                            break;
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    metrics
}

pub fn detect_gpus() -> GPUMetrics {
    // Try detectors in order of preference
    let detectors = [
        detect_nvidia_gpu,
        detect_amd_gpu,
        detect_intel_gpu,
        detect_generic_gpu,
    ];

    for detector in detectors {
        let metrics = detector();
        if metrics.is_available() {
            eprintln!("Using {:?} GPU detector - found {} devices", metrics.vendor, metrics.device_count);
            return metrics;
        }
    }

    eprintln!("No GPU detection method succeeded - continuing without GPU metrics");
    GPUMetrics {
        vendor: GPUVendor::Unknown,
        ..Default::default()
    }
}

pub fn get_gpu_utilization_permille() -> Permille {
    detect_gpus().utilization_permille
}