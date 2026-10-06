// The rule that cuts a pinned name to the identity measure used to ask its
// question of the cell (`:first-child:not(:has(> box)) > name`). A browser
// answers that for every first child on the page, and then restyles what is
// inside each of them whenever anything is added beneath it (audit,
// 2026-10-05: one element appended to a table cell restyled 1,801 of a
// dashboard's 3,464 elements). For a day the rule asked the name instead
// (`name:not(:has(~ box))`); it now reads the answer from the cell, where
// micro-ux.js keeps it as `data-edify-box-cell` (e2e/maintained-facts.spec.js
// holds that attribute to `tr > :first-child:has(> box)`). Either may change
// how the rule is found and nothing else: this holds the stylesheet's
// selector to the one it first replaced — the same elements, at the same
// weight — over every arrangement of a row's first two cells.
const fs = require('node:fs');
const path = require('node:path');
const { test, expect } = require('@playwright/test');

test.use({ video: 'off', trace: 'off' });

const BOX = ':is(input[type="checkbox"], input[type="radio"], .edify-table-choice)';
const REGION = '.edify-table-scroll-region:is([data-scroll-state="start"], [data-scroll-state="middle"], [data-scroll-state="end"])';
// As it stood until 2026-10-05.
const ORIGINAL = `${REGION} > table > tbody > tr > :is(:first-child:not(:has(> ${BOX})), :first-child:has(> ${BOX}) + *) > :first-child:not(input, button, .edify-table-choice)`;

// The fact the rule reads, written from the selector it stands for.
const MARK = (box) => {
  for (const cell of document.querySelectorAll('table > :is(thead, tbody, tfoot) > tr > *')) cell.toggleAttribute('data-edify-box-cell', cell.matches(`:first-child:has(> ${box})`));
};

