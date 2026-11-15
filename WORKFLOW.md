# Workflow

Obiettivo: migliorare le prestazioni mantenendo lo schema sBWT + bMTF e correggere le debolezze di implementazione con un hardening verificato con test. Nessuna crittoanalisi formale né dimostrazione di sicurezza.

Principio di verifica: finché il formato non cambia (passo 1) l'output deve essere identico alla versione di partenza a parità di chiave. Dal passo 2 il formato cambia e si verifica il round-trip.

## 0. Setup
- [ ] Rinominare `src/compression.py` (es. `sbwt_compress.py`): su Python 3.14 oscura il pacchetto stdlib `compression` e rompe `import bz2`.
- [ ] Installare `requirements.txt` (+ `numba`, `pydivsufsort`, `cryptography`).
- [ ] Misure di riferimento sui corpus (Canterbury, Calgary, Silesia in `../Analisi BZIP2 Grano/.../dataset/`): tempo di compressione e decompressione, throughput in MB/s, memoria massima, rapporto di compressione. Confronto con bzip2.
- [ ] Profiling per fase e conferma delle osservazioni preliminari (DC3 Python ~0,3 s per 60 KB, peso della sBWT sul tempo totale, 344 valori su 60.001 dipendenti dalla chiave nei primi 60 KB di `alice29.txt`).
- [ ] Test di round-trip di riferimento sulla versione di partenza.

## 1. P1 – Suffix array nativo
- [ ] In `src/sbwt/sbwt.py`: rinominare ogni carattere col suo rango nell'ordine segreto e chiamare `pydivsufsort.divsufsort` (o libsais/SA-IS).
- [ ] Tenere DC3 come alternativa per il confronto (DC3 Python contro SA-IS).
- [ ] Verifica: output BWT identico a DC3.

Atteso (stima da verificare): sBWT 25–50× più veloce, e oggi pesa il 92–95% del tempo.

## 2. RLE binaria + Huffman sui simboli
- [ ] Sostituire la RLE testuale (`12-0,3,`) con la codifica delle sequenze di zeri in stile bzip2 (RUNA/RUNB).
- [ ] Huffman sui simboli interi, non sul testo.
- [ ] MTF su array di byte (NumPy o Numba) al posto di liste Python.
- [ ] Verifica: round-trip corretto e confronto del rapporto di compressione.

Atteso (stima da verificare): file ~39% più piccolo (alice29: 0,497 → 0,301; bzip2 0,284).

## 3. P3 + P4 – Pipeline a byte e formato binario
- [ ] Leggere e scrivere in byte (niente `.decode()`), così funzionano anche i file binari.
- [ ] Togliere la sentinella `\003` e salvare l'indice primario (come fa bzip2).
- [ ] Niente file intermedi: un unico file con header e payload, tutto passa in memoria.
- [ ] Header: magic, versione, nonce, dimensioni dei blocchi, tabella Huffman. L'alfabeto va nell'header solo se serve e va dichiarato come metadato in chiaro.
- [ ] Il formato binario sostituisce `pickle`: si leggono solo campi con tipo e lunghezza noti.

## 4. Decompressione veloce
- [ ] BWT inversa in Numba.
- [ ] Decodifica Huffman più veloce (`dahuffman` è Python puro).

## 5. Hardening (implementato e verificato con test)
- [ ] KDF (PBKDF2 o scrypt) per ricavare la chiave dalla password, al posto di `random.seed(chiave)`.
- [ ] PRF standard (HKDF/HMAC) per generare le permutazioni, al posto di Mersenne Twister; `secrets` per i valori casuali.
- [ ] Chiave per blocco: `seed_i = PRF(K, nonce ‖ i)`. Elimina `r` in chiaro e il broadcast del seed, e ogni blocco è indipendente.
- [ ] Nonce casuale per file, nell'header: due compressioni dello stesso file danno output diversi.
- [ ] Encrypt-then-MAC: HMAC-SHA256 su header e payload, verificato con confronto a tempo costante prima di qualsiasi decodifica. AEAD (ChaCha20-Poly1305 o AES-GCM) nella modalità archivio solo se avanza tempo.
- [ ] Test funzionali (pass/fail): chiave errata rifiutata, un byte modificato in header, blocco o tag rifiutato, nonce diverso a ogni esecuzione, permutazioni diverse tra blocchi, file malformato rifiutato senza eseguire codice, la cartella di output contiene solo il file compresso.
- [ ] Misurare il costo in byte di header, nonce, tag e padding e includerlo nel rapporto di compressione.

Limite da dichiarare: Encrypt-then-MAC dà integrità e autenticazione, ma non rende da solo lo schema sicuro contro attacchi chosen-ciphertext. La bMTF con blocchi grandi resta una debolezza misurata, non risolta.

## 6. Esperimento sui blocchi bMTF (opzionale)
- [ ] Variare la dimensione dei blocchi e misurare rapporto di compressione e frazione di valori MTF che dipendono dalla chiave (stessa misura dell'esperimento preliminare).
- [ ] Grafico compressione contro dipendenza dalla chiave. È un indicatore, non una prova di sicurezza.

## 7. Se avanza tempo
- [ ] P5: rimisurare multiprocessing e MPI dopo il passo 1 e tenerli solo se il guadagno resta.
- [ ] bMTF in Numba (oggi pesa solo ~3%).
- [ ] Riscrittura in C di MTF e RLE, OpenMP, MPI con OpenMP, DC3 in C.
- [ ] Parallelismo CTR-like: confini dei blocchi dal contatore, merge dell'RLE con prefix scan, ricostruzione dello stato iniziale dell'MTF.

## 8. Piano a settimane (3 persone)

| Settimana | Persona A: prestazioni | Persona B: hardening | Persona C: benchmark |
| --- | --- | --- | --- |
| 1 | Tutti: setup, misure di riferimento, profiling, test di round-trip (passo 0) | | |
| 2–3 | Passo 1 (suffix array nativo) e passo 2 (RLE binaria, MTF su array) | Prototipo di KDF, PRF, nonce e chiavi per blocco in un modulo separato | Strumento di benchmark (tempo, MB/s, memoria), misure sulla versione MPI esistente |
| 4 | Passo 3 (pipeline a byte, formato binario) e integrazione con il modulo di hardening | Encrypt-then-MAC e test di manomissione nel nuovo formato | Benchmark della versione ottimizzata e confronto con bzip2 |
| 5 | Passo 4 (decompressione veloce) e confronto DC3 contro SA-IS | Test finali di hardening e misura dell'overhead in byte | Scalabilità (file e processi); esperimento bMTF se si fa |
| 6 | Tutti: tabelle di confronto, tesina e presentazione, pulizia di codice e script | | |

## 9. Chiusura
- [ ] Misure finali con lo stesso protocollo del passo 0.
- [ ] Tabelle di confronto originale / ottimizzato / bzip2, con header, nonce e tag inclusi nel rapporto.
- [ ] Tesina e presentazione.
