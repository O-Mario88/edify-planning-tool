// Planning page — unified status taxonomy + colour map.
//
// Before this file existed, every board on /planning shipped its own
// vocabulary:
//   • SchoolGapsBoard:       "Critical / High / Medium / Low"
//   • CoreSchoolCard:        "Blocked / Not started / Scheduled / Delivered / Verified / Completed"
//   • PlanningOwnershipSections: "Blocked / Pending / Scheduled / Delivered / Verified / Done"
//
// Three vocabularies for the same pipeline state. This module collapses
// them onto a single 6-step scale with one label + one colour pair,
// applied identically everywhere.
//
// Risk (Critical/High/Medium/Low) is intentionally NOT folded in — that
// axis is "how urgent is this gap?" which is orthogonal to pipeline
// state. It keeps its own colour scale.

import type { CoreActivityStatus } from "@/lib/planning/core-school-plan-mock";

// ────────── Canonical pipeline status ──────────

export type PlanningStatus =
  | "blocked"     // hard-gated, cannot proceed (e.g. SSA missing)
  | "pending"     // SSA done, activity in plan, no schedule yet
  | "scheduled"   // assigned to an owner + a date is set
  | "in_flight"   // delivered on the ground, awaiting verification
  | "verified"    // M&E-verified — counts toward 4/4 progress
  | "done";       // completed (synonym of verified for display purposes)

export const PLANNING_STATUS_LABEL: Record<PlanningStatus, string> = {
  blocked:   "Blocked",
  pending:   "Pending",
  scheduled: "Scheduled",
  in_flight: "Delivered",
  verified:  "Verified",
  done:      "Completed",
};

export type StatusTone = { bg: string; text: string; edge: string; ring: string };

export const PLANNING_STATUS_TONE: Record<PlanningStatus, StatusTone> = {
  blocked:   { bg: "bg-slate-100",   text: "text-slate-600",   edge: "bg-slate-400",   ring: "ring-slate-200" },
  pending:   { bg: "bg-rose-50",     text: "text-rose-700",    edge: "bg-rose-500",    ring: "ring-rose-100"  },
  scheduled: { bg: "bg-amber-50",    text: "text-amber-700",   edge: "bg-amber-500",   ring: "ring-amber-100" },
  in_flight: { bg: "bg-blue-50",     text: "text-blue-700",    edge: "bg-blue-500",    ring: "ring-blue-100"  },
  verified:  { bg: "bg-emerald-50",  text: "text-emerald-700", edge: "bg-emerald-500", ring: "ring-emerald-100" },
  done:      { bg: "bg-emerald-50",  text: "text-emerald-700", edge: "bg-emerald-500", ring: "ring-emerald-100" },
};

// ────────── Adapters ──────────

/**
 * Map the per-activity status used by the core school plan mock into
 * the canonical PlanningStatus. Several activity states fold to the
 * same display bucket (verified == done; delivered → in_flight).
 */
export function toPlanningStatus(s: CoreActivityStatus): PlanningStatus {
  switch (s) {
    case "blocked":     return "blocked";
    case "not_started": return "pending";
    case "scheduled":   return "scheduled";
    case "delivered":   return "in_flight";
    case "verified":    return "verified";
    case "completed":   return "done";
  }
}

// ────────── Risk axis (kept separate) ──────────
//
// Risk answers "how urgent is the gap?" — Critical means days, Low means
// weeks. Distinct from PlanningStatus.

export type RiskLevel = "Critical" | "High" | "Medium" | "Low";

export const RISK_TONE: Record<RiskLevel, { bg: string; text: string; edge: string }> = {
  Critical: { bg: "bg-rose-100",     text: "text-rose-800",    edge: "bg-rose-600"    },
  High:     { bg: "bg-rose-50",      text: "text-rose-700",    edge: "bg-rose-500"    },
  Medium:   { bg: "bg-amber-50",     text: "text-amber-700",   edge: "bg-amber-500"   },
  Low:      { bg: "bg-emerald-50",   text: "text-emerald-700", edge: "bg-emerald-500" },
};
