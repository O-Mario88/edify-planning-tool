/**
 * Figure tiles (owner, 2026-11-16: every figure strip as separate tiles, as
 * the Smart Route Planner's): which icon a tile draws, read from its label as
 * the web reads it (platform/web/src/lib/figureIcon.ts), and how many tiles
 * share a row.
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

/** Below this width tiles sit two a row. */
const WIDE = 768;
const MAX_ROW = 5;

/** Tiles a row: two on a phone; on a wide screen rows as even as they can be. */
export function tileColumns(count: number, width: number): number {
  if (width < WIDE) return Math.min(2, Math.max(count, 1));
  if (count <= 1) return 1;
  return Math.ceil(count / Math.ceil(count / MAX_ROW));
}
