// Shared shapes for the recovery engine. The field names match the JSON that
// the Python engine produced, so existing reports and the renderer keep working.

export const TOOL = "nvidia-fix";
export const VERSION = "1.2.0";

export const SEEK_OFFSET = 0.005;
export const CANDIDATE_RUN = 120;
export const MIN_RUN = 30;
export const DECODE_VALIDATE_SECONDS = 2;
export const SUPPORTED_VIDEO_CODECS = new Set(["h264"]);
export const SUPPORTED_SUFFIXES = new Set([".mp4", ".mov", ".m4v"]);
export const FULL_LENGTH_SUFFIX = ".full-length.mp4";
export const MIN_FULL_LENGTH_SECONDS = 1.0;
export const DUPLICATION_MAP_NAME = "duplication_dense.json";

export const CAVEAT =
  "Only the footage from clean_start onward is recoverable. Earlier video was " +
  "overwritten in place by the recorder and cannot be reconstructed from this " +
  "file. Audio before clean_start is exported separately.";

/** The caveat with the measured boundary filled in, for reports and the UI. */
export function caveatFor(cleanStartSeconds: number): string {
  const at = `${cleanStartSeconds.toFixed(2)} s`;
  return (
    `Only the footage from ${at} onward is recoverable. The first ${at} was ` +
    "overwritten in place by the recorder and cannot be reconstructed from this " +
    `file. Its audio up to ${at} is exported separately.`
  );
}

export const FULL_LENGTH_CAVEAT =
  "This is a rebuild, not the original recording. The opening shows footage the " +
  "recorder wrote over the head - real frames from later in the same session - " +
  "so it repeats material you also see near the end. The audio is the original " +
  "track for the whole length.";

export interface Sample {
  index: number;
  pts: number;
  dts: number;
  size: number;
  pos: number;
  flags: string;
  valid: boolean;
  nalType: number;
}

export interface VideoStreamInfo {
  codec_name: string;
  profile?: string | null;
  width: number;
  height: number;
  avg_frame_rate?: string | null;
  duration: number;
}

export interface AudioStreamInfo {
  codec_name: string;
  channels?: number | null;
  sample_rate?: string | null;
}

export interface MediaInfo {
  container: string | null;
  duration: number;
  video: VideoStreamInfo;
  audio: AudioStreamInfo | null;
}

export interface Analysis {
  path: string;
  media: MediaInfo;
  samples: Sample[];
  candidates: Sample[];
  badSamples: number;
  firstBad: Sample | null;
  lastBad: Sample | null;
  cleanRun: number;
  warning: string;
}

export interface DecodeCheck {
  errors: string[];
  warnings: string[];
  unclassified: string[];
  returncode: number;
  ok: boolean;
}

export interface DuplicationVerdict {
  damagedSeconds: number;
  duplicatedSeconds: number;
  destroyedSeconds: number;
  scanBlocks: number;
  matchedBlocks: number;
  firstMatch: [number, number] | null;
  lastMatch: [number, number] | null;
  mapPath: string | null;
}

export interface FullLengthPlan {
  startInTail: number;
  duration: number;
  needed: number;
  available: number;
  timelineStart: number;
  timelineEnd: number;
}

export type ProgressCallback = (message: string) => void;

export type Json = Record<string, unknown>;

export function round6(value: number): number {
  return Math.round(value * 1e6) / 1e6;
}

export function round(value: number, digits: number): number {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

export function toFloat(value: unknown, fallback = 0): number {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}
