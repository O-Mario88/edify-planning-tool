import { describe, expect, it } from 'vitest';

// @ts-expect-error -- a plain ES module script without type declarations.
import { extractTokens, staleFiles } from './sync-tokens.mjs';

describe('the design tokens', () => {
  it('are the existing web’s, unchanged (run npm run tokens when this fails)', () => {
    expect(staleFiles()).toEqual([]);
  });

  it('keep only the custom properties of the light and dark themes', () => {
    const css = ':root { --a: 1; color: red; }\n:root.light { --b: 2 }\n:root.theme-blue { --c: 3 }\n.x { --d: 4 }\n@media (min-width: 1px) { :root { --e: 5 } }';
    const out: string = extractTokens(css);
    expect(out).toContain('--a: 1');
    expect(out).toContain('--b: 2');
    expect(out).toContain('--e: 5');
    expect(out).not.toMatch(/color: red|--c|--d/);
  });
});
