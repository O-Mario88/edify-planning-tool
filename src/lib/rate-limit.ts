// Legacy re-export. The implementation moved to `src/lib/infra/rate-limit.ts`
// so it can switch between memory and Upstash via env. Existing callers
// (auth API routes, demo role-switch) keep their imports working.

import {
  ipFromRequest as _ipFromRequest,
  rateLimitResponse as _rateLimitResponse,
  type RateLimitOptions as _Opts,
  type RateLimitResult as _Result,
} from "./infra/rate-limit";
import { rateLimit as rateLimitAdapter } from "./infra";

export type RateLimitOptions = _Opts;
export type RateLimitResult  = _Result;
export const ipFromRequest      = _ipFromRequest;
export const rateLimitResponse  = _rateLimitResponse;

// Promise-returning now — the underlying adapter may hit Redis. The
// legacy synchronous call sites are auth routes that already await
// other I/O, so the change is fine.
export function rateLimit(key: string, opts: RateLimitOptions): Promise<RateLimitResult> {
  return rateLimitAdapter.check(key, opts);
}
