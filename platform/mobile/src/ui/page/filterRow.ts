/**
 * How many selects a phone's filter row holds (PageFilterBar): three, two
 * on a narrow phone so a value such as "All quarters" is never cut, as the
 * web's phone row does (PhoneFilters.inRowFor). Pure, so it is tested
 * apart from the screen.
 */

/** Selects a phone's filter row holds before the rest go under More. */
export const IN_ROW = 3;
/** On a row narrower than this a third select would cut its value. */
const NARROW_ROW = 480;
/** The page's own side padding, either side of the row (PageScreen). */
export const PAGE_GUTTERS = 32;

/** How many selects a row of this width holds. */
export function inRowFor(rowWidth: number): number {
  return rowWidth > 0 && rowWidth < NARROW_ROW ? IN_ROW - 1 : IN_ROW;
}
