// Observability adapter.
//
// Two implementations:
//
//   • `noop` — captures + drops. Default in dev.
//
//   • `sentry` — Sentry SDK-less. We hit the envelope endpoint with
//     fetch so production builds don't carry the @sentry/nextjs
//     package. Activated when SENTRY_DSN is set.
//
// The shape is intentionally tiny — captureError(err, ctx),
// captureMessage(msg, level, ctx), addBreadcrumb(crumb). The action
// layer wraps every catch in `captureError`; the dispatch layer adds
// breadcrumbs.

import "server-only";

export type Severity = "fatal" | "error" | "warning" | "info" | "debug";

export type Breadcrumb = {
  category?: string;
  message?:  string;
  level?:    Severity;
  data?:     Record<string, unknown>;
  timestampMs?: number;
};

export type CaptureContext = {
  tags?:        Record<string, string>;
  extra?:       Record<string, unknown>;
  user?:        { id?: string; email?: string; role?: string };
  fingerprint?: string[];
};

export type ObservabilityAdapter = {
  label: string;
  captureError(err: unknown, ctx?: CaptureContext): string;
  captureMessage(message: string, level?: Severity, ctx?: CaptureContext): string;
  addBreadcrumb(crumb: Breadcrumb): void;
};

// ────────── noop impl ───────────────────────────────────────────────

const noopAdapter: ObservabilityAdapter = {
  label: "noop",
  captureError(err) {
    // Still log to stderr so dev sessions surface errors. The id we
    // return is opaque — useful as a correlation token in toasts.
    // eslint-disable-next-line no-console
    console.error("[edify-obs]", err instanceof Error ? err.stack || err.message : err);
    return synthId();
  },
  captureMessage(message, level = "info") {
    // eslint-disable-next-line no-console
    (level === "error" || level === "fatal" ? console.error : console.log)("[edify-obs]", level, message);
    return synthId();
  },
  addBreadcrumb() {
    // Drop in dev.
  },
};

// ────────── Sentry impl ─────────────────────────────────────────────
//
// The DSN encodes the project ID + ingest host + public key. We parse
// it once and POST events as Sentry "envelope" format. This avoids a
// big SDK and works on Edge runtime where the SDK is finicky.

type SentryDsn = {
  ingestUrl: string;
  publicKey: string;
};

function parseDsn(dsn: string): SentryDsn {
  // dsn format: https://<publicKey>@<host>/<projectId>
  const m = /^https?:\/\/([^@]+)@([^/]+)\/(.+)$/.exec(dsn);
  if (!m) throw new Error("Invalid SENTRY_DSN");
  const [, publicKey, host, projectId] = m;
  return {
    publicKey,
    ingestUrl: `https://${host}/api/${projectId}/envelope/`,
  };
}

function makeSentryAdapter(): ObservabilityAdapter {
  const dsn = parseDsn(requireEnv("SENTRY_DSN"));
  const release = process.env.SENTRY_RELEASE ?? process.env.VERCEL_GIT_COMMIT_SHA ?? "unknown";
  const environment = process.env.SENTRY_ENV ?? process.env.NODE_ENV ?? "development";
  // In-memory ring buffer of breadcrumbs (per-process, last 50). Sentry
  // attaches the buffer to the next captureError.
  const breadcrumbs: Breadcrumb[] = [];

  function pushEvent(event: Record<string, unknown>): string {
    const eventId = randomEventId();
    event.event_id = eventId;
    event.timestamp = Math.floor(Date.now() / 1000);
    event.release = release;
    event.environment = environment;
    if (breadcrumbs.length > 0) event.breadcrumbs = { values: breadcrumbs.slice() };

    const envelopeHeader = JSON.stringify({ event_id: eventId, sent_at: new Date().toISOString() });
    const itemHeader     = JSON.stringify({ type: "event" });
    const item           = JSON.stringify(event);
    const body = `${envelopeHeader}\n${itemHeader}\n${item}`;

    // Fire-and-forget. If Sentry is unreachable, we don't want to
    // wedge the request — we already logged to stderr via noop chain.
    fetch(dsn.ingestUrl, {
      method: "POST",
      headers: {
        "content-type": "application/x-sentry-envelope",
        "x-sentry-auth": `Sentry sentry_version=7, sentry_key=${dsn.publicKey}, sentry_client=edify-edge/1.0`,
      },
      body,
    }).catch((err) => {
      // eslint-disable-next-line no-console
      console.error("[edify-obs] sentry post failed:", err);
    });
    return eventId;
  }

  return {
    label: `sentry (${environment})`,
    captureError(err, ctx) {
      const e = err instanceof Error ? err : new Error(String(err));
      const event = {
        level: "error" as Severity,
        platform: "javascript",
        logger: "edify",
        exception: {
          values: [
            {
              type: e.name,
              value: e.message,
              stacktrace: { frames: parseStack(e.stack ?? "") },
            },
          ],
        },
        tags: ctx?.tags,
        extra: ctx?.extra,
        user: ctx?.user,
        fingerprint: ctx?.fingerprint,
      };
      // eslint-disable-next-line no-console
      console.error("[edify-obs]", e.stack || e.message);
      return pushEvent(event);
    },
    captureMessage(message, level = "info", ctx) {
      const event = {
        level,
        platform: "javascript",
        logger: "edify",
        message: { formatted: message },
        tags: ctx?.tags,
        extra: ctx?.extra,
        user: ctx?.user,
      };
      // eslint-disable-next-line no-console
      console.log("[edify-obs]", level, message);
      return pushEvent(event);
    },
    addBreadcrumb(crumb) {
      breadcrumbs.push({ ...crumb, timestampMs: crumb.timestampMs ?? Date.now() });
      while (breadcrumbs.length > 50) breadcrumbs.shift();
    },
  };
}

function parseStack(stack: string): Array<{ filename: string; lineno?: number; colno?: number; function?: string }> {
  return stack.split("\n").slice(1, 30).map((line) => {
    // Best-effort. Sentry's UI parses what it gets.
    const m = /at\s+(?:(.+?)\s+\()?(.+):(\d+):(\d+)/.exec(line);
    if (!m) return { filename: line.trim() };
    return { function: m[1], filename: m[2], lineno: Number(m[3]), colno: Number(m[4]) };
  });
}

function randomEventId(): string {
  // 32 hex chars, lowercase. Avoids crypto.randomUUID for Edge compat.
  let s = "";
  for (let i = 0; i < 32; i++) s += Math.floor(Math.random() * 16).toString(16);
  return s;
}

function synthId(): string {
  return `noop_${Date.now().toString(36)}_${Math.floor(Math.random() * 1e6).toString(36)}`;
}

function requireEnv(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error(`Missing env var: ${name}`);
  return v;
}

// ────────── resolver ────────────────────────────────────────────────

export function resolveObservability(): ObservabilityAdapter {
  if (process.env.SENTRY_DSN) {
    try { return makeSentryAdapter(); }
    catch (err) {
      // eslint-disable-next-line no-console
      console.warn("[edify-infra] observability: Sentry config failed; using noop. Reason:", String(err));
    }
  }
  return noopAdapter;
}
