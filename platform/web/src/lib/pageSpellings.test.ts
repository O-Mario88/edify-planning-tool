import { describe, expect, it } from 'vitest';

import { firstAnswer, type SpellingAnswer } from './pageSpellings';

function asker(answers: Record<string, SpellingAnswer<string>>) {
  const asked: string[] = [];
  const ask = async (path: string) => {
    asked.push(path);
    return answers[path] ?? { kind: 'unavailable' as const };
  };
  return { ask, asked };
}

describe('firstAnswer', () => {
  it('takes the page from the spelling after one the gateway does not know', async () => {
    // The sidebar writes "/planning-monitor"; the page is "/planning-monitor/".
    const { ask, asked } = asker({
      '/planning-monitor': { kind: 'notFound' },
      '/planning-monitor/': { kind: 'page', page: 'monitor' },
    });
    expect(await firstAnswer(['/planning-monitor', '/planning-monitor/'], ask)).toEqual({ kind: 'page', page: 'monitor' });
    expect(asked).toEqual(['/planning-monitor', '/planning-monitor/']);
  });

  it('stops at the first spelling that answers', async () => {
    const { ask, asked } = asker({ '/planning': { kind: 'page', page: 'planning' } });
    expect(await firstAnswer(['/planning', '/planning/'], ask)).toEqual({ kind: 'page', page: 'planning' });
    expect(asked).toEqual(['/planning']);
  });

  it('is not found only when every spelling is refused', async () => {
    const { ask } = asker({ '/x': { kind: 'notFound' }, '/x/': { kind: 'notFound' } });
    expect(await firstAnswer(['/x', '/x/'], ask)).toEqual({ kind: 'notFound' });
  });

  it('is not moved yet when one spelling is a page the gateway has not drawn and the other is no page', async () => {
    // "/settings" is the reader's page, not drawn here yet; "/settings/" is
    // not a page at all. The reader is sent to the existing web, not told
    // the page does not exist.
    const { ask } = asker({ '/settings': { kind: 'unavailable' }, '/settings/': { kind: 'notFound' } });
    expect(await firstAnswer(['/settings', '/settings/'], ask)).toEqual({ kind: 'unavailable' });
  });

  it('is unavailable when every spelling is one the gateway has not moved yet', async () => {
    const { ask } = asker({});
    expect(await firstAnswer(['/z', '/z/'], ask)).toEqual({ kind: 'unavailable' });
  });
});
