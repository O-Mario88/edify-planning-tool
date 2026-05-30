// Rate-limit adapter.
//
// Two implementations:
//
//   • `memory` — fixed-window counter in a `Map`. Same behaviour as
//     the original `src/lib/rate-limit.ts`. Fine for single-instance
//     dev; bypassable across replicas.
//
//   • `upstash` — Upstash Redis via REST API. Works from Vercel Edge
//     and serverless functions. Activated when UPSTASH_REDIS_REST_URL
//     and UPSTASH_REDIS_REST_TOKEN are set.
//
// Same `rateLimit(key, opts) -> RateLimitResult` contract as before.
// The legacy `src/lib/rate-limit.ts` now re-exports from here so
// existing callers keep working.

import "server-only";

export type RateLimitOptions = {
  max: number;
  windowMs: number;
};

export type RateLimitResult = {
  ok: boolean;
  remaining: number;
  resetAt: number;
  retryAfterSec: number;
};

export type RateLimitAdapter = {
  label: string;
  check(key: string, opts: RateLimitOptions): Promise<RateLimitResult>;
};

// ────────── memory impl ────────────────────────────────────────────

const memBuckets = new Map<string, { count: number; resetAt: number }>();
const MEM_SOFT_CAP = 10_000;

const memoryAdapter: RateLimitAdapter = {
  label: "memory",
  async check(key, opts) {
    const now = Date.now();
    if (memBuckets.size > MEM_SOFT_CAP) {
      for (const [k, b] of memBuckets) if (b.resetAt < now) memBuckets.delete(k);
    }
    const b = memBuckets.get(key);
    if (!b || b.resetAt < now) {
      memBuckets.set(key, { count: 1, resetAt: now + opts.windowMs });
      return { ok: true, remaining: opts.max - 1, resetAt: now + opts.windowMs, retryAfterSec: 0 };
    }
    if (b.count >= opts.max) {
      return { ok: false, remaining: 0, resetAt: b.resetAt, retryAfterSec: Math.ceil((b.resetAt - now) / 1000) };
    }
    b.count += 1;
    return { ok: true, remaining: opts.max - b.count, resetAt: b.resetAt, retryAfterSec: 0 };
  },
};

// ────────── Upstash impl ────────────────────────────────────────────
//
// Implements a sliding-window counter via INCR + EXPIRE on first
// increment. Atomic enough for rate-limit semantics; bypass-safe
// across replicas because Redis is the single source of truth.

function makeUpstashAdapter(): RateLimitAdapter {
  const url = requireEnv("UPSTASH_REDIS_REST_URL");
  const token = requireEnv("UPSTASH_REDIS_REST_TOKEN");

  async function cmd(args: (string | number)[]): Promise<unknown> {
    const res = await fetch(`${url}/${args.map((a) => encodeURIComponent(String(a))).join("/")}`, {
      headers: { authorization: `Bearer ${token}` },
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`upstash ${res.status}: ${text.slice(0, 200)}`);
    }
    const j = await res.json() as { result?: unknown };
    return j.result;
  }

  return {
    label: "upstash",
    async check(key, opts) {
      const windowKey = `rl:${key}:${Math.floor(Date.now() / opts.windowMs)}`;
      const ttlSec = Math.ceil(opts.windowMs / 1000);
      // INCR returns the new counter value.
      const next = Number(await cmd(["INCR", windowKey]));
      // EXPIRE only sets a TTL if the key doesn't already have one;
      // safe to call every time, very cheap.
      await cmd(["EXPIRE", windowKey, ttlSec, "NX"]);
      const now = Date.now();
      const resetAt = (Math.floor(now / opts.windowMs) + 1) * opts.windowMs;
      if (next > opts.max) {
        return { ok: false, remaining: 0, resetAt, retryAfterSec: Math.ceil((resetAt - now) / 1000) };
      }
      return { ok: true, remaining: opts.max - next, resetAt, retryAfterSec: 0 };
    },
  };
}

function requireEnv(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error(`Missing env var: ${name}`);
  return v;
}

// ────────── resolver ────────────────────────────────────────────────

export function resolveRateLimit(): RateLimitAdapter {
  if (process.env.UPSTASH_REDIS_REST_URL && process.env.UPSTASH_REDIS_REST_TOKEN) {
    try { return makeUpstashAdapter(); }
    catch (err) {
      // eslint-disable-next-line no-console
      console.warn("[edify-infra] rate-limit: Upstash config failed; using memory. Reason:", String(err));
    }
  }
  return memoryAdapter;
}

// ────────── Helpers re-exported from legacy file ───────────────────

export function ipFromRequest(req: Request): string {
  const xff = req.headers.get("x-forwarded-for");
  if (xff) {
    const first = xff.split(",")[0]?.trim();
    if (first) return first;
  }
  const real = req.headers.get("x-real-ip");
  if (real) return real.trim();
  return "unknown";
}

export function rateLimitResponse(result: RateLimitResult, message: string): Response {
  return new Response(JSON.stringify({ ok: false, message }), {
    status: 429,
    headers: {
      "content-type": "application/json",
      "retry-after": String(result.retryAfterSec),
      "x-ratelimit-remaining": "0",
      "x-ratelimit-reset": String(Math.ceil(result.resetAt / 1000)),
    },
  });
}
