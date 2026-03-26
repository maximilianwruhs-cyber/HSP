import unittest
from unittest.mock import patch

from machine_inputs import MachineInputTracker


class TestMachineInputTracker(unittest.TestCase):
    @patch.object(MachineInputTracker, "_discover_rapl_energy_paths", return_value=[])
    @patch.object(MachineInputTracker, "_read_battery_power_w", return_value=0.0)
    @patch.object(MachineInputTracker, "_read_storage_temp_c", return_value=32.5)
    @patch.object(MachineInputTracker, "_read_rapl_energy_j_total", side_effect=[0.0, 0.0])
    @patch.object(MachineInputTracker, "_read_disk_busy_ms_total", side_effect=[100.0, 250.0])
    @patch.object(MachineInputTracker, "_read_net_drops_total", side_effect=[10.0, 12.0])
    @patch.object(MachineInputTracker, "_read_net_errors_total", side_effect=[20.0, 21.0])
    @patch("machine_inputs.time.monotonic", side_effect=[1.0, 3.0])
    def test_sample_rates_and_disk_busy(
        self,
        _mock_time,
        _mock_errors,
        _mock_drops,
        _mock_busy,
        _mock_energy,
        _mock_temp,
        _mock_battery,
        _mock_paths,
    ):
        tracker = MachineInputTracker()
        sample = tracker.sample()

        self.assertAlmostEqual(sample["net_errors_ps"], 0.5)
        self.assertAlmostEqual(sample["net_drops_ps"], 1.0)
        self.assertAlmostEqual(sample["disk_busy_pct"], 7.5)
        self.assertEqual(sample["storage_temp_c"], 32.5)
        self.assertEqual(sample["power_w"], 0.0)

    @patch.object(MachineInputTracker, "_discover_rapl_energy_paths", return_value=["/fake/rapl"])
    @patch.object(MachineInputTracker, "_read_battery_power_w", return_value=0.0)
    @patch.object(MachineInputTracker, "_read_storage_temp_c", return_value=30.0)
    @patch.object(MachineInputTracker, "_read_rapl_energy_j_total", side_effect=[100.0, 104.0])
    @patch.object(MachineInputTracker, "_read_disk_busy_ms_total", side_effect=[0.0, 0.0])
    @patch.object(MachineInputTracker, "_read_net_drops_total", side_effect=[0.0, 0.0])
    @patch.object(MachineInputTracker, "_read_net_errors_total", side_effect=[0.0, 0.0])
    @patch("machine_inputs.time.monotonic", side_effect=[5.0, 7.0])
    def test_power_w_from_rapl_delta(
        self,
        _mock_time,
        _mock_errors,
        _mock_drops,
        _mock_busy,
        _mock_energy,
        _mock_temp,
        _mock_battery,
        _mock_paths,
    ):
        tracker = MachineInputTracker()
        sample = tracker.sample()

        self.assertAlmostEqual(sample["power_w"], 2.0)
        self.assertAlmostEqual(sample["energy_j_total"], 104.0)


if __name__ == "__main__":
    unittest.main()
