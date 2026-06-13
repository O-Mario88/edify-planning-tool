import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchProjectPartners, assignProjectPartner } from "@/lib/api/surfaces";

// Partners monitored on a project (GET) + assign a partner (POST). Backend.
export const dynamic = "force-dynamic";

export async function GET(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getCurrentUser();
  const r = await fetchProjectPartners(user, id);
  return r.live
    ? NextResponse.json({ live: true, partners: r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}

export async function POST(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getCurrentUser();
  const body = await req.json().catch(() => ({}));
  const r = await assignProjectPartner(user, id, body?.partnerId ?? "");
  return r.live
    ? NextResponse.json({ live: true, ...r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
