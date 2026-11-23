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

from typing import List, Optional, Sequence, Tuple, Dict, Union
from collections import Counter
import heapq
import struct
import numpy as np

# Lunghezza massima accettata per un codice letto da file. Un codice di Huffman
# più lungo di 64 bit richiederebbe più di 10^13 simboli (frequenze di
# Fibonacci), quindi il limite non esclude nessun file prodotto dall'encoder.
MAX_CODE_LENGTH = 64


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
        # Tiene solo i bit non ancora emessi: senza questa maschera l'accumulatore
        # cresce fino a contenere l'intero stream e ogni shift costa O(n),
        # rendendo la codifica quadratica nel numero di simboli.
        self.bit_accum &= (1 << self.bits_in_accum) - 1

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


def validate_code_lengths(code_lengths: Dict[int, int], max_symbol: Optional[int] = None) -> None:
    """
    Controlla che una tabella di lunghezze (letta da un file non fidato) descriva
    un codice di Huffman valido, prima di costruire l'albero di decodifica.

    - simboli interi in [0, max_symbol] e lunghezze in [1, MAX_CODE_LENGTH];
    - un solo simbolo: lunghezza 1 (è ciò che produce l'encoder);
    - più simboli: disuguaglianza di Kraft con uguaglianza, sum(2^-l) == 1.
      Un codice di Huffman è sempre completo; con somma > 1 i codici canonici
      si sovrappongono, con somma < 1 restano sequenze di bit senza simbolo.

    Raises:
        ValueError: se la tabella non è valida.
    """
    for sym, length in code_lengths.items():
        if not isinstance(sym, int) or sym < 0 or (max_symbol is not None and sym > max_symbol):
            raise ValueError(f"simbolo non ammesso nella tabella di Huffman: {sym}")
        if not isinstance(length, int) or not 1 <= length <= MAX_CODE_LENGTH:
            raise ValueError(f"lunghezza di codice non valida: {length}")
    if len(code_lengths) == 1:
        if next(iter(code_lengths.values())) != 1:
            raise ValueError("una tabella con un solo simbolo deve avere lunghezza 1")
    elif len(code_lengths) > 1:
        kraft = sum(1 << (MAX_CODE_LENGTH - length) for length in code_lengths.values())
        if kraft != 1 << MAX_CODE_LENGTH:
            raise ValueError("le lunghezze dei codici non formano un codice di Huffman completo")


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


def _build_lookup_table(canonical_codes: Dict[int, Tuple[int, int]],
                        table_bits: int) -> List[Optional[Tuple[int, int]]]:
    """Costruisce una tabella di lookup per la decodifica veloce.

    Per ogni possibile combinazione di ``table_bits`` bit, memorizza
    ``(simbolo, lunghezza_codice)`` se il codice di quel simbolo è lungo al
    più ``table_bits``.  Un codice corto viene replicato in tutte le voci che
    condividono il suo prefisso: se il codice è lungo *l*, occupa
    2^(table_bits − l) voci consecutive.

    Le voci per le quali nessun codice di lunghezza ≤ table_bits è prefisso
    restano ``None``: dovranno passare dalla via lenta (albero).
    """
    size = 1 << table_bits
    table: List[Optional[Tuple[int, int]]] = [None] * size
    for sym, (code, length) in canonical_codes.items():
        if length <= table_bits:
            # I bit alti del codice sono seguiti da (table_bits - length) bit
            # arbitrari: riempiamo tutte le combinazioni.
            padding = table_bits - length
            base = code << padding
            for suffix in range(1 << padding):
                table[base | suffix] = (sym, length)
    return table


def _choose_table_bits(code_lengths: Dict[int, int], num_symbols: int) -> int:
    """Sceglie L (ampiezza della tabella) in base ai dati.

    Regola empirica: L = min(max_len_effettiva, 10), ma se il file è piccolo
    (< 2048 simboli) si scende a min(..., 8) per non pagare il costo della
    tabella più del guadagno sulla decodifica.
    """
    max_len = max(code_lengths.values())
    if num_symbols < 2048:
        return min(max_len, 8)
    return min(max_len, 10)


