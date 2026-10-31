export interface RecoveryRequest {
  path: string;
  fullDecode: boolean;
  fullLength?: boolean;
}

export interface OutputEntry {
  label: string;
  detail: string;
  path: string;
  name: string;
  sizeBytes: number | null;
  kind: "video" | "audio" | "report" | "full";
}

export interface CorruptionInfo {
  total_video_samples: number;
  bad_samples: number;
  first_bad_seconds: number | null;
  last_bad_seconds: number | null;
  clean_start_seconds: number | null;
  clean_start_index: number | null;
}

export interface RecoveryResult {
  status: string;
  message?: string;
  warning?: string;
  original_name?: string;
  original_path?: string;
  output_dir?: string;
  saved_note?: string;
  outputs?: OutputEntry[];
  paths?: {
    video: string | null;
    audio: string | null;
    full_length: string | null;
    report: string | null;
  };
  corruption?: CorruptionInfo;
  media?: {
    duration_seconds: number | null;
    video_codec: string | null;
    width: number | null;
    height: number | null;
    audio_codec: string | null;
  };
  recovery?: {
    clean_start_seconds: number;
    video: {
      name: string;
      size_bytes: number;
      duration_seconds: number;
      packets: number;
      first_packet_sha256: string | null;
      source_sample_sha256: string | null;
      decode_errors: number;
    };
    audio: { name: string; size_bytes: number; duration_seconds: number } | null;
    muxer_warnings: number;
  };
  [key: string]: unknown;
}

export interface AppInfo {
  version: string;
  engineVersion: string;
  runtime: string;
  samplePath: string | null;
}

export interface DesktopApi {
  info(): Promise<AppInfo>;
  pickVideo(): Promise<string | null>;
  pathForFile(file: File): string;
  recover(request: RecoveryRequest): Promise<RecoveryResult>;
  cancel(): Promise<boolean>;
  openPath(target: string): Promise<string>;
  showInFolder(target: string): Promise<void>;
  copyText(text: string): Promise<void>;
  onProgress(listener: (message: string) => void): () => void;
}
