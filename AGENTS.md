# AGENTS.md — NVIDIA-Fix

Operating notes for any agent working in this repository. Read this first, then
update **Mission log** before you stop working.

## Ground rules

- Truth over optimism. Every recovery claim must be backed by a reproducible
  measurement (byte ranges, hashes, frame counts). "It plays" is not "100%".
- If a byte range of the original media is provably gone, say so and quantify
  it. Never present a reconstruction as the original footage.
- **Throttle heavy runs.** Yassine games on this machine, so any local process
  that can saturate the box (ffmpeg, drive scans, full decodes) runs at
  `BelowNormal` priority and no more than 2 threads, and never takes a GPU or
  hwaccel path. There is no hardware decode in this toolchain by design.
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

## Mission goal: 100% of the recording (ACTIVE)

**The goal is 100% recovery of `recovery/Arc_Raiders corrupted.mp4`: all 35,998
frames / 300.013 s of video, not a 62% tail.**

Yassine reopened this on 2026-10-31. The earlier entry closed the project at the
in-file ceiling; that ceiling is a measurement of *this file*, not of the goal.
The goal stays open until either (a) all 300 s exist as playable, verified video,
or (b) every plausible second source has been searched and ruled out in writing.

### What this file can and cannot give

Measured ceiling from this file alone: **62.1% (22,347 frames / 186.21 s) is
intact; the other 37.9% (113.78 s) was overwritten in place and is not present
anywhere in these 439,194,252 bytes.** So 100% cannot come from re-parsing this
file. It can only come from a **second source** for 0–113.782 s:

1. The original ShadowPlay file from before the overwrite (check the ShadowPlay
   folder, temp folder, and any backup/OneDrive/Recycle Bin copy).
2. A re-encode or upload of the same session (YouTube/Twitch VOD, Discord,
   WhatsApp, Google Photos, phone export).
3. Another clip from the same play session that covers 0–114 s.

Until a source is supplied, the honest deliverable is the recovered tail plus
early audio. **Never present a reconstruction as the original footage** (line 8).
If a second source arrives, the acceptance test is: the donor's 0–113.782 s
joins the recovered tail at frame 13,680 with frame-exact continuity and a full
decode reporting zero decoder errors.

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

Exact boundary (`boundary_find.py`): last damaged sample **13,650 @ 113.782 s**;
first AVCC-valid sample **13,651 @ 113.790 s**, which is *not* decodable video (it
is a 108-byte non-IDR slice). The first clean **keyframe** is **13,680 @
114.032 s** — the earliest point a stream copy can start. `stss` entries are
1-based in ISO BMFF; reading them as 0-based is what once put the boundary at
13,651 (fixed in `parse_stss`).

### What would make 100% possible

Only a **second source** for 0–113.78 s: the original ShadowPlay file before it
was overwritten, a re-encode/upload of the same session, a VOD, or another clip
covering that time. No algorithm can restore bytes that are not in the file.
Tools that "restore 100%" repair headers, `moov` atoms and indices — they do not
invent overwritten media.

### Verified deliverable

`nvidia_fix.py fix` produces
`recovery/out_v2/Arc_Raiders corrupted.clean.mp4` — **185.981 s, 266,260,199 B,
22,318 packets**, stream-copied from keyframe 13,680 @ 114.031811 s, plus 114.03 s
of recovered early audio and a JSON report. Verified 2026-10-31: `status:
success`, first-packet SHA matches the source sample, **0 decoder errors**,
1,455 null-muxer dts warnings (timestamp noise from the verification command,
not file damage), no unclassified output, no retry attempts needed.

## Plan

- [x] Push the pending 1.1.0 work to `origin/main`.
- [x] Create `recovery/` workspace and move the input recording into it.
- [x] Build the forensics toolkit (9 scripts) and run the full evidence chain.
- [x] Decide the in-file ceiling: **186.21 s / 62.1% of frames.** The 100% goal
      stays open and can only be met with a second source (see above).
- [x] Produce and inspect a maximum-length recovery with the existing engine.
- [x] Fix the verifier: classify ffmpeg stderr instead of treating every line as
      a decode error. `non monotonically increasing dts` is now recorded as
      `recovery.muxer_warnings` and no longer rejects a clean cut; decoder and
      corruption messages still block, and unknown output sets
      `success_with_warnings` instead of being swallowed.
- [x] Start at the earliest error-free keyframe: **13,680 @ 114.031811 s**.
      The old "13,651 @ 113.790 s" target was a 1-based/0-based `stss` mix-up;
      sample 13,651 is a 108-byte non-IDR slice, not video you can start on.
- [ ] Add `--explain` (or `analyze` output) that runs the duplication check and
      reports "N s duplicated / N s destroyed" so the app tells the truth
      automatically instead of relying on a hand-written README. The dense map
      already exists at `recovery/duplication_dense.json`; the work is wiring,
      not new measurement.
