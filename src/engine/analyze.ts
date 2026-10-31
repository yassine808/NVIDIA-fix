// Corruption detection: every video packet is inspected as an AVCC H.264 sample.

import * as fs from "node:fs";
import * as path from "node:path";

import { NvidiaFixError, UnsupportedMediaError } from "./errors";
import { probeMedia, probePackets } from "./probe";
import { ensureTools } from "./tools";
import {
  Analysis,
  CANDIDATE_RUN,
  CAVEAT,
  caveatFor,
  Json,
  MIN_RUN,
  Sample,
  SUPPORTED_SUFFIXES,
  TOOL,
  VERSION,
  round6,
} from "./types";

/** Every NAL type if the buffer is well-formed AVCC, else null. */
export function avccNalTypes(data: Buffer): number[] | null {
  let offset = 0;
  const total = data.length;
  const types: number[] = [];
  while (offset < total) {
    if (offset + 4 > total) return null;
    const length = data.readUInt32BE(offset);
    if (length <= 0 || offset + 4 + length > total) return null;
    const header = data[offset + 4];
    if (header & 0x80) return null; // forbidden_zero_bit
    const nalType = header & 0x1f;
    if (nalType < 1 || nalType > 12) return null;
    types.push(nalType);
    offset += 4 + length;
  }
  return offset === total && types.length > 0 ? types : null;
}

/** Set sample.valid / sample.nalType by inspecting the sample payload. */
export function checkSample(fd: number, sample: Sample): void {
  if (sample.size < 5 || sample.pos < 0) {
    sample.valid = false;
    sample.nalType = -1;
    return;
  }

  const header = Buffer.alloc(5);
  const read = fs.readSync(fd, header, 0, 5, sample.pos);
  if (read < 5) {
    sample.valid = false;
    sample.nalType = -1;
    return;
  }

  const outer = header.readUInt32BE(0);
  const nal = header[4];
  const nalType = nal & 0x1f;
  sample.nalType = nalType;

  // Fast path: the overwhelming majority of samples hold exactly one NAL.
  if (outer === sample.size - 4 && !(nal & 0x80) && nalType >= 1 && nalType <= 12) {
    sample.valid = true;
    return;
  }

  // Slow path: multi-NAL samples, or corruption. Validate every NAL unit.
  const data = Buffer.alloc(sample.size);
  const filled = fs.readSync(fd, data, 0, sample.size, sample.pos);
  const types = filled === sample.size ? avccNalTypes(data) : null;
  sample.valid = types !== null;
  if (types) {
    sample.nalType = types.includes(5) ? 5 : types[0];
  }
}

export function isHealthy(analysis: Analysis): boolean {
  return analysis.badSamples === 0;
}

export function analysisStatus(analysis: Analysis): string {
  if (isHealthy(analysis)) return "healthy";
  if (analysis.candidates.length > 0) return "recoverable";
  return "unrecoverable";
}

export function analysisToDict(analysis: Analysis): Json {
  const video = analysis.media.video;
  const audio = analysis.media.audio;
  const boundary = analysis.candidates[0] ?? null;
  let warning: string | null = null;
  if (!isHealthy(analysis)) {
    warning = caveatFor(boundary ? boundary.pts : 0);
  }
  return {
    tool: TOOL,
    version: VERSION,
    status: analysisStatus(analysis),
    input: {
      name: path.basename(analysis.path),
      size_bytes: fs.statSync(analysis.path).size,
    },
    media: {
      container: analysis.media.container,
      duration_seconds: analysis.media.duration,
      video_codec: video.codec_name,
      width: video.width,
      height: video.height,
      audio_codec: audio ? audio.codec_name : null,
    },
    corruption: {
      total_video_samples: analysis.samples.length,
      bad_samples: analysis.badSamples,
      first_bad_seconds: analysis.firstBad ? round6(analysis.firstBad.pts) : null,
      last_bad_seconds: analysis.lastBad ? round6(analysis.lastBad.pts) : null,
      last_bad_index: analysis.lastBad ? analysis.lastBad.index : null,
      clean_start_seconds: boundary ? round6(boundary.pts) : null,
      clean_start_index: boundary ? boundary.index : null,
      clean_run_samples: analysis.cleanRun,
    },
    candidates: analysis.candidates.slice(0, 10).map((candidate) => ({
      seconds: round6(candidate.pts),
      index: candidate.index,
      size: candidate.size,
      flags: candidate.flags,
      nal_type: candidate.nalType,
    })),
    warning,
  };
}

export async function analyze(input: string): Promise<Analysis> {
  await ensureTools();
  const source = path.resolve(input);
  let stat: fs.Stats;
  try {
    stat = fs.statSync(source);
  } catch {
    throw new NvidiaFixError(`Input file not found: ${source}`);
  }
  if (!stat.isFile()) throw new NvidiaFixError(`Input file not found: ${source}`);

  const suffix = path.extname(source).toLowerCase();
  if (!SUPPORTED_SUFFIXES.has(suffix)) {
    throw new UnsupportedMediaError(
      `Unsupported file extension: ${suffix || "(none)"}. Supported: ${[...SUPPORTED_SUFFIXES].sort((a, b) => a.localeCompare(b)).join(", ")}`
    );
  }

  const media = await probeMedia(source);
  const samples = await probePackets(source);
  openSamples(source, samples);

  const bad = samples.filter((sample) => !sample.valid);
  if (bad.length === 0) {
    return {
      path: source,
      media,
      samples,
      candidates: [],
      badSamples: 0,
      firstBad: null,
      lastBad: null,
      cleanRun: 0,
      warning: CAVEAT,
    };
  }

  const lastBad = bad.at(-1);
  if (!lastBad) {
    throw new NvidiaFixError("No damaged sample was found while scanning the file.");
  }
  const { candidates, cleanRun } = findBoundaryCandidates(samples, lastBad.index + 1);

  return {
    path: source,
    media,
    samples,
    candidates,
    badSamples: bad.length,
    firstBad: bad[0],
    lastBad,
    cleanRun,
    warning: CAVEAT,
  };
}

function openSamples(source: string, samples: Sample[]): void {
  const fd = fs.openSync(source, "r");
  try {
    for (const sample of samples) checkSample(fd, sample);
  } finally {
    fs.closeSync(fd);
  }
}

function isCandidateStart(sample: Sample): boolean {
  return sample.valid && (sample.flags.includes("K") || sample.nalType === 5);
}

/** True when the next MIN_RUN samples (up to CANDIDATE_RUN) are all valid. */
function hasCleanRun(samples: Sample[], start: number): boolean {
  const run = samples.slice(start, start + CANDIDATE_RUN);
  const need = Math.min(MIN_RUN, samples.length - start);
  return need >= 5 && run.length >= need && run.slice(0, need).every((item) => item.valid);
}

function countCleanRun(samples: Sample[], start: number): number {
  const run = samples.slice(start, start + CANDIDATE_RUN);
  let cleanRun = 0;
  for (const item of run) {
    if (!item.valid) break;
    cleanRun += 1;
  }
  return cleanRun;
}

function findBoundaryCandidates(
  samples: Sample[],
  start: number
): { candidates: Sample[]; cleanRun: number } {
  const candidates: Sample[] = [];
  let cleanRun = 0;
  for (let i = start; i < samples.length; i += 1) {
    const sample = samples[i];
    if (!isCandidateStart(sample) || !hasCleanRun(samples, i)) continue;
    candidates.push(sample);
    if (cleanRun === 0) cleanRun = countCleanRun(samples, i);
    if (candidates.length >= 20) break;
  }
  return { candidates, cleanRun };
}
