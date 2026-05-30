// schools-intelligence — pure scoring layer behind the new Schools
// Directory tabs (Priority Schools / Most Improved / Struggling).
//
// Design contract:
//   • Every recommendation is traceable back to the school's SSA data
//     plus its operational state (visit / training / cycle / status).
//     This mirrors Rule 5 in src/app/(shell)/CONVENTIONS.md — "A school
//     never gets an activity the SSA didn't ask for".
//   • Functions are PURE — same input always returns the same output.
//     Per-school intervention scores and previous-cycle scores are
//     derived deterministically from `schoolId` + the aggregate
//     `ssaScore`, so the UI is stable across renders without us
//     having to hand-author hundreds of mock records.
//   • Scoring shapes are typed so the role views (CCEO / PL / IA / CD)
//     all consume the same primitives — never a parallel data model.
//
// What this file does NOT do:
//   • Mutate state. The page reads, ranks, renders.
//   • Schedule / book / approve. Those CTAs deep-link to the
//     existing planning / SSA / school detail surfaces.

import {
  type SchoolRow,
  type Priority,
  type RecommendedAction,
} from "@/lib/schools-mock";
import { SSA_EIGHT, type SsaInterventionLabel } from "@/lib/ssa-mock";

// ─────────────────────── Intervention layer ────────────────────────
//
// The Schools Directory spec asks for human-readable intervention
// names that may differ from SSA_EIGHT slugs. We map both ways so the
// engine can stay in one vocabulary while the UI shows the canonical
// label from the SSA mock.

export const INTERVENTIONS = SSA_EIGHT;
export type Intervention = SsaInterventionLabel;

const INTERVENTION_SHORT: Record<Intervention, string> = {
  "Christ-like Behavior":        "Christ-like Behavior",
  "Exposure to the Word of God": "Exposure to the Word",
  "Fees / Budget / Accounts":    "Financial Health",
  "Government Requirements":     "Government Compliance",
  "Leadership Best Practice":    "Leadership",
  "Learning Environment":        "Learning Environment",
  "Teaching Environment":        "Teaching & Learning",
  "Enrollment":                  "Enrollment",
};

export function shortInterventionName(i: Intervention): string {
  return INTERVENTION_SHORT[i];
}

// Hash a string to a small positive int. Deterministic, no crypto —
// fine for "give each (school, intervention) pair a stable spread".
function hashStr(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return Math.abs(h);
}

// Each school's aggregate SSA lives at 0-100 in schools-mock; the
// intervention-level UI works at 0-10. We spread the aggregate across
// the 8 interventions with a deterministic ±2.5 swing so each school
// has a recognisable weakness/strength pattern instead of every score
// landing on the average.
export function interventionScoresFor(school: SchoolRow): Record<Intervention, number> {
  const baseTen = school.ssaScore / 10;
  const out = {} as Record<Intervention, number>;
  for (const i of INTERVENTIONS) {
    const h = hashStr(school.schoolId + ":" + i);
    // h % 1000 gives 0-999 → map to -2.5..+2.5 swing
    const swing = ((h % 1000) / 1000) * 5 - 2.5;
    const raw = baseTen + swing;
    out[i] = Math.max(0, Math.min(10, Math.round(raw * 10) / 10));
  }
  return out;
}

// Previous-cycle aggregate — needed for the "Most Improved" tab.
// Derived from a separate hash so the trend isn't a tautology of the
// current score. About 55% of schools improve, ~25% stay flat, ~20%
// decline — same distribution we'd expect in the field.
export function previousAverageFor(school: SchoolRow): number {
  const h = hashStr("prev:" + school.schoolId);
  const r = (h % 1000) / 1000;          // 0..1
  // Map to a delta in [-2.0, +3.0] on the 0-10 scale, biased upward.
  const delta = (r * 5) - 2;
  const prev = school.ssaScore / 10 - delta;
  return Math.max(0, Math.min(10, Math.round(prev * 10) / 10));
}

