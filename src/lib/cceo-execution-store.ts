// CCEO Execution Store — client-side persisted state for the day-of
// execution loop. Sits alongside the server-side engine and survives
// reloads via localStorage.
//
// Responsibilities:
//   • VisitCompletion records (one per todo when the CCEO closes a visit)
//   • RealtimeBlocker records (raised mid-day, not at end-of-day debrief)
//   • Plan Builder batch approval status (PL Reviewing / Approved / Returned)
//   • Daily-debrief streak counter
//
// Pure client-side — no "server-only", no imports from server modules.

import type { DebriefBarrier } from "@/lib/field-intelligence-mock";

// ────────── Types ──────────

// Salesforce is the system of record for the actual evidence (photos,
// attendance, signatures, scores). The dashboard only needs the SF ID to
// confirm the activity was logged. Visit ID covers school / partner /
// follow-up / SSA visits; Training ID covers cluster trainings + meetings.
export type SalesforceIdKind = "Visit ID" | "Training ID";

export type VisitCompletion = {
  schoolId:         string;
  activityId:       string;
  completedAt:      string;
  salesforceId:     string;            // e.g. "SF-VST-2401" / "SF-TRN-1207"
  salesforceIdKind: SalesforceIdKind;
  note:             string;            // optional one-liner from the CCEO
};

export type RealtimeBlocker = {
  id:        string;
  raisedAt:  string;
  schoolId?: string;
  schoolName?: string;
  category:  DebriefBarrier | "Other";
  note:      string;
  photoTaken: boolean;
  status:    "Open" | "Acknowledged" | "Resolved";
};

export type BatchApprovalStatus = "PL Reviewing" | "Approved" | "Returned";

export type BatchApprovalRecord = {
  batchId:      string;
  status:       BatchApprovalStatus;
  reviewedAt?:  string;
  reviewerNote?:string;
};

export type DebriefStreak = {
  lastSubmittedDate: string | null;   // YYYY-MM-DD
  current:           number;          // consecutive working days
  best:              number;
};

// ────────── localStorage keys ──────────

const KEY_COMPLETIONS = "cceo.visitCompletions";
const KEY_BLOCKERS    = "cceo.realtimeBlockers";
const KEY_APPROVALS   = "cceo.batchApprovals";
const KEY_STREAK      = "cceo.debriefStreak";

// ────────── Visit completions ──────────

export function loadCompletions(): Record<string, VisitCompletion> {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(KEY_COMPLETIONS);
    return raw ? (JSON.parse(raw) as Record<string, VisitCompletion>) : {};
  } catch { return {}; }
}

export function saveCompletion(c: VisitCompletion): void {
  if (typeof window === "undefined") return;
  const all = loadCompletions();
  all[c.activityId] = c;
  try { window.localStorage.setItem(KEY_COMPLETIONS, JSON.stringify(all)); } catch {/* ignore */}
}

export function clearCompletions(): void {
  if (typeof window === "undefined") return;
  try { window.localStorage.removeItem(KEY_COMPLETIONS); } catch {/* ignore */}
}

// ────────── Real-time blockers ──────────

export function loadBlockers(): RealtimeBlocker[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(KEY_BLOCKERS);
    return raw ? (JSON.parse(raw) as RealtimeBlocker[]) : [];
  } catch { return []; }
}

export function saveBlocker(b: RealtimeBlocker): void {
  if (typeof window === "undefined") return;
  const all = loadBlockers();
  all.unshift(b);
  try { window.localStorage.setItem(KEY_BLOCKERS, JSON.stringify(all.slice(0, 50))); } catch {/* ignore */}
}

export function clearBlockers(): void {
  if (typeof window === "undefined") return;
  try { window.localStorage.removeItem(KEY_BLOCKERS); } catch {/* ignore */}
}

// Today's blockers (used by the PL Team Daily Debriefs card surfacer).
export function blockersForToday(now: Date = new Date()): RealtimeBlocker[] {
  const today = now.toISOString().slice(0, 10);
  return loadBlockers().filter((b) => b.raisedAt.slice(0, 10) === today);
}

// ────────── Batch approval status loop ──────────
//
// Plan Builder submits batches to "PL approval queue". This store layers a
// client-side simulated lifecycle so the CCEO sees status feedback after
// they submit (Reviewing → Approved | Returned-with-note).

export function loadApprovals(): Record<string, BatchApprovalRecord> {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(KEY_APPROVALS);
    return raw ? (JSON.parse(raw) as Record<string, BatchApprovalRecord>) : {};
  } catch { return {}; }
}

export function saveApproval(rec: BatchApprovalRecord): void {
  if (typeof window === "undefined") return;
  const all = loadApprovals();
  all[rec.batchId] = rec;
  try { window.localStorage.setItem(KEY_APPROVALS, JSON.stringify(all)); } catch {/* ignore */}
}

export function approvalStatusFor(batchId: string, fallback: BatchApprovalStatus = "PL Reviewing"): BatchApprovalStatus {
  return loadApprovals()[batchId]?.status ?? fallback;
}

// ────────── Daily debrief streak ──────────

const ZERO_STREAK: DebriefStreak = { lastSubmittedDate: null, current: 0, best: 0 };

export function loadStreak(): DebriefStreak {
  if (typeof window === "undefined") return ZERO_STREAK;
  try {
    const raw = window.localStorage.getItem(KEY_STREAK);
    return raw ? (JSON.parse(raw) as DebriefStreak) : ZERO_STREAK;
  } catch { return ZERO_STREAK; }
}

export function recordDebriefSubmission(now: Date = new Date()): DebriefStreak {
  if (typeof window === "undefined") return ZERO_STREAK;
  const today = now.toISOString().slice(0, 10);
  const prev  = loadStreak();
  if (prev.lastSubmittedDate === today) return prev; // already counted today
  const yesterday = new Date(now); yesterday.setDate(yesterday.getDate() - 1);
  const yest = yesterday.toISOString().slice(0, 10);
  const next: DebriefStreak = {
    lastSubmittedDate: today,
    current:           prev.lastSubmittedDate === yest ? prev.current + 1 : 1,
    best:              Math.max(prev.best, prev.lastSubmittedDate === yest ? prev.current + 1 : 1),
  };
  try { window.localStorage.setItem(KEY_STREAK, JSON.stringify(next)); } catch {/* ignore */}
  return next;
}

// ────────── Day / week helpers ──────────

const DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] as const;

export function todayShort(now: Date = new Date()): string {
  return DAY_NAMES[now.getDay()];
}

export function isFridayOrLater(now: Date = new Date()): boolean {
  const d = now.getDay();
  return d === 5 || d === 6;            // Fri / Sat
}

export function isLateInWeek(now: Date = new Date()): boolean {
  return now.getDay() >= 4;             // Thu+
}
