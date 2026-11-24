# Fase 4, stadio 2: BWT inversa con pointer jumping

Data: 24/11/2026. Benchmark con gli stessi parametri della Fase 4.1: Canterbury e
Calgary (25 file), 3 ripetizioni più 1 di riscaldamento. Risultati in
`benchmarks/results/fase_4_2_pointer_jumping`, confrontati con `fase_4_1_huffman`.

## In breve

L'inversa BWT (`ibwt_bytes` in `src/sbwt/sbwt.py`) ora segue la mappa LF con il
**pointer jumping** invece che con un ciclo Python da n passi. Sul benchmark lo stadio
I-BWT passa da **0,98 s a 0,23 s** (−77%) e il lavoro interno della decompressione da
**3,27 s a 2,58 s** (−21%). La memoria usata dall'inversa cala invece di crescere: su un
blocco da 900 KiB il picco scende da 52 MB a 14 MB. L'output è identico byte per byte,
anche su blocchi corrotti.

## Punto di partenza

La versione di Sebastiano (`docs/sebastiano/fase4-stadio2-bwt-inversa.md`, commit
`e5e5e69`) aveva già reso vettoriale la costruzione della mappa LF con NumPy (tabella da
256 voci, `argsort` stabile, inversione della permutazione). Il ciclo finale però era
rimasto in Python:

```python
lf_list = lf.tolist()
for position in range(n - 1, -1, -1):
    result[position] = last_column[row]
    row = lf_list[row]
```