function shippedSelector() {
  const css = fs.readFileSync(path.join(__dirname, '..', 'static', 'css', 'components', 'responsive-system.css'), 'utf8');
  // The rule under the comment that explains it (other rules cut names too).
  const from = css.indexOf('The name is the first child of the pinned cell');
  expect(from, 'the pinned-name rule is still in responsive-system.css').toBeGreaterThan(-1);
  const rule = css.slice(from).match(/\*\/\s*([^{}]+)\{[^{}]*max-inline-size: var\(--edify-table-identity-measure\) !important;/);
  expect(rule, 'the rule follows its comment').not.toBeNull();
  return rule[1].replace(/\s+/g, ' ').trim();
}

const CHILDREN = [
  '<input type="checkbox">',
  '<input type="radio">',
  '<input type="text">',
  '<button type="button">b</button>',
  '<span class="edify-table-choice">c</span>',
  '<span>s</span>',
  '<a href="#">a</a>',
  '<label><input type="checkbox"></label>',
];

// Every sequence of up to `length` children.
function sequences(length) {
  let all = [[]];
  let last = [[]];
  for (let n = 0; n < length; n += 1) {
    last = last.flatMap((sequence) => CHILDREN.map((child) => sequence.concat(child)));
    all = all.concat(last);
  }
  return all;
}

function fixture() {
  const rows = [];
  // The first cell decides: every arrangement of up to three children.
  for (const first of sequences(3)) rows.push(`<tr><td>${first.join('')}</td><td><span>name</span></td><td><span>x</span></td></tr>`);
  // The second cell is the identity when the first holds a box.
  for (const lead of ['', CHILDREN[0], CHILDREN[5] + CHILDREN[1], CHILDREN[4], CHILDREN[7], CHILDREN[2]]) {
    for (const second of sequences(2)) rows.push(`<tr><td>${lead}</td><td>${second.join('')}</td><td><span>x</span></td></tr>`);
  }
  // A header cell first, a row of one cell, an empty row.
  rows.push('<tr><th><span>name</span></th><td><span>x</span></td></tr>');
  rows.push('<tr><td><span>only</span></td></tr>', '<tr></tr>');
  const body = rows.join('');
  const table = (attrs, sections) => `<div class="edify-table-scroll-region" ${attrs}><table>${sections}</table></div>`;
  return [
    table('data-scroll-state="start"', `<thead><tr><th><span>head</span></th><th><span>head</span></th></tr></thead><tbody>${body}</tbody><tfoot><tr><td><span>foot</span></td></tr></tfoot>`),
    table('data-scroll-state="middle"', `<tbody>${body}</tbody>`),
    table('data-scroll-state="end"', `<tbody><tr><td><span>name</span><table><tbody><tr><td><span>nested</span></td></tr></tbody></table></td></tr></tbody>`),
    // No scroll state, another state, and a table that is not the region's child.
    table('', `<tbody>${body}</tbody>`),
    table('data-scroll-state="none"', `<tbody><tr><td><span>name</span></td></tr></tbody>`),
    `<div class="edify-table-scroll-region" data-scroll-state="start"><div><table><tbody><tr><td><span>name</span></td></tr></tbody></table></div></div>`,
  ].join('');
}

test('the pinned-name rule matches exactly what the selector it replaced matched', async ({ page }) => {
  const shipped = shippedSelector();
  expect(shipped, 'the rule no longer asks with :has()').not.toContain(':has(');
  await page.setContent(`<!doctype html><html><body>${fixture()}</body></html>`);
  await page.evaluate(MARK, BOX);
  const result = await page.evaluate(([original, current]) => {
    const all = Array.from(document.body.querySelectorAll('*'));
    const indexes = (selector) => Array.from(document.querySelectorAll(selector)).map((el) => all.indexOf(el));
    return { all: all.length, original: indexes(original), current: indexes(current) };
  }, [ORIGINAL, shipped]);
  expect(result.current).toEqual(result.original);
  // The fixture exercises both answers.
  expect(result.original.length).toBeGreaterThan(400);
  expect(result.original.length).toBeLessThan(result.all / 4);
});

test('the pinned-name rule weighs what the selector it replaced weighed', async ({ page }) => {
  const shipped = shippedSelector();
  // One row for each way the rule is reached: by the name in the first cell,
  // and by the name beside a box.
  await page.setContent(`<!doctype html><html><head><style id="s"></style></head><body>
    <div class="edify-table-scroll-region" data-scroll-state="start"><table><tbody>
      <tr><td><span data-p>name</span></td><td><span data-p>other</span></td></tr>
      <tr><td><input type="checkbox"></td><td><span data-p>name</span></td></tr>
    </tbody></table></div></body></html>`);
  await page.evaluate(MARK, BOX);
  const colours = (css) => page.evaluate((text) => {
    document.getElementById('s').textContent = text;
    return Array.from(document.querySelectorAll('[data-p]')).map((el) => getComputedStyle(el).color);
  }, css);
  const attrs = (n) => '[data-p]'.repeat(n);
  // Either side of six classes and four types, the weight of both selectors.
  const rivals = [
    `html body table tbody ${attrs(6)}`,
    `body table tbody ${attrs(6)}`,
    `html body table tbody tr ${attrs(6)}`,
    `html body table tbody ${attrs(5)}`,
    `html body table tbody ${attrs(7)}`,
    `table ${attrs(6)}`,
  ];
  let ruleWon = 0;
  let rivalWon = 0;
  for (const rival of rivals) {
    for (const rivalFirst of [true, false]) {
      const sheet = (selector) => {
        const rule = `${selector}{color:rgb(200, 0, 0)}`;
        const other = `${rival}{color:rgb(0, 0, 200)}`;
        return rivalFirst ? `${other}\n${rule}` : `${rule}\n${other}`;
      };
      const was = await colours(sheet(ORIGINAL));
      expect(await colours(sheet(shipped)), `against ${rival} ${rivalFirst ? 'before' : 'after'} it`).toEqual(was);
      // The two names the rule reaches; the middle element it never does.
      expect(was[1]).toBe('rgb(0, 0, 200)');
      if (was[0] === 'rgb(200, 0, 0)' && was[2] === 'rgb(200, 0, 0)') ruleWon += 1;
      if (was[0] === 'rgb(0, 0, 200)' && was[2] === 'rgb(0, 0, 200)') rivalWon += 1;
    }
  }
  // The rivals do straddle the weight: the rule wins some and loses some.
  expect(ruleWon).toBeGreaterThan(0);
  expect(rivalWon).toBeGreaterThan(0);
  expect(ruleWon + rivalWon).toBe(rivals.length * 2);
});
