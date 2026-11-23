# Fase 3: punto 4 e benchmark con Numba

Data: 23/11/2026. Tutti i benchmark usano gli stessi parametri: Canterbury e Calgary,
3 ripetizioni più 1 di riscaldamento.

## In breve

Il punto 4 è chiuso e non cambia le prestazioni. Installare Numba aveva reso ogni
esecuzione **circa 3,3 volte più lenta**, perché la MTF veniva ricompilata a ogni avvio.
Dopo la correzione i tempi sono tornati ai livelli precedenti. Numba ora si attiva solo
sui file grandi, dove dà un vantaggio moderato.

## Cosa è cambiato nel formato

- Tutti i numeri del file, compresa la tabella Huffman, sono in big endian.
- L'header ha un byte `coder` che identifica il codificatore (1 = Huffman). Un valore
  sconosciuto viene rifiutato.
- La versione del formato passa da 1 a 2, quindi i vecchi file `.sbwt` vengono
  rifiutati con un errore chiaro e vanno rigenerati.
- L'header resta di 54 byte.

## Risultati sui 17 file di testo

| Tempo totale | Senza Numba | Numba, prima della correzione | Numba, corretto |
|---|---|---|---|
| Compressione | 3,95 s | 13,14 s | **3,64 s** |
| Decompressione | 4,11 s | 13,51 s | **3,87 s** |

Cartelle in `benchmarks/results`: `fase_3_validazione`, `fase_3_numba`,
`fase_3_numba_avvio`. Il lavoro interno è uguale a quello senza Numba, perché nessun
file del corpus raggiunge la soglia. La piccola differenza di tempo totale non va quindi
letta come un guadagno dell'algoritmo. La dimensione compressa non cambia, a parte
poche centinaia di byte dovute al nonce casuale.

La decompressione resta circa il 18% più lenta della fase 1 (3,29 s). Recuperarla è il
compito della fase 4.

## Perché peggiorava

`src/bmtf/fast_mtf.py` importava Numba e compilava le funzioni MTF a ogni import, senza
salvare il risultato. Il benchmark apre un processo nuovo per ogni prova, quindi pagava
ogni volta circa 0,6 s di avvio, più di quanto Numba facesse risparmiare.

## La correzione

1. Numba non viene più importato all'avvio e la compilazione all'import è stata tolta.
2. Il codice compilato resta in cache su disco (`cache=True`).
3. Numba si carica solo dopo **8 MiB** di simboli elaborati. Sotto questa soglia si usa
   la MTF in Python, che produce esattamente gli stessi risultati (c'è un test apposito).

## Come è stata scelta la soglia

Una prima soglia di 1 MiB rallentava i file da 2 MB (circa 0,2 s) e pareggiava solo
verso i 6 MB, quindi è stata alzata. Con 8 MiB, su dati ottenuti concatenando i corpus:

| Dimensione | Compressione, Python → Numba | Decompressione, Python → Numba |
|---|---|---|
| 2 MB (Numba non attivo) | 1,12 → 1,13 s | 1,54 → 1,53 s |
| 6 MB (Numba non attivo) | 2,24 → 2,23 s | 3,14 → 3,17 s |
| 12 MB | 4,09 → 4,05 s | 5,88 → 5,97 s |
| 18 MB | 5,87 → 5,10 s (-13%) | 8,56 → 8,17 s (-5%) |

Queste prove sono una misura a parte, con 3 ripetizioni: non fanno parte del benchmark
standard, i cui file arrivano al massimo a 1 MB. Il benchmark è stato eseguito con la
soglia a 1 MiB, ma il risultato vale anche per 8 MiB perché in entrambi i casi Numba
non si attiva.
