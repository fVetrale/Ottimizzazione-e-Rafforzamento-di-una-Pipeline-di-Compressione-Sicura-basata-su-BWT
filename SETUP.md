# Setup e correzioni per far funzionare il progetto

Questo file elenca le modifiche da fare perché il progetto si avvii e i test passino.
Le modifiche **non sono ancora applicate**: ognuno le fa sulla propria copia.

Verifica fatta il 15/11/2026 su Linux con **Python 3.14.4**.

---

## 1. Preparare l'ambiente Python

Su Debian/Ubuntu `python3 -m venv` può fallire con l'errore `ensurepip is not available`.
In quel caso le alternative sono due:

```bash
# Opzione A: installare il pacchetto mancante
sudo apt install python3.14-venv
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Opzione B: usare uv (non serve sudo)
uv venv .venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

> Conviene aggiungere `.venv/` al `.gitignore` (vedi punto 3).

---

## 2. Rinominare `src/compression.py` (bloccante)

**Problema.** Da Python 3.14 la libreria standard contiene un pacchetto chiamato `compression`.
Il file `src/compression.py` prende il suo posto, quindi `import bz2` (usato in `src/pc/pc.py` e in `src/tester_bzip.py`) fallisce:

```
ModuleNotFoundError: No module named 'compression._common'; 'compression' is not a package
```

Senza questa correzione **nessun test parte**.

**Correzione.**

```bash
cd src
git mv compression.py sbwt_compress.py
```

Poi, in `src/tester.py`, cambiare la riga 1:

```python
# prima
import compression
# dopo
import sbwt_compress as compression
```

Controllare che non ci siano altri `import compression` rimasti:

```bash
grep -rnE '^\s*(import|from)\s+compression\b' --include='*.py' src
```

---

## 3. Correggere il `.gitignore`

**Problema.** La riga `_pycache_` usa un solo trattino basso per lato e non corrisponde a niente, quindi i file `.pyc` finirebbero nei commit.

**Correzione.** Il `.gitignore` deve essere così:

```
__pycache__/
*.pyc
.venv/

*.zip
```

Se dei `.pyc` sono già stati committati, vanno tolti dall'indice:

```bash
git rm -r --cached $(git ls-files | grep -E '__pycache__|\.pyc$')
```

> `*.zip` resta nel file: `test_300.zip` (~102 MB) supera il limite di 100 MB di GitHub. Gli zip di test vanno condivisi a parte.

---

## 4. Correggere un avviso in `src/rle/rle.py` (consigliato)

**Problema.** Alla riga 129 c'è `"-\d+$"` in una stringa normale. Su Python 3.14 produce un avviso:

```
SyntaxWarning: "\d" is an invalid escape sequence
```

Oggi funziona ancora, ma nelle prossime versioni di Python diventerà un errore.

**Correzione.**

```python
# prima
x = re.search("-\d+$", char)
# dopo
x = re.search(r"-\d+$", char)
```

---

## 5. Verificare che funzioni

I test vanno lanciati **dalla cartella `src/`**, perché i percorsi `TestFiles/...` sono relativi:

```bash
cd src
python tester.py alice29.txt chiave 0   # 0 = Huffman
python tester.py alice29.txt chiave 1   # 1 = Arithmetic Coding
python tester.py alice29.txt chiave 2   # 2 = LZW
python tester_bzip.py alice29.txt       # confronto con bzip2
```

Ogni test deve stampare `decompression was successful`.

> Attenzione: i test sovrascrivono i file in `src/TestFiles/Output/`, compreso `bfile.txt` che è versionato. Prima di fare un commit controllare con `git status`.

### Risultati attesi (dopo i punti 1–4)

| File | Modalità | Rapporto | Compressione | Esito |
|---|---|---|---|---|
| `grammar.lsp` | Huffman | 1,93 | 48,1% | ✅ |
| `grammar.lsp` | Arithmetic | 1,29 | 22,4% | ✅ |
| `grammar.lsp` | LZW | 1,73 | 42,1% | ✅ |
| `fields.c` | Huffman | 2,22 | 55,0% | ✅ |
| `fields.c` | Arithmetic | 1,88 | 46,9% | ✅ |
| `fields.c` | LZW | 2,02 | 50,5% | ✅ |
| `alice29.txt` | Huffman | 2,01 | 50,3% | ✅ |
| `alice29.txt` | Arithmetic | 2,04 | 51,0% | ✅ |
| `alice29.txt` | LZW | 1,92 | 47,9% | ✅ |
| `alice29.txt` | bzip2 | 3,52 | 71,6% | ✅ |

---

## 6. Versioni MPI (non ancora verificate)

`tester_mpi.py` e `test_bash.sh` richiedono `mpirun`, che non è incluso in `mpi4py`:

```bash
sudo apt install openmpi-bin libopenmpi-dev
cd src
mpirun --oversubscribe -np 4 python tester_mpi.py alice29.txt chiave 0
```

Queste versioni non sono ancora state provate: se qualcuno le fa girare, aggiorni questa sezione.

---

## Riepilogo

| # | Modifica | File | Priorità |
|---|---|---|---|
| 1 | Creare l'ambiente Python e installare le dipendenze | — | Necessaria |
| 2 | Rinominare `compression.py` → `sbwt_compress.py` e aggiornare l'import | `src/compression.py`, `src/tester.py` | **Bloccante** |
| 3 | `_pycache_` → `__pycache__/`, aggiungere `*.pyc` e `.venv/` | `.gitignore` | Alta |
| 4 | `"-\d+$"` → `r"-\d+$"` | `src/rle/rle.py:129` | Bassa |
| 5 | Lanciare i test da `src/` | — | Verifica |
| 6 | Installare OpenMPI per le versioni MPI | — | Facoltativa |