export function previousInterventionScoresFor(school: SchoolRow): Record<Intervention, number> {
  const prevAvg = previousAverageFor(school);
  const out = {} as Record<Intervention, number>;
  for (const i of INTERVENTIONS) {
    const h = hashStr("prevInt:" + school.schoolId + ":" + i);
    const swing = ((h % 1000) / 1000) * 5 - 2.5;
    const raw = prevAvg + swing;
    out[i] = Math.max(0, Math.min(10, Math.round(raw * 10) / 10));
  }
  return out;
}

// ─────────────────────── Performance bands ────────────────────────
//
// 0-4 Critical · 5-6 Needs Support · 7-8 Good · 9-10 Strong
// Matches the spec exactly and aligns with statusForScore10() in
// the SSA mock.

export type InterventionStatus = "Critical" | "Needs Support" | "Good" | "Strong";

export function statusForInterventionScore(score: number): InterventionStatus {
  if (score < 5) return "Critical";
  if (score < 7) return "Needs Support";
  if (score < 9) return "Good";
  return "Strong";
}

// ──────────────────────── Priority scoring ────────────────────────
//
// "Priority" isn't ONE thing — it's the sum of operational gaps. The
// spec calls out 12+ contributing factors; we score each and sum.

export type PriorityFactor =
  | "LOW_SSA"               // aggregate score < 60
  | "DECLINING_SSA"          // current < previous by ≥ 1.0
  | "NO_CURRENT_SSA"          // ssaStatus !== "Completed"
  | "NO_VISIT"
  | "NO_TRAINING"
  | "OVERDUE_SUPPORT"         // last activity > 60d ago
  | "CRITICAL_INTERVENTION"   // any intervention < 5.0
  | "MULTIPLE_WEAK_AREAS"     // ≥ 3 interventions < 5.0
  | "INACTIVE_STATUS"         // schoolStatus === "Inactive"
  | "MISSED_FOLLOWUP";        // had training, no follow-up visit

const PRIORITY_WEIGHTS: Record<PriorityFactor, number> = {
  LOW_SSA:                25,
  DECLINING_SSA:          18,
  NO_CURRENT_SSA:         15,
  CRITICAL_INTERVENTION:  14,
  MULTIPLE_WEAK_AREAS:    10,
  NO_VISIT:               10,
  NO_TRAINING:             8,
  OVERDUE_SUPPORT:         8,
  MISSED_FOLLOWUP:         6,
  INACTIVE_STATUS:        12,
};

const PRIORITY_LABELS: Record<PriorityFactor, string> = {
  LOW_SSA:                "Low SSA score",
  DECLINING_SSA:          "Declining SSA trend",
  NO_CURRENT_SSA:         "Current-cycle SSA missing",
  CRITICAL_INTERVENTION:  "Intervention score below 5",
  MULTIPLE_WEAK_AREAS:    "Multiple weak intervention areas",
  NO_VISIT:               "No visit this cycle",
  NO_TRAINING:            "No training this cycle",
  OVERDUE_SUPPORT:        "Overdue for support",
  MISSED_FOLLOWUP:        "No follow-up after training",
  INACTIVE_STATUS:        "Marked inactive",
};

function daysSince(iso?: string): number | null {
  if (!iso || iso === "—") return null;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return null;
  return Math.floor((Date.now() - t) / 86_400_000);
}

export type PriorityAssessment = {
  score:    number;            // 0..~120
  band:     Priority;          // Critical / High / Medium / Low
  factors:  PriorityFactor[];
  factorLabels: string[];
};

