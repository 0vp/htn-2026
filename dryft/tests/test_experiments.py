import unittest
from scripts.experiments import choose_winner


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
