// SSA recommendation engine — turns SSA gaps into concrete next actions. The
// Planning page never asks the user to guess; this function decides what each
// card should propose based on the SSA result, the gap kind, and the SSA gate.
//
// The returned object IS a PlanningRecommendation (gap-types.ts):
//   { primaryAction, primaryLabel, secondaryActions, reason, purpose?, intervention? }
// — primaryAction drives the card's primary button, primaryLabel is the
// human "Recommended:" sentence, secondaryActions render as chips.

import type {
  GapKind,
  PlanningActionKind,
  PlanningRecommendation,
  PlanningGap,
} from "./gap-types";

// ────────── SSA intervention domain ──────────
// Matches the existing core-school intervention names.
export type SsaIntervention =
  | "Teaching & Learning"
  | "Leadership Best Practice"
  | "Christ-like Behavior"
  | "Exposure to the Word of God"
  | "Fees / Budget / Accounts"
  | "Government Requirements"
  | "Learning Environment"
  | "Teaching Environment"
  | "Enrollment";

// ────────── Lookup: intervention → recommended action + sample purpose copy ──────────
export const INTERVENTION_TO_ACTION: Record<
  SsaIntervention,
  {
    primaryAction: PlanningActionKind;
    purpose: string;
  }
> = {
  "Teaching & Learning": {
    primaryAction: "SCHEDULE_IN_SCHOOL_TRAINING",
    purpose: "Classroom observation + coaching on teaching routines",
  },
  "Leadership Best Practice": {
    primaryAction: "SCHEDULE_VISIT",
    purpose: "Headteacher coaching visit on planning + delegation",
  },
  "Christ-like Behavior": {
    primaryAction: "SCHEDULE_CLUSTER_MEETING",
    purpose: "Cluster reflection on staff & student values",
  },
  "Exposure to the Word of God": {
    primaryAction: "SCHEDULE_VISIT",
    purpose: "Chaplaincy coaching visit + devotion review",
  },
  "Fees / Budget / Accounts": {
    primaryAction: "SCHEDULE_IN_SCHOOL_TRAINING",
    purpose: "Treasurer + bursar training on cash controls",
  },
  "Government Requirements": {
    primaryAction: "SCHEDULE_VISIT",
    purpose: "Compliance review visit — registration + inspection",
  },
  "Learning Environment": {
    primaryAction: "SCHEDULE_FOLLOW_UP_VISIT",
    purpose: "Walk-through visit — library, latrines, signage",
  },
  "Teaching Environment": {
    primaryAction: "SCHEDULE_IN_SCHOOL_TRAINING",
    purpose: "In-school training on classroom layout + materials",
  },
  Enrollment: {
    primaryAction: "SCHEDULE_CLUSTER_TRAINING",
    purpose: "Cluster training on enrolment campaigns + retention",
  },
};

// ────────── Helpers ──────────

const KNOWN_INTERVENTIONS = new Set<string>(Object.keys(INTERVENTION_TO_ACTION));

function asIntervention(name?: string): SsaIntervention | undefined {
  if (!name) return undefined;
  return KNOWN_INTERVENTIONS.has(name) ? (name as SsaIntervention) : undefined;
}

function interventionMapping(name?: string) {
  const iv = asIntervention(name);
  return iv ? { intervention: iv, ...INTERVENTION_TO_ACTION[iv] } : undefined;
}

function scoreLabel(score?: number): string {
  return typeof score === "number" ? `${score}/10` : "low score";
}

// Append the weakest-area focus to a base label when we know it.
function withFocus(base: string, weakest?: string): string {
  return weakest ? `${base} on ${weakest}` : base;
}

// The fields recommendForGap reads off a gap. Accepting a subset of
// PlanningGap means gap-mock can pass the whole gap (minus recommendation).
type RecommendInput = Pick<
  PlanningGap,
  | "kind"
  | "ssaGate"
  | "ssaWeakestArea"
  | "ssaSecondWeakest"
  | "ssaWeakestScore"
  | "schoolName"
  | "clusterName"
