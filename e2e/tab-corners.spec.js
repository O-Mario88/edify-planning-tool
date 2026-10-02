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

/* Owner, 2026-10-02: "fix the tab design. some of them are not properly placed
 * on the pill and pushed the labels up not center". The light rail has no
 * border and its segments were sized for one: 30px in a 32px track, top
 * aligned, so the selected fill stopped 2px above the rail's foot. A rail
 * written with a wrapping utility broke into two rows on a phone. And the
 * last tab left in a rail that had folded into "More" curved toward More. */
const railPage = (body) => `<html class="theme-light"><head><meta name="viewport" content="width=device-width, initial-scale=1">${sheets.map(s=>`<link rel="stylesheet" href="/static/css/${s}">`).join('')}</head><body><main style="padding:16px">${body}</main></body></html>`;
async function serve(page, body) {
  await page.route('http://tabs.test/**', route => {
    const file = path.join(root,new URL(route.request().url()).pathname);
    if(fs.existsSync(file)&&fs.statSync(file).isFile()) return route.fulfill({path:file});
    return route.fulfill({contentType:'text/html',body:railPage(body)});
  });
  await page.goto('http://tabs.test/');
  await page.evaluate(() => document.fonts.ready);
}

test('a segment is as tall as its rail and its label sits in the middle, in every theme', async ({page}) => {
  await page.setViewportSize({width:1280,height:800});
  const rails = families.map(([rail,control,tag])=>`<nav class="${rail}" data-test-rail>${['First','Middle','Last'].map((label,i)=>`<${tag} class="${control} ${i===0?'is-active active':''}"${i===0?' aria-pressed="true" aria-selected="true"':''} href="#" data-test-tab>${label}</${tag}>`).join('')}</nav>`).join('');
  await serve(page, rails);
  for (const theme of ['theme-light','theme-dark','theme-blue']) {
    await page.evaluate(theme=>document.documentElement.className=theme+(theme==='theme-light'?'':' dark'),theme);
    const measured = await page.locator('[data-test-rail]').evaluateAll(rails=>rails.map(rail=>{
      const box = rail.getBoundingClientRect(); const style = getComputedStyle(rail);
      const top = box.top + parseFloat(style.borderTopWidth); const bottom = box.bottom - parseFloat(style.borderBottomWidth);
      return [...rail.querySelectorAll('[data-test-tab]')].map(tab=>{
        const b = tab.getBoundingClientRect();
        const range = document.createRange(); range.selectNodeContents(tab.firstChild);
        const text = range.getBoundingClientRect();
        return { rail: rail.className, above: Math.round((b.top-top)*10)/10, below: Math.round((bottom-b.bottom)*10)/10, label: Math.round(((text.top+text.height/2)-(top+bottom)/2)*10)/10 };
      });
    }).flat());
    expect(measured).toHaveLength(families.length*3);
    for (const tab of measured) {
      expect(Math.abs(tab.above), `${theme} ${JSON.stringify(tab)}`).toBeLessThanOrEqual(0.5);
      expect(Math.abs(tab.below), `${theme} ${JSON.stringify(tab)}`).toBeLessThanOrEqual(0.5);
      expect(Math.abs(tab.label), `${theme} ${JSON.stringify(tab)}`).toBeLessThanOrEqual(1);
    }
  }
});

test('a rail written to wrap stays on one row on a phone', async ({page}) => {
  await page.setViewportSize({width:390,height:800});
  await serve(page, `<nav data-edify-tablist class="flex flex-wrap" data-test-rail>${['Distributed Priorities','Core Values','Spiritual Formation','Professional Development'].map((label,i)=>`<a data-edify-tab href="#"${i===0?' aria-current="page"':''}>${label}</a>`).join('')}</nav>`);
  const rows = await page.locator('[data-test-rail] > a').evaluateAll(tabs=>new Set(tabs.map(tab=>Math.round(tab.getBoundingClientRect().top))).size);
  expect(rows).toBe(1);
  expect(await page.locator('[data-test-rail]').evaluate(rail=>Math.round(rail.getBoundingClientRect().height))).toBe(32);
});

test('the last tab left beside More is square on that side', async ({page}) => {
  await page.setViewportSize({width:390,height:800});
  const more = (hidden) => `<details class="edify-rail-more"${hidden?' hidden':''}><summary class="edify-rail-more__toggle">More</summary><div class="edify-rail-more__menu"></div></details>`;
  await serve(page, [false,true].map(hidden=>`<nav class="edify-tab-container" data-test-rail="${hidden?'whole':'folded'}"><button class="edify-tab-btn active" aria-selected="true">Core Service Package Matrix</button>${more(hidden)}</nav>`).join(''));
  const corners = (name) => page.locator(`[data-test-rail="${name}"] > button`).evaluate(el=>{ const s=getComputedStyle(el); return [s.borderTopRightRadius,s.borderBottomRightRadius]; });
  expect(await corners('folded')).toEqual(['0px','0px']);
  const radius = await page.locator('main').evaluate(el => `${parseFloat(getComputedStyle(el).getPropertyValue('--edify-radius-sm')) - 2}px`);
  expect(await corners('whole')).toEqual([radius,radius]);
});

test('More is as tall as the tabs on a tablet, so the tabs still fill the rail', async ({page}) => {
  // Between 48rem and 64rem a summary's touch floor is 36px; it made More,
  // and with it the rail, 4px taller than the 32px tabs.
  await page.setViewportSize({width:820,height:900});
  await serve(page, `<div class="edify-shell edify-workspace" style="display:block;height:auto;min-height:0"><div><nav class="edify-tab-container" data-test-rail><button class="edify-tab-btn active" aria-selected="true">All Categories</button><button class="edify-tab-btn">Partners</button><details class="edify-rail-more"><summary class="edify-rail-more__toggle">More</summary><div class="edify-rail-more__menu"></div></details></nav></div></div>`);
  const heights = await page.locator('[data-test-rail]').evaluate(rail=>[rail, rail.querySelector('button'), rail.querySelector('summary')].map(el=>Math.round(el.getBoundingClientRect().height)));
  expect(heights).toEqual([32,32,32]);
});
