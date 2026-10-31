"""Where does real H.264 live inside the file?

1. Walk every indexed sample and score it as an AVCC NAL chain at its stated
   offset (no shift, +32, and +delta variants): gives a validity map over time.
2. Lock onto the unreferenced tail: find offsets where a long NAL chain parses.
3. Hex-dump a few probes in the tail so the layout can be identified.

Usage: python forensics/bitstream_map.py
"""
from __future__ import annotations

import json
import struct
import sys
from typing import List, Tuple

import mp4_probe as P
from sample_map import Reader, nal_chain

VIDEO = r"recovery/Arc_Raiders corrupted.mp4"


def load_tracks(video: str):
    import os
    size = os.path.getsize(video)
    with open(video, "rb") as fh:
        pos, moov_range, top = 0, None, []
        while pos + 8 <= size:
            fh.seek(pos)
            hdr = fh.read(16)
            sz = struct.unpack(">I", hdr[:4])[0]
            bt = hdr[4:8]
            hl = 8
            if sz == 1:
                sz = struct.unpack(">Q", hdr[8:16])[0]
                hl = 16
            elif sz == 0:
                sz = size - pos
            top.append({"type": bt.decode("latin-1"), "start": pos, "size": sz})
            if bt == b"moov":
                moov_range = (pos + hl, pos + sz)
            pos += sz
        fh.seek(moov_range[0])
        moov = fh.read(moov_range[1] - moov_range[0])
    tracks = [P.parse_track(moov, ps, pe)
              for bt, ps, pe, _b, _bad in P.boxes(moov, 0, len(moov))
              if bt == b"trak"]
    return tracks, top, size


def lock_points(r: Reader, start: int, end: int, limit: int = 8,
                window: int = 4 << 20) -> List[dict]:
    """Find byte offsets where >=4 consecutive AVCC NALs parse."""
    blob = r.read(start, min(window, end - start))
    hits = []
    for p in range(0, len(blob) - 64):
        ln = struct.unpack_from(">I", blob, p)[0]
        if ln < 4 or ln > 300000 or p + 4 + ln > len(blob):
            continue
        typ = blob[p + 4] & 0x1F
        if typ not in (1, 5, 6, 7, 8, 9):
            continue
        n, consumed, _t = nal_chain(blob[p:p + 1 << 20], max_nals=4)
        if n >= 4:
            hits.append({"offset": start + p, "nals": n, "consumed": consumed})
            if len(hits) >= limit:
                break
    return hits


def sample_times(stts):
    ts, t = [], 0
    for cnt, d in stts:
        for _ in range(cnt):
            ts.append(t)
            t += d
    return ts


def sample_score(r: Reader, off: int, sz: int) -> List[int]:
    """[parses@0, exact@0, parses@32, exact@32] for one indexed sample."""
    scores = []
    for delta in (0, 32):
        blob = r.read(off + delta, sz)
        if len(blob) != sz or sz < 8:
            scores.extend((0, 0))
            continue
        n, consumed, _t = nal_chain(blob, max_nals=8)
        scores.extend((int(n >= 1), int(consumed == sz)))
    return scores


def score_intervals(r: Reader, intervals, ts, timescale: int):
    """Bucket per-10s parse/exact counts at offset 0 and +32."""
    buckets = {}
    for off, sz, si in intervals:
        if si >= len(ts):
            continue
        b = int((ts[si] / timescale) // 10) * 10
        acc = buckets.setdefault(b, [0, 0, 0, 0, 0])
        acc[0] += 1
        for index, value in enumerate(sample_score(r, off, sz), start=1):
            acc[index] += value
    return buckets


def print_buckets(buckets) -> None:
    print(" t(s)  samples  parse@0  exact@0  parse@32  exact@32")
    for b in sorted(buckets):
        a = buckets[b]
        print("%5d %8d  %6.1f%%  %6.1f%%   %6.1f%%   %6.1f%%"
              % (b, a[0], 100.0 * a[1] / a[0], 100.0 * a[2] / a[0],
                 100.0 * a[3] / a[0], 100.0 * a[4] / a[0]))


def print_tail(r: Reader, top, intervals) -> None:
    """Report the unreferenced tail: size, lock points and hex probes."""
    mdat = next(b for b in top if b["type"] == "mdat")
    mstart, mend = mdat["start"] + 8, mdat["start"] + mdat["size"]
    covered_end = max(off + sz for off, sz, _ in intervals)
    print("\nmdat [%d,%d)  indexed data ends at %d  => tail %d bytes"
          % (mstart, mend, covered_end, mend - covered_end))

    print("\nlock points in tail:")
    for probe in (covered_end, covered_end + 1024, mend - 4 * 1024 * 1024,
                  mend - 65536):
        hits = lock_points(r, max(mstart, probe), mend, limit=3)
        print("  probe %d -> %s" % (probe, hits))

    print("\nhex probes in tail:")
    for probe in (covered_end, covered_end + 4096,
                  (covered_end + mend) // 2, mend - 4096):
        blob = r.read(probe, 64)
        print("  %d: %s" % (probe, blob.hex()))


def main() -> int:
    tracks, top, _size = load_tracks(VIDEO)
    vtr = next(t for t in tracks if t.get("handler") == "vide")
    intervals = vtr["intervals"]
    timescale = vtr.get("timescale") or 1
    ts = sample_times(vtr["stts"])

    r = Reader(VIDEO, window=8 << 20)
    buckets = score_intervals(r, intervals, ts, timescale)
    print_buckets(buckets)
    print_tail(r, top, intervals)
    r.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
