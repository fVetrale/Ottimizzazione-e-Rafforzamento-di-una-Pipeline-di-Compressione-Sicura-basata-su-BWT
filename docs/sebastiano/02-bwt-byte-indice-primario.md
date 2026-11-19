# Modifica 2 — BWT su byte con indice primario

## Scopo

Il punto 3 del `WORKFLOW.md` chiede di rimuovere la sentinella `\003` e salvare l’indice primario di ogni blocco. Questo passo aggiunge l’API BWT a byte necessaria per farlo, lasciando intatta l’API testuale legacy usata dalla pipeline attuale.

## File modificati

- `src/sbwt/sbwt.py` — aggiunte `bwt_bytes()` e `ibwt_bytes()`.
- `docs/sebastiano/02-bwt-byte-indice-primario.md` — questo report.

## Come funziona prima

La pipeline aggiunge `\003` alla stringa prima della BWT. L’ordinamento segreto forza quella sentinella in prima posizione; l’inversa parte implicitamente dalla riga che la contiene e rimuove il simbolo finale. Questo sottrae un simbolo disponibile ai dati e richiede che il file sia testo.

## Come funziona ora nell’API nuova

`bwt_bytes(data, key)` prende byte, costruisce l’array dei suffissi su due copie del blocco con `divsufsort` (la libreria nativa introdotta nella Fase 1) e seleziona le rotazioni che iniziano nella prima copia. Restituisce la colonna BWT come `bytes` e l’indice della riga della rotazione originale (indice primario). Non aggiunge alcun simbolo ai dati.

`ibwt_bytes(last_column, key, primary_index)` usa l’indice primario come riga iniziale, calcola i ranghi delle occorrenze e applica il mapping LF in ordine inverso. Restituisce il blocco come `bytes`. Controlla il tipo del dato e che l’indice sia nell’intervallo valido.

## Compatibilità e dipendenze

Le funzioni esistenti `bwt_from_suffix()` e `ibwt_from_suffix()` non sono state rimosse, quindi il programma attuale continua a usare il percorso con sentinella finché il successivo passo non collega le API byte alla pipeline. Dopo il merge della Fase 1, anche `bwt_bytes()` usa il suffix array nativo `divsufsort`; DC3 resta disponibile per il confronto. L’ordinamento segreto usa ancora la logica esistente; la sostituzione del generatore casuale appartiene alla Fase 5.

L’indice primario e la dimensione effettiva di ciascun blocco dovranno essere scritti e letti insieme nel contenitore del passo 1. La codifica MTF/RLE/Huffman deve poter consumare i byte BWT senza passare per una stringa Unicode; questa integrazione sarà un passo separato.

## Verifica prevista

Verifiche aggiunte dopo il merge della Fase 1: round-trip con `divsufsort` su input vuoto, blocco singolo, simboli ripetuti, byte nulli e tutti i valori 0–255; confronto del risultato con DC3 sugli stessi dati; controlli per indici primari invalidi. I test vengono eseguiti prima del commit.
