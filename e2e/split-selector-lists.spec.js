// The CSS build writes long `:is()` lists out as one selector per alternative
// (scripts/split_selector_lists.cjs; audit, 2026-10-05). That may change how a
// browser finds a rule and nothing else. tests/js checks the rewrite's own
// arithmetic; this asks the browser: for each list, against competing rules of
// every nearby weight placed before and after it, does every element compute
// the same style from the rewritten rule as from the original?
const { test, expect } = require('@playwright/test');
const { transform } = require('lightningcss');
const { splitLongList } = require('../scripts/split_selector_lists.cjs');

test.use({ video: 'off', trace: 'off' });

const split = (css) => transform({
  filename: 'fixture.css',
  code: Buffer.from(css),
  minify: true,
  visitor: { Selector: (selector) => splitLongList(selector) },
}).code.toString();

const LISTS = [
  // heaviest alternative is a class; tags and a descendant pair are lighter
  'main :is(label, td, .a, .b, .c, nav a)',
  // heaviest is an id
  'main :is(label, .a, .b, .c, .d, #c)',
  // heaviest is two classes
  'main :is(label, .a.b, .c, .d, .e, td)',
  // the list is not the last part of the selector
  ':is(label, .a, .b, .c, .d, td) > span',
  // something follows the list in its own part
  'main :is(label, td, .a, .b, .c, .d):not(.skip)',
];

// Weights either side of every list above.
const RIVALS = [
  '[data-p]',
  'main [data-p]',
  '[data-p][data-p]',
  'main [data-p][data-p]',
  'main[data-m] [data-p][data-p]',
  'main[data-m] [data-p][data-p][data-p]',
  '#m [data-p]',
  'main#m [data-p]',
  '#m [data-p][data-p]',
  'main#m[data-m] [data-p][data-p]',
];

const BODY = `
<main id="m" data-m>
  <label data-p>label <span data-p>in label</span></label>
  <table><tbody><tr><td data-p>cell <span data-p>in cell</span></td></tr></tbody></table>
  <div class="a" data-p>a <span data-p>in a</span></div>
  <div class="b skip" data-p>b, skipped</div>
  <div class="a b" data-p>a and b</div>
  <div class="c" data-p>c</div>
  <div class="d" data-p>d</div>
  <div class="e" data-p>e</div>
  <div id="c" data-p>id c</div>
  <nav><a data-p href="#">link in nav</a></nav>
  <p data-p>matches no alternative</p>
</main>
<label data-p>label outside main</label>`;

test('a rewritten list styles every element exactly as the original did', async ({ page }) => {
  await page.setContent(`<!doctype html><html><head><style id="s"></style></head><body>${BODY}</body></html>`);
  const colours = (css) => page.evaluate((text) => {
    document.getElementById('s').textContent = text;
    return Array.from(document.querySelectorAll('[data-p]')).map((el) => getComputedStyle(el).color);
  }, css);

  let compared = 0;
  for (const list of LISTS) {
    const rule = `${list}{color:rgb(200, 0, 0)}`;
    const rewritten = split(rule);
    expect(rewritten, `${list} should have been written out`).not.toBe(rule.replace(/ /g, ''));
    for (const rival of RIVALS) {
      const other = `${rival}{color:rgb(0, 0, 200)}`;
      for (const [first, second] of [[other, null], [null, other]]) {
        const sheet = (body) => [first, body, second].filter(Boolean).join('\n');
        expect(
          await colours(sheet(rewritten)),
          `${list} against ${rival} ${first ? 'before' : 'after'} it`,
        ).toEqual(await colours(sheet(rule)));
        compared += 1;
      }
    }
  }
  expect(compared).toBe(LISTS.length * RIVALS.length * 2);

  // And the fixture can tell the difference: drop the weight and a rival that
  // used to lose now wins.
  const list = LISTS[0];
  const rule = `${list}{color:rgb(200, 0, 0)}`;
  const weightless = split(rule).replace(/:is\(\*,[^)]*\)/g, '');
  const rival = '[data-p]{color:rgb(0, 0, 200)}';
  expect(await colours(`${weightless}\n${rival}`)).not.toEqual(await colours(`${rule}\n${rival}`));
});