- [ ] Surface that verdict in `desktop.py` and the README's forensic section.
- [x] Regression tests for the two bugs above (`tests/test_parsers.py`, 6 tests,
      no ffmpeg required).
- [ ] Still open: co64 fixture expectations and a duplication regression test
      built from a synthesized prefix/tail pair.
- [x] Commit + push (1.1.1, `2863c0d`).

## Mission log

### 2026-10-31 — session 3: the app reports duplicated vs destroyed

- `explain` verdict is now part of `process()`'s report: every recovery writes
  `duplication` (seconds copied later, seconds destroyed, block counts, the
  container→content copy window) when the map sits next to the input. A missing
  or unreadable map becomes `{"unavailable": …}`, never a silent omission, and
  never blocks the recovery itself.
- `desktop.py` result card now says what the missing prefix *is*: "N s of it is
  a copy of later footage and M s exists nowhere in this file", falling back to
  the old wording when no map is present.
- README gains a "How much is duplicated, how much is gone" block plus the
  `explain` CLI example. New rule in Ground rules: heavy runs go BelowNormal,
  ≤2 threads, no GPU (Yassine games on this box).
- Verified: real `fix --no-full-decode` run produced
  `status: success`, 0 decode errors and
  `duplication = {damaged 113.781922, duplicated 105.73, destroyed 8.051922,
  matched 614/760}`; `tests/test_explain.py` 7/7, `tests/test_parsers.py` 6/6;
  `desktop.py` imports clean. Temp output deleted afterwards.
- Still open: the donor hunt (running at BelowNormal as this was written — see
  `progress.md` for its result), the co64/duplication regression tests, and the
  100% goal.

### 2026-10-31 — session 2 close-out: the fixes are published

- Committed the verifier / `parse_stss` / `Reader` fixes as `2863c0d`
  ("Fix three false-verdict bugs in the recovery engine (1.1.1)") and pushed
  `main` (`167c525..2863c0d`), which also carried the unpushed `21fb2a2`
  forensics-toolkit commit.
- Verified before committing: `python tests/test_parsers.py` → 6 tests, OK.
  The 1.1.1 version has a single source (`nvidia_fix.VERSION`); `desktop.py`
  reads it, so nothing else needed bumping.
- The real-file recovery in `recovery/out_v2/` was **not** re-run this session.
  Its numbers stand from session 2: 185.981 s, 22,318 packets, 0 decoder errors.
- Next: `--explain` duplication verdict (then desktop.py + README surfacing),
  the co64/duplication regression tests, and a donor source for 0–113.782 s.

### 2026-10-31 — session 2 (goal reopened to 100%)

- Yassine reopened the mission: the goal is 100% of the 300 s, not the 62% tail.
  The in-file ceiling (186.21 s intact / 113.78 s overwritten) is recorded as a
  measurement of *this file*, and the only route to 100% is a second source.
- **Verifier bug, fixed.** `_decode_errors` counted every ffmpeg stderr line as a
  decode error. Measured: a full decode of the 114.03 s cut emits 2,902 lines,
  all of them `[null @ …] … non monotonically increasing dts to muxer`, and
  **zero** decoder messages. The tool rejected keyframe 13,680 and then reported
  a clean recovery as `success_with_warnings`. stderr is now classified
  (`_classify_stderr` / `DecodeCheck`): decoder + corruption markers block,
  muxer timestamp warnings are counted and ignored, unknown output sets a
  warning status instead of disappearing.
- **Boundary bug, fixed.** `parse_stss` returned `stss` entries raw, but ISO BMFF
  numbers sync samples from 1. My own note "first clean sample 13,651 is a
  keyframe" was this bug: sample 13,651 is a 108-byte non-IDR slice. The first
  clean keyframe is **13,680 @ 114.031811 s**, which is what `README.md` already
  said and what the engine now uses.
- **I/O bug, fixed.** `sample_map.Reader` anchored its 16 MiB window on the
  requested offset, so a backwards scan missed the cache every time:
  22k samples × 16 MiB ≈ 350 GB. Anchored on a window boundary instead;
  `boundary_find.py` went from hours to **1.2 s**.
- **Fresh recovery:** `recovery/out_v2/Arc_Raiders corrupted.clean.mp4` —
  185.981 s, 266,260,199 B, 22,318 packets, clean start 114.031811 s,
  `status: success`, 0 decoder errors, 1,455 muxer warnings, 0 retries,
  first-packet SHA == source sample SHA.
- Tests: new `tests/test_parsers.py` (6 fast regressions). Real-file test passes
  against the new engine (71.8 s). `tests/test_app.py` still cannot run locally:
  no Flask, no pytest in this environment.
- Still open: `--explain` duplication verdict, surfacing it in `desktop.py` and
  the README, the co64 fixture + duplication regression test, and finding a
  donor source for 0–113.782 s (the only path to 100%).

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
