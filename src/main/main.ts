import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";
import * as readline from "node:readline";

import { app, BrowserWindow, dialog, ipcMain, Menu, shell } from "electron";

import type {
  AppInfo,
  OutputEntry,
  RecoveryRequest,
  RecoveryResult,
} from "../shared/types";

const SUPPORTED_SUFFIXES = new Set([".mp4", ".mov", ".m4v"]);
const MAX_STDERR = 8 * 1024;

// Packaged: resources/engine/ holds the compiled engine and the portable ffmpeg
// build, so the app never depends on the checkout being next to it.
// Development: everything lives at the repository root.
const PACKAGED = app.isPackaged;
const ENGINE_ROOT = PACKAGED
  ? path.join(process.resourcesPath, "engine")
  : app.getAppPath();
const BRIDGE = PACKAGED
  ? path.join(ENGINE_ROOT, "dist", "engine", "bridge.js")
  : path.join(app.getAppPath(), "dist", "engine", "bridge.js");
const APP_ICON = PACKAGED
  ? path.join(process.resourcesPath, "icon.png")
  : path.join(app.getAppPath(), "build", "icon.png");

interface ActiveRun {
  child: ChildProcessWithoutNullStreams;
  cancel: () => void;
}

let active: ActiveRun | null = null;
let mainWindow: BrowserWindow | null = null;

function cleanPath(raw: string): string {
  let text = String(raw ?? "").trim();
  const quote = text.at(0) ?? "";
  if (text.length >= 2 && (quote === '"' || quote === "'") && text.endsWith(quote)) {
    text = text.slice(1, -1).trim();
  }
  const lower = text.toLowerCase();
  if (lower.startsWith("file:///")) text = text.slice(8);
  else if (lower.startsWith("file://")) text = text.slice(7);
  return text;
}

/** Resolve a path that must already exist as a regular file. */
function existingFile(raw: unknown): string {
  const resolved = path.resolve(String(raw ?? "").trim());
  try {
    const real = fs.realpathSync(resolved);
    if (fs.statSync(real).isFile()) return real;
  } catch {
    // fall through to the readable error below
  }
  throw new Error(`No file exists at:\n${resolved}`);
}

function resolveVideo(raw: string): string {
  const text = cleanPath(raw);
  if (!text) throw new Error("Choose a video file first.");
  const resolved = path.resolve(text);
  let stat: fs.Stats;
  try {
    stat = fs.statSync(resolved);
  } catch {
    throw new Error(`No file exists at:\n${resolved}`);
  }
  if (!stat.isFile()) throw new Error(`That is a folder, not a video file:\n${resolved}`);
  if (!SUPPORTED_SUFFIXES.has(path.extname(resolved).toLowerCase())) {
    throw new Error("Unsupported file type. Choose an MP4, MOV or M4V file.");
  }
  return resolved;
}

function engineVersion(): string {
  return app.getVersion();
}

function buildOutputs(result: RecoveryResult): OutputEntry[] {
  const paths = result.paths || { video: null, audio: null, full_length: null, report: null };
  const recovery = result.recovery;
  const video = recovery?.video;
  const audio = recovery?.audio;

  const entries: OutputEntry[] = [];
  if (paths.video) {
    entries.push({
      label: "Clean video",
      detail: "Stream-copied from the first intact keyframe. No re-encode.",
      path: paths.video,
      name: path.basename(paths.video),
      sizeBytes: video ? video.size_bytes : null,
      kind: "video",
    });
  }
  if (paths.audio) {
    entries.push({
      label: "Early audio",
      detail: "Audio that survives before the cut, exported separately.",
      path: paths.audio,
      name: path.basename(paths.audio),
      sizeBytes: audio ? audio.size_bytes : null,
      kind: "audio",
    });
  }
  if (paths.full_length) {
    entries.push({
      label: "Full-length rebuild",
      detail: "Duplicate footage joined to the clean tail. Not the original opening.",
      path: paths.full_length,
      name: path.basename(paths.full_length),
      sizeBytes: null,
      kind: "full",
    });
  }
  if (paths.report) {
    entries.push({
      label: "Recovery report",
      detail: "Boundary timestamps, hashes and decode verification in JSON.",
      path: paths.report,
      name: path.basename(paths.report),
      sizeBytes: null,
      kind: "report",
    });
  }
  return entries;
}

function runtimePath(): string {
  return process.execPath;
}

/**
 * Windows ships taskkill in System32. Use that absolute path instead of letting
 * PATH decide which executable runs; the bare name stays as a last resort.
 */
function taskkillPath(): string {
  const root = process.env.SystemRoot ?? "C:\\Windows";
  const absolute = path.join(root, "System32", "taskkill.exe");
  return fs.existsSync(absolute) ? absolute : "taskkill";
}

function killTree(child: ChildProcessWithoutNullStreams): void {
  if (process.platform === "win32" && child.pid) {
    spawn(taskkillPath(), ["/pid", String(child.pid), "/T", "/F"], {
      windowsHide: true,
      stdio: "ignore",
    }).unref();
  } else {
    child.kill("SIGTERM");
  }
}

