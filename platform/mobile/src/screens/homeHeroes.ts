/**
 * Each role's hero figures on Home, the one or two that decide today's work,
 * drawn large and first (owner, 2026-11-20, doc 181 §6.1: a CCEO's are
 * Overdue and Waiting on you). The web's rule is the same
 * (platform/web/src/lib/homeScreen.ts heroFirst). Pure, so it is tested
 * apart from the screen.
 */

/** The figure keys each role draws as heroes; a role not named has none. */
export const HERO_FIGURES: Readonly<Record<string, readonly string[]>> = {
  CCEO: ['overdue', 'waiting_me'],
};

/** The overview's figures split into the role's heroes (in their order) and the rest. */
export function splitHeroes<T extends { readonly key: string }>(figures: readonly T[], roleTitle: string): { heroes: T[]; rest: T[] } {
  const keys = HERO_FIGURES[roleTitle] ?? [];
  return {
    heroes: keys.flatMap((key) => figures.filter((f) => f.key === key)),
    rest: figures.filter((f) => !keys.includes(f.key)),
  };
}
