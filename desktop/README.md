# NVIDIA-Fix Desktop (TypeScript)

Electron + TypeScript front end for the NVIDIA-Fix recovery engine. It replaces
the Flask web UI: no browser tab, no upload, just a native window that asks for
one path and writes the recovered file beside the original.

## Requirements

- Node.js 18+ (built with Node 24)
- Python 3.9+ with the repository's `nvidia_fix.py`
- ffmpeg/ffprobe: found on `PATH`, or the bundled
  `recovery/tools/ff/*/bin` build is used automatically

## Run

```powershell
cd desktop
npm install
npm run build
npm start
```

`npm start` compiles and opens the window. `npm run typecheck` checks the
main/preload TypeScript without emitting.

## What it does

1. Pick a video with **Browse…**, drag it onto the window, or paste a path.
2. Press **Recover video**. The app runs the existing Python engine locally.
3. The recovered files are written next to the input:
   - `<name>.clean.mp4`
   - `<name>.clean.audio.m4a`
   - `<name>.clean.report.json`

Existing outputs are never overwritten; the engine adds `-2`, `-3`, … instead.
The window shows live engine progress and the verification result, and each
saved file has a copyable path.

## Architecture

| Path | Role |
| --- | --- |
| `src/main/main.ts` | Electron main process: window, IPC, Python child process, file dialogs |
| `src/main/preload.ts` | Narrow `contextBridge` API exposed to the renderer |
| `src/renderer/index.html` | The supplied single-page UI: inline CSS/JS, drag-and-drop, steps, tick strip, result view |
| `src/shared/types.ts` | Types shared by main and preload |
| `scripts/bridge.py` | JSON-lines bridge: runs `nvidia_fix.process`, streams progress |
| `scripts/smoke-ui.js` | End-to-end UI test over the Chrome DevTools Protocol |

The renderer has no Node access (`contextIsolation: true`, `sandbox: true`,
`nodeIntegration: false`). All privileged work goes through IPC.

## Smoke test

Drives the real Electron window against a real recording:

```powershell
npm run smoke -- --path "..\recovery\Arc_Raiders corrupted.mp4"
```

It fills the path field, clicks **Recover video**, waits for the result page,
prints it, and exits non-zero on any UI or engine error. Use a small clip while
iterating; the real recording takes ~25 s with full verification.
