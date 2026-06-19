import { NextResponse } from "next/server";
import { isBackendEnabled } from "@/lib/api/backend";

// Database probe. Reports whether the app has ANY live data source:
//  - backend proxy (EDIFY_USE_BACKEND=true → edify-api owns the DB), or
//  - a working local Prisma connection (consolidated backend), or
//  - neither → the app is serving mock / in-memory data.
export const dynamic = "force-dynamic";

export async function GET() {
  const backend = isBackendEnabled();
  const dbUrl = !!process.env.DATABASE_URL;

  let localPrismaProbe: string;
  if (!dbUrl) {
    localPrismaProbe = "no DATABASE_URL set";
  } else {
    try {
      const { prisma } = await import("@/server/prisma/prisma.service");
      await prisma.$queryRaw`SELECT 1`;
      localPrismaProbe = "connected";
    } catch (e) {
      localPrismaProbe = "error: " + (e instanceof Error ? e.message : String(e));
    }
  }

  const ok = backend || localPrismaProbe === "connected";
  return NextResponse.json({
    ok,
    backendProxyEnabled: backend, // EDIFY_USE_BACKEND
    databaseUrlConfigured: dbUrl,
    localPrismaProbe,
    note: ok
      ? undefined
      : "NO LIVE DATA SOURCE: backend proxy is off AND no working local Prisma DB. The app is serving mock / in-memory data; saves will not persist.",
    time: new Date().toISOString(),
  });
}
