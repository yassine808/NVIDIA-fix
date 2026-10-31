// Downloads the latest portable ffmpeg/ffprobe into recovery/tools/ff so the
// packaged app ships its own copy and never depends on the user's PATH.
//
//   node scripts/fetch-ffmpeg.js            # skip when a build is already there
//   node scripts/fetch-ffmpeg.js --force    # re-download the newest release
//
// Layout stays `<build>/bin/<tool>.exe` because that is what
// src/engine/tools.ts and scripts/stage-engine.js look for. Only the two
// executables are kept; the zip's docs and ffplay are dropped.
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { execFileSync } = require("node:child_process");
const https = require("node:https");

const root = path.resolve(__dirname, "..");
const ffRoot = path.join(root, "recovery", "tools", "ff");
const VERSION_URL = "https://www.gyan.dev/ffmpeg/builds/release-version";
const ZIP_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip";
const REQUIRED = ["ffmpeg.exe", "ffprobe.exe"];

const force = process.argv.includes("--force") || process.env.NVIDIA_FIX_FETCH_FORCE === "1";

function existing() {
  if (!fs.existsSync(ffRoot)) return null;
  for (const build of fs.readdirSync(ffRoot).sort().reverse()) {
    const bin = path.join(ffRoot, build, "bin");
    if (REQUIRED.every((tool) => fs.existsSync(path.join(bin, tool)))) return { build, bin };
  }
  return null;
}

function get(url, redirects = 0) {
  return new Promise((resolve, reject) => {
    https
      .get(url, { headers: { "user-agent": "nvidia-fix-build" } }, (res) => {
        if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location && redirects < 5) {
          res.resume();
          resolve(get(res.headers.location, redirects + 1));
          return;
        }
        if (res.statusCode !== 200) {
          res.resume();
          reject(new Error(`GET ${url} -> HTTP ${res.statusCode}`));
          return;
        }
        resolve(res);
      })
      .on("error", reject);
  });
}

async function readText(url) {
  const res = await get(url);
  const chunks = [];
  for await (const chunk of res) chunks.push(chunk);
  return Buffer.concat(chunks).toString("utf-8").trim();
}

async function download(url, target) {
  const res = await get(url);
  const total = Number(res.headers["content-length"] || 0);
  await new Promise((resolve, reject) => {
    const out = fs.createWriteStream(target);
    let seen = 0;
    let nextMark = 10;
    res.on("data", (chunk) => {
      seen += chunk.length;
      if (total) {
        const pct = (seen / total) * 100;
        if (pct >= nextMark) {
          process.stdout.write(`  ${pct.toFixed(0)}%\r`);
          nextMark += 10;
        }
      }
    });
    res.pipe(out);
    out.on("finish", () => {
      process.stdout.write("  100%\n");
      resolve();
    });
    out.on("error", reject);
    res.on("error", reject);
  });
}

function unzip(zip, into) {
  if (process.platform === "win32") {
    execFileSync(
      "powershell",
      ["-NoProfile", "-NonInteractive", "-Command", `Expand-Archive -LiteralPath '${zip}' -DestinationPath '${into}' -Force`],
      { stdio: "inherit" }
    );
    return;
  }
  execFileSync("unzip", ["-q", zip, "-d", into], { stdio: "inherit" });
}

async function main() {
  const have = existing();
  if (have && !force) {
    console.log(`ffmpeg already bundled: ${path.relative(root, have.bin)} (use --force to refresh)`);
    return;
  }

  let version = "latest";
  try {
    version = await readText(VERSION_URL);
  } catch (error) {
    console.warn(`could not read the release version (${error.message}); using the rolling zip name`);
  }

  const build = `ffmpeg-${version}-essentials_build`;
  const dest = path.join(ffRoot, build, "bin");
  if (REQUIRED.every((tool) => fs.existsSync(path.join(dest, tool)))) {
    console.log(`ffmpeg ${version} already present: ${path.relative(root, dest)}`);
    return;
  }

  const work = fs.mkdtempSync(path.join(os.tmpdir(), "nvidia-fix-ffmpeg-"));
  const zip = path.join(work, "ffmpeg.zip");
  try {
    console.log(`downloading ffmpeg ${version} from gyan.dev ...`);
    await download(ZIP_URL, zip);
    console.log("extracting ...");
    const unpacked = path.join(work, "unpacked");
    fs.mkdirSync(unpacked, { recursive: true });
    unzip(zip, unpacked);

    const inner = fs.readdirSync(unpacked).map((name) => path.join(unpacked, name));
    const binSource = inner
      .map((dir) => path.join(dir, "bin"))
      .find((bin) => REQUIRED.every((tool) => fs.existsSync(path.join(bin, tool))));
    if (!binSource) throw new Error("the downloaded archive has no bin/ffmpeg.exe + ffprobe.exe");

    fs.mkdirSync(dest, { recursive: true });
    for (const tool of REQUIRED) fs.copyFileSync(path.join(binSource, tool), path.join(dest, tool));
    fs.writeFileSync(path.join(ffRoot, "VERSION"), `${version}\n`, "utf-8");
    console.log(`bundled ffmpeg ${version}: ${path.relative(root, dest)}`);
  } finally {
    fs.rmSync(work, { recursive: true, force: true });
  }
}

main().catch((error) => {
  console.error(`ffmpeg download failed: ${error.message}`);
  console.error("The app still builds; it will fall back to ffmpeg on PATH.");
  process.exitCode = 1;
});
