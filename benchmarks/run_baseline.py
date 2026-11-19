#!/usr/bin/env python3
"""Benchmark della fase 0: misure di riferimento sulla pipeline sBWT originale e su bzip2.

Lanciare dalla radice del progetto con il Python della .venv:
    .venv/bin/python benchmarks/run_baseline.py                 # tutto
    .venv/bin/python benchmarks/run_baseline.py --corpora canterbury --reps 1 --warmup 0

Cosa fa:
  * crea una copia di lavoro di src/ in benchmarks/_work/ (i test sovrascrivono i file
    in TestFiles/Output, compreso bfile.txt che è versionato: così il repo resta pulito);
  * per ogni file, codificatore e ripetizione esegue compressione e decompressione in
    due processi separati e misura tempo, memoria, dimensione e round-trip;
  * raccoglie i tempi per fase stampati dal codice originale ("... -> elapsed time of X");
  * fa le stesse misure con bzip2 -9 come riferimento;
  * scrive i CSV in benchmarks/results/<etichetta>_<data>/ man mano (un'interruzione
    non perde i risultati già raccolti).

Dalla fase 3 misura la pipeline a byte: la compressione scrive un solo file
(TestFiles/Output/compressed.sbwt), quindi non ci sono più file di metadati né
hash degli stadi intermedi (le colonne restano, vuote, per confrontare i CSV con
la baseline). Se dopo la compressione in Output compare un altro file, la prova
viene segnata come errore. Solo il modo 0 (Huffman) è supportato.

Solo Linux (usa /proc e os.wait4).
"""
import argparse
import csv
import json
import os
import platform
import re
import shutil
import signal
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
BENCH = ROOT / "benchmarks"
INPUT_REL = "benchmark"                      # sottocartella di src/TestFiles/Input
DRIVER = BENCH / "_driver.py"
CORPORA = ["canterbury", "calgary", "large", "silesia"]
CODERS = {0: "sbwt-huffman", 1: "sbwt-arithmetic", 2: "sbwt-lzw"}

# Fase 3: un solo file contiene tutto ciò che serve alla decompressione.
PAYLOAD = "compressed.sbwt"
# File che possono trovarsi in Output senza essere prodotti dalla compressione.
OUTPUT_ALLOWED = {"README.md", PAYLOAD}

PHASE_RE = re.compile(r"^\s*([0-9.]+(?:e-?\d+)?)\s+->\s+elapsed time of\s+(.+?)\s*$")
BWT_BLOCK_SIZE = 900 * 1024   # come pipeline.BWT_BLOCK_SIZE

RESULT_FIELDS = [
    "label", "corpus", "file", "size_bytes", "coder", "rep", "warmup", "status", "error",
    "bwt_mode",
    "comp_wall_s", "comp_internal_s", "comp_maxrss_kb", "comp_peak_total_kb",
    "decomp_wall_s", "decomp_internal_s", "decomp_maxrss_kb", "decomp_peak_total_kb",
    "compressed_bytes", "payload_bytes", "metadata_bytes",
    "ratio", "bits_per_byte", "comp_MBps", "decomp_MBps",
    "sha256_bwt", "sha256_mtf",
]
PHASE_FIELDS = ["label", "corpus", "file", "coder", "rep", "warmup", "step", "phase", "seconds"]
SUMMARY_FIELDS = [
    "corpus", "file", "size_bytes", "coder", "runs", "status", "bwt_mode",
    "comp_wall_s", "decomp_wall_s", "comp_internal_s", "decomp_internal_s",
    "comp_MBps", "decomp_MBps", "comp_peak_total_kb", "decomp_peak_total_kb",
    "compressed_bytes", "ratio", "bits_per_byte",
]


# --------------------------------------------------------------------------- misura

def _group_rss_kb(pgid):
    """Somma della RSS (KB) di tutti i processi del gruppo pgid, letta da /proc."""
    page_kb = os.sysconf("SC_PAGE_SIZE") // 1024
    total = 0
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat", "rb") as f:
                data = f.read().decode(errors="replace")
        except OSError:
            continue
        fields = data[data.rfind(")") + 2:].split()
        # fields[0]=state, [2]=pgrp, [21]=rss (pagine)
        if len(fields) > 21 and int(fields[2]) == pgid:
            total += int(fields[21]) * page_kb
    return total


