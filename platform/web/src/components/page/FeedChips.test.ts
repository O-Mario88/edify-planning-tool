import { describe, expect, it } from 'vitest';

import { rowShows } from './FeedChips';

describe('a chip hides the rows another chip excludes, as the app does', () => {
  it.each([
    [{ cat: 'Finance' }, 'all', true],
    [{ cat: 'Finance' }, 'Finance', true],
    [{ cat: 'Planning' }, 'Finance', false],
    [{}, 'Finance', true],
  ])('a row keyed %j shows under %s: %s', (keys, value, shows) => {
    expect(rowShows(keys, 'cat', value)).toBe(shows);
  });
});
