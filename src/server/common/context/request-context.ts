import { AsyncLocalStorage } from "node:async_hooks";
import { randomUUID } from "node:crypto";

// Per-request provenance carried implicitly through the async call tree, so the
// (singleton) AuditService can stamp ip / user-agent / correlationId onto every
// audit row WITHOUT threading context through dozens of service call sites.
//
// edify-api opened this scope via Express middleware. In Next there is no such
// middleware around route handlers, so the consolidated backend opens the scope
// at the in-process dispatch boundary via `withRequestContext()` (called by the
// surfaces dispatcher / route handlers), building the context from the Web
// `Request` headers.
export interface RequestContext {
  ipAddress?: string;
  userAgent?: string;
  correlationId: string;
}

const storage = new AsyncLocalStorage<RequestContext>();

export const requestContext = {
  get(): RequestContext | undefined {
    return storage.getStore();
  },
};

/** Build a RequestContext from a Web Request's headers (or any Headers-like). */
export function contextFromHeaders(headers: Headers): RequestContext {
  const correlationId = headers.get("x-correlation-id") || randomUUID();
  const forwarded = headers.get("x-forwarded-for")?.split(",")[0]?.trim();
  return {
    ipAddress: forwarded || headers.get("x-real-ip") || undefined,
    userAgent: headers.get("user-agent") || undefined,
    correlationId,
  };
}

/**
 * Run `fn` inside an AsyncLocalStorage scope so AuditService can stamp
 * provenance. Pass the incoming request's Headers (Next route handlers expose
 * these via the `Request` object or `headers()`); when omitted, a bare context
 * with a fresh correlationId is used.
 */
export function withRequestContext<T>(
  headersOrCtx: Headers | RequestContext | undefined,
  fn: () => T,
): T {
  const ctx: RequestContext =
    headersOrCtx === undefined
      ? { correlationId: randomUUID() }
      : headersOrCtx instanceof Headers
        ? contextFromHeaders(headersOrCtx)
        : headersOrCtx;
  return storage.run(ctx, fn);
}
