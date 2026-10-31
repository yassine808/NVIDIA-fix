// The recovery workflow: analyze, cut, verify, export audio, report.

import * as fs from "node:fs";
import * as path from "node:path";

import { analyze, analysisToDict, isHealthy } from "./analyze";
import { loadDuplicationVerdict, verdictToDict } from "./duplication";
import { NvidiaFixError, NoCleanKeyframeError, ProcessingError } from "./errors";
import { probeDuration, probeMedia } from "./probe";
import { fullLengthBlock } from "./rebuild";
import { cutTail, decodeCheck, exportEarlyAudio, verifyFirstPacket } from "./verify";
import {
  Analysis,
  CAVEAT,
  DECODE_VALIDATE_SECONDS,
  DecodeCheck,
  DuplicationVerdict,
  FULL_LENGTH_SUFFIX,
  Json,
  ProgressCallback,
  Sample,
  round6,
  toFloat,
} from "./types";

export interface ProcessOptions {
  outDir?: string | null;
  fullDecode?: boolean;
  progress?: ProgressCallback | null;
  fullLength?: boolean;
}

function notify(progress: ProgressCallback | null | undefined, message: string): void {
  if (!progress) return;
  try {
    progress(message);
  } catch {
    // A UI callback must never break recovery.
  }
}

function uniqueBase(outDir: string, stem: string, audioExt: string): string {
  let base = `${stem}.clean`;
  let index = 1;
  const taken = (candidate: string): boolean =>
    [".mp4", `.audio${audioExt}`, ".report.json", FULL_LENGTH_SUFFIX].some((ext) =>
      fs.existsSync(path.join(outDir, `${candidate}${ext}`))
    );
  while (taken(base)) {
    index += 1;
    base = `${stem}.clean-${index}`;
  }
  return base;
}

