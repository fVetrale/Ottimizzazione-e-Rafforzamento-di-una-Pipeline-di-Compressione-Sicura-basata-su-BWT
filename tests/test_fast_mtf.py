import unittest
import numpy as np
import sys
import os
import subprocess

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

import bmtf.fast_mtf as fast_mtf
import bmtf.bmtf as bmtf
import bmtf.mtf as mtf


class TestFastMTF(unittest.TestCase):

    def test_empty(self):
        self.assertEqual(fast_mtf.fast_mtf_encode("", "abc"), [])
        self.assertEqual(fast_mtf.fast_mtf_decode([], "abc"), "")
        self.assertEqual(fast_mtf.fast_mtf_encode([], [1, 2, 3]), [])
        self.assertEqual(fast_mtf.fast_mtf_decode([], [1, 2, 3]), [])

    def test_simple_string(self):
        text = "bananaaa"
        dictionary = "abcdefghijklmnopqrstuvwxyz"
        ranks = fast_mtf.fast_mtf_encode(text, dictionary)
        self.assertEqual(ranks, [1, 1, 13, 1, 1, 1, 0, 0])
        decoded = fast_mtf.fast_mtf_decode(ranks, dictionary)
        self.assertEqual(decoded, text)

    def test_bytes_and_integers(self):
        data = [10, 20, 30, 20, 10, 10, 30]
        dictionary = [10, 20, 30, 40]
        ranks = fast_mtf.fast_mtf_encode(data, dictionary)
        decoded = fast_mtf.fast_mtf_decode(ranks, dictionary)
        self.assertEqual(decoded, data)

    def test_roundtrip_large_text(self):
        chars = [chr(65 + i) for i in range(26)]
        np.random.seed(42)
        text = "".join(np.random.choice(chars, size=50000))
        alphabet = sorted(set(text))

        ranks = fast_mtf.fast_mtf_encode(text, alphabet)
        decoded = fast_mtf.fast_mtf_decode(ranks, alphabet)
        self.assertEqual(decoded, text)

    def test_bmtf_secure_roundtrip(self):
        text = "Nel mezzo del cammin di nostra vita mi ritrovai per una selva oscura\003"
        alphabet = sorted(set(text))
        key = "SuperSecretKey123"
        block_size = 16

        enc = bmtf.secure_encode(text, alphabet, key, block_size)
        dec = bmtf.secure_decode(enc, alphabet, key, block_size)
        self.assertEqual(dec, text)


