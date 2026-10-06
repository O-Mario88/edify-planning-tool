const { chromium } = require('@playwright/test');
const B = 'http://127.0.0.1:8376';
(async () => { const browser = await chromium.launch(); const context = await browser.newContext({ viewport: { width: 1440, height: 900 } }); const page = await context.newPage();
  await page.goto(B + '/login'); await page.fill('input[name=email]', 'cceo2@edify.org'); await page.fill('input[name=password]', 'edify'); await Promise.all([page.waitForNavigation(), page.press('input[name=password]', 'Enter')]);
  console.log('sw registrations:', await page.evaluate(async () => (navigator.serviceWorker ? (await navigator.serviceWorker.getRegistrations()).length : 'n/a')), 'controller:', await page.evaluate(() => !!(navigator.serviceWorker && navigator.serviceWorker.controller)));
  await page.route((u) => u.origin === B && !u.pathname.startsWith('/static/'), async (route) => { const t = route.request().resourceType(); console.log('route', t, route.request().url().slice(0, 80)); if (t !== 'document') return route.continue(); const response = await route.fetch(); const body = await response.text(); console.log(' body', body.length, /<link rel="expect"/.test(body), (body.match(/<script\b[^>]*\bdefer\b[^>]*>/g) || []).length); await route.fulfill({ response, body: body.replace(/<link rel="expect"[^>]*>/, '') }); });
  await page.goto(B + '/planning', { waitUntil: 'load' });
  console.log('expect links in page:', await page.evaluate(() => document.querySelectorAll('link[rel=expect]').length), 'controller:', await page.evaluate(() => !!(navigator.serviceWorker && navigator.serviceWorker.controller)));
  await browser.close(); })().catch((e) => { console.error(e); process.exit(1); });
