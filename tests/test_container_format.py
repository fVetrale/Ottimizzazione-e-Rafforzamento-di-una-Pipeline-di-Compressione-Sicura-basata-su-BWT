import os
import sys
import unittest
from dataclasses import replace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

import container_format as cf


def sample(**changes):
    """A valid container: 10 bytes in blocks of 4 -> blocks of 4, 4 and 2 bytes."""
    base = cf.Container(
        original_size=10,
        bwt_block_size=4,
        bmtf_block_size=8,
        primary_indices=(3, 0, 1),
        symbol_count=7,
        payload=b"\x12\x34",
        nonce=bytes(range(cf.NONCE_SIZE)),
        huffman_table=b"\x00\x01\x00\x02\x01",
    )
    return replace(base, **changes)


class TestRoundTrip(unittest.TestCase):
    def test_round_trip(self):
        for container in (sample(), sample(tag=b"\xaa" * cf.TAG_SIZE), sample(metadata=b"meta")):
            with self.subTest(container=container):
                self.assertEqual(cf.parse(cf.serialize(container)), container)

    def test_empty_input(self):
        empty = cf.Container(original_size=0, bwt_block_size=4, bmtf_block_size=8,
                             primary_indices=(), symbol_count=0, payload=b"")
        self.assertEqual(cf.parse(cf.serialize(empty)), empty)

    def test_exact_multiple_of_block_size(self):
        container = sample(original_size=8, primary_indices=(3, 3))
        self.assertEqual(cf.parse(cf.serialize(container)), container)

    def test_block_helpers(self):
        self.assertEqual(cf.expected_block_count(0, 4), 0)
        self.assertEqual(cf.expected_block_count(10, 4), 3)
        self.assertEqual(cf.expected_block_count(8, 4), 2)
        self.assertEqual([cf.block_length(10, 4, i) for i in range(3)], [4, 4, 2])


class TestSerializeRejects(unittest.TestCase):
    def test_invalid_containers(self):
        cases = {
            "wrong block count": sample(primary_indices=(0, 0)),
            "primary index outside last (short) block": sample(primary_indices=(0, 0, 2)),
            "primary index outside full block": sample(primary_indices=(4, 0, 0)),
            "zero bwt block size": sample(bwt_block_size=0),
            "zero bmtf block size": sample(bmtf_block_size=0),
            "symbol_count zero": sample(symbol_count=0),
            "symbol_count above original_size": sample(symbol_count=11),
            "missing Huffman table": sample(huffman_table=b""),
            "missing payload": sample(payload=b""),
            "short nonce": sample(nonce=b"\x00" * 8),
            "bad tag size": sample(tag=b"\x00" * 5),
            "negative size": sample(original_size=-1),
            "bool size": sample(bmtf_block_size=True),
            "indices as list": sample(primary_indices=[3, 0, 1]),
            "empty input with data": cf.Container(original_size=0, bwt_block_size=4,
                                                  bmtf_block_size=8, primary_indices=(),
                                                  symbol_count=1, payload=b"x"),
        }
        for name, container in cases.items():
            with self.subTest(name), self.assertRaises(cf.ContainerFormatError):
                cf.serialize(container)

    def test_not_a_container(self):
        with self.assertRaises(TypeError):
            cf.serialize(b"not a container")


class TestParseRejects(unittest.TestCase):
    def setUp(self):
        self.data = cf.serialize(sample())

    def test_rejects_garbage(self):
        for blob in (b"", b"SBWT", b"\x00" * 200, b"PK\x03\x04" + self.data[4:]):
            with self.subTest(blob=blob[:8]), self.assertRaises(cf.ContainerFormatError):
                cf.parse(blob)

    def test_rejects_every_truncation_and_extension(self):
        for size in range(len(self.data)):
            with self.subTest(size=size), self.assertRaises(cf.ContainerFormatError):
                cf.parse(self.data[:size])
        with self.assertRaises(cf.ContainerFormatError):
            cf.parse(self.data + b"\x00")

    def test_rejects_header_tampering(self):
        # Flipping a header byte must be detected, except in the two fields that
        # cannot be cross-checked without an authentication tag (phase 5).
        accepted = []
        for position in range(cf.HEADER_SIZE):
            mutated = bytearray(self.data)
            mutated[position] ^= 0xFF
            try:
                cf.parse(bytes(mutated))
            except cf.ContainerFormatError:
                continue
            accepted.append(position)
        # bmtf_block_size: any positive value is legal (small files still use
        # the 10 KB minimum, so it cannot be bounded by original_size).
        # symbol_count: some values stay within [1, original_size].
        bmtf_offset = 4 + 1 + 1 + 2 + 8 + 4 + 4
        symbol_count_offset = bmtf_offset + 4
        allowed = set(range(bmtf_offset, symbol_count_offset + 8))
        self.assertTrue(set(accepted) <= allowed, accepted)

    def test_rejects_primary_index_tampering(self):
        offset = cf.HEADER_SIZE + cf.NONCE_SIZE
        mutated = bytearray(self.data)
        mutated[offset + 3] = 0xFF  # first primary index becomes 255, block has 4 bytes
        with self.assertRaises(cf.ContainerFormatError):
            cf.parse(bytes(mutated))

    def test_rejects_huge_declared_counts_without_allocating(self):
        mutated = bytearray(self.data)
        block_count_offset = 4 + 1 + 1 + 2 + 8 + 4
        mutated[block_count_offset:block_count_offset + 4] = b"\xff\xff\xff\xff"
        with self.assertRaises(cf.ContainerFormatError):
            cf.parse(bytes(mutated))

    def test_parse_requires_bytes(self):
        with self.assertRaises(TypeError):
            cf.parse("SBWT")


if __name__ == "__main__":
    unittest.main()
