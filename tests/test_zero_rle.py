import unittest
import numpy as np
import sys
import os

# Aggiungi 'src' al path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from rle.zero_rle import zero_rle_encode, zero_rle_decode, RUNA, RUNB


class TestZeroRLE(unittest.TestCase):

    def test_empty(self):
        self.assertEqual(zero_rle_encode([]), [])
        self.assertEqual(zero_rle_decode([]), [])

    def test_single_runs(self):
        # 1 zero -> RUNA
        self.assertEqual(zero_rle_encode([0]), [RUNA])
        self.assertEqual(zero_rle_decode([RUNA]), [0])

        # 2 zeri -> RUNB
        self.assertEqual(zero_rle_encode([0, 0]), [RUNB])
        self.assertEqual(zero_rle_decode([RUNB]), [0, 0])

        # 3 zeri -> RUNA, RUNA (1 + 2 = 3)
        self.assertEqual(zero_rle_encode([0, 0, 0]), [RUNA, RUNA])
        self.assertEqual(zero_rle_decode([RUNA, RUNA]), [0, 0, 0])

        # 4 zeri -> RUNB, RUNA (2 + 2 = 4)
        self.assertEqual(zero_rle_encode([0, 0, 0, 0]), [RUNB, RUNA])
        self.assertEqual(zero_rle_decode([RUNB, RUNA]), [0, 0, 0, 0])

        # 5 zeri -> RUNA, RUNB (1 + 4 = 5)
        self.assertEqual(zero_rle_encode([0, 0, 0, 0, 0]), [RUNA, RUNB])
        self.assertEqual(zero_rle_decode([RUNA, RUNB]), [0, 0, 0, 0, 0])

        # 6 zeri -> RUNB, RUNB (2 + 4 = 6)
        self.assertEqual(zero_rle_encode([0] * 6), [RUNB, RUNB])
        self.assertEqual(zero_rle_decode([RUNB, RUNB]), [0] * 6)

        # 7 zeri -> RUNA, RUNA, RUNA (1 + 2 + 4 = 7)
        self.assertEqual(zero_rle_encode([0] * 7), [RUNA, RUNA, RUNA])
        self.assertEqual(zero_rle_decode([RUNA, RUNA, RUNA]), [0] * 7)

    def test_all_run_lengths_up_to_1000(self):
        for length in range(1, 1001):
            original = [0] * length
            encoded = zero_rle_encode(original)
            decoded = zero_rle_decode(encoded)
            self.assertEqual(decoded, original, f"Fallito per lunghezza run {length}")

    def test_non_zeros_only(self):
        data = [1, 2, 5, 10, 255]
        expected_encoded = [2, 3, 6, 11, 256]
        self.assertEqual(zero_rle_encode(data), expected_encoded)
        self.assertEqual(zero_rle_decode(expected_encoded), data)

    def test_mixed_sequences(self):
        # Esempio tipico da MTF
        data = [0, 0, 0, 1, 0, 0, 4, 0, 0, 0, 0, 0, 2, 0]
        # [0, 0, 0] -> RUNA, RUNA
        # 1 -> 2
        # [0, 0] -> RUNB
        # 4 -> 5
        # [0, 0, 0, 0, 0] -> RUNA, RUNB
        # 2 -> 3
        # [0] -> RUNA
        expected = [RUNA, RUNA, 2, RUNB, 5, RUNA, RUNB, 3, RUNA]
        encoded = zero_rle_encode(data)
        self.assertEqual(encoded, expected)
        decoded = zero_rle_decode(encoded)
        self.assertEqual(decoded, data)

    def test_numpy_array_input(self):
        arr = np.array([0, 0, 3, 0, 1, 0, 0, 0], dtype=np.int32)
        encoded = zero_rle_encode(arr)
        decoded = zero_rle_decode(encoded)
        self.assertEqual(decoded, list(arr))

    def test_large_random_stream(self):
        # Simulazione di uno stream MTF: 75% zeri, il resto interi positivi
        np.random.seed(42)
        raw = np.random.choice([0, 1, 2, 3, 4, 15, 50], size=100000, p=[0.75, 0.10, 0.05, 0.04, 0.03, 0.02, 0.01])
        encoded = zero_rle_encode(raw)
        decoded = zero_rle_decode(encoded)
        self.assertEqual(decoded, list(raw))
        # Verifica compressione: lo stream codificato deve essere sensibilmente più corto
        self.assertLess(len(encoded), len(raw) * 0.6)


if __name__ == "__main__":
    unittest.main()
