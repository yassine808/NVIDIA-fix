"""Generate the app icon from the page mark.

The renderer's favicon and the ``.mark`` element in
``desktop/src/renderer/index.html`` are the same shape:

    green (#76B900) square on black, with the bottom-right 30% corner cut
    off: polygon(0 0, 100% 0, 100% 70%, 70% 100%, 0 100%)

This script rasterises exactly that, so the window, the taskbar and the favicon
are one identity. Output: ``desktop/build/icon.png`` (256 px) and
``desktop/build/icon.ico`` (16-256 px, PNG frames). No third-party packages.

    python scripts/make_icon.py
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

BLACK = (0, 0, 0)
GREEN = (118, 185, 0)  # --g in the renderer

# The cut corner, in unit coordinates: the edge runs 70% -> 100% on both axes.
CUT = 0.70
SIZES = (16, 24, 32, 48, 64, 128, 256)
SUPERSAMPLE = 4


def inside(x: float, y: float) -> bool:
    """Is the point (0..1) inside the mark? Cut corner: x + y <= 1 + CUT."""
    return (x + y) <= (1.0 + CUT) + 1e-9


def raster(size: int) -> list[bytes]:
    """RGBA rows, 4x4 supersampled so the diagonal edge is not jagged."""
    n = SUPERSAMPLE
    step = 1.0 / (size * n)
    rows: list[bytes] = []
    for py in range(size):
        row = bytearray()
        for px in range(size):
            hits = 0
            for sy in range(n):
                y = (py * n + sy + 0.5) * step
                for sx in range(n):
                    x = (px * n + sx + 0.5) * step
                    if inside(x, y):
                        hits += 1
            total = n * n
            if hits == total:
                colour = GREEN
            elif hits == 0:
                colour = BLACK
            else:
                # Blend the coverage into the black background.
                a = hits / total
                colour = tuple(round(BLACK[i] + (GREEN[i] - BLACK[i]) * a) for i in range(3))
            row += bytes((colour[0], colour[1], colour[2], 255))
        rows.append(bytes(row))
    return rows


def png(size: int) -> bytes:
    raw = b"".join(b"\x00" + row for row in raster(size))
    chunk = lambda tag, data: (  # noqa: E731 - tiny local helper
        struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def ico(images: list[tuple[int, bytes]]) -> bytes:
    """ICO container holding PNG frames (supported since Vista)."""
    offset = 6 + 16 * len(images)
    entries = bytearray()
    payload = bytearray()
    for size, data in images:
        entries += struct.pack(
            "<BBBBHHII",
            size if size < 256 else 0,
            size if size < 256 else 0,
            0, 0, 1, 32, len(data), offset,
        )
        payload += data
        offset += len(data)
    return struct.pack("<HHH", 0, 1, len(images)) + bytes(entries) + bytes(payload)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    out = root / "desktop" / "build"
    out.mkdir(parents=True, exist_ok=True)

    images = [(size, png(size)) for size in SIZES]
    (out / "icon.png").write_bytes(dict(images)[256])
    (out / "icon.ico").write_bytes(ico(images))
    print(f"wrote {out / 'icon.png'} and {out / 'icon.ico'} ({', '.join(map(str, SIZES))} px)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