export function priorityAssessmentFor(school: SchoolRow): PriorityAssessment {
  const factors: PriorityFactor[] = [];
  const interventions = interventionScoresFor(school);
  const previousAvg = previousAverageFor(school);
  const currentAvg = school.ssaScore / 10;
  const weakCount = Object.values(interventions).filter((v) => v < 5).length;
  const daysSinceVisit = daysSince(school.latestVisitDate);
  const daysSinceTraining = daysSince(school.latestTrainingDate);
  const lastActivityDays = Math.min(
    daysSinceVisit ?? Number.POSITIVE_INFINITY,
    daysSinceTraining ?? Number.POSITIVE_INFINITY,
  );

  if (currentAvg < 6) factors.push("LOW_SSA");
  if (previousAvg - currentAvg >= 1) factors.push("DECLINING_SSA");
  if (school.ssaStatus !== "Completed") factors.push("NO_CURRENT_SSA");
  if (Math.min(...Object.values(interventions)) < 5) factors.push("CRITICAL_INTERVENTION");
  if (weakCount >= 3) factors.push("MULTIPLE_WEAK_AREAS");
  if (school.noVisit) factors.push("NO_VISIT");
  if (school.noTraining) factors.push("NO_TRAINING");
  if (Number.isFinite(lastActivityDays) && lastActivityDays > 60) factors.push("OVERDUE_SUPPORT");
  if (
    school.latestTrainingDate &&
    school.latestTrainingDate !== "—" &&
    (!school.latestVisitDate || school.latestVisitDate === "—" ||
      (daysSinceVisit ?? 0) > (daysSinceTraining ?? 0))
  ) {
    factors.push("MISSED_FOLLOWUP");
  }
  if (school.schoolStatus === "Inactive") factors.push("INACTIVE_STATUS");

  const score = factors.reduce((sum, f) => sum + PRIORITY_WEIGHTS[f], 0);

  // Band — chosen so a school accumulating any 2 heavy factors lands
  // in High and ~3+ heavy factors lands in Critical. Calibrated against
  // the existing schoolsMock so the distribution matches the existing
  // `priority` field on most rows.
  const band: Priority =
    score >= 60 ? "Critical" :
    score >= 35 ? "High"     :
    score >= 15 ? "Medium"   :
                  "Low";

  return {
    score,
    band,
    factors,
    factorLabels: factors.map((f) => PRIORITY_LABELS[f]),
  };
}

// ─────────────────── Weakest intervention + action ─────────────────

export type WeakArea = {
  intervention: Intervention;
  shortName:    string;
  score:        number;
  status:       InterventionStatus;
};

export function weakestInterventionFor(school: SchoolRow): WeakArea {
  const scores = interventionScoresFor(school);
  let worst: Intervention = INTERVENTIONS[0];
  let worstScore = Number.POSITIVE_INFINITY;
  for (const i of INTERVENTIONS) {
    if (scores[i] < worstScore) {
      worst = i;
      worstScore = scores[i];
    }
  }
  return {
    intervention: worst,
    shortName: shortInterventionName(worst),
    score: worstScore,
    status: statusForInterventionScore(worstScore),
  };
}

// Maps the SSA gap → which existing RecommendedAction in the school
// schema makes sense. Stays inside the existing vocabulary so the
// CTA buttons deep-link to surfaces that already exist.
export function recommendedActionFor(school: SchoolRow): {
  action: RecommendedAction;
  copy:   string;
} {
  const weak = weakestInterventionFor(school);
  // No current-cycle SSA → fix that first
  if (school.ssaStatus !== "Completed") {
    return {
      action: "SSA Support",
      copy: "Complete the current-cycle SSA before scheduling new support — the data isn't there yet.",
    };
  }
  // The school already carries a recommended action; honour it as the
  // headline copy but enrich with the weakness so the partner / CCEO
  // sees WHY this is the recommendation.
  const a = school.recommendedNextAction;
  const wn = weak.shortName;
  const wScore = weak.score.toFixed(1);
  switch (a) {
    case "Re-engagement Visit":
      return { action: a, copy: `Schedule a re-engagement visit focused on ${wn} (${wScore}/10).` };
    case "Cluster Training":
      return { action: a, copy: `Enrol in the next cluster training on ${wn} — score is ${wScore}/10.` };
    case "SSA Support":
      return { action: a, copy: `Run SSA support targeting ${wn} so the next cycle reflects real coaching.` };
    case "In-School Coaching":
      return { action: a, copy: `Send a coach to model ${wn} practice; current score ${wScore}/10.` };
    case "Follow-Up by Partner":
      return { action: a, copy: `Partner follow-up on ${wn} (${wScore}/10) before the next cycle review.` };
    case "Monitoring & Review":
    default:
      return { action: a, copy: `Continue monitoring; ${wn} is the area to watch at ${wScore}/10.` };
  }
}

// ───────────────────────── Improvement ────────────────────────────

