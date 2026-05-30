// SSA recommendation engine — turns SSA gaps into concrete next actions. The Planning page never asks the user to guess; this function decides what each card should propose based on the SSA result, the gap kind, and the SSA gate.

import type {
  GapKind,
  PlanningActionKind,
  PlanningRecommendation,
  SsaGateState,
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

// ────────── Main entry: given a gap kind + SSA snapshot, produce the PlanningRecommendation ──────────
export function recommendForGap(opts: {
  kind: GapKind;
  ssaGate: SsaGateState;
  ssaWeakest?: string;
  ssaSecondWeakest?: string;
  ssaWeakestScore?: number;
  schoolName?: string;
  clusterName?: string;
}): PlanningRecommendation {
  const {
    kind,
    ssaGate,
    ssaWeakest,
    ssaWeakestScore,
    schoolName,
    clusterName,
  } = opts;

  // 1. SIT not done → schedule SIT, no secondary.
  if (ssaGate === "SIT_NOT_DONE") {
    return {
      primary: {
        action: "SCHEDULE_SIT",
        purpose:
          "Schedule School Improvement Training (SSA happens during SIT)",
      },
      secondary: [],
      reason:
        "School Improvement Training has not been scheduled — SSA happens during SIT.",
    } as PlanningRecommendation;
  }

  // 2. SIT done but SSA missing → only COMPLETE_SSA is allowed.
  if (ssaGate === "SIT_DONE_SSA_MISSING") {
    return {
      primary: {
        action: "COMPLETE_SSA",
        purpose:
          "Complete the School Self-Assessment so planning can be unlocked",
      },
      secondary: [],
      allOtherActionsDisabled: true,
      reason: "Planning locked. SSA not completed.",
    } as PlanningRecommendation;
  }

  // From here on, SSA is complete. Build a weakest-intervention mapping
  // we can reuse across gap kinds.
  const weakestMap = interventionMapping(ssaWeakest);

  // 3. NO_VISIT (SSA complete) → drive off weakest intervention.
  if (kind === "NO_VISIT") {
    const action = weakestMap?.primaryAction ?? "SCHEDULE_VISIT";
    const purpose =
      weakestMap?.purpose ?? "Schedule a support visit for this school";
    return {
      primary: { action, purpose },
      secondary: [{ action: "ASSIGN_TO_PARTNER" }, { action: "VIEW_SSA" }],
      reason: ssaWeakest
        ? `Address weakest SSA area: ${ssaWeakest} (${scoreLabel(ssaWeakestScore)})`
        : "School has no recorded support visit — schedule one.",
      intervention: weakestMap?.intervention,
    } as PlanningRecommendation;
  }

  // 4. NO_TRAINING (SSA complete) → force a training action.
  if (kind === "NO_TRAINING") {
    // Force training, even if the weakest-intervention default is a visit.
    const mapped = weakestMap?.primaryAction;
    const isTrainingAction =
      mapped === "SCHEDULE_IN_SCHOOL_TRAINING" ||
      mapped === "SCHEDULE_GROUP_TRAINING" ||
      mapped === "SCHEDULE_CLUSTER_TRAINING";
    const action: PlanningActionKind = isTrainingAction
      ? (mapped as PlanningActionKind)
      : "SCHEDULE_IN_SCHOOL_TRAINING";
    const purpose =
      weakestMap?.purpose ??
      "Schedule training aligned to the weakest SSA area";
    return {
      primary: { action, purpose },
      secondary: [{ action: "ASSIGN_TO_PARTNER" }, { action: "VIEW_SSA" }],
      reason: ssaWeakest
        ? `Address weakest SSA area: ${ssaWeakest} (${scoreLabel(ssaWeakestScore)})`
        : "School has no recorded training — schedule one.",
      intervention: weakestMap?.intervention,
    } as PlanningRecommendation;
  }

  // 5. Training done, no follow-up → embed practices.
  if (kind === "TRAINING_DONE_NO_FOLLOWUP") {
    return {
      primary: {
        action: "SCHEDULE_FOLLOW_UP_VISIT",
        purpose:
          weakestMap?.purpose ??
          "Follow-up visit to confirm training is embedded in practice",
      },
      secondary: [{ action: "ASSIGN_TO_PARTNER" }],
      reason: "Training completed — schedule follow-up to embed practices",
      intervention: weakestMap?.intervention,
    } as PlanningRecommendation;
  }

  // 6. No cluster → assign before scheduling cluster work.
  if (kind === "NO_CLUSTER") {
    return {
      primary: {
        action: "ADD_TO_CLUSTER",
        purpose: "Assign this school to a cluster before scheduling cluster work",
      },
      secondary: [{ action: "VIEW_SCHOOL" }],
      reason: "School is unclustered — assign before scheduling cluster work",
      intervention: weakestMap?.intervention,
    } as PlanningRecommendation;
  }

  // 7. Cluster missing-meeting kinds.
  if (
    kind === "CLUSTER_NO_FIRST_MEETING" ||
    kind === "CLUSTER_NO_SECOND_MEETING" ||
    kind === "CLUSTER_NO_THIRD_MEETING"
  ) {
    const meetingNumber =
      kind === "CLUSTER_NO_FIRST_MEETING"
        ? 1
        : kind === "CLUSTER_NO_SECOND_MEETING"
          ? 2
          : 3;
    const ordinal = meetingNumber === 1 ? "first" : meetingNumber === 2 ? "second" : "third";
    return {
      primary: {
        action: "SCHEDULE_CLUSTER_MEETING",
        purpose: `Schedule the ${ordinal} cluster meeting${clusterName ? ` for ${clusterName}` : ""}`,
        meetingNumber,
      },
      secondary: [{ action: "ASSIGN_TO_PARTNER" }],
      reason: `Cluster${clusterName ? ` ${clusterName}` : ""} has no ${ordinal} meeting scheduled.`,
      intervention: weakestMap?.intervention,
    } as PlanningRecommendation;
  }

  // 8. Core school missing-visit kinds.
  if (
    kind === "CORE_NO_VISIT" ||
    kind === "CORE_MISSING_VISIT" ||
    kind === "CORE_NO_RECENT_VISIT"
  ) {
    return {
      primary: {
        action: "SCHEDULE_VISIT",
        purpose:
          weakestMap?.purpose ??
          "Schedule a support visit aligned to the weakest SSA area",
      },
      secondary: [{ action: "VIEW_SCHOOL" }],
      reason: ssaWeakest
        ? `Core school${schoolName ? ` ${schoolName}` : ""} needs a visit on ${ssaWeakest} (${scoreLabel(ssaWeakestScore)}).`
        : `Core school${schoolName ? ` ${schoolName}` : ""} has no recent visit.`,
      intervention: weakestMap?.intervention,
    } as PlanningRecommendation;
  }

  // 9. Core school missing-training kinds.
  if (
    kind === "CORE_NO_TRAINING" ||
    kind === "CORE_MISSING_TRAINING" ||
    kind === "CORE_NO_RECENT_TRAINING"
  ) {
    return {
      primary: {
        action: "SCHEDULE_GROUP_TRAINING",
        purpose:
          weakestMap?.purpose ??
          "Schedule group training aligned to the weakest SSA area",
      },
      secondary: [{ action: "VIEW_SCHOOL" }],
      reason: ssaWeakest
        ? `Core school${schoolName ? ` ${schoolName}` : ""} needs training on ${ssaWeakest} (${scoreLabel(ssaWeakestScore)}).`
        : `Core school${schoolName ? ` ${schoolName}` : ""} has no recent training.`,
      intervention: weakestMap?.intervention,
    } as PlanningRecommendation;
  }

  // 10. Partner kinds.
  if (
    kind === "PARTNER_UNASSIGNED" ||
    kind === "PARTNER_NO_PARTNER" ||
    kind === "NO_PARTNER"
  ) {
    return {
      primary: {
        action: "ASSIGN_TO_PARTNER",
        purpose: "Assign a partner organisation to support this school",
      },
      secondary: [{ action: "VIEW_SCHOOL" }],
      reason: schoolName
        ? `${schoolName} has no partner assigned — assign one before scheduling partner-led work.`
        : "No partner is assigned — assign one before scheduling partner-led work.",
      intervention: weakestMap?.intervention,
    } as PlanningRecommendation;
  }

  if (
    kind === "PARTNER_ASSIGNED_NOT_SCHEDULED" ||
    kind === "ASSIGNED_NOT_SCHEDULED"
  ) {
    return {
      primary: {
        action: "SCHEDULE_VISIT",
        purpose:
          weakestMap?.purpose ??
          "Partner assigned — schedule the first support visit",
      },
      secondary: [{ action: "ASSIGN_TO_PARTNER" }, { action: "VIEW_SCHOOL" }],
      reason: schoolName
        ? `Partner is assigned to ${schoolName} but no visit is scheduled.`
        : "Partner is assigned but no visit is scheduled.",
      intervention: weakestMap?.intervention,
    } as PlanningRecommendation;
  }

  // 11. Default fallback.
  return {
    primary: {
      action: "VIEW_SCHOOL",
      purpose: "Open the school to inspect its full record",
    },
    secondary: [],
    reason: "No recommendation yet — open the school to inspect.",
    intervention: weakestMap?.intervention,
  } as PlanningRecommendation;
}
