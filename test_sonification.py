import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sonification_pipeline import Smoother, extract_gpu, map_to_midi, run_self_check


class TestSonification(unittest.TestCase):
    def test_smoother(self):
        smoother = Smoother(3)
        self.assertEqual(smoother.smooth("cpu", 10), 10)
        self.assertEqual(smoother.smooth("cpu", 20), 15)
        self.assertEqual(smoother.smooth("cpu", 30), 20)
        self.assertEqual(smoother.smooth("cpu", 40), 30)

    def test_smoother_unknown_metric_raises(self):
        smoother = Smoother(3)
        with self.assertRaises(ValueError):
            smoother.smooth("disk", 10)

    def test_map_to_midi_ranges(self):
        note, velocity, modulation, bend = map_to_midi(100, 100, 100, use_pitch_bend=True)
        self.assertTrue(0 <= note <= 127)
        self.assertTrue(0 <= velocity <= 127)
        self.assertTrue(0 <= modulation <= 127)
        self.assertTrue(-8192 <= bend <= 8191)

    def test_map_to_midi_clamps_out_of_range_inputs(self):
        note, velocity, modulation, bend = map_to_midi(-50, 200, -10, use_pitch_bend=True)
        self.assertEqual(note, 60)
        self.assertEqual(velocity, 127)
        self.assertEqual(modulation, 0)
        self.assertEqual(bend, 0)

    @patch("subprocess.check_output", return_value="80\n20\n")
    @patch("gpu_detector.extract_gpu", side_effect=Exception("Import failed"))
    def test_extract_gpu_averages_multi_gpu(self, _mock_gpu, _mock_out):
        self.assertEqual(extract_gpu(), 50.0)

    @patch("subprocess.check_output", side_effect=Exception("nvidia-smi missing"))
    @patch("gpu_detector.extract_gpu", side_effect=Exception("Import failed"))
    def test_extract_gpu_fallback(self, _mock_gpu, _mock_out):
        self.assertEqual(extract_gpu(), 0.0)

    @patch("sonification_pipeline.extract_cpu_ram", return_value=(12.0, 34.0))
    @patch("sonification_pipeline.subprocess.check_output", return_value="10\n20\n")
    @patch("sonification_pipeline.mido.open_output", return_value=SimpleNamespace(close=lambda: None))
    @patch("sonification_pipeline.mido.get_output_names", return_value=["FLUID Synth"])
    def test_run_self_check_success(
        self,
        _mock_names,
        _mock_open,
        _mock_gpu,
        _mock_cpu_ram,
    ):
        self.assertTrue(run_self_check("FLUID"))

    @patch("sonification_pipeline.extract_cpu_ram", return_value=(12.0, 34.0))
    @patch("sonification_pipeline.subprocess.check_output", side_effect=Exception("nvidia-smi missing"))
    @patch("sonification_pipeline.mido.get_output_names", return_value=[])
    def test_run_self_check_failure(self, _mock_names, _mock_gpu, _mock_cpu_ram):
        self.assertFalse(run_self_check())


if __name__ == "__main__":
    unittest.main()
