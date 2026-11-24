# Report di lavoro — Filippo

Questo documento racconta, fase per fase, cosa è stato fatto sulla pipeline sBWT,
perché, e con quali risultati. Si aggiorna alla fine di ogni fase.

---

## Fase 1 — Suffix array nativo

*17 novembre 2026*

### Il problema

Per calcolare la BWT di un testo bisogna mettere in ordine tutti i suoi suffissi,
cioè tutte le "code" del testo. Per `banana$` i suffissi sono `banana$`, `anana$`,
`nana$`, `ana$`, `na$`, `a$` e `$`. La lista delle loro posizioni di partenza, messe
in ordine, si chiama **suffix array**. Una volta che si ha il suffix array, la BWT si
ottiene subito: per ogni suffisso si prende il carattere che lo precede.

Il costo è tutto lì. Un file di 1 MB ha un milione di suffissi da ordinare, e
ciascuno può essere lungo fino a un milione di caratteri. Esistono algoritmi molto
furbi per farlo in tempo lineare, e la pipeline ne usa uno, DC3, introdotto dal
gruppo Sasso Giella. Il problema è che DC3 è scritto in **Python puro**
(`src/sbwt/suffix.py`). L'algoritmo è efficiente sulla carta, ma Python esegue ogni
singola operazione (un confronto, una somma, un accesso a una lista) tramite
l'interprete, decine di volte più lentamente di un programma compilato. Per questo la
sBWT occupava la quasi totalità del tempo di compressione.

La soluzione naturale sarebbe usare una libreria già scritta in C, come divsufsort:
è veloce, collaudata e già disponibile in Python. Ma c'è un ostacolo, ed è la ragione
per cui questa strada sembrava chiusa.

La **sBWT** non è una BWT normale. In una BWT normale i suffissi si ordinano in ordine
alfabetico: `a` prima di `b`, `b` prima di `n`. Nella sBWT invece l'ordine dei
caratteri è **segreto**: lo decide la chiave, e senza la chiave non si sa se `n` viene
prima o dopo `a`. È proprio questo che rende la trasformazione sicura, perché chi non
conosce l'ordine non può invertirla.

Una libreria come divsufsort, però, conosce un solo ordine: quello naturale dei
simboli, cioè il loro valore numerico (`a` vale 97, `b` 98, `n` 110). Non c'è modo di
dirle "usa quest'altro ordine". Se le si passa il testo così com'è, produce la BWT
normale, e la sicurezza sparisce.

### L'idea

Visto che non si può cambiare l'ordine usato dalla libreria, si cambia il testo.

Prima di chiamare la libreria, ogni carattere viene sostituito con un numero che
indica **la sua posizione nell'ordine segreto**. Se la chiave stabilisce che l'ordine
è `$ < n < b < a`, allora `$` diventa 1, `n` diventa 2, `b` diventa 3 e `a` diventa 4.
Il testo diventa una sequenza di numeri.

A questo punto la libreria ordina quei numeri con il suo ordine naturale, cioè dal più
piccolo al più grande. Ma dal più piccolo al più grande significa esattamente
nell'ordine segreto, perché i numeri sono stati scelti apposta. La libreria calcola
così il suffix array segreto senza sapere che esiste una chiave: la chiave è già
"dentro" i numeri.

In breve: la libreria non è cambiata, l'ordine segreto non è cambiato; è cambiato
solo il testo che le viene passato.

La cosa curiosa è che questa rinomina **esisteva già** nel codice:
`buildSuffixArrayDC3` la faceva come primo passo, perché DC3 lavora solo su numeri
interi. Bastava accorgersi che, dopo quel passo, al posto di DC3 si poteva usare
qualunque altro algoritmo.

Come libreria è stata scelta `pydivsufsort`, un'interfaccia Python a divsufsort, una
delle implementazioni in C più veloci per il suffix array. Era già nei
`requirements.txt` del progetto.

### Un esempio: `banana` con la chiave `"chiave"`

I valori seguenti sono stati calcolati con il codice del progetto.

Il primo passo è l'ordine segreto. `customSort.getSecretSort` inizializza il
generatore casuale con la chiave (`random.seed(key)`) e assegna a ogni carattere
dell'alfabeto un numero casuale; la sentinella `\003`, indicata qui con `$`, viene
forzata a `-1` perché sia sempre la più piccola:

```
'n' → 0.055    'b' → 0.293    'a' → 0.527    '$' → -1
```

L'ordine segreto è quello di questi numeri: **$ < n < b < a**. Una chiave diversa
produce numeri diversi e quindi un ordine diverso.

Il secondo passo è la rinomina, fatta da `secretRanks`. Ogni carattere viene
sostituito con la sua posizione nell'ordine segreto:

```
$ → 1,  n → 2,  b → 3,  a → 4

"banana$"  →  [3, 4, 2, 4, 2, 4, 1]
```

Da qui in avanti confrontare due numeri con il `<` normale equivale a confrontare i
due caratteri con l'ordine segreto: `n` viene prima di `a`, e infatti `2 < 4`.

