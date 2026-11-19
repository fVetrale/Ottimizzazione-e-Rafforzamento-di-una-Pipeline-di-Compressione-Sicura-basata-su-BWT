# Modifica 1 — Struttura iniziale del contenitore binario

## Scopo

Il punto 3 del `WORKFLOW.md` richiede un file unico con header e payload, campi tipizzati e lunghezze verificabili, in sostituzione della serializzazione `pickle`. Questo primo intervento introduce il formato e le sue funzioni di serializzazione/lettura, senza ancora cambiare il flusso di compressione esistente.

## File modificati

- `src/container_format.py` — nuovo modulo che definisce il contenitore versione 1.
- `docs/sebastiano/01-contenitore-binario.md` — questo report.

## Struttura definita

Il file è composto da header a dimensione fissa e sezioni contigue:

1. magic `SBWT`, versione, flag riservati;
2. dimensione originale e dimensioni/numero dei blocchi sBWT e bMTF;
3. conteggio e valori degli indici primari, uno per blocco;
4. nonce di 16 byte;
5. metadati facoltativi (per esempio alfabeto, se la pipeline lo richiederà);
6. tabella Huffman facoltativa;
7. payload opaco in byte;
8. tag facoltativo di 32 byte, per lasciare spazio all’integrazione HMAC della Fase 5.

Gli interi sono codificati in big endian. Il payload resta opaco: il formato non presume ancora se la Fase 2 fornirà simboli RLE interi o byte compressi.

## Validazioni implementate

`serialize()` rifiuta tipi errati, nonce/tag di dimensione non prevista, conteggi fuori limite e indici primari oltre il blocco. `parse()` verifica magic e versione, flag riservati, limiti delle sezioni e coerenza tra lunghezze dichiarate e dimensione effettiva del file prima di restituire le sezioni. Non deserializza oggetti Python e non può eseguire codice come `pickle`.

## Cosa cambia nel comportamento attuale

Per ora non cambia ancora: `sbwt_compress.py`, `decompression.py` e `pc.py` continuano a usare i file intermedi. Questo commit crea il componente di framing isolato che i prossimi passi collegheranno alla pipeline. È intenzionale, perché l’interfaccia del payload dipende anche dalle Fasi 1–2 e va coordinata con chi le implementa.

## Interferenze da coordinare

- **Fase 2:** confermare il formato della tabella Huffman e del payload compresso. Il contenitore accetta per ora entrambe le sezioni come byte opachi.
- **Fase 5:** concordare il nonce (qui fissato provvisoriamente a 16 byte) e la copertura esatta del tag HMAC. Il tag è previsto nel contenitore ma non viene ancora calcolato o verificato.
- **Fase 1/4:** definire il significato dell’indice primario e i confini dei blocchi affinché compressore e decompressore usino lo stesso ordinamento.

## Limite di questo passo

Questo modulo da solo non rende ancora la pipeline byte-safe, non rimuove la sentinella, non elimina gli intermedi e non integra il contenitore nei comandi esistenti. Sono i passi successivi del punto 3.
