const { test, expect } = require('@playwright/test');
test.use({ video: 'off', trace: 'off', serviceWorkers: 'block' });
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const sheets = ['fonts.css','main.css','design-system.css','components.css','components/mobile-patterns.css','pages.css','drawers.css','app.css','platform.css','consistency.css','components/mobile-micro-ux.css','components/interactions.css'];
const families = [
  ['edify-section-nav__inner','edify-section-nav__link','a'],
  ['edify-section-nav__clusters','edify-section-nav__cluster','a'],
  ['edify-tab-container','edify-tab-btn','button'],
  ['messages-inbox-tabs','messages-inbox-tab','button'],
  ['pto-tabs','','button'],['sp-period-tabs','','button'],['spp-tabs','','button'],
  ['tt-segmented','','button'],['oversight-entity-tabs','oversight-entity-tabs__link','a'],
];
for (const width of [390,768,1600]) {
  test(`connected tabs curve only at the outer ends at ${width}`, async ({page}) => {
    await page.setViewportSize({width,height:1000});
    await page.route('http://tabs.test/**', route => {
      const file = path.join(root,new URL(route.request().url()).pathname);
      if(fs.existsSync(file)&&fs.statSync(file).isFile()) return route.fulfill({path:file});
      // Every family twice: once with its first segment selected, once with
      // its middle one.
      const rails = [0,1].map((active)=>families.map(([rail,control,tag])=>`<nav class="${rail}">${['First','Middle','Last'].map((label,i)=>`<${tag} class="${control} ${i===active?'is-active active':''}"${i===active?' aria-pressed="true"':''} href="#" data-test-tab>${label}</${tag}>`).join('')}<span hidden>Updating</span></nav>`).join('')).join('');
      return route.fulfill({contentType:'text/html',body:`<html class="theme-light"><head>${sheets.map(s=>`<link rel="stylesheet" href="/static/css/${s}">`).join('')}</head><body><main>${rails}</main></body></html>`});
    });
    await page.goto('http://tabs.test/');
    for (const theme of ['theme-light','theme-dark','theme-blue']) {
      await page.evaluate(theme=>document.documentElement.className=theme+(theme==='theme-light'?'':' dark'),theme);
      const corners = await page.locator('[data-test-tab]').evaluateAll(els=>els.map(el=>{
        const s=getComputedStyle(el);return [s.borderTopLeftRadius,s.borderTopRightRadius,s.borderBottomRightRadius,s.borderBottomLeftRadius];
      }));
      expect(corners).toHaveLength(families.length*6);
      const radius = await page.locator('main').evaluate(el => `${parseFloat(getComputedStyle(el).getPropertyValue('--edify-radius-sm')) - 2}px`);
      // Selected or not, a segment keeps the rail's shape (owner, 2026-09-26:
      // "the straight line in the middle and curves on the curved edges"):
      // the ends round only outward and the middle is square. The selected
      // segment was a 9999px pill from 2026-09-20 to 2026-09-26.
      for(const [i,radii] of corners.entries()) expect(radii, families[Math.floor(i/3)%families.length][0] + ":" + i).toEqual(i%3===0 ? [radius,"0px","0px",radius] : i%3===2 ? ["0px",radius,radius,"0px"] : ["0px","0px","0px","0px"]);
    }
  });
}