class TestByteDecode(unittest.TestCase):
    """I-MTF che produce direttamente bytes (fast_mtf_decode_bytes, mtf.decode)."""

    def setUp(self):
        saved = (fast_mtf.NUMBA_THRESHOLD, fast_mtf._symbols_seen)
        self.addCleanup(lambda: _restore_numba_state(saved))
        fast_mtf.NUMBA_THRESHOLD = 1 << 40  # percorso Python, salvo dove indicato

    def test_known_result(self):
        # [10,20,30] -> r0: 10 | r1: 20, diz. [20,10,30] | r0: 20 | r2: 30, diz. [30,20,10]
        self.assertEqual(fast_mtf.fast_mtf_decode_bytes([0, 1, 0, 2], [10, 20, 30]),
                         bytes([10, 20, 20, 30]))
        self.assertEqual(fast_mtf.fast_mtf_decode_bytes([0, 1, 2], b"xyz"), b"xyz")

    def test_matches_list_decoder_on_both_paths(self):
        rng = np.random.default_rng(11)
        dictionary = rng.permutation(256).tolist()
        data = rng.integers(0, 256, size=20000).tolist()
        ranks = fast_mtf.fast_mtf_encode(data, dictionary)
        expected = bytes(data)
        self.assertEqual(fast_mtf.fast_mtf_decode_bytes(ranks, dictionary), expected)
        self.assertEqual(bytes(fast_mtf.fast_mtf_decode(ranks, dictionary)), expected)
        fast_mtf.NUMBA_THRESHOLD = 0  # percorso compilato
        self.assertEqual(fast_mtf.fast_mtf_decode_bytes(ranks, dictionary), expected)

    def test_mtf_decode_return_types(self):
        self.assertEqual(mtf.decode([0, 1, 0, 2], [10, 20, 30]), bytes([10, 20, 20, 30]))
        self.assertEqual(mtf.decode([1, 1, 13, 1, 1, 1, 0, 0], "abcdefghijklmnopqrstuvwxyz"),
                         "bananaaa")
        self.assertEqual(mtf.decode([], [1, 2, 3]), b"")
        self.assertEqual(mtf.decode([], "abc"), "")

    def test_rejects_ranks_outside_dictionary(self):
        for threshold in (1 << 40, 0):  # Python e Numba
            fast_mtf.NUMBA_THRESHOLD = threshold
            for ranks in ([-1], [256], [0, 3], [2 ** 40]):
                with self.subTest(threshold=threshold, ranks=ranks):
                    with self.assertRaisesRegex(ValueError, "fuori dal dizionario"):
                        mtf.decode(ranks, [0, 1, 2])

    def test_rejects_malformed_ranks(self):
        # Stessi errori del vecchio decoder: testo non convertibile in interi,
        # oppure ranghi annidati (array a due dimensioni).
        cases = ((["a"], "non validi"), ([[1]], "fuori dal dizionario"))
        for ranks, message in cases:
            with self.subTest(ranks=ranks):
                with self.assertRaisesRegex(ValueError, message):
                    mtf.decode(ranks, list(range(256)))

    def test_float_ranks_behave_as_before(self):
        # Il vecchio decoder li convertiva con numpy (troncamento): resta così.
        self.assertEqual(mtf.decode([1.0, 0.0], [10, 20]), bytes([20, 20]))

    def test_out_of_byte_dictionary_only_fails_when_used(self):
        self.assertEqual(mtf.decode([0, 0], [10, 300, 30]), bytes([10, 10]))
        with self.assertRaisesRegex(ValueError, r"outside \[0, 255\]"):
            mtf.decode([1], [10, 300, 30])

    def test_secure_byte_roundtrip_many_blocks(self):
        rng = np.random.default_rng(3)
        data = bytes(rng.integers(0, 40, size=5000, dtype=np.uint8))
        alphabet = list(range(256))
        enc = bmtf.secure_encode(data, alphabet, "chiave", 700)
        self.assertEqual(bmtf.secure_decode(enc, alphabet, "chiave", 700, output_bytes=True), data)


def _restore_numba_state(saved):
    fast_mtf.NUMBA_THRESHOLD, fast_mtf._symbols_seen = saved


class TestNumbaLoading(unittest.TestCase):

    def setUp(self):
        self.saved = (fast_mtf.NUMBA_THRESHOLD, fast_mtf._symbols_seen)
        self.addCleanup(self.restore)

    def restore(self):
        fast_mtf.NUMBA_THRESHOLD, fast_mtf._symbols_seen = self.saved

    def test_import_does_not_load_numba(self):
        src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
        code = "import sys, pipeline; sys.exit('numba' in sys.modules)"
        done = subprocess.run([sys.executable, "-c", code], cwd=src)
        self.assertEqual(done.returncode, 0)

    def test_python_below_threshold(self):
        fast_mtf.NUMBA_THRESHOLD = 100
        fast_mtf._symbols_seen = 0
        self.assertIsNone(fast_mtf._select_kernels(99))

    def test_compiled_and_python_paths_match(self):
        np.random.seed(7)
        data = np.random.randint(0, 256, size=5000).tolist()
        dictionary = np.random.permutation(256).tolist()

        fast_mtf.NUMBA_THRESHOLD = 1 << 40
        fast_mtf._symbols_seen = 0
        python_ranks = fast_mtf.fast_mtf_encode(data, dictionary)
        python_decoded = fast_mtf.fast_mtf_decode(python_ranks, dictionary)

        fast_mtf.NUMBA_THRESHOLD = 0
        compiled_ranks = fast_mtf.fast_mtf_encode(data, dictionary)
        compiled_decoded = fast_mtf.fast_mtf_decode(compiled_ranks, dictionary)

        self.assertEqual(compiled_ranks, python_ranks)
        self.assertEqual(compiled_decoded, python_decoded)
        self.assertEqual(compiled_decoded, data)


if __name__ == "__main__":
    unittest.main()