>;

// Convenience builder so every branch returns a complete, correctly-typed
// PlanningRecommendation without repeating the field names.
function rec(args: {
  primaryAction: PlanningActionKind;
  primaryLabel: string;
  secondaryActions?: PlanningActionKind[];
  reason: string;
  purpose?: string;
  intervention?: SsaIntervention;
}): PlanningRecommendation {
  return {
    primaryAction: args.primaryAction,
    primaryLabel: args.primaryLabel,
    secondaryActions: args.secondaryActions ?? [],
    reason: args.reason,
    purpose: args.purpose,
    intervention: args.intervention,
  };
}

// ────────── Main entry: given a gap + SSA snapshot, produce the recommendation ──────────
export function recommendForGap(input: RecommendInput): PlanningRecommendation {
  const {
    kind,
    ssaGate,
    ssaWeakestArea,
    ssaWeakestScore,
    schoolName,
    clusterName,
  } = input;

  // 1. SIT not done → schedule SIT (SSA happens during SIT). No secondaries.
  if (ssaGate === "SIT_NOT_DONE") {
    return rec({
      primaryAction: "SCHEDULE_SIT",
      primaryLabel: "Schedule School Improvement Training (SSA happens during SIT)",
      reason: "School Improvement Training has not been scheduled — SSA happens during SIT.",
      purpose: "Schedule School Improvement Training (SSA happens during SIT)",
    });
  }

  // 2. SIT done but SSA missing → only COMPLETE_SSA is allowed.
  if (ssaGate === "SIT_DONE_SSA_MISSING") {
    return rec({
      primaryAction: "COMPLETE_SSA",
      primaryLabel: "Complete the School Self-Assessment to unlock planning",
      reason: "Planning locked. SSA not completed.",
      purpose: "Complete the School Self-Assessment so planning can be unlocked",
    });
  }

  // Gaps whose whole point is the SSA itself.
  if (kind === "NO_SSA" || kind === "CORE_NO_SSA" || kind === "CLUSTER_SSA_MISSING") {
    return rec({
      primaryAction: "COMPLETE_SSA",
      primaryLabel: "Complete the School Self-Assessment",
      secondaryActions: ["VIEW_SCHOOL"],
      reason: "SSA has not been completed for this entity yet.",
    });
  }

  // From here on, SSA is complete. Build a weakest-intervention mapping we can
  // reuse across gap kinds.
  const weakestMap = interventionMapping(ssaWeakestArea);
  const weakestReason = ssaWeakestArea
    ? `Address weakest SSA area: ${ssaWeakestArea} (${scoreLabel(ssaWeakestScore)})`
    : undefined;

  // 3. NO_VISIT (SSA complete) → drive off weakest intervention.
  if (kind === "NO_VISIT") {
    const action = weakestMap?.primaryAction ?? "SCHEDULE_VISIT";
    return rec({
      primaryAction: action,
      primaryLabel: withFocus("Schedule a support visit", ssaWeakestArea),
      secondaryActions: ["ASSIGN_TO_PARTNER", "VIEW_SSA"],
      reason: weakestReason ?? "School has no recorded support visit — schedule one.",
      purpose: weakestMap?.purpose ?? "Schedule a support visit for this school",
      intervention: weakestMap?.intervention,
    });
  }

  // 4. NO_TRAINING (SSA complete) → force a training action.
  if (kind === "NO_TRAINING" || kind === "CLUSTER_TRAINING_NEEDED") {
    const mapped = weakestMap?.primaryAction;
    const isTrainingAction =
      mapped === "SCHEDULE_IN_SCHOOL_TRAINING" ||
      mapped === "SCHEDULE_GROUP_TRAINING" ||
      mapped === "SCHEDULE_CLUSTER_TRAINING";
    const action: PlanningActionKind =
      kind === "CLUSTER_TRAINING_NEEDED"
        ? "SCHEDULE_CLUSTER_TRAINING"
        : isTrainingAction
          ? (mapped as PlanningActionKind)
          : "SCHEDULE_IN_SCHOOL_TRAINING";
    return rec({
      primaryAction: action,
      primaryLabel: withFocus("Schedule training", ssaWeakestArea),
      secondaryActions: ["ASSIGN_TO_PARTNER", "VIEW_SSA"],
      reason: weakestReason ?? "No recorded training — schedule one aligned to the weakest SSA area.",
      purpose: weakestMap?.purpose ?? "Schedule training aligned to the weakest SSA area",
      intervention: weakestMap?.intervention,
    });
  }

  // 5. Training done, no follow-up → embed practices.
  if (kind === "TRAINING_DONE_NO_FOLLOWUP") {
    return rec({
      primaryAction: "SCHEDULE_FOLLOW_UP_VISIT",
      primaryLabel: "Schedule a follow-up visit to embed the training",
      secondaryActions: ["ASSIGN_TO_PARTNER"],
      reason: "Training completed — schedule follow-up to embed practices.",
      purpose: weakestMap?.purpose ?? "Follow-up visit to confirm training is embedded in practice",
      intervention: weakestMap?.intervention,
    });
  }

  // 6. No cluster → assign before scheduling cluster work.
  if (kind === "NO_CLUSTER") {
    return rec({
      primaryAction: "ADD_TO_CLUSTER",
      primaryLabel: "Add this school to a cluster",
      secondaryActions: ["VIEW_SCHOOL"],
      reason: "School is unclustered — assign before scheduling cluster work.",
      intervention: weakestMap?.intervention,
    });
  }

  // 7. SSA complete but nothing planned → propose the weakest-area action.
  if (kind === "SSA_COMPLETE_NOT_PLANNED") {
    const action = weakestMap?.primaryAction ?? "SCHEDULE_VISIT";
    return rec({
      primaryAction: action,
      primaryLabel: withFocus("Plan the next support action", ssaWeakestArea),
      secondaryActions: ["ASSIGN_TO_PARTNER", "ASSIGN_TO_SELF", "VIEW_SSA"],
      reason: weakestReason ?? "SSA is complete but no support has been planned yet.",
      purpose: weakestMap?.purpose ?? "Plan a support action aligned to the weakest SSA area",
      intervention: weakestMap?.intervention,
    });
  }

  // 8. Cluster meeting kinds.
  if (
    kind === "CLUSTER_NO_FIRST_MEETING" ||
    kind === "CLUSTER_NO_SECOND_MEETING" ||
    kind === "CLUSTER_NO_THIRD_MEETING"
  ) {
    const ordinal =
      kind === "CLUSTER_NO_FIRST_MEETING"
        ? "first"
        : kind === "CLUSTER_NO_SECOND_MEETING"
          ? "second"
          : "third";
    const where = clusterName ? ` for ${clusterName}` : "";
    return rec({
      primaryAction: "SCHEDULE_CLUSTER_MEETING",
      primaryLabel: `Schedule the ${ordinal} cluster meeting${where}`,
      secondaryActions: ["ASSIGN_TO_PARTNER"],
      reason: `Cluster${clusterName ? ` ${clusterName}` : ""} has no ${ordinal} meeting scheduled.`,
      intervention: weakestMap?.intervention,
    });
  }

  // 9. Cluster SIT.
  if (kind === "CLUSTER_NO_SIT") {
    return rec({
      primaryAction: "SCHEDULE_SIT",
      primaryLabel: `Schedule the cluster School Improvement Training${clusterName ? ` for ${clusterName}` : ""}`,
      secondaryActions: ["VIEW_CLUSTER"],
      reason: `Cluster${clusterName ? ` ${clusterName}` : ""} has no School Improvement Training scheduled.`,
    });
  }

  // 10. Core school missing-visit kinds (visits 1–4 + package).
  if (
    kind === "CORE_MISSING_VISIT_1" ||
    kind === "CORE_MISSING_VISIT_2" ||
    kind === "CORE_MISSING_VISIT_3" ||
    kind === "CORE_MISSING_VISIT_4" ||
    kind === "CORE_PACKAGE_INCOMPLETE"
  ) {
    return rec({
      primaryAction: "SCHEDULE_VISIT",
      primaryLabel: withFocus("Schedule the next core-package support visit", ssaWeakestArea),
      secondaryActions: ["VIEW_SCHOOL"],
      reason: weakestReason
        ? `Core school${schoolName ? ` ${schoolName}` : ""} needs a visit. ${weakestReason}.`
        : `Core school${schoolName ? ` ${schoolName}` : ""} is missing a core-package visit.`,
      purpose: weakestMap?.purpose ?? "Schedule a support visit aligned to the weakest SSA area",
      intervention: weakestMap?.intervention,
    });
  }

  // 11. Core school missing-training kinds (trainings 1–4).
  if (
    kind === "CORE_MISSING_TRAINING_1" ||
    kind === "CORE_MISSING_TRAINING_2" ||
    kind === "CORE_MISSING_TRAINING_3" ||
    kind === "CORE_MISSING_TRAINING_4"
  ) {
    return rec({
      primaryAction: "SCHEDULE_GROUP_TRAINING",
      primaryLabel: withFocus("Schedule the next core-package training", ssaWeakestArea),
      secondaryActions: ["VIEW_SCHOOL"],
      reason: weakestReason
        ? `Core school${schoolName ? ` ${schoolName}` : ""} needs training. ${weakestReason}.`
        : `Core school${schoolName ? ` ${schoolName}` : ""} is missing a core-package training.`,
      purpose: weakestMap?.purpose ?? "Schedule group training aligned to the weakest SSA area",
      intervention: weakestMap?.intervention,
    });
  }

  // 12. Core champion review.
  if (kind === "CORE_CHAMPION_REVIEW") {
    return rec({
      primaryAction: "VIEW_SCHOOL",
      primaryLabel: "Review this core school for champion potential",
      secondaryActions: ["VIEW_SSA"],
      reason: `Core school${schoolName ? ` ${schoolName}` : ""} is improving — review for champion-school status.`,
    });
  }

  // 13. Partner assigned but not scheduled → schedule the first visit.
  if (kind === "PARTNER_ASSIGNED_NOT_SCHEDULED") {
    return rec({
      primaryAction: "SCHEDULE_VISIT",
      primaryLabel: "Schedule the partner's first support visit",
      secondaryActions: ["ASSIGN_TO_PARTNER", "VIEW_SCHOOL"],
      reason: schoolName
        ? `Partner is assigned to ${schoolName} but no visit is scheduled.`
        : "Partner is assigned but no visit is scheduled.",
      purpose: weakestMap?.purpose,
      intervention: weakestMap?.intervention,
    });
  }

  // 14. Partner scheduled / delayed / rescheduled / evidence-pending →
  // monitoring states; open the record to act.
  if (
    kind === "PARTNER_SCHEDULED" ||
    kind === "PARTNER_DELAYED" ||
    kind === "PARTNER_RESCHEDULED" ||
    kind === "PARTNER_EVIDENCE_PENDING"
  ) {
    const reason =
      kind === "PARTNER_DELAYED"
        ? "Partner work is delayed — review and reschedule if needed."
        : kind === "PARTNER_RESCHEDULED"
          ? "Partner activity was rescheduled — confirm the new plan."
          : kind === "PARTNER_EVIDENCE_PENDING"
            ? "Partner submitted work — review the evidence."
            : "Partner activity is scheduled — monitor progress.";
    return rec({
      primaryAction: "VIEW_SCHOOL",
      primaryLabel: "Open the school to review partner progress",
      secondaryActions: ["VIEW_SSA"],
      reason,
    });
  }

  // 15. Default fallback.
  return rec({
    primaryAction: "VIEW_SCHOOL",
    primaryLabel: "Open the school to inspect its full record",
    reason: "No recommendation yet — open the school to inspect.",
    intervention: weakestMap?.intervention,
  });
}
