# Progress — NVIDIA-Fix

## Plan

- [x] Publish the 1.1.1 false-verdict fixes (`2863c0d`).
- [x] `explain`: split the damaged prefix into copied-later vs destroyed seconds (`71cfb0c`).
- [x] Surface that verdict in the recovery report, `desktop.py` and the README (`f000bc5`).
- [x] co64/stco fixture expectations (`1f83b9c`).
- [x] Donor hunt: 9,220 media files >20 MB across C:, D:, E:, F: plus the one C:
      shadow copy. **No donor.** The same-session `.DVR.BACKUP.mp4` is
      byte-identical to the corrupted file (SHA-256 `18893EB7…`); the 884.5 MB
      `.DVR.fixed.mp4` is green/blank for its first ~114 s and does not match
      this recording at any timestamp (PSNR 12–19 dB against every candidate).
- [x] Full-length deliverable built and verified (see the log entry below).
- [ ] 100% of the *original* opening: impossible from every local source.

## Environment rules

- Yassine games on this machine: any heavy local process (ffmpeg, scans) runs at
  **BelowNormal** priority, `-threads 2` max, and **no GPU/hwaccel** paths.

## Log

### 2026-10-31 — full-length build + donor hunt result

- Goal: give Yassine a complete-length clip, and settle whether a second source
  exists on this machine.
- Done — full-length build: `recovery/full-length/Arc_Raiders full-length rebuilt.mp4`
  (406.0 MB) with `REPORT.json` beside it. Video = 114.03 s of the footage the
  recorder wrote over the head (clean-tail 68.508–182.538 s = original content
  182.54–296.57 s) concatenated with the untouched tail from 114.031811 s; audio
  = the source's own full track. Stream copies only, no re-encode.
- Verified: video 300.013011 s / 36,002 frames, audio 300.010250 s / 14,062
  frames (the original count); full decode at BelowNormal produced **one** line,
  the benign `non monotonically increasing dts` muxer warning — 0 H.264 errors,
  0 AAC errors. Frames at 5/60/120/200/290 s are real gameplay (PNG 60–95 KB),
  and the early audio decodes clean (143 stderr lines, all h264, 0 aac).
- Done — donor hunt: 9,220 media files >20 MB across all four drives. Only
  same-session candidate is `D:\Videos\Arc Raiders\…19.06.32.02.DVR.fixed.mp4`
  (884.5 MB, 300.19 s, 36,023 frames): green/blank frames for the first ~114 s
  (Y≈15, U/V≈130) and PSNR 12–19 dB against this recording at every timestamp
  tried, i.e. a failed repair, not a donor. `.DVR.BACKUP.mp4` hashes identical to
  `recovery/Arc_Raiders corrupted.mp4`.
- Honest statement: 0–113.782 s of the original video does not exist in any local
  file. The full-length build is real footage and 100% original audio, but its
  first 114 s is the duplicate content, not the original opening. It must never
  be published as a recovered original.
- Next: nothing in flight. If a donor ever appears, the acceptance test is the
  documented one (joins at frame 13,680, frame-exact, full decode 0 errors).

### 2026-10-31 — verdict in the app, co64 fixtures, donor hunt

- Goal: the app must state why 37.9% is missing; close the co64 test gap; look
  for a second source.
- Done: `process()` now writes a `duplication` block into every report (seconds
  copied later, seconds destroyed, block counts, container→content copy window);
  a missing map becomes `{"unavailable": …}` and never blocks a recovery.
  `desktop.py` states the same numbers in the result card. README gained
  "How much is duplicated, how much is gone" plus the `explain` example.
  `tests/test_parsers.py` gained three co64/stco fixtures. Ground rule added:
  heavy runs go BelowNormal, ≤2 threads, no GPU (Yassine games on this box).
- Verified: real `fix --no-full-decode` run → `status: success`, 0 decode errors,
  `duplication = {damaged 113.781922, duplicated 105.73, destroyed 8.051922,
  matched 614/760, window 0.12→182.54 … 107.54→299.79}`. Tests: `test_explain` 7/7,
  `test_parsers` 9/9. Pushed `71cfb0c`, `f000bc5`, `1f83b9c`.
- Donor hunt part 1: one C: shadow copy exists (10/30/2026 18:19). Mounted it
  read-only via a `GLOBALROOT` symlink; no `Arc_Raiders` file and no 300 s
  recording anywhere in it. Two unrelated Recycle Bin clips found: 112.1 MB of
  zeros (unreadable, no `ftyp`) and 107.5 MB with a valid `ftyp/free/mdat` but
  **no `moov`** — an interrupted capture, not this session, not 439 MB.
- Next: read the whole-disk scan result, then either a donor is found (acceptance
  test: donor 0–113.782 s joins frame 13,680 with frame-exact continuity and a
  full decode with 0 decoder errors) or the 100% goal is closed in writing.

### 2026-10-31 — explain verdict + started the donor hunt

- Goal: let the app say *why* 37.9% is missing without quoting a README
  paragraph, then look for a second source of 0–113.782 s.
- Done: `nvidia_fix.py explain` reads the duplication map from
  `forensics/duplication_dense.py`, clips block spans at the measured damaged
  boundary, and reports duplicated vs destroyed seconds; refuses to re-derive
  the split from a coarser scan. `tests/test_explain.py` pins the arithmetic and
  the published numbers. Committed `71cfb0c`, pushed to `origin/main`. Deleted
  404 MB of regenerable artifacts (`build/`, `dist/`, `recovery/out/`, segment
  logs, `thumbs.raw`).
- Verified: `python tests/test_explain.py` 5/5, `tests/test_parsers.py` 6/6.
  `explain` on the real recording: damaged 113.782 s, copied later 105.730 s
  (80.8% of scanned blocks), destroyed 8.052 s, recoverable 186.231 s of
  300.013 s (62.1%).
- Next: finish the donor hunt, then surface the verdict in the app.

### 2026-10-31 — Session start

- Read `AGENTS.md`. Repo had one unpushed commit (`21fb2a2`) and uncommitted
  session-2 work (verifier/boundary/reader fixes + `tests/test_parsers.py`).
