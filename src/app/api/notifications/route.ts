import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchNotificationsRecent, fetchNotificationCounts } from "@/lib/api/surfaces";
import { readNotificationsFor, type NotificationRecord } from "@/lib/actions/audit";
import type { BackendNotification } from "@/lib/notifications-types";

// Backend-backed notifications (recent + counts). No generic mock fallback —
// when the backend is off or empty, the client renders a loading/empty/error
// state. EXCEPTION: the CCEO role reads the spec §20 catalogue through the
// canonical readNotificationsFor("CCEO") path, so the bell + drawer show the
// same rows as /notifications even before the backend emits anything.
export const dynamic = "force-dynamic";

const PRIORITY_OUT: Record<NonNullable<NotificationRecord["priority"]>, BackendNotification["priority"]> = {
  normal: "normal", important: "high", urgent: "urgent", critical: "urgent",
};

function toBackendShape(r: NotificationRecord): BackendNotification {
  return {
    id: r.id,
    title: r.title,
    body: r.body,
    contextType: r.category ?? null,
    targetRoute: r.href ?? null,
    actionRequired: r.actionRequired ?? false,
    priority: r.priority ? PRIORITY_OUT[r.priority] : "normal",
    status: r.read ? "read" : "unread",
    createdAt: r.createdAt,
    actionLabel: r.actionLabel ?? null,
    dueDate: r.dueDate ?? null,
    recommendedAction: r.recommendedAction ?? null,
  };
}

export async function GET() {
  const user = await getCurrentUser();
  const [recent, counts] = await Promise.all([
    fetchNotificationsRecent(user),
    fetchNotificationCounts(user),
  ]);

  // CCEO: merge the canonical role-token rows (live emits + §20 catalogue)
  // ahead of whatever the backend returned, de-duped on id.
  if (user.role === "CCEO") {
    const roleRows = [
      ...readNotificationsFor(user.staffId, { limit: 100 }),
      ...readNotificationsFor("CCEO", { limit: 100 }),
    ].map(toBackendShape);
    const backendRows: BackendNotification[] = recent.live && Array.isArray(recent.data) ? recent.data as BackendNotification[] : [];
    const seen = new Set<string>();
    const merged = [...roleRows, ...backendRows].filter((r) => !seen.has(r.id) && seen.add(r.id) !== undefined);
    merged.sort((a, b) => b.createdAt.localeCompare(a.createdAt));
    const unread = merged.filter((r) => r.status === "unread");
    return NextResponse.json({
      live: true,
      recent: merged,
      counts: { unread: unread.length, actionRequired: unread.filter((r) => r.actionRequired).length },
    });
  }

  if (!recent.live) return NextResponse.json({ live: false, error: recent.error }, { status: recent.error ? 502 : 200 });
  return NextResponse.json({ live: true, recent: recent.data, counts: counts.live ? counts.data : null });
}
