import unittest
import numpy as np
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

import bmtf.fast_mtf as fast_mtf
import bmtf.bmtf as bmtf


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


if __name__ == "__main__":
    unittest.main()
