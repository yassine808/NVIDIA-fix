#!/usr/bin/env python3
"""End-to-end CLI check used by CI and for local verification.

It creates a clean synthetic clip, corrupts its middle, runs the public CLI
through analyze and fix, and asserts that the recovered files are valid and the
input hash did not change.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.helpers import corrupt_middle, make_clip  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_cli(*args: str) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "nvidia_fix.py"), *args],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"CLI failed ({proc.returncode}): {' '.join(args)}\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return proc


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="nvidia-fix-ci-"))
    try:
        source = work / "ci-input.mp4"
        make_clip(source, seconds=8, with_audio=True)
        changed = corrupt_middle(source)
        before = sha256(source)
        print(f"fixture: {source} ({changed} corrupted samples)")

        analyze = run_cli("analyze", str(source), "--json")
        analysis = json.loads(analyze.stdout)
        assert analysis["status"] == "recoverable", analysis
        clean_start = analysis["corruption"]["clean_start_seconds"]
        assert 2.0 <= clean_start <= 5.0, analysis
        print(f"analyze OK: clean start {clean_start:.3f}s")

        output = work / "output"
        fix = run_cli("fix", str(source), "--out", str(output), "--json")
        result = json.loads(fix.stdout)
        assert result["status"] == "success", result
        video = result["recovery"]["video"]
        assert video["decode_errors"] == 0, result
        assert video["packets"] > 0, result
        assert video["first_packet_sha256"] == video["source_sample_sha256"], result

        paths = result["paths"]
        for key in ("video", "audio", "report"):
            path = Path(paths[key])
            assert path.is_file() and path.stat().st_size > 0, (key, path)

        report = json.loads(Path(paths["report"]).read_text(encoding="utf-8"))
        assert report["recovery"]["video"]["decode_errors"] == 0, report
        assert sha256(source) == before, "the input file was modified"
        print(
            "fix OK: "
            f"{video['packets']} packets, "
            f"{video['duration_seconds']:.3f}s, 0 decode errors"
        )
        print("input unchanged: OK")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
