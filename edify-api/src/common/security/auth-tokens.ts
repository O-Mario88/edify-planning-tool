// Secure token generation + hashing for invitations and password resets.
//
// Rules (spec):
//   • tokens are cryptographically random (crypto.randomBytes)
//   • the DB stores ONLY a SHA-256 hash — never the raw token
//   • tokens are single-use, expiring, revocable
//   • the raw token is returned to the caller ONCE (to put in the email/link)
//
// This module is the single place that knows how to mint + hash these tokens,
// so every endpoint (invite, reset) stays consistent.

import { randomBytes, createHash, timingSafeEqual } from 'node:crypto';

/** Generate a 32-byte (256-bit) random token, hex-encoded (64 chars). */
export function generateToken(): string {
  return randomBytes(32).toString('hex');
}

/** SHA-256 hash a token for DB storage. The raw token is never persisted. */
export function hashToken(token: string): string {
  return createHash('sha256').update(token).digest('hex');
}

/** Constant-time comparison of two hex-encoded hashes. */
export function compareHashes(a: string, b: string): boolean {
  const ab = Buffer.from(a, 'hex');
  const bb = Buffer.from(b, 'hex');
  if (ab.length !== bb.length) return false;
  return timingSafeEqual(ab, bb);
}

/** Compute an expiry Date `minutes` from now. */
export function expiryFromNow(minutes: number): Date {
  return new Date(Date.now() + minutes * 60_000);
}

/** Compute an expiry Date `days` from now. */
export function expiryFromNowDays(days: number): Date {
  return new Date(Date.now() + days * 24 * 60 * 60_000);
}
