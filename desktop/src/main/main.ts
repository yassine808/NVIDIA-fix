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

const PYTHON = process.env.NVIDIA_FIX_PYTHON || "python";
const ENGINE_ROOT = path.resolve(app.getAppPath(), "..");
const BRIDGE =
  process.env.NVIDIA_FIX_BRIDGE ||
  path.join(app.getAppPath(), "scripts", "bridge.py");

interface ActiveRun {
  child: ChildProcessWithoutNullStreams;
  cancel: () => void;
}

let active: ActiveRun | null = null;
let mainWindow: BrowserWindow | null = null;

function cleanPath(raw: string): string {
  let text = String(raw ?? "").trim();
  if (text.length >= 2 && text[0] === text[text.length - 1] && (text[0] === '"' || text[0] === "'")) {
    text = text.slice(1, -1).trim();
  }
  if (text.toLowerCase().startsWith("file:///")) text = text.slice(8);
  else if (text.toLowerCase().startsWith("file://")) text = text.slice(7);
  return text;
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
  try {
    const source = fs.readFileSync(path.join(ENGINE_ROOT, "nvidia_fix.py"), "utf-8");
    const match = source.match(/^VERSION\s*=\s*"([^"]+)"/m);
    return match ? match[1] : "unknown";
  } catch {
    return "unknown";
  }
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

function pickPython(): string {
  return PYTHON;
}

function killTree(child: ChildProcessWithoutNullStreams): void {
  if (process.platform === "win32" && child.pid) {
    spawn("taskkill", ["/pid", String(child.pid), "/T", "/F"], {
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
      child = spawn(pickPython(), args, {
        cwd: ENGINE_ROOT,
        windowsHide: true,
        env: { ...process.env, PYTHONIOENCODING: "utf-8" },
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
        new Error(
          `Could not start Python (${pickPython()}). Set NVIDIA_FIX_PYTHON to a working interpreter.\n${error.message}`
        )
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
      finish(
        new Error(
          `Recovery failed (exit ${code ?? "?"}).${detail ? `\n\n${detail}` : ""}`
        )
      );
    });

    mainWindow?.webContents.send(
      "recovery:progress",
      "Starting the engine and scanning every video sample…"
    );
  });
}

function createWindow(): void {
  const win = new BrowserWindow({
    width: 1060,
    height: 780,
    minWidth: 860,
    minHeight: 620,
    backgroundColor: "#0c0e12",
    title: "NVIDIA-Fix",
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
  ipcMain.handle("app:info", (): AppInfo => {
    const sample = path.join(ENGINE_ROOT, "recovery", "Arc_Raiders corrupted.mp4");
    return {
      version: app.getVersion(),
      engineVersion: engineVersion(),
      python: pickPython(),
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
    return shell.openPath(String(target ?? ""));
  });

  ipcMain.handle("shell:show-in-folder", (_event, target: string): void => {
    if (target) shell.showItemInFolder(String(target));
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
