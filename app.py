from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Dict, Tuple

from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from werkzeug.utils import secure_filename

import nvidia_fix

BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__, instance_relative_config=True)

MAX_UPLOAD_MB = int(os.environ.get("NVIDIA_FIX_MAX_UPLOAD_MB", "8192"))
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
app.config["MAX_UPLOAD_MB"] = MAX_UPLOAD_MB

RESULTS_DIR = Path(
    os.environ.get("NVIDIA_FIX_RESULTS", Path(app.instance_path) / "results")
).resolve()
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


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



def _valid_job(job: str) -> bool:
    return len(job) == 32 and all(c in "0123456789abcdef" for c in job)


def _result_dir(job: str) -> Path:
    if not _valid_job(job):
        abort(404)
    return RESULTS_DIR / job


def _load_result(job: str) -> Dict[str, object]:
    path = _result_dir(job) / "result.json"
    if not path.is_file():
        abort(404)
    return json.loads(path.read_text(encoding="utf-8"))


def _download_entries(result: Dict[str, object]) -> list:
    entries = []
    paths = result.get("paths") or {}
    recovery = result.get("recovery") or {}
    video = recovery.get("video") or {}
    audio = recovery.get("audio") or {}
    if paths.get("video"):
        entries.append({
            "name": Path(paths["video"]).name,
            "label": "Clean tail",
            "detail": "MP4 video from the first intact keyframe",
            "size_bytes": video.get("size_bytes"),
        })
    if paths.get("audio"):
        entries.append({
            "name": Path(paths["audio"]).name,
            "label": "Early audio",
            "detail": "Audio from the unrecoverable section",
            "size_bytes": audio.get("size_bytes"),
        })
    if paths.get("report"):
        entries.append({
            "name": Path(paths["report"]).name,
            "label": "Recovery report",
            "detail": "JSON evidence, timings and verification values",
            "size_bytes": None,
        })
    return entries


def _handle_upload() -> Tuple[Dict[str, object], int]:
    upload = request.files.get("video")
    if upload is None or not upload.filename:
        raise nvidia_fix.NvidiaFixError("Choose a video file to upload.")

    original = Path(upload.filename).name
    suffix = Path(original).suffix.lower()
    if suffix not in nvidia_fix.SUPPORTED_SUFFIXES:
        raise nvidia_fix.UnsupportedMediaError(
            f"Unsupported file type: {suffix or '(none)'}. "
            "Supported: " + ", ".join(sorted(nvidia_fix.SUPPORTED_SUFFIXES))
        )

    job = uuid.uuid4().hex
    upload_dir = Path(tempfile.mkdtemp(prefix="nvidia-fix-upload-"))
    safe_name = secure_filename(original) or f"recording{suffix}"
    if Path(safe_name).suffix.lower() != suffix:
        safe_name = f"{Path(safe_name).stem or 'recording'}{suffix}"
    saved = upload_dir / safe_name
    result_dir = RESULTS_DIR / job
    result_dir.mkdir(parents=True, exist_ok=True)

    try:
        upload.save(saved)
        result = nvidia_fix.process(saved, out_dir=result_dir, full_decode=True)
    except Exception:
        shutil.rmtree(result_dir, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(upload_dir, ignore_errors=True)

    if result.get("status") == "healthy":
        shutil.rmtree(result_dir, ignore_errors=True)
        return result, 200

    result["original_name"] = original
    result["job_id"] = job
    result["downloads"] = _download_entries(result)
    (result_dir / "result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return result, 200


@app.get("/")
def index():
    return render_template(
        "index.html",
        max_upload_mb=app.config["MAX_UPLOAD_MB"],
        error=None,
        healthy=None,
    )


@app.post("/fix")
def fix():
    try:
        result, _ = _handle_upload()
    except nvidia_fix.NvidiaFixError as exc:
        return render_template(
            "index.html",
            max_upload_mb=app.config["MAX_UPLOAD_MB"],
            error=str(exc),
            healthy=None,
        ), 400
    except Exception:
        app.logger.exception("Unexpected failure while processing upload")
        return render_template(
            "index.html",
            max_upload_mb=app.config["MAX_UPLOAD_MB"],
            error="Unexpected server error. Check the terminal running the app.",
            healthy=None,
        ), 500

    if result.get("status") == "healthy":
        return render_template(
            "index.html",
            max_upload_mb=app.config["MAX_UPLOAD_MB"],
            error=None,
            healthy=result.get("message")
            or "No corruption detected. This file is already intact.",
        )
    return redirect(url_for("result", job=result["job_id"]))


@app.post("/api/fix")
def api_fix():
    try:
        result, _ = _handle_upload()
        return jsonify(result)
    except nvidia_fix.NvidiaFixError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        app.logger.exception("Unexpected failure while processing upload")
        return jsonify({"error": "Unexpected server error"}), 500


@app.get("/result/<job>")
def result(job: str):
    data = _load_result(job)
    return render_template("result.html", result=data, job=job)


@app.get("/download/<job>/<name>")
def download(job: str, name: str):
    data = _load_result(job)
    allowed = {entry["name"] for entry in data.get("downloads") or []}
    if name not in allowed:
        abort(404)
    return send_from_directory(_result_dir(job), name, as_attachment=True)


@app.errorhandler(413)
def too_large(_error):
    message = (
        f"File is larger than the {app.config['MAX_UPLOAD_MB']} MB limit. "
        "Raise NVIDIA_FIX_MAX_UPLOAD_MB and restart the app, or use the CLI."
    )
    if request.path.startswith("/api/"):
        return jsonify({"error": message}), 413
    return render_template(
        "index.html",
        max_upload_mb=app.config["MAX_UPLOAD_MB"],
        error=message,
        healthy=None,
    ), 413


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False, threaded=True)
