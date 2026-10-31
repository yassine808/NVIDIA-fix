// Node-only regressions for the TypeScript recovery engine.
//
// The verdict decides what the app says about the 37.9% it cannot recover, so
// the split between "copied later" and "destroyed" is arithmetic, not narrative.
// Run with `npm test` (builds first).

import test from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

import { avccNalTypes } from "../dist/engine/analyze.js";
import { duplicationVerdict, loadDuplicationVerdict } from "../dist/engine/duplication.js";
import { NvidiaFixError } from "../dist/engine/errors.js";
import { concatEntry, planFullLength, planToDict } from "../dist/engine/rebuild.js";
import { classifyStderr } from "../dist/engine/verify.js";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const REAL_MAP = path.join(ROOT, "recovery", "duplication_dense.json");

function rows(spec) {
  return spec.map(([t, matched]) => ({
    t,
    matched,
    src: matched ? 0 : null,
    src_t: matched ? t + 180 : null,
    run: 8192,
    entropy: 5,
  }));
}

function verdict(first = [0.12, 200], last = [50, 260], damaged = 60) {
  return {
    damagedSeconds: damaged,
    duplicatedSeconds: 0,
    destroyedSeconds: 0,
    scanBlocks: 1,
    matchedBlocks: 1,
    firstMatch: first,
    lastMatch: last,
    mapPath: null,
  };
}

test("prefix splits into copied and destroyed", () => {
  const found = duplicationVerdict(rows([[0, true], [2, true], [3, false], [4, true]]), 5);
  assert.ok(Math.abs(found.duplicatedSeconds - 4) < 1e-9);
  assert.ok(Math.abs(found.destroyedSeconds - 1) < 1e-9);
  assert.ok(
    Math.abs(found.duplicatedSeconds + found.destroyedSeconds - found.damagedSeconds) < 1e-9
  );
});

test("clean footage past the boundary is not counted", () => {
  const found = duplicationVerdict(
    rows([[0, true], [1, true], [2, false], [3, false]]),
    2
  );
  assert.ok(Math.abs(found.duplicatedSeconds - 2) < 1e-9);
  assert.ok(Math.abs(found.destroyedSeconds) < 1e-9);
  assert.equal(found.scanBlocks, 4);
  assert.ok(Math.abs(found.matchedBlocks / found.scanBlocks - 0.5) < 1e-9);
});

test("match window is reported", () => {
  const found = duplicationVerdict(rows([[0.12, true], [107.54, true]]), 113.782);
  assert.deepEqual(found.firstMatch, [0.12, 180.12]);
  assert.deepEqual(found.lastMatch, [107.54, 287.54]);
});

test("untimed map is rejected", () => {
  assert.throws(() => duplicationVerdict([{ t: null, matched: true }], 10), NvidiaFixError);
});

test("missing map names the command that makes one", () => {
  assert.throws(
    () => loadDuplicationVerdict(path.join(ROOT, "tmp-does-not-exist.mp4"), 12),
    (error) => error instanceof NvidiaFixError && error.message.includes("forensics/duplication_dense.py")
  );
});

test("recorded map reproduces the published split", { skip: !fs.existsSync(REAL_MAP) }, () => {
  const payload = JSON.parse(fs.readFileSync(REAL_MAP, "utf-8"));
  const found = duplicationVerdict(payload.rows, 113.782);
  assert.ok(Math.abs(found.duplicatedSeconds - 105.73) < 0.01);
  assert.ok(Math.abs(found.destroyedSeconds - 8.05) < 0.01);
  assert.ok(Math.abs(found.matchedBlocks / found.scanBlocks - 0.808) < 0.001);
  assert.deepEqual(found.firstMatch, [0.12, 182.54]);
  assert.deepEqual(found.lastMatch, [107.54, 299.79]);
});

test("copy window fills the missing opening", () => {
  const plan = planFullLength(114.031811, 185.981, verdict([0.12, 180], [50, 300]));
  assert.ok(Math.abs(plan.duration - 114.031811) < 1e-9);
  assert.ok(Math.abs(plan.startInTail - (180 - 114.031811)) < 1e-9);
  assert.ok(Math.abs(plan.needed - plan.duration) < 1e-9);
  assert.ok(plan.startInTail + plan.duration <= 185.981 + 1e-9);
});

test("short copy window reports the shortfall", () => {
  const plan = planFullLength(114, 185, verdict([0.12, 200], [50, 260]));
  assert.ok(Math.abs(plan.duration - 60) < 1e-9);
  assert.ok(Math.abs(plan.available - 60) < 1e-9);
  assert.ok(Math.abs(plan.needed - plan.duration - 54) < 1e-9);
});

test("copy starting before the cut clamps to zero", () => {
  const plan = planFullLength(114, 185, verdict([0.12, 100], [50, 300]));
  assert.equal(plan.startInTail, 0);
  assert.equal(plan.timelineStart, 114);
});

test("copy running past the tail end is pulled back", () => {
  const plan = planFullLength(114, 60, verdict([0.12, 200], [50, 400]));
  assert.ok(Math.abs(plan.duration - 60) < 1e-9);
  assert.ok(plan.startInTail + plan.duration <= 60 + 1e-9);
});

test("no plan without a map or matches", () => {
  assert.equal(planFullLength(114, 186, null), null);
  const empty = verdict();
  empty.firstMatch = null;
  empty.lastMatch = null;
  assert.equal(planFullLength(114, 186, empty), null);
});

test("no plan for a negligible opening", () => {
  assert.equal(planFullLength(0.2, 186, verdict()), null);
});

test("plan dict is rounded", () => {
  const doc = planToDict(planFullLength(114, 185, verdict()));
  assert.equal(doc.filled_seconds, 60);
  assert.equal(typeof doc.start_in_tail_seconds, "number");
});

test("concat entries survive Windows paths and quotes", () => {
  assert.equal(concatEntry("D:\\a b\\c'd.mp4"), "file 'D:/a b/c'\\''d.mp4'");
});

test("ffmpeg muxer warnings never count as decode errors", () => {
  const check = classifyStderr([
    "[null @ 0x1] Application provided invalid, non monotonically increasing dts to muxer in stream 0",
    "[h264 @ 0x2] error while decoding MB 3 4",
    "something else",
  ]);
  assert.equal(check.warnings.length, 1);
  assert.equal(check.errors.length, 1);
  assert.equal(check.unclassified.length, 1);
});

test("AVCC parser accepts only well-formed samples", () => {
  const single = Buffer.alloc(4 + 1 + 10);
  single.writeUInt32BE(11, 0);
  single[4] = 0x65; // IDR
  assert.deepEqual(avccNalTypes(single), [5]);

  const forbidden = Buffer.from(single);
  forbidden[4] = 0x80;
  assert.equal(avccNalTypes(forbidden), null);

  const truncated = Buffer.alloc(6);
  truncated.writeUInt32BE(99, 0);
  truncated[4] = 0x41;
  assert.equal(avccNalTypes(truncated), null);

  const multi = Buffer.alloc(4 + 1 + 2 + 4 + 1 + 2);
  let offset = 0;
  multi.writeUInt32BE(3, offset);
  multi[offset + 4] = 0x09; // AUD
  offset += 4 + 3;
  multi.writeUInt32BE(3, offset);
  multi[offset + 4] = 0x65; // IDR
  assert.deepEqual(avccNalTypes(multi), [9, 5]);
});
