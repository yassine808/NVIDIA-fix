/** Base error with a message suitable for CLI/UI display. */
export class NvidiaFixError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "NvidiaFixError";
  }
}

export class UnsupportedMediaError extends NvidiaFixError {
  constructor(message: string) {
    super(message);
    this.name = "UnsupportedMediaError";
  }
}

export class NoCleanKeyframeError extends NvidiaFixError {
  constructor(message: string) {
    super(message);
    this.name = "NoCleanKeyframeError";
  }
}

export class ProcessingError extends NvidiaFixError {
  constructor(message: string) {
    super(message);
    this.name = "ProcessingError";
  }
}
