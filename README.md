# NVIDIA-Fix

**Fix a corrupted NVIDIA ShadowPlay recording. Get a clean, playable copy — no re-encoding, nothing uploaded.**

[![Download](https://img.shields.io/badge/Download-NVIDIA--Fix.exe-f0b44a?style=for-the-badge&logo=windows&logoColor=1a1204)](https://github.com/yassine808/NVIDIA-fix/releases/latest)

![NVIDIA-Fix home screen](docs/screenshots/home.png)

## What it does

Pick a broken ShadowPlay clip. Press **Recover video**. You get:

- `clip.clean.mp4` — the good part, copied (not re-encoded)
- `clip.clean.audio.m4a` — the sound from the broken part
- `clip.clean.report.json` — proof of what happened

![NVIDIA-Fix result screen](docs/screenshots/result.png)

Your original is never changed.

## How to use it

1. Download `NVIDIA-Fix.exe` from [Releases](https://github.com/yassine808/NVIDIA-fix/releases/latest) and run it.
2. Drop your recording on the window (or browse / paste the path).
3. Click **Recover video** and wait.

The app shows how much was lost and how much was recovered, then lists the saved files.

## The honest part

If ShadowPlay overwrote the start of the clip with a copy of later footage, that
start is gone. No tool can bring it back. This app recovers everything that still
exists and tells you exactly what was destroyed. It never fakes the missing part.

## Requirements

Windows 10 or 11. ffmpeg is included — nothing to install.

## Build from source

```powershell
npm install
npm start          # run the app
npm run dist       # build release\NVIDIA-Fix-<version>.exe
npm test           # engine tests
```

The app is Electron + TypeScript. The recovery engine lives in `src/engine/`.
`npm run dist` needs internet once, to download ffmpeg.

## License

[MIT](LICENSE) © 2026 yassine808
