/*
 * End-to-end smoke test for the Electron UI.
 *
 * Launches the real app with remote debugging, drives the renderer through the
 * Chrome DevTools Protocol, starts a recovery, and waits for the result page.
 * Uses only Node built-ins. Example:
 *
 *   npm run smoke -- --path "recovery\Arc_Raiders corrupted.mp4"
 */
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const APP_DIR = path.resolve(__dirname, "..");
const ELECTRON = require("electron");
const PORT = 9333;

function arg(name, fallback) {
  const index = process.argv.indexOf(`--${name}`);
  return index >= 0 && process.argv[index + 1] ? process.argv[index + 1] : fallback;
}

const videoPath = arg("path", "");
const timeoutMs = Number(arg("timeout", "600000"));
// Optional: --shot <dir> writes home.png and result.png from the real window.
const shotDir = arg("shot", "");
if (!videoPath) {
  console.error("Usage: node scripts/smoke-ui.js --path <video> [--timeout ms]");
  process.exit(2);
}

if (!process.env.NVIDIA_FIX_PYTHON) {
  console.log("python: default (python)");
}

const child = spawn(ELECTRON, [".", `--remote-debugging-port=${PORT}`], {
  cwd: APP_DIR,
  stdio: ["ignore", "pipe", "pipe"],
  windowsHide: true,
});

let stderr = "";
child.stderr.on("data", (chunk) => {
  stderr = (stderr + chunk.toString()).slice(-8000);
});
child.stdout.on("data", () => {});
child.on("exit", (code) => {
  if (code && stderr) console.error(stderr);
});

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function findTarget() {
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${PORT}/json/list`);
      const targets = await response.json();
      const page = targets.find(
        (target) => target.type === "page" && String(target.url).includes("index.html")
      );
      if (page && page.webSocketDebuggerUrl) return page;
    } catch {
      // Electron is still starting.
    }
    await sleep(400);
  }
  throw new Error("The Electron window never exposed a debugging target.");
}

function connect(url) {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(url);
    const pending = new Map();
    const listeners = [];
    let nextId = 1;

    function send(method, params = {}) {
      const id = nextId++;
      socket.send(JSON.stringify({ id, method, params }));
      return new Promise((res, rej) => pending.set(id, { res, rej }));
    }

    socket.addEventListener("open", () => {
      resolve({
        send,
        evaluate(expression) {
          return send("Runtime.evaluate", {
            expression,
            returnByValue: true,
            awaitPromise: true,
          }).then((message) => {
            if (message.exceptionDetails) {
              throw new Error(
                message.exceptionDetails.exception?.description ||
                  message.exceptionDetails.text ||
                  "Renderer exception"
              );
            }
            return message.result?.value;
          });
        },
        onEvent(listener) {
          listeners.push(listener);
        },
        close: () => socket.close(),
      });
    });

    socket.addEventListener("message", (event) => {
      let message;
      try {
        message = JSON.parse(String(event.data));
      } catch {
        return;
      }
      if (!message.id) {
        for (const listener of listeners) listener(message);
        return;
      }
      const waiter = pending.get(message.id);
      if (!waiter) return;
      pending.delete(message.id);
      if (message.error) waiter.rej(new Error(message.error.message));
      else waiter.res(message.result);
    });

    socket.addEventListener("error", () => reject(new Error("CDP socket error")));
  });
}

function killTree() {
  if (process.platform === "win32" && child.pid) {
    spawn("taskkill", ["/pid", String(child.pid), "/T", "/F"], {
      stdio: "ignore",
      windowsHide: true,
    });
  } else {
    child.kill("SIGTERM");
  }
}

(async () => {
  try {
    const target = await findTarget();
    const cdp = await connect(target.webSocketDebuggerUrl);
    await cdp.send("Runtime.enable");
    await cdp.send("Log.enable");
    await cdp.send("Page.enable");
    cdp.onEvent((message) => {
      if (message.method === "Runtime.exceptionThrown") {
        const details = message.params?.exceptionDetails;
        console.error(
          "renderer exception:",
          details?.exception?.description || details?.text || "(unknown)"
        );
      } else if (message.method === "Log.entryAdded") {
        const entry = message.params?.entry;
        if (entry && ["error", "warning"].includes(entry.level)) {
          console.error(`renderer ${entry.level}:`, entry.text);
        }
      }
    });

    await cdp.evaluate(`location.href`);
    const loadDeadline = Date.now() + 15000;
    let diagnostics = null;
    while (Date.now() < loadDeadline) {
      diagnostics = await cdp.evaluate(`({
        ready: document.readyState,
        api: typeof window.nvidiaFix,
        input: Boolean(document.getElementById('video_path')),
        title: document.title,
        href: location.href,
        version: document.getElementById('version')?.textContent,
        body: document.body ? document.body.innerText.slice(0, 400) : '',
        scripts: Array.from(document.scripts).map((s) => s.src)
      })`);
      if (diagnostics.ready === "complete" && diagnostics.input) break;
      await sleep(300);
    }
    console.log("renderer diagnostics:", JSON.stringify(diagnostics));
    if (!diagnostics || diagnostics.api !== "object" || !diagnostics.input) {
      throw new Error("Renderer did not expose the expected UI/API.");
    }

    async function capture(name) {
      if (!shotDir) return;
      fs.mkdirSync(shotDir, { recursive: true });
      const shot = await cdp.send("Page.captureScreenshot", { format: "png" });
      const file = path.join(shotDir, name);
      fs.writeFileSync(file, Buffer.from(shot.data, "base64"));
      console.log(`screenshot: ${file}`);
    }
    await capture("home.png");

    await cdp.evaluate(`(() => {
      const input = document.getElementById('video_path');
      input.value = ${JSON.stringify(videoPath)};
      input.dispatchEvent(new Event('input', { bubbles: true }));
      document.querySelector('input[name=full_decode]').checked = true;
      const go = document.getElementById('go');
      if (go.disabled) throw new Error('Recover button stayed disabled.');
      go.click();
      return true;
    })()`);

    const deadline = Date.now() + timeoutMs;
    let lastLog = "";
    while (Date.now() < deadline) {
      await sleep(1000);
      const state = await cdp.evaluate(`(() => {
        const result = document.getElementById('result');
        const error = document.getElementById('note');
        const log = document.getElementById('steps');
        return {
          done: Boolean(result && !result.hidden),
          error: Boolean(error && !error.hidden),
          text: error && !error.hidden ? error.textContent : '',
          log: log ? log.innerText : '',
          page: document.body.innerText,
        };
      })()`);

      if (state.log && state.log !== lastLog) {
        lastLog = state.log;
        for (const line of state.log.split("\n").slice(-2)) console.log(`  · ${line}`);
      }
      if (state.error) throw new Error(state.text || "The UI reported an error.");
      if (state.done) {
        const text = state.page || "";
        if (!/Clean video/i.test(text)) {
          throw new Error("The result page did not list the recovered video.");
        }
        console.log("\n--- result page ---");
        console.log(text.replace(/\n{2,}/g, "\n").trim());
        await capture("result.png");
        console.log("\nSMOKE TEST PASSED");
        cdp.close();
        killTree();
        process.exit(0);
      }
    }
    throw new Error("Timed out waiting for the recovery result.");
  } catch (error) {
    console.error(`SMOKE TEST FAILED: ${error.message}`);
    killTree();
    process.exit(1);
  }
})();
