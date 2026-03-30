#!/usr/bin/env python3
"""
Multi-GPU hardware detection and monitoring framework.
Supports NVIDIA, AMD ROCm, Intel, and generic GPU monitoring.
"""

import subprocess
import re
import os
import logging
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from enum import Enum


class GPUVendor(Enum):
    """Supported GPU vendors."""
    NVIDIA = "nvidia"
    AMD = "amd"
    INTEL = "intel"
    GENERIC = "generic"
    UNKNOWN = "unknown"


@dataclass
class GPUMetrics:
    """Unified GPU metrics structure."""
    vendor: GPUVendor
    utilization: float = 0.0  # 0-100 percentage
    temperature: float = 0.0  # Celsius
    power_usage: float = 0.0  # Watts
    memory_usage: float = 0.0  # 0-100 percentage
    memory_used: int = 0  # MB
    memory_total: int = 0  # MB
    device_count: int = 0
    
    def is_available(self) -> bool:
        """Check if any GPU metrics are available."""
        return self.vendor != GPUVendor.UNKNOWN and self.device_count > 0


class GPUDetector:
    """Base class for GPU detectors."""
    
    def __init__(self):
        self.vendor = GPUVendor.UNKNOWN
        
    def detect(self) -> GPUMetrics:
        """Detect and return GPU metrics."""
        raise NotImplementedError
        
    def _run_command(self, cmd: List[str], timeout: int = 5) -> Optional[str]:
        """Run command and return output or None on failure."""
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout
            )
            if result.returncode == 0:
                return result.stdout.strip()
            return None
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            return None


class NVIDIADetector(GPUDetector):
    """NVIDIA GPU detection using nvidia-smi."""
    
    def __init__(self):
        super().__init__()
        self.vendor = GPUVendor.NVIDIA
        
    def detect(self) -> GPUMetrics:
        """Detect NVIDIA GPUs using nvidia-smi."""
        metrics = GPUMetrics(vendor=self.vendor)
        
        # Get GPU count (also serves as availability check — some nvidia-smi
        # builds do not support --version, so we use a real query instead).
        gpu_query = self._run_command([
            "nvidia-smi", "--query-gpu=count", "--format=csv,noheader"
        ])
        
        if not gpu_query:
            return metrics

        try:
            metrics.device_count = int(gpu_query.strip())
        except ValueError:
            metrics.device_count = 0
        
        if metrics.device_count == 0:
            return metrics
            
        # Get utilization (average across all GPUs)
        util_output = self._run_command([
            "nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"
        ])
        
        if util_output:
            try:
                values = [float(line) for line in util_output.splitlines() if line.strip()]
                metrics.utilization = sum(values) / len(values) if values else 0.0
            except ValueError:
                pass
                
        # Get temperature (average)
        temp_output = self._run_command([
            "nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"
        ])
        
        if temp_output:
            try:
                values = [float(line) for line in temp_output.splitlines() if line.strip()]
                metrics.temperature = sum(values) / len(values) if values else 0.0
            except ValueError:
                pass
                
        # Get power usage (average)
        power_output = self._run_command([
            "nvidia-smi", "--query-gpu=power.draw", "--format=csv,noheader,nounits"
        ])
        
        if power_output:
            try:
                values = [float(line) for line in power_output.splitlines() if line.strip()]
                metrics.power_usage = sum(values) / len(values) if values else 0.0
            except ValueError:
                pass
                
        # Get memory usage
        mem_output = self._run_command([
            "nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"
        ])
        
        if mem_output:
            try:
                lines = mem_output.splitlines()
                total_used = 0
                total_total = 0
                
                for line in lines:
                    if line.strip():
                        parts = line.split(',')
                        if len(parts) >= 2:
                            total_used += int(parts[0].strip())
                            total_total += int(parts[1].strip())
                
                if total_total > 0:
                    metrics.memory_used = total_used
                    metrics.memory_total = total_total
                    metrics.memory_usage = (total_used / total_total) * 100.0
            except ValueError:
                pass
                
        return metrics


