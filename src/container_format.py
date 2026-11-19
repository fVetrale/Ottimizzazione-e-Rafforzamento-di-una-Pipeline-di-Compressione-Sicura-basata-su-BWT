"""Versioned binary container for the sBWT + bMTF pipeline.

The container is the only file written by the compressor. It replaces the
nine intermediate files and the ``pickle`` serialization of the original
pipeline. Every field has a fixed type and every section a declared length,
and the whole container is validated before any section is handed to the
decoding stages. All integers use network byte order (big endian).

Layout::

    header (fixed size, see _HEADER)
    nonce               NONCE_SIZE bytes
    primary indices     block_count x uint32, one per BWT block
    metadata            metadata_size bytes (opaque, reserved)
    huffman table       huffman_table_size bytes (canonical code lengths)
    payload             payload_size bytes (Huffman bitstream)
    tag                 0 or TAG_SIZE bytes (authentication tag, phase 5)

The BWT blocks are not stored individually: they all have ``bwt_block_size``
bytes except the last one, whose length follows from ``original_size``.
"""

from dataclasses import dataclass
import struct


MAGIC = b"SBWT"
VERSION = 1
NONCE_SIZE = 16
TAG_SIZE = 32
MAX_BLOCKS = 1_000_000
MAX_METADATA_SIZE = 1 << 20
MAX_HUFFMAN_TABLE_SIZE = 1 << 20

_U32_MAX = 0xFFFFFFFF
_U64_MAX = 0xFFFFFFFFFFFFFFFF

# magic, version, flags, reserved, original_size, bwt_block_size,
# block_count, bmtf_block_size, symbol_count, metadata_size,
# huffman_table_size, payload_size, tag_size
_HEADER = struct.Struct(">4sBBHQIIIQIIQH")
_U32 = struct.Struct(">I")
HEADER_SIZE = _HEADER.size


class ContainerFormatError(ValueError):
    """Raised when a container is truncated, malformed, or unsupported."""


@dataclass(frozen=True)
class Container:
    original_size: int
    bwt_block_size: int
    bmtf_block_size: int
    primary_indices: tuple[int, ...]
    symbol_count: int
    payload: bytes
    nonce: bytes = bytes(NONCE_SIZE)
    metadata: bytes = b""
    huffman_table: bytes = b""
    tag: bytes = b""


