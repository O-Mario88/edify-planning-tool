import { expect, it } from 'vitest';
import { selectionHref } from './selectionHref';

it.each([
  ['/activity-selection/cancel', 'ids', true, ['first,second']],
  ['/planning/bulk-schedule-drawer', 'school_ids', false, ['first', 'second']],
] as const)('passes the selected rows to %s', (href, param, joined, expected) => {
  const page = new URL(selectionHref('https://legacy.example/planning?fy=2026', { href, param, joined }, ['first', 'second']));
  expect(page.search).toBe('?fy=2026');
  const preview = new URL(new URLSearchParams(page.hash.slice(1)).get('selection')!, page.origin);
  expect(preview.pathname).toBe(href);
  expect(preview.searchParams.getAll(param)).toEqual(expected);
});
