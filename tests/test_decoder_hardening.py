"""Decoder hardening (phase 3, point 3).

A compressed file comes from outside and may be truncated or manipulated.
These tests check that every decoding stage rejects invalid input with a
clear error, before allocating memory or reading outside an array, and that
the pipeline reports any such problem as ContainerFormatError.
"""

import os
import random
import struct
import sys
import time
import unittest
from dataclasses import replace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

import container_format as cf
import pipeline
from bmtf import fast_mtf
from pc.symbol_huffman import (
    MAX_CODE_LENGTH,
    deserialize_code_lengths,
    huffman_decode_symbols,
    huffman_encode_symbols,
    serialize_code_lengths,
    validate_code_lengths,
)
from rle.zero_rle import RUNA, RUNB, zero_rle_decode, zero_rle_encode

KEY = "chiave-test"
NONCE = bytes(range(cf.NONCE_SIZE))


class TestZeroRleLimits(unittest.TestCase):
    def test_decompression_bomb_is_stopped_before_allocating(self):
        # 60 RUNB symbols ask for about 2^61 zeros: without the limit this
        # would exhaust memory; with it the error comes immediately.
        start = time.perf_counter()
        with self.assertRaises(ValueError):
            zero_rle_decode([RUNB] * 60, max_output=1000)
        self.assertLess(time.perf_counter() - start, 0.5)

    def test_limit_is_exact(self):
        data = [0] * 7 + [5, 0, 0]
        encoded = zero_rle_encode(data)
        self.assertEqual(zero_rle_decode(encoded, max_output=len(data)), data)
        with self.assertRaises(ValueError):
            zero_rle_decode(encoded, max_output=len(data) - 1)
        with self.assertRaises(ValueError):
            zero_rle_decode([6] * 4, max_output=3)

    def test_symbol_range(self):
        with self.assertRaises(ValueError):
            zero_rle_decode([2, -1, 3])
        with self.assertRaises(ValueError):
            zero_rle_decode([2, 300], max_symbol=256)
        self.assertEqual(zero_rle_decode([RUNA, 256], max_symbol=256), [0, 255])


class TestHuffmanTableValidation(unittest.TestCase):
    def test_valid_tables(self):
        validate_code_lengths({})
        validate_code_lengths({7: 1})
        validate_code_lengths({0: 1, 1: 2, 2: 2})
        _, lengths, _ = huffman_encode_symbols([random.Random(1).randrange(40) for _ in range(5000)])
        validate_code_lengths(lengths, max_symbol=256)

    def test_invalid_tables(self):
        cases = {
            "Kraft > 1 (overlapping codes)": {0: 1, 1: 1, 2: 1},
            "Kraft < 1 (incomplete code)": {0: 1, 1: 2},
            "zero length": {0: 0, 1: 1},
            "length above maximum": {0: 1, 1: MAX_CODE_LENGTH + 1},
            "single symbol with length 2": {5: 2},
            "negative symbol": {-1: 1, 1: 1},
        }
        for name, table in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                validate_code_lengths(table)
        with self.assertRaises(ValueError):
            validate_code_lengths({0: 1, 300: 1}, max_symbol=256)

    def test_serialized_table_is_strict(self):
        raw = serialize_code_lengths({0: 1, 1: 2, 2: 2})
        self.assertEqual(deserialize_code_lengths(raw), ({0: 1, 1: 2, 2: 2}, len(raw)))
        for size in range(len(raw)):
            with self.subTest(truncated=size), self.assertRaises(ValueError):
                deserialize_code_lengths(raw[:size])
        duplicate = struct.pack(">H", 2) + struct.pack(">HB", 3, 1) + struct.pack(">HB", 3, 1)
        with self.assertRaises(ValueError):
            deserialize_code_lengths(duplicate)


class TestHuffmanBitstream(unittest.TestCase):
    def setUp(self):
        self.symbols = [random.Random(2).choice([0, 1, 1, 2, 5, 9]) for _ in range(997)]
        self.data, self.lengths, self.count = huffman_encode_symbols(self.symbols)

    def test_valid_stream(self):
        self.assertEqual(huffman_decode_symbols(self.data, self.lengths, self.count), self.symbols)

    def test_invalid_streams(self):
        padded_bits = len(self.data) * 8 - sum(self.lengths[s] for s in self.symbols)
        cases = {
            "truncated": (self.data[:-1], self.count),
            "trailing byte": (self.data + b"\x00", self.count),
            "too many symbols for the bits": (self.data, len(self.data) * 8 + 1),
            "data for zero symbols": (self.data, 0),
        }
        if padded_bits:
            corrupted = bytearray(self.data)
            corrupted[-1] |= 1  # the last bit is padding: it must be zero
            cases["nonzero padding"] = (bytes(corrupted), self.count)
        for name, (data, count) in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                huffman_decode_symbols(data, self.lengths, count)

    def test_single_symbol_stream(self):
        data, lengths, count = huffman_encode_symbols([4] * 20)
        self.assertEqual(huffman_decode_symbols(data, lengths, count), [4] * 20)
        with self.assertRaises(ValueError):
            huffman_decode_symbols(b"\x01" + data[1:], lengths, count)
        with self.assertRaises(ValueError):
            huffman_decode_symbols(data + b"\x00", lengths, count)


