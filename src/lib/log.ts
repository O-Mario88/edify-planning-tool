// Structured logging — single source for every log line in the app.
//
// Design goals:
//   1. One import (`log`) for both server and Edge. The shape stays
//      identical across runtimes; production swaps the writer.
//   2. JSON-line output in production, pretty-print in dev. No
//      consumer should `JSON.stringify` themselves.
//   3. Stable field names — `level`, `msg`, `ts`, `at`, optional
//      `requestId` / `userId` / `route` — so log aggregators can
//      slice without per-call parsing.
//   4. Edge-safe: uses only console + Date + JSON. No `pino`, no
//      Node streams, no Buffer.
//
// Why not `pino`? It pulls native dependencies that the Edge Runtime
// can't bundle. The Edge middleware logs from the request hot path.
// One unified writer beats two runtime-specific ones.

type Level = "debug" | "info" | "warn" | "error";

export type LogFields = Record<string, unknown>;

type LogPayload = {
  level: Level;
  msg: string;
  ts: number;        // unix ms
  at: string;        // ISO 8601 for human eyes
} & LogFields;

const LEVEL_RANK: Record<Level, number> = {
  debug: 10,
  info:  20,
  warn:  30,
  error: 40,
};

// Default threshold: info in production, debug in dev. Override with
// EDIFY_LOG_LEVEL=warn (or any level) at runtime.
const MIN_LEVEL: Level = (() => {
  const env = process.env.EDIFY_LOG_LEVEL?.toLowerCase() as Level | undefined;
  if (env && env in LEVEL_RANK) return env;
  return process.env.NODE_ENV === "production" ? "info" : "debug";
})();

const IS_PROD = process.env.NODE_ENV === "production";

function emit(level: Level, msg: string, fields?: LogFields): void {
  if (LEVEL_RANK[level] < LEVEL_RANK[MIN_LEVEL]) return;
  const now = Date.now();
  const payload: LogPayload = {
    level,
    msg,
    ts: now,
    at: new Date(now).toISOString(),
    ...fields,
  };

  // Production: single JSON line per event. Log shippers (Vector,
  // Fluentbit, Vercel Log Drains) prefer this format. Dev: a single
  // formatted line with the structured fields appended — readable in
  // a terminal without losing data.
  if (IS_PROD) {
     
    console.log(JSON.stringify(payload));
    return;
  }

  const head = `[${level.toUpperCase()}] ${msg}`;
  const tail = fields && Object.keys(fields).length > 0 ? `  ${JSON.stringify(fields)}` : "";
  // Route warn / error to the right console method so dev tools tint them.
  const writer =
    level === "error" ? console.error
    : level === "warn" ? console.warn
    : console.log;
   
  writer(head + tail);
}

// Public surface — what every call site uses.

export const log = {
  debug(msg: string, fields?: LogFields) { emit("debug", msg, fields); },
  info (msg: string, fields?: LogFields) { emit("info",  msg, fields); },
  warn (msg: string, fields?: LogFields) { emit("warn",  msg, fields); },
  error(msg: string, fields?: LogFields) { emit("error", msg, fields); },

  /**
   * Wrap an async handler with timing + level-aware logging. Logs an
   * `info` on success, an `error` with the thrown reason on failure,
   * preserving the original throw. Use for API route handlers:
   *
   *   export const POST = log.handler("api.auth.login", async (req) => {…});
   */
  handler<TReq extends Request, TRes>(
    name: string,
    fn: (req: TReq) => Promise<TRes>,
  ): (req: TReq) => Promise<TRes> {
    return async (req: TReq) => {
      const started = Date.now();
      try {
        const result = await fn(req);
        emit("info", "request.ok", {
          route: name,
          method: req.method,
          durationMs: Date.now() - started,
        });
        return result;
      } catch (err) {
        emit("error", "request.failed", {
          route: name,
          method: req.method,
          durationMs: Date.now() - started,
          error: err instanceof Error ? err.message : String(err),
          stack: err instanceof Error ? err.stack : undefined,
        });
        throw err;
      }
    };
  },
};

// ────────── Telemetry abstraction ──────────
//
// Counterpart to `log` for product-event tracking + exception capture.
// Defaults to a no-op so the app boots without configuration. Wire to
// Sentry / Datadog / PostHog by overriding the export in a single
// adapter file.

export type TelemetryEvent = {
  /** Snake-case event name, e.g. "fund_request.approved". */
  name: string;
  /** Arbitrary structured fields. Always JSON-serializable. */
  props?: Record<string, unknown>;
  /** Optional user identifier — distinct from PII. */
  userId?: string;
};

export interface Telemetry {
  track(event: TelemetryEvent): void;
  captureException(err: unknown, extra?: Record<string, unknown>): void;
}

class NoopTelemetry implements Telemetry {
  track(event: TelemetryEvent) {
    log.debug("telemetry.track", { event: event.name, ...event.props });
  }
  captureException(err: unknown, extra?: Record<string, unknown>) {
    log.error("telemetry.exception", {
      error: err instanceof Error ? err.message : String(err),
      stack: err instanceof Error ? err.stack : undefined,
      ...extra,
    });
  }
}

// Single mutable export — swap in production via `setTelemetry`.
let _impl: Telemetry = new NoopTelemetry();

export const telemetry: Telemetry = {
  track:            (e) => _impl.track(e),
  captureException: (err, extra) => _impl.captureException(err, extra),
};

/** Replace the telemetry sink. Called once at boot from an adapter. */
export function setTelemetry(impl: Telemetry): void {
  _impl = impl;
}
