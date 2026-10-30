# AGENTS.md — NVIDIA-Fix

Operating notes for any agent working in this repository. Read this first, then
update **Mission log** before you stop working.

## Ground rules

- Truth over optimism. Every recovery claim must be backed by a reproducible
  measurement (byte ranges, hashes, frame counts). "It plays" is not "100%".
- If a byte range of the original media is provably gone, say so and quantify
  it. Never present a reconstruction as the original footage.
- The input recording is opened **read-only** in every tool under `recovery/`.
- Never commit media. `recovery/` and `*.mp4|*.mov|*.m4v|*.m4a|*.mka` are ignored.
- No silent guesses about container structure: MP4 `co64` vs `stco` burned us
  once (see log). Verify offsets by parsing the actual NAL framing.

## Layout

| Path | Contents |
| --- | --- |
| `recovery/` | Local workspace: input recording + every artifact. Ignored by git. |
| `recovery/tools/ff/` | Portable ffmpeg/ffprobe 9.0.2 used for decode + stream copy. |
| `forensics/` | Tracked, no-dependency analysis tools. Run with `PYTHONPATH=forensics`. |
| `nvidia_fix.py` | Recovery engine + CLI (what the app runs). |
| `desktop.py` | Tkinter desktop app. |
| `app.py`, `templates/` | Optional Flask UI. |
| `tests/` | Unit + real-file tests. |

Forensics entry points:

```
python forensics/mp4_probe.py "recovery/Arc_Raiders corrupted.mp4" --json recovery/probe.json
python forensics/coverage_report.py
python forensics/bitstream_map.py      # per-10s AVCC validity, orphan scan
python forensics/resync_probe.py       # is a damaged sample merely displaced?
python forensics/byte_dup.py           # do damaged bytes exist elsewhere?
python forensics/duplication_map.py    # drift-mapped copy detection
python forensics/duplication_dense.py  # dense 256 KiB duplication map
python forensics/boundary_find.py      # exact last damaged / first clean sample
python forensics/content_match.py      # thumbnail cross-time matching
```

## Mission status: SOLVED — 100% is provably impossible from this file

Input: `recovery/Arc_Raiders corrupted.mp4` (439,194,252 bytes, ShadowPlay).
Goal was to recover 100% of the ~300 s of footage. Result: **62.1% (186.21 s) is
recoverable; 37.9% (113.78 s) was overwritten in place and no longer exists in
this file.**

### Evidence chain (all reproducible)

1. **Container is intact, not broken.** `ftyp` + one `mdat` (438,672,317 B) +
   `moov` at the end (521,903 B). Video: 35,998 samples, `avc1` 1920×1080,
   120.000 fps, 300.013 s, 1,200 keyframes. Audio: 14,062 AAC frames, 300.010 s.
   The sample tables use **co64** (8-byte offsets).
2. **Nothing is missing or orphaned.** Video chunks describe 98.36% of the
   `mdat`, audio chunks exactly the remaining 1.64% (`7,199,780` B = the whole
   audio track). 298 gaps, all audio interleave. Zero overlaps, zero samples
   outside `mdat`, **zero unreferenced tail**. There is no hidden second copy
   of the recording to restore from.
3. **The damage is in the sample payloads.** AVCC framing parses 100% of samples
   from 113.79 s onward, but only ~32% before that. Damaged samples are not
   merely displaced: no ±4 KiB shift, and no length-prefix width (1/2/4 B),
   re-frames them (`resync_probe.py`).
4. **The prefix is a byte-shifted copy of the tail.** 64-byte needles from the
   damaged prefix are found in the tail at a slowly drifting delta
   (~274.4–274.6 MB, 0.125–0.2% drift). Dense mapping: **80.8% of the prefix is
   a copy of later bytes**, monotonic from container `0.12 s → content 182.54 s`
   to container `107.54 s → content 299.79 s`. The duplication is why the first
   ~108 s "plays" as smeared/duplicated footage: the recorder wrote a later
   stretch of the same stream over the start, at an offset that is not a
   multiple of 4, so the length prefixes are misaligned.