Il terzo passo è l'ordinamento. divsufsort riceve la sequenza di numeri e la ordina
in modo del tutto standard, senza sapere nulla della chiave. Dato che i numeri
rispettano già l'ordine segreto, il risultato è il suffix array segreto:

```
SA = [6, 4, 2, 0, 5, 3, 1]  →  $ , na$ , nana$ , banana$ , a$ , ana$ , anana$
BWT segreta = "aaa$nnb"
```

I suffissi che iniziano per `n` precedono quelli che iniziano per `b` e per `a`,
come vuole l'ordine segreto.

### Perché i colleghi non l'avevano fatto

Il suffix array segreto ha già cambiato implementazione due volte. Il primo progetto
("Secure Compression based on BWT") usava `buildSuffixArray`, un algoritmo di
*prefix doubling*: ordina i suffissi prima per i primi 2 caratteri, poi per i primi 4,
8 e così via, con un `sorted` di Python a ogni giro. La complessità è O(n log² n).
L'ordine segreto era gestito usando direttamente i numeri casuali della chiave come
valori di confronto. Il gruppo Sasso Giella lo ha sostituito con DC3, che è lineare.
La vecchia funzione è rimasta in `suffix.py`, ma non la chiama più nessuno: viene
eseguita solo nella piccola demo in fondo al file (`if __name__ == "__main__"`).

In entrambi i progetti la libreria C compare, ma commentata, in `sbwt/sbwt.py`:

```python
#from pydivsufsort import divsufsort
...
#s_array = divsufsort(string)
```

La chiamata passa alla libreria la stringa così com'è, senza rinomina. In questo modo
divsufsort ordina con l'ordine alfabetico naturale ($ < a < b < n) e l'ordine segreto
si perde. Nell'esempio di `banana` le due BWT sono diverse:

```
BWT con la stringa originale = "annb$aa"   ← una BWT standard, invertibile senza chiave
BWT con la rinomina segreta  = "aaa$nnb"   ← quella corretta, che dipende dalla chiave
```

Con la prima la sBWT diventa una BWT qualsiasi e lo schema non protegge più nulla.
È ragionevole pensare che il tentativo sia stato scartato proprio per questo, e che si
sia concluso che l'ordine segreto richiedesse un algoritmo scritto e adattato a mano. La tesina di Sasso Giella
va in questa direzione: parla di un "adattamento del layer di sicurezza
all'algoritmo", e l'obiettivo dichiarato del lavoro era l'introduzione di un algoritmo
lineare (DC3), più che la velocità assoluta.

Nessuna delle due tesine motiva esplicitamente l'abbandono di divsufsort, quindi
questa ricostruzione resta un'interpretazione. Resta il fatto che la soluzione era a
portata di mano: la rinomina che serviva a DC3 è la stessa che rende utilizzabile
la libreria C. Così si evita anche un passaggio in più, perché non serve né scrivere
né mantenere un algoritmo di suffix array proprio.

### Cosa è cambiato nel codice

In `src/sbwt/suffix.py` la rinomina segreta è diventata una funzione a sé,
`secretRanks(txt, key)`, e accanto a DC3 c'è ora
`buildSuffixArrayDivsufsort(txt, key)`, che rinomina e passa i ranghi a divsufsort
come array `int32`. `pydivsufsort` e `numpy` sono importati dentro questa funzione e
non in cima al modulo, per non rallentare la decompressione (vedi più avanti).

In `src/sbwt/sbwt.py` la funzione `bwt_from_suffix` ha un nuovo parametro `sa_algo`:
il valore predefinito è `"divsufsort"`, mentre `"dc3"` resta disponibile per i
confronti. Tutti i punti della pipeline che chiamano `bwt_from_suffix` (compressione
a file intero, a blocchi con multiprocessing e MPI) usano quindi la libreria C senza
altre modifiche. DC3 non è stato toccato e rimane come riferimento.

La chiave, `customSort.py`, la BWT inversa e il formato del file compresso non sono
cambiati.

### Verifiche

La prima domanda era se divsufsort accettasse alfabeti più grandi di 256 simboli,
perché la pipeline lavora ancora su caratteri Unicode e non su byte. La risposta è sì:
accetta array NumPy di interi a 16, 32 e 64 bit. La prova su un testo sintetico con
quasi 10.000 simboli distinti lo conferma.

Il criterio di correttezza è stato più forte del semplice round-trip: la BWT prodotta
con divsufsort deve essere **identica carattere per carattere** a quella prodotta con
DC3, a parità di chiave. Se lo è, la sicurezza dello schema non cambia, perché
l'output non cambia. La prova è stata fatta su sette file del corpus Canterbury
(fino a 150 KB), un testo Unicode sintetico, un testo molto ripetitivo e un caso
limite di un solo carattere, ciascuno con tre chiavi diverse. In tutti i casi la BWT
è risultata identica e la BWT inversa ha restituito il testo originale.

