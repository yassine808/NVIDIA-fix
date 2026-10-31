"""Prove or refute: is the damaged prefix a byte-shifted copy of the file's tail?

For probes spread across the prefix, locate the exact source offset by searching
the tail, then verify a long contiguous run is byte-identical. Summarises the
drift curve and how much of the prefix is duplicated.

Usage: python forensics/duplication_map.py
"""
from __future__ import annotations

import json
import os
import statistics

from bitstream_map import load_tracks

VIDEO = r"recovery/Arc_Raiders corrupted.mp4"
PROBE = 64
RUN = 1 << 20          # verify 1 MiB of equality at each hit
STEP = 2 << 20          # probe every 2 MiB of the prefix


def sample_times(stts):
    ts, t = [], 0
    for cnt, d in stts:
        for _ in range(cnt):
            ts.append(t)
            t += d
    return ts


def sample_time(intervals, ts, timescale, off):
    """Container time of the sample that owns this file offset."""
    lo, hi = 0, len(intervals) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if intervals[mid][0] < off:
            lo = mid + 1
        else:
            hi = mid
    _o, _sz, si = intervals[lo]
    if si < len(ts):
        return round(ts[si] / timescale, 2)
    return None


def probe_row(data: bytes, poff: int, size: int, intervals, ts, timescale):
    """Locate the source of this prefix probe and measure the identical run."""
    needle = data[poff:poff + PROBE]
    if len(needle) < PROBE:
        return None
    src = -1
    start = size - (size // 4)
    idx = data.find(needle, start)
    if idx < 0:
        idx = data.find(needle, poff + PROBE)
    if idx > poff:
        src = idx
    if src < 0:
        return {"off": poff, "t": sample_time(intervals, ts, timescale, poff),
                "src": None}
    delta = src - poff
    a = data[poff:poff + RUN]
    b = data[src:src + RUN]
    mismatch = next((i for i in range(0, min(len(a), len(b)))
                     if a[i] != b[i]), None)
    return {"off": poff, "t": sample_time(intervals, ts, timescale, poff),
            "src": src, "delta": delta,
            "match_run": mismatch if mismatch else RUN,
            "src_t": sample_time(intervals, ts, timescale, src)}


def print_report(rows) -> None:
    dup = [r for r in rows if r["src"]]
    print("prefix probes %d, duplicated %d (%.1f%%)"
          % (len(rows), len(dup), 100.0 * len(dup) / max(1, len(rows))))
    if not dup:
        return
    deltas = [r["delta"] for r in dup]
    print("delta: min %d  max %d  median %d  spread %d bytes"
          % (min(deltas), max(deltas), statistics.median(deltas),
             max(deltas) - min(deltas)))
    runs = [r["match_run"] for r in dup]
    print("contiguous identical run: min %d  median %d  max %d"
          % (min(runs), statistics.median(runs), max(runs)))
    # drift curve: delta vs prefix offset
    if len(dup) > 2:
        xs = [r["off"] for r in dup]
        ys = [r["delta"] for r in dup]
        n = len(xs)
        mx, my = sum(xs) / n, sum(ys) / n
        slope = (sum((x - mx) * (y - my) for x, y in zip(xs, ys))
                 / sum((x - mx) ** 2 for x in xs))
        print("drift slope %.6f bytes per byte (%.4f%%)"
              % (slope, 100.0 * slope))
    print("\n first 6 mappings (container time -> source time):")
    for r in dup[:6]:
        print("   t=%6.2fs off=%10d -> src=%10d t=%6.2fs  run=%d"
              % (r["t"] or -1, r["off"], r["src"], r["src_t"] or -1,
                 r["match_run"]))
    print(" last 3 mappings:")
    for r in dup[-3:]:
        print("   t=%6.2fs off=%10d -> src=%10d t=%6.2fs  run=%d"
              % (r["t"] or -1, r["off"], r["src"], r["src_t"] or -1,
                 r["match_run"]))
    undup = [r for r in rows if not r["src"]]
    print("\nprefix probes WITHOUT a copy in the tail: %d" % len(undup))
    for r in undup[:12]:
        print("   t=%6.2fs off=%10d" % (r["t"] or -1, r["off"]))


def main() -> int:
    size = os.path.getsize(VIDEO)
    tracks, _top, _s = load_tracks(VIDEO)
    vtr = next(t for t in tracks if t.get("handler") == "vide")
    intervals = vtr["intervals"]
    timescale = vtr.get("timescale") or 1
    ts = sample_times(vtr["stts"])

    data = open(VIDEO, "rb").read()      # 439 MB, fine on this machine
    rows = []
    for poff in range(1 << 20, size // 2, STEP):
        row = probe_row(data, poff, size, intervals, ts, timescale)
        if row is None:
            break
        rows.append(row)

    print_report(rows)
    json.dump(rows, open("recovery/duplication_map.json", "w"), indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
