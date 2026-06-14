// Session-cookie HMAC signing — closes the "any role is forgeable" hole.
//
// The session identity lives in three non-encrypted cookies (edify-email /
// -role / -name). Without a signature, anyone can hand-craft a Cookie header
// (e.g. `edify-email=admin@edify.org`) and be resolved as that user on the
// ungated /api/* proxies. This module signs the identity with HMAC-SHA256 so a
// forged cookie is rejected: login sets `edify-sig`, and both the server
// resolver (lib/auth.ts) and the edge middleware verify it before trusting the
// identity.
//
// IMPORTANT: imported by Edge middleware — Web Crypto only (no node:crypto /
// Buffer). The same code runs in the Node server handlers.

const SECRET = process.env.EDIFY_SESSION_SECRET || "";
export const SESSION_SIG_COOKIE = "edify-sig";

// Signing is ACTIVE whenever a secret is configured. Production MUST set one
// (prod-readiness should assert it); in local dev with no secret, signing is
// inert so the `?as=` impersonation + cookie-less previews still work.
export function sessionSigningActive(): boolean {
  return SECRET.length > 0;
}

async function hmacHex(data: string): Promise<string> {
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey("raw", enc.encode(SECRET), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(data));
  return Array.from(new Uint8Array(sig)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

// Sign over the security-critical identity (email + role). Name is cosmetic and
// omitted to avoid cookie value-encoding fragility across set/get.
export async function signSession(email: string, role: string): Promise<string> {
  return hmacHex(`${email}|${role}`);
}

function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

/** True when the (email, role, name) triple matches the provided signature.
 *  When signing is inert (no secret — dev only) this returns true so existing
 *  flows aren't blocked. With a secret set, a missing/wrong sig returns false. */
export async function verifySession(email: string, role: string, sig: string | undefined | null): Promise<boolean> {
  if (!sessionSigningActive()) return true;
  if (!sig) return false;
  const expected = await signSession(email, role);
  return timingSafeEqual(expected, sig);
}
