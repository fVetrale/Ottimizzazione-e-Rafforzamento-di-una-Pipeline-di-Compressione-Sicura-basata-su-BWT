import unittest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from sbwt import suffix
from sbwt.sbwt import bwt_bytes, ibwt_bytes


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

    def test_rejects_invalid_primary_index(self):
        for primary_index in (-1, 1):
            with self.subTest(primary_index=primary_index):
                with self.assertRaises(ValueError):
                    ibwt_bytes(b"x", "test-key", primary_index)


if __name__ == "__main__":
    unittest.main()
