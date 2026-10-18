"""Read/write Tesla-compatible FSEQ V2 (uncompressed, no sparse ranges)."""

import struct

import numpy as np

HEADER_SIZE = 24


def write_fseq(path, frames: np.ndarray, step_ms: int = 20) -> None:
    """frames: uint8 array of shape (frame_count, channel_count)."""
    frames = np.ascontiguousarray(frames, dtype=np.uint8)
    frame_count, channel_count = frames.shape
    if channel_count not in (48, 200):
        raise ValueError("Tesla shows need 48 or 200 channels")
    header = bytearray(HEADER_SIZE)
    header[0:4] = b"PSEQ"
    struct.pack_into("<H", header, 4, HEADER_SIZE)   # data offset
    header[6] = 0                                    # minor
    header[7] = 2                                    # major
    struct.pack_into("<H", header, 8, HEADER_SIZE)   # variable header offset
    struct.pack_into("<I", header, 10, channel_count)
    struct.pack_into("<I", header, 14, frame_count)
    header[18] = step_ms
    header[19] = 0                                   # flags
    header[20] = 0                                   # compression: none
    header[21] = 0                                   # compression block count
    header[22] = 0                                   # sparse range count
    header[23] = 0                                   # reserved
    with open(path, "wb") as f:
        f.write(bytes(header))
        f.write(frames.tobytes())


def read_fseq(path):
    """Returns (frames uint8[frame_count, channel_count], header dict)."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != b"PSEQ":
        raise ValueError("not an FSEQ file")
    start, minor, major = struct.unpack_from("<HBB", data, 4)
    channel_count, frame_count, step_ms = struct.unpack_from("<IIB", data, 10)
    compression = data[20] & 0x0F
    header = {
        "data_offset": start, "minor": minor, "major": major,
        "channel_count": channel_count, "frame_count": frame_count,
        "step_ms": step_ms, "compression": compression,
    }
    if compression != 0:
        raise ValueError("compressed FSEQ is not supported (Tesla needs uncompressed)")
    body = np.frombuffer(data, dtype=np.uint8, count=channel_count * frame_count, offset=start)
    return body.reshape(frame_count, channel_count), header
