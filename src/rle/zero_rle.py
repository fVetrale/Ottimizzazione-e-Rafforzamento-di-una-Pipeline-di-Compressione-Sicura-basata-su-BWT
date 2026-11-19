"""
Modulo per la RLE binaria (Zero-Run Encoding) in stile bzip2.

Dopo BWT + MTF, la maggioranza assoluta dei simboli è costituita da zeri.
Questo modulo comprime esclusivamente le sequenze di zeri consecutivi usando
la rappresentazione binaria biiettiva (1-based) con i simboli RUNA e RUNB.

- Valori MTF == 0:
    Le sequenze di N zeri consecutivi (N >= 1) vengono codificate con i simboli
    RUNA (valore 0, peso 1) e RUNB (valore 1, peso 2).
    Esempi:
      N = 1 -> [RUNA]
      N = 2 -> [RUNB]
      N = 3 -> [RUNA, RUNA]
      N = 4 -> [RUNB, RUNA]
      N = 5 -> [RUNA, RUNB]
      N = 6 -> [RUNB, RUNB]
      N = 7 -> [RUNA, RUNA, RUNA]

- Valori MTF > 0:
    Vengono traslati di 1: (v + 1), poiché i simboli 0 e 1 sono riservati
    a RUNA e RUNB.
    Esempi:
      v = 1 -> 2
      v = 2 -> 3
      v = k -> k + 1
"""

from typing import List, Optional, Sequence, Union
import numpy as np

RUNA = 0
RUNB = 1


def zero_rle_encode(data: Union[Sequence[int], np.ndarray]) -> List[int]:
    """
    Codifica una sequenza di interi non negativi (output tipico di MTF)
    in una sequenza di simboli interi usando la RLE stile bzip2 su zeri.
    
    Args:
        data: Sequenza o array di interi non negativi (es. output MTF).
        
    Returns:
        Lista di simboli interi dove 0=RUNA, 1=RUNB, e valori >= 2 sono (valore_originale + 1).
    """
    output: List[int] = []
    zero_run = 0

    for val in data:
        if val == 0:
            zero_run += 1
        else:
            if zero_run > 0:
                while zero_run > 0:
                    if zero_run % 2 == 1:
                        output.append(RUNA)
                        zero_run = (zero_run - 1) // 2
                    else:
                        output.append(RUNB)
                        zero_run = (zero_run - 2) // 2
            output.append(int(val) + 1)

    if zero_run > 0:
        while zero_run > 0:
            if zero_run % 2 == 1:
                output.append(RUNA)
                zero_run = (zero_run - 1) // 2
            else:
                output.append(RUNB)
                zero_run = (zero_run - 2) // 2

    return output


def zero_rle_decode(encoded: Union[Sequence[int], np.ndarray],
                    max_output: Optional[int] = None,
                    max_symbol: Optional[int] = None) -> List[int]:
    """
    Decodifica una sequenza di simboli interi prodotti da zero_rle_encode,
    ricostruendo l'esatta sequenza originale di interi MTF.

    Args:
        encoded: Sequenza o array di simboli interi (RUNA=0, RUNB=1, valori >= 2).
        max_output: se indicato, numero massimo di valori da produrre. Pochi
            simboli RUNB bastano a chiedere miliardi di zeri ("decompression
            bomb"): il limite viene controllato prima di allocare la sequenza.
        max_symbol: se indicato, valore massimo ammesso per un simbolo.

    Returns:
        Lista originale di interi MTF.

    Raises:
        ValueError: simbolo negativo o oltre max_symbol, oppure output oltre max_output.
    """
    output: List[int] = []
    i = 0
    n = len(encoded)

    while i < n:
        sym = int(encoded[i])
        if sym < 0 or (max_symbol is not None and sym > max_symbol):
            raise ValueError(f"simbolo Zero-RLE non valido: {sym}")
        if sym == RUNA or sym == RUNB:
            run_length = 0
            multiplier = 1
            while i < n and (encoded[i] == RUNA or encoded[i] == RUNB):
                if encoded[i] == RUNA:
                    run_length += 1 * multiplier
                else:
                    run_length += 2 * multiplier
                multiplier *= 2
                i += 1
                if max_output is not None and len(output) + run_length > max_output:
                    raise ValueError("la sequenza di zeri supera la lunghezza dichiarata")
            output.extend([0] * run_length)
        else:
            if max_output is not None and len(output) >= max_output:
                raise ValueError("la sequenza decodificata supera la lunghezza dichiarata")
            output.append(sym - 1)
            i += 1

    return output
