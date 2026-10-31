"""NVIDIA-Fix local web app.

A tiny Flask front end over ``nvidia_fix.process``. You give it the path to a
corrupted ShadowPlay recording; it writes the recovered video next to that
file as ``<name>.clean.mp4`` (plus the early audio and a JSON report) and shows
the verification result in the browser. Nothing is uploaded anywhere.

Run it with ``python app.py``.
"""

from __future__ import annotations

import os
import webbrowser
from pathlib import Path
from threading import Timer
from typing import Dict, Optional, Tuple

from flask import Flask, jsonify, render_template, request

import nvidia_fix

BASE_DIR = Path(__file__).resolve().parent
APP_VERSION = nvidia_fix.VERSION

app = Flask(__name__, instance_relative_config=True)
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024  # path input only, no uploads
# Keep editing templates while the server runs: a browser refresh picks them up.
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True


# --------------------------------------------------------------------------
# template helpers
# --------------------------------------------------------------------------

@app.template_filter("filesize")
def filesize(value):
    if value is None:
        return "—"
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} B"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


@app.template_filter("timecode")
def timecode(value):
    if value is None:
        return "—"
    minutes, seconds = divmod(float(value), 60)
    return f"{int(minutes)}:{seconds:05.2f}"


# --------------------------------------------------------------------------
# path handling
# --------------------------------------------------------------------------

def _clean_path(raw: object) -> str:
    """Accept what Explorer's "Copy as path" gives: quotes, file://, spaces."""
    text = str(raw or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    if text.lower().startswith("file:///"):
        text = text[8:]
    elif text.lower().startswith("file://"):
        text = text[7:]
    return text


def _resolve_video(raw: object) -> Path:
    text = _clean_path(raw)
    if not text:
        raise nvidia_fix.NvidiaFixError("Paste the full path to a video file.")

    path = Path(text).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    else:
        path = path.resolve()

    if not path.exists():
        raise nvidia_fix.NvidiaFixError(f"No file exists at: {path}")
    if not path.is_file():
        raise nvidia_fix.NvidiaFixError(f"That is a folder, not a video file: {path}")

    suffix = path.suffix.lower()
    if suffix not in nvidia_fix.SUPPORTED_SUFFIXES:
        raise nvidia_fix.UnsupportedMediaError(
            f"Unsupported file type: {suffix or '(none)'}. "
            "Supported: " + ", ".join(sorted(nvidia_fix.SUPPORTED_SUFFIXES))
        )
    return path


# --------------------------------------------------------------------------
# result shaping
# --------------------------------------------------------------------------

def _output_saved_note(path: str) -> str:
    return f"Saved next to the original in {Path(path).parent}"


def _output_entries(result: Dict[str, object]) -> list:
    paths = result.get("paths") or {}
    recovery = result.get("recovery") or {}
    video = recovery.get("video") or {}
    audio = recovery.get("audio") or {}
    full_length = result.get("full_length") or {}

    entries = []
    if paths.get("video"):
        entries.append({
            "label": "Clean video",
            "detail": "Stream-copied from the first intact keyframe. No re-encode.",
            "path": paths["video"],
            "name": Path(paths["video"]).name,
            "size_bytes": video.get("size_bytes"),
            "kind": "video",
        })
    if paths.get("audio"):
        entries.append({
            "label": "Early audio",
            "detail": "Audio that survives before the cut, exported separately.",
            "path": paths["audio"],
            "name": Path(paths["audio"]).name,
            "size_bytes": audio.get("size_bytes"),
            "kind": "audio",
        })
    if paths.get("full_length"):
        entries.append({
            "label": "Full-length rebuild",
            "detail": "Duplicate footage joined to the clean tail. Not the original opening.",
            "path": paths["full_length"],
            "name": Path(paths["full_length"]).name,
            "size_bytes": full_length.get("size_bytes"),
            "kind": "full",
        })
    if paths.get("report"):
        entries.append({
            "label": "Recovery report",
            "detail": "Boundary timestamps, hashes and decode verification in JSON.",
            "path": paths["report"],
            "name": Path(paths["report"]).name,
            "size_bytes": None,
            "kind": "report",
        })
    return entries


def _suggested_path() -> str:
    """Pre-fill the box with the sample recording when it is present."""
    sample = BASE_DIR / "recovery" / "Arc_Raiders corrupted.mp4"
    return str(sample) if sample.is_file() else ""


def _index(error: Optional[str] = None, healthy: Optional[str] = None,
           video_path: str = "", result: Optional[Dict[str, object]] = None):
    return render_template(
        "index.html",
        error=error,
        healthy=healthy,
        video_path=video_path,
        result=result,
        suggested_path=_suggested_path(),
        supported=", ".join(sorted(nvidia_fix.SUPPORTED_SUFFIXES)),
        version=APP_VERSION,
    )


def _run_fix(raw_path: object, full_decode: bool) -> Tuple[Dict[str, object], Path]:
    source = _resolve_video(raw_path)
    # No out_dir: the engine writes <stem>.clean.mp4 beside the input file.
    result = nvidia_fix.process(source, out_dir=None, full_decode=full_decode)
    result["original_name"] = source.name
    result["original_path"] = str(source)
    result["outputs"] = _output_entries(result)
    result["output_dir"] = str(source.parent)
    result["saved_note"] = _output_saved_note(
        (result.get("paths") or {}).get("video") or str(source)
    )
    return result, source


def _wants_full_decode(data, is_form: bool = False) -> bool:
    if is_form:
        # An unchecked HTML checkbox is simply absent.
        return str(data.get("full_decode", "")).strip().lower() not in {
            "0", "false", "off", "no", "",
        }
    raw = data.get("full_decode", True)
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() not in {"0", "false", "off", "no", ""}


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------

@app.get("/")
def index():
    return _index()


@app.post("/fix")
def fix():
    raw_path = request.form.get("video_path") or request.form.get("path") or ""
    try:
        result, _ = _run_fix(raw_path, _wants_full_decode(request.form, is_form=True))
    except nvidia_fix.NvidiaFixError as exc:
        return _index(error=str(exc), video_path=raw_path), 400
    except Exception:
        app.logger.exception("Unexpected failure while processing %s", raw_path)
        return _index(
            error="Unexpected server error. Check the terminal running the app.",
            video_path=raw_path,
        ), 500

    if result.get("status") == "healthy":
        return _index(
            healthy=result.get("message")
            or "No corruption detected. This file is already intact.",
            video_path=raw_path,
        )
    return _index(result=result, video_path=raw_path)


@app.post("/api/fix")
def api_fix():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = request.form
    raw_path = data.get("path") or data.get("video_path") or ""
    try:
        result, _ = _run_fix(raw_path, _wants_full_decode(data))
        return jsonify(result)
    except nvidia_fix.NvidiaFixError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        app.logger.exception("Unexpected failure while processing %s", raw_path)
        return jsonify({"error": "Unexpected server error"}), 500


@app.get("/healthz")
def healthz():
    return jsonify({"status": "ok", "version": APP_VERSION})


def _open_browser(url: str) -> None:
    try:
        webbrowser.open(url)
    except Exception:
        pass


if __name__ == "__main__":
    host = os.environ.get("NVIDIA_FIX_HOST", "127.0.0.1")
    port = int(os.environ.get("NVIDIA_FIX_PORT", "5000"))
    url = f"http://{host}:{port}/"
    if not os.environ.get("NVIDIA_FIX_NO_BROWSER"):
        Timer(1.2, _open_browser, args=(url,)).start()
    print(f"NVIDIA-Fix {APP_VERSION} running at {url}")
    app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)
