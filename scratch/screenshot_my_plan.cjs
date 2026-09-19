const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await context.addCookies([
    { name: 'sessionid', value: 'hx53qqqzv3lo7bkiycag1gh2io8opigr', domain: '127.0.0.1', path: '/' }
  ]);
  const page = await context.newPage();
  await page.goto('http://127.0.0.1:8000/my-plan');
  await page.waitForTimeout(1000);

  // Take screenshot of each card / table
  const cards = await page.$$('.card');
  for (let i = 0; i < cards.length; i++) {
    const card = cards[i];
    const text = await card.evaluate(el => el.querySelector('h2, h3, h4')?.innerText || `card_${i}`);
    const safeName = text.toLowerCase().replace(/[^a-z0-9]/g, '_').slice(0, 30);
    await card.screenshot({ path: `/Users/edwinomario/.gemini/antigravity-ide/brain/31b319f1-788f-4cd6-9a13-ac8270dded8c/card_${i}_${safeName}.png` });
  }

  await browser.close();
})();
