const { test, expect } = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');
test.use({ video: 'off', trace: 'off' });
test.describe.configure({ mode: 'parallel' });
const root = path.resolve(__dirname, '..');
const { execFileSync } = require('node:child_process');
function resolvePython() {
  if (process.env.PYTHON) return process.env.PYTHON;
  const venvPython = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  if (fs.existsSync(venvPython)) return venvPython;
  return 'python';
}
const pythonBin = resolvePython();
const expectedRoles = JSON.parse(execFileSync(pythonBin, ['-c', `import os,json; os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.dev'); import django; django.setup(); from apps.core.rbac import EdifyRole; print(json.dumps(EdifyRole.values()))`], { cwd: root, encoding: 'utf8' })).map(role => role.replace(/[^a-zA-Z0-9_-]/g, '_')).sort();
const directory = path.join(root, 'test-results/kpi-platform-crawl');
// Produced by the signed-in all-role Django crawl against an isolated test DB.
const reports = fs.existsSync(directory) ? fs.readdirSync(directory).filter(f => f.endsWith('.json')) : [];
test('crawl includes every platform role', () => {
  test.skip(!fs.existsSync(directory), 'Run the Django RouteCrawlTest before this browser audit');
  expect(reports.map(file => file.slice(0, -5)).sort(), 'Run the Django RouteCrawlTest before this browser audit').toEqual(expectedRoles);
});
for (const report of reports) {
  const role = report.slice(0, -5);
  test(`authenticated KPI pages: ${role}`, async ({ page }, testInfo) => {
    test.setTimeout(240000);
    const files = fs.existsSync(directory) ? fs.readdirSync(directory).filter(f => f.startsWith(role + '-') && f.endsWith('.html') && fs.readFileSync(path.join(directory, f), 'utf8').includes('data-context-metrics')) : [];
    test.setTimeout(Math.max(240000, files.length * 10000));
    expect(files.length, `No rendered KPI pages for ${role}`).toBeGreaterThan(0);
    const issues = [];
    let html;
    await page.route('**/*', route => {
      const url = new URL(route.request().url());
      if (url.hostname !== 'kpi.test') return route.fulfill({ status: 204 });
      if (url.pathname === '/audit-page') return route.fulfill({ body: html, contentType: 'text/html; charset=utf-8' });
      if (url.pathname.startsWith('/static/')) {
        const file = path.join(root, url.pathname);
        if (fs.existsSync(file) && fs.statSync(file).isFile()) return route.fulfill({ path: file });
      }
      return route.fulfill({ status: 204 });
    });
    for (const file of files) {
      html = fs.readFileSync(path.join(directory, file), 'utf8');
      await page.goto('http://kpi.test/audit-page', { waitUntil: 'domcontentloaded' });
      await page.locator('[data-kpi-ready]').first().waitFor({ state: 'attached' });
      // Freeze transitions while measuring each settled theme state.
      await page.addStyleTag({ content: '*,*::before,*::after { transition:none!important; animation:none!important; }' });
      for (const width of [390, 768, 1600]) {
        await page.setViewportSize({ width, height: 900 });
        for (const theme of ['theme-light', 'theme-dark', 'theme-blue']) {
          await page.evaluate(theme => {
            document.documentElement.classList.remove('theme-light', 'theme-dark', 'theme-blue');
            document.documentElement.classList.add(theme);
          }, theme);
          const failures = await page.locator('[data-context-metrics]').evaluateAll(sections => sections.flatMap(section => {
            const rail = section.querySelector('.context-metrics__sentence');
            const rect = rail.getBoundingClientRect();
            if (!rect.width || !rect.height) return [];
            const errors = [];
            if (rect.right > innerWidth + 2 || rect.left < -2) errors.push('strip exceeds viewport');
            if (![...rail.querySelectorAll('.context-metrics__label')].every(el => el.textContent.trim())) errors.push('missing label');
            if (![...rail.querySelectorAll('.context-metrics__value')].every(el => el.textContent.trim())) errors.push('missing value');
            return errors.map(error => ({ error, label: section.getAttribute('aria-label'), width: rect.width }));
          }));
          if (failures.length) issues.push({ file, width, theme, failures });
        }
      }
      if (file === files[0]) await page.screenshot({ path: testInfo.outputPath(`${role}.png`) });
    }
    expect(issues).toEqual([]);
    await testInfo.attach('coverage', { body: JSON.stringify({ role, pages: files.length, layouts: files.length * 9 }), contentType: 'application/json' });
  });
}
