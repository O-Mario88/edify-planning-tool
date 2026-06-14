"use client";

// notifications-store — backend-backed (no mock). The bell badge + drawer read
// the same snapshot fetched from /api/notifications (recent + counts), refresh
// on live SSE events, and write read-state through to the backend. Empty when
// the database has no notifications; never fabricated.

import { useCallback, useEffect, useState } from "react";
import { csrfHeaders } from "@/lib/csrf-client";
import { adaptNotification, adaptCommandCenterItem, type Notification, type NotificationCounts, type BackendNotification, type CommandCenterItem } from "./notifications-types";

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

// Locally-dismissed command-center alerts (no backend id to mark read). They
// reappear on the next reload if still unresolved — a red alert can't be
// permanently silenced, only acted on. Cleared whenever the feed refreshes.
const dismissedCc = new Set<string>();

export async function loadNotifications(): Promise<void> {
  if (loading) return;
  loading = true; error = null; emit();
  try {
    // Backend notifications (Updates) + the live recommendation feed (red alerts
    // / required actions) load in parallel and merge into one bell + drawer.
    const [notifRes, ccRes] = await Promise.allSettled([
      fetch("/api/notifications", { credentials: "include" }).then((r) => r.json()),
      fetch("/api/command-center/today", { credentials: "include" }).then((r) => r.json()),
    ]);

    let backendList: Notification[] = [];
    let backendUnread = 0;
    let backendAction = 0;
    if (notifRes.status === "fulfilled" && notifRes.value?.live !== false && Array.isArray(notifRes.value?.recent)) {
      backendList = (notifRes.value.recent as BackendNotification[]).map(adaptNotification);
      const base = countsOf(backendList);
      backendUnread = notifRes.value.counts?.unread ?? base.unread;
      backendAction = notifRes.value.counts?.actionRequired ?? base.action;
    } else if (notifRes.status === "fulfilled" && notifRes.value?.error) {
      error = notifRes.value.error;
    }

    // Command-center rollups become push notifications (one per red-alert type).
    let ccNotifs: Notification[] = [];
    if (ccRes.status === "fulfilled" && ccRes.value?.live && Array.isArray(ccRes.value?.groups)) {
      const items: CommandCenterItem[] = ccRes.value.groups
        .flatMap((g: { items: CommandCenterItem[] }) => g.items)
        .filter((i: CommandCenterItem) => i.count != null);
      ccNotifs = items.map(adaptCommandCenterItem).filter((n) => !dismissedCc.has(n.id));
    }

    const list = [...ccNotifs, ...backendList];
    const ccUrgent = ccNotifs.filter((n) => n.priority === "urgent" || n.priority === "critical").length;
    snapshot = {
      list,
      counts: {
        all: list.length,
        unread: ccNotifs.length + backendUnread,
        action: ccNotifs.length + backendAction,
        urgent: ccUrgent + countsOf(backendList).urgent,
      },
    };
  } catch {
    error = "Could not reach the server";
  }
  loaded = true; loading = false; emit();
}

export function markNotificationRead(id: string): void {
  const list = snapshot.list.map((n) => (n.id === id ? { ...n, unread: false } : n));
  snapshot = { list, counts: countsOf(list) };
  emit();
  // Command-center alerts have no backend row — dismiss locally (reappears next
  // reload if still unresolved). Only persist read-state for real notifications.
  if (id.startsWith("cc-")) { dismissedCc.add(id); return; }
  void fetch(`/api/notifications/${encodeURIComponent(id)}/read`, { method: "PATCH", credentials: "include", headers: { ...csrfHeaders() } }).catch(() => undefined);
}

export function markAllNotificationsRead(): void {
  for (const n of snapshot.list) if (n.id.startsWith("cc-")) dismissedCc.add(n.id);
  const list = snapshot.list.map((n) => ({ ...n, unread: false }));
  snapshot = { list, counts: countsOf(list) };
  emit();
  void fetch(`/api/notifications/mark-all-read`, { method: "PATCH", credentials: "include", headers: { ...csrfHeaders() } }).catch(() => undefined);
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