def expected_block_count(original_size: int, bwt_block_size: int) -> int:
    """Number of BWT blocks needed to cover ``original_size`` bytes."""
    if original_size == 0:
        return 0
    return -(-original_size // bwt_block_size)


def block_length(original_size: int, bwt_block_size: int, index: int) -> int:
    """Length in bytes of BWT block ``index`` (the last one may be shorter)."""
    start = index * bwt_block_size
    return min(bwt_block_size, original_size - start)


def _check_uint(name: str, value, maximum: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= maximum:
        raise ContainerFormatError(f"{name} must be an integer in [0, {maximum}]")


def _check_bytes(name: str, value, allowed_sizes=None, maximum=None) -> None:
    if not isinstance(value, bytes):
        raise ContainerFormatError(f"{name} must be bytes")
    if allowed_sizes is not None and len(value) not in allowed_sizes:
        raise ContainerFormatError(f"{name} has an invalid length")
    if maximum is not None and len(value) > maximum:
        raise ContainerFormatError(f"{name} exceeds the configured size limit")


def validate(container: Container) -> None:
    """Check every field and the consistency between fields.

    The same checks run when writing and when reading, so a file produced by
    ``serialize`` is always accepted by ``parse`` and vice versa.
    """
    if not isinstance(container, Container):
        raise TypeError("container must be a Container")

    _check_bytes("nonce", container.nonce, allowed_sizes=(NONCE_SIZE,))
    _check_bytes("tag", container.tag, allowed_sizes=(0, TAG_SIZE))
    _check_bytes("metadata", container.metadata, maximum=MAX_METADATA_SIZE)
    _check_bytes("Huffman table", container.huffman_table, maximum=MAX_HUFFMAN_TABLE_SIZE)
    _check_bytes("payload", container.payload)

    original_size = container.original_size
    bwt_block_size = container.bwt_block_size
    _check_uint("original_size", original_size, _U64_MAX)
    _check_uint("bwt_block_size", bwt_block_size, _U32_MAX)
    _check_uint("bmtf_block_size", container.bmtf_block_size, _U32_MAX)
    _check_uint("symbol_count", container.symbol_count, _U64_MAX)

    indices = container.primary_indices
    if not isinstance(indices, tuple) or len(indices) > MAX_BLOCKS:
        raise ContainerFormatError(f"primary_indices must be a tuple of at most {MAX_BLOCKS} items")

    if original_size == 0:
        # Empty input: nothing was transformed, so nothing may be stored.
        if indices or container.symbol_count or container.payload or container.huffman_table:
            raise ContainerFormatError("an empty input cannot carry block or payload data")
        return

    if bwt_block_size == 0 or container.bmtf_block_size == 0:
        raise ContainerFormatError("block sizes must be positive for a nonempty input")
    if len(indices) != expected_block_count(original_size, bwt_block_size):
        raise ContainerFormatError("block count does not match original_size and bwt_block_size")
    for index, primary in enumerate(indices):
        _check_uint("primary index", primary, _U32_MAX)
        if primary >= block_length(original_size, bwt_block_size, index):
            raise ContainerFormatError("primary index is outside its BWT block")

    # Zero-RLE never produces more symbols than the MTF output, which has
    # exactly original_size symbols, and a nonempty input yields at least one.
    if not 1 <= container.symbol_count <= original_size:
        raise ContainerFormatError("symbol_count is inconsistent with original_size")
    if not container.huffman_table or not container.payload:
        raise ContainerFormatError("a nonempty input requires a Huffman table and a payload")


def serialize(container: Container) -> bytes:
    """Validate a container and serialize it to one byte string."""
    validate(container)
    header = _HEADER.pack(
        MAGIC, VERSION, 0, 0,
        container.original_size, container.bwt_block_size,
        len(container.primary_indices), container.bmtf_block_size,
        container.symbol_count, len(container.metadata),
        len(container.huffman_table), len(container.payload), len(container.tag),
    )
    primary_bytes = b"".join(_U32.pack(index) for index in container.primary_indices)
    return b"".join((
        header, container.nonce, primary_bytes, container.metadata,
        container.huffman_table, container.payload, container.tag,
    ))


def parse(data: bytes) -> Container:
    """Parse and fully validate a container before exposing its sections."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("container data must be bytes")
    data = bytes(data)
    if len(data) < HEADER_SIZE + NONCE_SIZE:
        raise ContainerFormatError("truncated container header")

    (magic, version, flags, reserved, original_size, bwt_block_size,
     block_count, bmtf_block_size, symbol_count, metadata_size,
     huffman_size, payload_size, tag_size) = _HEADER.unpack_from(data)
    if magic != MAGIC:
        raise ContainerFormatError("invalid container magic")
    if version != VERSION:
        raise ContainerFormatError(f"unsupported container version: {version}")
    if flags != 0 or reserved != 0:
        raise ContainerFormatError("unsupported flags or nonzero reserved field")
    # Bound the variable sections before slicing, so a forged header cannot
    # make the parser allocate or loop over more than the file contains.
    if block_count > MAX_BLOCKS:
        raise ContainerFormatError("too many blocks")
    if metadata_size > MAX_METADATA_SIZE or huffman_size > MAX_HUFFMAN_TABLE_SIZE:
        raise ContainerFormatError("metadata section exceeds configured size limit")
    if tag_size not in (0, TAG_SIZE):
        raise ContainerFormatError("invalid authentication-tag size")

    offset = HEADER_SIZE
    nonce = data[offset:offset + NONCE_SIZE]
    offset += NONCE_SIZE
    indices_size = block_count * _U32.size
    expected_size = offset + indices_size + metadata_size + huffman_size + payload_size + tag_size
    if expected_size != len(data):
        raise ContainerFormatError("section lengths do not match the container size")

    indices = tuple(_U32.unpack_from(data, offset + i * _U32.size)[0] for i in range(block_count))
    offset += indices_size
    metadata = data[offset:offset + metadata_size]
    offset += metadata_size
    huffman_table = data[offset:offset + huffman_size]
    offset += huffman_size
    payload = data[offset:offset + payload_size]
    offset += payload_size
    tag = data[offset:offset + tag_size]

    container = Container(
        original_size=original_size,
        bwt_block_size=bwt_block_size,
        bmtf_block_size=bmtf_block_size,
        primary_indices=indices,
        symbol_count=symbol_count,
        payload=payload,
        nonce=nonce,
        metadata=metadata,
        huffman_table=huffman_table,
        tag=tag,
    )
    validate(container)
    return container
