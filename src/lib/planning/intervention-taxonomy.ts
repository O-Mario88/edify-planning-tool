// Intervention taxonomy reconciliation — the ONE place the differently-worded
// SSA intervention label sets are mapped to the canonical 8.
//
// There are three historical label sets in the codebase:
//   1. SsaInterventionArea  (planning-gaps-mock.ts)  ← CANONICAL (spec §2)
//   2. SSA_INTERVENTION_AREAS (intake-core.ts)       ← the IA upload form keys
//   3. SSA_EIGHT             (ssa-mock.ts)            ← the legacy display dashboard
//
// (1) is canonical and drives recommendations + per-school scores. (2) is the
// live data contract IA actually uploads against; it is the SAME 8 concepts,
// only worded differently, so this module maps (2) → (1) so an uploaded SSA can
// feed the recommendation engine directly. (3) is a separate display-only mock
// (it carries "Enrollment" instead of "Education Technology") and is left as-is.

import type { SsaInterventionArea } from "./planning-gaps-mock";
import { SSA_INTERVENTIONS } from "./ssa-performance-mock";

/** Intake-form label → canonical intervention. The two sets are a bijection. */
export const INTAKE_TO_CANONICAL: Record<string, SsaInterventionArea> = {
  "Christlike Behaviour": "Christlike Behaviour",
  "Exposure to the Word of God": "Exposure to the Word of God",
  "Fees/Budget and Accounts": "Financial Health",
  "Government Requirement": "Government Requirements & Compliance",
  "Leadership Best Practice": "Leadership",
  "Learning Environment": "Learning Environment",
  "Teaching Environment": "Teaching & Learning",
  "Education Technology": "Education Technology",
};

const CANONICAL_SET = new Set<string>(SSA_INTERVENTIONS);

/**
 * Normalize a raw score map (keyed by EITHER the intake labels or the canonical
 * labels) into a canonical-keyed map. Unknown keys are ignored. Returns a
 * partial — callers should treat absent areas as "not assessed".
 */
export function normalizeScores(raw: Record<string, number>): Partial<Record<SsaInterventionArea, number>> {
  const out: Partial<Record<SsaInterventionArea, number>> = {};
  for (const [key, value] of Object.entries(raw)) {
    if (typeof value !== "number" || Number.isNaN(value)) continue;
    const canonical = CANONICAL_SET.has(key) ? (key as SsaInterventionArea) : INTAKE_TO_CANONICAL[key];
    if (canonical) out[canonical] = value;
  }
  return out;
}

/** True when a normalized map covers all 8 canonical interventions. */
export function isComplete(scores: Partial<Record<SsaInterventionArea, number>>): boolean {
  return SSA_INTERVENTIONS.every((area) => typeof scores[area] === "number");
}
