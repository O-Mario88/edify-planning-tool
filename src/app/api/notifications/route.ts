import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchNotificationsRecent, fetchNotificationCounts } from "@/lib/api/surfaces";

// Backend-backed notifications (recent + counts). No mock fallback — when the
// backend is off or empty, the client renders a loading/empty/error state.
export const dynamic = "force-dynamic";

export async function GET() {
  const user = await getCurrentUser();
  const [recent, counts] = await Promise.all([
    fetchNotificationsRecent(user),
    fetchNotificationCounts(user),
  ]);
  if (!recent.live) return NextResponse.json({ live: false, error: recent.error }, { status: recent.error ? 502 : 200 });
  return NextResponse.json({ live: true, recent: recent.data, counts: counts.live ? counts.data : null });
}
