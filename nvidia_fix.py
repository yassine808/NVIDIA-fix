#!/usr/bin/env python3
"""
nvidia-fix: recover the clean tail of an NVIDIA ShadowPlay recording that was
corrupted by an in-place overwrite.

The recorder sometimes replaces the beginning of a recording with a later chunk
of the same recording.  The container index still describes the original
timeline, but the first samples no longer contain valid H.264.  The file is
still playable from the first intact IDR onward.

This tool finds the last invalid sample, picks the first clean IDR after it,
verifies that the cut starts on the exact packet, stream-copies the tail, and
exports the audio that precedes the cut.

It cannot reconstruct video that was overwritten.  Be honest about that.

Requires ffmpeg and ffprobe on PATH (or FFMPEG_BINARY / FFPROBE_BINARY).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

TOOL = "nvidia-fix"
VERSION = "1.1.1"

FFMPEG = os.environ.get("FFMPEG_BINARY", "ffmpeg")
FFPROBE = os.environ.get("FFPROBE_BINARY", "ffprobe")

SEEK_OFFSET = 0.005          # land just after the chosen IDR when seeking
CANDIDATE_RUN = 120          # samples that must be valid after a candidate
MIN_RUN = 30                 # ...but accept shorter runs near EOF
DECODE_VALIDATE_SECONDS = 2  # decode check on the produced tail
SUPPORTED_VIDEO_CODECS = {"h264"}
SUPPORTED_SUFFIXES = {".mp4", ".mov", ".m4v"}

CAVEAT = (
    "Only the footage from clean_start onward is recoverable. Earlier video "
    "was overwritten in place by the recorder and cannot be reconstructed from "
    "this file. Audio before clean_start is exported separately."
)


class NvidiaFixError(RuntimeError):
    """Base error with a message suitable for CLI/UI display."""


class UnsupportedMediaError(NvidiaFixError):
    pass


class NoCleanKeyframeError(NvidiaFixError):
    pass


class ProcessingError(NvidiaFixError):
    pass


@dataclass
class Sample:
    index: int
    pts: float
    dts: float
    size: int
    pos: int
    flags: str
    valid: bool
    nal_type: int


@dataclass
class Analysis:
    path: Path
    media: Dict[str, object]
    samples: List[Sample]
    candidates: List[Sample]
    bad_samples: int
    first_bad: Optional[Sample]
    last_bad: Optional[Sample]
    clean_run: int
    warning: str = CAVEAT

    @property
    def healthy(self) -> bool:
        return self.bad_samples == 0

    @property
    def boundary(self) -> Optional[Sample]:
        return self.candidates[0] if self.candidates else None

    @property
    def status(self) -> str:
        if self.healthy:
            return "healthy"
        if self.candidates:
            return "recoverable"
        return "unrecoverable"

    def to_dict(self) -> Dict[str, object]:
        video = self.media.get("video") or {}
        audio = self.media.get("audio") or {}
        boundary = self.boundary
        return {
            "tool": TOOL,
            "version": VERSION,
            "status": self.status,
            "input": {
                "name": self.path.name,
                "size_bytes": self.path.stat().st_size,
            },
            "media": {
                "container": self.media.get("container"),
                "duration_seconds": self.media.get("duration"),
                "video_codec": video.get("codec_name"),
                "width": video.get("width"),
                "height": video.get("height"),
                "audio_codec": audio.get("codec_name"),
            },
            "corruption": {
                "total_video_samples": len(self.samples),
                "bad_samples": self.bad_samples,
                "first_bad_seconds": _t(self.first_bad.pts) if self.first_bad else None,
                "last_bad_seconds": _t(self.last_bad.pts) if self.last_bad else None,
                "last_bad_index": self.last_bad.index if self.last_bad else None,
                "clean_start_seconds": _t(boundary.pts) if boundary else None,
                "clean_start_index": boundary.index if boundary else None,
                "clean_run_samples": self.clean_run,
            },
            "candidates": [
                {
                    "seconds": _t(c.pts),
                    "index": c.index,
                    "size": c.size,
                    "flags": c.flags,
                    "nal_type": c.nal_type,
                }
                for c in self.candidates[:10]
            ],
            "warning": None if self.healthy else self.warning,
        }


# --------------------------------------------------------------------------
# process helpers
# --------------------------------------------------------------------------

def _run(cmd: Sequence[str], check: bool = True, timeout: int = 600) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            list(cmd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise NvidiaFixError(
            f"Required executable not found: {cmd[0]}. Install ffmpeg/ffprobe and "
            "make sure they are on PATH."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise NvidiaFixError(f"Command timed out after {timeout}s: {cmd[0]}") from exc
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise ProcessingError(
            f"{Path(cmd[0]).name} exited with {result.returncode}: {detail[-2000:]}"
        )
    return result


def _ffprobe_json(args: Sequence[str], timeout: int = 300) -> Dict[str, object]:
    result = _run([FFPROBE, "-v", "error", *args], timeout=timeout)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise NvidiaFixError(f"ffprobe returned invalid JSON: {result.stdout[:500]}") from exc


def _float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _t(value: float) -> float:
    return round(float(value), 6)


def ensure_tools() -> None:
    missing = [name for name in (FFMPEG, FFPROBE) if shutil.which(name) is None]
    if missing:
        raise NvidiaFixError(
            "Missing required tool(s): " + ", ".join(missing) +
            ". Install ffmpeg (which includes ffprobe) and put both on PATH."
        )


# --------------------------------------------------------------------------
# probing
# --------------------------------------------------------------------------

def probe_media(path: Path) -> Dict[str, object]:
    data = _ffprobe_json([
        "-show_format", "-show_streams", "-of", "json", str(path),
    ])
    streams = data.get("streams") or []
    fmt = data.get("format") or {}

    video = None
    audio = None
    for stream in streams:
        kind = stream.get("codec_type")
        if kind == "video" and video is None:
            if (stream.get("disposition") or {}).get("attached_pic"):
                continue
            video = stream
        elif kind == "audio" and audio is None:
            audio = stream

    if not video:
        raise UnsupportedMediaError("No video stream found in this file.")

    codec = str(video.get("codec_name") or "").lower()
    if codec not in SUPPORTED_VIDEO_CODECS:
        pretty = codec.upper() if codec else "unknown"
        raise UnsupportedMediaError(
            f"Unsupported video codec: {pretty}. This tool currently supports "
            "H.264 (AVC) MP4/MOV recordings only. HEVC is not supported yet."
        )

    duration = _float(fmt.get("duration"), _float(video.get("duration"), 0.0))
    return {
        "container": fmt.get("format_name"),
        "duration": duration,
        "video": {
            "codec_name": codec,
            "profile": video.get("profile"),
            "width": int(video.get("width") or 0),
            "height": int(video.get("height") or 0),
            "avg_frame_rate": video.get("avg_frame_rate"),
            "duration": _float(video.get("duration"), duration),
        },
        "audio": {
            "codec_name": str(audio.get("codec_name") or "").lower(),
            "channels": audio.get("channels"),
            "sample_rate": audio.get("sample_rate"),
        } if audio else None,
    }


def probe_packets(path: Path, timeout: int = 300) -> List[Sample]:
    data = _ffprobe_json([
        "-select_streams", "v:0",
        "-show_entries", "packet=pts_time,dts_time,size,pos,flags",
        "-of", "json", str(path),
    ], timeout=timeout)

    samples: List[Sample] = []
    for i, packet in enumerate(data.get("packets") or []):
        pos = packet.get("pos")
        size = packet.get("size")
        if pos is None or size is None:
            raise UnsupportedMediaError(
                "This file does not expose video packet byte offsets, which are "
                "needed to inspect the H.264 data. Remux it with "
                "`ffmpeg -i input.mp4 -c copy remuxed.mp4` and try again."
            )
        pts = packet.get("pts_time")
        dts = packet.get("dts_time")
        if pts is None and dts is None:
            raise UnsupportedMediaError("A video packet has no timestamp.")
        samples.append(Sample(
            index=i,
            pts=_float(pts if pts is not None else dts),
            dts=_float(dts if dts is not None else pts),
            size=int(size),
            pos=int(pos),
            flags=str(packet.get("flags") or ""),
            valid=False,
            nal_type=-1,
        ))
    if not samples:
        raise UnsupportedMediaError("No video packets found in this file.")
    return samples


# --------------------------------------------------------------------------
# corruption detection
# --------------------------------------------------------------------------

def _avcc_nal_types(data: bytes) -> Optional[List[int]]:
    """Return every NAL type if the sample is well-formed AVCC, else None."""
    offset = 0
    total = len(data)
    types: List[int] = []
    while offset < total:
        if offset + 4 > total:
            return None
        length = int.from_bytes(data[offset:offset + 4], "big")
        if length <= 0 or offset + 4 + length > total:
            return None
        header = data[offset + 4]
        if header & 0x80:              # forbidden_zero_bit
            return None
        nal_type = header & 0x1F
        if not 1 <= nal_type <= 12:
            return None
        types.append(nal_type)
        offset += 4 + length
    return types if offset == total and types else None


def _check_sample(handle, sample: Sample) -> None:
    """Set sample.valid / sample.nal_type by inspecting the sample payload."""
    if sample.size < 5 or sample.pos < 0:
        sample.valid = False
        sample.nal_type = -1
        return

    handle.seek(sample.pos)
    header = handle.read(5)
    if len(header) < 5:
        sample.valid = False
        sample.nal_type = -1
        return

    outer = int.from_bytes(header[:4], "big")
    nal = header[4]
    nal_type = nal & 0x1F
    sample.nal_type = nal_type

    # Fast path: the overwhelming majority of samples hold exactly one NAL.
    if outer == sample.size - 4 and not (nal & 0x80) and 1 <= nal_type <= 12:
        sample.valid = True
        return

    # Slow path: multi-NAL samples, or corruption. Read the whole sample and
    # validate every length-prefixed NAL unit.
    handle.seek(sample.pos)
    data = handle.read(sample.size)
    types = _avcc_nal_types(data) if len(data) == sample.size else None
    sample.valid = types is not None
    if types is not None:
        # A sample may carry SPS/SEI/AUD before the IDR. Treat any IDR in the
        # sample as the identifying NAL type for keyframe detection.
        sample.nal_type = 5 if 5 in types else types[0]


def analyze(path: str | Path) -> Analysis:
    ensure_tools()
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise NvidiaFixError(f"Input file not found: {source}")
    if source.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise UnsupportedMediaError(
            f"Unsupported file extension: {source.suffix or '(none)'}. "
            "Supported: " + ", ".join(sorted(SUPPORTED_SUFFIXES))
        )

    media = probe_media(source)
    samples = probe_packets(source)

    with open(source, "rb") as handle:
        for sample in samples:
            _check_sample(handle, sample)

    bad = [s for s in samples if not s.valid]
    if not bad:
        return Analysis(
            path=source, media=media, samples=samples, candidates=[],
            bad_samples=0, first_bad=None, last_bad=None, clean_run=0,
        )

    last_bad = bad[-1]
    candidates: List[Sample] = []
    clean_run = 0
    for i in range(last_bad.index + 1, len(samples)):
        sample = samples[i]
        if not (sample.valid and ("K" in sample.flags or sample.nal_type == 5)):
            continue
        run = samples[i:i + CANDIDATE_RUN]
        need = min(MIN_RUN, len(samples) - i)
        if need >= 5 and len(run) >= need and all(s.valid for s in run[:need]):
            candidates.append(sample)
            if not clean_run:
                for item in run:
                    if not item.valid:
                        break
                    clean_run += 1
            if len(candidates) >= 20:
                break

    return Analysis(
        path=source, media=media, samples=samples, candidates=candidates,
        bad_samples=len(bad), first_bad=bad[0], last_bad=last_bad,
        clean_run=clean_run,
    )


# --------------------------------------------------------------------------
# cutting / verification
# --------------------------------------------------------------------------

def _unique_base(out_dir: Path, stem: str, audio_ext: str) -> str:
    base = f"{stem}.clean"
    index = 1
    while any((out_dir / f"{base}{ext}").exists() for ext in
              (".mp4", f".audio{audio_ext}", ".report.json")):
        index += 1
        base = f"{stem}.clean-{index}"
    return base


# Messages from ffmpeg's null muxer about timestamps. ShadowPlay records 120 fps
# with B-frames, so the decoder hands the muxer repeated dts values and the null
# muxer complains. That is a property of the verification command, not damage in
# the recovered file, so it must not reject a clean cut.
_MUXER_WARNING_MARKERS = (
    "non monotonically increasing dts",
    "non-monotonous dts",
)

# Messages that mean the bitstream itself did not decode.
_DECODER_ERROR_MARKERS = (
    "error while decoding",
    "corrupt decoded frame",
    "invalid nal unit",
    "no frame!",
    "non-existing pps",
    "non-existing sps",
    "illegal short term buffer state",
    "illegal reordering_of_pic_nums_idc",
    "decode_slice_header error",
    "error splitting the input",
    "invalid data found when processing input",
    "packet corrupt",
    "header missing",
    "concealing",
    "frame num change",
)


@dataclass
class DecodeCheck:
    """Decoder verdict plus the warnings that are not the file's fault."""

    errors: List[str]
    warnings: List[str]
    unclassified: List[str]
    returncode: int

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.errors


