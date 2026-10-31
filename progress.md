# Progress — NVIDIA-Fix

## Plan

- [x] Publish the 1.1.1 false-verdict fixes (`2863c0d`).
- [x] `explain`: split the damaged prefix into copied-later vs destroyed seconds (`71cfb0c`).
- [ ] Donor hunt: search every local source for a copy of 0–113.782 s.
- [ ] Surface the `explain` verdict in `desktop.py` and the README forensics section.
- [ ] co64 fixture expectations + a synthesized prefix/tail duplication regression test.
- [ ] 100% mission: only a second source for 0–113.782 s can close it.

## Environment rules

- Yassine games on this machine: any heavy local process (ffmpeg, scans) runs at
  **BelowNormal** priority, `-threads 2` max, and **no GPU/hwaccel** paths.

## Log

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
- Next: finish the donor hunt (interrupted), then surface the verdict in the app.

### 2026-10-31 — Session start

- Read `AGENTS.md`. Repo had one unpushed commit (`21fb2a2`) and uncommitted
  session-2 work (verifier/boundary/reader fixes + `tests/test_parsers.py`).
