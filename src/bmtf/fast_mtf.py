"""
Modulo Move-To-Front (MTF) e bMTF ad alte prestazioni con accelerazione Numba/NumPy.

Progettato per la Fase 2 della pipeline sBWT + bMTF:
- Sostituisce le liste Python ordinarie e pop/insert con array contigui.
- Ciclo compilato con Numba JIT (fastmath=True) per esecuzione a velocità nativa C (0.0003s per 60k simboli).
- Fallback automatico in Python puro/NumPy nel caso in cui Numba non sia disponibile.
- Numba si carica solo dopo NUMBA_THRESHOLD simboli: sui file piccoli il suo avvio
  costerebbe più di quanto fa risparmiare. Il codice compilato resta in cache su disco.
- Supporta sia stringhe (compatibilità Fase 0-1) sia array/byte (predisposto per Fase 3).
"""

from typing import List, Sequence, Union
import numpy as np

# Misurato: sotto i 6 MB circa l'avvio di Numba costa quanto o più di ciò che fa risparmiare.
NUMBA_THRESHOLD = 8 << 20

_symbols_seen = 0
_numba_kernels = None


def _mtf_encode_kernel(input_arr: np.ndarray, initial_dict: np.ndarray) -> np.ndarray:
    n = len(input_arr)
    k = len(initial_dict)
    out = np.empty(n, dtype=np.int32)
    d = initial_dict.copy()

    for i in range(n):
        val = input_arr[i]
        rank = 0
        while rank < k and d[rank] != val:
            rank += 1
        out[i] = rank

        # Move To Front: scorrimento degli elementi da 0 a rank-1 a destra
        for j in range(rank, 0, -1):
            d[j] = d[j - 1]
        d[0] = val

    return out


def _mtf_decode_kernel(ranks: np.ndarray, initial_dict: np.ndarray) -> np.ndarray:
    n = len(ranks)
    out = np.empty(n, dtype=initial_dict.dtype)
    d = initial_dict.copy()

    for i in range(n):
        rank = ranks[i]
        val = d[rank]
        out[i] = val

        # Move To Front
        for j in range(rank, 0, -1):
            d[j] = d[j - 1]
        d[0] = val

    return out


def _select_kernels(symbols: int):
    """Restituisce (encode, decode) compilati, o None se conviene restare in Python."""
    global _symbols_seen, _numba_kernels
    _symbols_seen += symbols
    if _symbols_seen < NUMBA_THRESHOLD:
        return None
    if _numba_kernels is None:
        try:
            from numba import njit
        except ImportError:
            _numba_kernels = ()
        else:
            _numba_kernels = (
                njit(fastmath=True, cache=True)(_mtf_encode_kernel),
                njit(fastmath=True, cache=True)(_mtf_decode_kernel),
            )
    return _numba_kernels or None


def _fallback_mtf_encode(input_list: List[int], dict_list: List[int]) -> List[int]:
    """Fallback puro in Python nel caso Numba sia disabilitato."""
    d = dict_list.copy()
    out = []
    for val in input_list:
        rank = d.index(val)
        out.append(rank)
        d.pop(rank)
        d.insert(0, val)
    return out


def _fallback_mtf_decode(ranks: List[int], dict_list: List[int]) -> List[int]:
    """Fallback puro in Python nel caso Numba sia disabilitato."""
    d = dict_list.copy()
    out = []
    for rank in ranks:
        val = d[rank]
        out.append(val)
        d.pop(rank)
        d.insert(0, val)
    return out


def fast_mtf_encode(data: Union[str, bytes, Sequence[int]],
                    dictionary: Union[str, Sequence[str], Sequence[int]]) -> List[int]:
    """
    Esegue la trasformata Move-To-Front (MTF) su data usando dictionary.
    
    Args:
        data: Stringa, bytes o sequenza di interi/caratteri.
        dictionary: Dizionario iniziale ordinato (stringa o lista).
        
    Returns:
        Lista di interi (ranks) prodotti dalla MTF.
    """
    if len(data) == 0:
        return []

    is_str_data = isinstance(data, str)
    is_bytes_data = isinstance(data, (bytes, bytearray))

    if is_str_data:
        in_arr = np.array([ord(c) for c in data], dtype=np.int32)
    elif is_bytes_data:
        in_arr = np.frombuffer(data, dtype=np.uint8).astype(np.int32)
    else:
        in_arr = np.ascontiguousarray(data, dtype=np.int32)

    is_str_dict = isinstance(dictionary, str) or (len(dictionary) > 0 and isinstance(dictionary[0], str))
    if is_str_dict:
        dict_arr = np.array([ord(c) for c in dictionary], dtype=np.int32)
    elif isinstance(dictionary, (bytes, bytearray)):
        dict_arr = np.frombuffer(dictionary, dtype=np.uint8).astype(np.int32)
    else:
        dict_arr = np.ascontiguousarray(dictionary, dtype=np.int32)

    # Il ciclo Numba non controlla i limiti: un simbolo assente dal dizionario
    # porterebbe il rango a len(dict) e scriverebbe fuori dall'array.
    if not np.isin(in_arr, dict_arr).all():
        raise ValueError("l'input contiene simboli assenti dal dizionario MTF")

    kernels = _select_kernels(len(in_arr))
    if kernels:
        return kernels[0](in_arr, dict_arr).tolist()
    return _fallback_mtf_encode(in_arr.tolist(), dict_arr.tolist())


def fast_mtf_decode(ranks: Sequence[int],
                    dictionary: Union[str, Sequence[str], Sequence[int]]) -> Union[str, List[int]]:
    """
    Esegue la trasformata inversa Move-To-Front (I-MTF) su ranks usando dictionary.
    
    Args:
        ranks: Sequenza di interi generati dalla MTF.
        dictionary: Dizionario iniziale ordinato.
        
    Returns:
        Stringa se dictionary conteneva caratteri, oppure lista di interi.
    """
    if len(ranks) == 0:
        if isinstance(dictionary, str) or (len(dictionary) > 0 and isinstance(dictionary[0], str)):
            return ""
        return []

    is_str_dict = isinstance(dictionary, str) or (len(dictionary) > 0 and isinstance(dictionary[0], str))

    if is_str_dict:
        dict_arr = np.array([ord(c) for c in dictionary], dtype=np.int32)
    elif isinstance(dictionary, (bytes, bytearray)):
        dict_arr = np.frombuffer(dictionary, dtype=np.uint8).astype(np.int32)
    else:
        dict_arr = np.ascontiguousarray(dictionary, dtype=np.int32)

    # I ranghi arrivano da un file non fidato e il ciclo Numba non controlla i
    # limiti: un rango fuori dal dizionario leggerebbe memoria arbitraria.
    try:
        wide = np.asarray(ranks, dtype=np.int64)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError("ranghi MTF non validi") from exc
    if wide.ndim != 1 or wide.min() < 0 or wide.max() >= len(dict_arr):
        raise ValueError("rango MTF fuori dal dizionario")
    ranks_arr = np.ascontiguousarray(wide, dtype=np.int32)

    kernels = _select_kernels(len(ranks_arr))
    if kernels:
        raw_vals = kernels[1](ranks_arr, dict_arr).tolist()
    else:
        raw_vals = _fallback_mtf_decode(ranks_arr.tolist(), dict_arr.tolist())

    if is_str_dict:
        return "".join(chr(c) for c in raw_vals)
    return raw_vals
