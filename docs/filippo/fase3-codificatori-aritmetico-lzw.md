# Fase 3 — Perché la pipeline a byte usa solo Huffman

## Il punto di partenza

La pipeline originale aveva tre codificatori finali, scelti con il parametro `mode`:
Huffman (`0`, tramite `dahuffman`), aritmetico (`1`) e LZW (`2`), tutti in `src/pc/`.
Nella fase 2 è stato riscritto solo Huffman, in forma canonica e su simboli interi
(`src/pc/symbol_huffman.py`). Nella fase 3 la pipeline a byte (`src/pipeline.py`)
usa quindi soltanto Huffman: `compressione()` e `decompressione()` rifiutano i modi
1 e 2 con un errore esplicito, e le versioni MPI, che non sono state convertite,
restano le uniche a contenerli.

Ci siamo chiesti se valesse la pena convertire anche gli altri due codificatori.
La risposta è no per LZW e "non così, e non ora" per l'aritmetico. Questo documento
spiega il perché, partendo dalle misure della baseline.

## Cosa dicono le misure della baseline

Nella fase 0 i tre codificatori sono stati misurati sulla stessa pipeline e sugli
stessi file del corpus Canterbury (`benchmarks/results/baseline_20261116_1218/summary.csv`).
Il rapporto è la dimensione compressa divisa per l'originale, quindi più è basso
meglio è; i tempi sono quelli reali del processo di decompressione.

| File | Huffman | Aritmetico | LZW | bzip2 -9 | Decompressione Huffman / aritmetico / LZW |
|---|---|---|---|---|---|
| grammar.lsp | **0,618** | 0,801 | 0,630 | 0,345 | 0,07 / 0,08 / 0,05 s |
| xargs.1 | **0,714** | 0,867 | 0,750 | 0,417 | 0,05 / 0,09 / 0,05 s |
| fields.c | **0,488** | 0,542 | 0,514 | 0,273 | 0,05 / 0,12 / 0,05 s |
| asyoulik.txt | 0,545 | **0,538** | 0,578 | 0,316 | 0,15 / 1,15 / 0,12 s |
| alice29.txt | 0,501 | **0,492** | 0,522 | 0,284 | 0,16 / 1,29 / 0,12 s |
| lcet10.txt | 0,448 | **0,437** | 0,463 | 0,252 | 0,36 / 3,24 / 0,29 s |
| plrabn12.txt | 0,528 | **0,517** | 0,550 | 0,302 | 0,44 / 4,29 / 0,33 s |

## LZW: abbandonato

LZW comprime peggio di Huffman su tutti i file misurati, e il motivo è strutturale,
non di implementazione. LZW guadagna trovando sequenze di simboli che si ripetono e
sostituendole con un indice in un dizionario. Nella nostra pipeline però arriva
dopo BWT, MTF e RLE: la BWT ha già raggruppato i contesti simili, la MTF ha
trasformato quei raggruppamenti in una sequenza di piccoli interi, in gran parte
zeri, e la RLE ha già compresso le sequenze di zeri. Le ripetizioni che LZW
cercherebbe sono state sfruttate a monte: LZW fa lo stesso mestiere della BWT,
e messo dopo di lei non ha più niente da trovare.

Convertirlo avrebbe solo costi: un dizionario da salvare nel contenitore, altro
codice da validare in decompressione contro i file manipolati, altra superficie da
proteggere nella fase 5. Il confronto con gli altri codificatori, utile per la
tesina, è già nella baseline.

## Aritmetico: non convertito, ma la strada resta aperta

L'aritmetico della pipeline originale guadagna poco: circa il 2% rispetto a Huffman
sui file medi (alice29 0,492 contro 0,501), mentre sui file piccoli peggiora molto
perché il costo del modello pesa più dei dati (xargs.1 0,867 contro 0,714). In
cambio la decompressione è da 8 a 10 volte più lenta, perché è scritta in Python
puro e lavora bit per bit. Convertirlo così andrebbe nella direzione opposta alla
fase 4, che deve rendere veloce proprio la decompressione.

Il punto più importante è un altro: il distacco che ci separa da bzip2 (circa il 9%
sui file di testo dopo la fase 3) non dipende dal tipo di codificatore, ma dal
modello statistico. Un codificatore aritmetico statico di ordine 0, come quello
originale, sfrutta le stesse frequenze di Huffman e ottiene quasi lo stesso
risultato. I guadagni veri vengono da modelli più ricchi:

- **più tabelle di Huffman che si alternano**, come fa bzip2 (fino a 6 tabelle,
  scelte ogni 50 simboli). È ancora Huffman, quindi la decodifica resta veloce,
  ed è il modo più economico per recuperare parte del distacco;
- **un codificatore aritmetico adattivo con contesto**, come nei compressori BWT
  moderni, che supera bzip2 in modo netto. Per non rallentare la decompressione
  andrebbe però scritto con Numba (il progetto usa solo Python e librerie native),
  ed è un lavoro a sé.

## Proposta

1. **Ora** non si aggiungono codificatori: prima si chiude la fase 3 (validazione
   in decompressione) e si proseguono le fasi 4 e 5 del piano.
2. **Nel formato** conviene riservare subito un campo che identifichi il
   codificatore (per esempio nel byte `flags` dell'header di `container_format`).
   Costa poco adesso e permette di aggiungerne uno in futuro senza rendere
   illeggibili i file già prodotti; dopo la fase 5, con nonce e tag di
   autenticazione, cambiare il formato sarà più costoso.
3. **Più avanti**, se avanza tempo: prima le tabelle di Huffman multiple, poi
   eventualmente l'aritmetico adattivo con Numba, sempre misurati con
   `benchmarks/run_baseline.py` contro bzip2.
