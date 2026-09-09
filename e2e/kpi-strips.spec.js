const { test, expect } = require('@playwright/test');
test.use({ video: 'off', trace: 'off', serviceWorkers: 'block' });
const { snapshotServer } = require('./helpers/snapshot-server');
const servers = new WeakMap();
test.afterEach(async ({page}) => { await servers.get(page)?.close(); });
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
// Render the real Django component without touching a database or requiring a login.
const markup = execFileSync(path.join(root, '.venv/bin/python'), ['-c', `
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev')
import django
django.setup()
from django.template.loader import render_to_string
labels = ['Schools reached', 'School visits', 'Trainings', 'SSA completed', 'Core schools', 'Completion', 'Budget used', 'Approvals']
values = ['2,048', '384', '48', '156', '120', '94.2%', '68.4%', '07']
helpers = ['↗ 12.8%', '↗ 8.2%', '↗ 6.7%', '↗ 9.4%', '↗ 5.3%', '↗ 3.1%', 'Within plan', 'Review →']
items = [dict(label=l, value=v, helper=h, tone='success' if i < 6 else 'warning' if i == 7 else 'neutral', link='#approvals' if i == 7 else None) for i,(l,v,h) in enumerate(zip(labels,values,helpers))]
print(render_to_string('components/context_metrics.html', dict(title='Performance overview', items=items)))
`], { cwd: root, encoding: 'utf8' });
const sheets = ['fonts.css', 'main.css', 'design-system.css', 'components.css', 'components/sidebar.css', 'components/mobile-shell.css', 'components/mobile-patterns.css', 'pages.css', 'drawers.css', 'app.css', 'platform.css', 'components/platform-status.css', 'components/interactions.css', 'consistency.css', 'components/mobile-micro-ux.css'];
async function render(page, theme, width, html = markup, fullDocument = false) {
  await page.setViewportSize({ width, height: 700 });
  let server = servers.get(page);
  if (!server) { server = await snapshotServer(root); servers.set(page, server); }
  server.setHtml(fullDocument ? html.replace('<html lang=', `<html class="${theme}${theme === 'theme-light' ? '' : ' dark'}" lang=`) : `<html class="${theme}${theme === 'theme-light' ? '' : ' dark'}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">${sheets.map(s => `<link rel="stylesheet" href="/static/css/${s}">`).join('')}</head><body><main style="padding:24px;max-width:none">${html}</main><script src="/static/js/kpi-strips.js"></script></body></html>`);
  await page.goto(server.origin + '/page');
  await expect(page.locator('[data-kpi-ready]')).toHaveCount(1);
  await page.evaluate(() => document.fonts.ready);
}
for (const [theme, color] of [['theme-light', 'rgb(255, 255, 255)'], ['theme-dark', 'rgb(18, 34, 52)'], ['theme-blue', 'rgba(0, 0, 0, 0)']]) {
  for (const [width, visible] of [[390, 2], [768, 4], [1600, 8]]) {
    test(`${theme} at ${width}: layout, navigation, overflow and surface`, async ({ page }, testInfo) => {
      await render(page, theme, width);
      const rail = page.locator('.context-metrics__sentence');
      await expect(rail).toHaveCSS('background-color', color);
      if (theme === 'theme-blue') await expect(rail).toHaveCSS('background-image', 'linear-gradient(110deg, rgb(7, 52, 84), rgb(16, 63, 98))');
      await expect(page.locator('.context-metrics__value').first()).toHaveCSS('font-weight', '700');
      const metrics = await rail.evaluate(el => ({ width: el.clientWidth, cell: el.children[0].getBoundingClientRect().width, height: el.offsetHeight, pageOverflow: document.documentElement.scrollWidth > innerWidth }));
      expect(Math.round(metrics.width / metrics.cell)).toBe(visible);
      expect(metrics.height).toBeLessThanOrEqual(100);
      expect(await page.locator(".context-metrics__value").first().evaluate(el => parseFloat(getComputedStyle(el).fontSize))).toBeLessThanOrEqual(24);
      expect(metrics.pageOverflow).toBe(false);
      await expect(page.locator('.context-metrics__value')).toHaveText(['2,048', '384', '48', '156', '120', '94.2%', '68.4%', '07']);
      if (visible < 8) {
        await expect(page.locator('.context-metrics__range')).toHaveText(`1–${visible} of 8`);
        await page.getByRole('button', { name: 'Show next metrics' }).click();
        await expect(page.locator('.context-metrics__range')).toHaveText(`${visible + 1}–${visible * 2} of 8`);
        await rail.evaluate(el => { el.scrollLeft = el.scrollWidth; });
        await expect(page.getByRole('button', { name: 'Show first metrics' })).toBeVisible();
        await page.getByRole('link', { name: /Approvals/ }).click();
        await expect(page).toHaveURL(/#approvals/);
        await page.getByRole('button', { name: 'Show first metrics' }).click();
        await expect(page.locator('.context-metrics__range')).toHaveText(`1–${visible} of 8`);
        await rail.focus();
        await page.keyboard.press('ArrowRight');
        await expect.poll(() => rail.evaluate(el => el.scrollLeft)).toBeGreaterThan(0);
        await rail.evaluate(el => { el.scrollLeft = 0; });
      } else await expect(page.locator('.context-metrics__navigation')).toBeHidden();
      await page.evaluate(() => document.activeElement?.blur());
      await page.screenshot({ path: testInfo.outputPath(`${theme}-${width}.png`) });
    });
  }
}
test('resize, long values, fewer metrics and HTMX replacement', async ({ page }) => {
  await render(page, 'theme-dark', 390);
  await page.setViewportSize({ width: 1600, height: 700 });
  await expect(page.locator('.context-metrics__navigation')).toBeHidden();
  await page.evaluate(() => {
    const original = document.querySelector('[data-context-metrics]');
    const replacement = original.cloneNode(true);
    document.dispatchEvent(new CustomEvent('htmx:beforeCleanupElement', { detail: { elt: original } }));
    original.replaceWith(replacement);
    [...replacement.querySelectorAll('[role=listitem]')].slice(2).forEach(el => el.remove());
    replacement.querySelector('.context-metrics__value').textContent = 'UGX 1,234,567,890,000';
    document.dispatchEvent(new CustomEvent('htmx:load', { detail: { elt: replacement } }));
  });
  await page.setViewportSize({ width: 320, height: 700 });
  await expect(page.locator('.context-metrics__navigation')).toBeHidden();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(await page.locator('.context-metrics__value').first().evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
});

test('strip has accessible names and sufficient contrast in every theme', async ({ page }) => {
  await render(page, 'theme-light', 390);
  await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
  for (const theme of ['theme-light', 'theme-dark', 'theme-blue']) {
    await page.evaluate(theme => { document.documentElement.className = theme + (theme === 'theme-light' ? '' : ' dark'); }, theme);
    const muted = { 'theme-light': 'rgb(82, 100, 122)', 'theme-dark': 'rgb(184, 204, 225)', 'theme-blue': 'rgb(212, 231, 250)' }[theme];
    await expect(page.locator('.context-metrics__range')).toHaveCSS('color', muted);
    await expect(page.locator('.context-metrics__next')).toHaveCSS('color', muted);
    const violations = await page.evaluate(async () => (await axe.run(document.querySelector('[data-context-metrics]'), { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa'] } })).violations);
    expect(violations.map(v => ({ id: v.id, nodes: v.nodes.map(n => n.failureSummary) }))).toEqual([]);
  }
});

const platformFixtures = JSON.parse(execFileSync(path.join(root, '.venv/bin/python'), [path.join(root, 'scripts/render_kpi_test_fixtures.py')], { cwd: root, env: { ...process.env, PYTHONPATH: root }, encoding: 'utf8' }));
for (const [name, html] of Object.entries(platformFixtures)) {
  test(`platform ${name}: populated data across all themes and sizes`, async ({ page }, testInfo) => {
    for (const theme of ['theme-light', 'theme-dark', 'theme-blue']) {
      for (const width of [390, 768, 1600]) {
        await page.unrouteAll();
        await render(page, theme, width, html);
        const rail = page.locator('.context-metrics__sentence');
        const measurements = await rail.evaluate(el => ({ height: el.offsetHeight, overflow: document.documentElement.scrollWidth > innerWidth, values: [...el.querySelectorAll('.context-metrics__value')].map(v => v.textContent.trim()), labels: [...el.querySelectorAll('.context-metrics__label')].map(v => v.textContent.trim()) }));
        expect(measurements.overflow).toBe(false);
        expect(measurements.height).toBeLessThan(200);
        expect(measurements.values.every(v => v && !v.includes('{{') && !v.includes('}}'))).toBe(true);
        expect(measurements.labels.every(Boolean)).toBe(true);
        if (name === 'finance-sources') {
          expect(measurements.labels).toEqual(['Approved', 'Committed', 'Disbursed', 'Accounted', 'Returned', 'Remaining']);
          await expect(page.locator('.context-metrics__value').first()).toHaveAttribute('title', 'UGX 1,250,000,000');
          await expect(page.locator('.context-metrics__value [aria-hidden="true"]').first()).toHaveText('UGX 1.25B');
        }
        if (name === 'upload-filters') await expect(page.locator('[aria-current="page"]')).toHaveAttribute('href', '?tab=review');
        if (width === 390) await page.screenshot({ path: testInfo.outputPath(`${name}-${theme}.png`) });
      }
    }
  });
}

test('public sign-in retains its live strip on mobile, tablet and desktop', async ({ page }, testInfo) => {
  const document = execFileSync(path.join(root, '.venv/bin/python'), [path.join(root, 'scripts/render_kpi_test_fixtures.py'), '--login-page'], { cwd: root, env: { ...process.env, PYTHONPATH: root }, encoding: 'utf8' });
  for (const width of [390, 768, 1600]) {
    await page.unrouteAll();
    await render(page, 'theme-light', width, document, true);
    await expect(page.locator('.context-metrics__sentence')).toBeVisible();
    const box = await page.locator('.context-metrics__sentence').boundingBox();
    expect(box.x + box.width).toBeLessThanOrEqual(width + 1);
    await expect(page.locator('.context-metrics__value')).toHaveText(['2048', '1536', '1024', '1800']);
    await page.screenshot({ path: testInfo.outputPath(`login-${width}.png`), fullPage: true });
  }
});


test('real HTMX swaps clean up text nodes and remount KPI navigation', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await render(page, 'theme-light', 390);
  await page.route('**/replacement', route => route.fulfill({
    body: '\n' + markup.replace('data-context-metrics', 'data-live-replacement data-context-metrics') + '\n', contentType: 'text/html',
  }));
  await page.evaluate(() => {
    const button = document.createElement('button');
    button.textContent = 'Refresh KPI fixture';
    button.setAttribute('hx-get', '/replacement');
    button.setAttribute('hx-target', 'main');
    document.body.append(button);
  });
  await page.addScriptTag({ path: path.join(root, 'static/js/vendor/htmx-1.9.12.min.js') });
  await page.getByRole('button', { name: 'Refresh KPI fixture' }).click();
  await expect(page.locator('main > [data-live-replacement][data-kpi-ready]')).toHaveCount(1);
  await page.getByRole('button', { name: 'Show next metrics' }).click();
  await expect(page.locator('.context-metrics__range')).toHaveText('3–4 of 8');
  expect(errors).toEqual([]);
});
