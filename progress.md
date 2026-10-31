# Progress — NVIDIA-Fix

## Plan

- [x] Publish the 1.1.1 false-verdict fixes (`2863c0d`).
- [x] `explain`: split the damaged prefix into copied-later vs destroyed seconds (`71cfb0c`).
- [x] Surface that verdict in the recovery report, `desktop.py` and the README (`f000bc5`).
- [x] co64/stco fixture expectations (`1f83b9c`).
- [ ] Donor hunt: search every local source for a copy of 0–113.782 s.
      C: shadow copy (10/30 18:19) ruled out; whole-disk media scan was still
      running when this entry was written (BelowNormal, pid 16540).
- [ ] 100% mission: only a second source for 0–113.782 s can close it.

## Environment rules

- Yassine games on this machine: any heavy local process (ffmpeg, scans) runs at
  **BelowNormal** priority, `-threads 2` max, and **no GPU/hwaccel** paths.

## Log

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
