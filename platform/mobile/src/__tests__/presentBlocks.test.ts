import { fromJson } from '@bufbuild/protobuf';
import type { JsonValue } from '@bufbuild/protobuf';

import type { PageLink } from '../gen/edify/screens/v1/page_pb';
import { GetPageResponseSchema } from '../gen/edify/screens/v1/page_screen_pb';

import { isStepper, presentBlocks, stepOf, tabCount } from '../ui/page/presentBlocks';

const blocksOf = (...blocks: JsonValue[]) => fromJson(GetPageResponseSchema, { blocks }).blocks;
const links = (...texts: string[]): JsonValue => ({ panel: { items: [{ links: { links: texts.map((text, i) => ({ text, href: `/x?${i}` })) } }] } });
const linkList = (...texts: string[]) => texts.map((text) => ({ text, href: '', caption: '', drawer: false }) as PageLink);

describe('a panel of counted links', () => {
  it('is drawn as a row of figure tiles, the figure apart from its words (owner, 2026-11-20)', () => {
    const [strip] = presentBlocks(blocksOf(links('0 planned this week', '0 verified', '0 past their day, not completed', '8 past due, any age')));
    expect(strip?.kind.case).toBe('strip');
    const metrics = strip?.kind.case === 'strip' ? strip.kind.value.metrics : [];
    expect(metrics.map((m) => [m.value, m.label, m.href])).toEqual([
      ['0', 'Planned this week', '/x?0'],
      ['0', 'Verified', '/x?1'],
      ['0', 'Past their day, not completed', '/x?2'],
      ['8', 'Past due, any age', '/x?3'],
    ]);
    expect(metrics.every((m) => m.note === '')).toBe(true);
  });

  it('leaves links that are not all counted, and a single counted link, as they came', () => {
    const mixed = blocksOf(links('0 planned', 'Open the plan'), links('3 schools'));
    expect(presentBlocks(mixed).map((b) => b.kind.case)).toEqual(['panel', 'panel']);
  });
});

describe('links that step through periods', () => {
  it('are a stepper when the first goes back and the last goes forward', () => {
    expect(isStepper(linkList('‹ Previous week', 'Next week ›'))).toBe(true);
    expect(isStepper(linkList('‹ Previous week', 'This week', 'Next week ›'))).toBe(true);
    expect(isStepper(linkList('Previous week', 'Next week'))).toBe(false);
    expect(isStepper(linkList('‹ Back'))).toBe(false);
  });

  it('names each step by its words and its way', () => {
    const [back, here, forward] = linkList('‹ Previous week', 'This week', 'Next week ›');
    expect(stepOf(back as PageLink)).toEqual({ words: 'Previous week', way: 'back' });
    expect(stepOf(here as PageLink)).toEqual({ words: 'This week', way: 'here' });
    expect(stepOf(forward as PageLink)).toEqual({ words: 'Next week', way: 'forward' });
  });
});

describe('a tab’s count', () => {
  it('is read off the end of its label, never from a number that names the tab', () => {
    expect(tabCount('My activities 8')).toEqual({ label: 'My activities', count: 8 });
    expect(tabCount('Waiting 120')).toEqual({ label: 'Waiting', count: 120 });
    expect(tabCount('My week')).toEqual({ label: 'My week', count: 0 });
    expect(tabCount('Week 47')).toEqual({ label: 'Week 47', count: 0 });
    expect(tabCount('FY 2027')).toEqual({ label: 'FY 2027', count: 0 });
    expect(tabCount('Q1')).toEqual({ label: 'Q1', count: 0 });
  });
});
