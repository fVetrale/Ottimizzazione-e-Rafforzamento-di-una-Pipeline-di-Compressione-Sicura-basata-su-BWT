# Fase 4, stadio 3: MTF inversa

Data: 24/11/2026. Benchmark con gli stessi parametri degli stadi precedenti: Canterbury e
Calgary (25 file), 3 ripetizioni più 1 di riscaldamento. Risultati in
`benchmarks/results/fase_4_3_mtf_inversa`, confrontati con `fase_4_2_pointer_jumping`.

## In breve

La MTF inversa ora produce direttamente `bytes` con un dizionario `bytearray`, invece di
passare da liste di interi, e non scorre più l'output una seconda volta per controllarlo.
Sul benchmark lo stadio I-BMTF passa da **0,96 s a 0,60 s** (−38%). L'output e gli
errori sono identici a prima.

Con questo stadio la fase 4 è chiusa. Sui 17 file di testo la decompressione passa da
**3,87 s** (inizio fase 4) a **3,09 s**, sotto i **3,29 s** della fase 1: **obiettivo
raggiunto**.

## Dove andava il tempo

Il tempo di I-BMTF cresceva in proporzione ai byte (0,14–0,2 µs per byte): pesava il
lavoro per simbolo, non un costo fisso per file. Numba non entrava mai in gioco, perché
si attiva sopra gli 8 MiB e nessun file del benchmark ci arriva. Su `book1` (768 KB,
76 blocchi bMTF da 10 KB) lo stadio richiedeva 107 ms:

| Parte | Tempo | |
|---|---|---|
| Ciclo MTF in Python (`_fallback_mtf_decode`) | 46 ms | `pop`/`insert` su una lista di 256 oggetti per ogni simbolo |
| Controllo `any(0 <= s <= 255)` in `mtf.decode` | 17 ms | scorreva tutti i byte decodificati |
| `md5(str(blocco))` | 17 ms | fa parte del formato |
| Validazione dei ranghi con NumPy e conversioni lista ↔ array | ~15 ms | |
| `getListSecretSort` per blocco | 9 ms | alfabeto segreto del blocco |

## Cosa è cambiato

**`src/bmtf/fast_mtf.py`: nuova funzione `fast_mtf_decode_bytes(ranks, dictionary)`**

- Il dizionario MTF è un `bytearray`. Spostare un simbolo in testa diventa un `memmove`
  su al più 256 byte; con rango 0 (circa metà dei simboli dopo BWT + RLE) non si sposta
  nulla. L'output si scrive direttamente in un `bytearray`.
- Il controllo che i simboli siano in [0, 255] si fa una volta sul dizionario e non più
  su tutto l'output: ogni byte prodotto viene dal dizionario, quindi è equivalente.
- I ranghi si controllano con `min`/`max` (`0 ≤ rango < len(dizionario)`) prima di
  qualsiasi accesso. Il controllo è obbligatorio per due motivi: il kernel Numba non
  controlla i limiti, e nel `bytearray` un rango negativo leggerebbe dalla fine invece di
  dare errore.
- Sopra gli 8 MiB si usa il kernel Numba di prima: soglia e cache non cambiano.
- Gli input che la pipeline non produce mai (dizionari con valori fuori da [0, 255],
  ranghi non interi o annidati) passano dal percorso di prima, così anche gli errori
  restano identici.

**`src/bmtf/mtf.py`: `decode`**

- Con alfabeto di interi chiama `fast_mtf_decode_bytes`; il ciclo `any(...)` sull'output
  non c'è più. Il percorso con alfabeto di caratteri (vecchie fasi, MPI) è invariato.

**Cosa non è cambiato:** `bmtf.secure_decode`, quindi la catena di hash calcolata su
`str()` della lista di ranghi e il formato del file. Neanche la codifica
(`secure_encode`, `fast_mtf_encode`) né `fast_mtf_decode`, che resta disponibile
com'era.

## Sicurezza

- **Ranghi non fidati.** Il controllo dei limiti resta prima del ciclo, su entrambi i
  percorsi. È stato verificato anche al contrario: togliendo il controllo sul rango
  massimo, il kernel Numba legge fuori memoria e il processo va in crash
  (`malloc(): unaligned tcache chunk detected`). Per questo il controllo non va mai
  spostato dopo il ciclo.
- **Chiave e alfabeti segreti.** Gli alfabeti dei blocchi si calcolano come prima, dalla
  chiave e dall'hash del blocco precedente. La modifica riguarda solo il modo in cui si
  applica la MTF inversa a un alfabeto già noto.
- **Esaurimento delle risorse.** Il lavoro per simbolo è limitato (al più 256 byte da
  spostare) e la memoria è più bassa di prima, perché non si creano più liste di interi
  Python grandi quanto il blocco.

## Verifica

1. **Riferimento.** Prima di modificare il codice è stata salvata fuori dal repository
   una copia di `src/bmtf/`, e sono stati compressi 8 file con il codice di prima
   (alice29.txt, kennedy.xls, grammar.lsp, sum, book1, pic, obj2 ed E.coli, che usa i
   processi paralleli). Il nuovo codice li decomprime tutti byte per byte.