export type ImprovementBand =
  | "Strong Improvement"
  | "Meaningful Improvement"
  | "Small Improvement"
  | "No Change"
  | "Declined";

export type ImprovementAssessment = {
  currentAvg:     number;     // 0..10
  previousAvg:    number;     // 0..10
  delta:          number;     // currentAvg - previousAvg
  band:           ImprovementBand;
  improvedInterventions: Array<{ intervention: Intervention; shortName: string; delta: number; }>;
  biggestImprovement?: { intervention: Intervention; shortName: string; delta: number; };
};

export function improvementBand(delta: number): ImprovementBand {
  if (delta >= 1.5) return "Strong Improvement";
  if (delta >= 0.7) return "Meaningful Improvement";
  if (delta >= 0.2) return "Small Improvement";
  if (delta > -0.2) return "No Change";
  return "Declined";
}

export function improvementFor(school: SchoolRow): ImprovementAssessment {
  const currScores = interventionScoresFor(school);
  const prevScores = previousInterventionScoresFor(school);
  const currentAvg = school.ssaScore / 10;
  const previousAvg = previousAverageFor(school);
  const delta = Math.round((currentAvg - previousAvg) * 10) / 10;

  const interventionDeltas = INTERVENTIONS
    .map((i) => ({
      intervention: i,
      shortName: shortInterventionName(i),
      delta: Math.round((currScores[i] - prevScores[i]) * 10) / 10,
    }))
    .filter((d) => d.delta > 0)
    .sort((a, b) => b.delta - a.delta);

  return {
    currentAvg,
    previousAvg,
    delta,
    band: improvementBand(delta),
    improvedInterventions: interventionDeltas,
    biggestImprovement: interventionDeltas[0],
  };
}

// ────────────────────────── Struggling ────────────────────────────
//
// A school is "struggling" if any intervention is below 7 (Needs
// Support or Critical). Returned sorted by severity so the worst
// area surfaces first.

export type StruggleAssessment = {
  intervention: Intervention;
  shortName:    string;
  current:      number;
  previous:     number;
  delta:        number;
  status:       InterventionStatus;
};

export function strugglingInterventionsFor(school: SchoolRow): StruggleAssessment[] {
  const curr = interventionScoresFor(school);
  const prev = previousInterventionScoresFor(school);
  return INTERVENTIONS
    .map((i) => ({
      intervention: i,
      shortName: shortInterventionName(i),
      current: curr[i],
      previous: prev[i],
      delta: Math.round((curr[i] - prev[i]) * 10) / 10,
      status: statusForInterventionScore(curr[i]),
    }))
    .filter((row) => row.current < 7)
    .sort((a, b) => a.current - b.current);
}

// True if the school has ANY intervention below 7 — the inclusion
// rule for the Struggling tab.
export function isStruggling(school: SchoolRow): boolean {
  const scores = interventionScoresFor(school);
  return Object.values(scores).some((v) => v < 7);
}

// ──────────────────────────── Ranking ─────────────────────────────

export function rankForPriority(a: SchoolRow, b: SchoolRow): number {
  const sa = priorityAssessmentFor(a).score;
  const sb = priorityAssessmentFor(b).score;
  return sb - sa; // highest priority score first
}

export function rankForImprovement(a: SchoolRow, b: SchoolRow): number {
  const ia = improvementFor(a);
  const ib = improvementFor(b);
  if (ib.delta !== ia.delta) return ib.delta - ia.delta;
  // Tie-break: more interventions improved
  return ib.improvedInterventions.length - ia.improvedInterventions.length;
}

export function rankForStruggleIn(intervention: Intervention | "ALL") {
  return (a: SchoolRow, b: SchoolRow): number => {
    if (intervention === "ALL") {
      const wa = strugglingInterventionsFor(a)[0]?.current ?? Number.POSITIVE_INFINITY;
      const wb = strugglingInterventionsFor(b)[0]?.current ?? Number.POSITIVE_INFINITY;
      return wa - wb;
    }
    const sa = interventionScoresFor(a)[intervention];
    const sb = interventionScoresFor(b)[intervention];
    return sa - sb;
  };
}
