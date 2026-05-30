// Plan cost calculators + visit-purpose + evidence panels.
//
// Pure math + pure data shaping — no I/O, no server-only. Imported by both
// server pages and client components. Cost rates are passed in as
// PlanCostRates (resolved server-side from cost-settings-mock and forwarded
// as props). Type-only imports from the server-only engine are safe because
// `import type` does not emit a runtime import.

import type {
  SchoolVisitRecommendation,
  Intervention,
  PlanningWarning,
} from "@/lib/plan-builder-engine";

// ────────── Visit purpose ──────────

export const VISIT_PURPOSES = [
  "In-School Coaching",
  "In-School Training",
  "Training Follow-Up",
  "Partner Follow-Up",
  "SSA Support",
  "SSA Verification",
  "Core School Visit",
  "School Improvement Visit",
  "Special Project Visit",
  "Data Collection",
  "Courtesy Visit",
] as const;

export type VisitPurpose = (typeof VISIT_PURPOSES)[number];

// Non-certified partners may only perform these on non-SSA schools.
export const NON_TECHNICAL_PURPOSES: VisitPurpose[] = ["Data Collection", "Courtesy Visit"];

// ────────── Evidence panels ──────────

export type EvidencePanel =
  | {
      kind: "coaching";
      schoolName: string;
      intervention: Intervention;
      ssaScore: number;
      weaknessReason: string;
    }
  | {
      kind: "training-follow-up";
      schoolName: string;
      trainingTitle: string;
      trainingDate: string;
      intervention: Intervention;
      provider: string;
      facilitator: string;
      daysSince: number;
      salesforceId: string;
    }
  | {
      kind: "partner-follow-up";
      schoolName: string;
      partnerName: string;
      trainingTitle: string;
      trainingDate: string;
      intervention: Intervention;
      daysSince: number;
    }
  | {
      kind: "ssa";
      schoolName: string;
      ssaScore: number | null;
      lastSsaDate: string;
      reason: string;
    }
  | {
      kind: "core";
      schoolName: string;
      lastVisitDate: string;
      gapDays: number;
    }
  | {
      kind: "improvement";
      schoolName: string;
      weakestIntervention: Intervention;
      ssaScore: number | null;
    }
  | {
      kind: "data-collection";
      schoolName: string;
      task: "MSC Story" | "Exam Results" | "Enrollment Update";
    };

// recommendPurpose — primary + optional secondary purpose, with reason.
// Priority boost fires when SSA weakness + recent training + no follow-up
// coexist, the strongest evidence that a school is being neglected.
export function recommendPurpose(s: SchoolVisitRecommendation): {
  primary: VisitPurpose;
  secondary?: VisitPurpose;
  reason: string;
  priorityBoost: boolean;
} {
  if (s.ssaScore == null) {
    // No SSA on record — no intervention or follow-up can be recommended
    // until the SSA is completed. Only SSA Support is offered.
    return {
      primary: "SSA Support",
      reason: "No current FY SSA on record — SSA Support is the only valid visit until the SSA is completed.",
      priorityBoost: false,
    };
  }
  const hasRecentTraining = s.lastTrainingDate !== "—";
  const hasVisitGap = s.lastVisitDate === "—";
  const ssaWeak = s.ssaScore < 5.5;
  if (ssaWeak && hasRecentTraining && hasVisitGap) {
    return {
      primary: "Training Follow-Up",
      secondary: "In-School Coaching",
      reason: `Trained on ${s.lastTrainingDate} but no follow-up visit recorded, while SSA in ${s.weakestIntervention} is ${s.ssaScore.toFixed(1)}. Coaching is overdue.`,
      priorityBoost: true,
    };
  }
  if (ssaWeak) {
    return {
      primary: "In-School Coaching",
      secondary: "SSA Support",
      reason: `Weak ${s.weakestIntervention} score (${s.ssaScore.toFixed(1)}) — targeted coaching needed.`,
      priorityBoost: false,
    };
  }
  if (hasRecentTraining && hasVisitGap) {
    return {
      primary: "Training Follow-Up",
      reason: `Trained on ${s.lastTrainingDate}, no post-training visit recorded.`,
      priorityBoost: false,
    };
  }
  if (hasVisitGap) {
    return {
      primary: "Core School Visit",
      reason: "Coverage gap — no staff visit this FY.",
      priorityBoost: false,
    };
  }
  return {
    primary: "Core School Visit",
    reason: "Routine coverage to sustain SSA performance.",
    priorityBoost: false,
  };
}

