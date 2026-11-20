import { create } from '@bufbuild/protobuf';

import { PageColumnSchema, PageRowSchema } from '../gen/edify/screens/v1/page_pb';
import { LEAD_FACTS, LIST_FROM, asList, rowCard, summaryOf } from '../ui/page/rowCard';

const columns = ['School ID', 'School Name', 'District', 'Status', 'Planned', 'Visits', 'Trainings', 'Owner', ''].map((label, i) =>
  create(PageColumnSchema, { label, numeric: i === 5 || i === 6 }),
);

describe('a row read as a card (the web reads it the same way)', () => {
  test('names the record, keeps its ID and status apart, leads with the first facts and holds the rest', () => {
    const row = create(PageRowSchema, {
      cells: [
        { text: '1688' },
        { text: 'Mukono Primary School', href: '/schools/1688' },
        { text: 'Mukono' },
        { text: 'Overdue', tone: 'danger' },
        { text: '1 Apr 2026' },
        { text: '2' },
        { text: '0' },
        { text: 'Moses K.' },
        { actions: [{ label: 'Open', enabled: true, href: '/my-plan/1' }] },
      ],
    });
    const card = rowCard(columns, row);
    expect(card.title?.text).toBe('Mukono Primary School');
    expect(card.id?.cell.text).toBe('1688');
    expect(card.status?.text).toBe('Overdue');
    expect(card.lead.map((f) => f.label)).toEqual(['District', 'Planned', 'Visits', 'Trainings']);
    expect(card.lead).toHaveLength(LEAD_FACTS);
    expect(card.rest.map((f) => f.label)).toEqual(['Owner']);
    expect(card.actions?.actions[0]?.label).toBe('Open');
  });

  test('takes the bold words, else the first words, as the title when nothing links', () => {
    const card = rowCard(columns, create(PageRowSchema, { cells: [{ text: '' }, { text: 'Cluster B', strong: true }, { text: '' }, { text: 'Planned' }] }));
    expect(card.title?.text).toBe('Cluster B');
    expect(card.id).toBeUndefined();
    expect(card.status?.text).toBe('Planned');
    expect(rowCard(columns, create(PageRowSchema, { cells: [{ text: '' }, { text: 'Kampala' }] })).title?.text).toBe('Kampala');
  });
});

describe('a long table on a phone', () => {
  test('is a compact list from 16 rows, cards below', () => {
    expect(asList(15)).toBe(false);
    expect(asList(LIST_FROM)).toBe(true);
    expect(asList(50)).toBe(true);
  });

  test('sums a row up in one line: its status, then its first two facts', () => {
    const row = create(PageRowSchema, {
      cells: [{ text: '1688' }, { text: 'Mukono Primary School', href: '/schools/1688' }, { text: 'Mukono' }, { text: 'Overdue', tone: 'danger' }, { text: '1 Apr 2026' }],
    });
    expect(summaryOf(rowCard(columns, row))).toBe('Overdue · Mukono · 1 Apr 2026');
    expect(summaryOf(rowCard(columns, create(PageRowSchema, { cells: [{ text: '' }, { text: 'Kampala' }] })))).toBe('');
  });
});
