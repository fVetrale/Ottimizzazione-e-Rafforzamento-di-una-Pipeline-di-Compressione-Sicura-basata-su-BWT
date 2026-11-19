"""
Modulo per la codifica entropica di Huffman su simboli interi (Canonical Huffman).

Progettato per la Fase 2 della pipeline sBWT + bMTF:
- Lavora direttamente su sequenze di interi (output dello stadio Zero-RLE).
- Usa la codifica di Huffman canonica (Canonical Huffman): la tabella dei codici
  è univocamente determinata dalle sole lunghezze dei codici.
- Zero dipendenze esterne (non richiede dahuffman né pickle).
- Serializzazione binaria compatta della tabella (2-3 byte per simbolo unico).
- Già predisposto per l'integrazione nell'header binario della Fase 3.
"""

from typing import List, Sequence, Tuple, Dict, Union
from collections import Counter
import heapq
import struct
import numpy as np


class BitWriter:
    """Buffer efficiente per la scrittura bit a bit impacchettata in byte."""
    __slots__ = ('buffer', 'bit_accum', 'bits_in_accum')

    def __init__(self):
        self.buffer = bytearray()
        self.bit_accum = 0
        self.bits_in_accum = 0

    def write_bits(self, code: int, length: int) -> None:
        self.bit_accum = (self.bit_accum << length) | code
        self.bits_in_accum += length
        while self.bits_in_accum >= 8:
            self.bits_in_accum -= 8
            byte = (self.bit_accum >> self.bits_in_accum) & 0xFF
            self.buffer.append(byte)

    def flush(self) -> Tuple[bytes, int]:
        """Finalizza lo stream allineando all'ultimo byte. Restituisce (bytes, total_bits)."""
        total_bits = len(self.buffer) * 8 + self.bits_in_accum
        if self.bits_in_accum > 0:
            byte = (self.bit_accum << (8 - self.bits_in_accum)) & 0xFF
            self.buffer.append(byte)
            self.bits_in_accum = 0
            self.bit_accum = 0
        return bytes(self.buffer), total_bits


class BitReader:
    """Lettore veloce bit a bit da un buffer di byte."""
    __slots__ = ('data', 'byte_pos', 'bit_accum', 'bits_in_accum', 'total_bytes')

    def __init__(self, data: bytes):
        self.data = data
        self.byte_pos = 0
        self.bit_accum = 0
        self.bits_in_accum = 0
        self.total_bytes = len(data)

    def read_bit(self) -> int:
        if self.bits_in_accum == 0:
            if self.byte_pos < self.total_bytes:
                self.bit_accum = self.data[self.byte_pos]
                self.byte_pos += 1
                self.bits_in_accum = 8
            else:
                return -1
        self.bits_in_accum -= 1
        return (self.bit_accum >> self.bits_in_accum) & 1


class HuffmanDecodeNode:
    """Nodo compatto per l'albero di decodifica bit a bit."""
    __slots__ = ('left', 'right', 'symbol')

    def __init__(self):
        self.left = None
        self.right = None
        self.symbol = None


def build_canonical_huffman(symbols: Sequence[int]) -> Tuple[Dict[int, int], Dict[int, Tuple[int, int]]]:
    """
    Calcola le lunghezze dei codici di Huffman e genera i codici canonici.
    
    Args:
        symbols: Sequenza di simboli interi non negativi.
        
    Returns:
        tuple (code_lengths, canonical_codes):
          - code_lengths: dict {simbolo: lunghezza_codice}
          - canonical_codes: dict {simbolo: (codice_intero, lunghezza)}
    """
    if len(symbols) == 0:
        return {}, {}

    counts = Counter(symbols)

    # Caso speciale: un solo simbolo unico presente
    if len(counts) == 1:
        sym = next(iter(counts))
        return {sym: 1}, {sym: (0, 1)}

    # Costruzione albero con min-heap standard
    # Gli elementi dell'heap sono: [frequenza, [simbolo, prefisso_bit]]
    heap = [[weight, [sym, ""]] for sym, weight in counts.items()]
    heapq.heapify(heap)

    while len(heap) > 1:
        lo = heapq.heappop(heap)
        hi = heapq.heappop(heap)
        for pair in lo[1:]:
            pair[1] = "0" + pair[1]
        for pair in hi[1:]:
            pair[1] = "1" + pair[1]
        heapq.heappush(heap, [lo[0] + hi[0]] + lo[1:] + hi[1:])

    tree_lengths = {sym: len(code) for sym, code in heap[0][1:]}

    # Assegnazione dei codici canonici:
    # 1. Ordina i simboli per lunghezza crescente, e a parità di lunghezza per valore del simbolo
    sorted_syms = sorted(tree_lengths.keys(), key=lambda s: (tree_lengths[s], s))

    canonical_codes: Dict[int, Tuple[int, int]] = {}
    code = 0
    prev_len = tree_lengths[sorted_syms[0]]

    for sym in sorted_syms:
        l = tree_lengths[sym]
        code <<= (l - prev_len)
        canonical_codes[sym] = (code, l)
        code += 1
        prev_len = l

    return tree_lengths, canonical_codes


def build_canonical_codes_from_lengths(code_lengths: Dict[int, int]) -> Dict[int, Tuple[int, int]]:
    """Ricostruisce i codici canonici a partire dal solo dizionario delle lunghezze."""
    if not code_lengths:
        return {}
    if len(code_lengths) == 1:
        sym = next(iter(code_lengths))
        return {sym: (0, 1)}

    sorted_syms = sorted(code_lengths.keys(), key=lambda s: (code_lengths[s], s))
    canonical_codes: Dict[int, Tuple[int, int]] = {}
    code = 0
    prev_len = code_lengths[sorted_syms[0]]

    for sym in sorted_syms:
        l = code_lengths[sym]
        code <<= (l - prev_len)
        canonical_codes[sym] = (code, l)
        code += 1
        prev_len = l

    return canonical_codes


