/**
 * The filter row keeps the existing web's two layouts (micro-ux.js
 * arrangeFilterRows): three or more fields share the row's width and end in
 * the ×; fewer, the school profile's Fiscal year and Period, keep each select
 * as wide as its words, and a page without a Clear has no ×.
 */
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { FilterBar } from './FilterBar';
import type { Filter } from './FilterBar';

const field = (name: string): Filter => ({
  name,
  label: name,
  value: 'a',
  options: [
    { value: 'a', label: 'A' },
    { value: 'b', label: 'B' },
  ],
});

describe('the filter row', () => {
  it('leaves two fields at their own width, with no × where the page has no Clear', () => {
    const html = renderToStaticMarkup(<FilterBar action="/schools/1000" oneRow hidden={{}} filters={[field('fy'), field('period')]} />);
    expect(html).toContain('data-own-width="true"');
    expect(html).toContain('flex flex-wrap');
    expect(html).not.toContain('grid-template-columns');
    expect(html.match(/w-auto max-w-full \[field-sizing:content\] pl-\[10px\] pr-\[30px\]/g)).toHaveLength(2);
    expect(html).not.toContain('Clear Filters');
  });

  it('shares the row among three fields and ends it in the ×', () => {
    const html = renderToStaticMarkup(<FilterBar action="/planning" clearHref="/planning" oneRow hidden={{}} filters={[field('fy'), field('quarter'), field('district')]} />);
    expect(html).not.toContain('data-own-width');
    expect(html).toContain('grid-template-columns:repeat(3, minmax(0, 1fr)) auto');
    expect(html.match(/w-full px-\[22px\]/g)).toHaveLength(3);
    expect(html).toContain('aria-label="Clear Filters"');
  });
});
