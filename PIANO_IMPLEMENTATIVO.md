# Piano implementativo

Questo piano unisce `WORKFLOW.md` e l'analisi di Gemini (`message.txt`), secondo il confronto in `CONFRONTO_WORKFLOW_GEMINI.md`.
È un piano **concettuale**: per ogni fase dice cosa si vuole ottenere, con quali idee e come si verifica,
non come si scrive il codice. I dettagli si decidono quando si arriva alla fase e il documento si aggiorna man mano.

## Principi

1. **Restiamo in Python.** Le parti lente passano a librerie native (C) o a Numba. Il team non scrive moduli C.
2. **Prima si misura, poi si ottimizza.** Ogni miglioramento si dimostra con un confronto prima/dopo fatto con lo stesso protocollo.
   È la risposta da dare al prof su "Python era il problema".
3. **Si verifica a ogni passo.** Finché il formato del file non cambia, l'output deve essere identico all'originale a parità di chiave.
   Quando il formato cambia, si verifica il round-trip (compressione e decompressione restituiscono il file originale).
4. **Non si inventa crittografia.** Si usano primitive standard e librerie consolidate. Lo scopo è eliminare le debolezze di implementazione,
   non dimostrare la sicurezza dello schema sBWT + bMTF.
5. **Lo schema resta sBWT + bMTF.** Cambia il modo in cui è implementato e protetto, non l'idea di fondo.

## La pipeline obiettivo

Dal file al risultato, tutto in memoria e in byte:

1. **Lettura** del file come byte, senza interpretarlo come testo.
2. **Chiavi:** dalla password e da un nonce casuale si ricava una master key, e da questa le chiavi per cifratura, MAC e singoli blocchi.
3. **sBWT per blocchi:** i simboli vengono rinominati secondo l'ordine segreto del blocco, poi il suffix array lo calcola una libreria C.
4. **bMTF per blocchi:** ogni blocco usa un alfabeto permutato con la propria chiave.
5. **RLE binaria** sulle sequenze di zeri, stile bzip2.
6. **Codifica entropica** (Huffman) sui simboli interi.
7. **Contenitore unico:** header descritto in modo esplicito, payload e tag di autenticazione.

La decompressione fa il percorso al contrario, ma **solo dopo** aver verificato il tag.

---

## Fase 0 — Punto di partenza

**Obiettivo:** sapere esattamente da dove partiamo, con numeri e test.

- Ambiente pronto e versione di Python concordata (oggi la `.venv` usa 3.13, la macchina ha 3.14).
- Misure sulla versione originale con i corpus Canterbury, Calgary e Silesia: tempo di compressione e decompressione,
  throughput, memoria massima e rapporto di compressione. Stesse misure per bzip2 come riferimento.
- Profiling per fase (sBWT, bMTF, RLE, codifica entropica e le fasi inverse), per confermare che la sBWT pesa intorno al 92–95%.
- Misura preliminare della debolezza bMTF: quanti valori MTF dipendono dalla chiave.
- Test di round-trip sulla versione originale, da usare come riferimento.

**Risultato:** una tabella di riferimento e una suite di test di base. Ogni fase successiva si confronta con questa.

**Da decidere:** il protocollo di misura (quante ripetizioni, quali file, come si misura la memoria).

---

## Fase 1 — Suffix array nativo

**Problema:** DC3 è scritto in Python puro ed è la parte che pesa di più.

**Idea:** l'ordine segreto si ottiene sostituendo ogni simbolo con la sua posizione nell'ordine segreto.
Dopo questa rinomina, l'ordinamento normale coincide con quello segreto, quindi si può usare una libreria C standard
per il suffix array (divsufsort o libsais) senza toccare lo schema.

- DC3 resta disponibile per il confronto DC3 Python contro SA-IS in C, un risultato da mettere nella tesina.
- Va controllato se la libreria accetta un alfabeto più grande di 256 simboli: finché la pipeline lavora su caratteri e non su byte, può servire.

**Verifica:** output della sBWT identico a quello di DC3 su tutti i file di test.

**Atteso (da verificare):** sBWT 25–50 volte più veloce.

---

## Fase 2 — MTF, RLE e codifica entropica sui simboli

**Problema:** dopo la fase 1 il collo di bottiglia si sposta qui. Inoltre la RLE testuale (`12-0,3,`) spreca spazio.

