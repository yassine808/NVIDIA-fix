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
- [x] Path-based web UI: paste a video path, outputs saved beside it as
      `<name>.clean.mp4`; tested end to end on the real recording.
- [x] Electron + TypeScript desktop front end under `desktop/`, tested through
      the real window on the corrupted recording.
- [x] Package the desktop app (installer/exe) and retire the legacy UIs.
- [x] Retire the legacy Python UIs; flatten the Electron app to the repo root.
- [x] Port the recovery engine from Python to TypeScript; delete `nvidia_fix.py`
      and `scripts/bridge.py`.
- [x] Bundle ffmpeg with the app: `scripts/fetch-ffmpeg.js`, `npm run
      fetch-ffmpeg`, staged by `npm run dist`, preferred over `PATH`.
- [x] README screenshots from the real window + a repo description that says
      what the app does.
- [x] Valorant 2026.04.05: ship the clean tail and the full-length rebuild
      generated from `video test/duplication_dense.json`.
- [ ] 100% of the *original* opening: impossible from every local source
      (Valorant confirms it: the head is a shifted copy of ~192-300 s).
- [x] Give the CI jobs plain names (no `1 /` prefixes).
- [x] Clear all 103 SonarCloud issues (forensics Python, renderer, smoke
      harness, TypeScript engine/main/cli).

## Environment rules

- Yassine games on this machine: any heavy local process (ffmpeg, scans) runs at
  **BelowNormal** priority, `-threads 2` max, and **no GPU/hwaccel** paths.

## Log

### 2026-10-31 — 1.2.1: the last 29 Sonar findings + the packaged exe

- Goal: close the 29 findings left after 1.2.0, then ship a fresh Windows
  build whose file name has no `-portable` suffix.
- Done: renderer uses `api.copyText` (new `shell:copy-text` IPC ->
  Electron `clipboard`) instead of deprecated `document.execCommand("copy")`,
  and six `api && api.x` guards became optional chains. `main.ts` lost the
  unused `existingFile()`; `shell:open-path` / `shell:show-in-folder` now
  resolve the target out of a `producedFiles` map filled from the engine
  result, so an arbitrary IPC path is refused. `String.raw` for Windows paths
  (`main.ts`, `tools.ts`, `smoke-ui.js`), `??` in `cli.ts`, `filter(Boolean)`
  in `tools.ts`, nested ternary extracted in `analyze.ts`, `concatEntry` uses
  `String.fromCharCode(92)` instead of an escaped backslash.
  `fetch-ffmpeg.js` runs absolute `powershell.exe` and `/usr/bin/unzip`.
  Python: `bitstream_map.score_intervals` split into `sample_score`, unused
  `ts`/`sample_times` removed from `byte_dup.py`, and the seven `S8707` sinks
  carry `# NOSONAR` with a comment (paths validated by
  `paths.readable_file()`; Sonar's taint tracker does not follow that
  cross-module sanitizer). Version bumped to 1.2.1 in `package.json` and
  `src/engine/types.ts`; `artifactName` is now `NVIDIA-Fix-${version}.exe`;
  README + CHANGELOG updated.
- Verified: `npm run build` clean, `npm test` 16/16, `--version` prints
  `nvidia-fix 1.2.1`, `python -m compileall` clean and all forensics modules
  import; `boundary_find.py` still reports 13,650/13,680 (62.1%);
  `npm run smoke` passed on `recovery/tmp-fixture.mp4`; `npm run dist`
  produced `release\NVIDIA-Fix-1.2.1.exe` (165,397,286 B); the packaged
  `release\win-unpacked\NVIDIA-Fix.exe` starts and loads the new renderer over
  CDP, and `app.asar` contains the 1.2.1 package, the clipboard bridge and the
  produced-files allowlist.
