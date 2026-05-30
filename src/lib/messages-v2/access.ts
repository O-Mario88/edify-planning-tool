// Role-based access. `messagesForUser` returns the slice of messages
// the signed-in user is allowed to see (anything they sent or where
// they're a recipient); `messageByIdForUser` does a permission-checked
// single fetch (callers use this in detail pages so a partner can't
// read an HR-only message by id-guessing).
//
// Sent vs Inbox: a message is "sent" by the user if their userId
// matches `senderId`; otherwise it's an "inbox" message. The same
// store backs both folders.

import type { EdifyRole } from "@/lib/auth-public";
import type { DemoUser } from "@/lib/auth";
import { allMessages, messageById } from "./mock";
import type { Message, MessageRecipient } from "./types";

export type MessageFolder = "inbox" | "sent";

export function messagesForUser(user: DemoUser, folder: MessageFolder = "inbox"): Message[] {
  const all = allMessages();
  const own = folder === "sent"
    ? all.filter((m) => m.senderId === user.staffId || m.senderEmail === user.email)
    : all.filter((m) => isRecipient(m, user));

  // Inbox + Sent show ONE row per thread (the most recent message).
  // The detail page renders the full thread; the list is a digest.
  const latestByThread = new Map<string, Message>();
  for (const m of own) {
    const existing = latestByThread.get(m.threadId);
    if (!existing || m.createdAt > existing.createdAt) {
      latestByThread.set(m.threadId, m);
    }
  }
  return [...latestByThread.values()].sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}

export function messageByIdForUser(
  id: string,
  user: DemoUser,
): Message | undefined {
  const m = messageById(id);
  if (!m) return undefined;
  // Visible if: admin, sender, or a recipient.
  if (user.role === "Admin") return m;
  if (m.senderId === user.staffId || m.senderEmail === user.email) return m;
  return isRecipient(m, user) ? m : undefined;
}

function isRecipient(m: Message, user: DemoUser): boolean {
  return m.recipients.some((r) => r.userId === user.staffId || r.recipientEmail === user.email);
}

/** Returns the current user's per-user delivery record for this message
 *  (status, readAt, etc). Used by the detail page to show the user's
 *  own ack/resolve state, not the aggregate. */
export function recipientForUser(m: Message, user: DemoUser): MessageRecipient | undefined {
  return m.recipients.find((r) => r.userId === user.staffId || r.recipientEmail === user.email);
}

// Filter keys the spec mandates for the list page. `Action Required`
// + `Urgent` aren't categories — they're status/priority filters.
export type ListFilterKey =
  | "all"
  | "unread"
  | "action_required"
  | "urgent"
  | "debriefs"
  | "evidence"
  | "payments"
  | "planning"
  | "partner"
  | "school_followup"
  | "resolved"
  | "archived";

export function applyListFilter(messages: Message[], filter: ListFilterKey): Message[] {
  switch (filter) {
    case "all":              return messages.filter((m) => !m.archived);
    case "unread":           return messages.filter((m) => m.status === "unread");
    case "action_required":  return messages.filter((m) => m.status === "action_required");
    case "urgent":           return messages.filter((m) => m.priority === "Urgent" || m.priority === "Critical");
    case "debriefs":         return messages.filter((m) => m.category === "field-debrief" || m.category === "partner-debrief");
    case "evidence":         return messages.filter((m) => m.category === "evidence-review" || m.category === "correction-request");
    case "payments":         return messages.filter((m) => m.category === "payment-update" || m.category === "finance");
    case "planning":         return messages.filter((m) => m.category === "planning-assignment" || m.category === "partner-scheduling");
    case "partner":          return messages.filter((m) => m.senderRole === "Partner" || m.category === "partner-debrief" || m.category === "partner-scheduling");
    case "school_followup":  return messages.filter((m) => m.category === "school-followup" || m.category === "cluster-update");
    case "resolved":         return messages.filter((m) => m.status === "resolved");
    case "archived":         return messages.filter((m) => m.archived);
  }
}

// Free-text search across sender, subject, preview, and related entity
// names. Case-insensitive substring match — Phase 2 swaps for fuse.js
// fuzzy if the inbox grows.
export function applySearch(messages: Message[], query: string): Message[] {
  const q = query.trim().toLowerCase();
  if (!q) return messages;
  return messages.filter((m) =>
    m.subject.toLowerCase().includes(q) ||
    m.senderName.toLowerCase().includes(q) ||
    m.preview.toLowerCase().includes(q) ||
    (m.related?.schoolName?.toLowerCase().includes(q) ?? false) ||
    (m.related?.clusterName?.toLowerCase().includes(q) ?? false) ||
    (m.related?.partnerName?.toLowerCase().includes(q) ?? false) ||
    (m.related?.activityType?.toLowerCase().includes(q) ?? false),
  );
}

// Compact relative-time helper. Locale-stable output so server and
// client render the same string (avoids hydration mismatch). Uses
// hardcoded short month names and a manual hh:mm clock so en-GB vs
// en-US locale negotiation can't shift the output between renders.
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function sameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

function formatClock(d: Date): string {
  const hours = d.getHours();
  const minutes = d.getMinutes().toString().padStart(2, "0");
  const period = hours >= 12 ? "PM" : "AM";
  const h12 = hours % 12 === 0 ? 12 : hours % 12;
  return `${h12}:${minutes} ${period}`;
}

export function formatMessageTime(iso: string, now: Date = new Date()): string {
  const t = new Date(iso);
  if (sameDay(t, now)) return formatClock(t);
  const yest = new Date(now); yest.setDate(yest.getDate() - 1);
  if (sameDay(t, yest)) return "Yesterday";
  return `${MONTHS[t.getMonth()]} ${t.getDate()}`;
}

export function formatMessageFullTimestamp(iso: string): string {
  const d = new Date(iso);
  return `${MONTHS[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()} · ${formatClock(d)}`;
}
