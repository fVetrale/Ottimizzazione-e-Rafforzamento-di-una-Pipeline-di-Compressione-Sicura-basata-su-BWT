"""
Driver e Pipeline di test per la Fase 2:
sBWT -> fast bMTF (Numba) -> Zero-RLE (bzip2 style) -> Canonical Huffman su simboli.

Questo modulo può essere eseguito da riga di comando o importato dai colleghi
come driver/stub per testare la Fase 2 in modo integrato.
"""

import os
import sys
import time
from typing import Tuple, Union

# Assicura che la cartella 'src' sia nel path
_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

import sbwt.sbwt as sbwt
import bmtf.bmtf as bmtf
from rle.zero_rle import zero_rle_encode, zero_rle_decode
from pc.symbol_huffman import (
    huffman_compress_to_bytes,
    huffman_decompress_from_bytes
)


def compress_phase2(data: str, key: str, bmtf_block_size: int = 1024) -> Tuple[bytes, str]:
    """
    Comprime una stringa di testo usando la pipeline completa della Fase 2.
    
    Returns:
        tuple (compressed_payload, alphabet_string)
    """
    input_with_eof = data + "\003"
    bwt_output = sbwt.bwt_from_suffix(input_with_eof, key)

    alphabet = "".join(sorted(set(bwt_output)))
    mtf_output = bmtf.secure_encode(bwt_output, list(alphabet), key, bmtf_block_size)
    rle_output = zero_rle_encode(mtf_output)
    compressed_bytes = huffman_compress_to_bytes(rle_output)

    return compressed_bytes, alphabet


def decompress_phase2(compressed_payload: bytes, alphabet: str, key: str, bmtf_block_size: int = 1024) -> str:
    """
    Decomprime il payload della Fase 2 ripristinando l'esatto testo originale.
    """
    rle_symbols = huffman_decompress_from_bytes(compressed_payload)
    mtf_symbols = zero_rle_decode(rle_symbols)
    bwt_output = bmtf.secure_decode(mtf_symbols, list(alphabet), key, bmtf_block_size)
    restored = sbwt.ibwt_from_suffix(bwt_output, key)

    if restored.endswith("\003"):
        restored = restored[:-1]
    return restored


if __name__ == "__main__":
    file_name = sys.argv[1] if len(sys.argv) > 1 else "alice29.txt"
    secret_key = sys.argv[2] if len(sys.argv) > 2 else "chiave"

    input_path = os.path.join(_SRC_DIR, "TestFiles", "Input", file_name)
    if not os.path.exists(input_path):
        input_path = file_name  # fallback percorso diretto

    print(f"=== Esecuzione Driver Fase 2 su: {input_path} ===")
    with open(input_path, "r", encoding="utf-8", errors="ignore") as f:
        original_text = f.read()

    orig_size = len(original_text.encode("utf-8"))
    print(f"Dimensione originale: {orig_size:,} byte")

    t0 = time.time()
    comp_bytes, alphabet = compress_phase2(original_text, secret_key)
    t_comp = time.time() - t0

    comp_size = len(comp_bytes)
    ratio = comp_size / orig_size
    saving = (1.0 - ratio) * 100.0

    print(f"Tempo di compressione: {t_comp:.3f} s")
    print(f"Dimensione compressa: {comp_size:,} byte")
    print(f"Rapporto di compressione: {ratio:.3f} (Risparmio spazio: {saving:.1f}%)")

    t1 = time.time()
    restored_text = decompress_phase2(comp_bytes, alphabet, secret_key)
    t_decomp = time.time() - t1

    print(f"Tempo di decompressione: {t_decomp:.3f} s")
    is_identical = (restored_text == original_text)
    print(f"Round-trip riuscito con successo: {'SI' if is_identical else 'NO'}")
    assert is_identical, "ERRORE: Il testo decompresso non corrisponde all'originale!"
