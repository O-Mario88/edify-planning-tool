/**
 * A page asked for under each of its spellings in turn.
 *
 * The existing application's pages are written "/x/" and a browser that asks
 * for "/x" is moved there (Django's APPEND_SLASH), but the gateway reads a
 * path as given: "/planning-monitor" is not a page there, "/planning-monitor/"
 * is. The sidebar writes some pages without their slash, so one spelling the
 * gateway does not know must not end the reader's request: the next spelling
 * is asked. Only when no spelling answers and one of them refused the reader
 * is the page not found; when every spelling is one the gateway has not
 * moved yet, the page is not moved yet.
 */

export type SpellingAnswer<T> = { kind: 'page'; page: T } | { kind: 'notFound' } | { kind: 'unavailable' };

export async function firstAnswer<T>(
  spellings: readonly string[],
  ask: (path: string) => Promise<SpellingAnswer<T>>,
): Promise<SpellingAnswer<T>> {
  let refused = false;
  for (const path of spellings) {
    const answer = await ask(path);
    if (answer.kind === 'page') return answer;
    if (answer.kind === 'notFound') refused = true;
  }
  return refused ? { kind: 'notFound' } : { kind: 'unavailable' };
}
