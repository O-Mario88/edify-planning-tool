/**
 * The icon a figure tile draws beside its figure (owner, 2026-11-16: every
 * figure strip as separate tiles, as the Smart Route Planner's). The feed
 * carries no icon, so it is read from the figure's label; the first rule
 * that matches wins, so problems ("Overdue", "Without SSA") beat the thing
 * they are about.
 */
export type FigureIconName = 'school' | 'cluster' | 'route' | 'clock' | 'calendar' | 'check' | 'alert' | 'money' | 'people' | 'training' | 'chart';

const RULES: ReadonlyArray<readonly [RegExp, FigureIconName]> = [
  [/overdue|critical|blocked|escalat|risk|missing|without|not (met|grouped|planned)|unsuccessful|attention|gap|needing|required/i, 'alert'],
  [/distance|\bkm\b|route/i, 'route'],
  [/travel|time|duration|hours?\b|minutes?/i, 'clock'],
  [/cost|budget|ugx|fund|advance|payment|spend|amount|invoice|disburse/i, 'money'],
  [/complet|done|verified|approved|submitted|ready|confirmed/i, 'check'],
  [/train|course|learning|cpd/i, 'training'],
  [/average|score|\bssa\b|rate\b|%|performance|intervention/i, 'chart'],
  [/staff|partner|team|people|leader|officer|users?\b|cceo/i, 'people'],
  [/schedul|planned|plan\b|calendar|week|visit/i, 'calendar'],
  [/school/i, 'school'],
  [/cluster/i, 'cluster'],
];

export function figureIcon(label: string): FigureIconName {
  return RULES.find(([pattern]) => pattern.test(label))?.[1] ?? 'chart';
}
