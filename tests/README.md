# Test

Test e misure del progetto. I file di input si leggono da `src/TestFiles/Input/` (in sola lettura);
nessuno script di questa cartella scrive in `src/TestFiles/Output/`.

| File | Contenuto |
|---|---|
| `conftest.py` | Aggiunge `src/` al path, così i moduli si importano come nella pipeline (`import sbwt.sbwt`) |
| `bench_sbwt.py` | Fase 1: velocità della sBWT con DC3 (Python) e divsufsort (C) |

## `bench_sbwt.py` — velocità della sBWT

Misura **solo la sBWT** su un file intero, senza multiprocessing, bMTF, RLE e codifica, e la divide in tre parti:

- `rename_s`: rinomina segreta dei caratteri nei loro ranghi (`suffix.secretRanks`);
- `sa_s`: costruzione del suffix array, l'unica parte che cambia tra gli algoritmi;
- `bwt_join_s`: costruzione della stringa BWT a partire dal suffix array.

Algoritmi confrontati (`--algos`):

| Nome | Cosa è |
|---|---|
| `dc3` | DC3 in Python puro, introdotto da Sasso Giella |
| `divsufsort` | `pydivsufsort` (libreria C) sui ranghi segreti, il default attuale |
| `doubling` | prefix doubling O(n log² n) del primo progetto; facoltativo, molto lento |

Ogni misura gira in un processo separato, così `maxrss_kb` è la memoria del singolo algoritmo.
Per ogni file lo script confronta lo SHA-256 della BWT di tutti gli algoritmi: se non coincide, lo segnala ed esce con errore.

I file vengono letti in `latin-1`, cioè un carattere per ogni byte, quindi la sBWT si misura anche sui file binari
(la pipeline completa oggi su quei file fallisce perché li legge in UTF-8; lo risolve la fase 3).

### Esecuzione

Dalla radice del progetto:

- completo: `.venv/bin/python tests/bench_sbwt.py`
- prova veloce: `.venv/bin/python tests/bench_sbwt.py --corpora canterbury --reps 1 --warmup 0`
- anche il prefix doubling: `--algos dc3,divsufsort,doubling`
- tutte le opzioni: `.venv/bin/python tests/bench_sbwt.py --help`

Valori predefiniti: stessi corpus della fase 0, 1 esecuzione di riscaldamento scartata + 3 misurate, mediana.
DC3 viene saltato sui file oltre 5 MB (`--dc3-max-mb`), perché richiede minuti e diversi GB di memoria;
il prefix doubling oltre 200 KB (`--doubling-max-kb`).

### Risultati

In `benchmarks/results/fase1_sbwt_<data>/`, accanto a quelli della fase 0:

| File | Contenuto |
|---|---|
| `environment.json` | Commit git, versioni di Python e librerie, CPU, chiave, parametri |
| `results.csv` | Una riga per esecuzione (riscaldamento compreso) |
| `summary.csv` | Mediana per file e algoritmo, MB/s, memoria, `speedup_vs_dc3`, `sa_speedup_vs_dc3`, `bwt_identical` |
