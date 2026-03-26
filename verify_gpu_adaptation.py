#!/usr/bin/env python3
"""
Final verification script for GPU hardware adaptation.
Tests all critical components to ensure the adaptation is complete.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_python_backend():
    """Test Python backend integration."""
    print("🔍 Testing Python backend...")
    
    # Test main pipeline
    from sonification_pipeline import extract_gpu
    util1 = extract_gpu()
    print(f"  ✓ sonification_pipeline.extract_gpu() = {util1}%")
    
    # Test async pipeline
    from sonification_pipeline_async import extract_gpu_stats
    stats = extract_gpu_stats()
    print(f"  ✓ sonification_pipeline_async.extract_gpu_stats() = {stats}")
    
    # Test GPU detector directly
    from gpu_detector import extract_gpu, MultiGPUDetector
    util2 = extract_gpu()
    print(f"  ✓ gpu_detector.extract_gpu() = {util2}%")
    
    # Test detector class
    detector = MultiGPUDetector()
    metrics = detector.detect_gpus()
    print(f"  ✓ MultiGPUDetector found: {metrics.vendor.value} ({metrics.device_count} devices)")
    
    return True

def test_rust_backend():
    """Test Rust backend compilation."""
    print("🔍 Testing Rust backend...")
    
    import subprocess
    result = subprocess.run(
        ["cargo", "check"],
        cwd="./hsp-rs",
        capture_output=True,
        text=True
    )
    
    if result.returncode == 0:
        print("  ✓ Rust backend compiles successfully")
        return True
    else:
        print(f"  ❌ Rust backend compilation failed: {result.stderr}")
        return False

def test_backward_compatibility():
    """Test that old functionality still works."""
    print("🔍 Testing backward compatibility...")
    
    # Test that the old nvidia-smi fallback still works
    import subprocess
    from unittest.mock import patch
    
    # Mock nvidia-smi to return test data
    with patch("subprocess.check_output", return_value="80\n20\n"):
        # Force the fallback by making gpu_detector import fail
        with patch("gpu_detector.extract_gpu", side_effect=Exception("Test fallback")):
            from sonification_pipeline import extract_gpu
            util = extract_gpu()
            expected = 50.0  # (80 + 20) / 2
            if abs(util - expected) < 0.01:
                print(f"  ✓ Fallback to nvidia-smi works: {util}% ≈ {expected}%")
                return True
            else:
                print(f"  ❌ Fallback failed: {util}% != {expected}%")
                return False

def test_all_detectors():
    """Test all individual GPU detectors."""
    print("🔍 Testing all GPU detectors...")
    
    from gpu_detector import MultiGPUDetector
    detector = MultiGPUDetector()
    
    vendors_found = []
    for i, gpu_detector in enumerate(detector.detectors):
        metrics = gpu_detector.detect()
        vendors_found.append(metrics.vendor.value)
        print(f"  ✓ Detector {i+1} ({metrics.vendor.value}): {metrics.device_count} devices")
    
    expected_vendors = ["nvidia", "amd", "intel", "generic"]
    if vendors_found == expected_vendors:
        print(f"  ✓ All expected vendors present: {vendors_found}")
        return True
    else:
        print(f"  ❌ Unexpected vendors: {vendors_found} != {expected_vendors}")
        return False

def test_integration():
    """Test that both backends produce consistent results."""
    print("🔍 Testing integration consistency...")
    
    from sonification_pipeline import extract_gpu
    from gpu_detector import extract_gpu as direct_extract_gpu
    
    util1 = extract_gpu()
    util2 = direct_extract_gpu()
    
    if abs(util1 - util2) < 0.01:
        print(f"  ✓ Both backends consistent: {util1}% == {util2}%")
        return True
    else:
        print(f"  ❌ Inconsistent results: {util1}% != {util2}%")
        return False

def main():
    """Run all verification tests."""
    print("🚀 GPU Hardware Adaptation Verification")
    print("=" * 50)
    
    tests = [
        ("Python Backend", test_python_backend),
        ("Rust Backend", test_rust_backend),
        ("Backward Compatibility", test_backward_compatibility),
        ("All Detectors", test_all_detectors),
        ("Integration", test_integration),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"  ❌ {name} failed with exception: {e}")
            results.append((name, False))
        print()
    
    # Summary
    print("=" * 50)
    print("📊 VERIFICATION SUMMARY")
    print("=" * 50)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status} {name}")
    
    print(f"\n🎯 Overall: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 SUCCESS! GPU hardware adaptation is complete and working correctly.")
        print("\nThe system now supports:")
        print("  • NVIDIA GPUs via nvidia-smi")
        print("  • AMD GPUs via rocm-smi")
        print("  • Intel GPUs via intel_gpu_top")
        print("  • Generic GPUs via sysfs/hwmon")
        print("  • Automatic detection and fallback")
        print("  • Full backward compatibility")
        return 0
    else:
        print(f"\n⚠️  WARNING: {total - passed} test(s) failed.")
        return 1

if __name__ == "__main__":
    sys.exit(main())