"""Structural forensics for a possibly-damaged MP4. Read-only, no dependencies.

Usage:
    python forensics/mp4_probe.py <file.mp4> [--json out.json]

Prints top-level box layout, per-track sample-table facts, and a coverage map of
which byte ranges of the file the index actually describes.
"""
from __future__ import annotations

import json
import os
import struct
import sys
from typing import Any, Dict, List, Optional, Tuple

from paths import readable_file

CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts", b"dinf",
              b"mvex", b"moof", b"traf", b"udta", b"ilst"}


def boxes(buf: bytes, start: int, end: int):
    """Yield (type, payload_start, payload_end, box_start) for boxes in [start,end)."""
    pos = start
    while pos + 8 <= end:
        size = struct.unpack(">I", buf[pos:pos + 4])[0]
        btype = buf[pos + 4:pos + 8]
        header = 8
        if size == 1:
            if pos + 16 > end:
                return
            size = struct.unpack(">Q", buf[pos + 8:pos + 16])[0]
            header = 16
        elif size == 0:
            size = end - pos
        if size < header or pos + size > end:
            # Truncated/garbage box: report and stop at this level.
            yield (btype, pos + header, end, pos, True)
            return
        yield (btype, pos + header, pos + size, pos, False)
        pos += size


def find(buf: bytes, start: int, end: int, path: List[bytes]):
    cur = [(start, end)]
    for want in path:
        nxt = []
        for s, e in cur:
            for btype, ps, pe, _bs, _bad in boxes(buf, s, e):
                if btype == want:
                    nxt.append((ps, pe))
        cur = nxt
        if not cur:
            return []
    return cur


def parse_stsd_codec(buf: bytes, s: int, e: int) -> Optional[str]:
    # FullBox: version/flags (4) + entry_count (4), then entries of sample entry boxes
    for btype, ps, pe, _bs, _bad in boxes(buf, s + 8, e):
        return btype.decode("latin-1")
    return None


def parse_stsz(buf: bytes, s: int, e: int) -> Tuple[int, List[int]]:
    _version_flags, sample_size, count = struct.unpack(">III", buf[s:s + 12])
    if sample_size != 0:
        return sample_size, [sample_size] * count
    need = s + 12 + 4 * count
    if need > e:
        count = (e - s - 12) // 4
    sizes = list(struct.unpack(">%dI" % count, buf[s + 12:s + 12 + 4 * count]))
    return 0, sizes


def parse_stco(buf: bytes, s: int, wide: bool = False) -> List[int]:
    """Chunk offsets. stco stores 32-bit values, co64 stores 64-bit; both are
    FullBoxes with version 0, so the box type -- not the version -- decides."""
    count = struct.unpack(">I", buf[s + 4:s + 8])[0]
    if wide:
        return list(struct.unpack(">%dQ" % count, buf[s + 8:s + 8 + 8 * count]))
    return list(struct.unpack(">%dI" % count, buf[s + 8:s + 8 + 4 * count]))


def parse_stsc(buf: bytes, s: int) -> List[Tuple[int, int, int]]:
    count = struct.unpack(">I", buf[s + 4:s + 8])[0]
    out = []
    off = s + 8
    for _ in range(count):
        out.append(struct.unpack(">III", buf[off:off + 12]))
        off += 12
    return out


def parse_stts(buf: bytes, s: int) -> List[Tuple[int, int]]:
    count = struct.unpack(">I", buf[s + 4:s + 8])[0]
    out = []
    off = s + 8
    for _ in range(count):
        out.append(struct.unpack(">II", buf[off:off + 8]))
        off += 8
    return out


def parse_stss(buf: bytes, s: int) -> List[int]:
    """Sync sample numbers from `stss`.

    ISO/IEC 14496-12 stores these **1-based** (first sample of the track is 1).
    Convert to 0-based indices so they line up with `intervals`, `stts` and
    ffprobe's packet indices; mixing the two once produced a false boundary.
    """
    count = struct.unpack(">I", buf[s + 4:s + 8])[0]
    return [n - 1 for n in struct.unpack(">%dI" % count, buf[s + 8:s + 8 + 4 * count])]


def parse_mdhd(buf: bytes, s: int) -> Dict[str, Any]:
    version = buf[s]
    if version == 1:
        _c, _m, timescale, dur = struct.unpack(">QQIQ", buf[s + 4:s + 32])
    else:
        _c, _m, timescale, dur = struct.unpack(">IIII", buf[s + 4:s + 20])
    return {"timescale": timescale, "duration": dur}


def parse_tkhd(buf: bytes, s: int) -> Dict[str, Any]:
    version = buf[s]
    if version == 1:
        track_id = struct.unpack(">I", buf[s + 20:s + 24])[0]
    else:
        track_id = struct.unpack(">I", buf[s + 12:s + 16])[0]
    return {"track_id": track_id}


def hdlr_type(buf: bytes, s: int) -> str:
    return buf[s + 8:s + 12].decode("latin-1")


