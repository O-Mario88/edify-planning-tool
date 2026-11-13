import { create } from '@bufbuild/protobuf';
import { describe, expect, it } from 'vitest';

import { PagePanelItemSchema, PagePanelSchema } from '@/gen/edify/screens/v1/page_pb';

import { noteTone, sentenceParts } from './sentence';

describe('sentenceParts', () => {
  it('keeps the sentence around a link whole, the link at its words', () => {
    const text = 'Every school is still in the School Directory — add them to a cluster.';
    expect(sentenceParts(text, '', [{ text: 'School Directory', href: '/schools' }])).toEqual([
      { kind: 'text', text: 'Every school is still in the ' },
      { kind: 'link', text: 'School Directory', href: '/schools' },
      { kind: 'text', text: ' — add them to a cluster.' },
    ]);
  });

  it('draws the bold opening apart from the rest', () => {
    expect(sentenceParts('Your FY2027 visits: 7 of 560 planned. Core 2 of 204.', 'Your FY2027 visits: 7 of 560 planned.', [])).toEqual([
      { kind: 'lead', text: 'Your FY2027 visits: 7 of 560 planned.' },
      { kind: 'text', text: ' Core 2 of 204.' },
    ]);
  });

  it('leaves a link whose words are not in the text out rather than inventing them', () => {
    expect(sentenceParts('Plain words.', '', [{ text: 'Elsewhere', href: '/x' }])).toEqual([{ kind: 'text', text: 'Plain words.' }]);
  });
});

describe('noteTone', () => {
  const text = (value: string, tone: string) => create(PagePanelItemSchema, { kind: { case: 'text', value }, tone });

  it('is the tone of an untitled card of toned paragraphs', () => {
    expect(noteTone(create(PagePanelSchema, { items: [text('Your visits.', 'info')] }))).toBe('info');
    expect(noteTone(create(PagePanelSchema, { items: [text('Past due.', 'warning')] }))).toBe('warning');
  });

  it('is nothing for a titled card, a plain paragraph or a fact tone', () => {
    expect(noteTone(create(PagePanelSchema, { title: 'SSA', items: [text('x', 'info')] }))).toBe('');
    expect(noteTone(create(PagePanelSchema, { items: [text('x', '')] }))).toBe('');
    expect(noteTone(create(PagePanelSchema, { items: [text('x', 'good')] }))).toBe('');
  });
});
