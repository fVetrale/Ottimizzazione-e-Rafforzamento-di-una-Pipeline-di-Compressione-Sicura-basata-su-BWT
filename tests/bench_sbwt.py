"""
Benchmark della fase 1: velocità della sBWT con diversi algoritmi di suffix array.

Confronta, sugli stessi file e con la stessa chiave:
  - dc3        : DC3 in Python puro (implementazione di Sasso Giella)
  - divsufsort : rinomina segreta + pydivsufsort (libreria C), il nuovo default
  - doubling   : prefix doubling O(n log^2 n) del primo progetto (facoltativo, lento)

Misura solo la sBWT su un file intero (niente multiprocessing, bMTF, RLE, codifica),
divisa in tre parti: rinomina segreta, suffix array, costruzione della stringa BWT.
Ogni misura gira in un processo separato, così la memoria massima è quella del singolo
algoritmo. Per ogni file controlla che tutti gli algoritmi diano la stessa BWT (SHA-256).

Uso, dalla radice del progetto:
    .venv/bin/python tests/bench_sbwt.py                       # tutto il corpus
    .venv/bin/python tests/bench_sbwt.py --corpora canterbury --reps 1 --warmup 0
    .venv/bin/python tests/bench_sbwt.py --help
"""
import argparse
import csv
import datetime
import hashlib
import json
import os
import platform
import resource
import statistics
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
CORPUS_DIR = os.path.join(SRC, "TestFiles", "Input", "benchmark")
RESULTS_DIR = os.path.join(ROOT, "benchmarks", "results")
CORPORA = ["canterbury", "calgary", "large", "silesia"]
ALGOS = ["dc3", "divsufsort", "doubling"]
KEY = "chiave-benchmark-fase1"

RESULT_FIELDS = ["corpus", "file", "size_bytes", "symbols", "algo", "rep", "warmup", "status",
                 "rename_s", "sa_s", "bwt_join_s", "total_s", "maxrss_kb", "sha256_bwt", "error"]
SUMMARY_FIELDS = ["corpus", "file", "size_bytes", "symbols", "algo", "runs", "status",
                  "rename_s", "sa_s", "bwt_join_s", "total_s", "total_min_s", "total_max_s",
                  "mb_per_s", "maxrss_kb", "speedup_vs_dc3", "sa_speedup_vs_dc3", "bwt_identical"]


# --------------------------------------------------------------------------- worker

def worker(path, algo):
    """Esegue una singola misura e stampa una riga JSON su stdout."""
    sys.path.insert(0, SRC)
    import numpy as np
    from pydivsufsort import divsufsort
    import sbwt.suffix as suffix
    # la prima chiamata carica la libreria C (~15 ms una tantum): la si fa fuori misura
    divsufsort(np.asarray([2, 1, 2, 1], dtype=np.int32))

    # latin-1 trasforma ogni byte in un carattere: funziona anche sui file binari.
    # (La pipeline legge in UTF-8; qui interessa solo la velocità della sBWT.)
    with open(path, "rb") as f:
        txt = f.read().decode("latin-1") + "\003"

    t0 = time.perf_counter()
    if algo == "doubling":
        # il prefix doubling usa direttamente i float della chiave, non ha rinomina separata
        t1 = t0
        sa = suffix.buildSuffixArray(txt, len(txt), KEY)
    else:
        ranks, k = suffix.secretRanks(txt, KEY)
        t1 = time.perf_counter()
        if algo == "divsufsort":
            sa =divsufsort(np.asarray(ranks, dtype=np.int32)).tolist()
        else:  # dc3: stessa chiamata interna di buildSuffixArrayDC3, senza ripetere la rinomina
            sa = suffix.dc3(ranks, len(ranks), k)
    t2 = time.perf_counter()
    bwt = "".join(txt[i - 1] for i in sa)
    t3 = time.perf_counter()

    print(json.dumps({
        "symbols": len(set(txt)),
        "rename_s": t1 - t0, "sa_s": t2 - t1, "bwt_join_s": t3 - t2, "total_s": t3 - t0,
        "maxrss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "sha256_bwt": hashlib.sha256(bwt.encode("latin-1", "surrogatepass")).hexdigest(),
    }))


# --------------------------------------------------------------------------- driver

def run_one(path, algo, timeout):
    cmd = [sys.executable, os.path.abspath(__file__), "--worker", path, algo]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "error": f"oltre {timeout} s"}
    if p.returncode != 0:
        err = (p.stderr.strip().splitlines() or ["errore sconosciuto"])[-1]
        return {"status": "error", "error": err[:300]}
    out = json.loads(p.stdout.strip().splitlines()[-1])
    out["status"] = "ok"
    return out