5. **Therefore the unique content set is 113.79 s → 300 s.** Everything before
   113.79 s is either a copy of footage that still exists later in the file, or
   (107.5–113.8 s) unmatched garbage. At least 107.5 s of the original timeline
   is duplicated, so the file cannot encode 300 s of distinct footage. This is
   a counting argument, not an opinion: two regions with identical bytes cannot
   both be the original of different timestamps.

Independent confirmation from the decoder: per-30 s segment decode gives
2,116 / 1,545 / 959 / 522 frames for 0–120 s (expected 3,600 each) and exactly
3,601 for every segment from 120 s to 300 s.

Exact boundary (`boundary_find.py`): last damaged sample **13,650 @ 113.782 s**,
first clean sample **13,651 @ 113.790 s**, which is also a keyframe.

### What would make 100% possible

Only a **second source** for 0–113.78 s: the original ShadowPlay file before it
was overwritten, a re-encode/upload of the same session, a VOD, or another clip
covering that time. No algorithm can restore bytes that are not in the file.
Tools that "restore 100%" repair headers, `moov` atoms and indices — they do not
invent overwritten media.

### Verified deliverable

`nvidia_fix.py fix` already produces:
`recovery/out/Arc_Raiders corrupted.clean.mp4` — 185.73 s, 265.7 MB, 22,288
packets, stream-copied from keyframe 114.28 s, plus 114.29 s of recovered early
audio and a JSON report.

## Plan

- [x] Push the pending 1.1.0 work to `origin/main`.
- [x] Create `recovery/` workspace and move the input recording into it.
- [x] Build the forensics toolkit (9 scripts) and run the full evidence chain.
- [x] Decide the ceiling: **186.21 s / 62.1% of frames; 100% impossible.**
- [x] Produce and inspect a maximum-length recovery with the existing engine.
- [ ] Fix the verifier: `non monotonically increasing dts` is a muxer warning,
      not a decode error. It currently rejects a good keyframe at 114.03 s and
      labels a clean recovery `success_with_warnings`.
- [ ] Make the engine start at the true boundary (13,651 @ 113.790 s) instead of
      13,680, and/or pick the earliest keyframe whose decode is error-free.
- [ ] Add `--explain` (or `analyze` output) that runs the duplication check and
      reports "N s duplicated / N s destroyed" so the app tells the truth
      automatically instead of relying on a hand-written README.
- [ ] Surface that verdict in `desktop.py` and the README's forensic section.
- [ ] Update tests: fix the fixture expectations for co64, add a duplication
      regression test using a synthesized prefix/tail pair.
- [ ] Commit + push.

## Mission log

### 2026-10-30 — session 1

- Pushed `167c525 Release 1.1.0` to `origin/main` (CI, license, docs, fixtures).
- Moved the 439 MB input into `recovery/`; added `recovery/` to `.gitignore`.
- Environment: Python 3.9.13, no ffmpeg on PATH, no pytest, no numpy. Installed
  portable ffmpeg 9.0.2 into `recovery/tools/ff/` and wrote dependency-free
  parsers instead of adding packages.
- **Bug found and fixed in my own tooling:** `parse_stco` decided 32-bit vs
  64-bit by FullBox version. `co64` is also version 0, so every 8-byte offset
  was read as two 4-byte halves. That produced phantom overlaps ("35998 samples
  spanning 226 MB") and a false "212 MB orphan tail" theory. Always branch on
  box type. After the fix: perfect tiling, no orphans.
- Falsified H1 (index-only damage) and H2 (second copy in the file).
- Established H3 (in-place overwritten prefix) quantitatively via drift mapping.
- Ran the existing engine end-to-end: 185.73 s recovered, 762 "decode errors"
  reported — all of them the benign dts muxer warning, see Plan.
- Verdict for Yassine: 100% is not attainable from this file; the honest
  maximum is 186.21 s. Awaiting his decision on a donor copy / publishing the
  negative result.
