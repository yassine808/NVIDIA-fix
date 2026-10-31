#!/usr/bin/env node
// Command line for the recovery engine. Same commands and JSON as before:
//   analyze <input> [--json]
//   fix <input> [--out DIR] [--no-full-decode] [--full-length] [--json]
//   explain <input> [--map FILE] [--json]
//   --version

import { analyze, analysisToDict, isHealthy } from "./analyze";
import { explain } from "./duplication";
import { NvidiaFixError } from "./errors";
import { process as recover } from "./process";
import { TOOL, VERSION, Json } from "./types";

function usage(): string {
  return [
    "usage: nvidia-fix <command> [options]",
    "",
    "commands:",
    "  analyze <input> [--json]        inspect a file without writing outputs",
    "  fix <input> [--out DIR] [--no-full-decode] [--full-length] [--json]",
    "  explain <input> [--map FILE] [--json]",
    "",
    "options:",
    "  --version                       print the version",
  ].join("\n");
}

function value(args: string[], name: string): string | undefined {
  const index = args.indexOf(name);
  return index >= 0 ? args[index + 1] : undefined;
}

function printAnalysis(analysis: Awaited<ReturnType<typeof analyze>>): void {
  const video = analysis.media.video;
  if (isHealthy(analysis)) {
    console.log("No corruption detected. The file is intact.");
    return;
  }
  const boundary = analysis.candidates[0];
  console.log(`Input        : ${analysis.path}`);
  console.log(`Video        : ${video.codec_name} ${video.width}x${video.height}`);
  console.log(`Samples      : ${analysis.samples.length} (${analysis.badSamples} invalid)`);
  console.log(`First bad    : ${analysis.firstBad!.pts.toFixed(3)}s`);
  console.log(`Last bad     : ${analysis.lastBad!.pts.toFixed(3)}s`);
  console.log(
    boundary
      ? `Clean IDR    : ${boundary.pts.toFixed(6)}s (index ${boundary.index})`
      : "Clean IDR    : none found"
  );
  console.log();
  console.log(analysis.warning);
}

function printExplain(result: Json): void {
  if (result.status === "healthy") {
    console.log(text(result.verdict));
    return;
  }
  const verdict = result.duplication as Json;
  const timeline = result.timeline as Json;
  const first = verdict.first_match as number[] | null;
  const last = verdict.last_match as number[] | null;
  console.log(`Input          : ${text(result.input)}`);
  console.log(`Damaged prefix : ${Number(verdict.damaged_seconds).toFixed(3)} s`);
  console.log(
    `  copied later : ${Number(verdict.duplicated_seconds).toFixed(3)} s ` +
      `(${(100 * Number(verdict.duplicated_fraction)).toFixed(1)}% of the prefix, ` +
      `${(100 * Number(verdict.matched_fraction)).toFixed(1)}% of the scanned blocks)`
  );
  console.log(`  destroyed    : ${Number(verdict.destroyed_seconds).toFixed(3)} s`);
  if (first && last) {
    console.log(
      `  copy window  : container ${first[0].toFixed(2)} s -> content ${first[1].toFixed(2)} s ` +
        `... container ${last[0].toFixed(2)} s -> content ${last[1].toFixed(2)} s`
    );
  }
  console.log(
    `Recoverable    : ${Number(timeline.recoverable_seconds).toFixed(3)} s of ` +
      `${Number(timeline.duration_seconds).toFixed(3)} s ` +
      `(${(100 * Number(timeline.recoverable_fraction)).toFixed(1)}%)`
  );
  console.log(`Verdict        : ${result.verdict}`);
}

/** Render any JSON value without ever printing "[object Object]". */
function text(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number") return String(value);
  return JSON.stringify(value) ?? String(value);
}

