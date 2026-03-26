import unittest

from sonification_pipeline_async import NaturalSamplingClock


class TestNaturalSamplingClock(unittest.TestCase):
    def test_interval_within_bounds(self):
        clock = NaturalSamplingClock(base_hz=2.0, min_hz=1.2, max_hz=5.0)
        interval, score = clock.update(
            metrics={"cpu": 10.0, "ram": 20.0, "gpu": 0.0},
            rates={"net_pps": 0.0, "disk_iops": 0.0, "ctx_switches_ps": 0.0, "interrupts_ps": 0.0},
            extra={"net_errors_ps": 0.0, "net_drops_ps": 0.0, "disk_busy_pct": 0.0, "power_w": 0.0},
        )
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)
        self.assertGreaterEqual(clock.current_hz, 1.2)
        self.assertLessEqual(clock.current_hz, 5.0)
        self.assertGreater(interval, 0.0)

    def test_higher_activity_increases_rate(self):
        clock = NaturalSamplingClock(base_hz=2.0, min_hz=1.2, max_hz=5.0)

        low_interval, _ = clock.update(
            metrics={"cpu": 10.0, "ram": 20.0, "gpu": 0.0},
            rates={"net_pps": 0.0, "disk_iops": 0.0, "ctx_switches_ps": 0.0, "interrupts_ps": 0.0},
            extra={"net_errors_ps": 0.0, "net_drops_ps": 0.0, "disk_busy_pct": 0.0, "power_w": 0.0},
        )

        high_interval, high_score = clock.update(
            metrics={"cpu": 95.0, "ram": 90.0, "gpu": 85.0},
            rates={"net_pps": 60000.0, "disk_iops": 7000.0, "ctx_switches_ps": 250000.0, "interrupts_ps": 90000.0},
            extra={"net_errors_ps": 12.0, "net_drops_ps": 10.0, "disk_busy_pct": 95.0, "power_w": 180.0},
        )

        self.assertGreater(high_score, 0.0)
        self.assertLess(high_interval, low_interval)

    def test_sustained_high_load_keeps_higher_rate(self):
        clock = NaturalSamplingClock(base_hz=2.0, min_hz=1.2, max_hz=5.0)

        low_interval, _ = clock.update(
            metrics={"cpu": 10.0, "ram": 20.0, "gpu": 0.0},
            rates={"net_pps": 0.0, "disk_iops": 0.0, "ctx_switches_ps": 0.0, "interrupts_ps": 0.0},
            extra={"net_errors_ps": 0.0, "net_drops_ps": 0.0, "disk_busy_pct": 0.0, "power_w": 0.0},
        )

        # Warm up with one transition into high-load state.
        clock.update(
            metrics={"cpu": 95.0, "ram": 90.0, "gpu": 85.0},
            rates={"net_pps": 0.0, "disk_iops": 0.0, "ctx_switches_ps": 0.0, "interrupts_ps": 0.0},
            extra={"net_errors_ps": 0.0, "net_drops_ps": 0.0, "disk_busy_pct": 0.0, "power_w": 0.0},
        )

        sustained_high_interval, sustained_high_score = clock.update(
            metrics={"cpu": 95.0, "ram": 90.0, "gpu": 85.0},
            rates={"net_pps": 0.0, "disk_iops": 0.0, "ctx_switches_ps": 0.0, "interrupts_ps": 0.0},
            extra={"net_errors_ps": 0.0, "net_drops_ps": 0.0, "disk_busy_pct": 0.0, "power_w": 0.0},
        )

        self.assertGreater(sustained_high_score, 0.0)
        self.assertLess(sustained_high_interval, low_interval)

    def test_escalation_regulator_increases_rate(self):
        low_reg_clock = NaturalSamplingClock(base_hz=2.0, min_hz=1.2, max_hz=5.0, escalation_regulator=0.6)
        high_reg_clock = NaturalSamplingClock(base_hz=2.0, min_hz=1.2, max_hz=5.0, escalation_regulator=2.0)

        metrics = {"cpu": 92.0, "ram": 88.0, "gpu": 84.0}
        rates = {"net_pps": 0.0, "disk_iops": 0.0, "ctx_switches_ps": 0.0, "interrupts_ps": 0.0}
        extra = {"net_errors_ps": 0.0, "net_drops_ps": 0.0, "disk_busy_pct": 0.0, "power_w": 0.0}

        # Warm both clocks once so they are in comparable high-load state.
        low_reg_clock.update(metrics=metrics, rates=rates, extra=extra)
        high_reg_clock.update(metrics=metrics, rates=rates, extra=extra)

        low_interval, _ = low_reg_clock.update(metrics=metrics, rates=rates, extra=extra)
        high_interval, _ = high_reg_clock.update(metrics=metrics, rates=rates, extra=extra)

        self.assertLess(high_interval, low_interval)


if __name__ == "__main__":
    unittest.main()
