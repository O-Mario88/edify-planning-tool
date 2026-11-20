import { fromJson } from '@bufbuild/protobuf';
import type { JsonValue } from '@bufbuild/protobuf';
import { describe, expect, it } from 'vitest';

import { GetPageResponseSchema } from '@/gen/edify/screens/v1/page_screen_pb';

import { FIGURES_SHOWN, foldFigures, liftHeroes } from './heroStrip';

const blocksOf = (...blocks: JsonValue[]) => fromJson(GetPageResponseSchema, { blocks }).blocks;
const strip = (title: string, ...labels: string[]): JsonValue => ({ strip: { title, metrics: labels.map((label) => ({ label, value: '1' })) } });
const labelsOf = (block: { kind: { case?: string; value?: unknown } }) =>
  block.kind.case === 'strip' ? (block.kind.value as { metrics: { label: string }[] }).metrics.map((m) => m.label) : [];

describe('a page’s hero figures', () => {
  it('lead the Programme Lead’s dashboard in a strip of their own, moved out of the strips they came in (owner, 2026-11-20)', () => {
    const page = blocksOf(
      { filters: { filters: [] } },
      strip('Team pulse', 'Team Priority Progress', 'Waiting on You', 'SSA Coverage'),
      strip('Team planning monitor', 'Visits Planned Against Target', 'Schools Not Clustered'),
    );
    const { blocks, heroAt } = liftHeroes(page, '/dashboard');
    expect(heroAt).toBe(1);
    expect(blocks.map(labelsOf)).toEqual([
      [],
      ['Waiting on You', 'Visits Planned Against Target'],
      ['Team Priority Progress', 'SSA Coverage'],
      ['Schools Not Clustered'],
    ]);
  });

  it('leaves a page with no heroes, or none of its heroes, as it came', () => {
    const page = blocksOf(strip('Figures', 'Schools'));
    expect(liftHeroes(page, '/my-plan')).toEqual({ blocks: page, heroAt: -1 });
    expect(liftHeroes(page, '/dashboard').heroAt).toBe(-1);
    expect(liftHeroes(page, '/dashboard').blocks.map(labelsOf)).toEqual([['Schools']]);
  });
});

describe('a strip of many figures', () => {
  const m = (label: string, value = '1') => ({ label, value });

  it('shows its first four measured figures and folds the rest (owner, 2026-11-20: "reduce the number of kpi stats")', () => {
    const figures = [m('A'), m('B', 'Not measured'), m('C'), m('D'), m('E'), m('F', ''), m('G')];
    const { shown, folded } = foldFigures(figures);
    expect(FIGURES_SHOWN).toBe(4);
    expect(shown.map((f) => f.label)).toEqual(['A', 'C', 'D', 'E']);
    expect(folded.map((f) => f.label)).toEqual(['B', 'F', 'G']);
  });

  it('folds nothing in a strip of four or fewer', () => {
    const figures = [m('A'), m('B', 'Not measured')];
    expect(foldFigures(figures)).toEqual({ shown: figures, folded: [] });
  });
});
