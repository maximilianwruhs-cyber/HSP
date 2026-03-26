"""Tests for the audio_driver module (PortAudio integration spec §6 — Unit Tests)."""

import subprocess
import sys
import unittest
from unittest.mock import MagicMock, call, patch


import audio_driver


class TestPeriodSize(unittest.TestCase):
    def test_returns_64(self):
        self.assertEqual(audio_driver.period_size(), 64)


class TestTryPyfluidsynth(unittest.TestCase):
    def _make_fake_fs(self):
        mock_synth = MagicMock()
        mock_module = MagicMock()
        mock_module.Synth.return_value = mock_synth
        return mock_module, mock_synth

    def test_returns_none_when_not_installed(self):
        with patch.dict(sys.modules, {"fluidsynth": None}):
            result = audio_driver._try_pyfluidsynth(None, None)
        self.assertIsNone(result)

    def test_sets_portaudio_driver(self):
        fake_fs, mock_synth = self._make_fake_fs()
        with patch.dict(sys.modules, {"fluidsynth": fake_fs}):
            audio_driver._try_pyfluidsynth(None, None)
        mock_synth.setting.assert_any_call("audio.driver", "portaudio")

    def test_sets_period_size(self):
        fake_fs, mock_synth = self._make_fake_fs()
        with patch.dict(sys.modules, {"fluidsynth": fake_fs}):
            audio_driver._try_pyfluidsynth(None, None)
        mock_synth.setting.assert_any_call("audio.period-size", 64)

    def test_sets_device_when_provided(self):
        fake_fs, mock_synth = self._make_fake_fs()
        device = "0:Windows WASAPI:Speakers"
        with patch.dict(sys.modules, {"fluidsynth": fake_fs}):
            audio_driver._try_pyfluidsynth(None, device)
        mock_synth.setting.assert_any_call("audio.portaudio.device", device)

    def test_does_not_set_device_when_none(self):
        fake_fs, mock_synth = self._make_fake_fs()
        with patch.dict(sys.modules, {"fluidsynth": fake_fs}):
            audio_driver._try_pyfluidsynth(None, None)
        device_calls = [
            c for c in mock_synth.setting.call_args_list
            if "audio.portaudio.device" in str(c)
        ]
        self.assertEqual(device_calls, [])

    def test_starts_portaudio_driver(self):
        fake_fs, mock_synth = self._make_fake_fs()
        with patch.dict(sys.modules, {"fluidsynth": fake_fs}):
            audio_driver._try_pyfluidsynth(None, None)
        mock_synth.start.assert_called_once_with(driver="portaudio")

    def test_returns_synth_instance(self):
        fake_fs, mock_synth = self._make_fake_fs()
        with patch.dict(sys.modules, {"fluidsynth": fake_fs}):
            result = audio_driver._try_pyfluidsynth(None, None)
        self.assertIs(result, mock_synth)

    def test_raises_on_start_failure(self):
        fake_fs, mock_synth = self._make_fake_fs()
        mock_synth.start.side_effect = Exception("no device")
        with patch.dict(sys.modules, {"fluidsynth": fake_fs}):
            with self.assertRaises(RuntimeError) as ctx:
                audio_driver._try_pyfluidsynth(None, None)
        self.assertIn("PortAudio driver", str(ctx.exception))

    def test_loads_soundfont_when_provided(self):
        fake_fs, mock_synth = self._make_fake_fs()
        mock_synth.sfload.return_value = 1
        with patch.dict(sys.modules, {"fluidsynth": fake_fs}):
            audio_driver._try_pyfluidsynth("/path/to/font.sf2", None)
        mock_synth.sfload.assert_called_once_with(
            "/path/to/font.sf2", update_midi_pitch=True
        )

    def test_raises_when_soundfont_load_fails(self):
        fake_fs, mock_synth = self._make_fake_fs()
        mock_synth.sfload.return_value = -1
        with patch.dict(sys.modules, {"fluidsynth": fake_fs}):
            with self.assertRaises(RuntimeError) as ctx:
                audio_driver._try_pyfluidsynth("/bad/font.sf2", None)
        self.assertIn("soundfont", str(ctx.exception))