function runRecovery(request: RecoveryRequest): Promise<RecoveryResult> {
  return new Promise<RecoveryResult>((resolve, reject) => {
    if (active) {
      reject(new Error("A recovery is already running."));
      return;
    }

    let source: string;
    try {
      source = resolveVideo(request.path);
    } catch (error) {
      reject(error);
      return;
    }

    const args = [BRIDGE, "--path", source];
    if (request.fullDecode) args.push("--full-decode");
    if (request.fullLength) args.push("--full-length");

    let child: ChildProcessWithoutNullStreams;
    try {
      child = spawn(runtimePath(), args, {
        cwd: ENGINE_ROOT,
        windowsHide: true,
        env: {
          ...process.env,
          ELECTRON_RUN_AS_NODE: "1",
          NVIDIA_FIX_ENGINE_ROOT: ENGINE_ROOT,
        },
      });
    } catch (error) {
      reject(error);
      return;
    }

    let settled = false;
    let stderr = "";
    let result: RecoveryResult | null = null;

    const finish = (error: Error | null, value?: RecoveryResult) => {
      if (settled) return;
      settled = true;
      active = null;
      if (error) reject(error);
      else resolve(value as RecoveryResult);
    };

    const cancel = () => {
      if (settled) return;
      finish(new Error("Recovery cancelled."));
      killTree(child);
    };

    active = { child, cancel };

    child.stderr.on("data", (chunk: Buffer) => {
      stderr = (stderr + chunk.toString("utf-8")).slice(-MAX_STDERR);
    });

    child.on("error", (error: Error) => {
      finish(
        new Error(`Could not start the recovery engine.\n${error.message}`)
      );
    });

    const lines = readline.createInterface({ input: child.stdout });
    lines.on("line", (line: string) => {
      const text = line.trim();
      if (!text.startsWith("{")) {
        if (text) mainWindow?.webContents.send("recovery:progress", text);
        return;
      }
      let payload: { event?: string; message?: string; result?: RecoveryResult };
      try {
        payload = JSON.parse(text);
      } catch {
        return;
      }
      if (payload.event === "progress" && payload.message) {
        mainWindow?.webContents.send("recovery:progress", payload.message);
      } else if (payload.event === "error") {
        finish(new Error(payload.message || "Recovery failed."));
      } else if (payload.event === "result" && payload.result) {
        result = payload.result;
      }
    });

    child.on("close", (code: number | null) => {
      lines.close();
      if (settled) return;
      if (result) {
        finish(null, result);
        return;
      }
      const detail = stderr.trim();
      const suffix = detail ? `\n\n${detail}` : "";
      finish(new Error(`Recovery failed (exit ${code ?? "?"}).${suffix}`));
    });

    mainWindow?.webContents.send(
      "recovery:progress",
      "Starting the engine and scanning every video sample…"
    );
  });
}

function createWindow(): void {
  const win = new BrowserWindow({
    // Fixed size: the layout is designed for one window and never rescales.
    width: 1184,
    height: 740,
    resizable: false,
    maximizable: false,
    fullscreenable: false,
    backgroundColor: "#0c0e12",
    title: "NVIDIA-Fix",
    icon: APP_ICON,
    show: false,
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  mainWindow = win;
  Menu.setApplicationMenu(null);
  win.once("ready-to-show", () => win.show());
  win.on("closed", () => {
    if (mainWindow === win) mainWindow = null;
  });
  void win.loadFile(path.join(__dirname, "..", "renderer", "index.html"));
  if (process.env.NVIDIA_FIX_DEVTOOLS === "1") win.webContents.openDevTools();
}

app.whenReady().then(() => {
  // Windows groups taskbar buttons by AppUserModelID; without it the window
  // borrows the launcher's identity and shows the wrong icon.
  app.setAppUserModelId("com.yassine808.nvidiafix");

  ipcMain.handle("app:info", (): AppInfo => {
    const sample = path.join(ENGINE_ROOT, "recovery", "Arc_Raiders corrupted.mp4");
    return {
      version: app.getVersion(),
      engineVersion: engineVersion(),
      runtime: "TypeScript engine",
      samplePath: fs.existsSync(sample) ? sample : null,
    };
  });

  ipcMain.handle("dialog:pick-video", async (): Promise<string | null> => {
    const parent = mainWindow ?? undefined;
    const options: Electron.OpenDialogOptions = {
      title: "Choose a corrupted recording",
      properties: ["openFile"],
      filters: [
        { name: "Video", extensions: ["mp4", "mov", "m4v"] },
        { name: "All files", extensions: ["*"] },
      ],
    };
    const result = parent
      ? await dialog.showOpenDialog(parent, options)
      : await dialog.showOpenDialog(options);
    return result.canceled || result.filePaths.length === 0 ? null : result.filePaths[0];
  });

  ipcMain.handle(
    "recovery:start",
    async (_event, request: RecoveryRequest): Promise<RecoveryResult> => {
      const result = await runRecovery(request);
      result.outputs = buildOutputs(result);
      if (result.paths?.video) {
        result.saved_note = `Saved next to the original in ${path.dirname(result.paths.video)}`;
      }
      return result;
    }
  );

  ipcMain.handle("recovery:cancel", (): boolean => {
    if (!active) return false;
    active.cancel();
    return true;
  });

  ipcMain.handle("shell:open-path", (_event, target: string): Promise<string> => {
    // Validate first: IPC input must resolve to a real regular file, and the
    // path is handed to Electron as data, never interpolated into a shell.
    return shell.openPath(existingFile(target));
  });

  ipcMain.handle("shell:show-in-folder", (_event, target: string): void => {
    if (target) shell.showItemInFolder(existingFile(target));
  });

  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (active) active.cancel();
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => {
  if (active) active.cancel();
});
