// Copies the static renderer into dist/ so the packaged app has one
// self-contained output folder. The app icon ships with it, because the page's
// favicon is that same file - one identity for the tab, the window and the
// taskbar.
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const src = path.join(root, "src", "renderer");
const dest = path.join(root, "dist", "renderer");

fs.mkdirSync(dest, { recursive: true });
fs.copyFileSync(path.join(src, "index.html"), path.join(dest, "index.html"));
fs.copyFileSync(path.join(root, "build", "icon.png"), path.join(dest, "icon.png"));
console.log("copied renderer assets to dist/renderer");
