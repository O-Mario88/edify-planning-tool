"use client";

// Resilient upload (spec layer #9). XHR-based so it reports byte progress, with
// automatic retry + exponential backoff on transient failures — the difference
// between losing a field officer's evidence on a flaky connection and not.
//
// True resumable upload needs server-side range support; until the backend adds
// it, this retries the whole transfer (idempotent on the server via the activity
// id) and surfaces progress so the user knows it's still going.

export type UploadProgress = { loaded: number; total: number; pct: number };

export type UploadOptions = {
  onProgress?: (p: UploadProgress) => void;
  /** Total attempts before giving up (default 4). */
  retries?: number;
  /** Base backoff in ms, doubled each retry (default 800). */
  backoffMs?: number;
  method?: "POST" | "PUT";
  headers?: Record<string, string>;
  signal?: AbortSignal;
};

export type UploadResult = { ok: boolean; status: number; body: string; attempts: number };

function once(url: string, body: XMLHttpRequestBodyInit, opts: UploadOptions): Promise<UploadResult> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(opts.method ?? "POST", url);
    for (const [k, v] of Object.entries(opts.headers ?? {})) xhr.setRequestHeader(k, v);

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && opts.onProgress) {
        opts.onProgress({ loaded: e.loaded, total: e.total, pct: Math.round((e.loaded / e.total) * 100) });
      }
    };
    xhr.onload = () => resolve({ ok: xhr.status >= 200 && xhr.status < 300, status: xhr.status, body: xhr.responseText, attempts: 1 });
    xhr.onerror = () => reject(new Error("network"));
    xhr.ontimeout = () => reject(new Error("timeout"));
    if (opts.signal) {
      opts.signal.addEventListener("abort", () => xhr.abort(), { once: true });
    }
    xhr.send(body);
  });
}

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

export async function uploadWithRetry(url: string, body: XMLHttpRequestBodyInit, opts: UploadOptions = {}): Promise<UploadResult> {
  const retries = opts.retries ?? 4;
  const backoff = opts.backoffMs ?? 800;
  let lastErr: unknown;
  for (let attempt = 1; attempt <= retries; attempt++) {
    if (opts.signal?.aborted) return { ok: false, status: 0, body: "aborted", attempts: attempt };
    try {
      const r = await once(url, body, opts);
      // Retry server 5xx; treat 4xx as terminal (won't get better by retrying).
      if (r.ok || (r.status >= 400 && r.status < 500)) return { ...r, attempts: attempt };
      lastErr = new Error(`server ${r.status}`);
    } catch (e) {
      lastErr = e;
    }
    if (attempt < retries) await wait(backoff * 2 ** (attempt - 1));
  }
  return { ok: false, status: 0, body: String(lastErr ?? "failed"), attempts: retries };
}