**Idee:**
- **MTF** su un array di dimensione fissa invece che su liste Python. Il ciclo è sequenziale per natura e in Python puro resta lento
  anche con un `bytearray`, quindi va compilato con Numba.
- **RLE binaria in stile bzip2:** si codificano solo le sequenze di zeri, che dopo BWT+MTF sono la maggioranza.
  Le coppie lunghezza/valore non convengono.
- **Huffman sui simboli interi** prodotti dalla RLE, non su una loro rappresentazione testuale.

**Verifica:** round-trip corretto e confronto del rapporto di compressione con la fase 0 e con bzip2.

**Atteso (da verificare):** file circa il 39% più piccolo (alice29: 0,497 → 0,301; bzip2: 0,284).

**Da decidere:** come rappresentare la tabella di Huffman (forma canonica con le sole lunghezze dei codici) e quale libreria usare,
o se scriverla noi.

---

## Fase 3 — Pipeline a byte e formato binario

**Problemi:** il file viene letto come testo (crash sui file binari); la sentinella `\003` limita i dati accettati;
ci sono nove file intermedi che lasciano tracce in chiaro; `pickle` permette di eseguire codice aprendo un file manipolato.

**Idee:**
- Tutto lavora su byte e in memoria. L'unico file scritto è quello compresso (o, in decompressione, quello ripristinato).
- Al posto della sentinella si salva l'**indice primario** di ogni blocco, come fa bzip2.
- Un **formato binario** unico con campi a tipo e lunghezza noti, validati prima dell'uso. Sostituisce del tutto `pickle`.
- Contenuto dell'header da definire: magic, versione, flag, nonce/salt, lunghezza originale, numero e dimensione dei blocchi,
  indici primari, dimensione dei blocchi bMTF, tabella di Huffman. L'alfabeto va incluso solo se serve, dichiarandolo come metadato in chiaro.
- Il formato si progetta già pensando alla fase 5: lo spazio per nonce e tag va previsto da subito.

**Verifica:** round-trip anche su file binari (immagini, eseguibili, archivi); un file malformato viene rifiutato
con un errore di validazione, senza eseguire niente.

---

## Fase 4 — Decompressione veloce

**Problema:** anche la decompressione ha cicli Python byte per byte: BWT inversa, MTF inversa e decodifica Huffman (`dahuffman` è Python puro).

**Idee:** BWT inversa e MTF inversa compilate con Numba; decodifica Huffman con tabelle di lookup invece che bit per bit.

**Verifica:** round-trip e misura dei tempi di decompressione rispetto alla fase 0.

---

## Fase 5 — Hardening

**Problemi:** Mersenne Twister al posto di un generatore crittografico; nessuna KDF; la stessa permutazione sBWT su tutti i blocchi;
`r` salvato in chiaro e trasmesso con broadcast; output deterministico (IV della bMTF fisso);
alfabeti bMTF ricavati da una catena di MD5; nessun controllo di integrità.

**Gerarchia delle chiavi:**
1. password + salt (il nonce del file) → **KDF lenta per password** (scrypt, Argon2id o PBKDF2) → master key;
2. master key → **HKDF** → chiavi separate per scopo: `K_enc` per le permutazioni e `K_mac` per l'autenticazione;
3. `K_enc` + nonce + indice del blocco + etichetta → chiave del singolo blocco. Le etichette tengono separati i domini
   **sBWT** e **bMTF**, così le due permutazioni dello stesso blocco sono indipendenti.

**Permutazioni:** dalla chiave del blocco si ricava un flusso di byte pseudocasuali (SHAKE-256 o HMAC in modalità contatore)
e si mescola l'alfabeto con Fisher–Yates, scartando i valori che introdurrebbero bias (rejection sampling).
Sostituisce sia `random.seed` sia la catena di MD5.

**Conseguenze:**
- spariscono `r` in chiaro e il broadcast del seed in MPI;
- ogni blocco è indipendente, il che aiuta anche il parallelismo;
- due compressioni dello stesso file danno output diversi, grazie al nonce casuale generato con `secrets`.

**Encrypt-then-MAC:** HMAC-SHA256 con `K_mac` su header e payload. In decompressione il tag si verifica **per primo**,
con un confronto a tempo costante. Se non corrisponde ci si ferma, senza decodificare niente. AEAD (ChaCha20-Poly1305 o AES-GCM)
solo come estensione, se avanza tempo.

