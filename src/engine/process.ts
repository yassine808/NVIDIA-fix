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
  caveatFor,
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

export type { Analysis } from "./types";

export interface ProcessOptions {
  outDir?: string | null;
  fullDecode?: boolean;
  progress?: ProgressCallback | null;
  fullLength?: boolean;
}

interface CleanTail {
  accepted: Sample;
  verify: Json;
  attempts: Json[];
}

type CandidateAttempt =
  | { ok: true; verify: Json }
  | { ok: false; failure: Json };

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

function emptyDecodeCheck(): DecodeCheck {
  return {
    errors: [],
    warnings: [],
    unclassified: [],
    returncode: 0,
    ok: true,
  };
}

function blockingOutput(check: DecodeCheck): string[] {
  if (check.errors.length > 0) return check.errors;
  if (check.unclassified.length > 0) return check.unclassified;
  return [`ffmpeg exited with ${check.returncode}`];
}

async function tryCandidate(
  source: string,
  candidate: Sample,
  attempt: number,
  total: number,
  temp: string,
  videoOut: string,
  progress: ProgressCallback | null
): Promise<CandidateAttempt> {
  try {
    notify(
      progress,
      `Cutting the clean tail from ${candidate.pts.toFixed(3)} s ` +
        `(candidate ${attempt} of ${total})…`
    );
    await cutTail(source, candidate, temp);
    notify(progress, "Verifying that the cut starts on the exact source packet…");
    const check = await verifyFirstPacket(source, candidate, temp);
    if (!check.ok) {
      return { ok: false, failure: { seconds: round6(candidate.pts), error: check.reason } };
    }
    notify(progress, "Checking the first seconds of the recovered video…");
    const startCheck = await decodeCheck(temp, DECODE_VALIDATE_SECONDS);
    if (!startCheck.ok) {
      return {
        ok: false,
        failure: {
          seconds: round6(candidate.pts),
          error: "decode errors at start of cut",
          details: blockingOutput(startCheck).slice(0, 5),
        },
      };
    }
    fs.renameSync(temp, videoOut);
    return { ok: true, verify: check };
  } finally {
    if (fs.existsSync(temp)) fs.rmSync(temp, { force: true });
  }
}

/** Walk the clean keyframe candidates until one cut verifies end to end. */
async function acceptCleanTail(
  source: string,
  analysis: Analysis,
  destination: string,
  base: string,
  videoOut: string,
  progress: ProgressCallback | null
): Promise<CleanTail> {
  const attempts: Json[] = [];
  for (let index = 0; index < analysis.candidates.length; index += 1) {
    const candidate = analysis.candidates[index];
    const attempt = index + 1;
    const temp = path.join(destination, `${base}.try${attempt}.part.mp4`);
    const result = await tryCandidate(
      source,
      candidate,
      attempt,
      analysis.candidates.length,
      temp,
      videoOut,
      progress
    );
    if (!result.ok) {
      attempts.push(result.failure);
      continue;
    }
    return { accepted: candidate, verify: result.verify, attempts };
  }

  throw new ProcessingError(
    `Could not produce a clean tail. Every clean keyframe candidate failed verification: ${JSON.stringify(attempts.slice(0, 3))}`
  );
}

async function exportAudio(
  source: string,
  cutPoint: number,
  audioOut: string,
  progress: ProgressCallback | null
): Promise<Json | null> {
  try {
    notify(progress, "Exporting the audio from before the cut…");
    await exportEarlyAudio(source, cutPoint, audioOut);
    return {
      name: path.basename(audioOut),
      size_bytes: fs.statSync(audioOut).size,
      duration_seconds: round6(await probeDuration(audioOut)),
    };
  } catch (error) {
    if (!(error instanceof NvidiaFixError)) throw error;
    if (fs.existsSync(audioOut)) fs.rmSync(audioOut, { force: true });
    return null;
  }
}

async function verifyVideo(
  videoOut: string,
  fullDecode: boolean,
  progress: ProgressCallback | null
): Promise<DecodeCheck> {
  if (!fullDecode) return emptyDecodeCheck();
  notify(progress, "Decoding the recovered video to verify it…");
  return decodeCheck(videoOut);
}

async function measureDuration(videoOut: string): Promise<number> {
  let duration = await probeDuration(videoOut);
  try {
    const outputMedia = await probeMedia(videoOut);
    duration = toFloat(outputMedia.video.duration, duration);
  } catch {
    // keep the format-level duration
  }
  return duration;
}

function loadDuplication(
  source: string,
  lastBad: Sample | null
): { duplication: Json | null; verdict: DuplicationVerdict | null } {
  if (!lastBad) return { duplication: null, verdict: null };
  try {
    const verdict = loadDuplicationVerdict(source, lastBad.pts);
    return { duplication: verdictToDict(verdict), verdict };
  } catch (error) {
    return {
      duplication: { unavailable: error instanceof Error ? error.message : String(error) },
      verdict: null,
    };
  }
}

interface FullLengthRequest {
  enabled: boolean;
  source: string;
  videoOut: string;
  duration: number;
  accepted: Sample;
  verdict: DuplicationVerdict | null;
  destination: string;
  base: string;
  fullDecode: boolean;
  progress: ProgressCallback | null;
}

async function buildFullLength(
  request: FullLengthRequest
): Promise<{ info: Json | null; output: string | null }> {
  if (!request.enabled) return { info: null, output: null };
  const block = await fullLengthBlock({
    source: request.source,
    tailVideo: request.videoOut,
    tailDuration: request.duration,
    cleanStart: request.accepted.pts,
    verdict: request.verdict,
    destination: request.destination,
    base: request.base,
    fullDecode: request.fullDecode,
    progress: request.progress,
  });
  return { info: block.info, output: block.output };
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

  const { accepted, verify, attempts } = await acceptCleanTail(
    source,
    analysis,
    destination,
    base,
    videoOut,
    progress
  );

  const audioInfo = analysis.media.audio
    ? await exportAudio(source, accepted.pts, audioOut, progress)
    : null;

  const decodeResult = await verifyVideo(videoOut, fullDecode, progress);
  const decodeErrors = decodeResult.errors;
  const duration = await measureDuration(videoOut);
  const { duplication, verdict } = loadDuplication(source, analysis.lastBad);
  const fullLengthBlockResult = await buildFullLength({
    enabled: fullLength,
    source,
    videoOut,
    duration,
    accepted,
    verdict,
    destination,
    base,
    fullDecode,
    progress,
  });
  const fullLengthInfo = fullLengthBlockResult.info;

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
    caveat: caveatFor(accepted.pts),
  };

  if (decodeErrors.length > 0) {
    report.warning =
      "The tail was recovered and its first packets verify, but a full decode reported errors. Inspect the decode_error_sample list.";
  } else if (decodeResult.unclassified.length > 0) {
    report.warning =
      "The full decode produced output this tool could not classify. Inspect recovery.unclassified_output.";
  }
  if (fullLengthInfo?.decode_errors) {
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
      full_length: fullLengthBlockResult.output,
      report: reportOut,
    },
  };
}
