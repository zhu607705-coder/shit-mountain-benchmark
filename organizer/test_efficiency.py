import unittest
from efficiency import score_efficiency


class EfficiencyTests(unittest.TestCase):
    def metrics(self, **kw):
        return dict(total_ms=2000, ttft_ms=300, output_tokens=100, reasoning_tokens=20, simulated=False, **kw)

    def test_fast_wrong_is_zero(self):
        self.assertEqual(score_efficiency(100, False, self.metrics(), trusted=True)['adjusted_quality'], 0)

    def test_under_budget_does_not_get_a_speed_bonus(self):
        self.assertEqual(score_efficiency(80, True, self.metrics(), trusted=True)['adjusted_quality'], 80)

    def test_overthinking_is_measured_not_inferred(self):
        m = self.metrics(); m.update(reasoning_tokens=50000, output_tokens=52000)
        r = score_efficiency(80, True, m, trusted=True, profile='reasoning_aware')
        self.assertLess(r['adjusted_quality'], 80)
        m['reasoning_tokens'] = None
        self.assertIsNone(score_efficiency(80, True, m, trusted=True, profile='reasoning_aware')['adjusted_quality'])

    def test_unknown_self_report_and_simulation_are_not_official_measurements(self):
        self.assertIsNone(score_efficiency(80, True, self.metrics())['adjusted_quality'])
        m = self.metrics(); m['simulated'] = True
        self.assertIsNone(score_efficiency(80, True, m, trusted=True)['adjusted_quality'])

    def test_penalty_is_capped_and_retry_cost_not_free(self):
        m = self.metrics(); m['logical_total_ms'] = 10**12
        r = score_efficiency(100, True, m, trusted=True)
        self.assertGreaterEqual(r['adjusted_quality'], 70)
        self.assertLess(r['adjusted_quality'], 100)

    def test_pending_quality_and_bad_numeric_metadata(self):
        self.assertIsNone(score_efficiency(None, None, self.metrics(), trusted=True)['adjusted_quality'])
        for bad in (True, float('nan'), -1):
            m = self.metrics(); m['total_ms'] = bad
            with self.subTest(bad=bad), self.assertRaises(ValueError): score_efficiency(80, True, m, trusted=True)

    def test_contradictory_telemetry_and_explicit_unknown_retry_totals(self):
        for updates in ({'ttft_ms':3000}, {'reasoning_tokens':101}):
            metrics=self.metrics(); metrics.update(updates)
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                score_efficiency(80, True, metrics, trusted=True)
        metrics=self.metrics(); metrics['logical_total_ms']=None
        result=score_efficiency(80, True, metrics, trusted=True)
        self.assertIsNone(result['adjusted_quality'])
        self.assertEqual(result['status'],'elapsed_time_unavailable')


if __name__ == '__main__': unittest.main()
