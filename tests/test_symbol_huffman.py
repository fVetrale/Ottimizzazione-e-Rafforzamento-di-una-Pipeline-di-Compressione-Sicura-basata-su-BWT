import unittest
import numpy as np
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from pc.symbol_huffman import (
    build_canonical_huffman,
    build_canonical_codes_from_lengths,
    huffman_encode_symbols,
    huffman_decode_symbols,
    serialize_code_lengths,
    deserialize_code_lengths,
    huffman_compress_to_bytes,
    huffman_decompress_from_bytes
)
from rle.zero_rle import zero_rle_encode, zero_rle_decode


class TestSymbolHuffman(unittest.TestCase):

    def test_empty(self):
        data, lengths, count = huffman_encode_symbols([])
        self.assertEqual(data, b"")
        self.assertEqual(lengths, {})
        self.assertEqual(count, 0)
        self.assertEqual(huffman_decode_symbols(data, lengths, count), [])

        payload = huffman_compress_to_bytes([])
        self.assertEqual(huffman_decompress_from_bytes(payload), [])

    def test_single_symbol(self):
        symbols = [0] * 50
        payload = huffman_compress_to_bytes(symbols)
        decoded = huffman_decompress_from_bytes(payload)
        self.assertEqual(decoded, symbols)

        symbols2 = [42] * 10
        payload2 = huffman_compress_to_bytes(symbols2)
        decoded2 = huffman_decompress_from_bytes(payload2)
        self.assertEqual(decoded2, symbols2)

    def test_two_symbols(self):
        symbols = [0, 1, 0, 0, 1, 1, 0, 1]
        payload = huffman_compress_to_bytes(symbols)
        decoded = huffman_decompress_from_bytes(payload)
        self.assertEqual(decoded, symbols)

    def test_prefix_free_canonical_codes(self):
        symbols = [0] * 100 + [1] * 50 + [2] * 25 + [3] * 12 + [4] * 6 + [5]
        lengths, canonical_codes = build_canonical_huffman(symbols)

        # Verifica che nessun codice sia prefisso di un altro
        binary_codes = [bin(code)[2:].zfill(length) for code, length in canonical_codes.values()]
        for i, c1 in enumerate(binary_codes):
            for j, c2 in enumerate(binary_codes):
                if i != j:
                    self.assertFalse(c1.startswith(c2), f"{c2} è prefisso di {c1}")

        # Verifica che il decoding a partire dalle sole lunghezze dia gli stessi codici
        reconstructed_codes = build_canonical_codes_from_lengths(lengths)
        self.assertEqual(canonical_codes, reconstructed_codes)

    def test_table_serialization(self):
        lengths = {0: 1, 1: 3, 2: 3, 3: 4, 100: 5, 255: 6}
        serialized = serialize_code_lengths(lengths)
        deserialized, bytes_read = deserialize_code_lengths(serialized)
        self.assertEqual(deserialized, lengths)
        self.assertEqual(bytes_read, len(serialized))

    def test_end_to_end_random_stream(self):
        np.random.seed(123)
        # 50.000 simboli con distribuzione geometrica/skewed (tipica di MTF/RLE)
        symbols = list(np.random.geometric(p=0.4, size=50000) - 1)
        payload = huffman_compress_to_bytes(symbols)
        decoded = huffman_decompress_from_bytes(payload)
        self.assertEqual(decoded, symbols)

    def test_combined_zero_rle_and_huffman(self):
        # Simula il flusso reale: MTF -> Zero-RLE -> Huffman -> De-Huffman -> De-Zero-RLE -> MTF
        np.random.seed(99)
        raw_mtf = list(np.random.choice([0, 1, 2, 5, 20], size=30000, p=[0.75, 0.15, 0.05, 0.03, 0.02]))

        # Codifica
        rle_symbols = zero_rle_encode(raw_mtf)
        huffman_payload = huffman_compress_to_bytes(rle_symbols)

        # Decodifica
        decoded_rle = huffman_decompress_from_bytes(huffman_payload)
        self.assertEqual(decoded_rle, rle_symbols)

        decoded_mtf = zero_rle_decode(decoded_rle)
        self.assertEqual(decoded_mtf, raw_mtf)

        # Verifica compressione: i byte del payload devono essere molto inferiori a len(raw_mtf)
        compression_ratio = len(huffman_payload) / len(raw_mtf)
        self.assertLess(compression_ratio, 0.35, f"Rapporto {compression_ratio:.3f} troppo alto")


if __name__ == "__main__":
    unittest.main()
