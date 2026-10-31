"""Summarize recovery/probe.json: coverage, gaps, duplication of the sample map.

Usage: python forensics/coverage_report.py [probe.json]
"""
import json
import sys

from paths import readable_file


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else r"recovery/probe.json"
    # The operator names an explicit local file on the command line; resolve it
    # once so the read below uses the validated path.
    d = json.load(open(readable_file(path, "probe json"), encoding="utf-8"))
    mdat = next(b for b in d["top_level"] if b["type"] == "mdat")
    mstart, mend = mdat["start"] + 8, mdat["start"] + mdat["size"]
    print("file      %d bytes" % d["size"])
    print("mdat      [%d, %d)  %d bytes" % (mstart, mend, mend - mstart))
    print("moov      offset %d (%d bytes)" % (d["moov"]["offset"], d["moov"]["size"]))
    for tr in d["tracks"]:
        c = tr["coverage"]
        print("\ntrack %s %s  handler=%s" % (tr.get("track_id"), tr.get("codec"),
                                            tr.get("handler")))
        print("  samples %d  duration %ss  sync %d  bytes %d"
              % (tr["sample_count"], tr.get("duration_s"), tr.get("sync_count", 0),
                 tr["bytes_described"]))
        print("  offsets [%d, %d)" % (tr["offset_min"], tr["offset_max"]))
        print("  described/available = %.2f%%"
              % (100.0 * tr["bytes_described"] / (mend - mstart)))
        print("  gaps %d  gap bytes %d  overlap %d  samples outside mdat %d"
              % (len(c["gaps"]), c["gap_bytes"], c["overlap_bytes"],
                 c["outside_mdat_samples"]))
        top = sorted(c["gaps"], key=lambda g: -(g[1] - g[0]))[:15]
        for a, b in top:
            print("    gap %12d..%-12d %10d bytes" % (a, b, b - a))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
