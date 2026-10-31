"""Can the damaged samples be re-framed?

For samples whose stated offset does not parse, look nearby:
  * all length-prefix widths (1, 2, 4 bytes)
  * offsets in [start-SEARCH, start+SEARCH]

Reports, per time bucket, how many samples parse as-is, how many parse after a
small shift, and the distribution of shifts. Read-only.
"""
from __future__ import annotations

import json
import struct
import sys
from collections import Counter

import mp4_probe as P
from sample_map import Reader
from bitstream_map import load_tracks

VIDEO = r"recovery/Arc_Raiders corrupted.mp4"
OK_TYPES = {1, 5, 6, 7, 8, 9}
SEARCH = 4096


def chain_at(blob: bytes, p: int, size: int, lw: int) -> int:
    """NALs parsed from blob[p:p+size] with length width lw; -1 if implausible."""
    end = p + size
    q = p
    n = 0
    while q + lw <= end and n < 64:
        if lw == 4:
            ln = struct.unpack_from(">I", blob, q)[0]
        elif lw == 2:
            ln = struct.unpack_from(">H", blob, q)[0]
        else:
            ln = blob[q]
        if ln < 1 or q + lw + ln > end:
            return -1
        if (blob[q + lw] & 0x1F) not in OK_TYPES:
            return -1
        q += lw + ln
        n += 1
    return n if q == end else -1


def parse_as_is(blob: bytes, base: int, sz: int):
    """Length width that parses this sample in place, or None."""
    for lw in (4, 2, 1):
        if chain_at(blob, base, sz, lw) > 0:
            return lw
    return None


def find_shift(blob: bytes, base: int, sz: int):
    """Nearest (delta, length_width) that parses, or None."""
    for d in range(-SEARCH, SEARCH + 1):
        p = base + d
        if p < 0 or p + sz > len(blob):
            continue
        lw = parse_as_is(blob, p, sz)
        if lw is not None:
            return d, lw
    return None


def classify_samples(r: Reader, picked):
    """Count as-is / shifted / dead samples and the shift histogram."""
    stat = Counter()
    shifts = Counter()
    for off, sz, _si in picked:
        span = r.read(max(0, off - SEARCH), sz + 2 * SEARCH)
        base = SEARCH if off >= SEARCH else off
        if parse_as_is(span, base, sz) is not None:
            stat["as_is"] += 1
            shifts[0] += 1
            continue
        found = find_shift(span, base, sz)
        if found:
            stat["shifted"] += 1
            shifts[found[0]] += 1
        else:
            stat["dead"] += 1
    return stat, shifts


def probe_centre(r: Reader, intervals, centre: int):
    """Classify the samples in one 120-frame bucket around `centre` seconds."""
    t0 = centre * 120
    picked = [iv for iv in intervals if t0 <= iv[2] < t0 + 120]
    if len(picked) > 240:
        picked = picked[::max(1, len(picked) // 240)]
    stat, shifts = classify_samples(r, picked)
    tot = max(1, sum(stat.values()))
    print("t=%3d  n=%3d  as-is %5.1f%%  shifted %5.1f%%  dead %5.1f%%  shifts %s"
          % (centre, tot, 100.0 * stat["as_is"] / tot,
             100.0 * stat["shifted"] / tot, 100.0 * stat["dead"] / tot,
             dict(shifts.most_common(5))))
    return {"t": centre, "n": tot, "as_is": stat["as_is"],
            "shifted": stat["shifted"], "dead": stat["dead"],
            "shift_hist": dict(shifts.most_common(8))}


def main() -> int:
    tracks, _top, _size = load_tracks(VIDEO)
    vtr = next(t for t in tracks if t.get("handler") == "vide")
    intervals = vtr["intervals"]

    r = Reader(VIDEO, window=32 << 20)
    out = [probe_centre(r, intervals, centre)
           for centre in (5, 30, 60, 90, 110, 130, 200)]
    r.close()
    json.dump(out, open("recovery/resync_probe.json", "w"), indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