def environment(args, files):
    def git(*a):
        try:
            return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        except OSError:
            return ""
    import importlib.metadata as md
    libs = {}
    for name in ("pydivsufsort", "numpy"):
        try:
            libs[name] = md.version(name)
        except md.PackageNotFoundError:
            libs[name] = ""
    cpu = ""
    try:
        with open("/proc/cpuinfo") as f:
            cpu = next(l.split(":", 1)[1].strip() for l in f if l.startswith("model name"))
    except (OSError, StopIteration):
        pass
    return {
        "data": datetime.datetime.now().isoformat(timespec="seconds"),
        "etichetta": args.label,
        "git_commit": git("rev-parse", "HEAD"),
        "git_modifiche_locali": git("status", "--porcelain"),
        "python": platform.python_version(),
        "librerie": libs,
        "sistema": platform.platform(),
        "cpu": cpu,
        "core_logici": os.cpu_count(),
        "chiave": KEY,
        "parametri": vars(args),
        "file": {c: [os.path.basename(p) for _, p in files if _ == c] for c in args.corpora.split(",")},
    }


def select_files(args):
    wanted = {f for f in args.files.split(",") if f}
    files = []
    for corpus in args.corpora.split(","):
        d = os.path.join(CORPUS_DIR, corpus)
        if not os.path.isdir(d):
            sys.exit(f"Corpus non trovato: {d}")
        for name in os.listdir(d):
            p = os.path.join(d, name)
            if os.path.isfile(p) and not name.startswith(".") and (not wanted or name in wanted):
                files.append((corpus, p))
    files.sort(key=lambda cp: os.path.getsize(cp[1]))
    return files


def summarize(rows):
    groups = {}
    for r in rows:
        if not r["warmup"]:
            groups.setdefault((r["corpus"], r["file"], r["algo"]), []).append(r)
    summary = []
    for (corpus, name, algo), rs in groups.items():
        ok = [r for r in rs if r["status"] == "ok"]
        s = {"corpus": corpus, "file": name, "size_bytes": rs[0]["size_bytes"], "algo": algo,
             "runs": len(ok), "status": "ok" if ok else rs[0]["status"]}
        if ok:
            med = lambda k: statistics.median(float(r[k]) for r in ok)
            s.update(symbols=ok[0]["symbols"],
                     rename_s=med("rename_s"), sa_s=med("sa_s"), bwt_join_s=med("bwt_join_s"),
                     total_s=med("total_s"),
                     total_min_s=min(float(r["total_s"]) for r in ok),
                     total_max_s=max(float(r["total_s"]) for r in ok),
                     maxrss_kb=int(med("maxrss_kb")))
            s["mb_per_s"] = s["size_bytes"] / 1e6 / s["total_s"] if s["total_s"] > 0 else ""
        summary.append(s)

    # speedup rispetto a DC3 e controllo che la BWT sia identica tra gli algoritmi
    by_file = {}
    for s in summary:
        by_file.setdefault((s["corpus"], s["file"]), {})[s["algo"]] = s
    hashes = {}
    for r in rows:
        if r["status"] == "ok":
            hashes.setdefault((r["corpus"], r["file"]), set()).add(r["sha256_bwt"])
    for key, algos in by_file.items():
        ref = algos.get("dc3")
        identical = len(hashes.get(key, ())) == 1 if hashes.get(key) else ""
        for s in algos.values():
            s["bwt_identical"] = identical
            if ref and ref["status"] == "ok" and s["status"] == "ok":
                s["speedup_vs_dc3"] = ref["total_s"] / s["total_s"]
                s["sa_speedup_vs_dc3"] = ref["sa_s"] / s["sa_s"] if s["sa_s"] > 0 else ""
    order = {c: i for i, c in enumerate(CORPORA)}
    summary.sort(key=lambda s: (order.get(s["corpus"], 99), s["size_bytes"], ALGOS.index(s["algo"])))
    return summary


