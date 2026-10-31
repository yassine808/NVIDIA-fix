"""Find the exact first sample from which the video stream is intact.

Scans backwards from the end: the first sample (from the tail) that fails AVCC
parsing marks the boundary. Also reports the first keyframe at/after it, which is
what a stream copy must start on.

Usage: python forensics/boundary_find.py
"""
from __future__ import annotations

import json

from bitstream_map import load_tracks
from sample_map import Reader, nal_chain

VIDEO = r"recovery/Arc_Raiders corrupted.mp4"


def sample_times(stts):
    ts, t = [], 0
    for cnt, d in stts:
        for _ in range(cnt):
            ts.append(t)
            t += d
    return ts


def find_bad(r: Reader, intervals, limit: int = 3):
    """Newest samples (from the tail) whose payload does not parse as AVCC."""
    bad = []
    for off, sz, si in reversed(intervals):
        blob = r.read(off, sz)
        _n, consumed, _ = nal_chain(blob, max_nals=64) if len(blob) == sz else (0, 0, 0)
        if consumed != sz:
            bad.append(si)
            if len(bad) >= limit:
                break
    return bad


def main() -> int:
    tracks, _top, _size = load_tracks(VIDEO)
    vtr = next(t for t in tracks if t.get("handler") == "vide")
    intervals = vtr["intervals"]
    syncs = set(vtr.get("sync_samples") or [])
    timescale = vtr.get("timescale") or 1
    ts = sample_times(vtr["stts"])

    r = Reader(VIDEO, window=16 << 20)
    bad = find_bad(r, intervals)
    r.close()

    last_bad = max(bad) if bad else -1
    first_good = last_bad + 1
    t_s = ts[first_good] / timescale
    print("last damaged sample index %d (t=%.3fs)" % (last_bad, ts[last_bad] / timescale))
    print("first clean sample       %d (t=%.3fs)" % (first_good, t_s))
    key = next((s for s in sorted(syncs) if s >= first_good), None)
    print("first keyframe >= boundary: %s (t=%.3fs)"
          % (key, ts[key] / timescale if key else -1))
    total = len(intervals)
    clean_frames = total - first_good
    print("frames: total %d, clean %d (%.1f%%), missing %d (%.1f%%)"
          % (total, clean_frames, 100.0 * clean_frames / total,
             first_good, 100.0 * first_good / total))
    print("clean duration %.2fs of %.2fs"
          % ((ts[-1] - ts[first_good]) / timescale, ts[-1] / timescale))
    json.dump({"last_bad": last_bad, "first_clean": first_good,
               "first_clean_t": t_s, "first_key": key,
               "key_t": ts[key] / timescale if key else None,
               "frames": total, "clean_frames": clean_frames},
              open("recovery/boundary.json", "w"), indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