def build_decode_tree(canonical_codes: Dict[int, Tuple[int, int]]) -> HuffmanDecodeNode:
    """Costruisce un albero di decodifica binario a partire dai codici canonici."""
    root = HuffmanDecodeNode()
    for sym, (code, length) in canonical_codes.items():
        curr = root
        for i in range(length - 1, -1, -1):
            bit = (code >> i) & 1
            if bit == 0:
                if curr.left is None:
                    curr.left = HuffmanDecodeNode()
                curr = curr.left
            else:
                if curr.right is None:
                    curr.right = HuffmanDecodeNode()
                curr = curr.right
        curr.symbol = sym
    return root


def huffman_encode_symbols(symbols: Union[Sequence[int], np.ndarray]) -> Tuple[bytes, Dict[int, int], int]:
    """
    Codifica una sequenza di simboli interi usando Huffman Canonico.
    
    Args:
        symbols: Sequenza di simboli interi.
        
    Returns:
        tuple (encoded_bytes, code_lengths, num_symbols):
          - encoded_bytes: flusso di byte compressi
          - code_lengths: dizionario {simbolo: lunghezza}
          - num_symbols: conteggio totale dei simboli codificati
    """
    num_symbols = len(symbols)
    if num_symbols == 0:
        return b"", {}, 0

    code_lengths, canonical_codes = build_canonical_huffman(symbols)

    writer = BitWriter()
    for sym in symbols:
        code, length = canonical_codes[int(sym)]
        writer.write_bits(code, length)

    encoded_bytes, _ = writer.flush()
    return encoded_bytes, code_lengths, num_symbols


def huffman_decode_symbols(data: bytes, code_lengths: Dict[int, int], num_symbols: int) -> List[int]:
    """
    Decodifica un flusso di byte in simboli interi usando le lunghezze canoniche.
    
    Args:
        data: Flusso di byte compressi.
        code_lengths: Dizionario {simbolo: lunghezza}.
        num_symbols: Numero esatto di simboli da decodificare.
        
    Returns:
        Lista di simboli interi originali.
    """
    if num_symbols == 0:
        return []

    canonical_codes = build_canonical_codes_from_lengths(code_lengths)
    root = build_decode_tree(canonical_codes)

    reader = BitReader(data)
    output: List[int] = []

    # Caso speciale con un solo simbolo unico
    if root.left is None and root.right is None:
        sym = next(iter(code_lengths))
        return [sym] * num_symbols

    curr = root
    for _ in range(num_symbols):
        while curr.symbol is None:
            bit = reader.read_bit()
            if bit == 0:
                curr = curr.left
            elif bit == 1:
                curr = curr.right
            else:
                raise ValueError("Flusso di bit terminato inaspettatamente prima di completare i simboli.")
        output.append(curr.symbol)
        curr = root

    return output


# --- Funzioni di serializzazione per la tabella dei codici (per Fase 2 e Fase 3) ---

def serialize_code_lengths(code_lengths: Dict[int, int]) -> bytes:
    """
    Serializza la tabella delle lunghezze canoniche in formato binario compatto:
      [2 byte: numero_simboli N]
      Per ogni simbolo:
        [2 byte: simbolo uint16]
        [1 byte: lunghezza uint8]
    """
    n = len(code_lengths)
    out = bytearray(struct.pack("<H", n))
    for sym, length in sorted(code_lengths.items()):
        out.extend(struct.pack("<HB", int(sym), int(length)))
    return bytes(out)


def deserialize_code_lengths(raw: bytes, offset: int = 0) -> Tuple[Dict[int, int], int]:
    """
    Deserializza la tabella delle lunghezze dal buffer binario a partire da offset.
    Restituisce: (code_lengths, bytes_letti).
    """
    if len(raw) < offset + 2:
        return {}, 0
    n = struct.unpack_from("<H", raw, offset)[0]
    pos = offset + 2
    code_lengths: Dict[int, int] = {}
    for _ in range(n):
        sym, length = struct.unpack_from("<HB", raw, pos)
        code_lengths[sym] = length
        pos += 3
    return code_lengths, pos - offset


def huffman_compress_to_bytes(symbols: Union[Sequence[int], np.ndarray]) -> bytes:
    """
    Comprime una sequenza di simboli interi producendo un payload binario autonomo:
      [4 byte: num_symbols uint32]
      [tabella_canonica_serializzata]
      [bitstream_compresso]
    """
    num_symbols = len(symbols)
    if num_symbols == 0:
        return struct.pack("<I", 0)

    encoded_bytes, code_lengths, _ = huffman_encode_symbols(symbols)
    table_bytes = serialize_code_lengths(code_lengths)

    header = struct.pack("<I", num_symbols)
    return header + table_bytes + encoded_bytes


def huffman_decompress_from_bytes(payload: bytes) -> List[int]:
    """
    Decomprime un payload binario generato da huffman_compress_to_bytes.
    """
    if len(payload) < 4:
        return []
    num_symbols = struct.unpack_from("<I", payload, 0)[0]
    if num_symbols == 0:
        return []

    code_lengths, table_len = deserialize_code_lengths(payload, offset=4)
    bitstream_offset = 4 + table_len
    bitstream = payload[bitstream_offset:]

    return huffman_decode_symbols(bitstream, code_lengths, num_symbols)
