import unittest
from unittest.mock import MagicMock, patch

import mido

from sonification_pipeline import map_to_midi, resolve_midi_port


class TestMIDICrossPlatform(unittest.TestCase):
    """Hardware-agnostic MIDI tests for hosted runners and local development."""

    def test_map_to_midi_ranges_across_scenarios(self):
        scenarios = [
            (0, 0, 0, False),
            (50, 30, 10, True),
            (100, 100, 100, True),
            (-25, 130, 250, True),
        ]
        for cpu, ram, gpu, use_pitch_bend in scenarios:
            note, velocity, modulation, bend = map_to_midi(
                cpu,
                ram,
                gpu,
                use_pitch_bend=use_pitch_bend,
                activity_score=0.6,
                phrase_step=4,
                iowait_pct=8.0,
                disk_busy_pct=40.0,
            )
            self.assertTrue(0 <= note <= 127)
            self.assertTrue(0 <= velocity <= 127)
            self.assertTrue(0 <= modulation <= 127)
            self.assertTrue(-8192 <= bend <= 8191)

    @patch("sonification_pipeline.mido.get_output_names", return_value=[])
    def test_resolve_midi_port_raises_when_no_ports(self, _mock_names):
        with self.assertRaises(IOError):
            resolve_midi_port()

    @patch("sonification_pipeline.mido.open_output")
    @patch("sonification_pipeline.mido.get_output_names", return_value=["MIDI Through", "FLUID Synth"])
    def test_resolve_midi_port_prefers_fluid(self, _mock_names, mock_open):
        fake_port = MagicMock(spec=mido.ports.BaseOutput)
        mock_open.return_value = fake_port
        resolved = resolve_midi_port()
        self.assertIs(resolved, fake_port)
        mock_open.assert_called_once_with("FLUID Synth")

    @patch("sonification_pipeline.mido.open_output")
    @patch("sonification_pipeline.mido.get_output_names", return_value=["loopMIDI Port", "Other Port"])
    def test_resolve_midi_port_hint_match(self, _mock_names, mock_open):
        fake_port = MagicMock(spec=mido.ports.BaseOutput)
        mock_open.return_value = fake_port
        resolved = resolve_midi_port("loop")
        self.assertIs(resolved, fake_port)
        mock_open.assert_called_once_with("loopMIDI Port")


if __name__ == "__main__":
    unittest.main()
