import { figureWashed } from '../theme';

describe('Home figure tiles take their tone’s wash as on the web', () => {
  test('brand, info, caution, alert and good tiles are washed', () => {
    for (const tone of ['brand', 'info', 'caution', 'alert', 'good']) {
      expect(figureWashed(tone)).toBe(true);
    }
  });

  test('a plain tile, or one with no tone, keeps the surface', () => {
    expect(figureWashed('plain')).toBe(false);
    expect(figureWashed('')).toBe(false);
  });
});
