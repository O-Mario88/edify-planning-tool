// Client-side CSRF helper.
//
// Use `fetchJson` instead of `fetch` for any mutating call to /api/*.
// It reads the `edify-csrf` cookie that middleware set on the page
// load and echoes it back as the `x-csrf-token` header, satisfying
// the double-submit check enforced by lib/csrf.ts on the server.
//
// JSON body in, JSON body out. Throws on non-2xx so callers don't
// have to remember to check status — wrap in try/catch when you
// care about the failure mode.

import { CSRF_COOKIE_NAME, CSRF_HEADER_NAME } from "@/lib/csrf";

function readCsrfTokenFromCookie(): string | null {
  if (typeof document === "undefined") return null;
  const cookies = document.cookie.split(";");
  for (const c of cookies) {
    const idx = c.indexOf("=");
    if (idx < 0) continue;
    const k = c.slice(0, idx).trim();
    if (k === CSRF_COOKIE_NAME) {
      return decodeURIComponent(c.slice(idx + 1).trim());
    }
  }
  return null;
}

// Header object carrying the CSRF token, for raw fetch() call sites that can't
// use fetchJson (multipart uploads, fire-and-forget mutations, or existing
// hand-rolled fetches). Spread into the request's headers:
//   fetch(url, { method: "POST", headers: { "Content-Type": "application/json", ...csrfHeaders() }, body })
// Returns {} when no token is present (SSR / no cookie) so it's always safe to spread.
export function csrfHeaders(): Record<string, string> {
  const token = readCsrfTokenFromCookie();
  return token ? { [CSRF_HEADER_NAME]: token } : {};
}

export type FetchJsonOptions = Omit<RequestInit, "body" | "method"> & {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown; // JSON-serialised automatically
};

export async function fetchJson<T = unknown>(
  url: string,
  opts: FetchJsonOptions = {},
): Promise<{ status: number; ok: boolean; data: T | null }> {
  const method = (opts.method ?? "POST").toUpperCase();
  const headers = new Headers(opts.headers);
  headers.set("content-type", "application/json");

  // Only mutating methods need the CSRF header. The server skips
  // verification on GET/HEAD/OPTIONS, so sending the token there is
  // harmless but wasteful.
  if (method !== "GET" && method !== "HEAD" && method !== "OPTIONS") {
    const token = readCsrfTokenFromCookie();
    if (token) headers.set(CSRF_HEADER_NAME, token);
  }

  const res = await fetch(url, {
    ...opts,
    method,
    credentials: opts.credentials ?? "include",
    headers,
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
  });
  let data: T | null = null;
  try {
    data = (await res.json()) as T;
  } catch {
    data = null;
  }
  return { status: res.status, ok: res.ok, data };
}
