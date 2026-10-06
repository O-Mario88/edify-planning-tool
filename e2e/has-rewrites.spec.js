// Rules that asked an ancestor a question with `:has()` and styled any
// element beneath it made a browser restyle a whole phone page whenever
// anything was added to it (audit, 2026-10-05). They were rewritten three
// ways: the question is read from an attribute micro-ux.js keeps on the
// ancestor (e2e/maintained-facts.spec.js holds those attributes to the page),
// it is asked of the styled element itself, or — "four children or more",
// "exactly two" — it is a count the element can read from its own place among
// its siblings. Each may change how a rule is found and nothing else. This
// takes every rewritten selector from the stylesheets as shipped, rebuilds the
// selector it replaced, and checks on one page built to exercise them all that
// the two select the same elements and weigh the same against rival rules
// either side of their weight. Two rules are kept in both forms, each for the
// widths where it is the cheaper to answer; the last test holds each pair
// together.
const fs = require('node:fs');
const path = require('node:path');
const { test, expect } = require('@playwright/test');
const { transform } = require('lightningcss');

test.use({ video: 'off', trace: 'off' });

const CSS = path.join(__dirname, '..', 'static', 'css');
const minify = (selector) => transform({ filename: 's.css', code: Buffer.from(`${selector}{color:red}`), minify: true }).code.toString().replace(/\{.*$/s, '');

// Every selector of a stylesheet, minified, one per rule alternative.
function selectorsOf(file) {
  const out = [];
  const print = (selector) => transform({ filename: 's.css', code: Buffer.from('a{color:red}'), minify: true, visitor: { Selector: () => selector } }).code.toString().replace(/\{.*$/s, '');
  transform({ filename: file, code: fs.readFileSync(path.join(CSS, file)), visitor: { Selector(selector) { out.push(print(selector)); return selector; } } });
  return out;
}

// The facts kept as attributes, as written in the stylesheets, and what each stood in for.
const BOX = ':is(input[type=checkbox],input[type=radio],.edify-table-choice)';
const SELECT_COLUMN = `>tbody>tr>:first-child>${BOX},>tbody>tr>:first-child>label>:is(input[type=checkbox],input[type=radio])`;
const KEPT = [
  ['table:not([data-edify-select-column]):is(*,_ _ _ _ ._)', `table:not(:has(${SELECT_COLUMN}))`],
  ['table[data-edify-select-column]:is(*,_ _ _ _ ._)', `table:has(${SELECT_COLUMN})`],
  [':where([data-edify-head-run]):is(*,_)', ':not(:has(>:is(p,div,ul,dl,form)))'],
  ['[data-edify-tablist][data-edify-beside-link]:is(*,_)', '[data-edify-tablist]:has(+a.btn)'],
  // The search box: an attribute weighs what `:has(.class)` weighed, so nothing is added to it.
  ['[data-edify-has-submit]', ':has(.edify-search-submit)'],
];
const ATTRIBUTES = /data-edify-(select-column|head-run|beside-link|has-submit)/;
const KEPT_IN = ['components/responsive-system.css', 'components/interactions.css', 'components.css', 'components/mobile-shell.css'];

// The questions now asked of the styled element: [stylesheet, as shipped, as it stood].
const LEAD = '.edify-page-eyebrow,.edify-page-header__eyebrow,h1,.edify-page-title,.edify-page-header__description,.edify-page-subtitle,[hidden]';
const HEADER = `main .edify-page-header.edify-page-header:has(>.edify-page-header__lead>:is(h1,.edify-page-title)):has(>.edify-page-header__controls>*):not(:has(>.edify-page-header__controls>:nth-child(3))):not(:has(>:nth-child(3))):not(:has(>.edify-page-header__lead>:not(${LEAD})))`;
const RAILS = 'main :is([role=tablist],.edify-tab-container,[data-edify-tablist],.messages-inbox-tabs,.pto-tabs,.sp-period-tabs,.spp-tabs,.tt-segmented,.oversight-entity-tabs,.edify-section-nav__clusters,.edify-section-nav__inner)';
const LAST_TAB = ':nth-last-child(1 of :is(a,button,[role=tab],[data-edify-tab]))';
const MORE = '.edify-rail-more:not([hidden])';
const TOOLS = '[data-pl-dashboard] [data-pl-section-tools] .edify-page-header-control';
// A caption with a paragraph or heading straight after it, among a surface's children (platform.css).
const CAPTION = '.edify-text-caption.uppercase:is(:has(+:is(p,h3,h4)),:has(~.edify-text-caption+:is(p,h3,h4)),.edify-text-caption:has(+:is(p,h3,h4))~*)';
const SURFACE = ':has(>.edify-text-caption+:is(p,h3,h4))>.edify-text-caption.uppercase';
const ASKED = [
  ['components/interactions.css', `${HEADER}>.edify-page-header__lead>:where(${LEAD})`, `${HEADER}>.edify-page-header__lead>*`],
  ['components/interactions.css', `${RAILS}>${LAST_TAB}:not(:is(${MORE},${MORE}~*,:has(~${MORE})))`, `${RAILS}:not(:has(>${MORE}))>${LAST_TAB}`],
  ['components.css', '#filters-form :is(div>select~span:not(.sr-only),div>span:not(.sr-only):has(~select),.edify-filter-label)', '#filters-form :is(div:has(>select)>span:not(.sr-only),.edify-filter-label)'],
  ['components/pl-dashboard.css', `${TOOLS}>span:not(:is(select[name=fy]~*,:has(~select[name=fy])))`, `${TOOLS}:not(:has(>select[name=fy]))>span`],
  // The second pass (F19): the block that holds an h1, asked of its last child, and a surface's caption, asked of the
  // caption (both below 1280px; platform.css keeps the originals for wider windows — the last test); four children
  // or more and exactly two, asked of a child.
  ['platform.css', 'main>div>:where(header,div)>:where(div,nav):last-child:is(:has(h1),:is(h1,:has(h1))~*)', 'main>div>:where(header,div):has(h1)>:where(div,nav):last-child'],
  ['components/interactions.css', ':root main .school-record-row .school-record-row__actions>:where(:first-child:nth-last-child(n+4),:first-child:nth-last-child(n+4)~*):is(*,._) svg', ':root main .school-record-row .school-record-row__actions:has(>:nth-child(4))>* svg'],
  ['components/interactions.css', 'main .edify-head-row--action.edify-head-row--action>.edify-head-row__title.edify-head-row__title:is(:first-child:nth-last-child(2),:nth-child(2):last-child)', 'main .edify-head-row--action.edify-head-row--action:has(>:nth-child(2):last-child)>.edify-head-row__title.edify-head-row__title'],
  // These two are the alternatives of one `main :where(…)` list: found there by their own text.
  ['platform.css', `main :where(.rounded-surface>${CAPTION})`, `main :where(.rounded-surface${SURFACE})`, `.rounded-surface>${CAPTION}`],
  ['platform.css', `main :where(.rounded-control>${CAPTION})`, `main :where(.rounded-control${SURFACE})`, `.rounded-control>${CAPTION}`],
];

function pairs() {
  const found = [];
  for (const file of KEPT_IN) {
    for (const shipped of selectorsOf(file)) {
      if (!ATTRIBUTES.test(shipped)) continue;
      let original = shipped;
      for (const [kept, asked] of KEPT) original = original.split(kept).join(asked);
      expect(original, `${shipped} is one of the known forms`).not.toMatch(ATTRIBUTES);
      found.push({ file, shipped, original });
    }
  }
  for (const [file, shipped, original, within] of ASKED) {
    // Minified the same way on both sides, so only the text of the selector is compared.
    const all = selectorsOf(file);
    const needle = within ? minify(`x ${within}`).slice(2) : minify(shipped).replace(/^#filters-form /, '');
    expect(all.some((selector) => selector === minify(shipped) || selector.includes(needle)), `${file} still carries ${shipped}`).toBe(true);
    found.push({ file, shipped: minify(shipped), original: minify(original) });
  }
  return found;
}

// One page that puts every rewritten rule through both of its answers.
function fixture() {
  const cells = [
    '<span>Name</span><span>more</span>',
    '<a href="#">Name</a>',
    '<input type="checkbox">',
    '<label><input type="checkbox"></label>',
    '<label class="edify-table-choice"><input type="radio"></label>',
    '<span class="edify-table-choice"></span>',
    '<button type="button">b</button><span>after</span>',
    '<span class="edify-cell-line">one</span><span class="edify-cell-line">two</span>',
    '<input type="text">',
    '',
  ];
  const tables = [];
  for (const state of ['start', 'middle', 'end', 'none', null]) {
    for (const first of cells) {
      const rows = cells.slice(0, 4).concat(cells[7]).map((second) => `<tr><td>${first}</td><td>${second}</td><td><span>x</span></td></tr>`).join('');
      const body = `<thead><tr><th><span>h1</span></th><th><span>h2</span></th><th>h3</th></tr></thead><tbody>${rows}<tr><td colspan="3"><span>Group</span></td></tr><tr><td data-pinned-stack><i>a</i><i>b</i></td><td>z</td></tr></tbody><tfoot><tr><td><span>f</span></td><td>g</td></tr></tfoot>`;
      tables.push(`<div class="edify-table-scroll-region"${state ? ` data-scroll-state="${state}"` : ''}><table>${body}</table></div>`);
    }
    // A box only in the header, and only in a later body cell: neither is a selection column.
    tables.push(`<div class="edify-table-scroll-region"${state ? ` data-scroll-state="${state}"` : ''}><table><thead><tr><th><input type="checkbox"></th><th>h</th></tr></thead><tbody><tr><td><span>n</span></td><td><input type="checkbox"></td></tr></tbody></table></div>`);
  }
  const kids = ['<h3 class="edify-head-row__title">Title</h3>', '<span>12</span>', '<a href="#">go</a>', '<p>para</p>', '<div>block</div>', '<ul><li>i</li></ul>', '<form></form>', '<svg></svg>'];
  const headRows = [];
  for (const action of ['', ' edify-head-row--action']) {
    for (let mask = 1; mask < 1 << kids.length; mask += 3) {
      headRows.push(`<div class="edify-head-row${action}">${kids.filter((_, index) => mask & (1 << index)).join('')}</div>`);
    }
  }
  const leads = ['<h1>T</h1>', '<p class="edify-page-eyebrow">e</p><h1 class="edify-page-title">T</h1><p class="edify-page-header__description">d</p>', '<h1>T</h1><span hidden>h</span>', '<h1>T</h1><div>other</div>', '<p class="edify-page-subtitle">no title</p>', '<span class="edify-page-header__eyebrow">e</span><h1>T</h1><p class="edify-page-subtitle">s</p>'];
  const controls = ['', '<a>1</a>', '<a>1</a><a>2</a>', '<a>1</a><a>2</a><a>3</a>'];
  const headers = [];
  for (const lead of leads) for (const control of controls) for (const extra of ['', '<div>third</div>']) {
    headers.push(`<header class="edify-page-header"><div class="edify-page-header__lead">${lead}</div><div class="edify-page-header__controls">${control}</div>${extra}</header>`);
  }
  headers.push('<header class="edify-page-header"><div class="edify-page-header__lead"><h1>T</h1></div></header>');
  const more = ['', '<details class="edify-rail-more"></details>', '<details class="edify-rail-more" hidden></details>'];
  const rails = [];
  for (const kind of ['role="tablist"', 'class="edify-tab-container"', 'data-edify-tablist', 'class="tt-segmented"', 'class="edify-section-nav__inner"', 'class="not-a-rail"']) {
    for (const before of more) for (const after of more) for (const tail of ['', '<span>status</span>']) {
      rails.push(`<nav ${kind}>${before}<a href="#">One</a><button type="button">Two</button><span role="tab">Three</span>${tail}${after}</nav>`);
    }
  }
  const toolbars = ['<a class="btn" href="#">Open</a>', '<a href="#">Open</a>', '<span>x</span><a class="btn" href="#">Open</a>', '<button class="btn">b</button>', ''].map((next) =>
    `<div class="edify-view-toolbar"><nav data-edify-tablist><a data-edify-tab href="#">A</a><button>B</button><span>C</span><details class="edify-rail-more"></details></nav>${next}</div>`);
  const fields = ['<select></select><span>after</span>', '<span>before</span><select></select>', '<span>alone</span>', '<span class="sr-only">hidden</span><select></select>', '<span>a</span><span>b</span><select></select><span>c</span>', '<label><span>in label</span><select></select></label>', '<span class="edify-filter-label">marked</span>', '<input><span>beside an input</span>'];
  const forms = `<form id="filters-form">${fields.map((field) => `<div>${field}</div>`).join('')}<p><select></select><span>not in a div</span></p></form><div>${fields[0]}</div>`;
  const tools = ['<span>Year</span><select name="fy"></select>', '<select name="fy"></select><span>Year</span>', '<span>Gap</span><select name="gap"></select>', '<span>alone</span>', '<span>a</span><select name="gap"></select><span>b</span><select name="fy"></select><span>c</span>'];
  const dashboard = `<section data-pl-dashboard><div data-pl-section-tools>${tools.map((tool) => `<label class="edify-page-header-control">${tool}</label>`).join('')}</div></section><div data-pl-section-tools><label class="edify-page-header-control">${tools[2]}</label></div>`;
  // A title beside one action, two, none; the title first, second or absent.
  const titled = [];
  const title = '<h3 class="edify-head-row__title">Title</h3>';
  for (const children of [[title], [title, '<a>act</a>'], ['<a>act</a>', title], [title, '<a>1</a>', '<a>2</a>'], ['<span>n</span>', title, '<a>1</a>'], ['<a>1</a>', '<a>2</a>'], [title, title], ['<a>1</a>', '<a>2</a>', title]]) {
    for (const action of ['edify-head-row edify-head-row--action', 'edify-head-row']) titled.push(`<div class="${action}">${children.join('')}</div>`);
  }
  // A school row's actions: one to six of them, each with an icon somewhere inside.
  const acts = ['<a href="#"><svg></svg>Open</a>', '<button type="button"><span><svg></svg></span>Plan</button>', '<div class="row-menu"><button type="button"><svg></svg></button></div>', '<svg></svg>'];
  const schoolRows = [];
  for (let count = 0; count <= 6; count += 1) for (let start = 0; start < acts.length; start += 1) {
    const children = Array.from({ length: count }, (_, index) => acts[(start + index) % acts.length]).join('');
    schoolRows.push(`<div class="school-record-row"><div class="school-record-row__actions">${children}</div><svg></svg></div><div class="school-record-row__actions">${children}</div>`);
  }
  // Blocks under main > div: every run of one to three of these children, in a header, a div and a section.
  const parts = ['<h1>T</h1>', '<div><h1>T</h1></div>', '<div>plain</div>', '<nav>n</nav>', '<nav><span><h1>deep</h1></span></nav>', '<p>p</p>', '<span>s</span>'];
  const runs = [];
  for (const a of parts) { runs.push([a]); for (const b of parts) { runs.push([a, b]); for (const c of parts) runs.push([a, b, c]); } }
  const blocks = [];
  for (const tag of ['header', 'div', 'section']) for (const run of runs) blocks.push(`<${tag}>${run.join('')}</${tag}>`);
  // One level too deep, and a block that is itself the last child of a block.
  blocks.push('<div><header><h1>T</h1><div>actions</div></header></div>', '<div><div><div><h1>T</h1></div><nav>n</nav></div><div>last</div></div>');
  // A surface's children: every run of one to three of these; and a caption one level too deep.
  const bits = ['<span class="edify-text-caption uppercase">Cap</span>', '<span class="edify-text-caption">cap</span>', '<p>para</p>', '<h3>h</h3>', '<h4>h</h4>', '<div>d</div>', '<span class="uppercase">u</span>'];
  const surfaces = [];
  for (const box of ['rounded-surface', 'rounded-control', 'card']) {
    for (const a of bits) { surfaces.push([box, a]); for (const b of bits) { surfaces.push([box, a + b]); for (const c of bits) surfaces.push([box, a + b + c]); } }
    surfaces.push([box, `<div>${bits[0]}${bits[2]}</div>`], [box, `${bits[0]}<div>${bits[2]}</div>`]);
  }
  const surfaced = surfaces.map(([box, inside]) => `<div class="${box}">${inside}</div>`);
  // The search box, with and without its button, in a form and not, open and shut; and something that only borrows its class.
  const submit = '<button class="edify-search-submit" type="submit"></button>';
  const searches = [`<form><input type="search">${submit}</form>`, `<input type="search">${submit}`, '<form><input type="search"></form>', '<input type="search">', `<form><input type="search"><span>${submit}</span></form>`, `<form><input type="text"></form>${submit}`, '']
    .flatMap((inside) => [`<search class="edify-topbar__search">${inside}</search>`, `<search class="edify-topbar__search is-open">${inside}</search>`, `<search>${inside}</search>`, `<div class="edify-topbar__search is-open">${inside}</div>`]);
  return `<main>${tables.join('')}${headRows.join('')}${headers.join('')}${rails.join('')}${toolbars.join('')}${forms}${dashboard}${titled.join('')}${schoolRows.join('')}${surfaced.join('')}<div>${blocks.join('')}</div></main>${searches.join('')}`;
}

test('every rewritten selector selects and weighs what the one it replaced did', async ({ page }) => {
  const all = pairs();
  expect(all.length, 'rewritten selectors found in the stylesheets').toBeGreaterThan(20);

  await page.setContent(`<!doctype html><html><head><style id="s"></style></head><body>${fixture()}</body></html>`);
  // The attributes, written from the selectors they stand for (maintained-facts.spec.js checks micro-ux.js does the same).
  await page.evaluate(([box]) => {
    for (const table of document.querySelectorAll('table')) table.toggleAttribute('data-edify-select-column', table.matches(`:has(> tbody > tr > :first-child > ${box}, > tbody > tr > :first-child > label > :is(input[type=checkbox], input[type=radio]))`));
    for (const row of document.querySelectorAll('.edify-head-row')) row.toggleAttribute('data-edify-head-run', !row.matches(':has(> :is(p, div, ul, dl, form))'));
    for (const rail of document.querySelectorAll('[data-edify-tablist]')) rail.toggleAttribute('data-edify-beside-link', rail.matches(':has(+ a.btn)'));
    for (const search of document.querySelectorAll('search, .edify-topbar__search')) search.toggleAttribute('data-edify-has-submit', search.matches(':has(.edify-search-submit)'));
  }, [BOX]);

  const results = await page.evaluate((list) => {
    const elements = Array.from(document.body.querySelectorAll('*'));
    const style = document.getElementById('s');
    const bare = (selector) => selector.replace(/::?(before|after)$/, '');
    // A rival that matches the same element at any weight asked for: `:is(*, …)` matches everything.
    const rival = (ids, classes, types) => (ids + classes + types
      ? `[data-rival]:is(*, ${'_ '.repeat(Math.max(types - 1, 0))}${types ? '_' : ''}${'#_'.repeat(ids)}${'._'.repeat(classes)})`
      : '[data-rival]');
    return list.map(({ shipped, original }) => {
      const was = Array.from(document.querySelectorAll(bare(original))).map((el) => elements.indexOf(el));
      const now = Array.from(document.querySelectorAll(bare(shipped))).map((el) => elements.indexOf(el));
      const same = was.length === now.length && was.every((index, i) => index === now[i]);
      let flips = 0; let disagreements = 0; let rulings = 0;
      if (was.length && !/::?(before|after)$/.test(shipped)) {
        const subject = elements[was[0]];
        subject.setAttribute('data-rival', '');
        // Every rival at once: each has a custom property of its own, declared before the rule (--a…) and after it (--z…).
        // One rival that weighs nothing at all, for the rules that weigh one type (inside `main :where(…)`).
        const rivals = [':where([data-rival])'];
        for (let ids = 0; ids <= 2; ids += 1) for (let classes = 0; classes <= 13; classes += 1) for (let types = 0; types <= 9; types += 1) rivals.push(rival(ids, classes, types));
        const rulingsOf = (selector) => {
          style.textContent = rivals.map((other, k) => `${other}{--a${k}:rival}`).join('\n')
            + `\n${selector}{${rivals.map((_, k) => `--a${k}:rule;--z${k}:rule`).join(';')}}\n`
            + rivals.map((other, k) => `${other}{--z${k}:rival}`).join('\n');
          const computed = getComputedStyle(subject);
          return rivals.flatMap((_, k) => [computed.getPropertyValue(`--a${k}`).trim(), computed.getPropertyValue(`--z${k}`).trim()]);
        };
        const a = rulingsOf(original); const b = rulingsOf(shipped);
        rulings = a.length;
        a.forEach((value, k) => { if (value !== b[k]) disagreements += 1; if (value === 'rival') flips += 1; });
        style.textContent = '';
        subject.removeAttribute('data-rival');
      }
      return { shipped, original, same, matched: was.length, total: elements.length, was: was.slice(0, 6), now: now.slice(0, 6), disagreements, flips, rulings };
    });
  }, all);

  const listed = JSON.stringify(results.map(({ shipped, original, matched, rulings }) => ({ shipped, original, matched, rulings })), null, 2);
  await test.info().attach('rewritten-selectors.json', { body: Buffer.from(listed), contentType: 'application/json' });
  if (process.env.EDIFY_REWRITES_OUT) fs.writeFileSync(process.env.EDIFY_REWRITES_OUT, listed);
  for (const result of results) {
    expect(result.same, `${result.shipped}\n  selects what\n${result.original}\n  selected (first indexes ${result.was} / ${result.now})`).toBe(true);
    expect(result.matched, `the page exercises ${result.shipped}`).toBeGreaterThan(0);
    expect(result.matched, `${result.shipped} does not select everything`).toBeLessThan(result.total / 2);
    expect(result.disagreements, `${result.shipped} against ${result.rulings} rival rulings`).toBe(0);
    // The rivals straddle the weight: the rule wins some and loses some.
    if (result.rulings) { expect(result.flips).toBeGreaterThan(0); expect(result.flips).toBeLessThan(result.rulings); }
  }
});

// Two rules of platform.css are asked the new way below 1280px and the old way from 1280px, where the new way costs
// a desktop page more than it saves: the block that holds an h1, and a surface's caption. A width must get exactly
// one of each pair, and the two must say the same thing.
const NARROW = 'not all and (min-width: 80rem)';
const WIDE = '(min-width: 80rem)';
const KEPT_BOTH_WAYS = [
  {
    starts: 'main > div > :where(header, div)',
    shipped: ASKED.find(([, , was]) => was.startsWith('main>div>:where(header,div):has(h1)>'))[1],
    original: 'main>div>:where(header,div):has(h1)>:where(div,nav):last-child',
    // Elsewhere: the phone's copy of the rewritten one, inside a narrower query; the original nowhere else.
    elsewhere: { shipped: 1, original: 0 },
    page: '<main><div><header><h1>T</h1><div id="yes">actions</div></header><header><p>T</p><div id="no">actions</div></header></div></main>',
    property: 'flex-wrap', yes: 'wrap', no: 'nowrap',
  },
  {
    starts: 'main :where(\n    .rounded-',
    shipped: `main :where(.rounded-surface>${CAPTION},.rounded-control>${CAPTION})`,
    original: `main :where(.rounded-surface${SURFACE},.rounded-control${SURFACE})`,
    elsewhere: { shipped: 0, original: 0 },
    page: `<style>.uppercase { text-transform: uppercase; }</style><main><div class="rounded-surface"><span id="yes" class="edify-text-caption uppercase">c</span><p>v</p></div>
      <div class="rounded-surface"><span id="no" class="edify-text-caption uppercase">c</span><div>v</div></div></main>`,
    property: 'text-transform', yes: 'none', no: 'uppercase',
  },
];

test('a rule kept in both forms gives every width exactly one of them', async ({ page }) => {
  const css = fs.readFileSync(path.join(CSS, 'platform.css'), 'utf8');
  const all = selectorsOf('platform.css');
  for (const pair of KEPT_BOTH_WAYS) {
    const block = (query) => {
      const at = css.indexOf(`@media ${query} {\n  ${pair.starts}`);
      expect(at, `platform.css keeps "${pair.starts}…" under @media ${query}`).toBeGreaterThan(-1);
      const [text, selector, body] = css.slice(at).match(/^@media [^{]+\{\s*([^{}]+?)\s*\{([^{}]*)\}\s*\}/);
      return { text, selector: minify(selector), body: body.replace(/\s+/g, ' ').trim() };
    };
    const narrow = block(NARROW);
    const wide = block(WIDE);
    expect(narrow.selector).toBe(minify(pair.shipped));
    expect(wide.selector).toBe(minify(pair.original));
    expect(narrow.body).toBe(wide.body);
    expect(narrow.body.length).toBeGreaterThan(0);
    expect(all.filter((selector) => selector === minify(pair.shipped)), 'the new way, at other widths').toHaveLength(1 + pair.elsewhere.shipped);
    expect(all.filter((selector) => selector === minify(pair.original)), 'the old way, at other widths').toHaveLength(1 + pair.elsewhere.original);

    await page.setContent(`<!doctype html><html><head><style>${narrow.text}\n${wide.text}</style></head><body>${pair.page}</body></html>`);
    for (const width of [320, 1279, 1280, 1281, 2560]) {
      await page.setViewportSize({ width, height: 800 });
      const seen = await page.evaluate(([a, b, property]) => ({
        queries: [matchMedia(a).matches, matchMedia(b).matches],
        yes: getComputedStyle(document.getElementById('yes')).getPropertyValue(property),
        no: getComputedStyle(document.getElementById('no')).getPropertyValue(property),
      }), [NARROW, WIDE, pair.property]);
      expect(seen, `${pair.starts} at ${width}px`).toEqual({ queries: [width < 1280, width >= 1280], yes: pair.yes, no: pair.no });
    }
  }
});
