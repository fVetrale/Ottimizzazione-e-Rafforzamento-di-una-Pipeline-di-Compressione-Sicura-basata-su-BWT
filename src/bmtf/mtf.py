from typing import List

try:
    import bmtf.fast_mtf as fast_mtf
except ImportError:
    try:
        from . import fast_mtf
    except ImportError:
        import fast_mtf


def encode(plain_text: str, dictionary) -> List[int]:
    """
    Esegue la trasformata Move-To-Front (MTF).
    Ottimizzato con Numba su array contigui a dimensione fissa.
    """
    return fast_mtf.fast_mtf_encode(plain_text, dictionary)


def decode(compressed_text: List[int], dictionary) -> str:
    """
    Esegue la trasformata inversa Move-To-Front (I-MTF).
    Ottimizzato con Numba su array contigui a dimensione fissa.
    """
    return fast_mtf.fast_mtf_decode(compressed_text, dictionary)


if __name__ == "__main__":
    input_text = "bananaaa"
    dictionary = "abcdefghijklmnopqrstuvwxyz"
    encoded_list = encode(input_text, dictionary)
    print("CODIFICA: " + str(encoded_list))
    decoded_text = decode(encoded_list, dictionary)
    print("DECODIFICA: " + str(decoded_text))
    assert decoded_text == input_text
