"""Dense duplication map of the damaged prefix.

Fits the drift line from confident matches, then validates every 256 KiB block of
the prefix against its predicted source position. Reports:
  * how many prefix bytes are provably a copy of tail bytes
  * the container-time -> content-time mapping
  * what the unmatched blocks look like (AVCC vs high-entropy garbage)

Usage: python forensics/duplication_dense.py [video] [end_mb]
"""
from __future__ import annotations

import json
import math
import os
import sys

from bitstream_map import load_tracks

VIDEO = sys.argv[1] if len(sys.argv) > 1 else r"recovery/Arc_Raiders corrupted.mp4"
END_MB = int(sys.argv[2]) if len(sys.argv) > 2 else 190
BLOCK = 256 << 10
NEEDLE = 64
SEARCH = 512 << 10
RUN = 8192


def entropy(b: bytes) -> float:
    if not b:
        return 0.0
    cnt = [0] * 256
    for x in b:
        cnt[x] += 1
    n = len(b)
    return -sum((c / n) * math.log2(c / n) for c in cnt if c)


def sample_times(stts):
    ts, t = [], 0
    for cnt, d in stts:
        for _ in range(cnt):
            ts.append(t)
            t += d
    return ts


def sample_time(starts, intervals, ts, timescale, off):
    lo, hi = 0, len(starts) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if starts[mid] < off:
            lo = mid + 1
        else:
            hi = mid
    si = intervals[lo][2]
    return round(ts[si] / timescale, 2) if si < len(ts) else None


def calibrate(data: bytes, size: int):
    """Fit src = a + b*off on confident prefix->tail matches; None if too few."""
    calib = []
    for poff in range(1 << 20, 175 << 20, 1 << 20):
        needle = data[poff:poff + NEEDLE]
        j = data.find(needle, int(size * 0.6))
        if j > poff:
            calib.append((poff, j - poff))
    if len(calib) < 4:
        return None
    n = len(calib)
    mx = sum(x for x, _ in calib) / n
    my = sum(y for _, y in calib) / n
    b = (sum((x - mx) * (y - my) for x, y in calib) / sum((x - mx) ** 2 for x, _ in calib))
    a = my - b * mx
    resid = [y - (a + b * x) for x, y in calib]
    resid.sort()
    print("drift line: src = %.1f + %.7f*off   residual median %d, p95 %d"
          % (a, b, resid[n // 2], resid[int(n * 0.95)]))
    print("calibration points %d" % n)
    return a, b


def validate_blocks(data: bytes, size: int, end_mb: int, a: float, b: float, time_of):
    """Validate every BLOCK of the prefix against the predicted source offset."""
    rows = []
    for poff in range(0, end_mb << 20, BLOCK):
        needle = data[poff:poff + NEEDLE]
        if len(needle) < NEEDLE:
            break
        predicted = poff + int(a + b * poff)
        lo = max(0, predicted - SEARCH)
        j = data.find(needle, lo, min(size, predicted + SEARCH + NEEDLE))
        if j < 0:
            probe = data[poff:poff + RUN]
            rows.append({"off": poff, "t": time_of(poff), "matched": False,
                         "src": None, "src_t": None,
                         "entropy": round(entropy(probe), 2)})
            continue
        run = next((i for i in range(RUN) if data[poff + i] != data[j + i]), RUN)
        rows.append({"off": poff, "t": time_of(poff), "matched": True,
                     "src": j, "src_t": time_of(j),
                     "run": run, "entropy": round(entropy(data[poff:poff + RUN]), 2)})
    return rows


def print_summary(rows) -> None:
    matched = [r for r in rows if r["matched"]]
    unmatched = [r for r in rows if not r["matched"]]
    print("blocks %d  matched %d (%.1f%%)  unmatched %d"
          % (len(rows), len(matched), 100.0 * len(matched) / len(rows),
             len(unmatched)))
    if matched:
        print("median identical run at block probes: %d bytes"
              % sorted(r["run"] for r in matched)[len(matched) // 2])
        print("time mapping: container %.2fs -> content %.2fs ... container %.2fs -> content %.2fs"
              % (matched[0]["t"], matched[0]["src_t"],
                 matched[-1]["t"], matched[-1]["src_t"]))
        step = max(1, len(matched) // 12)
        print("\n sampling of the mapping:")
        for r in matched[::step]:
            print("   t=%7.2fs -> content t=%7.2fs (run %d)"
                  % (r["t"], r["src_t"], r["run"]))
        print("\nentropy of matched blocks: min %.2f median %.2f"
              % (min(r["entropy"] for r in matched),
                 sorted(r["entropy"] for r in matched)[len(matched) // 2]))
    if unmatched:
        # compress to ranges
        ranges = []
        for r in unmatched:
            if ranges and r["off"] == ranges[-1][1] + BLOCK:
                ranges[-1][1] = r["off"]
                ranges[-1][3] = r["t"]
            else:
                ranges.append([r["off"], r["off"], r["t"], r["t"]])
        print("\nunmatched ranges (off_start..off_end, container t):")
        for a, b, t0, t1 in ranges:
            print("   %10d..%-10d  t=%6.2f..%6.2fs  (%d blocks)"
                  % (a, b, t0, t1, (b - a) // BLOCK + 1))

    # last prefix block that still matches -> boundary of the copied region
    if matched:
        last = max(matched, key=lambda r: r["off"])
        print("\nlast matched prefix block at off %d (container t=%ss, content t=%ss)"
              % (last["off"], last["t"], last["src_t"]))


def main() -> int:
    size = os.path.getsize(VIDEO)
    data = open(VIDEO, "rb").read()
    tracks, _top, _s = load_tracks(VIDEO)
    vtr = next(t for t in tracks if t.get("handler") == "vide")
    intervals = vtr["intervals"]
    timescale = vtr.get("timescale") or 1
    ts = sample_times(vtr["stts"])
    starts = [iv[0] for iv in intervals]

    # --- calibrate the drift line on confident matches -------------------
    fit = calibrate(data, size)
    if fit is None:
        print("calibration failed")
        return 1
    a, b = fit

    # --- dense validation ------------------------------------------------
    time_of = lambda off: sample_time(starts, intervals, ts, timescale, off)
    rows = validate_blocks(data, size, END_MB, a, b, time_of)
    print_summary(rows)

    target = os.path.join(os.path.dirname(VIDEO), "duplication_dense.json")
    json.dump({"line": {"a": a, "b": b}, "rows": rows}, open(target, "w"), indent=1)
    print("wrote", target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