Vale la pena capire anche come la libreria gestisce i ranghi. `pydivsufsort` non ha un
algoritmo separato per gli interi: sottrae il valore minimo e riduce l'array al tipo
più piccolo che lo contiene. Con al massimo 256 simboli distinti, quindi sempre quando
si lavora a byte, i ranghi diventano byte e vanno direttamente al codice C. Con più
simboli usa interi a 16 bit e ordina i loro byte: il risultato è corretto, ma il
lavoro raddoppia. Quando la fase 3 porterà la pipeline a lavorare su byte, si resterà
sempre nel caso veloce.

### Le misure

Le misure sono state fatte con `tests/bench_sbwt.py` sugli stessi corpus della fase 0
(Canterbury, Calgary, Large, Silesia), con un'esecuzione di riscaldamento scartata e
tre misurate, di cui si riporta la mediana. Lo script misura solo la sBWT su file
intero, ogni esecuzione in un processo separato, e la divide in tre parti: la
rinomina, il suffix array e la costruzione della stringa BWT. Su tutti i file la BWT
dei due algoritmi è risultata identica. I risultati completi sono in
`benchmarks/results/fase1_sbwt_20261117_1246/`.

| File | Dimensione | sBWT con DC3 | sBWT con divsufsort | Più veloce di | Solo suffix array |
|---|---:|---:|---:|---:|---:|
| alice29.txt | 152 KB | 1,47 s | 0,060 s | 24× | 55× |
| kennedy.xls | 1,0 MB | 4,90 s | 0,132 s | 37× | 63× |
| book1 | 769 KB | 5,02 s | 0,116 s | 43× | 79× |
| world192.txt | 2,5 MB | 20,6 s | 0,295 s | 70× | 137× |
| bible.txt | 4,0 MB | 36,5 s | 0,464 s | 79× | 157× |
| E.coli | 4,6 MB | 42,3 s | 0,587 s | 72× | 139× |
| dickens | 10,2 MB | — | 1,47 s | — | — |

Il guadagno cresce con la dimensione del file: si passa da circa 25 volte sui file da
100–150 KB a quasi 80 volte sui file da 4 MB. Considerando solo il suffix array, cioè la
parte che è stata effettivamente sostituita, si arriva a 140–160 volte. DC3 procede a
circa 0,1 MB/s, divsufsort a 7–9 MB/s.

Anche la memoria scende molto: su bible.txt DC3 arriva a circa 1 GB, divsufsort a
280 MB, perché DC3 tiene tutto in liste Python, dove ogni intero è un oggetto. Per
questo DC3 non è stato misurato sui file Silesia (5–10 MB): avrebbe richiesto minuti
per ogni esecuzione e diversi GB di memoria. divsufsort li elabora in 1–1,5 secondi.

Questi tempi sono più alti di quelli che compaiono nella pipeline reale, dove i file
grandi vengono divisi in blocchi elaborati in parallelo. Il confronto però è fatto
sullo stesso lavoro, quindi il rapporto tra i due algoritmi resta valido.

### Il nuovo collo di bottiglia

Con divsufsort il suffix array occupa ormai solo il 45–55% del tempo della sBWT.
Il resto se ne va nelle due parti ancora scritte in Python: la rinomina, che scorre il
testo carattere per carattere passando da un dizionario, e la costruzione della BWT,
che fa la stessa cosa con il suffix array. Su dickens queste due parti costano più del
suffix array stesso (0,19 s e 0,66 s contro 0,63 s). Entrambe si possono riscrivere con
operazioni vettoriali di NumPy, ma conviene farlo insieme alla fase 3, quando il testo
diventerà un array di byte e la rinomina si ridurrà a una tabella di 256 valori.

### La prova sulla pipeline completa

Le misure precedenti riguardano solo la sBWT. Per controllare che la pipeline intera
funzionasse ancora, compressione e decompressione comprese, ho rilanciato lo script
della fase 0, `benchmarks/run_baseline.py`, sui corpus Canterbury e Calgary con la
stessa chiave della baseline:

```
.venv/bin/python benchmarks/run_baseline.py --corpora canterbury,calgary --reps 1 --warmup 0 \
    --label fase_1_test_prestazioni_suffixarray \
    --out benchmarks/results/fase_1_test_prestazioni_suffixarray
```

Lo script lavora su una copia di `src/` in `benchmarks/_work/`, che cancella alla fine,
e confronta byte per byte ogni file decompresso con l'originale. Su Canterbury prova
tutti e tre i codificatori (Huffman, aritmetico, LZW), su Calgary solo Huffman. I
risultati sono in `benchmarks/results/fase_1_test_prestazioni_suffixarray/`.

**Correttezza.** Tutte le 56 prove sono andate a buon fine, senza nessun file
decompresso diverso dall'originale. Altre 16 prove riguardano file binari
(`kennedy.xls`, `ptt5`, `sum`, `cp.html`, `obj1`, `obj2`, `geo`, `pic`) e non sono
partite: la pipeline legge l'input come testo UTF-8 e quei file non lo sono. Fallivano
allo stesso modo nella baseline, quindi è un limite che c'era già e che la fase 3
risolverà passando ai byte. In modalità a file intero gli hash di BWT e MTF sono
identici a quelli della baseline. In modalità a blocchi (`book1`, `book2`) cambiano a
ogni esecuzione, ma solo perché il parametro `r` viene scelto a caso: succedeva già tra
le ripetizioni della baseline.

