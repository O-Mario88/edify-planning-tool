"use client";

// notifications-store — backend-backed (no mock). The bell badge + drawer read
// the same snapshot fetched from /api/notifications (recent + counts), refresh
// on live SSE events, and write read-state through to the backend. Empty when
// the database has no notifications; never fabricated.

import { useCallback, useEffect, useState } from "react";
import { adaptNotification, type Notification, type NotificationCounts, type BackendNotification } from "./notifications-types";

type Snapshot = { list: Notification[]; counts: NotificationCounts };

let snapshot: Snapshot = { list: [], counts: { all: 0, unread: 0, action: 0, urgent: 0 } };
let loaded = false;
let loading = false;
let error: string | null = null;
const listeners = new Set<() => void>();
function emit() { for (const l of listeners) l(); }

function countsOf(list: Notification[]): NotificationCounts {
  return {
    all: list.length,
    unread: list.filter((n) => n.unread).length,
    action: list.filter((n) => n.unread && n.actionRequired).length,
    urgent: list.filter((n) => n.unread && (n.priority === "urgent" || n.priority === "critical")).length,
  };
}

export async function loadNotifications(): Promise<void> {
  if (loading) return;
  loading = true; error = null; emit();
  try {
    const res = await fetch("/api/notifications", { credentials: "include" });
    const j = await res.json();
    if (!res.ok || j.live === false) {
      error = j.error || "Could not load notifications";
    } else {
      const list = (j.recent as BackendNotification[]).map(adaptNotification);
      const base = countsOf(list);
      // Prefer backend unread (counts the full set, not just the recent slice).
      const counts: NotificationCounts = j.counts
        ? { all: list.length, unread: j.counts.unread ?? base.unread, action: j.counts.actionRequired ?? base.action, urgent: base.urgent }
        : base;
      snapshot = { list, counts };
    }
  } catch {
    error = "Could not reach the server";
  }
  loaded = true; loading = false; emit();
}

export function markNotificationRead(id: string): void {
  const list = snapshot.list.map((n) => (n.id === id ? { ...n, unread: false } : n));
  snapshot = { list, counts: countsOf(list) };
  emit();
  void fetch(`/api/notifications/${encodeURIComponent(id)}/read`, { method: "PATCH", credentials: "include" }).catch(() => undefined);
}

export function markAllNotificationsRead(): void {
  const list = snapshot.list.map((n) => ({ ...n, unread: false }));
  snapshot = { list, counts: countsOf(list) };
  emit();
  void fetch(`/api/notifications/mark-all-read`, { method: "PATCH", credentials: "include" }).catch(() => undefined);
}

export function useNotifications(): { list: Notification[]; counts: NotificationCounts; loading: boolean; error: string | null; reload: () => void } {
  const [, force] = useState(0);
  useEffect(() => {
    const l = () => force((x) => x + 1);
    listeners.add(l);
    if (!loaded && !loading) void loadNotifications();
    const onLive = () => void loadNotifications();
    window.addEventListener("edify:realtime", onLive);
    return () => { listeners.delete(l); window.removeEventListener("edify:realtime", onLive); };
  }, []);
  const reload = useCallback(() => void loadNotifications(), []);
  return { list: snapshot.list, counts: snapshot.counts, loading: loading && !loaded, error, reload };
}
