# nvidia-fix

Recover the clean tail of an NVIDIA ShadowPlay recording that was corrupted by an
in-place overwrite. Includes a native Windows desktop app.

The failure this tool targets: a recording is created, then the recorder replaces its
beginning with a later chunk of the same recording. The MP4 index still describes the
original timeline, so players show a file that starts with broken or duplicated
footage. The ending is usually untouched. `nvidia-fix` finds where the damage stops
and extracts everything from the first intact keyframe onward, without re-encoding.

It does **not** pretend to recover video that was overwritten. The lost section is
gone. What survives is the clean tail plus the early audio.

## What you get

For an input named `clip.mp4`:

| Output | Contents |
| --- | --- |
| `clip.clean.mp4` | Video stream-copied from the first clean IDR, plus original audio |
| `clip.clean.audio.m4a` | Audio before the cut, so the surviving early audio is not lost |
| `clip.clean.report.json` | Boundary timestamps, sample counts, packet SHA-256, decode results |

Existing files are never overwritten. A second run produces `clip.clean-2.mp4`, etc.
The input file is opened read-only.

## Desktop app (Windows)

Download **[NVIDIA-Fix.exe](https://github.com/yassine808/NVIDIA-fix/releases/latest/download/NVIDIA-Fix.exe)**
from the latest release.

1. Install ffmpeg/ffprobe and make sure `ffmpeg -version` works in a terminal:
   `winget install Gyan.FFmpeg`
2. Run `NVIDIA-Fix.exe`, choose the corrupted recording, and choose where the
   recovered files should go (defaults to the input folder).
3. Click **Recover clean tail**. When it finishes, use **Play video**,
   **Open folder**, or **Report**.

The desktop app uses the same verified engine as the CLI. It does not modify the
input. The `.exe` does not bundle ffmpeg; it uses the copy on `PATH`.

To run the desktop app from source instead:

```powershell
python desktop.py
```

or double-click `NVIDIA-Fix.pyw` (uses `pythonw`, so no console window). The desktop
app itself needs only Python 3.9+ and ffmpeg/ffprobe; Flask is only for the optional
web UI.

### Build the desktop executable

```powershell
pip install pyinstaller
pyinstaller --noconfirm --onefile --windowed --name "NVIDIA-Fix" `
  --icon assets\nvidia-fix.ico `
  --add-data "assets\nvidia-fix.ico;assets" `
  desktop.py
```

The result is `dist\NVIDIA-Fix.exe`. The executable still expects ffmpeg/ffprobe on
`PATH`.

## Requirements

- Desktop: Windows 10/11, `ffmpeg` and `ffprobe` 6.0 or newer on `PATH`
- Source/CLI: Python 3.9 or newer, plus ffmpeg/ffprobe
- Optional web UI: Flask 3.1 (installed from `requirements.txt`)

On Windows, install ffmpeg with `winget install Gyan.FFmpeg` (or download a build from
<https://ffmpeg.org/download.html>) and reopen the terminal so `ffmpeg -version` works.

## CLI

```powershell
# inspect without writing anything
python nvidia_fix.py analyze "D:\Videos\clip.mp4"

# recover
python nvidia_fix.py fix "D:\Videos\clip.mp4"

# choose an output directory / skip the full decode (faster)
python nvidia_fix.py fix "D:\Videos\clip.mp4" --out "D:\Recovered" --no-full-decode

# JSON output
python nvidia_fix.py analyze "D:\Videos\clip.mp4" --json
python nvidia_fix.py fix "D:\Videos\clip.mp4" --json
```

Exit codes: `0` success (including an already-healthy file), `2` a handled error such
as unsupported codec or no clean keyframe.

## Optional web UI

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Open <http://127.0.0.1:5000>, drop the recording, and wait. Processing is local and
synchronous; a large recording can take a minute because the result is decoded to
verify it. Uploads are limited to 8 GB by default:

```powershell
$env:NVIDIA_FIX_MAX_UPLOAD_MB = "20000"
python app.py
```

## How the boundary is found

1. `ffprobe` lists every video packet with its timestamp, size, and byte offset.
2. Each sample's payload is checked as an AVCC H.264 sample: every length-prefixed NAL
   unit must fit the sample, the forbidden bit must be clear, and the NAL type must be
   1–12. Multi-NAL samples are parsed fully. No decoding is needed for this pass, so it
   is fast even on a 400 MB file.
3. The **last invalid sample** is the damage boundary. Every sample after it is valid.
4. The first keyframe after that boundary with a stable run of at least 30 valid samples
   is the clean start.
5. `ffmpeg -ss <start + 0.005> -i input -c copy` cuts from that IDR. The seek offset
   makes the input seek land on the chosen keyframe.
6. The first output video packet's payload is compared byte-for-byte with the source
   sample's payload. If it does not match, the next candidate keyframe is tried.
7. The first 2 seconds are decoded; then the full recovered video is decoded and any
   error lines are recorded in the report.
8. Early audio is exported with `-t <boundary> -c copy`.

Audio packet granularity means the early-audio file can include a fraction of a second
that belongs after the video boundary. Video frames are never duplicated or re-encoded.

## Supported input

- H.264 (AVC) in MP4, MOV, or M4V
- Files whose packets expose byte offsets (normal non-fragmented MP4/MOV)
- Corruption that leaves a valid keyframe somewhere after the damage

HEVC is rejected with a clear error. Support would require parsing HEVC NAL headers
(types 0–63) and choosing a clean IRAP frame; the current version deliberately does not
guess. Fragmented MP4 may not expose packet offsets; remux with `-c copy` first.

## Verified on a real corrupted recording

The detector and cut were validated against a 439,194,252-byte ShadowPlay DVR:

- 35,998 video samples, 11,000 invalid
- last invalid sample at **113.781922 s**
- first clean IDR at **114.031811 s** (index 13,680)
- 22,318 video packets recovered, 185.98 s of video
- first and last output packet SHA-256 matched the source
- full decode: 0 errors

The early video in that file was overwritten by a drifting copy of later footage, then
replaced by high-entropy garbage with no recoverable reference frames. That section is
not recoverable and the app says so.

## Tests

```powershell
python -m unittest discover -s tests -v
```

The suite generates its own clean and deliberately corrupted clips with ffmpeg and
exercises the detector, cutter, audio export, Flask upload flow, and the desktop UI
(hidden window). The desktop test is skipped if Tk is unavailable. To run the
real-recording integration test:

```powershell
$env:NVIDIA_FIX_REAL_INPUT = "D:\Videos\Arc Raiders\...DVR.mp4"
python -m unittest tests.test_real_file -v
```

That test writes a ~266 MB tail to a temporary directory and deletes it afterwards.

## Notes

- The original file is never modified.
- Outputs are stream copies; quality is identical to the source.
- A healthy file produces a "no corruption detected" result and no outputs.
- The tool is intentionally conservative: if it cannot find a keyframe with a valid
  run, it fails instead of emitting a broken file.