**Un problema trovato: l'import di pydivsufsort in decompressione.** La prima
esecuzione aveva una decompressione più lenta della baseline di circa 60 ms per file,
anche se la decompressione non calcola nessun suffix array. Il motivo era che
`decompression.py` importa `sbwt.sbwt`, che importa `sbwt.suffix`, dove `pydivsufsort`
e `numpy` erano importati in cima al modulo. Misurato con `python -X importtime`,
caricarli costa circa 65 ms a ogni processo. Ho spostato i due import dentro
`buildSuffixArrayDivsufsort`, così vengono caricati solo quando si calcola davvero il
suffix array. Il tempo di import della decompressione è sceso da 87 ms a 39 ms. La
compressione non ne risente, perché `sbwt_compress.py` usa comunque `numpy` per conto
suo. Il test riportato qui sotto è stato rifatto dopo la correzione.

| | Baseline (DC3) | Fase 1, import in cima | Fase 1, import nella funzione |
|---|---:|---:|---:|
| Compressione, somma di tutte le prove | 34,4 s | 10,3 s | 10,2 s |
| Decompressione, somma di tutte le prove | 14,5 s | 16,3 s | 14,2 s |

Alcuni file nel dettaglio (tempi di compressione, Huffman salvo dove indicato):

| File | Dimensione | Baseline | Fase 1 | Più veloce di |
|---|---:|---:|---:|---:|
| plrabn12.txt | 482 KB | 3,33 s | 0,39 s | 8,5× |
| lcet10.txt | 427 KB | 2,32 s | 0,32 s | 7,3× |
| news.eml | 377 KB | 2,49 s | 0,36 s | 6,9× |
| book1 (a blocchi) | 769 KB | 1,92 s | 0,44 s | 4,4× |
| alice29.txt | 152 KB | 0,69 s | 0,19 s | 3,6× |
| plrabn12.txt, aritmetico | 482 KB | 4,67 s | 1,79 s | 2,6× |

Sull'intera pipeline la compressione è circa 3,4 volte più veloce. Il guadagno è
minore di quello della sola sBWT perché ora il tempo va soprattutto nelle altre fasi:
MTF, RLE, codifica entropica e avvio dell'interprete Python. Con il codificatore
aritmetico il guadagno si ferma intorno a 2,6×, perché è la codifica stessa a essere
lenta. Sui file di pochi KB i tempi restano intorno a 0,1–0,2 s e sono dominati
dall'avvio del processo. La decompressione non cambia rispetto alla baseline, come
deve essere, perché questa fase non la tocca. Ogni file è stato misurato una sola
volta e senza riscaldamento: sotto il decimo di secondo le singole misure oscillano,
le somme sono più affidabili.

Questa prova non sostituisce quella finale, che andrà ripetuta dopo la fase 3, quando
cambierà il formato del file compresso.

### Cosa resta per chiudere la fase

- La prova finale della pipeline dopo la fase 3, quando cambierà il formato del file
  compresso.
- La scelta di divsufsort è annotata tra le decisioni di `PIANO_IMPLEMENTATIVO.md`.

---

## Fase 3 — Pipeline a byte e formato binario

*19 novembre 2026 — branch `fase3-pipeline`*

### Da dove siamo partiti

La fase 3 era assegnata a Sebastiano e la fase 2 a Mattia. Il 19 novembre i loro
lavori sono stati riuniti: `filippo` e `mattia` nel branch `integrazione`, e
`integrazione` dentro `sebastiano`. Il conflitto in `src/bmtf/mtf.py` si è risolto
tenendo la MTF compilata con Numba di Mattia, ma facendole restituire `bytes` quando
l'alfabeto è fatto di interi, come serve alla bMTF a byte di Sebastiano.

Analizzando il risultato, i pezzi c'erano ed erano corretti: il contenitore binario
(`container_format.py`), la BWT sui byte con l'indice primario al posto della
sentinella (`bwt_bytes`), la bMTF sui byte, la Zero-RLE e l'Huffman canonico di Mattia.
Mancava però proprio la fase 3: il programma vero (`sbwt_compress.py` e
`decompression.py`) era identico a quello di partenza. Leggeva il file come testo,
quindi falliva su ogni file binario; aggiungeva la sentinella `\003`; scriveva nove
file intermedi con i dati in chiaro in `TestFiles/Output/`; salvava la codifica con
`pickle`, che esegue codice quando si apre un file manipolato. Mettendo in fila i
moduli a mano si vedeva anche un problema di prestazioni serio nell'Huffman.

Abbiamo deciso di completare la fase noi, su un branch nuovo (`fase3-pipeline`, nato da
`sebastiano`), in quattro punti: la pipeline vera (1), il bug di Huffman (2), la
validazione in decompressione (3) e le decisioni sul formato (4, in parte).

