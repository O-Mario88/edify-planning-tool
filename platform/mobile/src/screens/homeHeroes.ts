/**
 * Each role's hero figures on Home, the one or two that decide today's work,
 * drawn large and first (owner, 2026-11-20, doc 181 §6.1: a CCEO's are
 * Overdue and Waiting on you). The web's rule is the same
 * (platform/web/src/lib/homeScreen.ts heroFirst). Pure, so it is tested
 * apart from the screen.
 */

/** The figure keys a role draws as heroes: its own when named; otherwise a
 *  role with its own plan leads with Overdue and To-Do (the partners) and a
 *  desk role with Critical and To-Do (owner, 2026-11-20: every role). */
export const HERO_FIGURES: Readonly<Record<string, readonly string[]>> = {
  CCEO: ['overdue', 'waiting_me'],
};

/** The heroes for a role whose Home shows these figure keys. */
export function heroKeys(keys: readonly string[], roleTitle: string): readonly string[] {
  const named = HERO_FIGURES[roleTitle];
  if (named) return named;
  if (keys.includes('overdue')) return ['overdue', 'waiting_me'];
  if (keys.includes('critical')) return ['critical', 'waiting_me'];
  return [];
}

/** The overview's figures split into the role's heroes (in their order) and the rest. */
export function splitHeroes<T extends { readonly key: string }>(figures: readonly T[], roleTitle: string): { heroes: T[]; rest: T[] } {
  const keys = heroKeys(figures.map((f) => f.key), roleTitle);
  return {
    heroes: keys.flatMap((key) => figures.filter((f) => f.key === key)),
    rest: figures.filter((f) => !keys.includes(f.key)),
  };
}
