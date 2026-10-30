#!/usr/bin/env python3
"""Create a small, deliberately corrupted H.264 clip for CI and manual tests."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.helpers import corrupt_middle, make_clip  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: make_fixture.py <output.mp4>", file=sys.stderr)
        return 2

    target = Path(sys.argv[1]).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    make_clip(target, seconds=8, with_audio=True)
    changed = corrupt_middle(target)
    print(f"created {target} ({changed} corrupted samples)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