def run_measured(cmd, cwd, timeout, stdout_path):
    """Esegue cmd e misura: tempo reale, RSS massima del processo più grande
    (esatta, da wait4) e picco della RSS sommata su tutti i processi (campionata)."""
    with open(stdout_path, "wb") as out:
        t0 = time.perf_counter()
        proc = subprocess.Popen(cmd, cwd=cwd, stdout=out, stderr=subprocess.STDOUT,
                                start_new_session=True)
        peak_total = 0
        timed_out = False
        next_sample = 0.0
        while True:
            pid, status, ru = os.wait4(proc.pid, os.WNOHANG)
            if pid != 0:
                break
            now = time.perf_counter() - t0
            if now > timeout:
                timed_out = True
                os.killpg(proc.pid, signal.SIGKILL)
                pid, status, ru = os.wait4(proc.pid, 0)
                break
            if now >= next_sample:
                peak_total = max(peak_total, _group_rss_kb(proc.pid))
                next_sample = now + 0.1
            time.sleep(0.01)
        wall = time.perf_counter() - t0
        proc.returncode = os.waitstatus_to_exitcode(status)
    # eventuali processi figli rimasti (pool non chiusi)
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    return {
        "wall_s": wall,
        "returncode": proc.returncode,
        "timed_out": timed_out,
        "maxrss_kb": ru.ru_maxrss,                 # KB su Linux
        "peak_total_kb": max(peak_total, ru.ru_maxrss),
    }


def parse_log(path):
    phases, internal, error = {}, None, ""
    text = Path(path).read_text(errors="replace")
    for line in text.splitlines():
        m = PHASE_RE.match(line)
        if m:
            phases[m.group(2)] = float(m.group(1))
        elif line.startswith("BENCH_JSON "):
            internal = json.loads(line[len("BENCH_JSON "):])["internal_s"]
    for line in reversed(text.splitlines()):
        if re.search(r"(Error|Exception)\b", line):
            error = line.strip()[:200]
            break
    return phases, internal, error



def files_equal(a, b):
    if os.path.getsize(a) != os.path.getsize(b):
        return False
    with open(a, "rb") as fa, open(b, "rb") as fb:
        while True:
            x, y = fa.read(1 << 20), fb.read(1 << 20)
            if x != y:
                return False
            if not x:
                return True


def bwt_mode(size):
    """Replica la scelta di pipeline.py: un solo blocco o più blocchi.

    Dalla fase 3 i blocchi hanno dimensione fissa (BWT_BLOCK_SIZE) e l'ultimo
    può essere più corto (divisione per eccesso).
    """
    return "block" if -(-size // BWT_BLOCK_SIZE) > 1 else "full"


# --------------------------------------------------------------------------- esecuzioni

def prepare_workdir():
    """Copia di lavoro di src/; Input è un link simbolico all'originale (sola lettura)."""
    work = BENCH / "_work"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    wsrc = work / "src"
    shutil.copytree(SRC, wsrc, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "Input"))
    (wsrc / "TestFiles" / "Input").symlink_to(SRC / "TestFiles" / "Input", target_is_directory=True)
    return work, wsrc


def clean_output(wsrc):
    out = wsrc / "TestFiles" / "Output"
    for p in out.iterdir():
        if p.name != "README.md":
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()


def empty_row(label, corpus, path, coder, rep, warmup):
    row = {k: "" for k in RESULT_FIELDS}
    row.update(label=label, corpus=corpus, file=path.name, size_bytes=path.stat().st_size,
               coder=coder, rep=rep, warmup=int(warmup))
    return row


def fill_rates(row, size, compressed):
    row["compressed_bytes"] = compressed
    row["ratio"] = round(size / compressed, 4) if compressed else ""
    row["bits_per_byte"] = round(8 * compressed / size, 4) if size else ""
    for step in ("comp", "decomp"):
        w = row[f"{step}_wall_s"]
        row[f"{step}_MBps"] = round(size / 1e6 / w, 4) if w else ""