### Le decisioni prese prima di scrivere codice

- **Solo Huffman.** La pipeline originale aveva anche il codificatore aritmetico
  (modo 1) e LZW (modo 2). Nella nuova pipeline esiste solo il modo 0; gli altri
  danno un errore esplicito. Il motivo, con le misure della baseline, è in
  [`fase3-codificatori-aritmetico-lzw.md`](fase3-codificatori-aritmetico-lzw.md): LZW
  comprime peggio di Huffman su tutti i file, l'aritmetico guadagna circa il 2% ma
  decomprime da 8 a 10 volte più lentamente.
- **Alfabeto fisso 0–255 per la bMTF.** Il decoder deve conoscere l'alfabeto prima di
  decodificare. Invece di salvarlo nel file, la bMTF parte sempre da tutti i 256 byte
  permutati dalla chiave: non c'è niente da salvare e il file compresso non rivela
  quali valori di byte compaiono nell'originale.
- **Versioni MPI non toccate.** `compression_mpi.py` e `decompression_mpi.py` restano
  la pipeline testuale originale; convertirle è un lavoro a parte.
- **Commit fatti da me**, sul branch `fase3-pipeline`.

### Il contenitore

Il formato di Sebastiano era una buona base: magic, versione, campi a dimensione
fissa in big endian, spazio per nonce e tag di autenticazione (fase 5). Per farci
stare la pipeline sono servite tre modifiche.

**Il numero di simboli Huffman è entrato nell'header** (`symbol_count`). Il decoder
deve sapere quando fermarsi, perché l'ultimo byte del flusso contiene bit di
riempimento. Prima Mattia lo scriveva in testa al proprio payload, cioè fuori da ogni
controllo; ora la tabella sta nel suo campo e il payload è solo il flusso di bit.

**È sparito un campo doppio.** `primary_count` valeva sempre quanto `block_count`: un
campo che ripete un altro serve solo a creare incoerenze.

**I campi si controllano a vicenda.** Un singolo campo può avere un valore plausibile
e insieme essere incoerente con gli altri. Ora il numero di blocchi deve essere
esattamente ⌈dimensione originale / dimensione del blocco⌉; ogni indice primario
deve stare dentro il *proprio* blocco (l'ultimo è più corto, e prima il controllo
usava sempre la dimensione piena); il numero di simboli deve stare tra 1 e la
dimensione originale, perché la Zero-RLE non produce mai più simboli dell'input; un
input vuoto non può portare dati. Tutti questi controlli sono in una sola funzione,
`validate()`, chiamata sia in scrittura sia in lettura: ciò che `serialize` produce,
`parse` lo accetta sempre. Le lunghezze dichiarate vengono confrontate con la
dimensione reale del file prima di leggere le sezioni, così un header falsificato non
può far allocare memoria o ciclare il parser.

### La pipeline in memoria: `src/pipeline.py`

È il cuore della fase. Due funzioni, senza file e senza stampe:

```
compress_bytes(dati, chiave)   -> un unico blocco di byte (il contenitore)
decompress_bytes(blob, chiave) -> i byte originali
```

La compressione divide i dati in blocchi, calcola la sBWT di ogni blocco con
`bwt_bytes` (che usa divsufsort, il lavoro della fase 1) e salva un indice primario
per blocco; poi applica la bMTF a tutto l'output, la Zero-RLE e l'Huffman canonico, e
mette tutto nel contenitore. La decompressione valida il contenitore e fa il
percorso inverso.

Per ogni compressione si estrae un **nonce casuale** di 16 byte, salvato in chiaro
nell'header, e le trasformazioni usano come chiave `nonce + chiave`. Lo stesso file
compresso due volte con la stessa chiave dà due risultati diversi. Il nonce prende il
posto del numero casuale `r` che la pipeline originale scriveva in `rfile.txt`, e
prepara la fase 5, dove servirà alla derivazione delle chiavi.

Separare la logica dalla lettura e scrittura dei file non è solo ordine: permette di
testare la pipeline direttamente, senza passare dal disco.

### Gli involucri e il benchmark

`sbwt_compress.py` e `decompression.py` sono diventati due involucri sottili attorno
a `pipeline.py`. Le funzioni `compressione()` e `decompressione()` hanno la stessa
firma di prima, quindi `tester.py` e `benchmarks/_driver.py` le chiamano come sempre.
L'unico file scritto in compressione è `TestFiles/Output/compressed.sbwt`; in
decompressione `decompressed.txt` (nome storico, contenuto binario). La scrittura passa
da un file temporaneo rinominato alla fine, così un errore non lascia mai un file a
metà. I tempi di ogni stadio vengono stampati nel formato della pipeline originale
(`... -> elapsed time of sBWT`), perché il benchmark li legge e li confronta con la
baseline.

`benchmarks/run_baseline.py` ora conta un payload unico senza metadati e, soprattutto,
**segna come errore la prova se dopo la compressione in `Output` compare qualunque
altro file**. L'assenza di file intermedi non è più una promessa: viene verificata a
ogni esecuzione.

