import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchSpecialProjects } from "@/lib/api/surfaces";

// Backend-backed special-projects list (role-scoped). No mock fallback.
export const dynamic = "force-dynamic";

export async function GET() {
  const user = await getCurrentUser();
  const r = await fetchSpecialProjects(user);
  return r.live
    ? NextResponse.json({ live: true, projects: r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
