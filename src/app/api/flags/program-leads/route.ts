import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchProgramLeads } from "@/lib/api/surfaces";

// Active Program Leads the CD can flag to (the flag form's picker).
export const dynamic = "force-dynamic";

export async function GET() {
  const user = await getCurrentUser();
  const r = await fetchProgramLeads({ email: user.email, role: user.role });
  return r.live
    ? NextResponse.json({ live: true, ...r.data })
    : NextResponse.json({ live: false, error: r.error, programLeads: [] }, { status: r.error ? 502 : 200 });
}
