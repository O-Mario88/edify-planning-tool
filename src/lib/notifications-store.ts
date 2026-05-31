"use client";

// notifications-store — ONE shared client store for notification read
// state, so the bell badge and the drawer never disagree. Before this,
// the drawer tracked `readIds` locally while the bell read a static
// `unreadNotificationCount` const — so marking a notification read never
// updated the badge. Now both read from here.
//
// This is the substrate the live SSE stream will plug into next: an
// `addStreamed()` entry point can push workflow-emitted rows onto the
// list, and both surfaces re-render from the same snapshot.

import { useSyncExternalStore } from "react";
import { NOTIFICATIONS, type Notification } from "./notifications-mock";

let readIds = new Set<string>();
const listeners = new Set<() => void>();
function emit() {
  for (const l of listeners) l();
}
function subscribe(l: () => void): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}

// Snapshot caching — useSyncExternalStore requires getSnapshot to return
// a referentially-stable value when nothing changed, or React loops.
function compute(r: Set<string>): Notification[] {
  return NOTIFICATIONS.map((n) => ({ ...n, unread: n.unread && !r.has(n.id) }));
}
const INITIAL = compute(new Set());
let cacheKey = readIds;
let cacheList = INITIAL;
function getSnapshot(): Notification[] {
  if (readIds !== cacheKey) {
    cacheKey = readIds;
    cacheList = compute(readIds);
  }
  return cacheList;
}
function getServerSnapshot(): Notification[] {
  return INITIAL;
}

// ─── mutations ───
export function markNotificationRead(id: string): void {
  if (readIds.has(id)) return;
  readIds = new Set(readIds);
  readIds.add(id);
  emit();
}

export function markAllNotificationsRead(): void {
  readIds = new Set(NOTIFICATIONS.map((n) => n.id));
  emit();
}

// ─── hook ───
export type NotificationCounts = {
  all: number;
  unread: number;
  action: number;
  urgent: number;
};

export function useNotifications(): {
  list: Notification[];
  counts: NotificationCounts;
} {
  const list = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const counts: NotificationCounts = {
    all: list.length,
    unread: list.filter((n) => n.unread).length,
    action: list.filter((n) => n.unread && n.actionRequired).length,
    urgent: list.filter(
      (n) => n.unread && (n.priority === "urgent" || n.priority === "critical"),
    ).length,
  };
  return { list, counts };
}
