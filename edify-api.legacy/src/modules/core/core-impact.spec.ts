import { describe, expect, it } from 'vitest';
import { computeImpact, scoresFromSsaRows } from './core-impact';
import { SsaIntervention } from '@prisma/client';

describe('core-impact', () => {
  const baseline = scoresFromSsaRows([
    { intervention: 'teaching_and_learning' as SsaIntervention, score: 6 },
    { intervention: 'leadership' as SsaIntervention, score: 7 },
    { intervention: 'financial_health' as SsaIntervention, score: 8 },
    { intervention: 'learning_environment' as SsaIntervention, score: 7.5 },
    { intervention: 'christlike_behaviour' as SsaIntervention, score: 8 },
    { intervention: 'exposure_to_word_of_god' as SsaIntervention, score: 8.5 },
    { intervention: 'government_requirements' as SsaIntervention, score: 7 },
    { intervention: 'education_technology' as SsaIntervention, score: 6.5 },
  ]);

  it('computes average change and champion candidacy when priority areas improve', () => {
    const followUp = { ...baseline, teaching_and_learning: 8, leadership: 8.5, financial_health: 8.5, learning_environment: 8 };
    const interventions = [
      { area: 'teaching_and_learning' as SsaIntervention, label: 'Teaching Environment', rank: 1, baselineScore: 6 },
      { area: 'leadership' as SsaIntervention, label: 'Leadership Best Practice', rank: 2, baselineScore: 7 },
      { area: 'financial_health' as SsaIntervention, label: 'Fees/Budget and Accounts', rank: 3, baselineScore: 8 },
      { area: 'learning_environment' as SsaIntervention, label: 'Learning Environment', rank: 4, baselineScore: 7.5 },
    ];
    const impact = computeImpact(baseline, followUp, 7.4, 8.2, interventions);
    expect(impact.averageChange).toBe(0.8);
    expect(impact.impactStatus).toBe('Improved');
    expect(impact.championCandidate).toBe(true);
    expect(impact.priorityInterventionChange.every((c) => c.priority)).toBe(true);
  });

  it('does not flag champion when follow-up average is below threshold', () => {
    const followUp = { ...baseline, teaching_and_learning: 7.5, leadership: 7.5, financial_health: 7.5, learning_environment: 7.5 };
    const interventions = [
      { area: 'teaching_and_learning' as SsaIntervention, label: 'Teaching Environment', rank: 1, baselineScore: 6 },
    ];
    const impact = computeImpact(baseline, followUp, 7.4, 7.6, interventions);
    expect(impact.championCandidate).toBe(false);
  });
});
