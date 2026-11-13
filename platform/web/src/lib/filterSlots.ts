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
