import { NextResponse } from "next/server";
import { getLoginHeroMetrics } from "@/lib/auth-metrics";

// GET /api/auth/login-metrics
//
// Returns the same shape the LoginHeroSection consumes via SSR. Useful for
// status pages, the marketing site, or a "verify the dashboard is alive"
// healthcheck — all of which must read the same verified-only numbers.
export async function GET() {
  const metrics = await getLoginHeroMetrics();
  return NextResponse.json(metrics, {
    headers: { "Cache-Control": "private, max-age=60, stale-while-revalidate=300" },
  });
}
