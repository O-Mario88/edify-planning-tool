/*
 * The desktop's one visual system, as a budget that only goes down (doc 184,
 * design pass 2026-11-20). The existing web's stylesheets (static/css, shared
 * with the Django pages until they retire) carry forced overrides
 * (`!important`) and hard-coded colours where the design tokens belong. They
 * are retired page by page with parity checks, not rewritten at once; this
 * fails the build when either count grows, and says so when a change lowers
 * one, so the baseline below is lowered with it.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

const LEGACY = join(__dirname, '..', '..', '..', 'static', 'css');

/** Measured 2026-11-21 (doc 184 §3), after the page sheets' colours became
 *  their equal tokens. Lower these as the counts fall; never raise them. */
const BASELINE = { important: 4002, hexColours: 711 };

/** Compiled bundles (Tailwind's, npm run build:css): their colours are the
 *  framework's palette, not hand-written debt. */
const COMPILED = new Set(['main.css', 'tokens.css']);

/** A token's own definition ("--edify-x: #fff;") is the system, not debt. */
const DEFINITION = /^\s*--[\w-]+\s*:/;

function cssFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === 'build' ? [] : cssFiles(path);
    return name.endsWith('.css') && !name.endsWith('.min.css') && !COMPILED.has(name) ? [path] : [];
  });
}

function measure(): { important: number; hexColours: number } {
  let important = 0;
  let hexColours = 0;
  for (const file of cssFiles(LEGACY)) {
    const css = readFileSync(file, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
    important += css.split('!important').length - 1;
    for (const declaration of css.split(';')) {
      if (DEFINITION.test(declaration.split('{').at(-1) ?? '')) continue;
      hexColours += (declaration.match(/#[0-9a-fA-F]{3,8}\b/g) ?? []).length;
    }
  }
  return { important, hexColours };
}

describe('the legacy stylesheets’ budget', () => {
  const now = measure();

  it('never gains a forced override', () => {
    expect(now.important).toBeLessThanOrEqual(BASELINE.important);
  });

  it('never gains a hard-coded colour', () => {
    expect(now.hexColours).toBeLessThanOrEqual(BASELINE.hexColours);
  });

  it('says when the baseline can come down', () => {
    if (now.important < BASELINE.important || now.hexColours < BASELINE.hexColours) {
      console.info(`css budget: now ${now.important} !important and ${now.hexColours} colours; lower BASELINE to match.`);
    }
    expect(now.important + now.hexColours).toBeGreaterThan(0);
  });
});