2. **Confronto con il vecchio decoder** su 426 casi: 400 casuali (dizionari permutati,
   blocchi da 0 a 10.240 ranghi) e 26 particolari (ranghi negativi, pari a 256, enormi,
   float, stringhe, annidati, interi NumPy, bool; dizionari vuoti, `bytes`, tuple, con
   valori fuori da [0, 255]). Sotto e sopra la soglia di Numba: stesso output, oppure
   stesso errore con lo stesso messaggio, in tutti i casi.
3. **Test aggiunti** in `tests/test_fast_mtf.py` (classe `TestByteDecode`, 8 test con
   risultato atteso esplicito): risultato noto calcolato a mano, uguaglianza con il
   decoder a liste su entrambi i percorsi, tipi restituiti da `mtf.decode`, ranghi fuori
   dal dizionario (Python e Numba), ranghi malformati, float trattati come prima,
   dizionario fuori da [0, 255] rifiutato solo se usato, round trip `secure_encode` /
   `secure_decode` su molti blocchi. La suite completa passa: **97 test**.
4. **Mutazioni.** Errori iniettati in una copia del codice: controllo sul rango minimo
   tolto, controllo sul rango massimo tolto, rango 1 non spostato in testa, controllo
   sul dizionario tolto. Sono tutti rilevati, mentre una mutazione neutra di controllo
   non lo è.

## Risultati

### Singolo stadio (`secure_decode`, migliore di 7 esecuzioni)

| File | Prima | Dopo |
|---|---|---|
| kennedy.xls (1,0 MB) | 141 ms | 70 ms (−50%) |
| book1 (769 KB) | 106 ms | 68 ms (−36%) |
| alice29.txt (152 KB) | 21 ms | 13 ms (−37%) |
| paper1 (53 KB) | 7,4 ms | 4,8 ms (−36%) |
| grammar.lsp (4 KB) | 0,9 ms | 0,6 ms (−28%) |

### Benchmark, stadi di decompressione (somma delle mediane)

| Stadio | 25 file, stadio 2 | 25 file, stadio 3 | 17 testo, stadio 2 | 17 testo, stadio 3 |
|---|---|---|---|---|
| I-PC | 0,92 s | 0,99 s | 0,67 s | 0,69 s |
| I-RLE | 0,43 s | 0,45 s | 0,31 s | 0,33 s |
| **I-BMTF** | **0,96 s** | **0,60 s** | **0,55 s** | **0,36 s** |
| I-BWT | 0,23 s | 0,24 s | 0,14 s | 0,14 s |
| **Totale interno** | **2,58 s** | **2,32 s** | **1,69 s** | **1,54 s** |

Tutte le 25 esecuzioni sono `ok`. La dimensione compressa non cambia, a parte poche
migliaia di byte dovute al nonce casuale, e neanche la memoria. Le piccole variazioni
degli stadi non toccati (+2–7%) sono rumore della macchina.

## Bilancio della fase 4

Decompressione sui 17 file di testo, cioè quelli `ok` nella run della fase 1
(`fase_1_test_prestazioni_suffixarray`). Tempo wall: mediana per file, poi somma.

| Momento | Decompressione (wall) | Lavoro interno | Cartella |
|---|---|---|---|
| Fase 1 (riferimento) | 3,29 s | — | `fase_1_test_prestazioni_suffixarray` |
| Inizio fase 4 | 3,87 s | 2,61 s | `fase_3_numba_avvio` |
| Stadio 1, Huffman | 3,30 s | 2,14 s | `fase_4_1_huffman` |
| Stadio 2, BWT inversa | 3,19 s | 1,69 s | `fase_4_2_pointer_jumping` |
| **Stadio 3, MTF inversa** | **3,09 s** | **1,54 s** | `fase_4_3_mtf_inversa` |

- Rispetto all'inizio della fase 4: **−20%** sul tempo wall, **−41%** sul lavoro
  interno.
- Rispetto alla fase 1: **−6%**. L'obiettivo della fase 4 (tornare sotto 3,29 s) è
  raggiunto.
- Ogni stadio ha ridotto quello che aveva preso di mira: I-PC 0,98 → 0,69 s,
  I-BWT 0,76 → 0,14 s, I-BMTF 0,55 → 0,36 s.

Il guadagno sul tempo wall è minore di quello sul lavoro interno perché il wall include
l'avvio di ogni processo: interprete, import di NumPy e dei moduli, circa 0,09 s per
file. Sui 17 file l'avvio vale ormai circa la metà del tempo totale. Ridurlo
richiederebbe di caricare meno moduli all'avvio, fuori dal perimetro di questa fase.

## Cosa resta

- **`md5(str(blocco))`**, circa 17 ms su book1: non si riduce senza cambiare il formato.
- **`getListSecretSort`**, circa 9 ms su book1: si potrebbe accelerare a parità di
  risultato, ma è codice condiviso con la codifica.
- **Blocchi bMTF in parallelo.** L'hash di ogni blocco si calcola sui ranghi ricevuti,
  non sul testo decodificato, quindi tutti gli alfabeti si possono preparare prima e i
  blocchi sarebbero indipendenti. Servirebbe solo sui file grandi.
- Ora lo stadio più pesante è la decodifica Huffman (I-PC, 0,69 s sui 17 file).