class TestMtfBounds(unittest.TestCase):
    def test_rank_outside_dictionary(self):
        for ranks in ([0, 3], [-1], [2**40]):
            with self.subTest(ranks=ranks), self.assertRaises(ValueError):
                fast_mtf.fast_mtf_decode(ranks, [10, 20, 30])

    def test_symbol_outside_dictionary(self):
        with self.assertRaises(ValueError):
            fast_mtf.fast_mtf_encode([10, 99], [10, 20, 30])
        with self.assertRaises(ValueError):
            fast_mtf.fast_mtf_encode("abz", "ab")

    def test_valid_input_still_works(self):
        ranks = fast_mtf.fast_mtf_encode([30, 30, 10], [10, 20, 30])
        self.assertEqual(fast_mtf.fast_mtf_decode(ranks, [10, 20, 30]), [30, 30, 10])


def forge(original_size, symbols, **changes):
    """Build a structurally valid container around an arbitrary RLE stream."""
    bits, lengths, count = huffman_encode_symbols(symbols)
    container = cf.Container(
        original_size=original_size, bwt_block_size=pipeline.BWT_BLOCK_SIZE,
        bmtf_block_size=pipeline.MIN_BMTF_BLOCK,
        primary_indices=tuple(0 for _ in range(cf.expected_block_count(original_size, pipeline.BWT_BLOCK_SIZE))),
        symbol_count=count, payload=bits, nonce=NONCE,
        huffman_table=serialize_code_lengths(lengths),
    )
    return cf.serialize(replace(container, **changes))


class TestPipelineRejectsForgedFiles(unittest.TestCase):
    def test_rle_bomb_with_small_declared_size(self):
        blob = forge(1000, [RUNB] * 60 + [2])
        start = time.perf_counter()
        with self.assertRaises(cf.ContainerFormatError):
            pipeline.decompress_bytes(blob, KEY, processes=1)
        self.assertLess(time.perf_counter() - start, 0.5)

    def test_declared_size_above_caller_limit(self):
        blob = forge(10**9, [RUNA, 2])
        with self.assertRaises(cf.ContainerFormatError):
            pipeline.decompress_bytes(blob, KEY, processes=1, max_output_size=10**6)

    def test_rle_symbol_above_byte_alphabet(self):
        with self.assertRaises(cf.ContainerFormatError):
            pipeline.decompress_bytes(forge(10, [300] * 10), KEY, processes=1)

    def test_decoded_length_mismatch(self):
        with self.assertRaises(cf.ContainerFormatError):
            pipeline.decompress_bytes(forge(10, [2] * 5), KEY, processes=1)

    def test_tiny_bmtf_block_is_rejected(self):
        blob = forge(10, [2] * 10, bmtf_block_size=1)
        with self.assertRaises(cf.ContainerFormatError):
            pipeline.decompress_bytes(blob, KEY, processes=1)


class TestTampering(unittest.TestCase):
    """Flip every byte (and random groups of bytes) of a real compressed file.

    Without an authentication tag (phase 5) some changes cannot be detected
    and only produce different output. What must never happen is a crash with
    another exception, a hang, or output of the wrong length.
    """

    @classmethod
    def setUpClass(cls):
        rng = random.Random(11)
        words = [b"segreto", b"bwt", b"chiave", b"blocco", b"\x00\x01", b"\xff"]
        cls.data = b" ".join(rng.choice(words) for _ in range(800))
        cls.blob = pipeline.compress_bytes(cls.data, KEY, processes=1, nonce=NONCE)

    def check(self, blob):
        try:
            out = pipeline.decompress_bytes(blob, KEY, processes=1)
        except cf.ContainerFormatError:
            return "rejected"
        self.assertEqual(len(out), len(self.data))
        return "same" if out == self.data else "different"

    def test_every_single_byte_flip(self):
        start = time.perf_counter()
        outcomes = {"rejected": 0, "different": 0, "same": 0}
        for position in range(len(self.blob)):
            mutated = bytearray(self.blob)
            mutated[position] ^= 0xFF
            with self.subTest(position=position):
                outcomes[self.check(bytes(mutated))] += 1
        self.assertGreater(outcomes["rejected"], 0)
        self.assertLess(time.perf_counter() - start, 60)

    def test_random_multi_byte_corruption(self):
        rng = random.Random(5)
        for trial in range(300):
            mutated = bytearray(self.blob)
            for _ in range(rng.randrange(1, 8)):
                mutated[rng.randrange(len(mutated))] = rng.randrange(256)
            with self.subTest(trial=trial):
                self.check(bytes(mutated))


if __name__ == "__main__":
    unittest.main()
