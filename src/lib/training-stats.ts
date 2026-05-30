// Training aggregate stats — what CD / RVP / IA dashboards read.
//
// Pure functions over training-mock.ts (the cohort catalogue) and
// CLUSTER_SEED (the SSA-driven cluster training recommendations). The
// dashboards consume these so they have a single, audited source for
// every training number — never inline counting in the card.
//
// Not server-only: callers can be server or client. The underlying
// mocks are static; production swaps in queries against the training
// + SSA tables.

import { TRAININGS, type Training, type TrainingStatus } from "@/lib/training-mock";

// ────────── Shape ──────────

export type TrainingStatusCounts = {
  scheduled:    number;
  inProgress:   number;
  completed:    number;
  cancelled:    number;
  /** Sum across all statuses. */
  total:        number;
  /** Verified-portion proxy: completed / (completed + cancelled). 0..100. */
  completionRate: number;
};

export type TrainingByIntervention = {
  intervention: string;
  total:        number;
  completed:    number;
  /** 0..100. completed / total. */
  coveragePct:  number;
};

// ────────── Base counts ──────────

export function trainingStatusCounts(trainings: Training[] = TRAININGS): TrainingStatusCounts {
  const by = (s: TrainingStatus) => trainings.filter((t) => t.status === s).length;
  const scheduled  = by("Scheduled");
  const inProgress = by("In Progress");
  const completed  = by("Completed");
  const cancelled  = by("Cancelled");
  const closed     = completed + cancelled;
  const completionRate = closed === 0 ? 0 : Math.round((completed / closed) * 100);
  return {
    scheduled,
    inProgress,
    completed,
    cancelled,
    total: scheduled + inProgress + completed + cancelled,
    completionRate,
  };
}

// ────────── Country-level (CD dashboard) ──────────
//
// Production reads district→country from school records. The mock
// trainings are cluster-keyed; we expose the same overall counts so
// the CD card has the right shape today and the country filter slots
// in cleanly when the join lands.

export function countryTrainingStats(_country?: string): TrainingStatusCounts {
  // Country filter is a no-op until the cluster→country join lands.
  // Underscore prefix to silence the unused-param lint without losing
  // the future-API signal.
  return trainingStatusCounts(TRAININGS);
}

// ────────── Region-level (RVP dashboard) ──────────

export function regionTrainingStats(): TrainingStatusCounts {
  return trainingStatusCounts(TRAININGS);
}

// ────────── Intervention breakdown (IA + CD detail) ──────────
//
// One row per SSA intervention area, with delivery vs scheduled —
// answers "are we training the gaps we said we'd train?".

export function trainingByIntervention(trainings: Training[] = TRAININGS): TrainingByIntervention[] {
  const map = new Map<string, { total: number; completed: number }>();
  for (const t of trainings) {
    const slot = map.get(t.intervention) ?? { total: 0, completed: 0 };
    slot.total += 1;
    if (t.status === "Completed") slot.completed += 1;
    map.set(t.intervention, slot);
  }
  return Array.from(map.entries())
    .map(([intervention, c]) => ({
      intervention,
      total: c.total,
      completed: c.completed,
      coveragePct: c.total === 0 ? 0 : Math.round((c.completed / c.total) * 100),
    }))
    .sort((a, b) => a.coveragePct - b.coveragePct); // worst coverage first
}

// ────────── Data-quality view (IA dashboard) ──────────
//
// Training evidence completeness. Production reads attendance rosters,
// material uploads, and post-training assessments. The mock derives a
// reasonable distribution from the status field so the IA card paints.

export type TrainingDataQualityStats = {
  /** Completed trainings with full evidence (roster + materials + post-assessment). */
  withFullEvidence:    number;
  /** Completed trainings awaiting verification by IA. */
  pendingVerification: number;
  /** Trainings flagged for missing or contested evidence. */
  failedQc:            number;
  /** Total completed trainings (the denominator for the IA funnel). */
  totalCompleted:      number;
  /** withFullEvidence / totalCompleted, 0..100. */
  evidencePct:         number;
};

export function trainingDataQualityStats(
  trainings: Training[] = TRAININGS,
): TrainingDataQualityStats {
  const completed = trainings.filter((t) => t.status === "Completed");
  // Deterministic split for the demo: 70% full evidence, 20% pending,
  // 10% failed. Production reads the verification queue directly.
  const totalCompleted = completed.length;
  const withFullEvidence    = Math.round(totalCompleted * 0.70);
  const pendingVerification = Math.round(totalCompleted * 0.20);
  const failedQc            = Math.max(0, totalCompleted - withFullEvidence - pendingVerification);
  const evidencePct = totalCompleted === 0 ? 0 : Math.round((withFullEvidence / totalCompleted) * 100);
  return {
    withFullEvidence,
    pendingVerification,
    failedQc,
    totalCompleted,
    evidencePct,
  };
}
