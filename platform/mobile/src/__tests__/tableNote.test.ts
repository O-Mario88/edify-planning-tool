import { fromJson } from '@bufbuild/protobuf';
import type { JsonValue } from '@bufbuild/protobuf';

import { GetPageResponseSchema } from '../gen/edify/screens/v1/page_screen_pb';

import { tableNote } from '../ui/page/tableNote';

const NOTE = 'A school counts from the day it is committed: planned by you, assigned to a partner, or on a group training.';
const table: JsonValue = { table: { title: 'My training summary', columns: [{ label: 'Training' }], rows: [{ cells: [{ text: 'Leadership' }] }] } };
const note = (text = NOTE): JsonValue => ({ panel: { items: [{ text }] } });
const pagerPanel: JsonValue = { panel: { items: [{ text: 'Showing 1–50 of 102' }, { links: { links: [{ text: 'Next', href: '?page=2' }] } }] } };
const blocksOf = (...blocks: JsonValue[]) => fromJson(GetPageResponseSchema, { blocks }).blocks;

describe('a table note sent as its own block', () => {
  test('is the sentence in an untitled panel straight after a table, or after its pager', () => {
    expect(tableNote(blocksOf(table, note()), 1)).toBe(NOTE);
    expect(tableNote(blocksOf(table, pagerPanel, note()), 2)).toBe(NOTE);
    expect(tableNote(blocksOf(table, { pager: { summary: 'Page 1 of 2' } }, note()), 2)).toBe(NOTE);
  });

  test('is not a panel away from a table, a titled or toned panel, a link, or a short status line', () => {
    expect(tableNote(blocksOf(note()), 0)).toBeNull();
    expect(tableNote(blocksOf({ strip: { title: 'Figures' } }, note()), 1)).toBeNull();
    expect(tableNote(blocksOf(table, { panel: { title: 'Details', items: [{ text: NOTE }] } }), 1)).toBeNull();
    expect(tableNote(blocksOf(table, { panel: { items: [{ text: NOTE, tone: 'warning' }] } }), 1)).toBeNull();
    expect(tableNote(blocksOf(table, { panel: { items: [{ text: NOTE, textLinks: [{ text: 'partner', href: '/p' }] }] } }), 1)).toBeNull();
    expect(tableNote(blocksOf(table, note('No planning records match your filters.')), 1)).toBeNull();
    expect(tableNote(blocksOf(table, pagerPanel), 1)).toBeNull();
    expect(tableNote(blocksOf(table), 0)).toBeNull();
  });
});
