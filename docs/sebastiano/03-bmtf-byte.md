# Modifica 3 — bMTF con simboli byte

## Scopo

Preparare la pipeline a passare i risultati della BWT come byte e simboli interi, senza dover decodificare il contenuto in Unicode per applicare la bMTF. Questo passo è indipendente dalla scelta del codec Huffman e non cambia ancora i file letti o scritti dalla pipeline.

## File modificati

- `src/bmtf/mtf.py` — MTF accetta input `bytes`; la decodifica restituisce byte quando l’alfabeto è composto da interi.
- `src/bmtf/bmtf.py` — bMTF accetta `str` o `bytes` e controlla che la dimensione del blocco sia positiva.
- `src/sbwt/customSort.py` — la permutazione restituisce esattamente l’alfabeto richiesto, evitando di aggiungere il marcatore testuale ETX a un alfabeto di interi.
- `docs/sebastiano/03-bmtf-byte.md` — questo report.

## Comportamento prima e dopo

Prima, MTF decodificava sempre con `"".join(...)`; un alfabeto di byte rappresentato da interi non era quindi restituibile come byte. Inoltre, la routine di permutazione aggiungeva sempre `\003`, anche quando il chiamante chiedeva di permutare un alfabeto numerico.

Ora, con un alfabeto di interi da 0 a 255, `secure_encode()` produce ranghi interi e `secure_decode()` restituisce `bytes`. Il parametro `output_bytes=True` preserva il tipo anche quando il blocco è vuoto e quindi l’alfabeto non contiene elementi. Con un alfabeto testuale, le funzioni continuano a restituire `str`. L’ordine segreto è limitato agli elementi forniti dal chiamante. La dimensione del blocco viene validata prima di essere usata come passo di iterazione.

## Limiti e coordinamento

Le funzioni di bMTF sono ora utilizzabili con byte, ma il chiamante `sbwt_compress.py` usa ancora la pipeline testuale precedente. La codifica RLE e il codec Huffman del progetto sono ancora testuali e vengono affrontati separatamente dopo aver coordinato l’interfaccia della Fase 2. Questo commit non sostituisce i file intermedi né rimuove `pickle`.

## Verifica

Prima del commit sono stati eseguiti round-trip su byte vuoti, tutti i valori 0–255, dati ripetuti e alfabeti con più dimensioni di blocco, oltre al round-trip testuale legacy e al controllo dei blocchi non validi.
