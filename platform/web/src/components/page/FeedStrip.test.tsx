/**
 * A strip's figures are drawn as the existing web's context-metrics row
 * (templates/components/context_metrics.html): each fact its label, figure
 * and the line under it, linked where it opens a page, its note kept for a
 * screen reader.
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
  it('draws one context-metrics row of facts: label, figure, the line under it', () => {
    const html = renderToStaticMarkup(<FeedStrip strip={strip} resolve={(href) => href} />);
    expect(html).toContain('class="context-metrics"');
    expect(html).toContain('data-kpi-count="3"');
    expect(html.match(/class="context-metrics__fact"/g)).toHaveLength(3);
    expect(html).toMatch(/context-metrics__label[^>]*>Client Schools<\/span><strong class="context-metrics__value"[^>]*>558<\/strong><span class="context-metrics__helper"[^>]*>80% of total<\/span>/);
  });

  it('links a figure that opens a page, and keeps a note for a screen reader', () => {
    const html = renderToStaticMarkup(<FeedStrip strip={strip} resolve={(href) => href} />);
    expect(html).toContain('<a class="context-metrics__link" href="/schools?school_type=client">');
    expect(html).toMatch(/data-kpi-note[^>]*>Past their date, not completed</);
  });

  it('is drawn the same way outside the page feed', () => {
    expect(renderToStaticMarkup(<KpiStrip strip={strip} />)).toBe(renderToStaticMarkup(<FeedStrip strip={strip} resolve={(href) => href} />));
  });
});
