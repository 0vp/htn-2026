import unittest
from scripts.analyze import comparison


class ComparisonTests(unittest.TestCase):
    def test_zero_candidate_latency_is_not_mistaken_for_missing_data(self):
        rows = comparison({'result': {'shapes': [{'id': 'case', 'modelMetrics': {
            'ttftMs': 0, 'referenceTtftMs': 20, 'tpotMs': 9, 'referenceTpotMs': 10,
        }}]}})
        self.assertEqual(rows[0]['ttftMsRatio'], 0)
        self.assertEqual(rows[0]['tpotMsRatio'], 0.9)

    def test_missing_native_measurement_does_not_imply_speedup(self):
        rows = comparison({'result': {'shapes': [{'id': 'case', 'modelMetrics': {'ttftMs': 2}}]}})
        self.assertIsNone(rows[0]['ttftMsRatio'])
