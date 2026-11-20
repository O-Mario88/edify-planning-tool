import { inRowFor } from '../ui/page/filterRow';

describe('the filter row', () => {
  test('holds two selects on a narrow phone, so no value is cut, and three from a 480px row', () => {
    expect(inRowFor(402 - 32)).toBe(2);
    expect(inRowFor(479)).toBe(2);
    expect(inRowFor(480)).toBe(3);
    expect(inRowFor(768 - 32)).toBe(3);
  });

  test('keeps three before the window has a width', () => {
    expect(inRowFor(0)).toBe(3);
  });
});
