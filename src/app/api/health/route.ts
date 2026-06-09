import { NextResponse } from "next/server";

// Liveness probe for the container / load balancer. Does not touch the backend
// or DB — just confirms the Next server is up and serving.
export const dynamic = "force-dynamic";

export function GET() {
  return NextResponse.json({ ok: true, service: "edify-web", time: new Date().toISOString() });
}
