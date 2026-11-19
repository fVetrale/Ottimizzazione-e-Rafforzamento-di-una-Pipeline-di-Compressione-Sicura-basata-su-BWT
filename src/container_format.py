"""Versioned binary container for the sBWT + bMTF pipeline.

The container deliberately stores opaque payload and metadata bytes. Transform
stages can evolve independently while the on-disk framing remains validated.
All integers use network byte order (big endian).
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

# magic, version, flags, reserved, original_size, bwt_block_size,
# block_count, bmtf_block_size, primary_count, metadata_size,
# huffman_table_size, payload_size, tag_size
_HEADER = struct.Struct(">4sBBHQIIIII I QH".replace(" ", ""))
_U32 = struct.Struct(">I")


class ContainerFormatError(ValueError):
    """Raised when a container is truncated, malformed, or unsupported."""


@dataclass(frozen=True)
class Container:
    original_size: int
    bwt_block_size: int
    bmtf_block_size: int
    primary_indices: tuple[int, ...]
    payload: bytes
    nonce: bytes = bytes(NONCE_SIZE)
    metadata: bytes = b""
    huffman_table: bytes = b""
    tag: bytes = b""


def _check_uint(name: str, value: int, maximum: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= maximum:
        raise ContainerFormatError(f"{name} must be an integer in [0, {maximum}]")


def serialize(container: Container) -> bytes:
    """Serialize a validated container to one byte string."""
    if not isinstance(container, Container):
        raise TypeError("container must be a Container")
    if not isinstance(container.nonce, bytes) or len(container.nonce) != NONCE_SIZE:
        raise ContainerFormatError(f"nonce must contain exactly {NONCE_SIZE} bytes")
    if not isinstance(container.payload, bytes):
        raise ContainerFormatError("payload must be bytes")
    if not isinstance(container.metadata, bytes) or len(container.metadata) > MAX_METADATA_SIZE:
        raise ContainerFormatError("metadata must be bytes within the configured size limit")
    if not isinstance(container.huffman_table, bytes) or len(container.huffman_table) > MAX_HUFFMAN_TABLE_SIZE:
        raise ContainerFormatError("Huffman table must be bytes within the configured size limit")
    if not isinstance(container.tag, bytes) or len(container.tag) not in (0, TAG_SIZE):
        raise ContainerFormatError(f"tag must be empty or exactly {TAG_SIZE} bytes")

    _check_uint("original_size", container.original_size, 0xFFFFFFFFFFFFFFFF)
    _check_uint("bwt_block_size", container.bwt_block_size, 0xFFFFFFFF)
    _check_uint("bmtf_block_size", container.bmtf_block_size, 0xFFFFFFFF)
    indices = container.primary_indices
    if not isinstance(indices, tuple) or len(indices) > MAX_BLOCKS:
        raise ContainerFormatError(f"primary_indices must be a tuple of at most {MAX_BLOCKS} items")
    if len(indices) != 0 and (container.bwt_block_size == 0 or container.bmtf_block_size == 0):
        raise ContainerFormatError("nonempty block data requires nonzero block sizes")
    for index in indices:
        _check_uint("primary index", index, 0xFFFFFFFF)
        if index >= container.bwt_block_size:
            raise ContainerFormatError("primary index must be less than the BWT block size")

    header = _HEADER.pack(
        MAGIC, VERSION, 0, 0, container.original_size,
        container.bwt_block_size, len(indices), container.bmtf_block_size,
        len(indices), len(container.metadata), len(container.huffman_table),
        len(container.payload), len(container.tag),
    )
    primary_bytes = b"".join(_U32.pack(index) for index in indices)
    return header + container.nonce + primary_bytes + container.metadata + container.huffman_table + container.payload + container.tag


def parse(data: bytes) -> Container:
    """Parse and validate a complete container before exposing its payload."""
    if not isinstance(data, bytes):
        raise TypeError("container data must be bytes")
    if len(data) < _HEADER.size + NONCE_SIZE:
        raise ContainerFormatError("truncated container header")

    (magic, version, flags, reserved, original_size, bwt_block_size,
     block_count, bmtf_block_size, primary_count, metadata_size,
     huffman_size, payload_size, tag_size) = _HEADER.unpack_from(data)
    if magic != MAGIC:
        raise ContainerFormatError("invalid container magic")
    if version != VERSION:
        raise ContainerFormatError(f"unsupported container version: {version}")
    if flags != 0 or reserved != 0:
        raise ContainerFormatError("unsupported flags or nonzero reserved field")
    if block_count > MAX_BLOCKS or primary_count != block_count:
        raise ContainerFormatError("invalid block or primary-index count")
    if metadata_size > MAX_METADATA_SIZE or huffman_size > MAX_HUFFMAN_TABLE_SIZE:
        raise ContainerFormatError("metadata section exceeds configured size limit")
    if tag_size not in (0, TAG_SIZE):
        raise ContainerFormatError("invalid authentication-tag size")
    if block_count and (bwt_block_size == 0 or bmtf_block_size == 0):
        raise ContainerFormatError("nonempty block data has a zero block size")

    offset = _HEADER.size
    nonce = data[offset:offset + NONCE_SIZE]
    offset += NONCE_SIZE
    indices_size = primary_count * _U32.size
    expected_size = offset + indices_size + metadata_size + huffman_size + payload_size + tag_size
    if expected_size != len(data):
        raise ContainerFormatError("section lengths do not match the container size")

    indices = tuple(_U32.unpack_from(data, offset + i * _U32.size)[0] for i in range(primary_count))
    if any(index >= bwt_block_size for index in indices):
        raise ContainerFormatError("primary index is outside its BWT block")
    offset += indices_size
    metadata = data[offset:offset + metadata_size]
    offset += metadata_size
    huffman_table = data[offset:offset + huffman_size]
    offset += huffman_size
    payload = data[offset:offset + payload_size]
    offset += payload_size
    tag = data[offset:offset + tag_size]

    return Container(
        original_size=original_size,
        bwt_block_size=bwt_block_size,
        bmtf_block_size=bmtf_block_size,
        primary_indices=indices,
        payload=payload,
        nonce=nonce,
        metadata=metadata,
        huffman_table=huffman_table,
        tag=tag,
    )