def run_sbwt(args, wsrc, logs, label, corpus, path, mode, rep, warmup):
    coder = CODERS[mode]
    row = empty_row(label, corpus, path, coder, rep, warmup)
    row["bwt_mode"] = bwt_mode(path.stat().st_size)
    rel = f"{INPUT_REL}/{corpus}/{path.name}"
    out_dir = wsrc / "TestFiles" / "Output"
    phase_rows = []
    clean_output(wsrc)
    tag = f"{corpus}_{path.name}_{coder}_r{rep}"
    status, error = "ok", ""

    for step in ("compress", "decompress"):
        log = logs / f"{tag}_{step}.log"
        m = run_measured([sys.executable, str(DRIVER), step, str(wsrc), rel, args.key, str(mode)],
                         wsrc, args.timeout, log)
        phases, internal, err = parse_log(log)
        p = "comp" if step == "compress" else "decomp"
        row[f"{p}_wall_s"] = round(m["wall_s"], 4)
        row[f"{p}_internal_s"] = round(internal, 4) if internal is not None else ""
        row[f"{p}_maxrss_kb"] = m["maxrss_kb"]
        row[f"{p}_peak_total_kb"] = m["peak_total_kb"]
        for name, sec in phases.items():
            phase_rows.append(dict(label=label, corpus=corpus, file=path.name, coder=coder,
                                   rep=rep, warmup=int(warmup), step=step, phase=name, seconds=sec))
        if m["timed_out"]:
            status, error = "timeout", f"{step}: oltre {args.timeout}s"
        elif m["returncode"] != 0:
            status = "unsupported" if "UnicodeDecodeError" in err else "error"
            error = f"{step}: {err or 'exit ' + str(m['returncode'])}"
        if status != "ok":
            break
        if step == "compress":
            extra = sorted(p.name for p in out_dir.iterdir() if p.name not in OUTPUT_ALLOWED)
            if extra or not (out_dir / PAYLOAD).exists():
                status = "error"
                error = f"compress: file inattesi in Output {extra}" if extra else "compress: manca " + PAYLOAD
                break
            row["payload_bytes"], row["metadata_bytes"] = (out_dir / PAYLOAD).stat().st_size, 0

    if status == "ok":
        if not files_equal(path, out_dir / "decompressed.txt"):
            status, error = "mismatch", "il file decompresso è diverso dall'originale"
        fill_rates(row, path.stat().st_size, row["payload_bytes"] + row["metadata_bytes"])
    else:
        fill_rates(row, path.stat().st_size, 0)
    row["status"], row["error"] = status, error

    if status == "ok" and not args.keep_logs:
        for step in ("compress", "decompress"):
            (logs / f"{tag}_{step}.log").unlink(missing_ok=True)
    return row, phase_rows


def run_bzip2(args, work, logs, label, corpus, path, rep, warmup):
    row = empty_row(label, corpus, path, "bzip2-9", rep, warmup)
    tmp = work / "bz"
    tmp.mkdir(exist_ok=True)
    comp, restored = tmp / "out.bz2", tmp / "restored"
    mc = run_measured(["bzip2", "-9", "-k", "-c", str(path)], tmp, args.timeout, comp)
    md = run_measured(["bzip2", "-d", "-c", str(comp)], tmp, args.timeout, restored)
    for p, m in (("comp", mc), ("decomp", md)):
        row[f"{p}_wall_s"] = round(m["wall_s"], 4)
        row[f"{p}_maxrss_kb"] = m["maxrss_kb"]
        row[f"{p}_peak_total_kb"] = m["peak_total_kb"]
    ok = mc["returncode"] == 0 and md["returncode"] == 0 and files_equal(path, restored)
    row["status"] = "ok" if ok else "error"
    size_c = comp.stat().st_size
    row["payload_bytes"], row["metadata_bytes"] = size_c, 0
    fill_rates(row, path.stat().st_size, size_c)
    return row


# --------------------------------------------------------------------------- output

