// KV cache adapter — drives dashboard rollups + materialized snapshots.
//
// Two implementations:
//
//   • `memory` — a `Map` with TTL. Per-process; lost on restart.
//   • `upstash` — Upstash Redis via REST.
//
// The contract is intentionally narrow: get / set / del / getOrFetch.
// Anything more complex (pub/sub, sorted sets) belongs in a different
// adapter so callers don't accidentally adopt Redis-shaped APIs we
// might not have on the in-memory fallback.

import "server-only";

export type CacheAdapter = {
  label: string;
  get<T>(key: string): Promise<T | null>;
  set<T>(key: string, value: T, ttlSec: number): Promise<void>;
  del(key: string): Promise<void>;
  /**
   * Read-through helper: returns the cached value if present,
   * otherwise invokes `fetch`, caches the result, and returns it.
   * Single-flight per key per process is NOT guaranteed by this
   * helper — use a separate dedup if the underlying fetch is
   * expensive enough that thundering herd matters.
   */
  getOrFetch<T>(key: string, ttlSec: number, fetcher: () => Promise<T>): Promise<T>;
};

// ────────── memory impl ────────────────────────────────────────────

const memStore = new Map<string, { value: unknown; expiresAt: number }>();
const MEM_SOFT_CAP = 5000;

const memoryAdapter: CacheAdapter = {
  label: "memory",
  async get<T>(key: string): Promise<T | null> {
    const e = memStore.get(key);
    if (!e) return null;
    if (e.expiresAt < Date.now()) {
      memStore.delete(key);
      return null;
    }
    return e.value as T;
  },
  async set<T>(key: string, value: T, ttlSec: number): Promise<void> {
    if (memStore.size > MEM_SOFT_CAP) {
      const now = Date.now();
      for (const [k, v] of memStore) if (v.expiresAt < now) memStore.delete(k);
    }
    memStore.set(key, { value, expiresAt: Date.now() + ttlSec * 1000 });
  },
  async del(key: string): Promise<void> {
    memStore.delete(key);
  },
  async getOrFetch<T>(key: string, ttlSec: number, fetcher: () => Promise<T>): Promise<T> {
    const hit = await this.get<T>(key);
    if (hit !== null) return hit;
    const fresh = await fetcher();
    await this.set(key, fresh, ttlSec);
    return fresh;
  },
};

// ────────── Upstash impl ────────────────────────────────────────────

function makeUpstashAdapter(): CacheAdapter {
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

  const prefix = process.env.EDIFY_CACHE_PREFIX ?? "edify:";

  return {
    label: "upstash",
    async get<T>(key: string): Promise<T | null> {
      const raw = await cmd(["GET", prefix + key]);
      if (raw == null) return null;
      try { return JSON.parse(String(raw)) as T; } catch { return null; }
    },
    async set<T>(key: string, value: T, ttlSec: number): Promise<void> {
      await cmd(["SET", prefix + key, JSON.stringify(value), "EX", ttlSec]);
    },
    async del(key: string): Promise<void> {
      await cmd(["DEL", prefix + key]);
    },
    async getOrFetch<T>(key: string, ttlSec: number, fetcher: () => Promise<T>): Promise<T> {
      const hit = await this.get<T>(key);
      if (hit !== null) return hit;
      const fresh = await fetcher();
      await this.set(key, fresh, ttlSec);
      return fresh;
    },
  };
}

function requireEnv(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error(`Missing env var: ${name}`);
  return v;
}

// ────────── resolver ────────────────────────────────────────────────

export function resolveCache(): CacheAdapter {
  if (process.env.UPSTASH_REDIS_REST_URL && process.env.UPSTASH_REDIS_REST_TOKEN) {
    try { return makeUpstashAdapter(); }
    catch (err) {
      // eslint-disable-next-line no-console
      console.warn("[edify-infra] cache: Upstash config failed; using memory. Reason:", String(err));
    }
  }
  return memoryAdapter;
}
