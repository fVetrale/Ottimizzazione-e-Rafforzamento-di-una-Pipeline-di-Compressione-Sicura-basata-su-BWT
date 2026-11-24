import unittest
import os
import random
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from sbwt import customSort, suffix
from sbwt.sbwt import bwt_bytes, ibwt_bytes


def _reference_ibwt(last_column: bytes, key, primary_index: int) -> bytes:
    """Inversa originale, un passo LF alla volta: oracolo per i test."""
    alphabet = sorted(set(last_column))
    secret_order = customSort.getSecretSort(alphabet, key)
    ordered_alphabet = sorted(alphabet, key=secret_order.__getitem__)
    ranks = [0] * len(last_column)
    counts = {symbol: 0 for symbol in alphabet}
    for position, symbol in enumerate(last_column):
        ranks[position] = counts[symbol]
        counts[symbol] += 1
    starts = {}
    total = 0
    for symbol in ordered_alphabet:
        starts[symbol] = total
        total += counts[symbol]
    result = bytearray(len(last_column))
    row = primary_index
    for position in range(len(last_column) - 1, -1, -1):
        symbol = last_column[row]
        result[position] = symbol
        row = starts[symbol] + ranks[row]
    return bytes(result)


class TestByteBWT(unittest.TestCase):
    def test_round_trip_and_match_dc3(self):
        samples = [
            b"",
            b"a",
            b"banana",
            b"aaaaaa",
            b"abababab",
            bytes([0, 1, 0, 255, 128, 0]),
            bytes(range(256)),
            bytes(range(255, -1, -1)),
        ]

        for data in samples:
            with self.subTest(data=data[:12]):
                transformed, primary_index = bwt_bytes(data, "test-key")
                self.assertEqual(
                    ibwt_bytes(transformed, "test-key", primary_index), data
                )

                if data:
                    doubled = list(data) * 2
                    dc3_suffixes = suffix.buildSuffixArrayDC3(doubled, "test-key")
                    dc3_rotations = [i for i in dc3_suffixes if i < len(data)]
                    expected_primary = dc3_rotations.index(0)
                    expected_transform = bytes(
                        data[(i - 1) % len(data)] for i in dc3_rotations
                    )
                    self.assertEqual(transformed, expected_transform)
                    self.assertEqual(primary_index, expected_primary)

    def test_matches_reference_on_bwt_output(self):
        rng = random.Random(1234)
        samples = [b"ab" * 500, b"abc" * 333, b"\x00" * 1000, bytes([7]) * 2]
        for size in (2, 3, 17, 256, 1000, 4097):
            samples.append(bytes(rng.randrange(256) for _ in range(size)))
            samples.append(bytes(rng.choice(b"acgt") for _ in range(size)))
        for data in samples:
            with self.subTest(size=len(data), head=data[:8]):
                transformed, primary_index = bwt_bytes(data, "test-key")
                result = ibwt_bytes(transformed, "test-key", primary_index)
                self.assertEqual(result, data)
                self.assertEqual(
                    result, _reference_ibwt(transformed, "test-key", primary_index)
                )

    def test_matches_reference_on_arbitrary_input(self):
        # Il decoder riceve anche blocchi non prodotti da bwt_bytes (dati
        # corrotti o manomessi): deve restare deterministico e uguale al
        # vecchio algoritmo, senza eccezioni né output di lunghezza diversa.
        rng = random.Random(99)
        for _ in range(200):
            size = rng.randrange(1, 600)
            block = bytes(rng.randrange(rng.choice((2, 4, 256))) for _ in range(size))
            primary_index = rng.randrange(size)
            key = rng.choice(("test-key", "altra-chiave"))
            with self.subTest(size=size, primary_index=primary_index):
                result = ibwt_bytes(block, key, primary_index)
                self.assertEqual(len(result), size)
                self.assertEqual(result, _reference_ibwt(block, key, primary_index))

    def test_rejects_invalid_primary_index(self):
        for primary_index in (-1, 1):
            with self.subTest(primary_index=primary_index):
                with self.assertRaises(ValueError):
                    ibwt_bytes(b"x", "test-key", primary_index)


if __name__ == "__main__":
    unittest.main()
