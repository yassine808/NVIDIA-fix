// Cutting, packet-level verification and decode classification.

import { createHash } from "node:crypto";
import * as fs from "node:fs";
import * as path from "node:path";

import { probePackets } from "./probe";
import { FFMPEG, run } from "./tools";
import {
  DecodeCheck,
  Json,
  SEEK_OFFSET,
  Sample,
  round6,
} from "./types";

const MUXER_WARNING_MARKERS = ["non monotonically increasing dts", "non-monotonous dts"];

const DECODER_ERROR_MARKERS = [
  "error while decoding",
  "corrupt decoded frame",
  "invalid nal unit",
  "no frame!",
  "non-existing pps",
  "non-existing sps",
  "illegal short term buffer state",
  "illegal reordering_of_pic_nums_idc",
  "decode_slice_header error",
  "error splitting the input",
  "invalid data found when processing input",
  "packet corrupt",
  "header missing",
  "concealing",
  "frame num change",
];

export function classifyStderr(lines: string[]): DecodeCheck {
  const errors: string[] = [];
  const warnings: string[] = [];
  const unclassified: string[] = [];
  for (const line of lines) {
    const low = line.toLowerCase();
    if (MUXER_WARNING_MARKERS.some((marker) => low.includes(marker))) warnings.push(line);
    else if (DECODER_ERROR_MARKERS.some((marker) => low.includes(marker))) errors.push(line);
    else unclassified.push(line);
  }
  return { errors, warnings, unclassified, returncode: 0, ok: errors.length === 0 };
}

export async function decodeCheck(
  target: string,
  seconds?: number,
  timeoutMs = 1_800_000
): Promise<DecodeCheck> {
  const cmd = [FFMPEG, "-hide_banner", "-v", "error", "-nostdin", "-i", target];
  if (seconds !== undefined) cmd.push("-t", seconds.toFixed(3));
  cmd.push("-map", "0:v:0", "-f", "null", "-");

  const result = await run(cmd, { check: false, timeoutMs, lowPriority: true });
  const lines = result.stderr
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  const check = classifyStderr(lines);
  check.returncode = result.code ?? 0;
  check.ok = check.returncode === 0 && check.errors.length === 0;
  if (result.code !== 0 && lines.length === 0) {
    check.errors.push(`ffmpeg exited with ${result.code}`);
  }
  return check;
}

export async function cutTail(
  source: string,
  candidate: Sample,
  target: string,
  timeoutMs = 1_800_000
): Promise<void> {
  fs.mkdirSync(path.dirname(target), { recursive: true });
  const seek = candidate.pts + SEEK_OFFSET;
  const cmd = [
    FFMPEG,
    "-hide_banner",
    "-v",
    "error",
    "-nostdin",
    "-y",
    "-ss",
    seek.toFixed(6),
    "-i",
    source,
    "-map",
    "0:v:0",
    "-map",
    "0:a:0?",
    "-c",
    "copy",
    "-avoid_negative_ts",
    "make_zero",
    "-movflags",
    "+faststart",
    target,
  ];
  await run(cmd, { timeoutMs, lowPriority: true });
}

export async function verifyFirstPacket(
  source: string,
  candidate: Sample,
  output: string
): Promise<Json> {
  const packets = await probePackets(output);
  const first = packets[0];
  if (first.size !== candidate.size) {
    return {
      ok: false,
      reason: `first output packet is ${first.size} bytes, expected ${candidate.size} (seek landed on a different sample)`,
    };
  }

  const sourceFd = fs.openSync(source, "r");
  const sourcePayload = Buffer.alloc(candidate.size);
  let sourceRead: number;
  try {
    sourceRead = fs.readSync(sourceFd, sourcePayload, 0, candidate.size, candidate.pos);
  } finally {
    fs.closeSync(sourceFd);
  }

  const outputFd = fs.openSync(output, "r");
  const outputPayload = Buffer.alloc(first.size);
  let outputRead: number;
  try {
    outputRead = fs.readSync(outputFd, outputPayload, 0, first.size, first.pos);
  } finally {
    fs.closeSync(outputFd);
  }

  if (sourceRead !== candidate.size || outputRead !== first.size || !sourcePayload.equals(outputPayload)) {
    return { ok: false, reason: "first output packet payload differs from source sample" };
  }

  const digest = createHash("sha256").update(sourcePayload).digest("hex");
  return {
    ok: true,
    first_packet_sha256: digest,
    source_sample_sha256: digest,
    output_packets: packets.length,
    first_packet_pts: round6(first.pts),
  };
}

export async function exportEarlyAudio(
  source: string,
  boundary: number,
  target: string,
  timeoutMs = 1_800_000
): Promise<void> {
  const cmd = [
    FFMPEG,
    "-hide_banner",
    "-v",
    "error",
    "-nostdin",
    "-y",
    "-i",
    source,
    "-t",
    boundary.toFixed(6),
    "-map",
    "0:a:0",
    "-vn",
    "-c",
    "copy",
    target,
  ];
  await run(cmd, { timeoutMs, lowPriority: true });
}
