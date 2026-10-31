// Complete-length rebuild: the copied opening, then the clean tail, then the
// original audio over both. Stream copies only - nothing is re-encoded.

import * as fs from "node:fs";
import * as path from "node:path";

import { ffprobeJson, run, FFMPEG } from "./tools";
import { decodeCheck } from "./verify";
import {
  DuplicationVerdict,
  FULL_LENGTH_CAVEAT,
  FULL_LENGTH_SUFFIX,
  FullLengthPlan,
  Json,
  MIN_FULL_LENGTH_SECONDS,
  ProgressCallback,
  round6,
  toFloat,
} from "./types";

export { DUPLICATION_MAP_NAME } from "./types";

export function planFullLength(
  cleanStart: number,
  tailDuration: number,
  verdict: DuplicationVerdict | null
): FullLengthPlan | null {
  if (!verdict?.firstMatch || !verdict.lastMatch) return null;
  const needed = cleanStart;
  if (needed < MIN_FULL_LENGTH_SECONDS || tailDuration < MIN_FULL_LENGTH_SECONDS) return null;

  const contentStart = verdict.firstMatch[1];
  const contentEnd = verdict.lastMatch[1];
  const available = Math.max(0, contentEnd - contentStart);
  const duration = Math.min(needed, available, tailDuration);
  if (duration < MIN_FULL_LENGTH_SECONDS) return null;

  // Tail second 0 is source second `cleanStart`, so the copy begins that much
  // earlier than the content time the map reports.
  let start = contentStart - needed;
  start = Math.min(Math.max(0, start), Math.max(0, tailDuration - duration));
  return {
    startInTail: start,
    duration,
    needed,
    available,
    timelineStart: cleanStart + start,
    timelineEnd: cleanStart + start + duration,
  };
}

export function planToDict(plan: FullLengthPlan): Json {
  return {
    filled_seconds: round6(plan.duration),
    start_in_tail_seconds: round6(plan.startInTail),
    timeline_start_seconds: round6(plan.timelineStart),
    timeline_end_seconds: round6(plan.timelineEnd),
    needed_seconds: round6(plan.needed),
    available_seconds: round6(plan.available),
    shortfall_seconds: round6(Math.max(0, plan.needed - plan.duration)),
  };
}

// A single backslash, written without an escaped literal so no regex or
// double-escaped string is needed (String.raw cannot close on one).
const BACKSLASH = String.fromCodePoint(92);

/** A concat-demuxer line that survives spaces, quotes and Windows paths. */
export function concatEntry(target: string): string {
  const text = target.replaceAll(BACKSLASH, "/").replaceAll("'", `'${BACKSLASH}''`);
  return `file '${text}'`;
}

function notify(progress: ProgressCallback | null, message: string): void {
  if (!progress) return;
  try {
    progress(message);
  } catch {
    // A UI callback must never break recovery.
  }
}

