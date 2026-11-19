"""Decompressione da file (fase 3): involucro attorno a ``pipeline.decompress_bytes``.

Legge ``TestFiles/Output/compressed.sbwt``, lo valida per intero prima di
decodificarlo e scrive i byte originali in ``TestFiles/Output/decompressed.txt``
(il nome resta quello storico, ma il contenuto è binario). Un file malformato
viene rifiutato con ``container_format.ContainerFormatError``: non c'è più
``pickle``, quindi aprire un file manipolato non esegue codice.
"""

import os
import time

import pipeline
from sbwt_compress import COMPRESSED_PATH, OUTPUT_DIR, check_mode, print_timings, write_atomically

DECOMPRESSED_PATH = os.path.join(OUTPUT_DIR, "decompressed.txt")


def decompress_file(input_path: str, output_path: str, secret_key: str) -> int:
    """Decomprime ``input_path`` in ``output_path``; restituisce la dimensione scritta."""
    start = time.perf_counter()
    with open(input_path, "rb") as handle:
        blob = handle.read()
    timings = {}
    data = pipeline.decompress_bytes(blob, secret_key, timings=timings)
    write_atomically(output_path, data)
    print_timings(timings, "decompression", time.perf_counter() - start)
    return len(data)


def decompressione(secret_key: str, mode: int = 0) -> None:
    """Interfaccia storica usata da tester.py e da benchmarks/_driver.py."""
    check_mode(mode)
    decompress_file(COMPRESSED_PATH, DECOMPRESSED_PATH, secret_key)
