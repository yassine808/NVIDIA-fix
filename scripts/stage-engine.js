// Stages the sidecar resources the packaged app needs:
//
//   .stage/engine/recovery/tools/ff/...  portable ffmpeg (if downloaded)
//   .stage/icon.png                      window/taskbar icon
//
// electron-builder copies `.stage` into the app's resources folder and copies
// dist/engine there separately (see "extraResources" in package.json), so the
// packaged layout is:
//
//   resources/engine/dist/engine/bridge.js   compiled recovery engine
//   resources/engine/recovery/tools/ff/...   ffmpeg, when available
//   resources/icon.png                       icon
//
// The ffmpeg build lives under recovery/ (git-ignored), so a machine without it
// still packages; that build then needs ffmpeg on PATH.
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const stage = path.join(root, ".stage");

fs.rmSync(stage, { recursive: true, force: true });
fs.mkdirSync(path.join(stage, "engine"), { recursive: true });

fs.copyFileSync(path.join(root, "build", "icon.png"), path.join(stage, "icon.png"));

// Keep the <build>/bin/<tool>.exe shape the engine globs for, newest build only
// so the installer never carries two copies of ffmpeg.
const ffRoot = path.join(root, "recovery", "tools", "ff");
let bundled = 0;
if (fs.existsSync(ffRoot)) {
  const builds = fs
    .readdirSync(ffRoot)
    .filter((build) => fs.existsSync(path.join(ffRoot, build, "bin")))
    .sort();
  const build = builds[builds.length - 1];
  if (build) {
    const bin = path.join(ffRoot, build, "bin");
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
    ? `staged icon + ${bundled} ffmpeg binaries`
    : "staged icon (no bundled ffmpeg; the app will use PATH)"
);
