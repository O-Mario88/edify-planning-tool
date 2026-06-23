import { NextRequest, NextResponse } from "next/server";
import { getCurrentUserOrNull } from "@/lib/auth";
import { backendFetch } from "@/lib/api/backend";

// The role-specific message contexts the caller may use for a given recipient
// (spec §6/§8 step 2). The backend resolves the (senderRole → recipientRole)
// matrix; an empty list means the pairing is off-policy.
export const dynamic = "force-dynamic";

export type MessageContextOption = {
  key: string;
  label: string;
  requiresLinkedRecord: boolean;
  recordTypes: string[];
};

export async function GET(req: NextRequest) {
  const user = await getCurrentUserOrNull();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const recipientId = req.nextUrl.searchParams.get("recipientId");
  if (!recipientId) return NextResponse.json({ live: false, contexts: [], error: "recipientId is required" }, { status: 200 });
  const r = await backendFetch<MessageContextOption[]>(`/messages/contexts?recipientId=${encodeURIComponent(recipientId)}`, user);
  return r.ok
    ? NextResponse.json({ live: true, contexts: r.data })
    : NextResponse.json({ live: false, contexts: [], error: r.error }, { status: 200 });
}