Il collo di bottiglia restava dunque in quei 900.000 giri di interprete per blocco.
In più `lf.tolist()` crea 900.000 oggetti interi Python (circa 36 byte l'uno), e per
questo quella versione usava **più** memoria dell'originale.

## La tecnica

Le righe da visitare formano una catena: `p, LF(p), LF²(p), …`, dove `p` è l'indice
primario. La riga visitata al passo i dà il byte in posizione n−1−i del testo. Ogni passo
dipende dal precedente, quindi seguire la catena un anello alla volta richiede n passi.

Il pointer jumping costruisce salti sempre più lunghi: `LF²` = `LF[LF]`, `LF⁴` =
`LF²[LF²]`, e così via. Ognuno si ottiene con una sola operazione NumPy su tutto
l'array. Se si conoscono le righe dei passi 0…m−1, applicando a tutte `LFᵐ` si ottengono
in un colpo quelle dei passi m…2m−1:

| Giro | Righe note | Operazione |
|---|---|---|
| inizio | `[p]` | — |
| 1 | 2 | `LF` applicata a 1 riga |
| 2 | 4 | `LF²` applicata a 2 righe |
| 3 | 8 | `LF⁴` applicata a 4 righe |
| … | … | … |

Bastano circa log₂(n) giri: per un blocco da 900 KiB sono 20 operazioni vettoriali invece
di 900.000 passi Python. Il lavoro complessivo cresce un po' (n·log n invece di n), ma si
svolge tutto in C dentro NumPy.

## Cosa è cambiato nel codice

Solo `ibwt_bytes`. Restano invariati i controlli in ingresso, il calcolo dell'ordine
segreto e la costruzione vettoriale di LF fatta da Sebastiano.

- Gli indici usano `int32` quando n < 2³¹, altrimenti `int64` (prima `intp`, cioè
  sempre 64 bit): metà memoria e accessi più veloci.
- Gli array intermedi (`mapped`, `P`) vengono liberati appena calcolata LF.
- `lf.tolist()` e il ciclo sono sostituiti da:

```python
rows = np.empty(n, dtype=index_type)
rows[0] = primary_index
jump = lf
known = 1
while known < n:
    step = min(known, n - known)
    rows[known:known + step] = jump[rows[:step]]
    known += step
    if known < n:
        jump = jump[jump]          # LF^m -> LF^2m
return symbols[rows[::-1]].tobytes()
```

Non cambiano `bwt_bytes`, `pipeline.py` né il formato del contenitore: i file `.sbwt`
già creati si decomprimono come prima.

## Garanzie mantenute

- **Stesso output.** Le righe visitate sono esattamente quelle del ciclo originale, nello
  stesso ordine. Vale anche per gli input periodici (`abab…`), dove LF ha più cicli.
- **Dati corrotti o manomessi.** LF è sempre una permutazione di 0…n−1, qualunque sia il
  contenuto del blocco, quindi ogni accesso resta dentro l'array. NumPy controlla
  comunque i limiti: un indice errato darebbe un errore, non una lettura arbitraria.
- **Terminazione.** Il numero di giri dipende solo da n (circa log₂ n): non esistono
  input che allungano o bloccano il ciclo.
- **Overflow.** Il tipo degli indici è scelto in base a n.

## Sicurezza

- **Chiave e ordine segreto.** L'ordine segreto si calcola dalla chiave come prima, e
  prima del pointer jumping, che lavora solo su LF. La chiave non viene usata, salvata o
  esposta in modo diverso, e il risultato è lo stesso, quindi chi non ha la chiave non
  ottiene nulla in più. La sBWT in compressione non è toccata.
- **Esaurimento delle risorse.** Il tempo dipende solo dalla lunghezza del blocco, non
  dal contenuto. La memoria per blocco è circa 3,7 volte più bassa della versione
  precedente, quindi un file costruito apposta ottiene meno di prima. I limiti già
  presenti sul contenitore (`original_size`, `max_output_size`) restano.
- **Canali laterali.** Gli accessi in memoria dipendono dai dati, come nel ciclo
  originale: l'inversa BWT non era a tempo costante prima e non lo è ora. Nessun rischio
  nuovo.

## Risultati

### Singolo blocco (prefissi di `bible.txt`, migliore di più ripetizioni)

| Blocco | Originale | Sebastiano | Pointer jumping |
|---|---|---|---|
| 4 KB, tempo | 0,45 ms | 0,21 ms | **0,13 ms** |
| 64 KB, tempo | 5,7 ms | 3,0 ms | **1,8 ms** |
| 900 KiB, tempo | 211 ms | 165 ms | **32 ms** |
| 64 KB, picco memoria | 2,4 MB | 3,7 MB | **1,1 MB** |
| 900 KiB, picco memoria | 36,5 MB | 51,9 MB | **14,1 MB** |

Il picco è misurato con `tracemalloc`, che conta anche gli array NumPy. Il pointer
jumping vince a tutte le dimensioni, anche sui blocchi piccoli.

### Decompressione completa (un processo, mediana di 3 esecuzioni)

| File | Versione | Totale | Stadio I-BWT | Memoria del processo |
|---|---|---|---|---|
| bible.txt (4,0 MB) | Originale | 2,26 s | 0,99 s | 128 MB |
| | Sebastiano | 2,03 s | 0,77 s | 148 MB |
| | **Pointer jumping** | **1,43 s** | **0,17 s** | **112 MB** |
| E.coli (4,6 MB) | Originale | 3,30 s | 1,31 s | 153 MB |
| | Sebastiano | 3,06 s | 1,06 s | 168 MB |
| | **Pointer jumping** | **2,18 s** | **0,17 s** | **136 MB** |

Sopra i 4 MB la pipeline decomprime i blocchi in processi paralleli. Il picco totale è
quindi circa "picco per blocco × processi": con 12 processi, circa 620 MB per la
versione precedente contro 170 MB ora (stima dal picco per blocco).

### Benchmark Canterbury + Calgary (somma delle mediane sui 25 file)

| Stadio di decompressione | Fase 4.1 | Fase 4.2 |
|---|---|---|
| I-PC (Huffman) | 0,88 s | 0,92 s |
| I-RLE | 0,43 s | 0,43 s |
| I-BMTF | 0,96 s | 0,96 s |
| **I-BWT** | **0,98 s** | **0,23 s** |
| **Lavoro interno totale** | **3,27 s** | **2,58 s** |

- Tutte le 25 esecuzioni sono `ok`. La dimensione compressa non cambia, a parte poche
  centinaia di byte dovute al nonce casuale.
- Il picco di memoria della decompressione, sommato sui file, scende del 10,9%. Sui file
  più grandi il calo è del 20–25% (book1: 76,7 → 58,3 MB; kennedy.xls: 83,0 → 62,3 MB).
- Il tempo *wall* totale scende solo del 4,5% (4,94 → 4,72 s), perché in questa
  esecuzione l'avvio di ogni processo è stato più lento: circa 86 ms contro 67 ms.
  Lo si vede anche dove il codice non è cambiato: la compressione (+12,6%) e bzip2
  (+17%). Per valutare la modifica conta il lavoro interno, che esclude l'avvio.

Dopo questa modifica l'inversa BWT è lo stadio più leggero della decompressione. Il più
pesante ora è I-BMTF (0,96 s), che è l'oggetto dello stadio 3.

## Test aggiunti

In `tests/test_sbwt_bytes.py`, con una copia dell'inversa originale come oracolo
(`_reference_ibwt`):

- `test_matches_reference_on_bwt_output`: sugli output reali di `bwt_bytes` (testo
  casuale, alfabeto DNA, input periodici, byte tutti uguali, da 2 a 4.097 byte) il
  risultato è uguale al testo di partenza e all'oracolo.
- `test_matches_reference_on_arbitrary_input`: 200 blocchi casuali, come fossero
  corrotti, con indice primario e chiave casuali: stessa lunghezza e stesso output
  dell'oracolo, senza eccezioni.

La suite completa passa: 89 test. Per verificare che i test servano davvero, quattro
errori sono stati iniettati in una copia del codice (argsort non stabile, output non
invertito, raddoppio mancante, passo sbagliato a fine catena): tutti vengono rilevati.