export async function process(
  input: string,
  options: ProcessOptions = {}
): Promise<Json> {
  const { outDir = null, fullDecode = true, progress = null, fullLength = false } = options;
  const source = path.resolve(input);
  notify(progress, "Reading the container and scanning every video sample…");
  const analysis = await analyze(source);
  const analysisDoc = analysisToDict(analysis);

  if (isHealthy(analysis)) {
    notify(progress, "No corruption detected. The file is already intact.");
    return {
      ...analysisDoc,
      status: "healthy",
      message: "No corruption detected. This file is already intact.",
      recovery: null,
      paths: null,
    };
  }

  if (analysis.candidates.length === 0) {
    throw new NoCleanKeyframeError(
      "No clean keyframe was found after the last damaged sample. The corruption may extend to the end of the file, so no clean tail can be recovered."
    );
  }

  notify(
    progress,
    `Found ${analysis.badSamples.toLocaleString("en-US")} damaged samples. ` +
      `First clean keyframe: ${analysis.candidates[0].pts.toFixed(3)} s.`
  );

  const destination = outDir ? path.resolve(outDir) : path.dirname(source);
  fs.mkdirSync(destination, { recursive: true });

  const audioCodec = analysis.media.audio?.codec_name ?? "";
  const audioExt = audioCodec === "aac" ? ".m4a" : ".mka";
  const base = uniqueBase(destination, path.basename(source, path.extname(source)), audioExt);
  const videoOut = path.join(destination, `${base}.mp4`);
  const audioOut = path.join(destination, `${base}.audio${audioExt}`);
  const reportOut = path.join(destination, `${base}.report.json`);

  let accepted: Sample | null = null;
  let verify: Json = {};
  const attempts: Json[] = [];

  for (let index = 0; index < analysis.candidates.length; index += 1) {
    const candidate = analysis.candidates[index];
    const attempt = index + 1;
    const temp = path.join(destination, `${base}.try${attempt}.part.mp4`);
    try {
      notify(
        progress,
        `Cutting the clean tail from ${candidate.pts.toFixed(3)} s ` +
          `(candidate ${attempt} of ${analysis.candidates.length})…`
      );
      await cutTail(source, candidate, temp);
      notify(progress, "Verifying that the cut starts on the exact source packet…");
      const check = await verifyFirstPacket(source, candidate, temp);
      if (!check.ok) {
        attempts.push({ seconds: round6(candidate.pts), error: check.reason });
        continue;
      }
      notify(progress, "Checking the first seconds of the recovered video…");
      const startCheck = await decodeCheck(temp, DECODE_VALIDATE_SECONDS);
      if (!startCheck.ok) {
        const blocking =
          startCheck.errors.length > 0
            ? startCheck.errors
            : startCheck.unclassified.length > 0
              ? startCheck.unclassified
              : [`ffmpeg exited with ${startCheck.returncode}`];
        attempts.push({
          seconds: round6(candidate.pts),
          error: "decode errors at start of cut",
          details: blocking.slice(0, 5),
        });
        continue;
      }
      fs.renameSync(temp, videoOut);
      accepted = candidate;
      verify = check;
      break;
    } finally {
      if (fs.existsSync(temp)) fs.rmSync(temp, { force: true });
    }
  }

  if (!accepted) {
    throw new ProcessingError(
      `Could not produce a clean tail. Every clean keyframe candidate failed verification: ${JSON.stringify(attempts.slice(0, 3))}`
    );
  }

  let audioInfo: Json | null = null;
  if (analysis.media.audio) {
    try {
      notify(progress, "Exporting the audio from before the cut…");
      await exportEarlyAudio(source, accepted.pts, audioOut);
      audioInfo = {
        name: path.basename(audioOut),
        size_bytes: fs.statSync(audioOut).size,
        duration_seconds: round6(await probeDuration(audioOut)),
      };
    } catch (error) {
      if (!(error instanceof NvidiaFixError)) throw error;
      if (fs.existsSync(audioOut)) fs.rmSync(audioOut, { force: true });
      audioInfo = null;
    }
  }

  let decodeResult: DecodeCheck = {
    errors: [],
    warnings: [],
    unclassified: [],
    returncode: 0,
    ok: true,
  };
  if (fullDecode) {
    notify(progress, "Decoding the recovered video to verify it…");
    decodeResult = await decodeCheck(videoOut);
  }
  const decodeErrors = decodeResult.errors;

  let duration = await probeDuration(videoOut);
  try {
    const outputMedia = await probeMedia(videoOut);
    duration = toFloat(outputMedia.video.duration, duration);
  } catch {
    // keep the format-level duration
  }

  let duplication: Json | null = null;
  let verdict: DuplicationVerdict | null = null;
  if (analysis.lastBad) {
    try {
      verdict = loadDuplicationVerdict(source, analysis.lastBad.pts);
      duplication = verdictToDict(verdict);
    } catch (error) {
      duplication = { unavailable: error instanceof Error ? error.message : String(error) };
    }
  }

  let fullLengthInfo: Json | null = null;
  let fullLengthOut: string | null = null;
  if (fullLength) {
    const block = await fullLengthBlock(
      source,
      videoOut,
      duration,
      accepted.pts,
      verdict,
      destination,
      base,
      fullDecode,
      progress
    );
    fullLengthInfo = block.info;
    fullLengthOut = block.output;
  }

  const report: Json = {
    ...analysisDoc,
    status: decodeResult.ok && decodeResult.unclassified.length === 0 ? "success" : "success_with_warnings",
    recovery: {
      clean_start_seconds: round6(accepted.pts),
      video: {
        name: path.basename(videoOut),
        size_bytes: fs.statSync(videoOut).size,
        duration_seconds: round6(duration),
        packets: Math.trunc(toFloat(verify.output_packets, 0)),
        first_packet_sha256: verify.first_packet_sha256 ?? null,
        source_sample_sha256: verify.source_sample_sha256 ?? null,
        decode_errors: decodeErrors.length,
      },
      audio: audioInfo,
      decode_error_sample: decodeErrors.slice(0, 20),
      muxer_warnings: decodeResult.warnings.length,
      muxer_warning_sample: decodeResult.warnings.slice(0, 3),
      unclassified_output: decodeResult.unclassified.slice(0, 5),
      full_decode_returncode: decodeResult.returncode,
      attempts,
    },
    duplication,
    full_length: fullLengthInfo,
    caveat: CAVEAT,
  };

  if (decodeErrors.length > 0) {
    report.warning =
      "The tail was recovered and its first packets verify, but a full decode reported errors. Inspect the decode_error_sample list.";
  } else if (decodeResult.unclassified.length > 0) {
    report.warning =
      "The full decode produced output this tool could not classify. Inspect recovery.unclassified_output.";
  }
  if (fullLengthInfo && fullLengthInfo.decode_errors) {
    report.warning =
      "The clean tail verifies, but the full-length rebuild reported decoder errors. Inspect full_length.decode_error_sample.";
  }

  notify(progress, "Writing the recovery report…");
  fs.writeFileSync(reportOut, JSON.stringify(report, null, 2), "utf-8");
  return {
    ...report,
    paths: {
      video: videoOut,
      audio: audioInfo ? audioOut : null,
      full_length: fullLengthOut,
      report: reportOut,
    },
  };
}

export type { Analysis };