export function buildEvidencePanel(
  s: SchoolVisitRecommendation,
  purpose: VisitPurpose,
  partnerName?: string,
): EvidencePanel {
  switch (purpose) {
    case "In-School Coaching":
    case "In-School Training":
      return {
        kind: "coaching",
        schoolName: s.schoolName,
        intervention: s.weakestIntervention,
        ssaScore: s.ssaScore ?? 0,
        weaknessReason: s.priorityReason,
      };
    case "Training Follow-Up": {
      const daysSince = s.lastTrainingDate === "—" ? 0
        : Math.max(7, 60 - ((s.schoolId.charCodeAt(s.schoolId.length - 1) % 7) * 6));
      return {
        kind: "training-follow-up",
        schoolName: s.schoolName,
        trainingTitle: `${s.weakestIntervention} Training`,
        trainingDate: s.lastTrainingDate === "—" ? "Not on record" : s.lastTrainingDate,
        intervention: s.weakestIntervention,
        provider: "Edify Field Team",
        facilitator: s.assignedCceo,
        daysSince,
        salesforceId: `SF-TRN-${s.schoolId.replace(/[^0-9]/g, "")}`,
      };
    }
    case "Partner Follow-Up": {
      const daysSince = s.lastTrainingDate === "—" ? 0
        : Math.max(14, 90 - ((s.schoolId.charCodeAt(s.schoolId.length - 1) % 8) * 7));
      return {
        kind: "partner-follow-up",
        schoolName: s.schoolName,
        partnerName: partnerName ?? "Partner",
        trainingTitle: `${s.weakestIntervention} Training (Partner-led)`,
        trainingDate: s.lastTrainingDate === "—" ? "Not on record" : s.lastTrainingDate,
        intervention: s.weakestIntervention,
        daysSince,
      };
    }
    case "SSA Support":
    case "SSA Verification":
      return {
        kind: "ssa",
        schoolName: s.schoolName,
        ssaScore: s.ssaScore,
        lastSsaDate: s.ssaScore == null ? "Not on record" : "Feb 2026",
        reason: s.priorityReason,
      };
    case "Core School Visit": {
      const gapDays = s.lastVisitDate === "—" ? 999
        : 30 + ((s.schoolId.charCodeAt(s.schoolId.length - 1) % 5) * 10);
      return {
        kind: "core",
        schoolName: s.schoolName,
        lastVisitDate: s.lastVisitDate,
        gapDays,
      };
    }
    case "School Improvement Visit":
    case "Special Project Visit":
      return {
        kind: "improvement",
        schoolName: s.schoolName,
        weakestIntervention: s.weakestIntervention,
        ssaScore: s.ssaScore,
      };
    case "Data Collection":
    case "Courtesy Visit": {
      const tasks: ("MSC Story" | "Exam Results" | "Enrollment Update")[] = ["MSC Story", "Exam Results", "Enrollment Update"];
      const task = tasks[s.schoolId.charCodeAt(s.schoolId.length - 1) % tasks.length];
      return { kind: "data-collection", schoolName: s.schoolName, task };
    }
  }
}

// ────────── Partner visit rules ──────────

// Purposes that only staff can perform — never offered on partner visits.
export const STAFF_ONLY_PURPOSES: VisitPurpose[] = ["SSA Verification"];

// Purposes that depend on the school already being scheduled for an SSA
// visit (SSA Support or SSA Verification) by staff. The partner can only
// piggy-back data collection on those scheduled SSA visits.
export const SSA_DEPENDENT_PURPOSES: VisitPurpose[] = ["Data Collection"];

// partnerVisitBlocker — combined rule check for a partner-school-purpose
// triple. Returns a human-readable reason if the assignment is invalid,
// or null if eligible.
export function partnerVisitBlocker(
  s: SchoolVisitRecommendation,
  purpose: VisitPurpose,
  partnerCertified: boolean,
  isScheduledForSsa: boolean,
): string | null {
  if (STAFF_ONLY_PURPOSES.includes(purpose)) {
    return `${purpose} is performed by staff, not partners.`;
  }
  if (SSA_DEPENDENT_PURPOSES.includes(purpose) && !isScheduledForSsa) {
    return `${s.schoolName} is not scheduled for SSA Support or SSA Verification — Data Collection requires an SSA visit first.`;
  }
  if (!partnerCertified) {
    if (!NON_TECHNICAL_PURPOSES.includes(purpose)) {
      return "Non-certified partners may only perform Data Collection or Courtesy Visits.";
    }
    if (purpose === "Courtesy Visit" && s.ssaScore != null) {
      return `${s.schoolName} has a current-FY SSA — non-certified partners can't perform Courtesy Visits here.`;
    }
  }
  return null;
}

