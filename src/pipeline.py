"""Byte pipeline of the secure compressor (phase 3).

    compress:   sBWT per block -> bMTF -> Zero-RLE -> canonical Huffman -> container
    decompress: container -> Huffman -> Zero-RLE -> bMTF -> inverse sBWT per block

Everything works on ``bytes`` and in memory: there is no sentinel, no
intermediate file and no ``pickle``. The only output is the container defined
in ``container_format``, which is fully validated before decoding starts.

Keys. A random nonce is drawn for every compression and stored in clear in the
container. The key used by the transforms is ``nonce.hex() + key``, so the same
file compressed twice with the same key gives two different outputs. This takes
over the role of the random value ``r`` that the original pipeline wrote to
``rfile.txt``. Proper key derivation and authentication belong to phase 5.

Alphabet. The bMTF always starts from the full byte alphabet 0..255 permuted by
the key, so the decoder needs no alphabet and the container does not reveal
which byte values occur in the input.
"""

import multiprocessing
import os
import time
from contextlib import contextmanager

import container_format as cf
import bmtf.bmtf as bmtf
from pc.symbol_huffman import (
    deserialize_code_lengths,
    huffman_decode_symbols,
    huffman_encode_symbols,
    serialize_code_lengths,
)
from rle.zero_rle import zero_rle_decode, zero_rle_encode
from sbwt.sbwt import bwt_bytes, ibwt_bytes


# BWT blocks. The original pipeline split the file into one block per core
# (256 KB - 2 MB) because DC3 was slow and parallelism paid off. With
# divsufsort a 256 KB block takes about 0.1 s, less than starting a "spawn"
# pool (about 0.15 s), and small blocks also compress text worse. So blocks
# have a fixed size, like bzip2 -9 (900 KB), and the pool is used only for
# inputs large enough to amortize its start-up cost.
BWT_BLOCK_SIZE = 900 * 1024
PARALLEL_THRESHOLD = 4 * 1024 * 1024   # about 5 blocks

MIN_BMTF_BLOCK = 10 * 1024        # smaller blocks weaken the bMTF permutation
MAX_BMTF_BLOCK = 8 * 1024 * 1024

BYTE_ALPHABET = list(range(256))


def choose_bwt_block_size(size: int) -> int:
    """BWT block size: fixed, so the ratio does not depend on the machine."""
    return BWT_BLOCK_SIZE


def choose_processes(size: int) -> int:
    """Worker processes for an input of ``size`` bytes: 1 below the threshold."""
    if size < PARALLEL_THRESHOLD:
        return 1
    return multiprocessing.cpu_count()


