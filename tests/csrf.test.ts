import { describe, it, expect } from "vitest";
import {
  generateCsrfToken,
  requireCsrf,
  CSRF_COOKIE_NAME,
  CSRF_HEADER_NAME,
} from "@/lib/csrf";

// CSRF is the only thing standing between a user's session cookie and
// a cross-origin attacker who can persuade their browser to POST. The
// double-submit pattern stops that with one rule: header value must
// equal cookie value, compared in constant time.

function req(opts: {
  method?: string;
  cookie?: string;
  header?: string;
}): Request {
  const headers: Record<string, string> = {};
  if (opts.cookie !== undefined) headers["cookie"] = `${CSRF_COOKIE_NAME}=${opts.cookie}`;
  if (opts.header !== undefined) headers[CSRF_HEADER_NAME] = opts.header;
  return new Request("http://example.com/api/auth/login", {
    method: opts.method ?? "POST",
    headers,
  });
}

describe("generateCsrfToken", () => {
  it("produces a unique 32-byte base64url token each call", () => {
    const a = generateCsrfToken();
    const b = generateCsrfToken();
    expect(a).not.toBe(b);
    // base64url(32 bytes) = 43 chars, no padding.
    expect(a).toMatch(/^[A-Za-z0-9_-]{43}$/);
  });
});

describe("requireCsrf", () => {
  it("returns null (success) on GET, HEAD, OPTIONS regardless of headers", () => {
    for (const method of ["GET", "HEAD", "OPTIONS"] as const) {
      expect(requireCsrf(req({ method }))).toBeNull();
    }
  });

  it("returns null when cookie === header (double-submit happy path)", () => {
    const token = generateCsrfToken();
    expect(requireCsrf(req({ cookie: token, header: token }))).toBeNull();
  });

  it("returns 403 when the header is missing", () => {
    const token = generateCsrfToken();
    const r = requireCsrf(req({ cookie: token }));
    expect(r).not.toBeNull();
    expect(r?.status).toBe(403);
  });

  it("returns 403 when the cookie is missing", () => {
    const r = requireCsrf(req({ header: generateCsrfToken() }));
    expect(r?.status).toBe(403);
  });

  it("returns 403 when header ≠ cookie", () => {
    const a = generateCsrfToken();
    const b = generateCsrfToken();
    expect(requireCsrf(req({ cookie: a, header: b }))?.status).toBe(403);
  });

  it("returns 403 when lengths differ (constant-time check rejects early)", () => {
    expect(requireCsrf(req({ cookie: "shorter", header: "definitely-longer-token" }))?.status).toBe(403);
  });
});