// allowedStaffPurposes — the staff dropdown's option set.
//   • No SSA on record → only "SSA Support" is selectable. No intervention,
//     coaching, or data collection can be recommended until the SSA is
//     completed.
//   • SSA on record   → all purposes are available (SSA Verification is
//     staff-only and requires this existing SSA).
export function allowedStaffPurposes(s: SchoolVisitRecommendation): VisitPurpose[] {
  if (s.ssaScore == null) {
    return ["SSA Support"];
  }
  return Array.from(VISIT_PURPOSES);
}

// allowedPartnerPurposes — the dropdown's option set, already filtered
// by certification and SSA scheduling.
export function allowedPartnerPurposes(
  partnerCertified: boolean,
  isScheduledForSsa: boolean,
): VisitPurpose[] {
  const base = VISIT_PURPOSES.filter((p) => !STAFF_ONLY_PURPOSES.includes(p));
  if (!partnerCertified) {
    return isScheduledForSsa
      ? ["Data Collection", "Courtesy Visit"]
      : ["Courtesy Visit"];
  }
  return base.filter((p) => !SSA_DEPENDENT_PURPOSES.includes(p) || isScheduledForSsa);
}

// ────────── Multi-facilitator training capacity ──────────

// 1 facilitator → 1 cluster training/day. Each additional facilitator adds
// one parallel training slot for the same day.
export function maxTrainingsPerDay(facilitators: number): number {
  return Math.max(1, Math.floor(facilitators));
}

export function validateTrainingDayCapacity(
  facilitators: number,
  plannedByDate: Record<string, number>,
): PlanningWarning[] {
  const cap = maxTrainingsPerDay(facilitators);
  const warnings: PlanningWarning[] = [];
  for (const [date, count] of Object.entries(plannedByDate)) {
    if (count > cap) {
      warnings.push({
        id: `train-cap-${date}`,
        level: "error",
        message: `${count} cluster trainings planned on ${date} but only ${facilitators} facilitator${facilitators === 1 ? "" : "s"} available (max ${cap}/day).`,
      });
    }
  }
  return warnings;
}

// ────────── Cost calculators ──────────

export type PlanCostRates = {
  staffCommutingTransport:        number;
  staffLunch:                     number;
  staffOvernightTransport:        number;
  breakfastPerDay:                number;
  lunchPerDay:                    number;
  dinnerPerDay:                   number;
  accommodationPerNight:          number;
  clusterTrainingPerParticipant:  number;
  clusterMeetingPerParticipant:   number;
  venueFee:                       number;
  facilitationFee:                number;
  partnerVisitCostPerSchool:      number;
  partnerTrainingFacilitationFee: number;
  partnerFacilitatorDailyFee:     number;
};

// ────────── Staff Visit ──────────

export type StaffVisitType = "Commuting Visit" | "Overnight Visit";

export type StaffVisitCostInput = {
  visitType: StaffVisitType;
  staffCount: number;
  schoolCount: number;
  nights?: number; // required when Overnight
  days?:   number; // required when Overnight — covers per-diem feeding
};

export type StaffVisitCostBreakdown = {
  visitType:      StaffVisitType;
  transport:      number;
  lunch:          number;
  breakfast:      number;
  dinner:         number;
  accommodation:  number;
  perStaff:       number;
  total:          number;
  formula:        string;
};