**Test di hardening (pass/fail):**
- una chiave sbagliata viene rifiutata;
- un byte modificato nell'header, in un blocco o nel tag viene rifiutato;
- il nonce cambia a ogni esecuzione;
- le permutazioni cambiano da blocco a blocco e tra sBWT e bMTF;
- un file malformato viene rifiutato senza eseguire codice;
- nella cartella di output c'è solo il file compresso.

**Misura:** costo in byte di header, nonce, tag ed eventuale padding, incluso nel rapporto di compressione.

**Limite da dichiarare:**
Encrypt-then-MAC garantisce integrità e autenticità e neutralizza la manipolazione del file.
Non rende però sBWT + bMTF un cifrario dimostrabilmente sicuro: la riservatezza dipende dalla resistenza dello schema
ad attacchi a testo in chiaro scelto, che non è dimostrata. La bMTF con blocchi grandi resta una debolezza misurata, non risolta.

**Da decidere:** quale KDF usare e con quali parametri; SHAKE-256 o HMAC per le permutazioni; dimensione del nonce.

---

## Fase 6 — Esperimento sui blocchi bMTF (facoltativo)

**Domanda:** quanto costa in compressione rendere la bMTF più dipendente dalla chiave?

**Idea:** variare la dimensione dei blocchi bMTF e misurare rapporto di compressione e frazione di valori che dipendono dalla chiave
(stessa misura della fase 0), poi mettere i due in un grafico. È un indicatore, non una prova di sicurezza.

---

## Fase 7 — Se avanza tempo

- Rimisurare multiprocessing e MPI dopo la fase 1, e tenerli solo se il guadagno resta (con blocchi indipendenti dovrebbe migliorare).
- Parallelismo in stile CTR: confini dei blocchi ricavati dal contatore, unione delle RLE parziali, ricostruzione dello stato iniziale dell'MTF.
- AEAD al posto di Encrypt-then-MAC nella modalità archivio.

La riscrittura in C non è prevista.

---

## Chiusura

- Misure finali con lo stesso protocollo della fase 0.
- Tabelle originale / ottimizzato / bzip2, con header, nonce e tag inclusi nel rapporto.
- Confronto DC3 Python contro SA-IS in C, e tempi per fase prima/dopo.
- Tesina e presentazione, con lo schema della pipeline obiettivo e i limiti dichiarati.

---

## Divisione del lavoro (3 persone)

| Settimana | Persona A: prestazioni | Persona B: hardening | Persona C: benchmark e test |
| --- | --- | --- | --- |
| 1 | Tutti: fase 0 (ambiente, misure, profiling, test di riferimento) | | |
| 2–3 | Fase 1 e fase 2 | Prototipo della gerarchia delle chiavi e delle permutazioni, in un modulo separato | Strumento di benchmark, misure sulla versione MPI esistente |
| 4 | Fase 3 e integrazione con il modulo di hardening | Encrypt-then-MAC e test di manomissione nel nuovo formato | Benchmark della versione ottimizzata e confronto con bzip2 |
| 5 | Fase 4 e confronto DC3 contro SA-IS | Test finali di hardening e misura dell'overhead in byte | Scalabilità (file e processi); fase 6 se si fa |
| 6 | Tutti: chiusura (tabelle, tesina, presentazione, pulizia) | | |

---

## Decisioni aperte

Da discutere quando si arriva alla fase corrispondente. Ogni decisione presa si annota qui con la data.

| Fase | Decisione | Stato |
|---|---|---|
| 0 | Versione di Python comune (3.13 o 3.14) | aperta |
| 0 | Protocollo di misura | aperta |
| 1 | Libreria per il suffix array (divsufsort o libsais) | **decisa** |
| 2 | Libreria Huffman o implementazione nostra | aperta |
| 3 | Struttura esatta dell'header | aperta |
| 5 | KDF e parametri | aperta |
| 5 | Sorgente pseudocasuale per le permutazioni (SHAKE-256 o HMAC) | aperta |
| 5 | Dimensione del nonce | aperta |
| — | Implementazione: Python + librerie native, nessun modulo C nostro | **decisa (16/11/2026)** |
