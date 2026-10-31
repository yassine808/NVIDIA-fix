# Changelog

## 1.2.1 - 2026-10-31

Closing the remaining SonarCloud findings, plus a clearer installer name.

### Changed

- The Windows build is now `NVIDIA-Fix-1.2.1.exe` (no `-portable` suffix).
- The renderer copies saved paths through the Electron clipboard bridge instead
  of the deprecated `document.execCommand("copy")`.
- `Open` / `Show in folder` resolve the target from the outputs this session
  produced; an arbitrary IPC path is refused.
- `fetch-ffmpeg.js` runs PowerShell and `unzip` from fixed OS paths, never from
  `PATH`.

### Fixed

- SonarCloud cleanups: optional chaining in the renderer, `String.raw` for
  Windows paths, `??` and boolean shorthand in the engine, a split
  `score_intervals` in `bitstream_map.py`, an unused variable in `byte_dup.py`,
  and path-validation suppressions where the CLI intentionally takes an
  operator-named file.

## 1.1.1 — 2026-10-31

Correctness pass on verification. No change to the recovery strategy; the
maximum recoverable length from this file is unchanged.

### Fixed

- The verifier treated ffmpeg's null-muxer `non monotonically increasing dts`
  warnings as decode errors. On 120 fps B-frame recordings that rejected the
  earliest clean keyframe and labelled a clean cut `success_with_warnings`.
  Output is now classified: decoder/corruption messages block the cut, muxer
  timestamp warnings are reported as `recovery.muxer_warnings`, and anything
  unrecognised sets `success_with_warnings` instead of being swallowed.
- `stss` sync samples were read as 0-based; ISO BMFF stores them 1-based. This
  shifted the reported boundary one sample early and made a 108-byte non-IDR
  slice look like a keyframe. `parse_stss` now converts and documents it.
- `sample_map.Reader` re-read its 16 MiB cache window for every sample when
  scanning backwards (~350 GB of I/O); it now anchors the window on a boundary.
  `boundary_find.py` runs in ~1 s instead of hours.

### Changed

- Recovered tail now starts at 114.031811 s (packet 13,680): 22,318 packets,
  185.981 s, 0 decoder errors.
- Added `tests/test_parsers.py` regressions for the `stss` and stderr
  classification bugs.

## 1.1.0 — 2026-10-19

Maintenance and release-quality pass. The recovery algorithm and its
limitations are unchanged.

### Added

- MIT license.
- GitHub Actions CI with five independent checks: quality/docs, unit tests,
  desktop UI, CLI end-to-end recovery, and a PyInstaller package smoke test.
- Reproducible CI fixtures in `scripts/`.
- Desktop screenshots in `docs/screenshots/` and a rewritten README.

### Changed

- Version bumped to `1.1.0`.
- `--smoke-test` now hides the window, so it can run on headless Windows CI.
- Rebuilt `NVIDIA-Fix.exe` for the new release.

## 1.0.0 — 2026-10-18

- Initial release: stream-copy recovery engine, CLI, optional Flask UI, native
  Tkinter desktop app, report output, tests, and Windows executable.
