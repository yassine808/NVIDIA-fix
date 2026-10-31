// ffprobe-based reading: media info and the exact video packet table.

import { UnsupportedMediaError } from "./errors";
import { ffprobeJson } from "./tools";
import {
  MediaInfo,
  SUPPORTED_VIDEO_CODECS,
  Sample,
  toFloat,
} from "./types";

interface Stream {
  codec_type?: string;
  codec_name?: string;
  profile?: string | null;
  width?: number;
  height?: number;
  avg_frame_rate?: string | null;
  duration?: string;
  channels?: number;
  sample_rate?: string;
  disposition?: { attached_pic?: number };
}

interface Packet {
  pts_time?: string;
  dts_time?: string;
  size?: string | number;
  pos?: string | number;
  flags?: string;
}

export async function probeMedia(target: string): Promise<MediaInfo> {
  const data = await ffprobeJson(["-show_format", "-show_streams", "-of", "json", target]);
  const streams = (data.streams as Stream[] | undefined) ?? [];
  const format = (data.format as Record<string, unknown> | undefined) ?? {};

  let video: Stream | undefined;
  let audio: Stream | undefined;
  for (const stream of streams) {
    if (stream.codec_type === "video" && !video) {
      if (stream.disposition?.attached_pic) continue;
      video = stream;
    } else if (stream.codec_type === "audio" && !audio) {
      audio = stream;
    }
  }

  if (!video) throw new UnsupportedMediaError("No video stream found in this file.");

  const codec = String(video.codec_name ?? "").toLowerCase();
  if (!SUPPORTED_VIDEO_CODECS.has(codec)) {
    const pretty = codec ? codec.toUpperCase() : "unknown";
    throw new UnsupportedMediaError(
      `Unsupported video codec: ${pretty}. This tool currently supports H.264 (AVC) MP4/MOV recordings only. HEVC is not supported yet.`
    );
  }

  const duration = toFloat(format.duration, toFloat(video.duration, 0));
  return {
    container: (format.format_name as string | undefined) ?? null,
    duration,
    video: {
      codec_name: codec,
      profile: video.profile ?? null,
      width: Math.trunc(toFloat(video.width, 0)),
      height: Math.trunc(toFloat(video.height, 0)),
      avg_frame_rate: video.avg_frame_rate ?? null,
      duration: toFloat(video.duration, duration),
    },
    audio: audio
      ? {
          codec_name: String(audio.codec_name ?? "").toLowerCase(),
          channels: audio.channels ?? null,
          sample_rate: audio.sample_rate ?? null,
        }
      : null,
  };
}

export async function probePackets(target: string, timeoutMs = 300_000): Promise<Sample[]> {
  const data = await ffprobeJson(
    [
      "-select_streams",
      "v:0",
      "-show_entries",
      "packet=pts_time,dts_time,size,pos,flags",
      "-of",
      "json",
      target,
    ],
    timeoutMs
  );

  const packets = (data.packets as Packet[] | undefined) ?? [];
  const samples: Sample[] = [];
  packets.forEach((packet, index) => {
    const pos = packet.pos;
    const size = packet.size;
    if (pos === undefined || pos === null || size === undefined || size === null) {
      throw new UnsupportedMediaError(
        "This file does not expose video packet byte offsets, which are needed to inspect the H.264 data. Remux it with `ffmpeg -i input.mp4 -c copy remuxed.mp4` and try again."
      );
    }
    const pts = packet.pts_time;
    const dts = packet.dts_time;
    if (pts === undefined && dts === undefined) {
      throw new UnsupportedMediaError("A video packet has no timestamp.");
    }
    samples.push({
      index,
      pts: toFloat(pts !== undefined ? pts : dts),
      dts: toFloat(dts !== undefined ? dts : pts),
      size: Math.trunc(toFloat(size)),
      pos: Math.trunc(toFloat(pos)),
      flags: String(packet.flags ?? ""),
      valid: false,
      nalType: -1,
    });
  });

  if (samples.length === 0) {
    throw new UnsupportedMediaError("No video packets found in this file.");
  }
  return samples;
}

export async function probeDuration(target: string): Promise<number> {
  const data = await ffprobeJson(["-show_entries", "format=duration", "-of", "json", target]);
  const format = (data.format as Record<string, unknown> | undefined) ?? {};
  return toFloat(format.duration, 0);
}