def fmt(x, nd=3):
    return f"{x:.{nd}f}" if isinstance(x, float) else str(x)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--worker", nargs=2, metavar=("FILE", "ALGO"), help=argparse.SUPPRESS)
    ap.add_argument("--corpora", default=",".join(CORPORA), help="elenco separato da virgole")
    ap.add_argument("--files", default="", help="limita ai file con questi nomi (virgole)")
    ap.add_argument("--algos", default="dc3,divsufsort", help="tra: " + ",".join(ALGOS))
    ap.add_argument("--reps", type=int, default=3, help="ripetizioni misurate per file e algoritmo")
    ap.add_argument("--warmup", type=int, default=1, help="esecuzioni iniziali scartate")
    ap.add_argument("--dc3-max-mb", type=float, default=5.0,
                    help="salta DC3 sui file più grandi (lento e molta memoria); 0 = nessun limite")
    ap.add_argument("--doubling-max-kb", type=float, default=200.0,
                    help="salta il prefix doubling sui file più grandi; 0 = nessun limite")
    ap.add_argument("--timeout", type=int, default=1800, help="secondi per singola misura")
    ap.add_argument("--label", default="fase1_sbwt")
    ap.add_argument("--out", default="", help="cartella dei risultati (default benchmarks/results/<label>_<data>)")
    args = ap.parse_args()

    if args.worker:
        worker(*args.worker)
        return

    algos = [a for a in args.algos.split(",") if a]
    for a in algos:
        if a not in ALGOS:
            sys.exit(f"Algoritmo sconosciuto: {a}")
    files = select_files(args)
    if not files:
        sys.exit("Nessun file selezionato.")

    out = args.out or os.path.join(RESULTS_DIR, f"{args.label}_{datetime.datetime.now():%Y%m%d_%H%M}")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "environment.json"), "w") as f:
        json.dump(environment(args, files), f, indent=2, ensure_ascii=False)

    limits = {"dc3": args.dc3_max_mb * 1e6, "doubling": args.doubling_max_kb * 1e3}
    rows = []
    res_path = os.path.join(out, "results.csv")
    with open(res_path, "w", newline="") as fres:
        wr = csv.DictWriter(fres, fieldnames=RESULT_FIELDS)
        wr.writeheader()
        for corpus, path in files:
            size = os.path.getsize(path)
            name = os.path.basename(path)
            for algo in algos:
                lim = limits.get(algo, 0)
                if lim and size > lim:
                    row = {"corpus": corpus, "file": name, "size_bytes": size, "algo": algo,
                           "rep": 1, "warmup": 0, "status": "skipped", "error": "oltre il limite di dimensione"}
                    rows.append(row); wr.writerow(row); fres.flush()
                    print(f"{corpus:10s} {name:14s} {size:>10d}  {algo:10s} saltato (dimensione)")
                    continue
                for i in range(args.warmup + args.reps):
                    warm = i < args.warmup
                    r = run_one(path, algo, args.timeout)
                    row = {"corpus": corpus, "file": name, "size_bytes": size, "algo": algo,
                           "rep": i - args.warmup + 1 if not warm else 0, "warmup": int(warm), **r}
                    rows.append(row); wr.writerow(row); fres.flush()
                    tag = "riscaldamento" if warm else f"rep {row['rep']}"
                    info = f"{float(r['total_s']):8.3f} s  sa {float(r['sa_s']):8.3f} s" if r["status"] == "ok" else r["status"]
                    print(f"{corpus:10s} {name:14s} {size:>10d}  {algo:10s} {tag:14s} {info}", flush=True)
                    if r["status"] != "ok":
                        break  # inutile ripetere un errore o un timeout

    summary = summarize(rows)
    with open(os.path.join(out, "summary.csv"), "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS, extrasaction="ignore")
        wr.writeheader()
        for s in summary:
            wr.writerow({k: fmt(v, 4) if isinstance(v, float) else v for k, v in s.items()})

    print(f"\nRisultati in {out}")
    print(f"{'file':14s} {'byte':>10s} {'algo':10s} {'totale s':>9s} {'SA s':>9s} {'MB/s':>7s} {'RSS MB':>7s} {'x DC3':>7s} identica")
    for s in summary:
        if s["status"] != "ok":
            print(f"{s['file']:14s} {s['size_bytes']:>10d} {s['algo']:10s} {s['status']}")
            continue
        sp = s.get("speedup_vs_dc3", "")
        print(f"{s['file']:14s} {s['size_bytes']:>10d} {s['algo']:10s} {s['total_s']:9.3f} {s['sa_s']:9.3f} "
              f"{s['mb_per_s']:7.2f} {s['maxrss_kb'] / 1024:7.0f} {fmt(sp, 1):>7s} {s['bwt_identical']}")
    if any(s.get("bwt_identical") is False for s in summary):
        print("\nATTENZIONE: su almeno un file gli algoritmi danno BWT diverse.")
        sys.exit(1)


if __name__ == "__main__":
    main()