def huffman_decode_symbols(data: bytes, code_lengths: Dict[int, int], num_symbols: int,
                           max_symbol: Optional[int] = None) -> List[int]:
    """
    Decodifica un flusso di byte in simboli interi usando le lunghezze canoniche.

    Usa una tabella di lookup di 2^L voci per risolvere i codici che stanno in
    L bit con un solo accesso; i codici più lunghi passano dall'albero binario.

    Args:
        data: Flusso di byte compressi.
        code_lengths: Dizionario {simbolo: lunghezza}.
        num_symbols: Numero esatto di simboli da decodificare.
        max_symbol: se indicato, valore massimo ammesso per un simbolo.

    Returns:
        Lista di simboli interi originali.

    Raises:
        ValueError: tabella non valida, bit insufficienti, byte in eccesso o
            bit di riempimento diversi da zero (il flusso deve essere esattamente
            quello prodotto da huffman_encode_symbols).
    """
    if num_symbols == 0:
        if data:
            raise ValueError("flusso di bit non vuoto per zero simboli")
        return []

    validate_code_lengths(code_lengths, max_symbol)
    if not code_lengths:
        raise ValueError("tabella di Huffman vuota per un flusso non vuoto")
    # Ogni simbolo occupa almeno un bit: si scarta subito un conteggio impossibile.
    if num_symbols > len(data) * 8:
        raise ValueError("il flusso di bit è troppo corto per il numero di simboli dichiarato")

    # Caso speciale con un solo simbolo unico: l'encoder scrive un bit 0 per simbolo.
    # (Il codice (0, 1) crea un ramo sinistro, quindi la radice non è mai una
    # foglia: il caso si riconosce dalla tabella, non dalla forma dell'albero.)
    if len(code_lengths) == 1:
        if len(data) != -(-num_symbols // 8) or any(data):
            raise ValueError("flusso di bit non valido per una tabella con un solo simbolo")
        sym = next(iter(code_lengths))
        return [sym] * num_symbols

    canonical_codes = build_canonical_codes_from_lengths(code_lengths)

    # --- Tabella di lookup + fallback ad albero per codici lunghi -----------
    table_bits = _choose_table_bits(code_lengths, num_symbols)
    table = _build_lookup_table(canonical_codes, table_bits)

    # L'albero serve solo se qualche codice è più lungo di table_bits.
    max_len = max(code_lengths.values())
    need_tree = max_len > table_bits
    if need_tree:
        root = build_decode_tree(canonical_codes)

    # --- Accumulatore di bit a blocchi --------------------------------------
    # Legge molti byte alla volta per ridurre l'overhead Python per bit.
    total_bits = len(data) * 8
    bit_accum = 0
    bits_in_accum = 0
    byte_pos = 0
    data_len = len(data)

    output: List[int] = [0] * num_symbols  # pre-allocazione
    table_mask = (1 << table_bits) - 1
    bits_consumed = 0  # bit effettivamente consumati (codici decodificati)

    for i in range(num_symbols):
        # Riempimento dell'accumulatore: portiamo almeno table_bits bit (o
        # max_len se servono) pronti.  Leggiamo fino a 8 byte alla volta.
        needed = max_len if need_tree else table_bits
        while bits_in_accum < needed and byte_pos < data_len:
            # Carica fino a 8 byte alla volta nell'accumulatore.
            can_load = min(8, data_len - byte_pos)
            for _ in range(can_load):
                bit_accum = (bit_accum << 8) | data[byte_pos]
                byte_pos += 1
                bits_in_accum += 8

        # Bit realmente rimasti nel flusso (non padding).
        bits_remaining = total_bits - bits_consumed

        if bits_in_accum < 1:
            raise ValueError("Flusso di bit terminato inaspettatamente prima di completare i simboli.")

        # Tentativo veloce con la tabella di lookup.
        # Se l'accumulatore ha meno di table_bits bit, paddiamo con zeri a
        # destra: il codice canonico corretto è comunque un prefisso di ciò
        # che leggiamo, e il padding zero non crea ambiguità purché si
        # verifichi che la lunghezza del codice trovato non superi i bit
        # realmente rimasti.
        if bits_in_accum >= table_bits:
            peek = (bit_accum >> (bits_in_accum - table_bits)) & table_mask
        elif bits_in_accum > 0:
            peek = ((bit_accum & ((1 << bits_in_accum) - 1))
                    << (table_bits - bits_in_accum)) & table_mask
        else:
            peek = -1  # nessun bit: forza il fallback

        if peek >= 0:
            entry = table[peek]
            if entry is not None:
                sym, length = entry
                # Controllo: il codice non deve essere più lungo dei bit
                # realmente rimasti (escludendo il padding finale).
                if length > bits_remaining:
                    raise ValueError("Flusso di bit terminato inaspettatamente prima di completare i simboli.")
                bits_in_accum -= length
                bit_accum &= (1 << bits_in_accum) - 1
                bits_consumed += length
                output[i] = sym
                continue

        # Via lenta: percorso bit per bit lungo l'albero, per codici > table_bits.
        if not need_tree:
            # Non dovrebbe mai succedere con una tabella valida e codici
            # non più lunghi di table_bits.
            raise ValueError("sequenza di bit che non corrisponde a nessun codice")

        curr = root
        code_bits_used = 0
        while curr.symbol is None:
            if bits_in_accum < 1:
                raise ValueError("Flusso di bit terminato inaspettatamente prima di completare i simboli.")
            if bits_consumed + code_bits_used >= total_bits:
                raise ValueError("Flusso di bit terminato inaspettatamente prima di completare i simboli.")
            bits_in_accum -= 1
            code_bits_used += 1
            bit = (bit_accum >> bits_in_accum) & 1
            if bit == 0:
                curr = curr.left
            else:
                curr = curr.right
            if curr is None:
                raise ValueError("sequenza di bit che non corrisponde a nessun codice")
        bit_accum &= (1 << bits_in_accum) - 1
        bits_consumed += code_bits_used
        output[i] = curr.symbol

    # --- Controlli finali ---------------------------------------------------
    # Bit consumati dalla decodifica: tutto il resto deve essere padding zero.
    # Il numero di byte effettivamente necessari è ceil(bits_consumed / 8).
    expected_bytes = -(-bits_consumed // 8) if bits_consumed else 0
    if expected_bytes != data_len:
        raise ValueError("byte in eccesso dopo l'ultimo simbolo")
    padding_bits = data_len * 8 - bits_consumed
    if padding_bits > 0:
        # I bit di riempimento sono gli ultimi 'padding_bits' bit dell'ultimo byte.
        padding_mask = (1 << padding_bits) - 1
        if data[-1] & padding_mask:
            raise ValueError("bit di riempimento diversi da zero")
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
    out = bytearray(struct.pack(">H", n))
    for sym, length in sorted(code_lengths.items()):
        out.extend(struct.pack(">HB", int(sym), int(length)))
    return bytes(out)


def deserialize_code_lengths(raw: bytes, offset: int = 0) -> Tuple[Dict[int, int], int]:
    """
    Deserializza la tabella delle lunghezze dal buffer binario a partire da offset.
    Restituisce: (code_lengths, bytes_letti).

    Raises:
        ValueError: tabella troncata o simboli non in ordine strettamente
            crescente (serialize_code_lengths li scrive ordinati; un duplicato
            sovrascriverebbe in silenzio la lunghezza precedente).
    """
    if len(raw) < offset + 2:
        raise ValueError("tabella di Huffman troncata")
    n = struct.unpack_from(">H", raw, offset)[0]
    pos = offset + 2
    if len(raw) < pos + 3 * n:
        raise ValueError("tabella di Huffman troncata")
    code_lengths: Dict[int, int] = {}
    previous = -1
    for _ in range(n):
        sym, length = struct.unpack_from(">HB", raw, pos)
        if sym <= previous:
            raise ValueError("simboli della tabella di Huffman duplicati o non ordinati")
        code_lengths[sym] = length
        previous = sym
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
        return struct.pack(">I", 0)

    encoded_bytes, code_lengths, _ = huffman_encode_symbols(symbols)
    table_bytes = serialize_code_lengths(code_lengths)

    header = struct.pack(">I", num_symbols)
    return header + table_bytes + encoded_bytes


def huffman_decompress_from_bytes(payload: bytes) -> List[int]:
    """
    Decomprime un payload binario generato da huffman_compress_to_bytes.
    """
    if len(payload) < 4:
        return []
    num_symbols = struct.unpack_from(">I", payload, 0)[0]
    if num_symbols == 0:
        return []

    code_lengths, table_len = deserialize_code_lengths(payload, offset=4)
    bitstream_offset = 4 + table_len
    bitstream = payload[bitstream_offset:]

    return huffman_decode_symbols(bitstream, code_lengths, num_symbols)
