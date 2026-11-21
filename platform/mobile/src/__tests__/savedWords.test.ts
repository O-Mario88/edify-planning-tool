import { savedWords } from '../ui/page/savedWords';

describe('what the app says when a save lands', () => {
  test('is "Saved." where the existing web asks for Refresh, as the app redraws the page itself (owner, 2026-11-21)', () => {
    expect(savedWords('Saved. Press Refresh to see it on the page. ×')).toBe('Saved.');
    expect(savedWords('Saved. Press Refresh to see it on the page.')).toBe('Saved.');
  });

  test('keeps any other sentence the save gave', () => {
    expect(savedWords('Saved. Press Refresh to see it on the page. Two schools were already in the cluster. ×')).toBe(
      'Saved. Two schools were already in the cluster.',
    );
    expect(savedWords('Follow-up saved.')).toBe('Follow-up saved.');
  });

  test('says "Saved." when the save gave no words', () => {
    expect(savedWords('')).toBe('Saved.');
    expect(savedWords(' × ')).toBe('Saved.');
  });
});
