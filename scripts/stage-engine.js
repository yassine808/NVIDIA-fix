// Stages what the packaged app needs beside the Electron code:
//
//   .stage/engine/nvidia_fix.py            the recovery engine
//   .stage/engine/scripts/bridge.py        the JSON-lines bridge
//   .stage/engine/recovery/tools/ff/...    portable ffmpeg (if downloaded)
//   .stage/icon.png                        window/taskbar icon
//
// electron-builder copies `.stage` into the app's resources folder, so the
// packaged layout is resources/engine and resources/icon.png. The ffmpeg build
// lives under recovery/ (git-ignored), so a machine without it - CI, a fresh
// clone - still packages; that build then needs ffmpeg on PATH.
const fs = require("node:fs");
const path = require("node:path");

const here = __dirname;
const root = path.resolve(here, "..");
const repo = root;
const stage = path.join(root, ".stage");

fs.rmSync(stage, { recursive: true, force: true });
fs.mkdirSync(path.join(stage, "engine", "scripts"), { recursive: true });

fs.copyFileSync(path.join(repo, "nvidia_fix.py"), path.join(stage, "engine", "nvidia_fix.py"));
fs.copyFileSync(path.join(here, "bridge.py"), path.join(stage, "engine", "scripts", "bridge.py"));
fs.copyFileSync(path.join(root, "build", "icon.png"), path.join(stage, "icon.png"));

// Portable ffmpeg: keep the <build>/bin/<tool>.exe shape nvidia_fix.py globs for.
const ffRoot = path.join(repo, "recovery", "tools", "ff");
let bundled = 0;
if (fs.existsSync(ffRoot)) {
  for (const build of fs.readdirSync(ffRoot)) {
    const bin = path.join(ffRoot, build, "bin");
    if (!fs.existsSync(bin)) continue;
    const dest = path.join(stage, "engine", "recovery", "tools", "ff", build, "bin");
    fs.mkdirSync(dest, { recursive: true });
    for (const tool of ["ffmpeg.exe", "ffprobe.exe"]) {
      const src = path.join(bin, tool);
      if (fs.existsSync(src)) {
        fs.copyFileSync(src, path.join(dest, tool));
        bundled += 1;
      }
    }
  }
}

console.log(
  bundled
    ? `staged engine + icon + ${bundled} ffmpeg binaries`
    : "staged engine + icon (no bundled ffmpeg; the app will use PATH)"
);
