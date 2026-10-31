"""JSON-lines bridge between the TypeScript desktop app and nvidia_fix.

Usage:
    python scripts/bridge.py --path <video> [--full-decode] [--full-length]

Every line written to stdout is one JSON object:
    {"event": "progress", "message": "..."}
    {"event": "result", "result": {...}}
    {"event": "error", "message": "..."}

The recovery engine is imported from the repository root; nothing is uploaded.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import nvidia_fix  # noqa: E402


def emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bridge.py")
    parser.add_argument("--path", required=True, help="video file to recover")
    parser.add_argument("--full-decode", action="store_true")
    parser.add_argument("--full-length", action="store_true")
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    try:
        result = nvidia_fix.process(
            args.path,
            out_dir=None,  # write beside the input
            full_decode=args.full_decode,
            progress=lambda message: emit({"event": "progress", "message": message}),
            full_length=args.full_length,
        )
    except nvidia_fix.NvidiaFixError as exc:
        emit({"event": "error", "message": str(exc)})
        return 2
    except Exception as exc:  # keep the UI informed instead of dying silently
        emit({"event": "error", "message": f"{type(exc).__name__}: {exc}"})
        return 1

    source = Path(args.path).expanduser().resolve()
    result["original_name"] = source.name
    result["original_path"] = str(source)
    result["output_dir"] = str(source.parent)
    emit({"event": "result", "result": result})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
