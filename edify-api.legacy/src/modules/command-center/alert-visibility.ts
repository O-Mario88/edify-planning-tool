import { NotificationPriority } from '@prisma/client';

// ── Command-center alert visibility (spec §13) ──────────────────────────────
//
// Command-center alerts are PERSISTENT operational risks generated from data
// conditions. The spec rule that makes them different from notifications:
//
//   • an alert is keyed by a stable conditionHash — the SAME unresolved
//     condition maps to ONE open row;
//   • a user may dismiss it TEMPORARILY (CommandCenterAlertDismissal carries a
//     `dismissedUntil`);
//   • the alert REAPPEARS once the dismissal window passes IF still unresolved;
//   • it disappears for good only when the underlying issue is resolved.
//
// This module is the pure decision layer (no DB, no Nest) so the reappear-while-
// unresolved behaviour can be exhaustively unit-tested (spec §20).

/** A single data condition the generator evaluates each run. */
export type AlertConditionResult = {
  alertType: string;
  severity: NotificationPriority;
  scope: string;
  title: string;
  body: string;
  targetRoute: string;
  contextType?: string;
  /** The live count behind the condition. 0 → the issue is resolved. */
  count: number;
};

/** Stable identity for a condition — one open row per (type, scope). Re-running
 *  the generator upserts the same row instead of creating duplicates. */
export function conditionHash(alertType: string, scope: string): string {
  return `${alertType}:${scope}`;
}

export type OpenAlert = {
  id: string;
  alertType: string;
  severity: NotificationPriority;
  scope: string | null;
  title: string;
  body: string | null;
  targetRoute: string | null;
  contextType: string | null;
  contextId: string | null;
  conditionHash: string;
  createdAt: Date;
  updatedAt: Date;
};

export type Dismissal = { alertId: string; dismissedUntil: Date };

/**
 * Decide which OPEN alerts a user should currently SEE. An alert is hidden only
 * while a dismissal window is still in the future; once it lapses the alert
 * reappears (spec §13 — by design, not a bug). Resolved alerts are never passed
 * in here (the caller queries status='open').
 */
export function visibleAlerts(open: OpenAlert[], dismissals: Dismissal[], now: Date = new Date()): OpenAlert[] {
  const hiddenUntil = new Map<string, number>();
  for (const d of dismissals) hiddenUntil.set(d.alertId, d.dismissedUntil.getTime());
  return open.filter((a) => {
    const until = hiddenUntil.get(a.id);
    return until === undefined || until <= now.getTime();
  });
}

const SEVERITY_RANK: Record<NotificationPriority, number> = { urgent: 0, high: 1, normal: 2, low: 3 };

/** Sort most-severe first, then newest — the order the rail/command center renders. */
export function sortAlerts<T extends { severity: NotificationPriority; createdAt: Date }>(alerts: T[]): T[] {
  return [...alerts].sort((a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity] || b.createdAt.getTime() - a.createdAt.getTime());
}

/** Summary buckets for GET /command-center/alerts/summary (spec §17). */
export function summarize(alerts: { severity: NotificationPriority }[]): {
  total: number;
  urgent: number;
  high: number;
  normal: number;
  low: number;
} {
  const s = { total: alerts.length, urgent: 0, high: 0, normal: 0, low: 0 };
  for (const a of alerts) s[a.severity] += 1;
  return s;
}
