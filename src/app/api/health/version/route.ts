import { NextResponse } from "next/server";
import { isBackendEnabled } from "@/lib/api/backend";

// Build + runtime-mode probe. The single most useful production signal: which
// DATA MODE the app is actually running in (proxy / local-prisma / mock).
export const dynamic = "force-dynamic";

export function GET() {
  const dataMode = isBackendEnabled()
    ? "proxy"
    : process.env.DATABASE_URL
      ? "local-prisma-available"
      : "mock";
  return NextResponse.json({
    ok: true,
    service: "edify-web",
    env: process.env.NODE_ENV ?? "unknown",
    commit:
      process.env.RAILWAY_GIT_COMMIT_SHA ??
      process.env.VERCEL_GIT_COMMIT_SHA ??
      process.env.GIT_COMMIT_SHA ??
      "unknown",
    dataMode,
    backendProxyEnabled: isBackendEnabled(),
    inProcessDomains: process.env.EDIFY_INPROC_DOMAINS || "(none)",
    time: new Date().toISOString(),
  });
}