### Tre problemi trovati strada facendo

**L'Huffman era quadratico.** Nel `BitWriter` di Mattia l'accumulatore dei bit non
veniva mai svuotato: dopo aver emesso un byte, i bit già scritti restavano lì, e
l'accumulatore cresceva fino a contenere l'intero flusso. Ogni scrittura faceva uno
shift su un intero sempre più grande, quindi il tempo cresceva col quadrato dei
simboli: 0,8 s per 100.000 simboli, 45 s per 800.000. Su book1 l'Huffman impiegava
13,4 s, contro 0,4 s di tutto il resto. È bastata una riga che tiene solo i bit non
ancora emessi; ora book1 richiede 0,08 s, circa 170 volte meno, e il formato prodotto
è identico. Due test controllano che l'accumulatore resti sotto gli 8 bit e che
l'output coincida bit per bit con una versione di riferimento.

**I processi in parallelo si bloccavano.** I blocchi della sBWT sono elaborati in
processi separati. Su Linux Python li crea di default con `fork`, cioè copiando il
processo principale. Ma a quel punto numpy e pydivsufsort hanno già avviato dei
thread: se uno di questi tiene un lock nel momento della copia, il processo figlio lo
eredita bloccato e resta fermo per sempre. Lo segnala Python stesso (*"This process is
multi-threaded, use of fork() may lead to deadlocks in the child"*), e nei test
succedeva davvero. I processi ora partono con `spawn`, cioè da zero, che è anche l'unico
modo disponibile su Windows: la pipeline si comporta allo stesso modo su tutte le
macchine del gruppo. L'unica conseguenza è che chi la usa da uno script deve avere la
solita guardia `if __name__ == "__main__":`.

**Il parallelismo costava più di quanto rendeva.** La politica dei blocchi veniva dalla
fase 0: un blocco per core, tra 256 KB e 2 MB. Aveva senso con DC3, lentissimo. Con
divsufsort un blocco da 256 KB si trasforma in circa 0,1 s, meno del tempo necessario
ad avviare i processi (circa 0,15 s, perché ognuno deve reimportare numpy e
pydivsufsort). Su book1: sBWT 0,28 s con un processo, 0,30 s in parallelo; BWT inversa
0,12 s contro 0,26 s. In più i blocchi piccoli comprimono peggio i testi. Ora i blocchi
sono fissi da 900 KB, come in bzip2 -9, e il parallelismo scatta solo da 4 MB in su.
Su book1 il rapporto è passato da 0,352 a 0,328 e la compressione da 0,69 a 0,51 s.
C'è un caso in cui il blocco grande comprime un po' peggio, kennedy.xls (da 0,202 a
0,217): su dati eterogenei un blocco piccolo si adatta meglio. Abbiamo accettato il
compromesso, a favore dei testi e della velocità.

### La validazione in decompressione

Il file compresso arriva da fuori, quindi può essere troncato o manipolato. La regola
che ci siamo dati: un file non valido deve essere **rifiutato con un errore di
formato**, mai far crollare il programma con un'altra eccezione, mai bloccarlo, mai
fargli leggere fuori da un array o allocare memoria senza limite.

| Stadio | Cosa si controlla | Contro cosa protegge |
|---|---|---|
| Contenitore | struttura, lunghezze, coerenza tra i campi | file troncati, allungati o con campi incoerenti |
| Tabella Huffman | simboli ammessi, lunghezze tra 1 e 64, disuguaglianza di Kraft con uguaglianza esatta, nessun duplicato | tabelle che darebbero codici sovrapposti o incompleti |
| Flusso Huffman | bit sufficienti, nessun byte in eccesso, riempimento a zero | payload troncato o allungato |
| Zero-RLE | limite sulla lunghezza controllato *prima* di allocare gli zeri, simboli ammessi | "decompression bomb": 60 simboli RUNB chiederebbero circa 2⁶¹ zeri |
| MTF (Numba) | ranghi dentro il dizionario | letture fuori dall'array: il ciclo compilato non controlla i limiti |
| bMTF | blocco non più piccolo di 10 KB | file che renderebbero la decompressione lentissima |

La condizione di Kraft merita due parole. Un codice di Huffman è sempre *completo*: la
somma di 2⁻ˡ su tutte le lunghezze l vale esattamente 1. Se la somma supera 1, i codici
canonici ricostruiti dal decoder si sovrappongono; se è minore di 1, restano sequenze di
bit che non corrispondono a nessun simbolo. Una tabella manipolata quasi sempre viola
questa uguaglianza, e la si scarta prima di costruire l'albero.

Infine `pipeline.py` trasforma qualunque errore di decodifica in `ContainerFormatError`:
chi usa la pipeline deve gestire un solo tipo di errore.

Scrivendo i test è emerso un altro bug nell'Huffman: con un solo simbolo il caso
speciale non scattava mai (il codice `0` crea un ramo nell'albero, quindi la radice
non è mai una foglia), e un bit corrotto portava a un `AttributeError` invece che a un
errore di formato. Ora il caso si riconosce dalla tabella, e ogni discesa verso un ramo
inesistente è un errore di formato.

Per misurare la validazione abbiamo invertito, uno alla volta, ogni byte di un file
compresso (553 byte) e provato a decomprimerlo:

| Zona | Byte | Rifiutati | Output diverso | Output identico |
|---|---|---|---|---|
| Header | 54 | 46 | 0 | 8 |
| Nonce | 16 | 0 | 16 | 0 |
| Indici primari | 4 | 3 | 1 | 0 |
| Tabella Huffman | 89 | 88 | 1 | 0 |
| Payload | 390 | 311 | 79 | 0 |
| **Totale** | 553 | **448 (81%)** | 97 | 8 |

Nessuna alterazione ha causato altre eccezioni o blocchi. Gli 8 byte dell'header con
output identico sono le due dimensioni di blocco: il file di prova sta comunque in un
blocco solo. Le alterazioni del nonce e una parte di quelle del payload producono dati
validi ma diversi, e senza un'autenticazione non si possono riconoscere per
costruzione. Allo stesso modo un header falsificato può dichiarare una dimensione
originale enorme: per questo `decompress_bytes` accetta un limite `max_output_size`.
Entrambi i punti si chiudono con il tag di autenticazione della fase 5, per cui il
formato ha già lo spazio.

### Le misure

Benchmark ufficiale con `run_baseline.py` su Canterbury e Calgary, tre ripetizioni più
una di riscaldamento, come la baseline. I risultati sono in
`benchmarks/results/fase_3_validazione/` (la prova con la vecchia politica dei
blocchi da 256 KB è in `fase_3_pipeline_byte/`). Il rapporto è la
dimensione compressa divisa per l'originale.

**File supportati: 25 su 25**, contro 17 della baseline. Gli otto binari (obj1, geo,
obj2, pic, cp.html, sum, ptt5, kennedy.xls) prima fallivano con `UnicodeDecodeError`.

Sui 17 file di testo che anche la baseline gestiva:

| | Fase 0 | Fase 1 | **Fase 3** | bzip2 -9 |
|---|---|---|---|---|
| Byte compressi | 1.743.298 | ≈ fase 0 | **1.063.790 (−39%)** | 976.577 |
| Compressione (somma) | 15,91 s | 3,76 s | **3,95 s** | |
| Decompressione (somma) | 3,22 s | 3,29 s | **4,11 s** | |

Alcuni file:

| File | Fase 0 | Fase 3 | bzip2 |
|---|---|---|---|
| alice29.txt | 0,501 | 0,310 | 0,284 |
| book1 | 0,565 | 0,328 | 0,303 |
| lcet10.txt | 0,448 | 0,275 | 0,252 |
| pic (binario) | — | 0,111 | 0,097 |
| kennedy.xls (binario) | — | 0,217 | 0,127 |

Il rapporto migliora del 39%, che era l'obiettivo della fase 2 nel piano; restiamo
circa il 9% sopra bzip2. La compressione è praticamente alla pari con la fase 1, ma
ora gestisce i binari, non lascia file intermedi, non usa `pickle` e produce un
formato validato. La validazione costa poco: circa il 6% sul tempo interno di
decompressione.

La decompressione è circa 0,8 s più lenta della fase 1 sui 17 file. Due le cause:
l'import di numpy, richiesto dalla MTF con Numba (60–85 ms per processo, che sui file
piccoli pesano: xargs.1 passa da 0,05 a 0,13 s), e la BWT inversa e la decodifica
Huffman bit per bit, ancora in Python puro. Il secondo punto è esattamente il lavoro
della fase 4.

