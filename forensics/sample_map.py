"""Content-level forensics: does each indexed sample point at real video bytes?

Produces:
  * a shift test -- which constant offset delta makes samples parse as AVCC NALs
  * per-sample SHA-1 of the payload -> duplication / time-to-source map
  * a NAL-chain walk of the region the index does NOT describe (orphan media)

Read-only. Streams from disk; never loads the whole file.

Usage: python forensics/sample_map.py [video] [--json out]
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
import sys
from typing import Dict, List, Optional, Tuple

import mp4_probe as P

AVC_NAL_OK = {1, 5, 6, 7, 8, 9, 10, 11, 12, 13}


class Reader:
    """Small windowed reader so we never hold 438 MB in RAM."""

    def __init__(self, path: str, window: int = 4 << 20):
        self.fh = open(path, "rb")
        self.size = os.path.getsize(path)
        self.window = window
        self.start = -1
        self.buf = b""

    def read(self, off: int, n: int) -> bytes:
        if n <= 0 or off < 0 or off >= self.size:
            return b""
        end = min(off + n, self.size)
        if not (self.start <= off and end <= self.start + len(self.buf)):
            if n > self.window:
                start = off
            else:
                # Anchor the cache on a window boundary, not on `off`. Anchoring
                # on `off` meant a backwards scan (every next offset smaller than
                # the last) missed the cache every time and re-read the window:
                # 22k samples x 16 MiB = ~350 GB of I/O on this recording.
                start = (off // self.window) * self.window
            limit = min(self.size, max(start + self.window, end))
            self.fh.seek(start)
            self.buf = self.fh.read(limit - start)
            self.start = start
        a = off - self.start
        return self.buf[a:a + (end - off)]

    def close(self):
        self.fh.close()


def nal_chain(blob: bytes, max_nals: int = 512) -> Tuple[int, int, int]:
    """Parse AVCC length-prefixed NALs. Returns (nals_ok, bytes_consumed, total_nals)."""
    p, n, total = 0, 0, 0
    L = len(blob)
    while p + 4 <= L and n < max_nals:
        ln = struct.unpack_from(">I", blob, p)[0]
        if ln <= 0 or p + 4 + ln > L:
            break
        typ = blob[p + 4] & 0x1F
        total += 1
        if typ not in AVC_NAL_OK:
            break
        p += 4 + ln
        n += 1
    return n, p, total


def score_shift(r: Reader, intervals: List[Tuple[int, int, int]], delta: int,
                probe_n: int = 400) -> Dict[str, float]:
    """Fraction of probed samples that are a self-consistent AVCC sample at +delta."""
    good = exact = 0
    step = max(1, len(intervals) // probe_n)
    tested = 0
    for off, size, _si in intervals[::step]:
        blob = r.read(off + delta, size)
        if len(blob) != size or size < 8:
            tested += 1
            continue
        n, consumed, _t = nal_chain(blob)
        tested += 1
        if n >= 1:
            good += 1
        if consumed == size:
            exact += 1
    return {"delta": delta, "tested": tested,
            "parses": round(good / max(tested, 1), 4),
            "exact": round(exact / max(tested, 1), 4)}


def orphan_scan(r: Reader, gaps: List[Tuple[int, int]], budget_nals: int = 2_000_000):
    """Walk each undescribed region as a continuous AVCC stream."""
    out = []
    for gstart, gend in sorted(gaps, key=lambda g: -(g[1] - g[0]))[:6]:
        if gend - gstart < 1 << 20:
            continue
        blob = r.read(gstart, gend - gstart)
        p = 0
        n = 0
        types: Dict[int, int] = {}
        first_nal_offsets = []
        while p + 4 <= len(blob) and n < budget_nals:
            ln = struct.unpack_from(">I", blob, p)[0]
            if ln <= 0 or p + 4 + ln > len(blob):
                break
            typ = blob[p + 4] & 0x1F
            if typ not in AVC_NAL_OK:
                break
            types[typ] = types.get(typ, 0) + 1
            if len(first_nal_offsets) < 5:
                first_nal_offsets.append(gstart + p)
            p += 4 + ln
            n += 1
        out.append({"start": gstart, "end": gend, "bytes": gend - gstart,
                    "nals_parsed": n, "consumed": p,
                    "coverage_pct": round(100.0 * p / (gend - gstart), 2),
                    "nal_types": {str(k): v for k, v in sorted(types.items())},
                    "first_nals": first_nal_offsets})
        if n:
            break
    return out


def main() -> int:
    video = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") \
        else r"recovery/Arc_Raiders corrupted.mp4"
    out_json = None
    if "--json" in sys.argv:
        out_json = sys.argv[sys.argv.index("--json") + 1]

    with open(video, "rb") as fh:
        fh.seek(0)
        size = os.path.getsize(video)
        pos, moov_range, top = 0, None, []
        while pos + 8 <= size:
            fh.seek(pos)
            hdr = fh.read(16)
            sz = struct.unpack(">I", hdr[:4])[0]
            bt = hdr[4:8]
            hdrlen = 8
            if sz == 1:
                sz = struct.unpack(">Q", hdr[8:16])[0]
                hdrlen = 16
            elif sz == 0:
                sz = size - pos
            top.append({"type": bt.decode("latin-1"), "start": pos, "size": sz})
            if bt == b"moov":
                moov_range = (pos + hdrlen, pos + sz)
            pos += sz
        fh.seek(moov_range[0])
        moov = fh.read(moov_range[1] - moov_range[0])

    tracks = []
    for bt, ps, pe, _bs, _bad in P.boxes(moov, 0, len(moov)):
        if bt == b"trak":
            tracks.append(P.parse_track(moov, ps, pe, size))
    vtr = next(t for t in tracks if t.get("handler") == "vide")
    atr = next((t for t in tracks if t.get("handler") == "soun"), None)
    intervals = vtr["intervals"]

    r = Reader(video)
    report: Dict[str, object] = {"video": video, "file_size": size,
                                 "top_level": top,
                                 "video_samples": len(intervals)}
    print("shift test ...", file=sys.stderr)
    report["shift_test"] = [score_shift(r, intervals, d) for d in (0, 8, -32, 32, 24, -8)]
    print(json.dumps(report["shift_test"]), file=sys.stderr)
    best = max(report["shift_test"], key=lambda s: (s["exact"], s["parses"]))
    delta = int(best["delta"])
    report["best_delta"] = delta

    # timestamps
    stts = vtr.get("stts") or []
    ts_of: List[int] = []
    t = 0
    for cnt, d in stts:
        for _ in range(cnt):
            ts_of.append(t)
            t += d
    report["ts_count"] = len(ts_of)
    timescale = vtr.get("timescale") or 1

    print("hashing %d samples ..." % len(intervals), file=sys.stderr)
    recs = []
    for off, sz, si in intervals:
        blob = r.read(off + delta, sz)
        h = hashlib.sha1(blob).hexdigest()[:16]
        recs.append({"i": si, "off": off + delta, "size": sz, "sha": h,
                     "ts": ts_of[si] / timescale if si < len(ts_of) else None})
    report["samples"] = recs

    by_hash: Dict[str, List[int]] = {}
    for rec in recs:
        by_hash.setdefault(rec["sha"], []).append(rec["i"])
    dup_clusters = {h: v for h, v in by_hash.items() if len(v) > 1}
    report["unique_payloads"] = len(by_hash)
    report["dup_clusters"] = len(dup_clusters)
    report["dup_samples"] = sum(len(v) - 1 for v in dup_clusters.values())
    report["unique_bytes"] = sum(recs[v[0]]["size"] for v in by_hash.values())
    print("unique payloads %d / %d, duplicated samples %d, unique bytes %d"
          % (len(by_hash), len(recs), report["dup_samples"],
             report["unique_bytes"]), file=sys.stderr)

    # time -> source mapping for duplicated samples (the README's drift table)
    dup_by_index = {}
    for h, idxs in dup_clusters.items():
        for i in idxs[1:]:
            dup_by_index[i] = (idxs[0], h)
    mapping = []
    for i in sorted(dup_by_index)[:4000]:
        src, _h = dup_by_index[i]
        if recs[i]["ts"] is not None and recs[src]["ts"] is not None:
            mapping.append({"sample": i, "ts": round(recs[i]["ts"], 3),
                            "source_sample": src,
                            "source_ts": round(recs[src]["ts"], 3)})
    report["drift_sample"] = mapping[:200]
    report["duplicated_sample_count"] = len(dup_by_index)

    # which byte ranges hold unique payloads / which are orphaned
    mdat = next(b for b in top if b["type"] == "mdat")
    mstart, mend = mdat["start"] + 8, mdat["start"] + mdat["size"]
    iv = sorted((rec["off"], rec["size"]) for rec in recs)
    gaps, cur = [], mstart
    for off, sz in iv:
        if off > cur:
            gaps.append([cur, off])
        cur = max(cur, off + sz)
    if cur < mend:
        gaps.append([cur, mend])
    gaps = [g for g in gaps if g[1] - g[0] > 1024]
    report["gaps"] = gaps
    print("gaps: %d, largest %s" % (len(gaps), max((b - a for a, b in gaps), default=0)),
          file=sys.stderr)

    print("orphan NAL scan ...", file=sys.stderr)
    report["orphan_scan"] = orphan_scan(r, [tuple(g) for g in gaps])
    print(json.dumps(report["orphan_scan"], indent=1), file=sys.stderr)

    r.close()
    for key in ("samples", "drift_sample"):
        pass
    if out_json:
        with open(out_json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, default=str)
        print("wrote", out_json, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
