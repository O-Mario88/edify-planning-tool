const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 }
  });

  // 1. Inspect CCEO My Plan
  await context.addCookies([
    {
      name: 'sessionid',
      value: 'hx53qqqzv3lo7bkiycag1gh2io8opigr',
      domain: '127.0.0.1',
      path: '/'
    }
  ]);

  const page = await context.newPage();
  await page.goto('http://127.0.0.1:8000/my-plan');
  await page.waitForTimeout(1000);
  await page.screenshot({ path: '/Users/edwinomario/.gemini/antigravity-ide/brain/31b319f1-788f-4cd6-9a13-ac8270dded8c/cceo_my_plan_view.png', fullPage: true });

  const cceoTables = await page.evaluate(() => {
    return Array.from(document.querySelectorAll('table')).map(t => {
      const headers = Array.from(t.querySelectorAll('th')).map(th => th.innerText.trim());
      const firstRowCells = Array.from(t.querySelectorAll('tbody tr:first-child td')).map(td => ({
        html: td.innerHTML.trim().slice(0, 150),
        text: td.innerText.trim(),
        scrollWidth: td.scrollWidth,
        clientWidth: td.clientWidth
      }));
      return {
        caption: t.closest('.card') ? (t.closest('.card').querySelector('h2, h3, h4, h5') || {}).innerText : 'table',
        headers,
        firstRowCells
      };
    });
  });
  console.log('=== CCEO My Plan Tables ===');
  console.log(JSON.stringify(cceoTables, null, 2));

  // 2. Inspect PL Team Oversight
  await context.clearCookies();
  await context.addCookies([
    {
      name: 'sessionid',
      value: 'r76l8y4266023i3d12wcqb1uq23a29n7',
      domain: '127.0.0.1',
      path: '/'
    }
  ]);

  const pagePL = await context.newPage();
  await pagePL.goto('http://127.0.0.1:8000/team-planning-oversight/');
  await pagePL.waitForTimeout(1000);
  await pagePL.screenshot({ path: '/Users/edwinomario/.gemini/antigravity-ide/brain/31b319f1-788f-4cd6-9a13-ac8270dded8c/pl_team_oversight_view.png', fullPage: true });

  const plTables = await pagePL.evaluate(() => {
    return Array.from(document.querySelectorAll('table')).map(t => {
      const headers = Array.from(t.querySelectorAll('th')).map(th => th.innerText.trim());
      const firstRowCells = Array.from(t.querySelectorAll('tbody tr:first-child td')).map(td => ({
        html: td.innerHTML.trim().slice(0, 150),
        text: td.innerText.trim(),
        scrollWidth: td.scrollWidth,
        clientWidth: td.clientWidth
      }));
      return {
        caption: t.closest('.card') ? (t.closest('.card').querySelector('h2, h3, h4, h5') || {}).innerText : 'table',
        headers,
        firstRowCells
      };
    });
  });
  console.log('=== PL Team Oversight Tables ===');
  console.log(JSON.stringify(plTables, null, 2));

  // 3. Inspect CD Country Planning Oversight
  await context.clearCookies();
  await context.addCookies([
    {
      name: 'sessionid',
      value: 'ahnmzx96n6w35y82i7i0v5t7wm4j67y1',
      domain: '127.0.0.1',
      path: '/'
    }
  ]);

  const pageCD = await context.newPage();
  await pageCD.goto('http://127.0.0.1:8000/country-planning-oversight/');
  await pageCD.waitForTimeout(1500);
  await pageCD.screenshot({ path: '/Users/edwinomario/.gemini/antigravity-ide/brain/31b319f1-788f-4cd6-9a13-ac8270dded8c/cd_oversight_view.png', fullPage: true });

  const cdTables = await pageCD.evaluate(() => {
    return Array.from(document.querySelectorAll('table')).map(t => {
      const headers = Array.from(t.querySelectorAll('th')).map(th => th.innerText.trim());
      const firstRowCells = Array.from(t.querySelectorAll('tbody tr:first-child td')).map(td => ({
        html: td.innerHTML.trim().slice(0, 150),
        text: td.innerText.trim(),
        scrollWidth: td.scrollWidth,
        clientWidth: td.clientWidth
      }));
      return {
        caption: (t.closest('.card') || t.closest('section') || {}).querySelector('h4, h5') ? (t.closest('.card') || t.closest('section')).querySelector('h4, h5').innerText : 'table',
        headers,
        firstRowCells
      };
    });
  });
  console.log('=== CD Country Oversight Tables ===');
  console.log(JSON.stringify(cdTables, null, 2));

  await browser.close();
})();
