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
    huffman_decompress_from_bytes,
    BitWriter,
    _build_lookup_table,
    _choose_table_bits,
)
from rle.zero_rle import zero_rle_encode, zero_rle_decode


# Codici canonici: 0 -> 0, 1 -> 10, 2 -> 110, 3 -> 111
SMALL_LENGTHS = {0: 1, 1: 2, 2: 3, 3: 3}


def chain_lengths(max_length):
    """Codice completo con lunghezze 1, 2, ..., max_length, max_length."""
    lengths = {symbol: symbol + 1 for symbol in range(max_length)}
    lengths[max_length] = max_length
    return lengths


def encode_with_lengths(symbols, lengths):
    codes = build_canonical_codes_from_lengths(lengths)
    writer = BitWriter()
    for symbol in symbols:
        writer.write_bits(*codes[symbol])
    return writer.flush()[0]


def reference_decode(data, lengths, count):
    """Decoder indipendente su stringhe di bit, usato come confronto."""
    codes = build_canonical_codes_from_lengths(lengths)
    by_bits = {format(code, f"0{length}b"): symbol for symbol, (code, length) in codes.items()}
    bits = "".join(format(byte, "08b") for byte in data)
    output, position = [], 0
    for _ in range(count):
        end = position + 1
        while bits[position:end] not in by_bits:
            if end > len(bits):
                raise ValueError("flusso terminato")
            end += 1
        if end > len(bits):
            raise ValueError("flusso terminato")
        output.append(by_bits[bits[position:end]])
        position = end
    remainder = bits[position:]
    if len(remainder) >= 8 or "1" in remainder:
        raise ValueError("byte in eccesso o padding non nullo")
    return output


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

    def test_bit_writer_accumulator_stays_bounded(self):
        # L'accumulatore deve contenere solo i bit non ancora emessi (< 8):
        # se crescesse con lo stream la codifica diventerebbe quadratica.
        writer = BitWriter()
        for i in range(50_000):
            writer.write_bits(i % 32, 5 + i % 13)
            self.assertLess(writer.bits_in_accum, 8)
            self.assertLess(writer.bit_accum.bit_length(), 8)
        data, total_bits = writer.flush()
        self.assertEqual(len(data), -(-total_bits // 8))

    def test_bit_writer_matches_reference_bitstring(self):
        rng = np.random.default_rng(5)
        writer = BitWriter()
        reference = []
        for _ in range(5000):
            length = int(rng.integers(1, 20))
            code = int(rng.integers(0, 1 << length))
            writer.write_bits(code, length)
            reference.append(format(code, f"0{length}b"))
        data, total_bits = writer.flush()
        bits = "".join(reference)
        self.assertEqual(total_bits, len(bits))
        bits += "0" * (-len(bits) % 8)
        expected = bytes(int(bits[i:i + 8], 2) for i in range(0, len(bits), 8))
        self.assertEqual(data, expected)


class TestLookupDecoder(unittest.TestCase):

    def test_table_width_depends_on_stream_not_on_declared_maximum(self):
        self.assertEqual(_choose_table_bits(SMALL_LENGTHS, 100_000), 3)
        self.assertEqual(_choose_table_bits(chain_lengths(64), 2047), 8)
        self.assertEqual(_choose_table_bits(chain_lengths(64), 2048), 10)

    def test_lookup_table_entries(self):
        canonical = build_canonical_codes_from_lengths(SMALL_LENGTHS)
        self.assertEqual(_build_lookup_table(canonical, 3), [
            (0, 1), (0, 1), (0, 1), (0, 1), (1, 2), (1, 2), (2, 3), (3, 3),
        ])
        # I prefissi dei codici più lunghi della tabella restano alla via lenta.
        self.assertEqual(_build_lookup_table(canonical, 2), [(0, 1), (0, 1), (1, 2), None])

    def test_known_bitstream(self):
        # 111 0 110 10 + 7 bit di padding
        self.assertEqual(encode_with_lengths([3, 0, 2, 1], SMALL_LENGTHS), b"\xed\x00")
        self.assertEqual(huffman_decode_symbols(b"\xed\x00", SMALL_LENGTHS, 4), [3, 0, 2, 1])

    def test_codes_longer_than_table_up_to_maximum(self):
        for max_length in (8, 9, 10, 11, 12, 32, 63, 64):
            lengths = chain_lengths(max_length)
            for repeats in (1, 2100 // len(lengths) + 1):  # tabella da 8 e da 10 bit
                symbols = list(lengths) * repeats
                data = encode_with_lengths(symbols, lengths)
                with self.subTest(max_length=max_length, count=len(symbols)):
                    self.assertEqual(huffman_decode_symbols(data, lengths, len(symbols)), symbols)

    def test_code_cut_by_end_of_stream_is_rejected(self):
        # 111 111 poi restano "11": completati con zeri sembrerebbero il codice 110.
        with self.assertRaisesRegex(ValueError, "terminato"):
            huffman_decode_symbols(b"\xff", SMALL_LENGTHS, 3)
        # Lo stesso per un codice lungo che passa dalla via lenta.
        lengths = chain_lengths(16)
        data = encode_with_lengths([16], lengths)
        with self.assertRaisesRegex(ValueError, "terminato"):
            huffman_decode_symbols(data[:1], lengths, 1)

    def test_truncated_streams_are_rejected(self):
        lengths = chain_lengths(24)
        symbols = list(lengths) * 3
        data = encode_with_lengths(symbols, lengths)
        for size in range(len(data)):
            with self.subTest(size=size), self.assertRaises(ValueError):
                huffman_decode_symbols(data[:size], lengths, len(symbols))

    def test_extra_bytes_are_rejected(self):
        for extra in (b"\x00", b"\xff", b"\x00" * 9):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                huffman_decode_symbols(b"\xed\x00" + extra, SMALL_LENGTHS, 4)

    def test_every_nonzero_padding_bit_is_rejected(self):
        for bit in range(7):
            with self.subTest(bit=bit), self.assertRaises(ValueError):
                huffman_decode_symbols(bytes([0xED, 1 << bit]), SMALL_LENGTHS, 4)

    def test_matches_reference_on_valid_and_corrupted_streams(self):
        rng = np.random.default_rng(2026)
        for case in range(300):
            max_length = int(rng.integers(2, 25))
            lengths = chain_lengths(max_length)
            count = int(rng.integers(1, 200))
            weights = np.array([0.5 ** min(length, 12) for length in lengths.values()])
            symbols = rng.choice(list(lengths), size=count, p=weights / weights.sum()).tolist()
            data = encode_with_lengths(symbols, lengths)
            self.assertEqual(huffman_decode_symbols(data, lengths, count), symbols)

            corrupted = bytearray(data)
            corrupted[int(rng.integers(len(data)))] ^= 1 << int(rng.integers(8))
            for stream, declared in ((bytes(corrupted), count), (data, count + 1), (data, max(count - 1, 1))):
                try:
                    expected = reference_decode(stream, lengths, declared)
                except ValueError:
                    with self.subTest(case=case), self.assertRaises(ValueError):
                        huffman_decode_symbols(stream, lengths, declared)
                else:
                    with self.subTest(case=case):
                        self.assertEqual(huffman_decode_symbols(stream, lengths, declared), expected)


if __name__ == "__main__":
    unittest.main()
