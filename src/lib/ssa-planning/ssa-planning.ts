// SSA-driven planning recommendations.
//
// Product principle: SSA should not only show school weakness — it
// should help staff act on it.
//
// Given a school's SSA snapshot (overall score + which intervention
// area is weakest + recent support history), this engine produces
// one or more ActionItems with the right "Add to Plan" CTA already
// pre-populated. They flow through the same role-action-engine path
// every other ActionItem follows, so the recommendation appears in
// the CCEO's Next-3 + Inbox automatically.

import type { ActionItem } from "@/lib/actions/action-types";

// ────────── Inputs ──────────

export type SsaSchoolSnapshot = {
  schoolId: string;
  schoolName: string;
  districtId: string;
  /// 0..10 — full-school average.
  ssaScore: number;
  /// The intervention area where the school is weakest.
  weakestArea: SsaInterventionArea;
  /// Sub-score 0..10 in that area.
  weakestAreaScore: number;
  /// Days since the last support activity in this area (any kind).
  daysSinceLastSupportInArea: number | null;
  /// The CCEO assigned to this school's portfolio.
  assignedCceoId: string;
  /// Optional: cost setting for the suggested activity (engine pre-
  /// fills the budget hint when known).
  suggestedActivityCostUgx?: number;
};

export type SsaInterventionArea =
  | "TeachingAndLearning"
  | "LearningEnvironment"
  | "LeadershipAndGovernance"
  | "ParentAndCommunityEngagement"
  | "StudentWellbeing"
  | "AssessmentAndDataUse";

// ────────── Recommendation rule set ──────────
//
// For each area + severity band, the engine knows the canonical
// "next-best" support activity. These are concrete, named — not
// generic "do something" suggestions.

const ACTIVITY_FOR_AREA: Record<SsaInterventionArea, { title: string; kind: string }> = {
  TeachingAndLearning:         { title: "Schedule in-school coaching session", kind: "InSchoolCoaching" },
  LearningEnvironment:         { title: "Run a learning-environment audit",    kind: "EnvironmentAudit" },
  LeadershipAndGovernance:     { title: "Coach school leadership",             kind: "LeadershipCoaching" },
  ParentAndCommunityEngagement:{ title: "Convene a parent-community meeting",  kind: "CommunityMeeting" },
  StudentWellbeing:            { title: "Run a wellbeing check-in visit",      kind: "WellbeingVisit" },
  AssessmentAndDataUse:        { title: "Coach teachers on assessment use",    kind: "AssessmentCoaching" },
};

// ────────── Public API ──────────

export function recommendedActionsForSchool(
  snap: SsaSchoolSnapshot,
  /// Optional date offset for the suggested due date. Defaults to
  /// 14 days out, leaves room in the CCEO's plan to schedule.
  dueDateInDays: number = 14,
): ActionItem[] {
  // Don't recommend on schools without a real signal.
  if (snap.ssaScore == null || snap.weakestAreaScore == null) return [];

  // Severity bands drive priority + risk level.
  const severity = severityBand(snap.weakestAreaScore);
  if (severity === "Healthy") return []; // nothing to recommend

  const recipe = ACTIVITY_FOR_AREA[snap.weakestArea];
  const due = isoOffsetDays(dueDateInDays);

  const item: ActionItem = {
    id: `ssa-rec-${snap.schoolId}-${snap.weakestArea}`,
    role: "CCEO",
    priority: severity === "Critical" ? 1 : severity === "AtRisk" ? 2 : 3,
    category: "SchoolRisk",
    title: `${recipe.title}: ${snap.schoolName}`,
    description: explain(snap, severity),
    affectedEntity: { kind: "School", id: snap.schoolId, label: snap.schoolName },
    dueDate: due,
    riskLevel:
      severity === "Critical" ? "Critical" :
      severity === "AtRisk"   ? "High"     :
                                "Medium",
    status: "Pending",
    approvalSafety: "SafeToApprove",
    primaryAction: {
      // Concrete + pre-filled: the existing /plans/new route already
      // accepts school + activity-kind query params.
      label: "Add to plan",
      intent: "submit",
      href: `/plans/new?schoolId=${encodeURIComponent(snap.schoolId)}&activityKind=${encodeURIComponent(recipe.kind)}&suggestedBy=ssa`,
    },
    secondaryAction: {
      label: "Open school",
      intent: "open",
      href: `/schools?focus=${encodeURIComponent(snap.schoolId)}`,
    },
    sourceModule: "ssa",
    inboxTab: severity === "Critical" ? "NeedsApproval" : "NeedsFollowUp",
  };

  return [item];
}

// ────────── Helpers ──────────

type Severity = "Healthy" | "Watch" | "AtRisk" | "Critical";

function severityBand(score: number): Severity {
  if (score >= 7) return "Healthy";
  if (score >= 5.5) return "Watch";
  if (score >= 4) return "AtRisk";
  return "Critical";
}

function explain(snap: SsaSchoolSnapshot, severity: Severity): string {
  const areaLabel = snap.weakestArea.replace(/([A-Z])/g, " $1").trim();
  const gap = snap.daysSinceLastSupportInArea;
  const gapClause = gap == null
    ? "No support recorded yet in this area."
    : gap > 60
      ? `${gap} days since last support in this area — overdue.`
      : `Last support in this area was ${gap} days ago.`;

  if (severity === "Critical") {
    return `${areaLabel} score is ${snap.weakestAreaScore.toFixed(1)}/10 — at-risk band. ${gapClause}`;
  }
  if (severity === "AtRisk") {
    return `${areaLabel} score is ${snap.weakestAreaScore.toFixed(1)}/10. ${gapClause} Coaching here lifts the SSA fastest.`;
  }
  return `${areaLabel} is the weakest dimension at this school (${snap.weakestAreaScore.toFixed(1)}/10). ${gapClause}`;
}

function isoOffsetDays(days: number, now: Date = new Date()): string {
  const d = new Date(now);
  d.setDate(now.getDate() + days);
  return d.toISOString();
}

// ────────── Bulk helper ──────────
//
// Given many school snapshots, return the union of recommendations.
// Used by role-action-engine to inject SSA recs into the CCEO inbox.

export function recommendedActionsForPortfolio(snapshots: SsaSchoolSnapshot[]): ActionItem[] {
  const out: ActionItem[] = [];
  for (const s of snapshots) {
    for (const item of recommendedActionsForSchool(s)) out.push(item);
  }
  // Sort: highest priority (lowest priority number) first.
  return out.sort((a, b) => a.priority - b.priority);
}