### Le verifiche

La suite di test conta ora 72 test, tutti superati:

| File | Test | Cosa verifica |
|---|---|---|
| `test_container_format.py` | 12 | round-trip, contenitori non validi, ogni troncamento, ogni byte dell'header |
| `test_pipeline.py` | 15 | round-trip su casi limite, binari e alice29, più blocchi in serie e in parallelo, nonce, chiave sbagliata, nessun file scritto, politica dei blocchi |
| `test_file_wrappers.py` | 3 | file binario con un solo file prodotto, file malformato senza output lasciato, modi non supportati |
| `test_decoder_hardening.py` | 19 | ogni controllo della validazione, file falsificati, manomissione di ogni byte e 300 corruzioni casuali |
| `test_symbol_huffman.py` | 9 | i 7 test di Mattia più 2 sul `BitWriter` |
| `test_fast_mtf.py`, `test_zero_rle.py`, `test_sbwt_bytes.py` | 14 | i test di Mattia e Sebastiano, invariati |

### Cosa resta

- **Formato (punto 4): fatto il 23/11/2026.** Formato versione 2: tutto in big endian,
  byte `coder` nell'header (1 = Huffman), dimensione dell'header invariata (54 byte),
  La riga "Struttura esatta dell'header" del piano è chiusa.
