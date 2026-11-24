from typing import List

try:
    import bmtf.fast_mtf as fast_mtf
except ImportError:
    try:
        from . import fast_mtf
    except ImportError:
        import fast_mtf


def encode(plain_text: str | bytes, dictionary) -> List[int]:
    """
    Esegue la trasformata Move-To-Front (MTF).
    Ottimizzato con Numba su array contigui a dimensione fissa.
    Accetta testo (str) oppure byte (bytes).
    """
    return fast_mtf.fast_mtf_encode(plain_text, dictionary)


def decode(compressed_text: List[int], dictionary) -> str | bytes:
    """
    Esegue la trasformata inversa Move-To-Front (I-MTF).
    Restituisce str con un alfabeto di caratteri, bytes con un alfabeto di interi.
    """
    if isinstance(dictionary, str) or (len(dictionary) > 0 and isinstance(dictionary[0], str)):
        return fast_mtf.fast_mtf_decode(compressed_text, dictionary)
    # Alfabeto di interi: si producono direttamente bytes. Il controllo che ogni
    # simbolo sia in [0, 255] si fa sul dizionario (256 valori) e non più su
    # tutto l'output, perché ogni byte prodotto viene dal dizionario.
    return fast_mtf.fast_mtf_decode_bytes(compressed_text, dictionary)


if __name__ == "__main__":
    input_text = "bananaaa"
    dictionary = "abcdefghijklmnopqrstuvwxyz"
    encoded_list = encode(input_text, dictionary)
    print("CODIFICA: " + str(encoded_list))
    decoded_text = decode(encoded_list, dictionary)
    print("DECODIFICA: " + str(decoded_text))
    assert decoded_text == input_text