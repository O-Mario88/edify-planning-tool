/**
 * How many filters a row shows before the rest fold under "More filters"
 * (static/js/micro-ux.js `filterSlots` and its row rule): a phone keeps three
 * and More; wider, one 144px slot (and a 12px gap) per filter in the row's
 * width, at least three; when the filters do not all fit, the last slot is
 * More's.
 */
const SLOT_PX = 144;
const GAP_PX = 12;
const PHONE_FIELDS = 3;
const MIN_SLOTS = 3;
/** The slots the existing web assumes before it can measure (a wide screen). */
export const UNMEASURED_SLOTS = 6;

export function filterSlots(width: number, phone: boolean): number {
  if (phone) return PHONE_FIELDS + 1;
  if (!width) return UNMEASURED_SLOTS;
  return Math.max(MIN_SLOTS, Math.floor((width + GAP_PX) / (SLOT_PX + GAP_PX)));
}

/** How many of `count` filters stay in the row; the rest go under More. */
export function filterFields(count: number, slots: number, phone: boolean): number {
  const folds = count > (phone ? PHONE_FIELDS : slots);
  return folds ? Math.min(count, slots - 1) : count;
}

/**
 * Which filters stay in the row and which sit under More (micro-ux.js
 * arrangeFilterRows). A filter the page itself authors under its More
 * filters (PageFilter.more: the Clusters page's last three) is always
 * folded; then, where the row folds by width, More takes the last slot and
 * the row's last fields that do not fit move under it, in front of the
 * authored ones. A page that keeps its own grid folds only what it authors.
 */
export function foldFilters<T extends { readonly more?: boolean }>(
  shown: readonly T[],
  slots: number,
  phone: boolean,
  byWidth: boolean,
): { inRow: T[]; folded: T[] } {
  const row = shown.filter((filter) => !filter.more);
  const authored = shown.filter((filter) => filter.more);
  if (!byWidth) return { inRow: row, folded: authored };
  const fields = authored.length ? Math.min(row.length, slots - 1) : filterFields(row.length, slots, phone);
  return { inRow: row.slice(0, fields), folded: [...row.slice(fields), ...authored] };
}

/** The fewest fields micro-ux.js lays out as a shared row: fewer keep their own width. */
const ROW_FIELDS = 3;
const PHONE_ROW_FIELDS = 2;

/**
 * Whether a bar of `count` fields is laid out as the shared filter row
 * (micro-ux.js arrangeFilterRows leaves a bar of fewer than two fields on a
 * phone, three wider, as it is); such a bar, the school profile's Fiscal year
 * and Period, keeps each select as wide as its words.
 */
export function arrangesRow(count: number, phone: boolean): boolean {
  return count >= (phone ? PHONE_ROW_FIELDS : ROW_FIELDS);
}