def _classify_stderr(lines: Sequence[str]) -> DecodeCheck:
    errors: List[str] = []
    warnings: List[str] = []
    unclassified: List[str] = []
    for line in lines:
        low = line.lower()
        if any(marker in low for marker in _MUXER_WARNING_MARKERS):
            warnings.append(line)
        elif any(marker in low for marker in _DECODER_ERROR_MARKERS):
            errors.append(line)
        else:
            unclassified.append(line)
    return DecodeCheck(errors, warnings, unclassified, returncode=0)


def _decode_check(path: Path, seconds: Optional[float] = None,
                  timeout: int = 1800) -> DecodeCheck:
    cmd = [FFMPEG, "-hide_banner", "-v", "error", "-nostdin", "-i", str(path)]
    if seconds is not None:
        cmd += ["-t", f"{seconds:.3f}"]
    cmd += ["-map", "0:v:0", "-f", "null", "-"]
    result = _run(cmd, check=False, timeout=timeout)
    lines = [line.strip() for line in (result.stderr or "").splitlines() if line.strip()]
    check = _classify_stderr(lines)
    check.returncode = result.returncode
    if result.returncode != 0 and not lines:
        check.errors.append(f"ffmpeg exited with {result.returncode}")
    return check


def _cut_tail(source: Path, candidate: Sample, target: Path,
              timeout: int = 1800) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    seek = candidate.pts + SEEK_OFFSET
    cmd = [
        FFMPEG, "-hide_banner", "-v", "error", "-nostdin", "-y",
        "-ss", f"{seek:.6f}",
        "-i", str(source),
        "-map", "0:v:0", "-map", "0:a:0?",
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart",
        str(target),
    ]
    _run(cmd, timeout=timeout)