class AMDDetector(GPUDetector):
    """AMD GPU detection using rocm-smi."""
    
    def __init__(self):
        super().__init__()
        self.vendor = GPUVendor.AMD
        
    def detect(self) -> GPUMetrics:
        """Detect AMD GPUs using rocm-smi."""
        metrics = GPUMetrics(vendor=self.vendor)
        
        # Check if rocm-smi is available
        if not self._run_command(["rocm-smi", "--version"]):
            return metrics
            
        # Get GPU count and metrics
        output = self._run_command(["rocm-smi", "--showproductname", "--showuse", "--showtemp", "--showpower"])
        
        if not output:
            return metrics
            
        # Parse rocm-smi output (format varies by version)
        lines = output.split('\n')
        gpu_sections = []
        current_section = []
        
        for line in lines:
            if line.strip() and not line.startswith('='):
                current_section.append(line)
            elif current_section:
                gpu_sections.append(current_section)
                current_section = []
        
        if current_section:
            gpu_sections.append(current_section)
            
        metrics.device_count = len(gpu_sections)
        
        if metrics.device_count == 0:
            return metrics
            
        # Parse metrics from each GPU section
        total_util = 0.0
        total_temp = 0.0
        total_power = 0.0
        
        for section in gpu_sections:
            section_text = '\n'.join(section)
            
            # Extract utilization
            util_match = re.search(r'GPU Use\s+:\s+(\d+)%', section_text)
            if util_match:
                total_util += float(util_match.group(1))
                
            # Extract temperature
            temp_match = re.search(r'Temperature.*:\s+(\d+)', section_text)
            if temp_match:
                total_temp += float(temp_match.group(1))
                
            # Extract power
            power_match = re.search(r'Average Graphics Package Power\s+:\s+(\d+)', section_text)
            if not power_match:
                power_match = re.search(r'Power\s+:\s+(\d+)', section_text)
            if power_match:
                total_power += float(power_match.group(1))
                
        if metrics.device_count > 0:
            metrics.utilization = total_util / metrics.device_count
            metrics.temperature = total_temp / metrics.device_count
            metrics.power_usage = total_power / metrics.device_count
            
        return metrics


class IntelDetector(GPUDetector):
    """Intel GPU detection using intel_gpu_top."""
    
    def __init__(self):
        super().__init__()
        self.vendor = GPUVendor.INTEL
        
    def detect(self) -> GPUMetrics:
        """Detect Intel GPUs using intel_gpu_top."""
        metrics = GPUMetrics(vendor=self.vendor)
        
        # Check if intel_gpu_top is available
        if not self._run_command(["intel_gpu_top", "--version"]):
            return metrics
            
        # Run intel_gpu_top and parse output
        output = self._run_command(["intel_gpu_top", "-J", "-s", "1"])
        
        if not output:
            return metrics
            
        try:
            import json
            data = json.loads(output)
            
            # Intel GPU top provides per-engine utilization
            # We'll use the overall GPU utilization
            if 'engines' in data:
                metrics.device_count = 1  # intel_gpu_top typically shows one device
                
                # Calculate overall utilization (average of all engines)
                total_util = 0.0
                engine_count = 0
                
                for engine_name, engine_data in data['engines'].items():
                    if isinstance(engine_data, dict) and 'busy' in engine_data:
                        total_util += engine_data['busy']
                        engine_count += 1
                        
                if engine_count > 0:
                    metrics.utilization = total_util / engine_count
                    
                # Get temperature if available
                if 'temperature' in data:
                    metrics.temperature = data['temperature']
                    
                # Get power if available
                if 'power' in data:
                    metrics.power_usage = data['power']
                    
        except (json.JSONDecodeError, KeyError, ImportError):
            pass
            
        return metrics


