import os
import random
import sys
import tempfile
import unittest

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, SRC)

import multiprocessing

import container_format as cf
import pipeline
from pipeline import compress_bytes, decompress_bytes

KEY = "chiave-test"
NONCE = bytes(range(cf.NONCE_SIZE))


def round_trip(data, **options):
    processes = options.pop("processes", 1)
    blob = compress_bytes(data, KEY, processes=processes, **options)
    return decompress_bytes(blob, KEY, processes=processes)


class TestRoundTrip(unittest.TestCase):
    def test_edge_cases(self):
        samples = {
            "empty": b"",
            "one byte": b"a",
            "sentinel byte": b"\x03",
            "all byte values": bytes(range(256)),
            "repeated": b"\x00" * 5000,
            "periodic": b"ab" * 3000,
            "text": "La BWT sicura funziona anche con accenti: àèìòù €.\r\n".encode() * 50,
        }
        for name, data in samples.items():
            with self.subTest(name):
                self.assertEqual(round_trip(data), data)

    def test_random_binary(self):
        rng = random.Random(7)
        for size in (1, 17, 1000, 40000):
            data = bytes(rng.randrange(256) for _ in range(size))
            with self.subTest(size=size):
                self.assertEqual(round_trip(data), data)

    def test_corpus_file(self):
        path = os.path.join(SRC, "TestFiles", "Input", "alice29.txt")
        with open(path, "rb") as handle:
            data = handle.read()
        blob = compress_bytes(data, KEY, processes=1)
        self.assertEqual(decompress_bytes(blob, KEY, processes=1), data)
        self.assertLess(len(blob), len(data) * 0.35)

    def test_multiple_blocks_serial_and_parallel(self):
        rng = random.Random(3)
        data = bytes(rng.choice(b"abcde\x00\xff") for _ in range(10_000))
        for processes in (1, 3):
            for block in (1000, 3333, 9999, 10_000):
                with self.subTest(processes=processes, block=block):
                    blob = compress_bytes(data, KEY, bwt_block_size=block,
                                          processes=processes, nonce=NONCE)
                    container = cf.parse(blob)
                    self.assertEqual(len(container.primary_indices),
                                     cf.expected_block_count(len(data), block))
                    self.assertEqual(decompress_bytes(blob, KEY, processes=processes), data)

    def test_parallel_output_matches_serial(self):
        data = os.urandom(5000)
        serial = compress_bytes(data, KEY, bwt_block_size=1000, processes=1, nonce=NONCE)
        parallel = compress_bytes(data, KEY, bwt_block_size=1000, processes=4, nonce=NONCE)
        self.assertEqual(serial, parallel)


class TestBlockPolicy(unittest.TestCase):
    def test_fixed_block_size(self):
        self.assertEqual(pipeline.choose_bwt_block_size(10), pipeline.BWT_BLOCK_SIZE)
        self.assertEqual(pipeline.choose_bwt_block_size(10**9), pipeline.BWT_BLOCK_SIZE)
        blob = compress_bytes(b"x" * 1000, KEY)
        self.assertEqual(cf.parse(blob).bwt_block_size, pipeline.BWT_BLOCK_SIZE)

    def test_parallel_only_above_threshold(self):
        self.assertEqual(pipeline.choose_processes(0), 1)
        self.assertEqual(pipeline.choose_processes(pipeline.PARALLEL_THRESHOLD - 1), 1)
        self.assertEqual(pipeline.choose_processes(pipeline.PARALLEL_THRESHOLD),
                         multiprocessing.cpu_count())


class TestKeysAndNonce(unittest.TestCase):
    data = b"segreto industriale " * 200

    def test_same_nonce_is_deterministic(self):
        first = compress_bytes(self.data, KEY, processes=1, nonce=NONCE)
        second = compress_bytes(self.data, KEY, processes=1, nonce=NONCE)
        self.assertEqual(first, second)

    def test_fresh_nonce_changes_output(self):
        first = compress_bytes(self.data, KEY, processes=1)
        second = compress_bytes(self.data, KEY, processes=1)
        self.assertNotEqual(cf.parse(first).nonce, cf.parse(second).nonce)
        self.assertNotEqual(first, second)
        self.assertEqual(decompress_bytes(first, KEY, processes=1), self.data)
        self.assertEqual(decompress_bytes(second, KEY, processes=1), self.data)

    def test_wrong_key_does_not_restore(self):
        blob = compress_bytes(self.data, KEY, processes=1)
        self.assertNotEqual(decompress_bytes(blob, "chiave-sbagliata", processes=1), self.data)

    def test_key_must_be_text(self):
        with self.assertRaises(TypeError):
            compress_bytes(b"abc", b"bytes-key", processes=1)


class TestMalformedInput(unittest.TestCase):
    def setUp(self):
        self.blob = compress_bytes(b"dati di prova " * 100, KEY, processes=1, nonce=NONCE)

    def test_truncated_or_extended(self):
        for blob in (self.blob[:10], self.blob[:-1], self.blob + b"\x00", b""):
            with self.subTest(size=len(blob)), self.assertRaises(cf.ContainerFormatError):
                decompress_bytes(blob, KEY, processes=1)

    def test_not_a_container(self):
        with self.assertRaises(cf.ContainerFormatError):
            decompress_bytes(b"\x80\x04\x95" + bytes(200), KEY, processes=1)  # pickle-like bytes

    def test_compress_rejects_text(self):
        with self.assertRaises(TypeError):
            compress_bytes("testo", KEY)


class TestNoFilesWritten(unittest.TestCase):
    def test_pipeline_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = os.getcwd()
            os.chdir(directory)
            try:
                blob = compress_bytes(b"nessun file intermedio" * 50, KEY, processes=1)
                decompress_bytes(blob, KEY, processes=1)
                self.assertEqual(os.listdir(directory), [])
            finally:
                os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
