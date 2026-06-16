// SSA → Recommendation engine (the keystone of the school-centered workflow).
//
//   School Directory  →  SSA performance (by School ID)  →  THIS MODULE  →  Plan
//
// Given a school's SSA scores it (1) classifies EVERY one of the 8 interventions
// by severity, (2) routes each struggling intervention to a recommended delivery
// (staff vs partner) by intervention type, and (3) emits a per-intervention
// recommendation card (score, severity, why, recommended activity, delivery,
// suggested next actions). A school can struggle in more than one intervention,
// so the output is a RANKED LIST, weakest → strongest.
//
// Taxonomy: the canonical 8 (SsaInterventionArea) — the same enum the live
// per-school scores in project-school-ssa.ts are keyed on. There is exactly one
// intervention taxonomy in the recommendation path; this module is its semantics.
//
// The recommendation GUIDES, it does not force: every card carries both the
// recommended delivery AND the alternate, so staff/PL can override with reason.

import type { SsaInterventionArea } from "./planning-gaps-mock";
import { SSA_INTERVENTIONS } from "./ssa-performance-mock";
import { ssaForSchool } from "@/lib/projects/project-school-ssa";
import { ssaUploads } from "@/lib/intake/intake-mock";
import { normalizeScores, isComplete } from "./intervention-taxonomy";

// ────────── Severity (spec §6 thresholds) ──────────
//   0–4 Critical · 5–6 Needs Support · 7–8 Good · 9–10 Strong

export type Severity = "Critical" | "Needs Support" | "Good" | "Strong";

/** Classify a 0–10 SSA score into a severity band. */
export function classifySeverity(score: number): Severity {
  if (score < 5) return "Critical";
  if (score < 7) return "Needs Support";
  if (score < 9) return "Good";
  return "Strong";
}

/** A school is "struggling" in an intervention when it scores below Good (7). */
export function isStruggling(score: number): boolean {
  return score < 7;
}

export const SEVERITY_TONE: Record<Severity, "rose" | "amber" | "emerald" | "edify"> = {
  Critical: "rose",
  "Needs Support": "amber",
  Good: "emerald",
  Strong: "edify",
};

// ────────── Delivery routing (spec §7) ──────────
// Technical / specialized interventions route to PARTNER expertise; general
// school-improvement interventions route to STAFF (CCEO/PL). This is the
// recommended default — never a hard lock.

export type DeliveryType = "staff" | "partner";

export type RecommendedActivity = "Visit" | "Training" | "Follow-up" | "In-school support";

type InterventionPolicy = {
  /** Recommended delivery owner for this intervention type. */
  delivery: DeliveryType;
  /** The kind of activity that best addresses this intervention. */
  activity: RecommendedActivity;
  /** When delivery is "partner", the kind of partner expertise needed. */
  partnerType?: string;
  /** Plain-English justification surfaced on the recommendation card. */
  reason: string;
};

const POLICY: Record<SsaInterventionArea, InterventionPolicy> = {
  // ── Technical / specialized → partner ──
  "Teaching & Learning": {
    delivery: "partner",
    activity: "Training",
    partnerType: "Literacy / Numeracy / pedagogy partner",
    reason: "Literacy, numeracy and classroom-practice support needs technical partner expertise.",
  },
  "Education Technology": {
    delivery: "partner",
    activity: "Training",
    partnerType: "EdTech partner",
    reason: "Education technology rollout and teacher device-practice needs a specialist EdTech partner.",
  },
  // ── General school improvement → staff (CCEO / PL) ──
  Leadership: {
    delivery: "staff",
    activity: "Visit",
    reason: "Headteacher leadership and management coaching can be handled by CCEO/PL directly.",
  },
  "Learning Environment": {
    delivery: "staff",
    activity: "Visit",
    reason: "Learning-environment walk-throughs (library, latrines, signage) are general staff support.",
  },
  "Government Requirements & Compliance": {
    delivery: "staff",
    activity: "Visit",
    reason: "Registration, inspection and compliance review is general staff support.",
  },
  "Financial Health": {
    delivery: "staff",
    activity: "Training",
    reason: "Budget, fees and accounts coaching can be handled by CCEO/PL.",
  },
  "Christlike Behaviour": {
    delivery: "staff",
    activity: "Visit",
    reason: "Basic Christlike-behaviour support is general staff coaching (a CC-SEL partner is the deeper option).",
  },
  "Exposure to the Word of God": {
    delivery: "staff",
    activity: "Visit",
    reason: "General chaplaincy and devotion support is staff-delivered (a Bible-project partner is the deeper option).",
  },
};

/** The recommended delivery owner for an intervention type. */
export function deliveryFor(area: SsaInterventionArea): DeliveryType {
  return POLICY[area].delivery;
}

// ────────── Per-intervention recommendation (spec §8) ──────────

export type InterventionRecommendation = {
  intervention: SsaInterventionArea;
  score: number; // /10
  severity: Severity;
  /** The activity that best addresses this intervention. */
  recommendedActivity: RecommendedActivity;
  /** Recommended owner — guides, doesn't force. */
  delivery: DeliveryType;
  /** Partner expertise to look for, when delivery is "partner". */
  partnerType?: string;
  /** Why this is recommended. */
  reason: string;
  /** Concrete next-action labels for the card (recommended first, override after). */
  suggestedActions: string[];
};

