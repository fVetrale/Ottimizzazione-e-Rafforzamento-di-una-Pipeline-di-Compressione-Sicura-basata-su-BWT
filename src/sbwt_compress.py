"""Compressione da file (fase 3): involucro attorno a ``pipeline.compress_bytes``.

Legge il file in binario, lo comprime in memoria e scrive un solo file,
``TestFiles/Output/compressed.sbwt``, nel formato di ``container_format``.
Rispetto alla pipeline originale non ci sono più la lettura come testo, la
sentinella, i nove file intermedi in chiaro e ``pickle``.

La nuova pipeline usa solo la codifica di Huffman (modo 0). I modi 1
(aritmetico) e 2 (LZW) appartenevano alla pipeline testuale e restano nella
cronologia di git e nelle versioni MPI, che non sono state convertite.

Chi chiama queste funzioni da uno script deve usare la guardia
``if __name__ == "__main__":``, perché i blocchi della sBWT sono elaborati
in processi avviati con "spawn".
"""

import os
import time

import pipeline

INPUT_DIR = os.path.join("TestFiles", "Input")
OUTPUT_DIR = os.path.join("TestFiles", "Output")
COMPRESSED_PATH = os.path.join(OUTPUT_DIR, "compressed.sbwt")
SUPPORTED_MODES = (0,)


def check_mode(mode: int) -> None:
    if mode not in SUPPORTED_MODES:
        raise ValueError(
            f"modo {mode} non supportato: la pipeline a byte usa solo Huffman (modo 0); "
            "aritmetico (1) e LZW (2) esistono solo nella pipeline testuale originale"
        )


def write_atomically(path: str, data: bytes) -> None:
    """Scrive ``data`` in ``path`` senza lasciare file a metà in caso di errore."""
    temporary = path + ".tmp"
    with open(temporary, "wb") as handle:
        handle.write(data)
    os.replace(temporary, path)


def print_timings(timings: dict, total_name: str, total: float) -> None:
    """Stampa i tempi nel formato della pipeline originale, letto dal benchmark."""
    for name, seconds in timings.items():
        print(f"{seconds}  -> elapsed time of {name}")
    print(f"{total}  -> elapsed time of {total_name}")


def compress_file(input_path: str, output_path: str, secret_key: str) -> int:
    """Comprime ``input_path`` in ``output_path``; restituisce la dimensione scritta."""
    start = time.perf_counter()
    with open(input_path, "rb") as handle:
        data = handle.read()
    timings = {}
    blob = pipeline.compress_bytes(data, secret_key, timings=timings)
    write_atomically(output_path, blob)
    print_timings(timings, "compression", time.perf_counter() - start)
    return len(blob)


def compressione(file_name: str, secret_key: str, mode: int = 0) -> None:
    """Interfaccia storica usata da tester.py e da benchmarks/_driver.py."""
    check_mode(mode)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    compress_file(os.path.join(INPUT_DIR, file_name), COMPRESSED_PATH, secret_key)