class TestLaunchFluidsynthProcess(unittest.TestCase):
    def _run_with_popen_mock(self, soundfont=None, device=None, env=None):
        mock_proc = MagicMock(spec=subprocess.Popen)
        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            if env:
                with patch.dict("os.environ", env, clear=False):
                    audio_driver._launch_fluidsynth_process(soundfont, device)
            else:
                audio_driver._launch_fluidsynth_process(soundfont, device)
        return mock_popen.call_args[0][0]  # returns cmd list

    def test_uses_portaudio_driver_by_default(self):
        cmd = self._run_with_popen_mock(env={"AUDIO_DRIVER": ""})
        # default when env var is empty string falls to portaudio
        # (empty string is falsy so os.environ.get returns "" which is used)
        # Re-run with env var removed:
        mock_proc = MagicMock(spec=subprocess.Popen)
        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen, \
             patch.dict("os.environ", {}, clear=True):
            audio_driver._launch_fluidsynth_process(None, None)
        cmd = mock_popen.call_args[0][0]
        self.assertIn("portaudio", cmd)
        idx = cmd.index("-a")
        self.assertEqual(cmd[idx + 1], "portaudio")

    def test_audio_driver_env_override(self):
        cmd = self._run_with_popen_mock(env={"AUDIO_DRIVER": "pulseaudio"})
        idx = cmd.index("-a")
        self.assertEqual(cmd[idx + 1], "pulseaudio")

    def test_passes_correct_default_bufsize(self):
        with patch("subprocess.Popen") as mock_popen, \
             patch.object(audio_driver, "period_size", return_value=64), \
             patch.dict("os.environ", {}, clear=True):
            mock_popen.return_value = MagicMock()
            audio_driver._launch_fluidsynth_process(None, None)
        cmd = mock_popen.call_args[0][0]
        idx = cmd.index("-z")
        self.assertEqual(cmd[idx + 1], "64")

    def test_audio_bufsize_env_override(self):
        cmd = self._run_with_popen_mock(env={"AUDIO_BUFSIZE": "256"})
        idx = cmd.index("-z")
        self.assertEqual(cmd[idx + 1], "256")

    def test_uses_provided_soundfont(self):
        cmd = self._run_with_popen_mock(soundfont="/custom/font.sf2")
        self.assertIn("/custom/font.sf2", cmd)

    def test_uses_default_soundfont_when_none(self):
        cmd = self._run_with_popen_mock(soundfont=None)
        self.assertIn(audio_driver._DEFAULT_SOUNDFONT, cmd)

    def test_passes_server_and_no_interactive_flags(self):
        cmd = self._run_with_popen_mock()
        self.assertIn("-s", cmd)
        self.assertIn("-i", cmd)

    def test_raises_when_binary_not_found(self):
        with patch("subprocess.Popen", side_effect=FileNotFoundError("not found")):
            with self.assertRaises(RuntimeError) as ctx:
                audio_driver._launch_fluidsynth_process(None, None)
        self.assertIn("FluidSynth executable not found", str(ctx.exception))

    def test_raises_on_os_error(self):
        with patch("subprocess.Popen", side_effect=OSError("permission denied")):
            with self.assertRaises(RuntimeError) as ctx:
                audio_driver._launch_fluidsynth_process(None, None)
        self.assertIn("Failed to launch FluidSynth", str(ctx.exception))


class TestInitializeAudioDriver(unittest.TestCase):
    def test_uses_pyfluidsynth_when_available(self):
        expected = MagicMock()
        with patch.object(audio_driver, "_try_pyfluidsynth", return_value=expected) as mock_try, \
             patch.object(audio_driver, "_launch_fluidsynth_process") as mock_cli:
            result = audio_driver.initialize_audio_driver()
        mock_try.assert_called_once_with(None, None)
        mock_cli.assert_not_called()
        self.assertIs(result, expected)

    def test_falls_back_to_cli_when_pyfluidsynth_unavailable(self):
        expected = MagicMock(spec=subprocess.Popen)
        with patch.object(audio_driver, "_try_pyfluidsynth", return_value=None), \
             patch.object(audio_driver, "_launch_fluidsynth_process", return_value=expected) as mock_cli:
            result = audio_driver.initialize_audio_driver(soundfont="/sf.sf2")
        mock_cli.assert_called_once_with("/sf.sf2", None)
        self.assertIs(result, expected)

    def test_passes_soundfont_and_device(self):
        with patch.object(audio_driver, "_try_pyfluidsynth", return_value=None), \
             patch.object(audio_driver, "_launch_fluidsynth_process", return_value=MagicMock()) as mock_cli:
            audio_driver.initialize_audio_driver(
                soundfont="/my.sf2",
                device="0:CoreAudio:Built-in Output",
            )
        mock_cli.assert_called_once_with("/my.sf2", "0:CoreAudio:Built-in Output")


if __name__ == "__main__":
    unittest.main()
