"""CPU orchestration tests only; CUDA graphs and arithmetic require remote tests."""
from contextlib import nullcontext
from io import StringIO
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from engine.components import proposals


class FakeLogits:
    def __init__(self, tokens):
        self.tokens = tokens

    def __getitem__(self, key):
        return self

    def argmax(self, dim):
        return self

    def tolist(self):
        return self.tokens


def load_coordinator():
    fake_torch = SimpleNamespace(
        Tensor=object, cuda=SimpleNamespace(CUDAGraph=object),
        inference_mode=nullcontext, int64=object,
        tensor=lambda rows, **kwargs: rows)
    path = Path(__file__).parents[1] / 'engine/components/graph_verification.py'
    spec = importlib.util.spec_from_file_location('graph_coordinator_test', path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict('sys.modules', {
        spec.name: module, 'torch': fake_torch,
        'transformers': SimpleNamespace(StaticCache=object),
        'components.execution': SimpleNamespace(forward=None),
        'components.proposals': proposals,
    }):
        spec.loader.exec_module(module)
    return module


class CoordinatorTests(unittest.TestCase):
    def test_prefix_acceptance_output_budget_and_consecutive_requests(self):
        module = load_coordinator()

        def model(input_ids, **kwargs):
            return SimpleNamespace(
                logits=FakeLogits([(row[-1] + 1) % 7 for row in input_ids]),
                past_key_values=SimpleNamespace(key_cache=[], value_cache=[]))

        verifier = module.GraphVerifier(model)
        resets = []
        verifier.cache = SimpleNamespace(key_cache=[], value_cache=[],
                                         reset=lambda: resets.append(True))
        verifier.prepare = lambda *args: None
        calls = []

        def evaluate(rows, start):
            calls.append((start, len(rows[0])))
            return [[(token + 1) % 7 for token in row] for row in rows]

        verifier.evaluate = evaluate
        for prompts in ([[0, 1, 2, 3, 4, 5, 6, 0, 1]], [[5, 6], [1, 2]]):
            for count in (0, 1, 2, 11):
                calls.clear()
                with patch('sys.stderr', new_callable=StringIO):
                    result = list(verifier.generate(prompts, count))
                expected = [[(row[-1] + step + 1) % 7 for row in prompts]
                            for step in range(count)]
                self.assertEqual(result, expected)
                if calls:
                    self.assertEqual(calls[0][0], len(prompts[0]))
                self.assertTrue(all(1 <= width <= 4 for _, width in calls))
                self.assertEqual(verifier.last_stats['committed'], max(0, count - 1))
        self.assertEqual(len(resets), 6)

        class WrongDraft(proposals.SuffixLookup):
            def propose(self, limit):
                return [99] * min(3, limit)

        calls.clear()
        with patch.object(module, 'SuffixLookup', WrongDraft), patch('sys.stderr', new_callable=StringIO):
            result = list(verifier.generate([[0, 1], [5, 6]], 9))
        self.assertEqual(result, [[(2 + step) % 7, step % 7] for step in range(9)])
        self.assertEqual([start for start, _ in calls], list(range(2, 10)))
        self.assertEqual(verifier.last_stats['accepted'], 0)
        self.assertEqual(verifier.last_stats['committed'], 8)
        self.assertGreater(verifier.last_stats['drafted'], 0)