class GenericDetector(GPUDetector):
    """Generic GPU detection using sysfs and hwmon."""
    
    def __init__(self):
        super().__init__()
        self.vendor = GPUVendor.GENERIC
        
    def detect(self) -> GPUMetrics:
        """Detect GPUs using generic Linux sysfs/hwmon interfaces."""
        metrics = GPUMetrics(vendor=self.vendor)
        
        # Look for GPU devices in sysfs
        gpu_devices = []
        
        # Common GPU sysfs paths
        possible_paths = [
            '/sys/class/drm',
            '/sys/class/hwmon'
        ]
        
        for base_path in possible_paths:
            if os.path.exists(base_path):
                try:
                    for item in os.listdir(base_path):
                        item_path = os.path.join(base_path, item)
                        
                        # Check if this looks like a GPU device
                        name_path = os.path.join(item_path, 'name')
                        if os.path.exists(name_path):
                            with open(name_path, 'r') as f:
                                name = f.read().strip().lower()
                                if 'gpu' in name or 'amd' in name or 'intel' in name or 'nvidia' in name:
                                    gpu_devices.append(item_path)
                except (OSError, IOError):
                    continue
                    
        metrics.device_count = len(gpu_devices)
        
        if metrics.device_count == 0:
            return metrics
            
        # Try to get temperature from hwmon
        temp_total = 0.0
        temp_count = 0
        
        for device_path in gpu_devices:
            # Look for temperature files
            for root, dirs, files in os.walk(device_path):
                for file in files:
                    if file.startswith('temp') and file.endswith('input'):
                        temp_file = os.path.join(root, file)
                        try:
                            with open(temp_file, 'r') as f:
                                temp_millidegrees = float(f.read().strip())
                                temp_celsius = temp_millidegrees / 1000.0
                                temp_total += temp_celsius
                                temp_count += 1
                        except (ValueError, IOError):
                            continue
                        
        if temp_count > 0:
            metrics.temperature = temp_total / temp_count
            
        # Generic detection has limited capabilities
        # Utilization and power are typically not available through generic interfaces
        return metrics


class MultiGPUDetector:
    """Main GPU detection class that tries all available detectors."""
    
    def __init__(self):
        self.detectors = [
            NVIDIADetector(),
            AMDDetector(),
            IntelDetector(),
            GenericDetector()
        ]
        self._warned = False
        self._active_detector: Optional[GPUDetector] = None
        self._no_gpu = False
        
    def detect_gpus(self) -> GPUMetrics:
        """Detect GPUs using all available methods, returning the first successful result.
        
        Caches the working detector after the first call. If no GPU was found initially,
        subsequent calls return an empty GPUMetrics without re-probing.
        """
        if self._no_gpu:
            return GPUMetrics(vendor=GPUVendor.UNKNOWN)

        if self._active_detector is not None:
            return self._active_detector.detect()

        # Try detectors in order of preference
        for detector in self.detectors:
            metrics = detector.detect()
            if metrics.is_available():
                logging.info(f"Using {metrics.vendor.value} GPU detector - found {metrics.device_count} devices")
                self._active_detector = detector
                return metrics
                
        # No GPUs found — warn once
        if not self._warned:
            logging.warning("No GPU detection method succeeded - continuing without GPU metrics")
            self._warned = True
        self._no_gpu = True
        return GPUMetrics(vendor=GPUVendor.UNKNOWN)
        
    def get_all_available_metrics(self) -> List[GPUMetrics]:
        """Get metrics from all available GPU detectors."""
        results = []
        for detector in self.detectors:
            metrics = detector.detect()
            if metrics.is_available():
                results.append(metrics)
        return results


# Module-level singleton so GPU detection is only run once.
_gpu_detector: Optional[MultiGPUDetector] = None


def extract_gpu() -> float:
    """
    Extract GPU utilization using the multi-GPU detector.
    Returns average utilization across all GPUs (0-100).
    First call runs detection; subsequent calls reuse the cached result.
    """
    global _gpu_detector
    if _gpu_detector is None:
        _gpu_detector = MultiGPUDetector()
    return _gpu_detector.detect_gpus().utilization


if __name__ == "__main__":
    # Test the detector
    detector = MultiGPUDetector()
    metrics = detector.detect_gpus()
    
    print(f"GPU Vendor: {metrics.vendor.value}")
    print(f"GPU Count: {metrics.device_count}")
    print(f"Utilization: {metrics.utilization:.1f}%")
    print(f"Temperature: {metrics.temperature:.1f}°C")
    print(f"Power: {metrics.power_usage:.1f}W")
    print(f"Memory: {metrics.memory_used}MB/{metrics.memory_total}MB ({metrics.memory_usage:.1f}%)")