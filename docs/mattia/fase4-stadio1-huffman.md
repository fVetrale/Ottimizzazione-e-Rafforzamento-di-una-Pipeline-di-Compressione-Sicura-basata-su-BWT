### Stadio 1: velocizzare la decodifica Huffman

L'implementazione delle modifiche è **completata**.

### Cosa è stato fatto in `src/pc/symbol_huffman.py`:

1. **Tabella di lookup (`_build_lookup_table`)**:
   - Mappa le sequenze di $L$ bit a `(simbolo, lunghezza_codice)` replicando i codici prefissi.
   - Selezione di $L$ con `_choose_table_bits`: calibrata a $\min(\text{max\_len}, 8)$ per file piccoli ($< 2048$ simboli, come i file da 4 KB del benchmark) e $\min(\text{max\_len}, 10)$ per stream più grandi, evitando l'overhead di allocazione e garantendo che non dipenda mai da `MAX_CODE_LENGTH = 64`.

2. **Via lenta di fallback**:
   - Se un codice ha lunghezza $> L$, la tabella contiene `None` e la decodifica di quel simbolo passa per l'albero canonico (`build_decode_tree`).

3. **Accumulatore di bit e correzione critica**:
   - La lettura avviene a blocchi di byte con buffer intero.
   - **Fix critico applicato**: l'accumulatore `bit_accum` viene ora mascherato (`bit_accum &= (1 << bits_in_accum) - 1`) ad ogni simbolo consumato, impedendo che cresca indefinitamente creando un costo quadratico $O(n^2)$ (lo stesso bug che era presente in `BitWriter`).

4. **Tutti i vincoli di sicurezza e validazione preservati**:
   - `validate_code_lengths` eseguito a monte prima di allocare la tabella.
   - Caso speciale per singolo simbolo gestito immediatamente.
   - Verifica di fine flusso: con padding di zeri su $L$ bit per guardare in avanti a fine stream, un codice non viene accettato se la sua lunghezza supera i bit realmente residui (`length > bits_remaining`).
   - Controllo byte in eccesso conteggiando i bit effettivi consumati (`expected_bytes = ceil(bits_consumed / 8)`).
   - Controllo che i bit di riempimento finali siano esattamente zero.

---

### Segnalazione su `BitReader` e `build_decode_tree`:

- **`BitReader`**: **Resta inutilizzato** nella decodifica, poiché la lettura bit-per-bit è stata sostituita dall'accumulatore a blocchi con lookup. È stato mantenuto intatto nel file come richiesto.
- **`build_decode_tree`**: **È ancora utilizzato** come fallback per la via lenta (costruito solo quando $\max(\text{lengths}) > L$).
