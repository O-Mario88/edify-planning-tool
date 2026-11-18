/**
 * A page asked for under each of its spellings in turn.
 *
 * The existing application's pages are written "/x/" and a browser that asks
 * for "/x" is moved there (Django's APPEND_SLASH), but the gateway reads a
 * path as given: "/planning-monitor" is not a page there, "/planning-monitor/"
 * is. The sidebar writes some pages without their slash, so one spelling the
 * gateway does not know must not end the reader's request: the next spelling
 * is asked. A spelling the gateway has not moved yet means the page exists
 * and is the reader's, so it outweighs a spelling that is no page at all
 * ("/settings" is a page, "/settings/" is not): the page is not found only
 * when every spelling is refused.
 */

export type SpellingAnswer<T> = { kind: 'page'; page: T } | { kind: 'notFound' } | { kind: 'unavailable' };

export async function firstAnswer<T>(
  spellings: readonly string[],
  ask: (path: string) => Promise<SpellingAnswer<T>>,
): Promise<SpellingAnswer<T>> {
  let notMoved = spellings.length === 0;
  for (const path of spellings) {
    const answer = await ask(path);
    if (answer.kind === 'page') return answer;
    if (answer.kind === 'unavailable') notMoved = true;
  }
  return notMoved ? { kind: 'unavailable' } : { kind: 'notFound' };
}
