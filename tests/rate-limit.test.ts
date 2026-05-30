import { describe, it, expect, vi, afterEach } from "vitest";
import { rateLimit, ipFromRequest } from "@/lib/rate-limit";

// Rate limiter is the only line between a real login flow and a
// credential-stuffing script. These tests pin the windowing,
// retry-after timing, and IP extraction logic.

afterEach(() => {
  vi.useRealTimers();
});

describe("rateLimit", () => {
  // `rateLimit` is now async (the adapter may hit Redis). Tests await
  // the call. Behaviour against the in-memory default is unchanged.

  it("allows up to `max` requests inside the window, then blocks", async () => {
    const key = `k:${Math.random()}`;
    const opts = { max: 3, windowMs: 60_000 };

    expect((await rateLimit(key, opts)).ok).toBe(true);
    expect((await rateLimit(key, opts)).ok).toBe(true);
    expect((await rateLimit(key, opts)).ok).toBe(true);
    const blocked = await rateLimit(key, opts);
    expect(blocked.ok).toBe(false);
    expect(blocked.remaining).toBe(0);
    expect(blocked.retryAfterSec).toBeGreaterThan(0);
  });

  it("decrements the remaining counter on each call", async () => {
    const key = `k:${Math.random()}`;
    const opts = { max: 5, windowMs: 60_000 };
    expect((await rateLimit(key, opts)).remaining).toBe(4);
    expect((await rateLimit(key, opts)).remaining).toBe(3);
    expect((await rateLimit(key, opts)).remaining).toBe(2);
  });

  it("resets the bucket once the window elapses", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 0, 1, 12, 0, 0));

    const key = `k:${Math.random()}`;
    const opts = { max: 2, windowMs: 1_000 };

    expect((await rateLimit(key, opts)).ok).toBe(true);
    expect((await rateLimit(key, opts)).ok).toBe(true);
    expect((await rateLimit(key, opts)).ok).toBe(false);

    // Advance past the window.
    vi.advanceTimersByTime(1_500);

    const after = await rateLimit(key, opts);
    expect(after.ok).toBe(true);
    // First call in the fresh window — should report max-1 remaining.
    expect(after.remaining).toBe(opts.max - 1);
  });

  it("keys are isolated — limiting one IP does not limit another", async () => {
    const opts = { max: 1, windowMs: 60_000 };
    const a = `k:a:${Math.random()}`;
    const b = `k:b:${Math.random()}`;
    expect((await rateLimit(a, opts)).ok).toBe(true);
    expect((await rateLimit(a, opts)).ok).toBe(false);
    // b is fresh.
    expect((await rateLimit(b, opts)).ok).toBe(true);
  });
});

describe("ipFromRequest", () => {
  function req(headers: Record<string, string>): Request {
    return new Request("http://example.com/login", { headers });
  }

  it("uses the first IP in x-forwarded-for when present", () => {
    expect(
      ipFromRequest(req({ "x-forwarded-for": "203.0.113.42, 10.0.0.1" })),
    ).toBe("203.0.113.42");
  });

  it("falls back to x-real-ip when x-forwarded-for is absent", () => {
    expect(ipFromRequest(req({ "x-real-ip": "198.51.100.7" }))).toBe(
      "198.51.100.7",
    );
  });

  it("returns 'unknown' rather than crashing when no proxy header is set", () => {
    expect(ipFromRequest(req({}))).toBe("unknown");
  });
});