class CsvAppender:
    def __init__(self, path, fields):
        self.path, self.fields = path, fields
        with open(path, "w", newline="") as f:
            csv.DictWriter(f, fields).writeheader()

    def write(self, rows):
        with open(self.path, "a", newline="") as f:
            csv.DictWriter(f, self.fields).writerows(rows)


def write_environment(out, args, corpora_files):
    def cmd(c):
        try:
            return subprocess.run(c, capture_output=True, text=True, cwd=ROOT).stdout.strip()
        except OSError:
            return ""
    cpu = ""
    try:
        for line in open("/proc/cpuinfo"):
            if line.startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    mem_kb = 0
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemTotal"):
                mem_kb = int(line.split()[1])
    except OSError:
        pass
    libs = {}
    for name in ("numpy", "dahuffman", "mpi4py"):
        try:
            from importlib.metadata import version
            libs[name] = version(name)
        except Exception:
            libs[name] = "non installato"
    env = {
        "data": datetime.now().isoformat(timespec="seconds"),
        "etichetta": args.label,
        "git_commit": cmd(["git", "rev-parse", "HEAD"]),
        "git_describe": cmd(["git", "describe", "--tags", "--always", "--dirty"]),
        "git_modifiche_locali": cmd(["git", "status", "--short", "--", "src"]) or "nessuna",
        "python": sys.version.split()[0],
        "python_exe": sys.executable,
        "librerie": libs,
        "bzip2": cmd(["bzip2", "--version"]).splitlines()[0] if cmd(["bzip2", "--version"]) else "",
        "sistema": platform.platform(),
        "cpu": cpu,
        "core_logici": os.cpu_count(),
        "ram_gb": round(mem_kb / 1024 / 1024, 1),
        "parametri": {k: v for k, v in vars(args).items() if k != "key"},
        "file": {c: [p.name for p in fs] for c, fs in corpora_files.items()},
    }
    (out / "environment.json").write_text(json.dumps(env, indent=2, ensure_ascii=False))