- Pushed to `main` as `0a9b582`; SonarCloud failed the gate with 5 issues: two
  `S7632` (text after `# NOSONAR` is invalid) leaving the `S8707` open in
  `coverage_report.py` and `mp4_probe.py`, plus `S7758` (`fromCharCode`).
  Fixed both in `374d0ff` (bare `# NOSONAR`, `String.fromCodePoint`).
- Verified after the rescan: SonarCloud analysis **success**, the project API
  reports **0 open issues**, and all four CI jobs plus SonarCloud are green on
  `374d0ff`. `release\NVIDIA-Fix-1.2.1.exe` (165,400,997 B) was rebuilt from
  this source.
- Next: nothing in flight.

### 2026-10-31 — SonarCloud cleanup resumed: verification + one real bug

- Goal: finish the 103-issue cleanup that was already committed as `e9945aa`
  (repo description, plain CI job names, Python/TypeScript/renderer/smoke
  fixes), and prove the refactors did not break the toolchain.
- Done: repo description checked with `gh repo edit --json` — no
  "Desktop app built with Electron." left. CI jobs already named "Quality and
  docs", "Engine tests", "Desktop app", "CLI recovery". Fixed a real defect the
  refactor introduced in `forensics/mp4_probe.py`: `write_report()` was called
  twice per run (one copy after `print_summary`), so every `--json` report was
  written twice.
- Verified: `npm run build` clean; `npm test` 16/16; `python -m compileall -q
  tests scripts forensics` OK; `python scripts/ci_e2e.py` passes (clean start
  4.000 s, 120 packets, 0 decode errors, input hash unchanged); `npm run smoke`
  on `recovery/tmp-fixture.mp4` reaches the result page through the split
  renderer (`index.html` + `renderer.js` + `styles.css`, CSP without
  `unsafe-inline`); `forensics/mp4_probe.py` on the real recording prints
  35,998 samples / 300.013 s / 298 audio gaps / 7,199,780 B of audio exactly as
  documented, and `boundary_find.py` still finds 13,650 last-damaged / 13,680
  first clean keyframe (62.1% clean).
- Next: push `e9945aa` plus this fix; nothing else in flight on the cleanup.

### 2026-10-31 — SonarCloud cleanup (103 issues) + plain CI job names

- Goal: clear every issue SonarCloud reports for `yassine808/NVIDIA-fix` (49 in
  `forensics/` + `scripts/make_icon.py`, 24 in TypeScript, 22 in
  `src/renderer/index.html` + `scripts/smoke-ui.js`), drop the "Desktop app
  built with Electron." line from the repo description, and give the CI jobs
  plain names instead of "1 / ...", "2 / ...".
- Done: repo description shortened with `gh repo edit`; CI job names renamed to
  "Quality and docs", "Engine tests", "Desktop app", "CLI recovery". Python:
  unused locals/params, real bug at `mp4_probe` report print (extra format
  argument, the crash seen earlier), empty block, cognitive-complexity splits.
  TypeScript: unused import, optional chaining, `replaceAll`/`String.raw`,
  parameter object for `fullLengthBlock`, re-exports, `startsWith`, `.at()`,
  `??`, `localeCompare` sort, nested template literal, command-injection sink.
  Renderer: CSP without `unsafe-inline` (CSS/JS moved out of `index.html`),
  labels on every input, `Number.isNaN`, de-nested ternaries, handled catches.
  Smoke harness: absolute `taskkill`, awaited IIFE, split poll loops.
- Verified: `python -m compileall -q tests scripts forensics`, `npm run build`,
  `npm test`, `npm run smoke`, `python scripts/ci_e2e.py`, and
  `python forensics/mp4_probe.py <video>` on the real recording.
- Next: nothing in flight.

### 2026-10-31 — ffmpeg bundled, README screenshots, repo description

- Goal: the app must not depend on the user's PATH for ffmpeg, the README must
  show what the app looks like, and the repo's public description must say what
  it does.
