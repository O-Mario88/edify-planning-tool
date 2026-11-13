/**
 * A strip's cells carry the existing strip's parts (label, figure, the line
 * under it) under the class names globals.css lays out by width, so eight
 * tiles share a desktop row and only nine or more swipe.
 */
import { create } from '@bufbuild/protobuf';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { PageStripSchema } from '@/gen/edify/screens/v1/page_pb';

import { KpiStrip } from '../blocks/KpiStrip';
import { FeedStrip } from './FeedStrip';

const strip = create(PageStripSchema, {
  title: 'Figures',
  metrics: [
    { label: 'School Leaders Trained', value: '2', helper: '2 in school' },
    { label: 'Enrolment', value: '105', note: 'Learners enrolled this year' },
  ],
});

describe('a strip', () => {
  it('lays its cells out as the existing strip, label, figure and the line under it in order', () => {
    const html = renderToStaticMarkup(<FeedStrip strip={strip} resolve={(href) => href} />);
    expect(html).toContain('<dl class="edify-strip">');
    expect(html).toMatch(/edify-strip__label[^>]*>School Leaders Trained<\/dt><dd class="edify-strip__value[^>]*>2<\/dd><dd class="edify-strip__helper[^>]*>2 in school<\/dd>/);
    expect(html).toContain('<dd class="sr-only">Learners enrolled this year</dd>');
  });

  it('is drawn the same way outside the page feed', () => {
    expect(renderToStaticMarkup(<KpiStrip strip={strip} />)).toBe(renderToStaticMarkup(<FeedStrip strip={strip} resolve={(href) => href} />));
  });
});
