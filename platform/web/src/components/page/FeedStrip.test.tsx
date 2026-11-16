/**
 * A strip's figures are separate tiles (owner, 2026-11-16): each the figure,
 * its label and the line under it, with an info dot for a note, in even rows
 * of at most five on a wide screen.
 */
import { create } from '@bufbuild/protobuf';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { PageStripSchema } from '@/gen/edify/screens/v1/page_pb';

import { KpiStrip } from '../blocks/KpiStrip';
import { FeedStrip, tileColumns } from './FeedStrip';

const strip = create(PageStripSchema, {
  title: 'Figures',
  metrics: [
    { label: 'School Leaders Trained', value: '2', helper: '2 in school' },
    { label: 'Overdue Plans', value: '105', note: 'Past their date, not completed', tone: 'danger' },
  ],
});

describe('a strip', () => {
  it('draws each figure as its own tile: figure, label, the line under it', () => {
    const html = renderToStaticMarkup(<FeedStrip strip={strip} resolve={(href) => href} />);
    expect(html.match(/data-tile=/g)).toHaveLength(2);
    expect(html).toMatch(/>2<\/dd><dt[^>]*>School Leaders Trained<\/dt><dd[^>]*>2 in school<\/dd>/);
  });

  it('says a note in an info dot and tints a problem red', () => {
    const html = renderToStaticMarkup(<FeedStrip strip={strip} resolve={(href) => href} />);
    expect(html).toContain('aria-label="Past their date, not completed"');
    expect(html).toContain('data-tile="alert"');
    expect(html).toContain('color:#dc2626');
  });

  it('spreads tiles into even rows of at most five', () => {
    expect([1, 4, 5, 6, 8, 9, 10, 12].map(tileColumns)).toEqual([1, 4, 5, 3, 4, 5, 5, 4]);
  });

  it('is drawn the same way outside the page feed', () => {
    expect(renderToStaticMarkup(<KpiStrip strip={strip} />)).toBe(renderToStaticMarkup(<FeedStrip strip={strip} resolve={(href) => href} />));
  });
});
