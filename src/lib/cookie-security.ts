// Decide a cookie's `Secure` flag from the request, not from NODE_ENV.
//
// A browser silently DROPS a `Secure` cookie delivered over plain HTTP. With
// NODE_ENV=production but the app reached over http:// — e.g. `docker compose up`
// at http://localhost:3000 — the CSRF + session cookies were marked Secure and
// never stored, so the double-submit check failed with "Missing CSRF token" and
// sessions never persisted. Basing Secure on the actual request keeps cookies
// Secure behind TLS (prod / Railway, where x-forwarded-proto=https) while letting
// the stack work over http://localhost.
//
// Edge-safe: reads only request headers + URL (no node-only APIs), so the
// middleware can import it too.
export function cookieSecure(req: Request): boolean {
  // Behind a proxy / load balancer (Railway, etc.) the client's protocol is here.
  const proto = (req.headers.get("x-forwarded-proto") ?? "")
    .split(",")[0]
    .trim()
    .toLowerCase();
  if (proto) return proto === "https";

  // No proxy header → a direct connection; read the request URL.
  try {
    const url = new URL(req.url);
    if (url.protocol === "https:") return true; // direct TLS
    const host = url.hostname;
    // Plain http to a loopback host (local docker-compose / dev) must NOT be
    // Secure, or the browser drops the cookie.
    if (host === "localhost" || host === "127.0.0.1" || host === "::1" || host === "0.0.0.0") {
      return false;
    }
  } catch {
    /* fall through to the prod-safe default */
  }

  // Unknown http host with no proxy header: keep the production posture (Secure).
  return process.env.NODE_ENV === "production";
}
