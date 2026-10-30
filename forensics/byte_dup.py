"""Do the damaged bytes exist elsewhere in the file?

For probes taken from damaged samples, search the whole file for the same 64-byte
sequence. A hit outside the probe's own position means the damaged region holds a
copy of data that still exists elsewhere (recoverable by parallel copy). No hit
means those bytes are genuinely absent (destroyed in place).
"""
from __future__ import annotations

import hashlib
import json
import os

from bitstream_map import load_tracks
from sample_map import Reader, nal_chain

VIDEO = r"recovery/Arc_Raiders corrupted.mp4"
CHUNK = 32 << 20
PROBE = 64


def find_all(hay: bytes, needle: bytes):
    out, i = [], 0
    while True:
        i = hay.find(needle, i)
        if i < 0:
            return out
        out.append(i)
        i += 1


def main() -> int:
    size = os.path.getsize(VIDEO)
    tracks, top, _s = load_tracks(VIDEO)
    vtr = next(t for t in tracks if t.get("handler") == "vide")
    intervals = vtr["intervals"]
    timescale = vtr.get("timescale") or 1
    ts, t = [], 0
    for cnt, d in vtr["stts"]:
        for _ in range(cnt):
            ts.append(t)
            t += d

    r = Reader(VIDEO, window=1 << 20)
    probes = []
    for target in range(2, 300, 12):
        t0 = target * 120
        cand = [iv for iv in intervals if t0 <= iv[2] < t0 + 60]
        for off, sz, si in cand:
            if sz < 2048:
                continue
            blob = r.read(off, sz)
            n, consumed, _ = nal_chain(blob)
            if consumed != sz:          # damaged sample
                probes.append((off, sz, si, target))
                break
    print("probes:", [(p[3], p[0]) for p in probes])

    results = []
    for off, sz, si, target in probes:
        needle = r.read(off + sz // 3, PROBE)
        hits = []
        with open(VIDEO, "rb") as fh:
            pos = 0
            while pos < size:
                fh.seek(pos)
                hay = fh.read(CHUNK + PROBE)
                if not hay:
                    break
                for i in find_all(hay, needle):
                    hits.append(pos + i)
                pos += CHUNK
        elsewhere = [h for h in hits if abs(h - (off + sz // 3)) > 4]
        results.append({"t": target, "offset": off, "size": sz,
                        "sha": hashlib.sha1(needle).hexdigest()[:12],
                        "hits": len(hits), "elsewhere": elsewhere[:5]})
        print("t=%3ds off=%9d size=%5d  self_hits=%d elsewhere=%s"
              % (target, off, sz, len(hits), elsewhere[:5]))
    r.close()
    json.dump(results, open("recovery/byte_dup.json", "w"), indent=1)
    hits_total = sum(1 for x in results if x["elsewhere"])
    print("\nprobes with copies elsewhere: %d / %d" % (hits_total, len(results)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
