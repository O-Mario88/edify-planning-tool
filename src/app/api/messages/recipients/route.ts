import { NextResponse } from "next/server";
import { getCurrentUserOrNull } from "@/lib/auth";
import { backendFetch } from "@/lib/api/backend";

// Active users the caller may message (role-scoped on the backend).
export const dynamic = "force-dynamic";

export type MessageRecipient = { id: string; name: string; role: string };

export async function GET() {
  const user = await getCurrentUserOrNull();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const r = await backendFetch<MessageRecipient[]>(`/messages/recipients`, user);
  return r.ok
    ? NextResponse.json({ live: true, recipients: r.data })
    : NextResponse.json({ live: false, recipients: [], error: r.error }, { status: 200 });
}