def parse_track(buf: bytes, ts: int, te: int) -> Dict[str, Any]:
    tr = read_track_boxes(buf, ts, te)
    build_intervals(tr)
    return tr


def read_track_boxes(buf: bytes, ts: int, te: int) -> Dict[str, Any]:
    """Read the tkhd/mdia boxes of one trak into a flat dict."""
    tr: Dict[str, Any] = {}
    for btype, ps, pe, _bs, _bad in boxes(buf, ts, te):
        if btype == b"tkhd":
            tr.update(parse_tkhd(buf, ps))
        elif btype == b"mdia":
            read_mdia_boxes(buf, ps, pe, tr)
    return tr


def read_mdia_boxes(buf: bytes, s: int, e: int, tr: Dict[str, Any]) -> None:
    for btype, ps, pe, _b, _bd in boxes(buf, s, e):
        if btype == b"mdhd":
            tr.update(parse_mdhd(buf, ps))
        elif btype == b"hdlr":
            tr["handler"] = hdlr_type(buf, ps)
        elif btype == b"minf":
            for b3, s3, e3, _x, _y in boxes(buf, ps, pe):
                if b3 == b"stbl":
                    tr.update(parse_stbl(buf, s3, e3))


def samples_per_chunk(stsc: List[Tuple[int, int, int]], chunk_number: int) -> Optional[int]:
    """stsc entry valid for this 1-based chunk number, if any."""
    spc = None
    for first, per, _sdi in stsc:
        if chunk_number >= first:
            spc = per
        else:
            break
    return spc


def build_intervals(tr: Dict[str, Any]) -> None:
    """Chunk -> sample mapping, then absolute byte intervals."""
    if "chunk_offsets" not in tr or "sample_sizes" not in tr:
        return
    sizes = tr["sample_sizes"]
    stsc = tr["stsc"]
    offsets = tr["chunk_offsets"]
    intervals: List[Tuple[int, int, int]] = []  # (file_off, size, sample_index)
    si = 0
    for ci, chunk_off in enumerate(offsets):
        spc = samples_per_chunk(stsc, ci + 1)
        if spc is None:
            continue
        pos = chunk_off
        for _ in range(spc):
            if si >= len(sizes):
                break
            sz = sizes[si]
            intervals.append((pos, sz, si))
            pos += sz
            si += 1
    tr["intervals"] = intervals
    tr["mapped_samples"] = si
    del tr["sample_sizes"]


def parse_stbl(buf: bytes, s: int, e: int) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for btype, ps, pe, _bs, _bad in boxes(buf, s, e):
        try:
            if btype == b"stsd":
                out["codec"] = parse_stsd_codec(buf, ps, pe)
                out["stsd_json"] = buf[ps:pe][:64].hex()
            elif btype == b"stsz":
                _ss, sizes = parse_stsz(buf, ps, pe)
                out["sample_sizes"] = sizes
            elif btype == b"stz2":
                out["stz2_unsupported"] = True
            elif btype == b"stco":
                out["chunk_offsets"] = parse_stco(buf, ps, wide=False)
            elif btype == b"co64":
                out["chunk_offsets"] = parse_stco(buf, ps, wide=True)
            elif btype == b"stsc":
                out["stsc"] = parse_stsc(buf, ps)
            elif btype == b"stts":
                out["stts"] = parse_stts(buf, ps)
            elif btype == b"stss":
                out["sync_samples"] = parse_stss(buf, ps)
        except struct.error as exc:
            out.setdefault("errors", []).append("%s: %s" % (btype, exc))
    return out


def coverage(intervals: List[Tuple[int, int, int]], mdat_start: int,
             mdat_end: int) -> Dict[str, Any]:
    """Gaps inside mdat not described by any sample, plus overlap/overshoot stats."""
    iv = sorted(intervals)
    gaps = []
    cur = mdat_start
    for off, sz, _si in iv:
        if off > cur:
            gaps.append((cur, off))
        cur = max(cur, off + sz)
    if cur < mdat_end:
        gaps.append((cur, mdat_end))
    gaps = [(a, b) for a, b in gaps if b > a]
    overshoot = [x for x in iv if x[0] + x[1] > mdat_end or x[0] < mdat_start]
    overl = 0
    prev_end = -1
    for off, sz, _si in iv:
        if off < prev_end:
            overl += min(prev_end - off, sz)
        prev_end = max(prev_end, off + sz)
    return {
        "described_bytes": sum(s for _o, s, _i in iv),
        "gaps": gaps,
        "gap_bytes": sum(b - a for a, b in gaps),
        "biggest_gaps": sorted(gaps, key=lambda g: g[0] - g[1])[:10],
        "outside_mdat_samples": len(overshoot),
        "overlap_bytes": overl,
    }


