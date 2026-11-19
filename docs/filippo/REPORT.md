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
