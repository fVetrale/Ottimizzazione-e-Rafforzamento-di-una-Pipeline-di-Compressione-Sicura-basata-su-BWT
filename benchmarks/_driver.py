"""Esegue UNA fase (compressione o decompressione) della pipeline originale.

Viene lanciato da run_baseline.py in un processo separato, così tempo e memoria
di compressione e decompressione si misurano in modo indipendente.

Uso: python _driver.py compress|decompress <src_dir> <file_relativo_a_Input> <chiave> <modo>
"""
import json
import os
import sys
import time


def main():
    step, src_dir, file_name, key, mode = sys.argv[1:6]
    mode = int(mode)
    os.chdir(src_dir)                 # il codice originale usa percorsi relativi a src/
    sys.path.insert(0, src_dir)

    if step == "compress":
        import sbwt_compress as compression
        t0 = time.perf_counter()
        compression.compressione(file_name, key, mode)
        elapsed = time.perf_counter() - t0
    elif step == "decompress":
        import decompression
        t0 = time.perf_counter()
        decompression.decompressione(key, mode)
        elapsed = time.perf_counter() - t0
    else:
        raise SystemExit(f"fase sconosciuta: {step}")

    sys.stdout.flush()
    print("BENCH_JSON " + json.dumps({"internal_s": elapsed}), flush=True)


if __name__ == "__main__":
    main()
