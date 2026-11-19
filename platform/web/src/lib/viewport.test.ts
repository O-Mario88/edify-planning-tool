/**
 * Which reading a request gets: the phone's (the native app's design) or the
 * desktop's (the existing web's). The screen's own width, which the browser
 * keeps in a cookie, wins; before the first measure the device's hints guess.
 */
import { describe, expect, it } from 'vitest';

import { viewFrom } from './viewport';

const IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148';
const ANDROID = 'Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 Chrome/131.0 Mobile Safari/537.36';
const MAC = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 15_1) AppleWebKit/605.1.15 Version/18.1 Safari/605.1.15';

describe('the reading a request gets', () => {
  it('follows the measured screen first', () => {
    expect(viewFrom({ cookie: 'phone', mobileHint: '?0', userAgent: MAC })).toBe('phone');
    expect(viewFrom({ cookie: 'desktop', mobileHint: '?1', userAgent: IPHONE })).toBe('desktop');
  });

  it('guesses from the device before the screen is measured', () => {
    expect(viewFrom({ cookie: undefined, mobileHint: '?1', userAgent: MAC })).toBe('phone');
    expect(viewFrom({ cookie: undefined, mobileHint: null, userAgent: IPHONE })).toBe('phone');
    expect(viewFrom({ cookie: undefined, mobileHint: null, userAgent: ANDROID })).toBe('phone');
    expect(viewFrom({ cookie: undefined, mobileHint: null, userAgent: MAC })).toBe('desktop');
    expect(viewFrom({ cookie: undefined, mobileHint: null, userAgent: null })).toBe('desktop');
  });

  it('ignores a cookie it did not write', () => {
    expect(viewFrom({ cookie: 'tablet', mobileHint: null, userAgent: IPHONE })).toBe('phone');
    expect(viewFrom({ cookie: '', mobileHint: null, userAgent: MAC })).toBe('desktop');
  });
});
