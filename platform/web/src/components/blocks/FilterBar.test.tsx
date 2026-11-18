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
  it('leaves two fields unarranged, with no × where the page has no Clear', () => {
    const html = renderToStaticMarkup(<FilterBar action="/schools/1000" oneRow hidden={{}} filters={[field('fy'), field('period')]} />);
    expect(html).toContain('class="edify-filter-bar flex flex-wrap items-end gap-2.5 "');
    expect(html).not.toContain('data-edify-filter-row');
    expect(html.match(/class="platform-filter-compact flex flex-col edify-filter-field "/g)).toHaveLength(2);
    expect(html).not.toContain('data-edify-filter-clear');
  });

  it('arranges three fields as the existing filter row and ends it in the ×', () => {
    const html = renderToStaticMarkup(<FilterBar action="/planning" clearHref="/planning" oneRow hidden={{}} filters={[field('fy'), field('quarter'), field('district')]} />);
    expect(html).toContain('edify-filter-row" data-edify-filter-row=""');
    expect(html).toContain('--edify-filter-cols:3');
    expect(html.match(/edify-filter-field edify-filter-row__field/g)).toHaveLength(3);
    expect(html).toContain('<span class="edify-filter-label">fy</span>');
    expect(html).toContain('data-edify-filter-clear="" aria-label="Clear filters"');
  });
});
