// How much of the unreadable prefix is a copy of later bytes, and how much is
// gone for good. The recorder overwrote the head with a later stretch of the
// same stream, so most of those bytes exist again further on.

import * as fs from "node:fs";
import * as path from "node:path";

import { analyze, analysisStatus, isHealthy } from "./analyze";
import { NvidiaFixError } from "./errors";
import { probeDuration } from "./probe";
import {
  DUPLICATION_MAP_NAME,
  DuplicationVerdict,
  Json,
  TOOL,
  VERSION,
  round,
  round6,
  toFloat,
} from "./types";

interface MapRow {
  t?: unknown;
  src_t?: unknown;
  matched?: unknown;
}

export function verdictToDict(verdict: DuplicationVerdict): Json {
  const matchedFraction = verdict.scanBlocks > 0 ? verdict.matchedBlocks / verdict.scanBlocks : 0;
  const duplicatedFraction =
    verdict.damagedSeconds > 0 ? verdict.duplicatedSeconds / verdict.damagedSeconds : 0;
  return {
    damaged_seconds: round6(verdict.damagedSeconds),
    duplicated_seconds: round6(verdict.duplicatedSeconds),
    destroyed_seconds: round6(verdict.destroyedSeconds),
    duplicated_fraction: round(duplicatedFraction, 4),
    scan_blocks: verdict.scanBlocks,
    matched_blocks: verdict.matchedBlocks,
    matched_fraction: round(matchedFraction, 4),
    first_match: verdict.firstMatch ? [...verdict.firstMatch] : null,
    last_match: verdict.lastMatch ? [...verdict.lastMatch] : null,
    map: verdict.mapPath,
  };
}

export function duplicationVerdict(
  rows: MapRow[],
  damagedSeconds: number,
  mapPath: string | null = null
): DuplicationVerdict {
  const timed = rows.filter((row) => row.t !== undefined && row.t !== null);
  if (timed.length === 0) {
    throw new NvidiaFixError(
      "The duplication map has no timed blocks; regenerate it with `python forensics/duplication_dense.py`."
    );
  }

  const starts = timed.map((row) => toFloat(row.t));
  const gaps = starts
    .slice(1)
    .map((value, index) => value - starts[index])
    .filter((gap) => gap > 0)
    .sort((a, b) => a - b);
  const tailSpan = gaps.length > 0 ? gaps[Math.floor(gaps.length / 2)] : 0;

  let duplicated = 0;
  let destroyed = 0;
  timed.forEach((row, index) => {
    const start = starts[index];
    const end = index + 1 < starts.length ? starts[index + 1] : start + tailSpan;
    const lo = start;
    const hi = Math.min(end, damagedSeconds);
    if (hi <= lo) return;
    if (row.matched) duplicated += hi - lo;
    else destroyed += hi - lo;
  });

  const matched = timed.filter((row) => row.matched);
  const first = matched.length > 0 ? ([toFloat(matched[0].t), toFloat(matched[0].src_t)] as [number, number]) : null;
  const lastRow = matched.at(-1);
  const last = lastRow ? ([toFloat(lastRow.t), toFloat(lastRow.src_t)] as [number, number]) : null;

  return {
    damagedSeconds,
    duplicatedSeconds: duplicated,
    destroyedSeconds: destroyed,
    scanBlocks: timed.length,
    matchedBlocks: matched.length,
    firstMatch: first,
    lastMatch: last,
    mapPath,
  };
}

export function loadDuplicationVerdict(
  source: string,
  damagedSeconds: number,
  mapPath?: string | null
): DuplicationVerdict {
  const target = mapPath ? path.resolve(mapPath) : path.join(path.dirname(source), DUPLICATION_MAP_NAME);
  if (!fs.existsSync(target)) {
    throw new NvidiaFixError(
      `No duplication map at ${target}. Generate it with:\n  PYTHONPATH=forensics python forensics/duplication_dense.py`
    );
  }
  const payload = JSON.parse(fs.readFileSync(target, "utf-8")) as { rows?: MapRow[] };
  return duplicationVerdict(payload.rows ?? [], damagedSeconds, target);
}

export async function explain(input: string, mapPath?: string | null): Promise<Json> {
  const analysis = await analyze(input);
  const result: Json = {
    tool: TOOL,
    version: VERSION,
    input: analysis.path,
  };

  if (isHealthy(analysis) || !analysis.lastBad) {
    return {
      ...result,
      status: "healthy",
      verdict: "No corruption: the file is intact.",
    };
  }

  const duration = await probeDuration(analysis.path);
  const damaged = analysis.lastBad.pts;
  const verdict = loadDuplicationVerdict(analysis.path, damaged, mapPath);
  const recoverable = Math.max(0, duration - damaged);

  return {
    ...result,
    status: analysisStatus(analysis),
    duplication: verdictToDict(verdict),
    timeline: {
      duration_seconds: round6(duration),
      damaged_seconds: round6(damaged),
      recoverable_seconds: round6(recoverable),
      recoverable_fraction: duration > 0 ? round(recoverable / duration, 4) : 0,
      unique_seconds: round6(Math.max(0, duration - verdict.duplicatedSeconds)),
    },
    verdict:
      `${verdict.duplicatedSeconds.toFixed(3)} s of the damaged prefix is a byte-shifted ` +
      `copy of later footage and ${verdict.destroyedSeconds.toFixed(3)} s exists nowhere ` +
      `in the file. Only ${recoverable.toFixed(3)} s of the ${duration.toFixed(3)} s timeline is ` +
      "playable; 100% needs a second source.",
  };
}