def choose_bmtf_block_size(size: int) -> int:
    """bMTF block size, same formula as the original pipeline."""
    return max(MIN_BMTF_BLOCK, min(size // len(BYTE_ALPHABET), MAX_BMTF_BLOCK))


def transform_key(nonce: bytes, key: str) -> str:
    """Key used by sBWT and bMTF for one container."""
    if not isinstance(key, str):
        raise TypeError("key must be a string")
    return nonce.hex() + key


def _bwt_task(args):
    block, key = args
    return bwt_bytes(block, key)


def _ibwt_task(args):
    block, key, primary_index = args
    return ibwt_bytes(block, key, primary_index)


def _map_blocks(function, tasks, processes):
    """Run ``function`` on every task, in parallel only when it pays off.

    Workers are started with "spawn", not "fork": the native libraries
    (numpy, pydivsufsort) may already have started threads in this process,
    and forking a multi-threaded process can leave a child deadlocked on a
    lock held by a thread that does not exist in the child. "spawn" is also
    the only method on Windows, so every platform behaves the same way.
    Callers must keep the usual ``if __name__ == "__main__":`` guard.
    """
    if processes <= 1 or len(tasks) <= 1:
        return [function(task) for task in tasks]
    context = multiprocessing.get_context("spawn")
    with context.Pool(min(processes, len(tasks))) as pool:
        return pool.map(function, tasks)  # map keeps the block order


@contextmanager
def _stage(timings, name):
    """Record the duration of one stage in ``timings`` (if a dict is given).

    Stage names match the ones printed by the original pipeline, so the
    benchmark can compare stage times with the phase-0 baseline.
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        if timings is not None:
            timings[name] = time.perf_counter() - start


def _split(data: bytes, block_size: int) -> list[bytes]:
    return [data[start:start + block_size] for start in range(0, len(data), block_size)]


def compress_bytes(data: bytes, key: str, *, bwt_block_size: int | None = None,
                   processes: int | None = None, nonce: bytes | None = None,
                   timings: dict | None = None) -> bytes:
    """Compress ``data`` and return one serialized container.

    ``bwt_block_size``, ``processes`` and ``nonce`` exist for tests and
    benchmarks; by default the block size is BWT_BLOCK_SIZE, the number of
    processes follows ``choose_processes`` and a fresh random nonce is used.
    If ``timings`` is a dict, the duration of every stage is stored in it.
    """
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("data must be bytes")
    data = bytes(data)
    processes = processes or choose_processes(len(data))
    nonce = os.urandom(cf.NONCE_SIZE) if nonce is None else nonce
    if not isinstance(nonce, bytes) or len(nonce) != cf.NONCE_SIZE:
        raise ValueError(f"nonce must contain exactly {cf.NONCE_SIZE} bytes")
    secret = transform_key(nonce, key)

    if bwt_block_size is None:
        bwt_block_size = choose_bwt_block_size(len(data))
    bmtf_block_size = choose_bmtf_block_size(len(data))

    if not data:
        return cf.serialize(cf.Container(
            original_size=0, bwt_block_size=bwt_block_size, bmtf_block_size=bmtf_block_size,
            primary_indices=(), symbol_count=0, payload=b"", nonce=nonce,
        ))

    # 1. sBWT, one primary index per block instead of a sentinel.
    with _stage(timings, "sBWT"):
        blocks = _split(data, bwt_block_size)
        results = _map_blocks(_bwt_task, [(block, secret) for block in blocks], processes)
        transformed = b"".join(block for block, _ in results)
        primary_indices = tuple(index for _, index in results)

    # 2. bMTF on the whole BWT output, 3. Zero-RLE, 4. canonical Huffman.
    with _stage(timings, "bMTF"):
        ranks = bmtf.secure_encode(transformed, BYTE_ALPHABET, secret, bmtf_block_size)
    with _stage(timings, "RLE"):
        symbols = zero_rle_encode(ranks)
    with _stage(timings, "PC"):
        bitstream, code_lengths, symbol_count = huffman_encode_symbols(symbols)

    return cf.serialize(cf.Container(
        original_size=len(data),
        bwt_block_size=bwt_block_size,
        bmtf_block_size=bmtf_block_size,
        primary_indices=primary_indices,
        symbol_count=symbol_count,
        payload=bitstream,
        nonce=nonce,
        huffman_table=serialize_code_lengths(code_lengths),
    ))


# Zero-RLE symbols: RUNA=0, RUNB=1, MTF rank r -> r + 1, and ranks are < 256.
MAX_RLE_SYMBOL = len(BYTE_ALPHABET)


def decompress_bytes(blob: bytes, key: str, *, processes: int | None = None,
                     timings: dict | None = None,
                     max_output_size: int | None = None) -> bytes:
    """Validate a container and return the original bytes.

    The container comes from an untrusted file, so every stage checks its
    input before using it, and any decoding failure is reported as
    ``container_format.ContainerFormatError``: a malformed or manipulated file
    never crashes the decoder with another exception, never reads outside an
    array and never makes it allocate more than ``original_size`` values.

    ``original_size`` itself is declared by the file. Until the authentication
    tag of phase 5 exists, a forged header can still ask for a large output;
    ``max_output_size`` lets a caller put an upper bound on it.
    If ``timings`` is a dict, the duration of every stage is stored in it.
    """
    container = cf.parse(blob)
    if max_output_size is not None and container.original_size > max_output_size:
        raise cf.ContainerFormatError("declared size exceeds the allowed maximum")
    if container.original_size == 0:
        return b""
    # The encoder never uses smaller bMTF blocks; tiny blocks would only make
    # decoding very slow (one secret permutation of the alphabet per block).
    if container.bmtf_block_size < MIN_BMTF_BLOCK:
        raise cf.ContainerFormatError("bMTF block size below the minimum used by the encoder")
    processes = processes or choose_processes(container.original_size)
    secret = transform_key(container.nonce, key)

    try:
        return _decode(container, secret, processes, timings)
    except cf.ContainerFormatError:
        raise
    except ValueError as exc:
        raise cf.ContainerFormatError(f"corrupted payload: {exc}") from exc


def _decode(container: cf.Container, secret: str, processes: int, timings) -> bytes:
    """Decoding stages of ``decompress_bytes``; they raise ValueError on bad input."""
    with _stage(timings, "I-PC"):
        code_lengths, table_size = deserialize_code_lengths(container.huffman_table)
        if table_size != len(container.huffman_table):
            raise cf.ContainerFormatError("Huffman table length does not match its contents")
        symbols = huffman_decode_symbols(container.payload, code_lengths,
                                         container.symbol_count, max_symbol=MAX_RLE_SYMBOL)
    with _stage(timings, "I-RLE"):
        ranks = zero_rle_decode(symbols, max_output=container.original_size,
                                max_symbol=MAX_RLE_SYMBOL)
    if len(ranks) != container.original_size:
        raise cf.ContainerFormatError("decoded length does not match original_size")

    with _stage(timings, "I-BMTF"):
        transformed = bmtf.secure_decode(ranks, BYTE_ALPHABET, secret,
                                         container.bmtf_block_size, output_bytes=True)
    with _stage(timings, "I-BWT"):
        blocks = _split(transformed, container.bwt_block_size)
        tasks = [(block, secret, primary)
                 for block, primary in zip(blocks, container.primary_indices)]
        return b"".join(_map_blocks(_ibwt_task, tasks, processes))
