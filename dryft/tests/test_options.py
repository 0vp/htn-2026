import unittest
from engine.options import Options, VARIANTS


class OptionTests(unittest.TestCase):
    def test_invalid_compositions_fail_before_model_loading(self):
        for kwargs in ({'graph': True}, {'static': True}, {'native_prefill': True},
                       {'adaptive_speculation': True}, {'batched_speculation': True},
                       {'norms': 'typo'}, {'norm_warps': 3},
                       {'folded_gqa': True, 'custom_attention': True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                Options(**kwargs)

    def test_independent_custom_attention_and_supported_combinations(self):
        self.assertTrue(Options(custom_attention=True).custom_attention)
        self.assertTrue(Options(norms='all', direct=True, static=True, graph=True,
                                native_prefill=True, folded_gqa=True).graph)
        self.assertTrue(all(isinstance(option, Options) for option in VARIANTS.values()))
