import { NextResponse } from "next/server";
import { getCurrentUserOrNull } from "@/lib/auth";
import { backendFetch } from "@/lib/api/backend";

// Full thread for the reader pane (participant-scoped; marks own messages read).
export const dynamic = "force-dynamic";

export type ThreadMessage = { id: string; body: string; senderId: string; senderName: string; mine: boolean; createdAt: string };
export type MessageThreadVM = { id: string; subject: string; contextType: string | null; contextId: string | null; messages: ThreadMessage[] };

export async function GET(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const user = await getCurrentUserOrNull();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const r = await backendFetch<MessageThreadVM>(`/messages/thread/${encodeURIComponent(id)}`, user);
  return r.ok
    ? NextResponse.json({ live: true, thread: r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: 502 });
}
