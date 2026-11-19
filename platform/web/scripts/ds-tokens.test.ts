import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

// @ts-expect-error -- a plain ES module script without type declarations.
import { build, contrast, contrastReport, MOBILE_OUT, TOKENS, WEB_OUT } from '../../design/build-tokens.mjs';

describe('the design system tokens', () => {
  it('are the same in the web and native apps as in platform/design/tokens.json (run npm run tokens:ds when this fails)', () => {
    const { css, ts } = build();
    expect(readFileSync(WEB_OUT, 'utf8')).toBe(css);
    expect(readFileSync(MOBILE_OUT, 'utf8')).toBe(ts);
  });

  it('meet WCAG 2.2 AA contrast for every text and status colour on the surfaces it is drawn on', () => {
    const tokens = JSON.parse(readFileSync(TOKENS, 'utf8'));
    const { rows, failures } = contrastReport(tokens);
    expect(failures).toEqual([]);
    expect(rows.length).toBeGreaterThan(60);
  });

  it('measure contrast as WCAG does', () => {
    expect(contrast('#000000', '#ffffff')).toBeCloseTo(21, 5);
    expect(contrast('#ffffff', '#ffffff')).toBeCloseTo(1, 5);
  });
});
