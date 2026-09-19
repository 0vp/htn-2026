import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from scripts import benchmark


class BenchmarkTests(unittest.TestCase):
    def test_results_preserve_failures_and_tps_units(self):
        output = benchmark.summary({'id': 'r1', 'state': 'failed', 'result': {
            'score': 200, 'rankingReason': 'latency_limit',
            'failureMessage': 'TTFT exceeds gate',
        }})
        self.assertIn('200 tok/s', output)
        self.assertIn('latency_limit', output)
        self.assertIn('TTFT exceeds gate', output)

    def test_uncertain_run_request_reuses_saved_key(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder) / 'state.json'
            intent = {'pending_key': 'stable-retry-key', 'submission_id': 's1'}
            benchmark.save(state, intent)
            with patch.object(benchmark, 'STATE', state), \
                 patch.object(benchmark, 'validate', return_value='digest'), \
                 patch.object(benchmark, 'git', side_effect=['', 'main', 'commit']):
                with self.assertRaisesRegex(RuntimeError, 'saved idempotency key'):
                    benchmark.select_run(None)
                self.assertEqual(__import__('json').loads(state.read_text()), intent)

    def test_dirty_checkout_cannot_submit(self):
        with patch.object(benchmark, 'validate', return_value='digest'), \
             patch.object(benchmark, 'git', return_value=' M engine/engine.py'):
            with self.assertRaisesRegex(RuntimeError, 'Commit your changes'):
                benchmark.select_run(None)

    def test_existing_submission_reuses_auto_run_without_push(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(benchmark, 'STATE', Path(folder) / 'state.json'), \
                 patch.object(benchmark, 'validate', return_value='digest'), \
                 patch.object(benchmark, 'git', side_effect=['', 'main', 'commit']), \
                 patch.object(benchmark, 'items', side_effect=[
                     [{'id': 's1', 'commitSha': 'commit'}],
                     [{'id': 'r1', 'submissionId': 's1', 'createdAt': '2026-09-19'}],
                 ]), patch.object(benchmark.subprocess, 'run') as push:
                state = benchmark.select_run(None)
                self.assertEqual(state['run_id'], 'r1')
                push.assert_not_called()

    def test_failed_post_retry_keeps_idempotency_key(self):
        with tempfile.TemporaryDirectory() as folder:
            state_path = Path(folder) / 'state.json'
            benchmark.save(state_path, {'submission_id': 's1', 'run_id': 'old'})
            api = Mock()
            api.run.return_value = {'state': 'succeeded'}
            api.start_run.side_effect = [TimeoutError('connection lost'), {'id': 'new'}]
            api.benchmark.return_value = {}
            with patch.object(benchmark, 'STATE', state_path), \
                 patch.object(benchmark, 'ROOT', Path(folder)), \
                 patch.object(benchmark, 'client', return_value=api), \
                 patch.object(benchmark, 'collect', return_value=True), \
                 patch.object(benchmark.sys, 'argv', ['benchmark.py', 'rerun']):
                with self.assertRaises(TimeoutError):
                    benchmark.main()
                self.assertEqual(benchmark.main(), 0)
            keys = [call.kwargs['idempotency_key'] for call in api.start_run.call_args_list]
            self.assertEqual(len(keys), 2)
            self.assertEqual(keys[0], keys[1])


if __name__ == '__main__':
    unittest.main()