- Done: new `scripts/fetch-ffmpeg.js` downloads the newest gyan.dev essentials
  build into `recovery/tools/ff/ffmpeg-<ver>-essentials_build/bin/` (skips when
  present, `--force` refreshes, keeps only `ffmpeg.exe` + `ffprobe.exe`).
  `npm run fetch-ffmpeg` added; `npm run dist` now fetches first, and
  `scripts/stage-engine.js` stages only the newest build. `src/engine/tools.ts`
  now prefers the bundled binaries over `PATH` and the missing-tool error points
  at the fetch script. Renderer/report caveat no longer leaks the literal
  `clean_start` placeholder (`caveatFor()` in `types.ts`). README: new hero
  screenshot + result screenshot (`docs/screenshots/home.png`, `result.png`,
  captured from the real window through `npm run smoke -- --shot`), an "ffmpeg
  ships with the app" section, and an updated packaging note. GitHub repo
  description + topics set with `gh repo edit`. The description no longer says
  "+ CLI" (there is a CLI only from a source checkout, via `npm run engine --`,
  not a shipped command); the README section is now titled "CLI (from a source
  checkout)" and says so.
- Verified: `node scripts/fetch-ffmpeg.js` reports the existing build, `npm run
  build` clean, the engine resolves `recovery\tools\ff\...\ffmpeg.exe`, and the
  smoke run passed on the fixture while writing both screenshots.
- Next: rebuild the Valorant deliverables with the duplication map now present.

### 2026-10-31 — Valorant 2026.04.05 DVR: the opening is a shifted copy of the tail

