// CSRF — double-submit cookie pattern.
//
// On any GET to a non-static path, middleware ensures `edify-csrf`
// exists. That cookie is *not* HttpOnly — by design — so client JS
// can read it and echo it back as the `x-csrf-token` header on
// mutating requests. Server-side, mutating API routes call
// `requireCsrf(req)`; if the header doesn't match the cookie, we
// reject with 403.
//
// This is the WHATWG fetch / form pattern that stops cross-origin
// posts: a cross-origin attacker can make a POST, but they cannot
// read the user's cookie store from the attacker page (browsers
// enforce origin isolation on cookies). Without the cookie, they
// can't craft a matching header.
//
// Tokens are 32 random bytes, encoded base64url, rotated never —
// per-session is sufficient for double-submit. (Rotate on login if
// you adopt session fixation defence later.)
//
// IMPORTANT: this module is imported by Edge middleware. Use only
// the Web Crypto API + standard JS — no `node:crypto`, no Buffer.

export const CSRF_COOKIE_NAME = "edify-csrf";
export const CSRF_HEADER_NAME = "x-csrf-token";

function bytesToBase64Url(bytes: Uint8Array): string {
  let str = "";
  for (let i = 0; i < bytes.length; i++) str += String.fromCharCode(bytes[i]);
  return btoa(str).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function generateCsrfToken(): string {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return bytesToBase64Url(bytes);
}

// Constant-time string comparison. Both inputs must be the same
// length; bail before the loop otherwise so we don't leak length
// via timing (the caller already early-rejected on length difference).
function timingSafeEqualStrings(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) {
    diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return diff === 0;
}

// Server-side check used by every mutating API route.
//
//   - GET / HEAD / OPTIONS bypass entirely (safe methods, no state change).
//   - Header must exist and equal the cookie via constant-time comparison.
//
// Returns `null` on success (so callers can early-`return await ...`),
// or a 403 Response when verification fails.
export function requireCsrf(req: Request): Response | null {
  const method = req.method.toUpperCase();
  if (method === "GET" || method === "HEAD" || method === "OPTIONS") return null;

  const cookieHeader = req.headers.get("cookie") ?? "";
  const cookie = parseCookie(cookieHeader, CSRF_COOKIE_NAME);
  const header = req.headers.get(CSRF_HEADER_NAME);

  if (!cookie || !header) {
    return forbidden("Missing CSRF token");
  }
  if (!timingSafeEqualStrings(cookie, header)) {
    return forbidden("CSRF token mismatch");
  }
  return null;
}

function forbidden(message: string): Response {
  return new Response(JSON.stringify({ ok: false, message }), {
    status: 403,
    headers: { "content-type": "application/json" },
  });
}

function parseCookie(header: string, name: string): string | null {
  if (!header) return null;
  for (const pair of header.split(";")) {
    const idx = pair.indexOf("=");
    if (idx < 0) continue;
    const k = pair.slice(0, idx).trim();
    if (k === name) {
      return decodeURIComponent(pair.slice(idx + 1).trim());
    }
  }
  return null;
}