- **Numba (punto 5): fatto il 23/11/2026.** La prima misura era circa 3,3 volte più
  lenta, perché la MTF veniva ricompilata a ogni avvio di processo. Ora Numba si carica
  solo dopo 8 MiB di simboli e usa la cache su disco: sui 17 file di testo la
  compressione richiede 3,64 s e la decompressione 3,87 s (erano 3,95 e 4,11 s senza
  Numba), con 78 test superati. A 18 MB Numba fa risparmiare il 13% in compressione e il
  5% in decompressione. Dettagli in `docs/filippo/fase3-punto4-benchmark-numba.md`.
- **Fase 4: fatta il 24/11/2026.** Decompressione sui 17 file di testo da 3,87 a
  3,09 s, sotto i 3,29 s della fase 1. Vedi il riepilogo qui sotto.
- **Fase 5.** Derivazione delle chiavi dal nonce e tag di autenticazione, che chiudono
  i due rischi residui della validazione.
- **MPI.** Le versioni MPI usano ancora la pipeline testuale.
- **Integrazione.** Il branch `fase3-pipeline` va committato e riportato in
  `integrazione`.

---

## Riepilogo complessivo: dalla fase 0 alla fase 4

*24 novembre 2026*

Confronto tra la pipeline originale (fase 0, `baseline_20261116_1218`) e quella attuale
(dopo la fase 4, `fase_4_3_mtf_inversa`), sui 17 file di testo di Canterbury e Calgary
(3,46 MB in tutto). Tempi: mediana per file, poi somma. Nella fase 0 `book1` e `book2`
giravano solo in modalità a blocchi e sono contati così.

| Misura | Fase 0 | Oggi | Variazione |
|---|---|---|---|
| **Compressione** (wall) | 15,91 s | **3,89 s** | **4,1× più veloce** (−76%) |
| Compressione (lavoro interno) | 14,21 s | 2,43 s | 5,8× più veloce |
| **Decompressione** (wall) | 3,22 s | **3,09 s** | −4% |
| Decompressione (lavoro interno) | 2,44 s | 1,54 s | −37% |
| **Dimensione compressa** | 1.743.298 B | **1.062.942 B** | **−39%** |
| Rapporto di compressione | 1,99 | **3,26** | |
| Picco di memoria in compressione\* | 2,57 GB | 1,07 GB | −59% |
| Picco di memoria in decompressione\* | 747 MB | 670 MB | −10% |
| File supportati (25 tra Canterbury e Calgary) | 20 ok, gli altri non supportati | **25 ok, binari compresi** | |

\* Somma dei picchi dei singoli file: serve a confrontare le due colonne, non è un
consumo contemporaneo.

### Da dove vengono i guadagni

- **Compressione più veloce:** quasi tutto dalla fase 1 (suffix array con divsufsort),
  che l'ha portata da 15,9 a 3,8 s.
- **File più piccoli:** dalla fase 3 (pipeline a byte con Zero-RLE e Huffman canonico).
- **Decompressione:** la fase 3 l'aveva rallentata fino a 3,87 s (nuovo formato,
  controlli contro i file manomessi, decodifica in Python). La fase 4 l'ha riportata
  sotto il punto di partenza. Il lavoro interno cala del 37%; il tempo wall cala poco
  perché ormai metà di quei 3,09 s è l'avvio di ogni processo (interprete e import,
  circa 0,09 s per file).
- **Robustezza:** il decoder rifiuta i file corrotti o manomessi invece di bloccarsi o
  produrre dati sbagliati, e la pipeline gestisce anche i file binari.

### La fase 4 stadio per stadio

Decompressione sui 17 file di testo (tempo wall e lavoro interno):

| Momento | Wall | Interno | Resoconto |
|---|---|---|---|
| Fase 1 (riferimento) | 3,29 s | — | |
| Inizio fase 4 | 3,87 s | 2,61 s | `fase3-punto4-benchmark-numba.md` |
| Stadio 1, decodifica Huffman | 3,30 s | 2,14 s | `docs/mattia/fase4-stadio1-huffman.md` |
| Stadio 2, BWT inversa | 3,19 s | 1,69 s | `docs/sebastiano/fase4-stadio2-bwt-inversa.md`, `docs/filippo/fase4-stadio2-pointer-jumping.md` |
| Stadio 3, MTF inversa | **3,09 s** | **1,54 s** | `docs/filippo/fase4-stadio3-mtf-inversa.md` |

### Confronto con bzip2 -9 (stessi 17 file)

| | bzip2 | Noi |
|---|---|---|
| Dimensione | 976.577 B | 1.062.942 B (**+8,8%**; in fase 0 era +78,5%) |
| Compressione | 0,35 s | 3,89 s |
| Decompressione | 0,29 s | 3,09 s |

Sulla dimensione siamo vicini a bzip2. Sui tempi restiamo circa 10 volte più lenti:
bzip2 è C puro, mentre noi siamo in Python con librerie C. Inoltre facciamo lavoro che
bzip2 non fa: ordinamento segreto, catena di hash della bMTF e controlli sui file
manomessi.
