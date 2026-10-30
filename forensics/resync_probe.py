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


def main() -> int:
    tracks, top, size = load_tracks(VIDEO)
    vtr = next(t for t in tracks if t.get("handler") == "vide")
    intervals = vtr["intervals"]
    timescale = vtr.get("timescale") or 1
    ts, t = [], 0
    for cnt, d in vtr["stts"]:
        for _ in range(cnt):
            ts.append(t)
            t += d

    r = Reader(VIDEO, window=32 << 20)
    out = []
    for centre in (5, 30, 60, 90, 110, 130, 200):
        t0 = centre * 120
        picked = [iv for iv in intervals if t0 <= iv[2] < t0 + 120]
        if len(picked) > 240:
            picked = picked[::max(1, len(picked) // 240)]
        stat = Counter()
        shifts = Counter()
        for off, sz, si in picked:
            span = r.read(max(0, off - SEARCH), sz + 2 * SEARCH)
            base = SEARCH if off >= SEARCH else off
            blob = span
            # as-is, per length width
            hit = None
            for lw in (4, 2, 1):
                if chain_at(blob, base, sz, lw) > 0:
                    hit = (0, lw)
                    break
            if hit:
                stat["as_is"] += 1
                shifts[0] += 1
                continue
            found = None
            for d in range(-SEARCH, SEARCH + 1):
                p = base + d
                if p < 0 or p + sz > len(blob):
                    continue
                for lw in (4, 2, 1):
                    if chain_at(blob, p, sz, lw) > 0:
                        found = (d, lw)
                        break
                if found:
                    break
            if found:
                stat["shifted"] += 1
                shifts[found[0]] += 1
            else:
                stat["dead"] += 1
        tot = max(1, sum(stat.values()))
        out.append({"t": centre, "n": tot, "as_is": stat["as_is"],
                    "shifted": stat["shifted"], "dead": stat["dead"],
                    "shift_hist": dict(shifts.most_common(8))})
        print("t=%3d  n=%3d  as-is %5.1f%%  shifted %5.1f%%  dead %5.1f%%  shifts %s"
              % (centre, tot, 100.0 * stat["as_is"] / tot,
                 100.0 * stat["shifted"] / tot, 100.0 * stat["dead"] / tot,
                 dict(shifts.most_common(5))))
    r.close()
    json.dump(out, open("recovery/resync_probe.json", "w"), indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
