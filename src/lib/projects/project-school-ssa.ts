// Per-school, per-intervention SSA scores for the SCHOOL DIRECTORY (intake)
// schools — the ID space projects actually assign against (numeric schoolIds
// like "40118"), keyed on the canonical 8-intervention planning enum
// (SsaInterventionArea).
//
// WHY THIS EXISTS: the rich per-intervention SSA history in
// planning/ssa-performance-mock.ts is keyed by GAP-* planning ids, a separate
// namespace with no mapping to intake schools, and intake's own `ssaUploads`
// store ships empty. Project eligibility ("which schools are weak in the
// intervention this project targets?") and project impact ("did the mapped
// intervention move after the project?") both need real before/after scores
// for the assignable schools. This module is that source.
//
// Year-1 mock; Year-2 backend swap = a join on the SSA records table by
// schoolId. The shape (baseline + current per intervention) is deliberately
// the minimum the impact engine needs.

import type { SsaInterventionArea } from "@/lib/planning/planning-gaps-mock";
import { SSA_INTERVENTIONS } from "@/lib/planning/ssa-performance-mock";

export type InterventionScores = Record<SsaInterventionArea, number>; // 0–10

export type ProjectSchoolSsa = {
  schoolId: string;
  /** SSA taken before the project window — the baseline for impact. */
  baselineDate: string;
  baseline: InterventionScores;
  /** Most recent SSA — the "after" reading. */
  currentDate: string;
  current: InterventionScores;
};

/** Fill all 8 interventions from a partial map, defaulting the rest. */
function fill(partial: Partial<InterventionScores>, base: number): InterventionScores {
  const out = {} as InterventionScores;
  for (const area of SSA_INTERVENTIONS) out[area] = partial[area] ?? base;
  return out;
}

