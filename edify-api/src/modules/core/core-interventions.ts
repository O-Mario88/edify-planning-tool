import { SsaIntervention } from '@prisma/client';

/** Backend SsaIntervention enum → FE display label (matches intake-core). */
export const INTERVENTION_LABEL: Record<SsaIntervention, string> = {
  christlike_behaviour: 'Christlike Behaviour',
  exposure_to_word_of_god: 'Exposure to the Word of God',
  financial_health: 'Fees/Budget and Accounts',
  government_requirements: 'Government Requirement',
  leadership: 'Leadership Best Practice',
  learning_environment: 'Learning Environment',
  teaching_and_learning: 'Teaching Environment',
  education_technology: 'Education Technology',
};

export const ALL_INTERVENTIONS = Object.keys(INTERVENTION_LABEL) as SsaIntervention[];

export const CORE_SSA_THRESHOLD = 7.5;
export const CHAMPION_SSA_THRESHOLD = 8.0;
export const VISITS_TARGET = 4;
export const TRAININGS_TARGET = 4;

export type StoredIntervention = {
  area: SsaIntervention;
  label: string;
  rank: number;
  baselineScore: number;
};

export function interventionsFromScores(
  scores: { intervention: SsaIntervention; score: number }[],
): StoredIntervention[] {
  return [...scores]
    .sort((a, b) => a.score - b.score)
    .slice(0, 4)
    .map((s, i) => ({
      area: s.intervention,
      label: INTERVENTION_LABEL[s.intervention],
      rank: i + 1,
      baselineScore: s.score,
    }));
}
