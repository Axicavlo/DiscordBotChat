"""Generate server corner tiles with constant RGB and antialiased alpha."""
from pathlib import Path
import struct
import zlib


def chunk(kind, data):
    return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))


def tile(color, radius=12, samples=16):
    rgb = bytes.fromhex(color)
    size = radius * 2
    rows = bytearray()
    for y in range(size):
        rows.append(0)  # PNG filter: None
        for x in range(size):
            covered = sum(
                (x + (sx + .5) / samples - radius) ** 2
                + (y + (sy + .5) / samples - radius) ** 2 <= radius ** 2
                for sy in range(samples) for sx in range(samples))
            rows.extend(rgb)
            rows.append(round(255 * covered / samples ** 2))
    header = struct.pack('!2I5B', size, size, 8, 6, 0, 0, 0)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header)
            + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))


if __name__ == '__main__':
    assets = Path(__file__).resolve().parents[1] / 'assets'
    for color in ('edf3f6', 'd7dfe5', '00a6bd', 'dce6ed', 'c7d6e0'):
        (assets / f'round-{color}-12.png').write_bytes(tile(color))