// Seed spans the intake districts and biases weakness so each project's
// mapped intervention has a believable candidate pool:
//   • EdTech weakness        → 40118 (in SP-EDTECH), 51884, 90050
//   • Christlike Behaviour   → 32791 (in SP-CCSEL), 33180, 80124
//   • Teaching & Learning    → 70210, 33120, 52040, 80110, 70233
//   • Learning Environment   → 60233, 52910
// Schools already in a project show real movement on the mapped area
// (current > baseline); comparison schools drift only slightly.
const SEED: ProjectSchoolSsa[] = [
  // ── In SP-EDTECH (Education Technology) — clear post-project lift ──
  {
    schoolId: "40118", baselineDate: "2025-01-10", currentDate: "2026-05-20",
    baseline: fill({ "Education Technology": 3, "Learning Environment": 4, "Teaching & Learning": 5 }, 6),
    current:  fill({ "Education Technology": 6, "Learning Environment": 6, "Teaching & Learning": 6 }, 6),
  },
  // ── In SP-CCSEL (Christlike Behaviour) — clear lift ──
  {
    schoolId: "32791", baselineDate: "2025-01-28", currentDate: "2026-05-12",
    baseline: fill({ "Christlike Behaviour": 4, "Exposure to the Word of God": 5, "Teaching & Learning": 6 }, 6),
    current:  fill({ "Christlike Behaviour": 7, "Exposure to the Word of God": 7, "Teaching & Learning": 6 }, 6),
  },
  // ── EdTech-weak candidates (not yet in a project) ──
  {
    schoolId: "51884", baselineDate: "2025-02-15", currentDate: "2026-04-30",
    baseline: fill({ "Education Technology": 3, "Learning Environment": 5 }, 6),
    current:  fill({ "Education Technology": 3, "Learning Environment": 5 }, 6),
  },
  {
    schoolId: "90050", baselineDate: "2025-03-01", currentDate: "2026-05-05",
    baseline: fill({ "Education Technology": 2, "Teaching & Learning": 5 }, 6),
    current:  fill({ "Education Technology": 3, "Teaching & Learning": 5 }, 6),
  },
  // ── Teaching & Learning-weak candidates (for a Literacy/Numeracy project) ──
  {
    schoolId: "70210", baselineDate: "2025-02-20", currentDate: "2026-05-18",
    baseline: fill({ "Teaching & Learning": 4, "Learning Environment": 5 }, 6),
    current:  fill({ "Teaching & Learning": 4, "Learning Environment": 5 }, 6),
  },
  {
    schoolId: "70233", baselineDate: "2025-02-22", currentDate: "2026-05-19",
    baseline: fill({ "Teaching & Learning": 4, "Leadership": 5 }, 6),
    current:  fill({ "Teaching & Learning": 5, "Leadership": 5 }, 6),
  },
  {
    schoolId: "33120", baselineDate: "2025-03-05", currentDate: "2026-05-10",
    baseline: fill({ "Teaching & Learning": 3, "Education Technology": 5 }, 6),
    current:  fill({ "Teaching & Learning": 4, "Education Technology": 5 }, 6),
  },
  {
    schoolId: "52040", baselineDate: "2025-03-12", currentDate: "2026-05-14",
    baseline: fill({ "Teaching & Learning": 4, "Financial Health": 5 }, 6),
    current:  fill({ "Teaching & Learning": 4, "Financial Health": 5 }, 6),
  },
  {
    schoolId: "80110", baselineDate: "2025-03-18", currentDate: "2026-05-16",
    baseline: fill({ "Teaching & Learning": 4, "Government Requirements & Compliance": 5 }, 6),
    current:  fill({ "Teaching & Learning": 5, "Government Requirements & Compliance": 5 }, 6),
  },
  // ── Christlike Behaviour-weak candidates ──
  {
    schoolId: "33180", baselineDate: "2025-03-22", currentDate: "2026-05-08",
    baseline: fill({ "Christlike Behaviour": 4, "Exposure to the Word of God": 5 }, 6),
    current:  fill({ "Christlike Behaviour": 4, "Exposure to the Word of God": 5 }, 6),
  },
  {
    schoolId: "80124", baselineDate: "2025-04-02", currentDate: "2026-05-09",
    baseline: fill({ "Christlike Behaviour": 3, "Leadership": 5 }, 6),
    current:  fill({ "Christlike Behaviour": 4, "Leadership": 5 }, 6),
  },
  // ── Learning Environment-weak candidates ──
  {
    schoolId: "60233", baselineDate: "2025-02-10", currentDate: "2026-05-06",
    baseline: fill({ "Learning Environment": 3, "Education Technology": 4 }, 6),
    current:  fill({ "Learning Environment": 4, "Education Technology": 4 }, 6),
  },
  {
    schoolId: "52910", baselineDate: "2025-02-26", currentDate: "2026-05-11",
    baseline: fill({ "Learning Environment": 4, "Financial Health": 5 }, 6),
    current:  fill({ "Learning Environment": 5, "Financial Health": 5 }, 6),
  },
];

const BY_SCHOOL: Record<string, ProjectSchoolSsa> = Object.fromEntries(
  SEED.map((r) => [r.schoolId, r]),
);

export function ssaForSchool(schoolId: string): ProjectSchoolSsa | undefined {
  return BY_SCHOOL[schoolId];
}

export function hasSsa(schoolId: string): boolean {
  return schoolId in BY_SCHOOL;
}

export type WeakInterventionPick = { intervention: SsaInterventionArea; score: number };

/** Lowest-scoring intervention on the most recent SSA (the gap). */
export function weakestIntervention(schoolId: string): WeakInterventionPick | undefined {
  const r = BY_SCHOOL[schoolId];
  if (!r) return undefined;
  let pick: WeakInterventionPick | undefined;
  for (const area of SSA_INTERVENTIONS) {
    const score = r.current[area];
    if (!pick || score < pick.score) pick = { intervention: area, score };
  }
  return pick;
}

/** Score for one intervention, baseline or current. */
export function interventionScore(
  schoolId: string,
  intervention: SsaInterventionArea,
  which: "baseline" | "current",
): number | undefined {
  const r = BY_SCHOOL[schoolId];
  return r ? r[which][intervention] : undefined;
}

/** All school ids with seeded SSA scores (the assignable+scored pool). */
export function scoredSchoolIds(): string[] {
  return Object.keys(BY_SCHOOL);
}