def _verify_first_packet(source: Path, candidate: Sample, output: Path) -> Dict[str, object]:
    packets = probe_packets(output)
    first = packets[0]
    if first.size != candidate.size:
        return {
            "ok": False,
            "reason": (
                f"first output packet is {first.size} bytes, expected "
                f"{candidate.size} (seek landed on a different sample)"
            ),
        }
    with open(source, "rb") as handle:
        handle.seek(candidate.pos)
        source_payload = handle.read(candidate.size)
    with open(output, "rb") as handle:
        handle.seek(first.pos)
        output_payload = handle.read(first.size)
    if len(source_payload) != candidate.size or source_payload != output_payload:
        return {"ok": False, "reason": "first output packet payload differs from source sample"}

    digest = hashlib.sha256(source_payload).hexdigest()
    return {
        "ok": True,
        "first_packet_sha256": digest,
        "source_sample_sha256": digest,
        "output_packets": len(packets),
        "first_packet_pts": _t(first.pts),
    }


def _export_early_audio(source: Path, boundary: float, target: Path,
                        timeout: int = 1800) -> None:
    cmd = [
        FFMPEG, "-hide_banner", "-v", "error", "-nostdin", "-y",
        "-i", str(source),
        "-t", f"{boundary:.6f}",
        "-map", "0:a:0", "-vn", "-c", "copy",
        str(target),
    ]
    _run(cmd, timeout=timeout)


