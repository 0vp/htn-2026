import unittest
from engine.components.proposals import SuffixLookup, accepted_prefix


class SpeculationTests(unittest.TestCase):
    def test_rejection_stops_at_first_mismatch_even_if_later_tokens_match(self):
        self.assertEqual(accepted_prefix([3, 4, 5], [3, 9, 5, 8]), 1)
        self.assertEqual(accepted_prefix([], [8]), 0)
        self.assertEqual(accepted_prefix([3, 4], [3, 4, 8]), 2)

    def test_lookup_and_output_budget(self):
        lookup = SuffixLookup([1, 2, 3, 4, 1, 2])
        self.assertEqual(lookup.propose(5), [3, 4])
        self.assertEqual(lookup.propose(1), [3])
        self.assertEqual(lookup.propose(0), [])

    def test_longer_context_wins_over_recent_shorter_match(self):
        lookup = SuffixLookup([9, 1, 2, 3, 7, 1, 2, 3, 8, 9, 1, 2, 3])
        self.assertEqual(lookup.propose(1), [7])

    def test_consecutive_requests_do_not_share_lookup_state(self):
        first = SuffixLookup([1, 2, 3, 4, 1, 2])
        first.append([3, 4])
        second = SuffixLookup([8, 9, 10])
        self.assertEqual(second.propose(6), [])
        self.assertEqual(second.history, [8, 9, 10])

    def test_newly_committed_tokens_become_proposal_sources(self):
        lookup = SuffixLookup([1, 2])
        lookup.append([7, 8, 1, 2])
        self.assertEqual(lookup.propose(2), [7, 8])

    def test_repeated_rejection_backs_off_and_recovers(self):
        lookup = SuffixLookup([1, 2, 3, 4, 1, 2])
        lookup.feedback(2, 0)
        lookup.feedback(1, 0)
        for _ in range(4):
            self.assertEqual(lookup.propose(6), [])
        self.assertEqual(lookup.propose(6), [3])
        lookup.feedback(1, 1)
        self.assertEqual(lookup.propose(6), [3, 4])

    def test_batch_shared_prefix_is_limited_by_first_rejecting_sequence(self):
        drafts = [[1, 2, 3], [4, 5, 6]]
        predictions = [[1, 2, 3, 7], [4, 9, 6, 8]]
        accepted = min(accepted_prefix(d, p) for d, p in zip(drafts, predictions))
        self.assertEqual(accepted, 1)
        # Each sequence emits its verified prefix plus its own next greedy token.
        self.assertEqual([p[:accepted + 1] for p in predictions], [[1, 2], [4, 9]])
