// JSON-lines bridge between the Electron app and the recovery engine.
//
//   node dist/engine/bridge.js --path <video> [--full-decode] [--full-length]
//
// Every line on stdout is one JSON object:
//   {"event":"progress","message":"..."}
//   {"event":"result","result":{...}}
//   {"event":"error","message":"..."}

import * as path from "node:path";

import { NvidiaFixError } from "./errors";
import { process as recover } from "./process";

function emit(payload: Record<string, unknown>): void {
  process.stdout.write(`${JSON.stringify(payload)}\n`);
}

function arg(name: string): string | undefined {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : undefined;
}

async function main(): Promise<number> {
  const source = arg("--path");
  if (!source) {
    emit({ event: "error", message: "bridge needs --path <video>" });
    return 2;
  }

  try {
    const result = await recover(source, {
      outDir: null, // write beside the input
      fullDecode: process.argv.includes("--full-decode"),
      fullLength: process.argv.includes("--full-length"),
      progress: (message) => emit({ event: "progress", message }),
    });
    const resolved = path.resolve(source);
    result.original_name = path.basename(resolved);
    result.original_path = resolved;
    result.output_dir = path.dirname(resolved);
    emit({ event: "result", result });
    return 0;
  } catch (error) {
    if (error instanceof NvidiaFixError) {
      emit({ event: "error", message: error.message });
      return 2;
    }
    emit({
      event: "error",
      message: `${error instanceof Error ? error.name : "Error"}: ${
        error instanceof Error ? error.message : String(error)
      }`,
    });
    return 1;
  }
}

main()
  .then((code) => process.exit(code))
  .catch((error) => {
    emit({ event: "error", message: String(error) });
    process.exit(1);
  });