def write_summary(out, rows):
    groups = {}
    for r in rows:
        if r["warmup"]:
            continue
        groups.setdefault((r["corpus"], r["file"], r["coder"]), []).append(r)
    order = {"ok": 0, "mismatch": 1, "unsupported": 2, "timeout": 3, "error": 4}
    result = []
    for (corpus, file, coder), rs in groups.items():
        statuses = {r["status"] for r in rs}
        status = max(statuses, key=lambda s: order.get(s, 9))
        ok = [r for r in rs if r["status"] == "ok"]

        def med(key):
            vals = [r[key] for r in ok if r[key] != ""]
            return round(statistics.median(vals), 4) if vals else ""

        def mx(key):
            vals = [r[key] for r in ok if r[key] != ""]
            return max(vals) if vals else ""

        result.append({
            "corpus": corpus, "file": file, "size_bytes": rs[0]["size_bytes"], "coder": coder,
            "runs": len(rs), "status": status, "bwt_mode": rs[0]["bwt_mode"],
            "comp_wall_s": med("comp_wall_s"), "decomp_wall_s": med("decomp_wall_s"),
            "comp_internal_s": med("comp_internal_s"), "decomp_internal_s": med("decomp_internal_s"),
            "comp_MBps": med("comp_MBps"), "decomp_MBps": med("decomp_MBps"),
            "comp_peak_total_kb": mx("comp_peak_total_kb"),
            "decomp_peak_total_kb": mx("decomp_peak_total_kb"),
            "compressed_bytes": med("compressed_bytes"), "ratio": med("ratio"),
            "bits_per_byte": med("bits_per_byte"),
        })
    with open(out / "summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, SUMMARY_FIELDS)
        w.writeheader()
        w.writerows(result)
    return result


# --------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpora", default=",".join(CORPORA), help="elenco separato da virgole")
    ap.add_argument("--files", default="", help="limita ai file con questi nomi (virgole)")
    ap.add_argument("--modes", default="0", help="modi sBWT su tutti i corpus (0=Huffman, 1=Arith, 2=LZW)")
    ap.add_argument("--extra-modes", default="",
                    help="modi aggiuntivi solo su --extra-corpora (dalla fase 3 esiste solo il modo 0)")
    ap.add_argument("--extra-corpora", default="canterbury")
    ap.add_argument("--reps", type=int, default=3, help="ripetizioni misurate per file")
    ap.add_argument("--warmup", type=int, default=1, help="esecuzioni iniziali scartate per file")
    ap.add_argument("--timeout", type=int, default=1800, help="secondi massimi per fase")
    ap.add_argument("--key", default="chiave-benchmark-fase0")
    ap.add_argument("--label", default="baseline")
    ap.add_argument("--no-bzip2", action="store_true")
    ap.add_argument("--keep-logs", action="store_true", help="tiene i log anche delle esecuzioni riuscite")
    ap.add_argument("--out", default="", help="cartella dei risultati (default benchmarks/results/<label>_<data>)")
    args = ap.parse_args()

    corpora = [c for c in args.corpora.split(",") if c]
    only = {f for f in args.files.split(",") if f}
    modes = [int(m) for m in args.modes.split(",") if m]
    extra_modes = [int(m) for m in args.extra_modes.split(",") if m]
    extra_corpora = {c for c in args.extra_corpora.split(",") if c}

    input_root = SRC / "TestFiles" / "Input" / INPUT_REL
    corpora_files = {}
    for c in corpora:
        d = input_root / c
        if not d.is_dir():
            sys.exit(f"Corpus mancante: {d}")
        fs = sorted(p for p in d.iterdir() if p.is_file() and not p.name.startswith("."))
        if only:
            fs = [p for p in fs if p.name in only]
        if fs:
            corpora_files[c] = sorted(fs, key=lambda p: p.stat().st_size)

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    out = Path(args.out) if args.out else BENCH / "results" / f"{args.label}_{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    logs = out / "logs"
    logs.mkdir(exist_ok=True)
    write_environment(out, args, corpora_files)
    res_csv = CsvAppender(out / "results.csv", RESULT_FIELDS)
    ph_csv = CsvAppender(out / "phases.csv", PHASE_FIELDS)

    work, wsrc = prepare_workdir()
    all_rows = []
    total_runs = args.warmup + args.reps
    try:
        for corpus, files in corpora_files.items():
            corpus_modes = modes + ([m for m in extra_modes if m not in modes] if corpus in extra_corpora else [])
            for path in files:
                for mode in corpus_modes:
                    for i in range(total_runs):
                        warm = i < args.warmup
                        rep = i - args.warmup + 1 if not warm else 0
                        row, phases = run_sbwt(args, wsrc, logs, args.label, corpus, path, mode, rep, warm)
                        if warm and row["status"] in ("unsupported", "error", "timeout"):
                            # un fallimento non è una misura di riscaldamento: va nel riepilogo
                            row["warmup"], row["rep"] = 0, 1
                        res_csv.write([row])
                        ph_csv.write(phases)
                        all_rows.append(row)
                        print(f"[{corpus}/{path.name}] {CODERS[mode]} {'warmup' if warm else 'rep ' + str(rep)}: "
                              f"{row['status']}  comp {row['comp_wall_s']}s  decomp {row['decomp_wall_s']}s  "
                              f"ratio {row['ratio']}  {row['error']}", flush=True)
                        if row["status"] in ("unsupported", "error", "timeout"):
                            break      # inutile ripetere: fallirebbe di nuovo
                if not args.no_bzip2:
                    for i in range(total_runs):
                        warm = i < args.warmup
                        rep = i - args.warmup + 1 if not warm else 0
                        row = run_bzip2(args, work, logs, args.label, corpus, path, rep, warm)
                        res_csv.write([row])
                        all_rows.append(row)
                    print(f"[{corpus}/{path.name}] bzip2-9: {row['status']}  ratio {row['ratio']}", flush=True)
    except KeyboardInterrupt:
        print("\nInterrotto: salvo il riepilogo con i risultati raccolti finora.")
    finally:
        write_summary(out, all_rows)
        shutil.rmtree(work, ignore_errors=True)
        if not any(logs.iterdir()):
            logs.rmdir()
    print(f"\nRisultati in {out}")


if __name__ == "__main__":
    main()
