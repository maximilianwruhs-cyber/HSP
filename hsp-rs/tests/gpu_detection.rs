use hsp_rs::gpu::{detect_gpus, GPUMetrics, GPUVendor};

#[test]
fn test_gpu_detection_invariants() {
    // Test that detection returns internally consistent values.
    let metrics = detect_gpus();

    assert!(metrics.utilization_permille <= 1000);
    assert!(metrics.memory_permille <= 1000);

    if metrics.is_available() {
        assert_ne!(metrics.vendor, GPUVendor::Unknown);
        assert!(metrics.device_count > 0);
    } else {
        assert_eq!(metrics.vendor, GPUVendor::Unknown);
        assert_eq!(metrics.device_count, 0);
        assert_eq!(metrics.utilization_permille, 0);
    }
}

#[test]
fn test_gpu_metrics_defaults() {
    let metrics = GPUMetrics::default();
    
    assert_eq!(metrics.vendor, GPUVendor::Unknown);
    assert_eq!(metrics.device_count, 0);
    assert_eq!(metrics.utilization_permille, 0);
    assert_eq!(metrics.temperature_deci_c, 0);
    assert_eq!(metrics.power_deci_w, 0);
    assert_eq!(metrics.memory_permille, 0);
    assert!(!metrics.is_available());
}

#[test]
fn test_gpu_utilization_function() {
    // Test that the utilization function doesn't panic
    let utilization = hsp_rs::gpu::get_gpu_utilization_permille();
    assert!(utilization <= 1000);
}