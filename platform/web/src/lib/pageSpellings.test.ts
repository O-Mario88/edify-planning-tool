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

  it('is not found only when no spelling answers and one refused', async () => {
    const { ask } = asker({ '/x': { kind: 'notFound' }, '/x/': { kind: 'notFound' } });
    expect(await firstAnswer(['/x', '/x/'], ask)).toEqual({ kind: 'notFound' });
    const { ask: mixed } = asker({ '/y': { kind: 'unavailable' }, '/y/': { kind: 'notFound' } });
    expect(await firstAnswer(['/y', '/y/'], mixed)).toEqual({ kind: 'notFound' });
  });

  it('is unavailable when every spelling is one the gateway has not moved yet', async () => {
    const { ask } = asker({});
    expect(await firstAnswer(['/z', '/z/'], ask)).toEqual({ kind: 'unavailable' });
  });
});
