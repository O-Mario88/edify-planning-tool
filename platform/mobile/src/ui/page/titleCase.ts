/**
 * A column name in Title Case (owner, 2026-10-08: "Capitalise Case for the
 * column head"), done properly (2026-11-20, the premium pass): CSS
 * `text-transform: capitalize` made "Part Of The Plan" and, in the app,
 * "School Id". Here the small words stay lower case unless they open or
 * close the name, and a word already holding a capital or a digit (ID, FY,
 * SSA, FY2027) is kept as written. Pure, so it is tested apart from the
 * tables; the web has the same rule (platform/web/src/lib/titleCase.ts).
 */

/** Words a title keeps in lower case between its first and last word. */
const SMALL_WORDS = new Set([
  'a', 'an', 'and', 'as', 'at', 'but', 'by', 'for', 'from', 'in', 'into', 'nor', 'of', 'on', 'or', 'per', 'the', 'to', 'vs', 'via', 'with',
]);

/** A capital after a word's first letter: an initialism or a code (ID, FY). */
const INNER_CAPITAL = /[A-Z]/;

function word(w: string, isEdge: boolean): string {
  if (w === '' || INNER_CAPITAL.test(w.slice(1)) || /\d/.test(w)) return w;
  const lower = w.toLowerCase();
  if (!isEdge && SMALL_WORDS.has(lower)) return lower;
  return w.charAt(0).toUpperCase() + w.slice(1);
}

export function titleCase(label: string): string {
  const words = label.split(' ');
  const last = words.length - 1;
  return words.map((w, i) => word(w, i === 0 || i === last)).join(' ');
}
