"use client";

import { useEffect, useState } from "react";

// Public, unauthenticated build-provenance page (NOT under the (shell) route
// group, so it never hits the auth-gated layout; the middleware allowlist also
// leaves it public). It answers one operational question by eye:
//
//   "Is production actually running the latest committed code?"
//
// • BUNDLE row  — the commit/branch/build-time baked into THIS browser bundle at
//   build time (Dockerfile NEXT_PUBLIC_*). This proves what the frontend was
//   built from, independent of any runtime env.
// • SERVER row  — live fetch of /api/health/version: what the running server
//   reports (Railway runtime RAILWAY_GIT_COMMIT_SHA, with the baked SHA as
//   fallback) plus the DATA MODE (proxy / local-prisma / mock).
//
// Compare either against the latest commit on GitHub's main branch — if they
// match, the deploy is current. Exposes no secrets.

type ApiVersion = {
  service?: string;
  environment?: string;
  commit?: string;
  commitShort?: string;
  branch?: string;
  buildTime?: string;
  version?: string;
  dataMode?: string;
  backendProxyEnabled?: boolean;
  time?: string;
};

// NEXT_PUBLIC_* are inlined at build time, so these are literals in the bundle.
const BUNDLE = {
  commit: process.env.NEXT_PUBLIC_GIT_COMMIT_SHA || "unknown",
  branch: process.env.NEXT_PUBLIC_GIT_BRANCH || "unknown",
  buildTime: process.env.NEXT_PUBLIC_BUILD_TIME || "unknown",
  apiUrl: process.env.NEXT_PUBLIC_API_URL || "(same-origin /api)",
};

function short(sha: string | undefined): string {
  return sha && sha !== "unknown" ? sha.slice(0, 7) : "unknown";
}

export default function VersionPage() {
  const [api, setApi] = useState<ApiVersion | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    fetch("/api/health/version", { cache: "no-store" })
      .then((r) => r.json() as Promise<ApiVersion>)
      .then((d) => {
        if (active) setApi(d);
      })
      .catch((e: unknown) => {
        if (active) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      active = false;
    };
  }, []);

  const wrap: React.CSSProperties = {
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
    maxWidth: 640,
    margin: "48px auto",
    padding: "0 20px",
    color: "#0f172a",
    lineHeight: 1.6,
  };
  const card: React.CSSProperties = {
    border: "1px solid #e2e8f0",
    borderRadius: 12,
    padding: "16px 20px",
    margin: "16px 0",
    background: "#f8fafc",
  };
  const row: React.CSSProperties = {
    display: "flex",
    justifyContent: "space-between",
    gap: 16,
    padding: "4px 0",
  };
  const k: React.CSSProperties = { color: "#64748b" };
  const v: React.CSSProperties = { fontWeight: 600, textAlign: "right", wordBreak: "break-all" };

  return (
    <main style={wrap}>
      <h1 style={{ fontSize: 20, marginBottom: 4 }}>Edify · Build Version</h1>
      <p style={{ color: "#64748b", marginTop: 0 }}>
        Compare these against the latest commit on GitHub <code>main</code>. Matching SHAs = production is current.
      </p>

      <section style={card}>
        <div style={{ fontWeight: 700, marginBottom: 8 }}>Frontend bundle (this page)</div>
        <div style={row}>
          <span style={k}>commit</span>
          <span style={v}>{short(BUNDLE.commit)}</span>
        </div>
        <div style={row}>
          <span style={k}>branch</span>
          <span style={v}>{BUNDLE.branch}</span>
        </div>
        <div style={row}>
          <span style={k}>built</span>
          <span style={v}>{BUNDLE.buildTime}</span>
        </div>
        <div style={row}>
          <span style={k}>API URL</span>
          <span style={v}>{BUNDLE.apiUrl}</span>
        </div>
      </section>

      <section style={card}>
        <div style={{ fontWeight: 700, marginBottom: 8 }}>Server (live /api/health/version)</div>
        {error ? (
          <div style={{ color: "#b91c1c" }}>Could not reach /api/health/version: {error}</div>
        ) : !api ? (
          <div style={k}>loading…</div>
        ) : (
          <>
            <div style={row}>
              <span style={k}>service</span>
              <span style={v}>{api.service ?? "—"}</span>
            </div>
            <div style={row}>
              <span style={k}>environment</span>
              <span style={v}>{api.environment ?? "—"}</span>
            </div>
            <div style={row}>
              <span style={k}>commit</span>
              <span style={v}>{api.commitShort ?? short(api.commit)}</span>
            </div>
            <div style={row}>
              <span style={k}>branch</span>
              <span style={v}>{api.branch ?? "—"}</span>
            </div>
            <div style={row}>
              <span style={k}>built</span>
              <span style={v}>{api.buildTime ?? "—"}</span>
            </div>
            <div style={row}>
              <span style={k}>data mode</span>
              <span style={v}>{api.dataMode ?? "—"}</span>
            </div>
          </>
        )}
      </section>
    </main>
  );
}