def walk_top_level(fh, file_size: int) -> Tuple[List[Dict[str, Any]], Optional[Tuple[int, int]]]:
    """Walk box headers from the file start; return (boxes, moov payload range)."""
    pos = 0
    moov_range = None
    top: List[Dict[str, Any]] = []
    while pos + 8 <= file_size:
        fh.seek(pos)
        hdr = fh.read(16)
        if len(hdr) < 8:
            break
        size = struct.unpack(">I", hdr[:4])[0]
        btype = hdr[4:8]
        header = 8
        if size == 1:
            size = struct.unpack(">Q", hdr[8:16])[0]
            header = 16
        elif size == 0:
            size = file_size - pos
        top.append({"type": btype.decode("latin-1"), "start": pos,
                    "size": size})
        if btype == b"moov":
            moov_range = (pos + header, pos + size)
        pos += size
    return top, moov_range


def read_moov(fh, moov_range: Tuple[int, int]) -> bytes:
    fh.seek(moov_range[0])
    return fh.read(moov_range[1] - moov_range[0])


def add_timing(tr: Dict[str, Any]) -> None:
    stts = tr.pop("stts")
    dur = sum(c * d for c, d in stts)
    ts = tr.get("timescale") or 1
    tr["duration_s"] = round(dur / ts, 3)
    tr["stts_entries"] = len(stts)
    tr["constant_frame_rate"] = len({d for _c, d in stts}) == 1


def add_syncs(tr: Dict[str, Any]) -> None:
    syncs = tr.pop("sync_samples")
    tr["sync_count"] = len(syncs)
    tr["first_syncs"] = syncs[:5]
    tr["last_syncs"] = syncs[-3:]


def summarize_track(tr: Dict[str, Any], mdat: Optional[Dict[str, Any]]) -> None:
    tr.setdefault("intervals", [])
    tr["sample_count"] = len(tr["intervals"])
    tr["bytes_described"] = sum(s for _o, s, _i in tr["intervals"])
    if tr["intervals"]:
        tr["offset_min"] = min(o for o, _s, _i in tr["intervals"])
        tr["offset_max"] = max(o + s for o, s, _i in tr["intervals"])
    if mdat:
        tr["coverage"] = coverage(
            tr["intervals"], mdat["start"] + 8,
            mdat["start"] + mdat["size"])
    if tr.get("stts"):
        add_timing(tr)
    if "sync_samples" in tr:
        add_syncs(tr)


def build_report(path: str, file_size: int, top: List[Dict[str, Any]],
                 moov: Optional[bytes], moov_range: Optional[Tuple[int, int]]) -> Dict[str, Any]:
    report: Dict[str, Any] = {"file": path, "size": file_size, "top_level": top}
    if moov is None or moov_range is None:
        return report
    report["moov"] = {"offset": moov_range[0], "size": len(moov)}
    tracks = [parse_track(moov, ps, pe)
              for btype, ps, pe, _bs, _bad in boxes(moov, 0, len(moov))
              if btype == b"trak"]
    mdat = next((b for b in top if b["type"] == "mdat"), None)
    for tr in tracks:
        summarize_track(tr, mdat)
    report["tracks"] = tracks
    return report


def strip_intervals(report: Dict[str, Any]) -> None:
    # Keep stdout readable: drop the bulky per-sample intervals.
    for tr in report.get("tracks", []):
        if len(tr.get("intervals", [])) > 20:
            tr["intervals_count"] = len(tr["intervals"])
            tr.pop("intervals")


def print_summary(report: Dict[str, Any]) -> None:
    for tr in report.get("tracks", []):
        cov = tr.get("coverage") or {}
        print("[%s] %s samples=%s dur=%ss crf=%s bytes=%s off=[%s,%s) gaps=%s bytes=%s outside=%s overlap=%s"
              % (tr.get("handler"), tr.get("codec"), tr.get("sample_count"),
                 tr.get("duration_s"), tr.get("constant_frame_rate"),
                 tr.get("bytes_described"), tr.get("offset_min"),
                 tr.get("offset_max"), len(cov.get("gaps", [])),
                 cov.get("gap_bytes"), cov.get("outside_mdat_samples"),
                 cov.get("overlap_bytes")))


def write_report(report: Dict[str, Any], target: str, label: str) -> None:
    # `target` is a realpath() the operator named on the command line.
    with open(target, "w", encoding="utf-8") as fh:  # NOSONAR
        json.dump(report, fh, indent=2, default=str)
    print("wrote", label)


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else r"recovery/Arc_Raiders corrupted.mp4"
    out_json = None
    if "--json" in sys.argv:
        out_json = sys.argv[sys.argv.index("--json") + 1]
    # The operator names an explicit local file on the command line; resolve it
    # once so every read below uses the validated path.
    resolved = readable_file(path, "video")
    out_target = os.path.realpath(out_json) if out_json else None
    file_size = os.path.getsize(resolved)

    with open(resolved, "rb") as fh:  # NOSONAR: readable_file() validated it
        # moov can be at the end; read it explicitly by walking sizes from the file.
        top, moov_range = walk_top_level(fh, file_size)
        moov = read_moov(fh, moov_range) if moov_range else None
        report = build_report(path, file_size, top, moov, moov_range)
        strip_intervals(report)
        print(json.dumps(report, indent=2, default=str))
        if out_target:
            write_report(report, out_target, out_json)
        print_summary(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
