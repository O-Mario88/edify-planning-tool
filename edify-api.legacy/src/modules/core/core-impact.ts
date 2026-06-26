import { SsaIntervention } from '@prisma/client';
import { ALL_INTERVENTIONS, CHAMPION_SSA_THRESHOLD, INTERVENTION_LABEL, StoredIntervention } from './core-interventions';

export type ScoreMap = Partial<Record<SsaIntervention, number>>;

export type InterventionChangeDto = {
  intervention: string;
  label: string;
  baselineScore: number;
  followUpScore: number;
  change: number;
  classification: 'Improved' | 'No Change' | 'Declined' | 'No Comparison';
  priority: boolean;
};

export type CoreImpactDto = {
  baselineAverage: number;
  followUpAverage: number;
  averageChange: number;
  priorityInterventionChange: InterventionChangeDto[];
  allInterventionChange: InterventionChangeDto[];
  bestImproved?: string;
  weakestRemaining?: string;
  impactStatus: 'Improved' | 'No Change' | 'Declined' | 'No Comparison';
  championCandidate: boolean;
  computedAt: string;
};

function classify(change: number, hasBoth: boolean): InterventionChangeDto['classification'] {
  if (!hasBoth) return 'No Comparison';
  if (change > 0.0001) return 'Improved';
  if (change < -0.0001) return 'Declined';
  return 'No Change';
}

export function computeImpact(
  baselineScores: ScoreMap,
  followUpScores: ScoreMap,
  baselineAverage: number,
  followUpAverage: number,
  interventions: StoredIntervention[],
): CoreImpactDto {
  const priority = new Set(interventions.map((i) => i.area));

  const all: InterventionChangeDto[] = ALL_INTERVENTIONS.map((area) => {
    const b = baselineScores[area];
    const f = followUpScores[area];
    const hasBoth = b != null && f != null;
    const change = hasBoth ? Math.round((f! - b!) * 10) / 10 : 0;
    return {
      intervention: INTERVENTION_LABEL[area],
      label: INTERVENTION_LABEL[area],
      baselineScore: b ?? 0,
      followUpScore: f ?? 0,
      change,
      classification: classify(change, hasBoth),
      priority: priority.has(area),
    };
  });

  const priorityChange = all.filter((c) => c.priority);
  const averageChange = Math.round((followUpAverage - baselineAverage) * 10) / 10;
  const improved = [...all].sort((a, b) => b.change - a.change);
  const bestImproved = improved[0]?.change > 0 ? improved[0].intervention : undefined;
  const weakestRemaining = [...all].sort((a, b) => a.followUpScore - b.followUpScore)[0]?.intervention;
  const impactStatus = averageChange > 0.0001 ? 'Improved' : averageChange < -0.0001 ? 'Declined' : 'No Change';
  const championCandidate =
    followUpAverage >= CHAMPION_SSA_THRESHOLD &&
    priorityChange.length > 0 &&
    priorityChange.every((c) => c.change > 0);

  return {
    baselineAverage,
    followUpAverage,
    averageChange,
    priorityInterventionChange: priorityChange,
    allInterventionChange: all,
    bestImproved,
    weakestRemaining,
    impactStatus,
    championCandidate,
    computedAt: new Date().toISOString(),
  };
}

export function scoresFromSsaRows(rows: { intervention: SsaIntervention; score: number }[]): ScoreMap {
  const out: ScoreMap = {};
  for (const r of rows) out[r.intervention] = r.score;
  return out;
}
