/**
 * A strip's figures are drawn as tiles (owner, 2026-11-20): each its tinted
 * icon, figure, label and the line under it, the whole tile a link where it
 * opens a page, its note kept for a screen reader.
 */
import { create } from '@bufbuild/protobuf';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { PageStripSchema } from '@/gen/edify/screens/v1/page_pb';

import { KpiStrip } from '../blocks/KpiStrip';
import { FeedStrip } from './FeedStrip';

const strip = create(PageStripSchema, {
  title: 'School list context',
  metrics: [
    { label: 'Total Schools', value: '699' },
    { label: 'Client Schools', value: '558', helper: '80% of total', href: '/schools?school_type=client' },
    { label: 'Overdue Plans', value: '105', note: 'Past their date, not completed', tone: 'danger' },
  ],
});

describe('a strip', () => {
  it('draws a tile for each figure: its icon, figure, label and the line under it', () => {
    const html = renderToStaticMarkup(<FeedStrip strip={strip} resolve={(href) => href} />);
    expect(html).toContain('data-kpi-count="3"');
    expect(html.match(/data-figure=""/g)).toHaveLength(3);
    expect(html.match(/<svg/g)?.length).toBeGreaterThanOrEqual(3);
    expect(html).toMatch(/>558<\/span><span[^>]*>Client Schools<\/span><span[^>]*>80% of total<\/span>/);
    expect(html).not.toContain('context-metrics');
  });

  it('links a figure that opens a page, and keeps a note for a screen reader', () => {
    const html = renderToStaticMarkup(<FeedStrip strip={strip} resolve={(href) => href} />);
    expect(html).toMatch(/<a class="[^"]*" data-figure="" role="listitem" href="\/schools\?school_type=client">/);
    expect(html).toMatch(/data-kpi-note[^>]*>Past their date, not completed</);
  });

  it('is drawn the same way outside the page feed', () => {
    expect(renderToStaticMarkup(<KpiStrip strip={strip} />)).toBe(renderToStaticMarkup(<FeedStrip strip={strip} resolve={(href) => href} />));
  });
});