function buildRecommendation(area: SsaInterventionArea, score: number): InterventionRecommendation {
  const policy = POLICY[area];
  const severity = classifySeverity(score);
  const activityNoun = policy.activity === "Visit" ? "Visit" : policy.activity === "Training" ? "Training" : policy.activity;

  // Recommended action first, then the override path (the other delivery owner).
  const suggestedActions =
    policy.delivery === "partner"
      ? [
          `Assign ${area} ${activityNoun} to Partner`,
          `Schedule Staff ${activityNoun} (override)`,
          "View SSA",
        ]
      : [
          `Schedule Staff ${area} ${activityNoun}`,
          `Assign ${area} to Partner (override)`,
          "View SSA",
        ];

  return {
    intervention: area,
    score,
    severity,
    recommendedActivity: policy.activity,
    delivery: policy.delivery,
    partnerType: policy.delivery === "partner" ? policy.partnerType : undefined,
    reason: policy.reason,
    suggestedActions,
  };
}

export type SchoolRecommendation = {
  schoolId: string;
  hasSsa: boolean;
  /** Overall SSA average across the 8 interventions (/10), or null without SSA. */
  overallAverage: number | null;
  currentDate?: string;
  /** Every intervention, ranked weakest → strongest, with its severity band. */
  all: InterventionRecommendation[];
  /** Only the interventions scoring below Good (7) — the actionable gaps. */
  struggling: InterventionRecommendation[];
};

/**
 * Resolve a school's current per-intervention scores (canonical-keyed). Prefers
 * the most recent IA SSA upload (normalized from the intake labels) so a freshly
 * uploaded SSA feeds recommendations immediately; falls back to the seeded
 * per-school baseline+current scores. Returns undefined when neither exists —
 * the "no scored SSA" state that keeps planning locked.
 */
function currentScoresForSchool(
  schoolId: string,
): { scores: Record<SsaInterventionArea, number>; date?: string } | undefined {
  // Latest IA upload for this school (uploads are stored newest-first).
  const upload = ssaUploads
    .filter((u) => u.schoolId === schoolId)
    .sort((a, b) => (a.ssaDate < b.ssaDate ? 1 : -1))[0];
  if (upload) {
    const normalized = normalizeScores(upload.scores);
    if (isComplete(normalized)) {
      return { scores: normalized as Record<SsaInterventionArea, number>, date: upload.ssaDate };
    }
  }
  // Fall back to the seeded scores (the assignable+scored pool).
  const seed = ssaForSchool(schoolId);
  if (seed) return { scores: seed.current, date: seed.currentDate };
  return undefined;
}

/**
 * The recommendation for a school, derived from its most recent SSA. Returns
 * `hasSsa: false` (and empty lists) when the school has no scored SSA yet — in
 * that state planning is locked and the next action is SIT / SSA, not support.
 */
export function recommendInterventionsForSchool(schoolId: string): SchoolRecommendation {
  const resolved = currentScoresForSchool(schoolId);
  if (!resolved) {
    return { schoolId, hasSsa: false, overallAverage: null, all: [], struggling: [] };
  }

  // Deterministic tie-break (score, then intervention name) so the two weakest are
  // stable across renders and match the backend recommendation engine on ties.
  const all = SSA_INTERVENTIONS.map((area) => buildRecommendation(area, resolved.scores[area])).sort(
    (a, b) => a.score - b.score || a.intervention.localeCompare(b.intervention),
  );
  const struggling = all.filter((r) => isStruggling(r.score));
  const sum = all.reduce((acc, r) => acc + r.score, 0);
  const overallAverage = Math.round((sum / all.length) * 10) / 10;

  return {
    schoolId,
    hasSsa: true,
    overallAverage,
    currentDate: resolved.date,
    all,
    struggling,
  };
}

/**
 * The 4 weakest interventions for a school — the focus areas a Core-school
 * package (4 visits + 4 trainings) is built around. Consumed by the Core
 * planning surface in a later phase; defined here so the SSA→focus rule lives
 * in one place.
 */
export function coreFocusInterventions(schoolId: string): InterventionRecommendation[] {
  return recommendInterventionsForSchool(schoolId).all.slice(0, 4);
}

/** Compact, serializable summary for list rows (School Directory, planning). */
export type SchoolRecommendationSummary = {
  hasSsa: boolean;
  strugglingCount: number;
  weakestArea?: SsaInterventionArea;
  weakestScore?: number;
  weakestSeverity?: Severity;
  weakestDelivery?: DeliveryType;
};

export function schoolRecommendationSummary(schoolId: string): SchoolRecommendationSummary {
  const r = recommendInterventionsForSchool(schoolId);
  if (!r.hasSsa) return { hasSsa: false, strugglingCount: 0 };
  const weakest = r.all[0]; // ranked weakest → strongest
  return {
    hasSsa: true,
    strugglingCount: r.struggling.length,
    weakestArea: weakest?.intervention,
    weakestScore: weakest?.score,
    weakestSeverity: weakest?.severity,
    weakestDelivery: weakest?.delivery,
  };
}
