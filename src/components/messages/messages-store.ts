"use client";

// messages-store — backend-backed (no mock). The message bell badge + drawer
// read the same snapshot fetched from /api/messages (recent + counts), refresh
// on live SSE events, and write read-state through to the backend. Empty when
// the database has no inbox messages; never fabricated.
//
// Mirrors notifications-store.ts. Scope is intentionally the THIN backend
// messages module (recent / counts / mark-read) — there is no thread-body or
// compose backend, so the full message center is left on its existing surface.

import { useCallback, useEffect, useState } from "react";
import { csrfHeaders } from "@/lib/csrf-client";
import type {
  Message,
  MessagePriority,
  MessageCategory,
  MessageStatus,
} from "@/lib/messages-v2/types";

// ─── Backend record shape (Prisma Message + included relations) ───
export type BackendMessage = {
  id: string;
  threadId: string;
  senderId: string;
  recipientId: string | null;
  body: string;
  category: string | null;
  priority: "low" | "normal" | "high" | "urgent" | string;
  actionRequired: boolean;
  status: "unread" | "read" | "archived" | string;
  createdAt: string;
  thread?: { subject?: string | null } | null;
  sender?: { name?: string | null } | null;
};

type Snapshot = { list: Message[]; counts: MessageCounts };
export type MessageCounts = { all: number; unread: number; action: number; urgent: number };

let snapshot: Snapshot = { list: [], counts: { all: 0, unread: 0, action: 0, urgent: 0 } };
let loaded = false;
let loading = false;
let error: string | null = null;
const listeners = new Set<() => void>();
function emit() { for (const l of listeners) l(); }

const PRIORITY_MAP: Record<string, MessagePriority> = {
  low: "Normal",
  normal: "Normal",
  high: "Important",
  urgent: "Urgent",
  critical: "Critical",
};

const VALID_CATEGORIES = new Set<MessageCategory>([
  "field-debrief", "partner-debrief", "evidence-review", "correction-request",
  "payment-update", "planning-assignment", "partner-scheduling", "school-followup",
  "cluster-update", "ssa-update", "finance", "hr-support", "system-notification",
  "leadership-decision", "general",
]);

function initialsOf(name: string): string {
  return name
    .split(/\s+/)
    .map((n) => n[0])
    .filter(Boolean)
    .join("")
    .slice(0, 2)
    .toUpperCase() || "—";
}

// Adapt a thin backend record to the rich frontend Message shape. The drawer
// only reads a subset (subject / preview / sender / status / priority /
// category / createdAt / recipients[].actionRequired). The remaining fields
// are populated with safe defaults so the type stays valid.
function adaptMessage(m: BackendMessage): Message {
  const status: MessageStatus =
    m.status === "read" ? "read" :
    m.status === "archived" ? "archived" :
    m.actionRequired ? "action_required" : "unread";
  const priority = PRIORITY_MAP[m.priority] ?? "Normal";
  const category: MessageCategory =
    m.category && VALID_CATEGORIES.has(m.category as MessageCategory)
      ? (m.category as MessageCategory)
      : "general";
  const senderName = m.sender?.name ?? "Edify";
  const subject = m.thread?.subject ?? "(no subject)";
  const preview = (m.body ?? "").replace(/\s+/g, " ").trim().slice(0, 180);

  return {
    id: m.id,
    subject,
    preview,
    body: m.body ?? "",
    senderId: m.senderId,
    senderName,
    senderEmail: "",
    senderRole: "System",
    senderInitials: initialsOf(senderName),
    threadId: m.threadId,
    recipients: m.recipientId
      ? [{
          id: `${m.id}-r`,
          messageId: m.id,
          userId: m.recipientId,
          recipientName: "",
          recipientEmail: "",
          recipientRole: "System",
          status,
          deliveredAt: m.createdAt,
          actionRequired: m.actionRequired,
        }]
      : [],
    recipientRoles: [],
    createdAt: m.createdAt,
    updatedAt: m.createdAt,
    status,
    priority,
    category,
    context: { type: "general_internal", id: "general-internal", label: "Internal" },
    contexts: [{ type: "general_internal", id: "general-internal", label: "Internal" }],
    contextMode: "single",
    isSystemGenerated: true,
  };
}

function isUnread(m: Message) { return m.status === "unread" || m.status === "action_required"; }
function isAction(m: Message) {
  return m.status === "action_required" ||
    m.recipients.some((r) => r.actionRequired && (r.status === "unread" || r.status === "action_required"));
}
function isUrgent(m: Message) { return m.priority === "Urgent" || m.priority === "Critical"; }

function countsOf(list: Message[]): MessageCounts {
  return {
    all: list.length,
    unread: list.filter(isUnread).length,
    action: list.filter((m) => isUnread(m) && isAction(m)).length,
    urgent: list.filter((m) => isUnread(m) && isUrgent(m)).length,
  };
}

export async function loadMessages(): Promise<void> {
  if (loading) return;
  loading = true; error = null; emit();
  try {
    const res = await fetch("/api/messages", { credentials: "include" });
    const j = await res.json();
    if (!res.ok || j.live === false) {
      error = j.error || "Could not load messages";
    } else {
      const list = (j.recent as BackendMessage[]).map(adaptMessage);
      const base = countsOf(list);
      // Prefer backend unread (counts the full inbox, not just the recent slice).
      const counts: MessageCounts = j.counts
        ? { all: list.length, unread: j.counts.unread ?? base.unread, action: j.counts.actionRequired ?? base.action, urgent: base.urgent }
        : base;
      snapshot = { list, counts };
    }
  } catch {
    error = "Could not reach the server";
  }
  loaded = true; loading = false; emit();
}

export function markMessageRead(id: string): void {
  const list = snapshot.list.map((m) => (m.id === id ? { ...m, status: "read" as MessageStatus } : m));
  snapshot = { list, counts: countsOf(list) };
  emit();
  void fetch(`/api/messages/${encodeURIComponent(id)}/read`, { method: "PATCH", credentials: "include", headers: { ...csrfHeaders() } }).catch(() => undefined);
}

export function markAllMessagesRead(): void {
  const list = snapshot.list.map((m) => ({ ...m, status: "read" as MessageStatus }));
  snapshot = { list, counts: countsOf(list) };
  emit();
}

type MessagesState = {
  list: Message[];
  counts: MessageCounts;
  loading: boolean;
  error: string | null;
  reload: () => void;
};

export function useMessages(): MessagesState {
  const [, force] = useState(0);
  useEffect(() => {
    const l = () => force((x) => x + 1);
    listeners.add(l);
    if (!loaded && !loading) void loadMessages();
    const onLive = () => void loadMessages();
    window.addEventListener("edify:realtime", onLive);
    return () => { listeners.delete(l); window.removeEventListener("edify:realtime", onLive); };
  }, []);
  const reload = useCallback(() => void loadMessages(), []);
  return { list: snapshot.list, counts: snapshot.counts, loading: loading && !loaded, error, reload };
}
