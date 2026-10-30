# Changelog

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