export async function rebuildFullLength(
  source: string,
  tailVideo: string,
  plan: FullLengthPlan,
  target: string,
  fullDecode = true,
  progress: ProgressCallback | null = null
): Promise<Json> {
  fs.mkdirSync(path.dirname(target), { recursive: true });
  const work = fs.mkdtempSync(path.join(path.dirname(target), "nvidia-fix-rebuild-"));
  try {
    const head = path.join(work, "head.mp4");
    notify(progress, `Re-cutting the first ${plan.duration.toFixed(3)} s from the copied footage…`);
    await run(
      [
        FFMPEG,
        "-hide_banner",
        "-v",
        "error",
        "-nostdin",
        "-y",
        "-ss",
        plan.startInTail.toFixed(6),
        "-i",
        tailVideo,
        "-t",
        plan.duration.toFixed(6),
        "-map",
        "0:v:0",
        "-c",
        "copy",
        "-avoid_negative_ts",
        "make_zero",
        head,
      ],
      { timeoutMs: 1_800_000, lowPriority: true }
    );

    const joined = path.join(work, "joined.mp4");
    const listing = path.join(work, "concat.txt");
    fs.writeFileSync(listing, `${[concatEntry(head), concatEntry(tailVideo)].join("\n")}\n`, "utf-8");

    notify(progress, "Joining the rebuilt opening to the clean tail…");
    await run(
      [
        FFMPEG,
        "-hide_banner",
        "-v",
        "error",
        "-nostdin",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        listing,
        "-c",
        "copy",
        "-avoid_negative_ts",
        "make_zero",
        joined,
      ],
      { timeoutMs: 1_800_000, lowPriority: true }
    );

    notify(progress, "Muxing the original audio track over the whole rebuild…");
    await run(
      [
        FFMPEG,
        "-hide_banner",
        "-v",
        "error",
        "-nostdin",
        "-y",
        "-i",
        joined,
        "-i",
        source,
        "-map",
        "0:v:0",
        "-map",
        "1:a:0?",
        "-c",
        "copy",
        "-shortest",
        "-movflags",
        "+faststart",
        target,
      ],
      { timeoutMs: 1_800_000, lowPriority: true }
    );
  } finally {
    fs.rmSync(work, { recursive: true, force: true });
  }

  const info: Json = {};
  let streams: Array<Record<string, unknown>> = [];
  try {
    const data = await ffprobeJson([
      "-show_entries",
      "stream=codec_type,duration,nb_frames",
      "-of",
      "json",
      target,
    ]);
    streams = (data.streams as Array<Record<string, unknown>> | undefined) ?? [];
  } catch {
    streams = [];
  }
  const video = streams.find((stream) => stream.codec_type === "video") ?? {};
  const audio = streams.find((stream) => stream.codec_type === "audio") ?? {};
  Object.assign(info, {
    name: path.basename(target),
    size_bytes: fs.statSync(target).size,
    video_duration_seconds: round6(toFloat(video.duration, 0)),
    video_frames: Math.trunc(toFloat(video.nb_frames, 0)),
    audio_duration_seconds: audio && Object.keys(audio).length > 0 ? round6(toFloat(audio.duration, 0)) : null,
    audio_frames: audio && Object.keys(audio).length > 0 ? Math.trunc(toFloat(audio.nb_frames, 0)) : null,
  });
  Object.assign(info, planToDict(plan));
  info.caveat = FULL_LENGTH_CAVEAT;
  if (fullDecode) {
    notify(progress, "Decoding the full-length rebuild to verify it…");
    const check = await decodeCheck(target);
    Object.assign(info, {
      decode_errors: check.errors.length,
      decode_error_sample: check.errors.slice(0, 20),
      muxer_warnings: check.warnings.length,
      unclassified_output: check.unclassified.slice(0, 5),
    });
  }
  info.decode_checked = Boolean(fullDecode);
  return info;
}

export interface FullLengthBlockOptions {
  source: string;
  tailVideo: string;
  tailDuration: number;
  cleanStart: number;
  verdict: DuplicationVerdict | null;
  destination: string;
  base: string;
  fullDecode: boolean;
  progress: ProgressCallback | null;
}

export async function fullLengthBlock(
  options: FullLengthBlockOptions
): Promise<{ info: Json; output: string | null }> {
  const { source, tailVideo, tailDuration, cleanStart, verdict, destination, base } = options;
  const { fullDecode, progress } = options;
  if (!verdict) {
    return {
      info: {
        skipped:
          "no duplication map beside the input, so the copy window that would fill the opening is unknown",
      },
      output: null,
    };
  }
  const plan = planFullLength(cleanStart, tailDuration, verdict);
  if (!plan) {
    return { info: { skipped: "the damaged prefix has no matched copy in this file" }, output: null };
  }

  const target = path.join(destination, `${base}${FULL_LENGTH_SUFFIX}`);
  notify(
    progress,
    `Building the full-length rebuild: ${plan.duration.toFixed(1)} s of copied footage, then the clean tail, then the original audio…`
  );
  try {
    const info = await rebuildFullLength(source, tailVideo, plan, target, fullDecode, progress);
    return { info, output: target };
  } catch (error) {
    if (fs.existsSync(target)) fs.rmSync(target, { force: true });
    const message = error instanceof Error ? error.message : String(error);
    return { info: { error: message }, output: null };
  }
}
