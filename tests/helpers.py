import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _tool(name):
    found = shutil.which(name)
    if found:
        return found
    bundled = sorted((ROOT / "recovery" / "tools" / "ff").glob(f"*/bin/{name}.exe"))
    return str(bundled[0]) if bundled else name


FFMPEG = _tool("ffmpeg")
FFPROBE = _tool("ffprobe")


def run(cmd):
    return subprocess.run(
        cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
    )


def probe_packets(path):
    out = run([
        FFPROBE, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "packet=pts_time,size,pos,flags",
        "-of", "json", str(path),
    ]).stdout
    return json.loads(out)["packets"]


def make_clip(path, seconds=8, with_audio=True, width=320, height=240, fps=30):
    cmd = [
        FFMPEG, "-hide_banner", "-v", "error", "-y",
        "-f", "lavfi", "-i",
        f"testsrc2=size={width}x{height}:rate={fps}:duration={seconds}",
    ]
    if with_audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    cmd += [
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-g", str(fps * 2), "-keyint_min", str(fps * 2),
        "-sc_threshold", "0",
        "-force_key_frames", "expr:gte(t,n_forced*2)",
    ]
    if with_audio:
        cmd += ["-c:a", "aac", "-b:a", "64k", "-shortest"]
    cmd += ["-movflags", "+faststart", str(path)]
    run(cmd)
    return Path(path)


def corrupt_middle(path, start=2.5, end=3.9):
    """Overwrite the NAL headers of non-keyframe samples in a time range."""
    packets = probe_packets(path)
    changed = 0
    with open(path, "r+b") as handle:
        for packet in packets:
            pts = float(packet["pts_time"])
            if not (start <= pts < end):
                continue
            if "K" in packet.get("flags", ""):
                continue
            size = int(packet["size"])
            pos = int(packet["pos"])
            if size < 8:
                continue
            handle.seek(pos)
            handle.write(b"\xde\xad\xbe\xef\x00\x00\x00\x00")
            changed += 1
    if changed == 0:
        raise RuntimeError("no samples were corrupted")
    return changed