- Goal: the user's new recording `video test/Valorant 2026.04.05 -
  23.27.11.02.DVR.mp4` must be recovered "100%"; he can see the first frames.
- Done: `video test/` is already ignored and committed (`e3ee443`); the copy is
  byte-identical to `D:\Videos\VALORANT\Valorant 2026.04.05 - 23.27.11.02.DVR.mp4`
  (SHA-256 `32C90D62…`, 665,137,344 B), so there is no second local source.
  Structure is intact: `ftyp`, one `mdat` (664,555,945 B), `moov` at the end;
  video track 36,000 samples / 300.0 s / 1200 sync frames, audio 14,062 samples,
  0 overlapping or out-of-mdat samples.
  Payload test: every one of the first 13,200 video samples has its 4-byte AVCC
  length exactly equal to `stsz`, but only 2,472 (18.7%) start with a legal NAL
  header — the same rate random bytes would give. So framing is intact and the
  bytes inside the samples are shifted.
  Duplication scan (`recovery/dup_scan.py`, 512-byte blocks on a 2 MiB grid):
  **105 of 118 blocks from the first 232 MB reappear at +432,170,000 B
  (range 432,130,168-432,233,574, i.e. a drift of 103,406 B)**. In time that
  destination is ~194.9-195.0 s. The file is therefore `[A][B][A]` with
  A = 232 MB: file 0-105 s is a byte-shifted copy of file ~195-300 s.
  Visual test: frames at 1-8 s decode to smeared/rotated stills of the *same*
  gameplay that sits at ~195 s (they show the party UI and ability timers), then
  go black; ffmpeg logs "Frame num change", "missing picture in access unit".
- Verified: hashes, `forensics/mp4_probe.py` output (`recovery/valorant-probe.json`),
  `recovery/head_check.py` (length/NAL counts), `recovery/dup_scan.py` (105/118
  hits), thumbnails in `recovery/shots/valorant/`.
- Next: build the deliverable with the engine (`fix --full-length`) and verify a
  full decode; then state the honest verdict: the original 0-110.25 s gameplay
  is destroyed, the head can only be refilled with the duplicated tail.

### 2026-10-31 — Valorant 2026.04.05 DVR: deliverables built and verified

- Goal: hand over a recovered file instead of a diagnosis.
- Done: `forensics/duplication_dense.py` now takes the video path and an end
  bound and writes `duplication_dense.json` beside that video (it used to be
  hardcoded to the Arc Raiders file). Dense map for Valorant: drift line
  `src = 432137759 + 0.0004038*off`, 872/1000 probe blocks matched, container
  0.09 s -> content 192.26 s and container 103.53 s -> content 299.91 s, so
  101.79 s of the 110.25 s damaged opening is provably a copy and 8.33 s is
  garbage. Ran `fix --full-length`; outputs live beside the input in `video
  test/`: `.clean.mp4` (189.7487 s, 22,770 packets, 0 decode errors),
  `.clean.audio.m4a` (110.27 s), `.clean.full-length.mp4` (297.411 s, 35,689
  frames, original audio 297.40 s, 0 decode errors), `.clean.report.json`.
- Verified: full decode of every output returned 0 decoder errors (only benign
  non-monotonic-DTS muxer warnings). Frames pulled from the rebuild at 1, 30,
  60, 100, 109, 111, 150 and 290 s are clean 1920x1080 Valorant gameplay — the
  rebuilt opening is real footage, not smeared garbage, and the join at 107.65 s
  is seamless. `npm test` 16/16.
- Honest statement: the rebuild is 297.41 s, not 300 s, because the recorder's
  copy window ends at content 299.91 s; only 107.65 s of duplicated footage
  exists to refill a 110.25 s hole (`shortfall_seconds: 2.599533` in the
  report). The original 0-110.25 s gameplay does not exist anywhere on this
  machine.
- Next: nothing in flight. If the user wants an exact 300 s file, the only
  honest option is to fill the last 2.6 s with real tail footage (content
  189.75-192.26 s), which would be a product decision, not a recovery.

### 2026-10-31 — recovery engine ported to TypeScript; Python app removed

- Goal: remove the Python version of the app entirely and run the whole product
  from the TypeScript codebase.
- Done: new `src/engine/` (types, tools, probe, analyze, duplication, verify,
  rebuild, process, cli, bridge) reproduces the Python engine's algorithm, JSON
  report and CLI (`analyze`, `fix`, `explain`, `--version`). The Electron main
  process now spawns `dist/engine/bridge.js` with `ELECTRON_RUN_AS_NODE` instead
  of `python scripts/bridge.py`. Deleted `nvidia_fix.py`, `scripts/bridge.py` and
  the Python test modules; added `tests/engine.test.mjs` (16 Node tests) and
  pointed `scripts/ci_e2e.py` at the Node CLI. `scripts/stage-engine.js` no
  longer stages Python; packaging copies `dist/engine` beside the app.
- Verified: `npm test` 16/16; `python scripts/ci_e2e.py` passes against the real
  CLI (clean start 4.000 s, 120 packets, 0 decode errors, input hash unchanged);
  `npm run smoke` drove the real window through the TS engine and reached the
  result page; a fixture recovery produced the same numbers as the Python
  engine before deletion (clean start 4.0 s, 120 packets, identical first-packet
  SHA-256).
- Next: keep `forensics/` and the fixture helpers as dev-only Python tooling, or
  port them too if they need to leave the repo.

### 2026-10-31 — Electron app moved to the repo root, Python UIs retired

- Goal: one app at the top level of the repository instead of a `desktop/`
  subfolder, with the dead Python front ends and their leftovers gone.
- Done: moved `desktop/{package.json,package-lock.json,tsconfig.json,build,src,
  scripts}` to the repo root and merged the two `scripts/` folders. Deleted
  `desktop/.gitignore`, `desktop/README.md` and every empty leftover folder.
  Updated the path assumptions (`ENGINE_ROOT` is now `app.getAppPath()`,
  `stage-engine.js` uses the repo root), rewrote `.gitignore` for the root
  layout, removed the Flask/Tk/PyInstaller references from `README.md` and
  replaced the CI workflow with four jobs that match the actual repo.
- Verified: `npm run build` clean from the root; the app launches from the root
  checkout and the bridge still finds `nvidia_fix.py`.
- Next: port the recovery engine to TypeScript, then remove the Python engine.

### 2026-10-31 — desktop uses Yassine's supplied frontend

- Goal: replace the custom renderer with the exact HTML/CSS/JS design Yassine
  supplied (NVIDIA green, drop zone, steps, tick strip, result page).
- Done: `desktop/src/renderer/index.html` is now that single file with inline
  CSS/JS, adapted only at the integration points: `window.nvidiaFix` replaces
  the Flask POST/`pywebview` calls, Browse uses the Electron dialog, dropped
  files resolve to real paths, and the result section is filled from the engine
  JSON instead of Jinja. Removed `renderer.ts`, `styles.css` and
  `tsconfig.renderer.json`; `npm run build` is one `tsc` pass plus `copy-assets`.
  README architecture updated.
- Verified: `npm run build` clean. `npm run smoke` passed on a synthetic
  corrupted clip (lost 0.5 s / recovered 11.5 s, 6 damaged samples, 0 decode
  errors) and on `recovery/Arc_Raiders corrupted.mp4` (lost 1:54.03, recovered
  3:05.98, 11,000 damaged samples, 0 decode errors). Created `clean-2` outputs
  were deleted afterward; no source files touched.
- Next: review the diff, then decide on packaging and retiring the legacy UIs.

### 2026-10-31 — Electron + TypeScript desktop app (branch `desktop-typescript`)

- Goal: switch the app from the Flask web UI to a TypeScript desktop app.
- Done: new `desktop/` app (Electron 45 + TypeScript 5.9). Main process spawns
  `scripts/bridge.py`, which streams `nvidia_fix.process` progress as JSON lines.
  Sandboxed renderer with a `contextBridge` API; Browse dialog, drag-and-drop,
  live log, cancel, and Open / Show in folder / Copy for each output. Outputs
  remain `<name>.clean.mp4` beside the input. Legacy Tkinter/Flask UIs kept.
- Verified: `npm run typecheck` + `npm run build` clean. `npm run smoke` drives
  the real Electron window over CDP: synthetic clip passed; the real recording
  passed with clean start 114.031811 s, 185.981 s / 22,318 packets, 0 decode
  errors. Temporary duplicate outputs removed.
- Next: review the branch, then decide whether to delete the legacy UIs and
  package the Electron app.


### 2026-10-31 — path-based web UI, tested on the real recording

- Goal: make the Flask app usable as a local tool: one input (the video path),
  output written beside it as `<name>.clean.mp4`, and an HTML front end that is
  easy to modify later.
- Done: `app.py` is now path-based (`video_path` form field / `{"path": ...}` on
  `/api/fix`) and calls `nvidia_fix.process(source, out_dir=None)` so outputs
  land next to the input. The whole front end is one file,
  `templates/index.html` (layout, CSS, path form, live output-name preview,
  result view switched by `{% if result %}`). Removed the upload/job/download
  flow.
  `nvidia_fix._resolve_tool` now falls back to the bundled
  `recovery/tools/ff/*/bin` ffmpeg/ffprobe, so no PATH setup is needed. Tests
  (`tests/test_app.py`, `tests/helpers.py`) updated for the path flow. Also
  fixed `desktop.py` reading `full_length_var` from the worker thread (Tk threw
  "main thread is not in main loop"); the value is now captured before the
  thread starts.
- Verified: Flask 3.1.3 installed here. `python tests/test_app.py` 11/11,
  `python tests/test_parsers.py` 9/9. Server smoke test on port 5123: `/healthz`
  ok, `/` 200. Real run through `/api/fix` on `recovery/Arc_Raiders corrupted.mp4`:
  `status: success`, clean start 114.031811 s, 185.981 s / 22,318 packets,
  **0 decode errors** in 24.8 s; wrote
  `recovery/Arc_Raiders corrupted.clean.mp4` (266,260,199 B),
  `.clean.audio.m4a` and `.clean.report.json`.
- Next: nothing in flight. The 100% goal is still closed to a donor source.


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
