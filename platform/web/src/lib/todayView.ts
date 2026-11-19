/**
 * What the redesigned Today shows from Go's Home answer (docs/migration/177
 * stage D): the next thing on the plan, the To-Dos that wait on the reader
 * (Home's rows less those that only report "all clear"), and the figures
 * that hold something. Pure, so the choice is tested apart from the page.
 */
import type { HomePriorityRow, HomeUpcoming } from '@/gen/edify/screens/v1/home_pb';

export type Tone = 'neutral' | 'info' | 'success' | 'warning' | 'danger';

/** Go's tone words as the design system's. */
export function toneOf(word: string): Tone {
  switch (word) {
    case 'danger':
    case 'critical':
      return 'danger';
    case 'warning':
      return 'warning';
    case 'success':
      return 'success';
    case 'info':
    case 'primary':
      return 'info';
    default:
      return 'neutral';
  }
}

/** A row that only reports nothing to do ("0 … — All clear"). */
export function allClear(row: HomePriorityRow): boolean {
  return row.count === 0 && toneOf(row.statusTone) === 'success';
}

/** Home's rows that wait on the reader, in Home's order. */
export function waitingRows(rows: readonly HomePriorityRow[]): HomePriorityRow[] {
  return rows.filter((row) => !allClear(row));
}

/** The figures Today shows, from Home's merged cards (homeFigures): whole
 *  numbers above nought, in Home's order. */
export function countedFigures<F extends { readonly value: string }>(cards: readonly F[]): F[] {
  return cards.filter((f) => /^\d[\d,]*$/.test(f.value) && f.value.replace(/[,0]/g, '') !== '');
}

/** A figure's value as a number ("1,204" → 1204). */
export function figureNumber(f: { readonly value: string }): number {
  return Number(f.value.replace(/,/g, ''));
}

/** Next up: today's first activity, else the first coming one. */
export function nextUp(upcoming: readonly HomeUpcoming[]): HomeUpcoming | undefined {
  return upcoming.find((u) => u.isToday) ?? upcoming[0];
}