export function calculateStaffVisitCost(
  input: StaffVisitCostInput,
  rates: PlanCostRates,
): StaffVisitCostBreakdown {
  // 0-school batches are nonsensical for cost — surface the empty state
  // explicitly so the UI can show "select schools first" instead of a
  // misleading non-zero per-staff figure.
  if (input.schoolCount < 1) {
    return {
      visitType:     input.visitType,
      transport:     0,
      lunch:         0,
      breakfast:     0,
      dinner:        0,
      accommodation: 0,
      perStaff:      0,
      total:         0,
      formula:       "0 schools selected",
    };
  }
  const staff   = Math.max(1, input.staffCount);
  const schools = Math.max(1, input.schoolCount);
  if (input.visitType === "Commuting Visit") {
    const transport = rates.staffCommutingTransport;
    const lunch     = rates.staffLunch;
    const perStaff  = transport + lunch;
    return {
      visitType:     "Commuting Visit",
      transport,
      lunch,
      breakfast:     0,
      dinner:        0,
      accommodation: 0,
      perStaff,
      total:         perStaff * staff * schools,
      formula:       `(Transport ${fmt(transport)} + Lunch ${fmt(lunch)}) × ${staff} staff × ${schools} school${schools === 1 ? "" : "s"}`,
    };
  }
  // Overnight: enforce nights ≤ days (nights are nested within days; you
  // can't have more overnight stays than visit-days).
  const daysRaw       = Math.max(1, input.days ?? Math.max(1, (input.nights ?? 0) + 1));
  const days          = daysRaw;
  const nights        = Math.min(days, Math.max(0, input.nights ?? 0));
  const transport     = rates.staffOvernightTransport;
  const breakfast     = rates.breakfastPerDay * days;
  const lunch         = rates.lunchPerDay     * days;
  const dinner        = rates.dinnerPerDay    * days;
  const accommodation = rates.accommodationPerNight * nights;
  const perStaff      = transport + breakfast + lunch + dinner + accommodation;
  return {
    visitType:     "Overnight Visit",
    transport,
    lunch,
    breakfast,
    dinner,
    accommodation,
    perStaff,
    total:         perStaff * staff * schools,
    formula:       `(Transport ${fmt(transport)} + Accom ${fmt(rates.accommodationPerNight)}×${nights} + B/L/D per day×${days}) × ${staff} staff × ${schools} school${schools === 1 ? "" : "s"}`,
  };
}

// ────────── Participant-based costing (Cluster Training / Meeting) ──────────

export type ParticipantActivity = "Cluster Training" | "Cluster Meeting";

export type ParticipantCostInput = {
  activity:        ParticipantActivity;
  participants:    number;
  includeVenue:    boolean;
  includeFacilitation: boolean;
};

export type ParticipantCostBreakdown = {
  activity:       ParticipantActivity;
  participants:   number;
  perParticipant: number;
  feeding:        number;
  venue:          number;
  facilitation:   number;
  total:          number;
  formula:        string;
};

export function calculateParticipantBasedCost(
  input: ParticipantCostInput,
  rates: PlanCostRates,
): ParticipantCostBreakdown {
  const participants   = Math.max(0, input.participants);
  const perParticipant = input.activity === "Cluster Training"
    ? rates.clusterTrainingPerParticipant
    : rates.clusterMeetingPerParticipant;
  const feeding      = perParticipant * participants;
  const venue        = input.includeVenue        ? rates.venueFee       : 0;
  const facilitation = input.includeFacilitation ? rates.facilitationFee: 0;
  return {
    activity:       input.activity,
    participants,
    perParticipant,
    feeding,
    venue,
    facilitation,
    total:          feeding + venue + facilitation,
    formula:        `(${participants} × ${fmt(perParticipant)})${input.includeVenue ? ` + Venue ${fmt(venue)}` : ""}${input.includeFacilitation ? ` + Facilitation ${fmt(facilitation)}` : ""}`,
  };
}

// ────────── Partner Visit ──────────

export type PartnerVisitCostInput = {
  schoolCount: number;
};

export type PartnerVisitCostBreakdown = {
  schoolCount: number;
  perSchool:   number;
  total:       number;
  formula:     string;
};

export function calculatePartnerVisitCost(
  input: PartnerVisitCostInput,
  rates: PlanCostRates,
): PartnerVisitCostBreakdown {
  const schoolCount = Math.max(0, input.schoolCount);
  const perSchool   = rates.partnerVisitCostPerSchool;
  return {
    schoolCount,
    perSchool,
    total:       perSchool * schoolCount,
    formula:     `${schoolCount} schools × ${fmt(perSchool)}`,
  };
}

// ────────── Helpers ──────────

function fmt(n: number): string {
  if (n >= 1_000_000) return `UGX ${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000)     return `UGX ${(n / 1_000).toFixed(0)}K`;
  return `UGX ${n}`;
}