function printFixResult(result: Json, fullLengthRequested: boolean): void {
  if (result.status === "healthy") {
    console.log(text(result.message));
    return;
  }
  const paths = result.paths as Json;
  console.log(`Clean tail   : ${text(paths.video)}`);
  if (paths.audio) console.log(`Early audio  : ${text(paths.audio)}`);
  if (paths.full_length) {
    const full = (result.full_length ?? {}) as Json;
    console.log(`Full-length  : ${text(paths.full_length)}`);
    console.log(
      `               ${Number(full.video_duration_seconds ?? 0).toFixed(3)} s, ` +
        `${text(full.video_frames ?? 0)} frames; first ` +
        `${Number(full.filled_seconds ?? 0).toFixed(3)} s repeats footage from ` +
        `${Number(full.timeline_start_seconds ?? 0).toFixed(3)}–` +
        `${Number(full.timeline_end_seconds ?? 0).toFixed(3)} s (not the original opening)`
    );
  } else if (fullLengthRequested) {
    const block = (result.full_length ?? {}) as Json;
    console.log(`Full-length  : not built (${text(block.skipped ?? block.error ?? "not built")})`);
  }
  console.log(`Report       : ${text(paths.report)}`);
  console.log(`Status       : ${text(result.status)}`);
  const recovery = result.recovery as Json;
  const video = recovery.video as Json;
  console.log(`Decode errors: ${text(video.decode_errors)}`);
  const warnings = Number(recovery.muxer_warnings ?? 0);
  if (warnings > 0) {
    console.log(`Muxer warning: ${warnings} timestamp warning(s) (not file damage)`);
  }
}

function findInput(args: string[]): string | undefined {
  const withValue = new Set(["--out", "--map"]);
  for (let i = 0; i < args.length; i += 1) {
    const arg = args[i];
    if (withValue.has(arg)) {
      i += 1;
      continue;
    }
    if (arg.startsWith("--")) continue;
    return arg;
  }
  return undefined;
}

async function runAnalyze(input: string | undefined, rest: string[]): Promise<number> {
  if (!input) throw new NvidiaFixError("analyze needs an input file.");
  const analysis = await analyze(input);
  if (rest.includes("--json")) console.log(JSON.stringify(analysisToDict(analysis), null, 2));
  else printAnalysis(analysis);
  return 0;
}

async function runFix(input: string | undefined, rest: string[]): Promise<number> {
  if (!input) throw new NvidiaFixError("fix needs an input file.");
  const result = await recover(input, {
    outDir: value(rest, "--out") ?? null,
    fullDecode: !rest.includes("--no-full-decode"),
    fullLength: rest.includes("--full-length"),
  });
  if (rest.includes("--json")) {
    console.log(JSON.stringify(result, null, 2));
  } else {
    printFixResult(result, rest.includes("--full-length"));
  }
  return 0;
}

async function runExplain(input: string | undefined, rest: string[]): Promise<number> {
  if (!input) throw new NvidiaFixError("explain needs an input file.");
  const result = await explain(input, value(rest, "--map") ?? null);
  if (rest.includes("--json")) console.log(JSON.stringify(result, null, 2));
  else printExplain(result);
  return 0;
}

async function main(argv: string[]): Promise<number> {
  if (argv.includes("--version")) {
    console.log(`${TOOL} ${VERSION}`);
    return 0;
  }
  const command = argv[0];
  const rest = argv.slice(1);
  const input = findInput(rest);

  if (!command || command === "help" || command === "-h" || command === "--help") {
    console.log(usage());
    return command ? 0 : 1;
  }

  try {
    if (command === "analyze") return await runAnalyze(input, rest);
    if (command === "fix") return await runFix(input, rest);
    if (command === "explain") return await runExplain(input, rest);

    console.log(usage());
    return 1;
  } catch (error) {
    if (error instanceof NvidiaFixError) {
      console.error(`error: ${error.message}`);
      return 2;
    }
    throw error;
  }
}

main(process.argv.slice(2))
  .then((code) => process.exit(code))
  .catch((error) => {
    console.error(error);
    process.exit(1);
  });
