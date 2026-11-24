### Cosa è stato fatto e perché

#### 1. Calcolo vettoriale della mappatura LF con NumPy
Prima di questa modifica, la mappatura LF veniva costruita con due dizionari Python (`counts` e `starts`) e due cicli espliciti:
1. un ciclo su tutti i simboli di `last_column` per contare le occorrenze e assegnare i ranghi individuali;
2. un ciclo su `ordered_alphabet` per calcolare le posizioni cumulative `starts`.

Nel nuovo flusso, l'intera fase di conteggio e lookup è sostituita da operazioni vettorizzate in C tramite NumPy:
- **Tabella di lookup da 256 voci (`dtype=np.uint8`)**:
  ```python
  table = np.zeros(256, dtype=np.uint8)
  for rank, byte_val in enumerate(ordered_alphabet):
      table[byte_val] = rank
  ```
  La tabella mappa istantaneamente ciascun byte presente nel blocco alla sua posizione nell'ordine segreto.
- **Ridenominazione vettoriale a zero-copy**:
  ```python
  mapped = table[np.frombuffer(last_column, dtype=np.uint8)]
  ```
  `np.frombuffer` avvolge il buffer `bytes` senza duplicare memoria; l'indicizzazione vettoriale genera l'array `mapped` contenente i ranghi segreti.
- **`argsort` stabile**:
  ```python
  P = np.argsort(mapped, kind="stable")
  ```
  Poiché `mapped` ha tipo `uint8`, NumPy esegue un ordinamento lineare (radix/counting sort). Il vettore risultante $P$ contiene, per ogni riga $j$ della prima colonna $F$, l'indice originario in `last_column` ($L$).
- **Inversione della permutazione ($LF$)**:
  Dalla proprietà fondamentale della BWT, la mappatura $LF(i)$ è la posizione in colonna $F$ del simbolo $L[i]$. Essendo $P[j] = i$, la mappatura $LF$ è la **permutazione inversa** di $P$:
  ```python
  lf = np.empty(n, dtype=np.intp)
  lf[P] = np.arange(n, dtype=np.intp)
  ```
  Questa singola assegnazione vettoriale calcola $LF[i]$ per tutti gli $n$ elementi simultaneamente, eliminando completamente `starts[symbol] + ranks[row]`.

---

#### 2. Ciclo di attraversamento e confronto `.tolist()` vs NumPy
Il ciclo finale di ricostruzione percorre la mappatura a ritroso per $n$ passi:
```python
lf_list = lf.tolist()

result = bytearray(n)
row = primary_index
for position in range(n - 1, -1, -1):
    result[position] = last_column[row]
    row = lf_list[row]
return bytes(result)
```

**Perché `.tolist()` conviene nettamente rispetto a indicizzare l'array NumPy:**
- In un ciclo Python puro che itera centinaia di migliaia di volte (es. blocchi da 256 KB o 1 MB), accedere a un array NumPy (`row = lf[row]`) costringe l'interprete a invocare `ndarray.__getitem__` a ogni giro. Questo alloca un nuovo oggetto scalare `numpy.int64` nell'heap, che deve poi essere convertito in un indice intero C per la lettura successiva da `last_column`.
- La conversione `lf.tolist()` viene eseguita **una sola volta in C** all'uscita dal calcolo vettoriale.
- All'interno del ciclo, `lf_list[row]` è una normale indicizzazione su lista Python (`list->ob_item[row]` in CPython): non c'è allocazione di oggetti, non c'è wrapping scalare e il byte `last_column[row]` viene inserito direttamente nel `bytearray`.

---

### Rispetto puntuale di tutti i vincoli

1. **Modifica isolata:** modificata esclusivamente la funzione `ibwt_bytes`. Nessuna riga di `bwt_bytes`, `ibwt_from_suffix`, della gestione delle chiavi o del formato del file è stata toccata.
2. **Ordine segreto invariato:** `alphabet`, `secret_order` e `ordered_alphabet` vengono derivati con le identiche chiamate originali (`customSort.getSecretSort`).
3. **Nessun modulo C proprietario né Numba:** utilizzata esclusivamente la libreria standard e `numpy`.
4. **Resilienza su file manomessi o corrotti:**
   - La permutazione inversa `lf` contiene per costruzione esclusivamente indici compresi nell'intervallo $[0, n-1]$.
   - Anche in presenza di cicli multipli o dati arbitrariamente alterati, `lf_list[row]` non può mai sollevare un `IndexError`.
   - Il ciclo è rigorosamente delimitato da `range(n - 1, -1, -1)`: termina esattamente dopo $n$ iterazioni senza possibilità di cicli infiniti.
   - A parità di input valido o non valido, la traiettoria percorsa è identica alla vecchia formulazione `starts[symbol] + ranks[row]`.
5. **Validazione iniziale preservata:** i controlli di tipo su `last_column`, sul blocco vuoto (`if not last_column: if primary_index != 0: ...`) e su `primary_index` sono rimasti identici.
6. **Serializzabilità con multiprocessing `spawn`:** `ibwt_bytes` rimane una normale funzione a livello di modulo serializzabile da `multiprocessing`.
7. **Nessun test o benchmark eseguito**, in conformità con la direttiva finale.