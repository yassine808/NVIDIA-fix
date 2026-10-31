// Copies the static renderer into dist/ so the packaged app has one
// self-contained output folder.
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const src = path.join(root, "src", "renderer");
const dest = path.join(root, "dist", "renderer");

fs.mkdirSync(dest, { recursive: true });
for (const name of ["index.html"]) {
  fs.copyFileSync(path.join(src, name), path.join(dest, name));
}
console.log("copied renderer assets to dist/renderer");
