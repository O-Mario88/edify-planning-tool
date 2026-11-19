/**
 * What the redesigned Today shows from Go's Home answer (docs/migration/177
 * stage D), the same choice as the web's (platform/web/src/lib/todayView.ts):
 * the next thing on the plan, the To-Dos that wait on the reader (Home's rows
 * less those that only report "all clear"), and the figures that hold
 * something. Pure, so the choice is tested apart from the screen.
 */
import type { HomePriorityRow, HomeUpcoming } from '../gen/edify/screens/v1/home_pb';

export type Tone = 'neutral' | 'info' | 'success' | 'warning' | 'danger';

/** Home's tone words (brand | info | plain | caution | alert | good), as the web reads them. */
const TONES: Readonly<Record<string, Tone>> = {
  brand: 'info',
  info: 'info',
  caution: 'warning',
  alert: 'danger',
  good: 'success',
};

export function toneOf(word: string): Tone {
  return TONES[word] ?? 'neutral';
}

/** A row that only reports nothing to do ("0 … — All clear"). */
export function allClear(row: HomePriorityRow): boolean {
  return row.count === 0 && toneOf(row.statusTone) === 'success';
}

/** Home's rows that wait on the reader, in Home's order. */
export function waitingRows(rows: readonly HomePriorityRow[]): HomePriorityRow[] {
  return rows.filter((row) => !allClear(row));
}

/** The figures Today shows: whole numbers above nought, in Home's order. */
export function countedFigures<F extends { readonly value: string; readonly loading?: boolean }>(
  cards: readonly F[],
): F[] {
  return cards.filter((f) => !f.loading && /^\d[\d,]*$/.test(f.value) && f.value.replace(/[,0]/g, '') !== '');
}

/** Next up: today's first activity, else the first coming one. */
export function nextUp(upcoming: readonly HomeUpcoming[]): HomeUpcoming | undefined {
  return upcoming.find((u) => u.isToday) ?? upcoming[0];
}

/** "All 9 To-Dos" once the total is known. */
export function todosLinkLabel(total: number | null | undefined): string {
  return total ? `All ${total} To-Dos` : 'All To-Dos';
}

/** The roles whose Home is the redesigned Today, as on the web (app/(app)/home). */
const TODAY_ROLES: ReadonlySet<string> = new Set(['CCEO']);

export function redesignedToday(role: string): boolean {
  return TODAY_ROLES.has(role);
}
