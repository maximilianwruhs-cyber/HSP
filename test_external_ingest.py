import unittest
from unittest.mock import patch

from sonification_pipeline_async import ExternalTelemetryState


class TestExternalTelemetryState(unittest.TestCase):
    def test_ingest_direct_metric_map(self):
        state = ExternalTelemetryState()

        accepted = state.ingest_payload({"cpu": "42.5", "ram": 73, "gpu": 11.0})

        self.assertTrue(accepted)
        snapshot = state.snapshot(max_age_seconds=5.0)
        self.assertIsNotNone(snapshot)
        self.assertAlmostEqual(snapshot["cpu"], 42.5)
        self.assertAlmostEqual(snapshot["ram"], 73.0)
        self.assertAlmostEqual(snapshot["gpu"], 11.0)

    def test_ingest_telegraf_cpu_metric(self):
        state = ExternalTelemetryState()

        accepted = state.ingest_payload(
            {
                "name": "cpu",
                "tags": {"cpu": "cpu-total"},
                "fields": {"usage_idle": 90.0, "usage_iowait": 1.5},
            }
        )

        self.assertTrue(accepted)
        snapshot = state.snapshot(max_age_seconds=5.0)
        self.assertIsNotNone(snapshot)
        self.assertAlmostEqual(snapshot["cpu"], 10.0)
        self.assertAlmostEqual(snapshot["iowait_pct"], 1.5)

    @patch("sonification_pipeline_async.psutil.cpu_count", return_value=8)
    def test_ingest_telegraf_system_load(self, _mock_cpu_count):
        state = ExternalTelemetryState()

        accepted = state.ingest_payload(
            {
                "name": "system",
                "fields": {"load1": 4.0},
                "tags": {},
            }
        )

        self.assertTrue(accepted)
        snapshot = state.snapshot(max_age_seconds=5.0)
        self.assertIsNotNone(snapshot)
        self.assertAlmostEqual(snapshot["load1_pct"], 50.0)

    def test_ingest_list_payload_merges_metrics(self):
        state = ExternalTelemetryState()

        accepted = state.ingest_payload(
            [
                {"name": "mem", "fields": {"used_percent": 63.0}, "tags": {}},
                {"name": "swap", "fields": {"used_percent": 12.0}, "tags": {}},
            ]
        )

        self.assertTrue(accepted)
        snapshot = state.snapshot(max_age_seconds=5.0)
        self.assertIsNotNone(snapshot)
        self.assertAlmostEqual(snapshot["ram"], 63.0)
        self.assertAlmostEqual(snapshot["swap_pct"], 12.0)

    @patch("sonification_pipeline_async.time.monotonic", side_effect=[10.0, 16.5])
    def test_snapshot_expires_after_max_age(self, _mock_monotonic):
        state = ExternalTelemetryState()

        accepted = state.ingest_payload({"cpu": 22.0})
        self.assertTrue(accepted)

        snapshot = state.snapshot(max_age_seconds=5.0)
        self.assertIsNone(snapshot)


if __name__ == "__main__":
    unittest.main()
