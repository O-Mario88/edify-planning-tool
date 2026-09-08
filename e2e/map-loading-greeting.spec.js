const {test, expect} = require('@playwright/test');
const {signIn} = require('./helpers/auth');
test.use({video:'off', trace:'off', timezoneId:'Africa/Kampala', reducedMotion:'no-preference'});

test('map renders together and requests detail only on zoom', async ({page}) => {
  await signIn(page, 'cceo@edify.org', 'edify', {acceptRequiredAgreements:false});
  const details = [];
  page.on('request', r => { if(r.url().includes('uganda_subcounty_index.json')) details.push(r.url()); });
  await page.addInitScript(() => {
    let factory;
    Object.defineProperty(window, 'subregionMap', {
      configurable:true,
      get() { return factory; },
      set(value) {
        factory = function () {
          const component = value();
          const draw = component.draw;
          component.draw = function () {
            const start = performance.now();
            const result = draw.call(this);
            window.mapDrawDuration = performance.now() - start;
            return result;
          };
          return component;
        };
      },
    });
  });
  await page.goto('/dashboard?view=map');
  const map = page.locator('.analytics-geo-card');
  const paths = page.locator('.sr-district-layer > path');
  await expect(paths.first()).toBeVisible();
  expect(await paths.count()).toBeGreaterThan(100);
  expect(details).toHaveLength(0);
  const measurements = await map.evaluate(el => ({
    frozen: Object.isFrozen(Alpine.$data(el).geo),
    drawMs: window.mapDrawDuration,
    animations: [...el.querySelectorAll('.sr-district-layer > path, .sr-school-pin')]
      .filter(p => getComputedStyle(p).animationName !== 'none').length,
  }));
  expect(measurements.frozen).toBe(true);
  expect(measurements.animations).toBe(0);
  console.log('Map rendering:', JSON.stringify(measurements));
  await paths.first().focus();
  await paths.first().press('Enter');
  await expect.poll(() => details.length).toBe(1);
  await expect.poll(() => map.evaluate(el => Alpine.$data(el).detailLoading)).toBe(false);
  expect(await map.evaluate(el => Alpine.$data(el).detailFailed)).toBe(false);
  await page.keyboard.press('Escape');
  await expect.poll(() => map.evaluate(el => Alpine.$data(el).focused)).toBe(null);
});

test('greeting uses local time, actual name and refreshes across noon', async ({page}) => {
  await signIn(page, 'cceo@edify.org', 'edify', {acceptRequiredAgreements:false});
  await page.clock.install({time: new Date('2026-09-09T08:59:30Z')});
  await page.goto('/dashboard?view=operations');
  const heading = page.locator('h1').filter({has:page.locator('[x-data="edifyGreeting()"]')});
  await expect(heading).toContainText('Good morning, Paul N');
  await page.clock.fastForward(60000);
  await expect(heading).toContainText('Good afternoon, Paul N');
  await page.clock.setSystemTime(new Date('2026-09-09T15:00:00Z'));
  await page.evaluate(() => window.dispatchEvent(new Event('focus')));
  await expect(heading).toContainText('Good evening, Paul N');
});
