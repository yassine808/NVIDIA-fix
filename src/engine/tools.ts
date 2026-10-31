// Locating and running ffmpeg/ffprobe. The engine never decodes by itself; it
// shells out to the tools ffmpeg exposes and inspects the bytes in between.

import { spawn } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";

import { NvidiaFixError, ProcessingError } from "./errors";

function which(name: string): string | null {
  const exts = process.platform === "win32" ? [".exe", ".cmd", ".bat", ""] : [""];
  for (const dir of (process.env.PATH ?? "").split(path.delimiter)) {
    if (!dir) continue;
    for (const ext of exts) {
      const candidate = path.join(dir, name + ext);
      try {
        if (fs.statSync(candidate).isFile()) return candidate;
      } catch {
        // not there
      }
    }
  }
  return null;
}

function bundled(name: string): string | null {
  const roots = [
    process.env.NVIDIA_FIX_ENGINE_ROOT,
    path.resolve(__dirname, "..", ".."),
    process.cwd(),
  ].filter((value): value is string => Boolean(value));

  for (const root of roots) {
    const ffRoot = path.join(root, "recovery", "tools", "ff");
    let builds: string[];
    try {
      builds = fs.readdirSync(ffRoot).sort();
    } catch {
      continue;
    }
    for (const build of builds) {
      const exe = path.join(ffRoot, build, "bin", `${name}.exe`);
      if (fs.existsSync(exe)) return exe;
    }
  }
  return null;
}

function resolveTool(name: string, envVar: string): string {
  const explicit = process.env[envVar];
  if (explicit) return explicit;
  return which(name) ?? bundled(name) ?? name;
}

export const FFMPEG = resolveTool("ffmpeg", "FFMPEG_BINARY");
export const FFPROBE = resolveTool("ffprobe", "FFPROBE_BINARY");

export interface RunOptions {
  check?: boolean;
  timeoutMs?: number;
  /** Run ffmpeg at below-normal priority: Yassine games on this machine. */
  lowPriority?: boolean;
}

export interface RunResult {
  stdout: string;
  stderr: string;
  code: number | null;
}

function lowerPriority(pid: number): void {
  if (process.platform !== "win32" || !pid) return;
  // Node cannot pass CREATE_BELOW_NORMAL_PRIORITY_CLASS to spawn, so ask
  // PowerShell once, after the process exists. Best effort by design.
  const child = spawn(
    "powershell",
    [
      "-NoProfile",
      "-NonInteractive",
      "-Command",
      `try { (Get-Process -Id ${pid}).PriorityClass = 'BelowNormal' } catch { }`,
    ],
    { windowsHide: true, stdio: "ignore" }
  );
  child.unref();
}

export function run(cmd: string[], options: RunOptions = {}): Promise<RunResult> {
  const { check = true, timeoutMs = 600_000, lowPriority = false } = options;
  return new Promise<RunResult>((resolve, reject) => {
    let child;
    try {
      child = spawn(cmd[0], cmd.slice(1), {
        windowsHide: true,
        stdio: ["ignore", "pipe", "pipe"],
      });
    } catch (error) {
      reject(
        new NvidiaFixError(
          `Required executable not found: ${cmd[0]}. Install ffmpeg/ffprobe and make sure they are on PATH.`
        )
      );
      return;
    }

    if (lowPriority && child.pid) lowerPriority(child.pid);

    const out: Buffer[] = [];
    const err: Buffer[] = [];
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      child.kill();
      reject(new NvidiaFixError(`Command timed out after ${Math.round(timeoutMs / 1000)}s: ${cmd[0]}`));
    }, timeoutMs);

    child.stdout?.on("data", (chunk: Buffer) => out.push(chunk));
    child.stderr?.on("data", (chunk: Buffer) => err.push(chunk));

    child.on("error", (error: NodeJS.ErrnoException) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (error.code === "ENOENT") {
        reject(
          new NvidiaFixError(
            `Required executable not found: ${cmd[0]}. Install ffmpeg/ffprobe and make sure they are on PATH.`
          )
        );
      } else {
        reject(new NvidiaFixError(error.message));
      }
    });

    child.on("close", (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      const stdout = Buffer.concat(out).toString("utf-8");
      const stderr = Buffer.concat(err).toString("utf-8");
      if (check && code !== 0) {
        const detail = (stderr || stdout || "").trim();
        reject(
          new ProcessingError(
            `${path.basename(cmd[0])} exited with ${code}: ${detail.slice(-2000)}`
          )
        );
        return;
      }
      resolve({ stdout, stderr, code });
    });
  });
}

export async function ffprobeJson(args: string[], timeoutMs = 300_000): Promise<Record<string, unknown>> {
  const result = await run([FFPROBE, "-v", "error", ...args], { timeoutMs });
  try {
    return JSON.parse(result.stdout) as Record<string, unknown>;
  } catch {
    throw new NvidiaFixError(`ffprobe returned invalid JSON: ${result.stdout.slice(0, 500)}`);
  }
}

/** Probe once up front so a missing tool is an immediate, readable error. */
export async function ensureTools(): Promise<void> {
  const missing: string[] = [];
  for (const [name, binary] of [
    ["ffmpeg", FFMPEG],
    ["ffprobe", FFPROBE],
  ]) {
    try {
      await run([binary, "-version"], { check: false, timeoutMs: 20_000 });
    } catch {
      missing.push(name);
    }
  }
  if (missing.length > 0) {
    throw new NvidiaFixError(
      `Missing required tool(s): ${missing.join(", ")}. Install ffmpeg (which includes ffprobe) and put both on PATH.`
    );
  }
}
