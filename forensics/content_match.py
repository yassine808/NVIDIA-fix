"""Match every 2 fps thumbnail against the rest of the recording.

Input: raw 8-bit gray frames, W x H, produced by
    ffmpeg -vf "fps=2,scale=64:36,format=gray" -f rawvideo thumbs.raw

Answers: for each damaged-window frame, is there a near-identical frame later
in the file (=> overwritten with a copy), or is the content unique?
"""
import json
import sys

from paths import readable_file

W, H, FPS = 64, 36, 2
FRAME = W * H


def load(path):
    # Callers pass paths.readable_file() output.
    data = open(path, "rb").read()  # NOSONAR
    n = len(data) // FRAME
    return [data[i * FRAME:(i + 1) * FRAME] for i in range(n)]


def dist(a, b, stride=1):
    s = 0
    for i in range(0, FRAME, stride):
        d = a[i] - b[i]
        s += d * d
    return s / (FRAME // stride)


def activity(frames, var):
    """Frozen and blank frames, given the per-frame variance."""
    frozen = [i for i in range(1, len(frames)) if dist(frames[i], frames[i - 1]) < 2.0]
    blank = [i for i in range(len(frames)) if var[i] < 40]
    return frozen, blank


def variances(frames):
    var = []
    for f in frames:
        mean = sum(f) / FRAME
        var.append(sum((v - mean) ** 2 for v in f) / FRAME)
    return var


def match_rows(frames, var):
    """For each early frame, find the closest later frame."""
    n = len(frames)
    rows = []
    for i in range(0, n):
        t = i / FPS
        if t > 120:
            continue
        best_j, best_d = None, 1e18
        for j in range(int(120 * FPS), n):
            d = dist(frames[i], frames[j], stride=2)
            if d < best_d:
                best_d, best_j = d, j
        own = [dist(frames[i], frames[k], stride=2)
               for k in range(max(0, i - 2), min(n, i + 3)) if k != i]
        rows.append({"t": round(t, 1), "best_t": round(best_j / FPS, 1),
                     "best_d": round(best_d, 1),
                     "neighbour_d": round(min(own), 1) if own else None,
                     "var": round(var[i], 1)})
    return rows


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "recovery/thumbs.raw"
    # The operator names an explicit local file on the command line; resolve it
    # once so the read below uses the validated path.
    frames = load(readable_file(path, "thumb file"))
    n = len(frames)
    print("frames", n, "= %.1fs" % (n / FPS))
    if n < 10:
        return 1

    # Per-frame activity (variance) and self-distance to neighbours: tells us
    # which frames are actually decoded pictures and which are frozen/blank.
    var = variances(frames)
    frozen, blank = activity(frames, var)

    # Cross-time matching: for each early frame find the closest later frame.
    rows = match_rows(frames, var)

    print("\n t   best_t  best_d  neighbour_d  var     verdict")
    for r in rows:
        same = r["best_d"] <= (r["neighbour_d"] or 1e9) * 1.5
        print("%5.1f %6.1f %7.1f %11s %7.1f  %s"
              % (r["t"], r["best_t"], r["best_d"], r["neighbour_d"], r["var"],
                 "COPY-OF-LATER" if same else "unique"))
    print("\nfrozen frames %d, blank frames %d" % (len(frozen), len(blank)))
    json.dump({"rows": rows, "frozen": frozen, "blank": blank,
               "fps": FPS, "n": n},
              open("recovery/content_match.json", "w"), indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