def _probe_duration(path: Path) -> float:
    data = _ffprobe_json(["-show_entries", "format=duration", "-of", "json", str(path)])
    return _float((data.get("format") or {}).get("duration"), 0.0)


# --------------------------------------------------------------------------
# main workflow
# --------------------------------------------------------------------------

ProgressCallback = Callable[[str], None]


def _notify(progress: Optional[ProgressCallback], message: str) -> None:
    if progress is None:
        return
    try:
        progress(message)
    except Exception:
        # A UI callback must never break recovery.
        pass


def process(path: str | Path, out_dir: Optional[str | Path] = None,
            full_decode: bool = True,
            progress: Optional[ProgressCallback] = None) -> Dict[str, object]:
    source = Path(path).expanduser().resolve()
    _notify(progress, "Reading the container and scanning every video sample…")
    analysis = analyze(source)
    analysis_doc = analysis.to_dict()

    if analysis.healthy:
        _notify(progress, "No corruption detected. The file is already intact.")
        return {
            **analysis_doc,
            "status": "healthy",
            "message": "No corruption detected. This file is already intact.",
            "recovery": None,
            "paths": None,
        }

    if not analysis.candidates:
        raise NoCleanKeyframeError(
            "No clean keyframe was found after the last damaged sample. The "
            "corruption may extend to the end of the file, so no clean tail can "
            "be recovered."
        )

    _notify(
        progress,
        f"Found {analysis.bad_samples:,} damaged samples. "
        f"First clean keyframe: {analysis.candidates[0].pts:.3f} s.",
    )

    destination = Path(out_dir).expanduser().resolve() if out_dir else source.parent
    destination.mkdir(parents=True, exist_ok=True)

    audio_codec = (analysis.media.get("audio") or {}).get("codec_name") or ""
    audio_ext = ".m4a" if audio_codec == "aac" else ".mka"
    base = _unique_base(destination, source.stem, audio_ext)
    video_out = destination / f"{base}.mp4"
    audio_out = destination / f"{base}.audio{audio_ext}"
    report_out = destination / f"{base}.report.json"

    accepted: Optional[Sample] = None
    verify: Dict[str, object] = {}
    attempts: List[Dict[str, object]] = []

    for attempt, candidate in enumerate(analysis.candidates, start=1):
        temp = destination / f"{base}.try{attempt}.part.mp4"
        try:
            _notify(
                progress,
                f"Cutting the clean tail from {candidate.pts:.3f} s "
                f"(candidate {attempt} of {len(analysis.candidates)})…",
            )
            _cut_tail(source, candidate, temp)
            _notify(progress, "Verifying that the cut starts on the exact source packet…")
            check = _verify_first_packet(source, candidate, temp)
            if not check.get("ok"):
                attempts.append({"seconds": _t(candidate.pts), "error": check.get("reason")})
                continue
            _notify(progress, "Checking the first seconds of the recovered video…")
            start_check = _decode_check(temp, DECODE_VALIDATE_SECONDS)
            if not start_check.ok:
                blocking = start_check.errors or start_check.unclassified or [
                    f"ffmpeg exited with {start_check.returncode}"
                ]
                attempts.append({
                    "seconds": _t(candidate.pts),
                    "error": "decode errors at start of cut",
                    "details": blocking[:5],
                })
                continue
            os.replace(temp, video_out)
            accepted = candidate
            verify = check
            break
        finally:
            if temp.exists():
                temp.unlink()

    if accepted is None:
        raise ProcessingError(
            "Could not produce a clean tail. Every clean keyframe candidate "
            f"failed verification: {attempts[:3]}"
        )

    audio_info = None
    if analysis.media.get("audio"):
        try:
            _notify(progress, "Exporting the audio from before the cut…")
            _export_early_audio(source, accepted.pts, audio_out)
            audio_info = {
                "name": audio_out.name,
                "size_bytes": audio_out.stat().st_size,
                "duration_seconds": _t(_probe_duration(audio_out)),
            }
        except NvidiaFixError:
            if audio_out.exists():
                audio_out.unlink()
            audio_info = None

    decode_check = DecodeCheck([], [], [], returncode=0)
    if full_decode:
        _notify(progress, "Decoding the recovered video to verify it…")
        decode_check = _decode_check(video_out)
    decode_errors = decode_check.errors

    duration = _probe_duration(video_out)
    try:
        output_media = probe_media(video_out)
        duration = _float((output_media.get("video") or {}).get("duration"), duration)
    except NvidiaFixError:
        pass
    report: Dict[str, object] = {
        **analysis_doc,
        "status": "success" if decode_check.ok and not decode_check.unclassified
        else "success_with_warnings",
        "recovery": {
            "clean_start_seconds": _t(accepted.pts),
            "video": {
                "name": video_out.name,
                "size_bytes": video_out.stat().st_size,
                "duration_seconds": _t(duration),
                "packets": int(verify.get("output_packets") or 0),
                "first_packet_sha256": verify.get("first_packet_sha256"),
                "source_sample_sha256": verify.get("source_sample_sha256"),
                "decode_errors": len(decode_errors),
            },
            "audio": audio_info,
            "decode_error_sample": decode_errors[:20],
            "muxer_warnings": len(decode_check.warnings),
            "muxer_warning_sample": decode_check.warnings[:3],
            "unclassified_output": decode_check.unclassified[:5],
            "full_decode_returncode": decode_check.returncode,
            "attempts": attempts,
        },
        "caveat": CAVEAT,
    }
    if decode_errors:
        report["warning"] = (
            "The tail was recovered and its first packets verify, but a full "
            "decode reported errors. Inspect the decode_error_sample list."
        )
    elif decode_check.unclassified:
        report["warning"] = (
            "The full decode produced output this tool could not classify. "
            "Inspect recovery.unclassified_output."
        )

    _notify(progress, "Writing the recovery report…")
    report_out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        **report,
        "paths": {
            "video": str(video_out),
            "audio": str(audio_out) if audio_info else None,
            "report": str(report_out),
        },
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _print_analysis(analysis: Analysis) -> None:
    video = analysis.media.get("video") or {}
    if analysis.healthy:
        print("No corruption detected. The file is intact.")
        return
    boundary = analysis.boundary
    print(f"Input        : {analysis.path}")
    print(f"Video        : {video.get('codec_name')} {video.get('width')}x{video.get('height')}")
    print(f"Samples      : {len(analysis.samples)} ({analysis.bad_samples} invalid)")
    print(f"First bad    : {analysis.first_bad.pts:.3f}s")
    print(f"Last bad     : {analysis.last_bad.pts:.3f}s")
    if boundary:
        print(f"Clean IDR    : {boundary.pts:.6f}s (index {boundary.index})")
    else:
        print("Clean IDR    : none found")
    print()
    print(analysis.warning)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nvidia_fix.py",
        description="Recover the clean tail of a corrupted NVIDIA ShadowPlay recording.",
    )
    parser.add_argument("--version", action="version", version=f"{TOOL} {VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_analyze = sub.add_parser("analyze", help="inspect a file without writing outputs")
    p_analyze.add_argument("input")
    p_analyze.add_argument("--json", action="store_true", help="print JSON")

    p_fix = sub.add_parser("fix", help="recover the clean tail")
    p_fix.add_argument("input")
    p_fix.add_argument("--out", help="output directory (default: next to input)")
    p_fix.add_argument("--no-full-decode", action="store_true",
                       help="skip the full decode verification (faster)")
    p_fix.add_argument("--json", action="store_true", help="print JSON")

    p_serve = sub.add_parser("serve", help="start the local web app")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=5000)

    args = parser.parse_args(argv)

    try:
        if args.command == "analyze":
            analysis = analyze(args.input)
            if args.json:
                print(json.dumps(analysis.to_dict(), indent=2, ensure_ascii=False))
            else:
                _print_analysis(analysis)
            return 0

        if args.command == "fix":
            result = process(args.input, out_dir=args.out,
                             full_decode=not args.no_full_decode)
            if args.json:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            elif result["status"] == "healthy":
                print(result["message"])
            else:
                paths = result["paths"]
                print(f"Clean tail   : {paths['video']}")
                if paths.get("audio"):
                    print(f"Early audio  : {paths['audio']}")
                print(f"Report       : {paths['report']}")
                print(f"Status       : {result['status']}")
                decode = result["recovery"]["video"]["decode_errors"]
                print(f"Decode errors: {decode}")
                warnings = result["recovery"].get("muxer_warnings") or 0
                if warnings:
                    print(f"Muxer warning: {warnings} timestamp warning(s) (not file damage)")
            return 0

        if args.command == "serve":
            import app as webapp
            webapp.app.run(host=args.host, port=args.port, debug=False,
                           use_reloader=False, threaded=True)
            return 0
    except NvidiaFixError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
