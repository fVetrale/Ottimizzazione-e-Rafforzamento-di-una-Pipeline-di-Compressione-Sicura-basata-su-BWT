import contextlib
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

import container_format as cf
import decompression
import sbwt_compress

KEY = "chiave-test"


def quiet(function, *args):
    with contextlib.redirect_stdout(io.StringIO()) as output:
        result = function(*args)
    return result, output.getvalue()


class TestFileWrappers(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = lambda name: os.path.join(self.directory.name, name)

    def test_binary_file_round_trip_writes_only_one_file(self):
        data = bytes(range(256)) * 40 + b"\x00\xff\xfe" * 1000  # not valid UTF-8
        with open(self.path("input.bin"), "wb") as handle:
            handle.write(data)

        size, log = quiet(sbwt_compress.compress_file, self.path("input.bin"),
                          self.path("out.sbwt"), KEY)
        self.assertEqual(size, os.path.getsize(self.path("out.sbwt")))
        self.assertEqual(sorted(os.listdir(self.directory.name)), ["input.bin", "out.sbwt"])
        for stage in ("sBWT", "bMTF", "RLE", "PC", "compression"):
            self.assertIn(f"-> elapsed time of {stage}", log)

        restored, log = quiet(decompression.decompress_file, self.path("out.sbwt"),
                              self.path("restored.bin"), KEY)
        self.assertEqual(restored, len(data))
        with open(self.path("restored.bin"), "rb") as handle:
            self.assertEqual(handle.read(), data)
        for stage in ("I-PC", "I-RLE", "I-BMTF", "I-BWT", "decompression"):
            self.assertIn(f"-> elapsed time of {stage}", log)

    def test_malformed_file_is_rejected_and_no_output_is_left(self):
        with open(self.path("bad.sbwt"), "wb") as handle:
            handle.write(b"SBWT" + bytes(100))
        with self.assertRaises(cf.ContainerFormatError):
            quiet(decompression.decompress_file, self.path("bad.sbwt"), self.path("out.bin"), KEY)
        self.assertFalse(os.path.exists(self.path("out.bin")))
        self.assertFalse(os.path.exists(self.path("out.bin.tmp")))

    def test_only_huffman_mode_is_supported(self):
        sbwt_compress.check_mode(0)
        for mode in (1, 2):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                sbwt_compress.check_mode(mode)


if __name__ == "__main__":
    unittest.main()
