// Escalation Rules (spec layer #8).
//
// Ignored work escalates on a ladder: Day 1 notify the owner → Day 2 remind →
// Day 3 escalate to the supervisor (PL) → Day 5+ surface on the CD risk summary.
// Computed deterministically on-read from each item's age + stage (no cron, no
// background job) so it's always correct and reproducible — the production swap
// is a BullMQ reminder that reads the same levels.
//
// server-only: reads the Unified Activity model.

import "server-only";

import { allUnifiedActivities } from "@/lib/activity/unified-activity-source";
import { isOpenActivity, type UnifiedActivity } from "@/lib/activity/unified-activity";

export type EscalationLevel = 1 | 2 | 3 | 4;
export type EscalationAudience = "owner" | "supervisor" | "country_director";

export type EscalationItem = {
  id: string;
  category: string;
  label: string;
  detail: string;
  ageDays: number;
  level: EscalationLevel;
  audience: EscalationAudience;
  action: string;
  href?: string;
};

const LEVEL_META: Record<EscalationLevel, { audience: EscalationAudience; action: string }> = {
  1: { audience: "owner", action: "Notify owner" },
  2: { audience: "owner", action: "Remind owner" },
  3: { audience: "supervisor", action: "Escalate to Program Lead" },
  4: { audience: "country_director", action: "Add to CD risk summary" },
};

export const LEVEL_LABEL: Record<EscalationLevel, string> = {
  1: "Day 1 · Notify",
  2: "Day 2 · Remind",
  3: "Day 3 · Supervisor",
  4: "Day 5+ · CD risk",
};

/** The ladder: age in days → escalation level. */
export function levelForAge(ageDays: number): EscalationLevel {
  if (ageDays >= 5) return 4;
  if (ageDays >= 3) return 3;
  if (ageDays >= 2) return 2;
  return 1;
}

function dayDiff(fromIso: string | undefined, todayIso: string): number {
  if (!fromIso) return 0;
  const a = Date.parse(fromIso);
  const b = Date.parse(todayIso);
  if (Number.isNaN(a) || Number.isNaN(b)) return 0;
  return Math.max(0, Math.round((b - a) / 86_400_000));
}

// Which open stages escalate, and how each reads to the owner.
const STAGE_RULE: Partial<Record<UnifiedActivity["stage"], { category: string; action: string; href: string }>> = {
  evidence_pending: { category: "Missing evidence", action: "Upload evidence", href: "/evidence" },
  salesforce_pending: { category: "Missing Salesforce ID", action: "Enter Salesforce ID", href: "/evidence" },
  ia_pending: { category: "IA verification pending", action: "IA to verify", href: "/data-verification" },
  ia_returned: { category: "Returned by IA", action: "Fix & resubmit", href: "/evidence" },
  payment_pending: { category: "Payment pending", action: "Clear payment", href: "/disbursements" },
};

export function escalations(opts: { todayIso?: string } = {}): EscalationItem[] {
  const todayIso = opts.todayIso ?? new Date().toISOString().slice(0, 10);
  const items: EscalationItem[] = [];

  for (const a of allUnifiedActivities().filter(isOpenActivity)) {
    // Overdue scheduled activity — past its date but never started.
    if (a.stage === "planned" && a.scheduledDate && a.scheduledDate < todayIso) {
      const age = dayDiff(a.scheduledDate, todayIso);
      const level = levelForAge(age);
      items.push({
        id: `overdue-${a.id}`,
        category: "Overdue activity",
        label: a.title,
        detail: `Scheduled ${a.scheduledDate}, not started — ${age} day(s) overdue.`,
        ageDays: age,
        level,
        audience: LEVEL_META[level].audience,
        action: LEVEL_META[level].action,
        href: "/my-plan",
      });
      continue;
    }
    const rule = STAGE_RULE[a.stage];
    if (!rule) continue;
    const age = dayDiff(a.updatedAt, todayIso);
    if (age < 1) continue; // only escalates once it's been ignored a day
    const level = levelForAge(age);
    items.push({
      id: `${a.stage}-${a.id}`,
      category: rule.category,
      label: a.title,
      detail: `${rule.category} for ${age} day(s).`,
      ageDays: age,
      level,
      audience: LEVEL_META[level].audience,
      action: `${rule.action} (${LEVEL_META[level].action.toLowerCase()})`,
      href: rule.href,
    });
  }

  // Most-escalated first.
  return items.sort((x, y) => y.level - x.level || y.ageDays - x.ageDays);
}

/** The CD's risk view — everything that reached Day-5 escalation. */
export function cdRiskSummary(opts: { todayIso?: string } = {}): EscalationItem[] {
  return escalations(opts).filter((i) => i.level === 4);
}

/** Counts per level — for a compact ladder header. */
export function escalationCounts(opts: { todayIso?: string } = {}): Record<EscalationLevel, number> {
  const counts: Record<EscalationLevel, number> = { 1: 0, 2: 0, 3: 0, 4: 0 };
  for (const i of escalations(opts)) counts[i.level] += 1;
  return counts;
}
