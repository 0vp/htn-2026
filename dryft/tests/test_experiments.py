import unittest
from unittest.mock import Mock, patch
from scripts.experiments import choose_winner, wait_run
from agent.client import ApiError


class ExperimentSelectionTests(unittest.TestCase):
    def state(self, entries):
        return {'control_result': {'score': 200}, 'spec_digest': 'same',
                'experiments': entries}

    def entry(self, score, **overrides):
        return dict({'state': 'succeeded', 'spec_digest': 'same',
                     'result': {'score': score, 'ranked': True}}, **overrides)

    def test_regression_keeps_control(self):
        self.assertEqual(choose_winner(self.state({'slow': self.entry(199)})), 'baseline')

    def test_invalid_or_incomparable_fast_results_cannot_win(self):
        entries = {'failed': self.entry(1000, state='failed'),
                   'changed': self.entry(1000, spec_digest='different'),
                   'unranked': self.entry(1000, result={'score': 1000, 'ranked': False}),
                   'good': self.entry(250)}
        self.assertEqual(choose_winner(self.state(entries)), 'good')

    def test_tie_keeps_control(self):
        self.assertEqual(choose_winner(self.state({'tie': self.entry(200)})), 'baseline')

    def test_transient_status_failure_retries_same_remote_run(self):
        api = Mock()
        api.run.side_effect = [ApiError(500, 'internal_error', 'try later'),
                               {'id': 'existing', 'state': 'succeeded'}]
        with patch('scripts.experiments.time.sleep'), patch('scripts.experiments.save'):
            self.assertEqual(wait_run(api, 'existing')['state'], 'succeeded')
        self.assertEqual([call.args for call in api.run.call_args_list], [('existing',), ('existing',)])
        api.start_run.assert_not_called()

    def test_auth_failure_is_not_retried_forever(self):
        api = Mock()
        api.run.side_effect = ApiError(401, 'unauthorized', 'denied')
        with self.assertRaises(ApiError):
            wait_run(api, 'existing')
        self.assertEqual(api.run.call_count, 1)

    def test_persistent_forbidden_stops_after_bounded_retries(self):
        api = Mock()
        api.run.side_effect = ApiError(403, 'http_error', 'Forbidden')
        with patch('scripts.experiments.time.sleep'), self.assertRaises(ApiError):
            wait_run(api, 'existing')
        self.assertEqual(api.run.call_count, 3)
        api.start_run.assert_not_called()
