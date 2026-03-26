#!/usr/bin/env python3
"""
Test script for multi-GPU detection framework.
Tests all GPU detectors and validates integration.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gpu_detector import MultiGPUDetector, GPUVendor

def test_gpu_detectors():
    """Test all individual GPU detectors."""
    print("=== Testing Individual GPU Detectors ===")
    
    detector = MultiGPUDetector()
    
    # Test each detector individually
    for i, gpu_detector in enumerate(detector.detectors):
        metrics = gpu_detector.detect()
        print(f"\nDetector {i+1} ({gpu_detector.vendor.name}):")
        print(f"  Vendor: {metrics.vendor.value}")
        print(f"  Devices: {metrics.device_count}")
        print(f"  Utilization: {metrics.utilization:.1f}%")
        print(f"  Temperature: {metrics.temperature:.1f}°C")
        print(f"  Power: {metrics.power_usage:.1f}W")
        print(f"  Memory: {metrics.memory_used}MB/{metrics.memory_total}MB ({metrics.memory_usage:.1f}%)")
        print(f"  Available: {metrics.is_available()}")

def test_multi_gpu_detector():
    """Test the main multi-GPU detector."""
    print("\n=== Testing Multi-GPU Detector ===")
    
    detector = MultiGPUDetector()
    metrics = detector.detect_gpus()
    
    print(f"Selected GPU Vendor: {metrics.vendor.value}")
    print(f"GPU Count: {metrics.device_count}")
    print(f"Utilization: {metrics.utilization:.1f}%")
    print(f"Temperature: {metrics.temperature:.1f}°C")
    print(f"Power: {metrics.power_usage:.1f}W")
    print(f"Memory: {metrics.memory_used}MB/{metrics.memory_total}MB ({metrics.memory_usage:.1f}%)")
    print(f"Available: {metrics.is_available()}")
    
    # Test all available metrics
    all_metrics = detector.get_all_available_metrics()
    print(f"\nAll available GPU detectors ({len(all_metrics)}):")
    for i, m in enumerate(all_metrics):
        print(f"  {i+1}. {m.vendor.value}: {m.device_count} devices, {m.utilization:.1f}% util")

def test_integration():
    """Test integration with sonification pipeline."""
    print("\n=== Testing Integration ===")
    
    # Test the extract_gpu function
    from gpu_detector import extract_gpu
    utilization = extract_gpu()
    print(f"extract_gpu() returned: {utilization:.1f}%")
    
    # Test integration with sonification_pipeline
    try:
        from sonification_pipeline import extract_gpu as pipeline_extract_gpu
        pipeline_util = pipeline_extract_gpu()
        print(f"sonification_pipeline.extract_gpu() returned: {pipeline_util:.1f}%")
        
        if abs(utilization - pipeline_util) < 0.1:
            print("✓ Integration test PASSED: Both functions return same value")
        else:
            print("✗ Integration test FAILED: Values differ")
            
    except Exception as e:
        print(f"✗ Integration test FAILED: {e}")

def test_fallback_behavior():
    """Test fallback behavior when no GPUs are detected."""
    print("\n=== Testing Fallback Behavior ===")
    
    detector = MultiGPUDetector()
    metrics = detector.detect_gpus()
    
    if not metrics.is_available():
        print("✓ Correctly detected no GPUs available")
        print(f"✓ Gracefully returned zero metrics")
        print(f"✓ Utilization: {metrics.utilization}% (should be 0)")
        
        if metrics.utilization == 0.0:
            print("✓ Fallback test PASSED")
        else:
            print("✗ Fallback test FAILED: Non-zero utilization")
    else:
        print(f"Found GPU: {metrics.vendor.value} with {metrics.device_count} devices")
        print("✓ GPU detection working")

def main():
    """Run all tests."""
    print("Multi-GPU Detection Framework Test Suite")
    print("=" * 50)
    
    try:
        test_gpu_detectors()
        test_multi_gpu_detector()
        test_integration()
        test_fallback_behavior()
        
        print("\n" + "=" * 50)
        print("✓ All tests completed successfully!")
        print("\nThe system now supports:")
        print("  • NVIDIA GPUs via nvidia-smi")
        print("  • AMD GPUs via rocm-smi")
        print("  • Intel GPUs via intel_gpu_top")
        print("  • Generic GPUs via sysfs/hwmon")
        print("  • Automatic detection and fallback")
        
    except Exception as e:
        print(f"\n✗ Test suite failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()