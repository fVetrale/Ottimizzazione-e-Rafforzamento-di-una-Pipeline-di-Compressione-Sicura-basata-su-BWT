# Benchmark

Misure della fase 0 (punto di partenza), da ripetere con lo stesso protocollo alla fine del progetto.

## Dataset

I file di test sono in `src/TestFiles/Input/benchmark/<corpus>/` e **non sono versionati** (~80 MB).
Vengono da `MaterialeProgettoCompre/progetto/Analisi BZIP2 Grano/Analisi bzip2/progetto compressione/dataset/`:

| Corpus | Contenuto |
|---|---|
| `canterbury` | Canterbury corpus completo (11 file) |
| `calgary` | Calgary corpus completo (14 file) |
| `large` | E.coli, bible.txt, world192.txt |
| `silesia` | Solo i file fino a 11 MB: dickens, mr, ooffice, osdb, reymont.pdf, sao, x-ray, xml.tar |

`dataset_manifest.csv` contiene dimensione e SHA-256 di ogni file, così ognuno può controllare di avere gli stessi dati.
Attenzione: `alice29.txt` del corpus (152.089 byte) è diverso da quello già presente in `TestFiles/Input/` (152.062 byte).

## Esecuzione

Dalla radice del progetto, con l'ambiente attivo:

- benchmark completo: `.venv/bin/python benchmarks/run_baseline.py`
- prova veloce: `.venv/bin/python benchmarks/run_baseline.py --corpora canterbury --reps 1 --warmup 0`
- tutte le opzioni: `.venv/bin/python benchmarks/run_baseline.py --help`

Valori predefiniti: 1 esecuzione di riscaldamento scartata + 3 misurate per file, timeout di 30 minuti per fase,
Huffman su tutti i corpus, aritmetico e LZW solo su Canterbury, bzip2 -9 come riferimento.

Lo script lavora su una copia di `src/` (in `benchmarks/_work/`, cancellata alla fine), quindi non modifica i file del repo.
Conviene lanciarlo con il PC collegato alla corrente e senza altri programmi pesanti aperti.

## Risultati

Ogni esecuzione crea `results/<etichetta>_<data>/` con:

| File | Contenuto |
|---|---|
| `environment.json` | Commit git, versioni di Python e librerie, CPU, RAM, parametri |
| `results.csv` | Una riga per esecuzione (riscaldamento compreso, colonna `warmup`) |
| `phases.csv` | Tempi per fase stampati dal codice (sBWT, bMTF, RLE, PC e inverse) |
| `summary.csv` | Mediana delle esecuzioni misurate per file e codificatore |
| `logs/` | Log delle sole esecuzioni fallite |

## Come leggere le colonne

- `status`: `ok`, `unsupported` (il codice originale non legge il file, di solito perché non è UTF-8), `error`, `timeout`, `mismatch` (il file decompresso è diverso dall'originale).
- `compressed_bytes`: **tutto** ciò che serve per decomprimere, cioè il payload (`outputPC.txt`) più i metadati (codec, dizionari, `rfile`, `bfile`, `bFileMTF`).
  Per questo il rapporto è più basso di quello stampato da `tester.py`, che conta solo il payload.
- `*_wall_s`: tempo reale del processo, compreso l'avvio di Python e gli import (circa 0,1–0,2 s). È il valore usato per i MB/s, confrontabile con bzip2.
- `*_internal_s`: tempo della sola funzione di compressione o decompressione.
- `*_maxrss_kb`: memoria massima del processo più grande; `*_peak_total_kb`: picco della somma di tutti i processi (conta anche il multiprocessing).
- `bwt_mode`: `full` (file intero, output deterministico) o `block` (oltre ~512 KB). In modalità `block` entra il valore casuale `r`,
  quindi rapporto e hash cambiano leggermente da un'esecuzione all'altra.
- `sha256_bwt`, `sha256_mtf`: impronte dell'output di sBWT e bMTF, per verificare nelle fasi successive che l'output sia identico (solo in modalità `full`).

## Non ancora coperto

- Misura della dipendenza dalla chiave della bMTF (344 valori su 60.001): va definita come nell'esperimento preliminare.
- Profiling dettagliato dentro le singole fasi.
- Versioni MPI (`mpirun` non è installato).
