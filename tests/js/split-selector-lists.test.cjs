// The CSS build writes a long `:is()` list out as one selector per
// alternative, so a browser can file each under its own class or tag instead
// of trying the whole list against every element (audit, 2026-10-05:
// consistency.css was 71% of a whole-page style recalculation). The rewrite
// is only allowed to change how a rule is found, never what it matches or how
// much it weighs. These pin that, through the same parser the build uses.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { transform } = require('lightningcss');
const { SPLIT_FROM, specificity, splitLongList } = require('../../scripts/split_selector_lists.cjs');

function build(css) {
  return transform({
    filename: 'fixture.css',
    code: Buffer.from(css),
    minify: true,
    visitor: { Selector: selector => splitLongList(selector) },
  }).code.toString();
}

// The built rule's selectors, split at the commas between them (not the ones
// inside a pseudo-class).
function selectorsOf(css) {
  const list = build(css).replace(/\{.*$/s, '');
  const out = [''];
  let depth = 0;
  for (const char of list) {
    if (char === '(') depth += 1;
    if (char === ')') depth -= 1;
    if (char === ',' && depth === 0) out.push('');
    else out[out.length - 1] += char;
  }
  return out;
}

function parsed(selector) {
  let seen = null;
  transform({
    filename: 'fixture.css',
    code: Buffer.from(`${selector}{color:red}`),
    visitor: { Selector(node) { seen = seen || node; return node; } },
  });
  return seen;
}

const weigh = selector => specificity(parsed(selector));

test('a list of equal-weight classes becomes one plain selector each', () => {
  assert.deepEqual(
    selectorsOf('main :is(.a, .b, .c, .d, .e, .f) { color: red }'),
    ['main .a', 'main .b', 'main .c', 'main .d', 'main .e', 'main .f'],
  );
});

test('a lighter alternative keeps the weight the list gave it', () => {
  // `:is(label, .a, …)` weighs as a class whichever alternative matched, so
  // `label` on its own would lose to a rule it used to beat.
  const out = selectorsOf('main :is(label, .a, .b, .c, .d, .e) { color: red }');
  assert.equal(out[0], 'main :where(label):is(*,._)');
  assert.deepEqual(out.slice(1), ['main .a', 'main .b', 'main .c', 'main .d', 'main .e']);
  for (const selector of out) {
    assert.deepEqual(weigh(selector), weigh('main :is(label, .a, .b, .c, .d, .e)'), selector);
  }
});

test('every rewritten selector weighs what the list weighed', () => {
  const lists = [
    'main :is(label, dt, th, .a, .b, .c)',
    'main :is(.a, .b, .c, .d, .e, #id)',
    'main :is(nav a, .a, .b, .c, .d, .e)',
    'main :is(.a.b, .c, .d, .e, .f, td)',
    'main :is(div.card:not(.flat), .a, .b, .c, .d, .e)',
    'main :is(a:hover, b, i, em, strong, small)',
    'main :is(.a, .b, .c, .d, .e, .f):not(:is(h1, .title)) > span',
    ':is(.a, .b, .c, .d, .e, td, th) *',
  ];
  for (const list of lists) {
    const out = selectorsOf(`${list} { color: red }`);
    assert.ok(out.length >= SPLIT_FROM, `${list} was not split`);
    for (const selector of out) assert.deepEqual(weigh(selector), weigh(list), `${list} → ${selector}`);
  }
});

test('the weight is carried by something that cannot exclude an element', () => {
  // `:is(*, x)` matches everything; `:not(.x)` would stop matching the day an
  // element was given that class.
  const out = build('main :is(label, .a.b, #c, .d, .e, .f) { color: red }');
  assert.match(out, /:where\(label\):is\(\*,#_\)/);
  assert.doesNotMatch(out, /:not\(/);
});

test('a list inside a list is one list', () => {
  assert.deepEqual(
    selectorsOf('main :is(.a, :is(.b, .c, .d), .e, :is(.f)) { color: red }'),
    ['main .a', 'main .b', 'main .c', 'main .d', 'main .e', 'main .f'],
  );
});

test('an alternative with its own combinator stays whole', () => {
  const out = selectorsOf('main :is(nav a, .a, .b, .c, .d, .e) { color: red }');
  assert.equal(out[0], 'main :where(nav a):is(*,._)');
});

test('what surrounds the list is repeated around every alternative', () => {
  assert.deepEqual(
    selectorsOf('main > :is(.a, .b, .c, .d, .e, .f):hover + p::before { color: red }'),
    ['.a', '.b', '.c', '.d', '.e', '.f'].map(name => `main>${name}:hover+p:before`),
  );
});

test('short lists are left alone', () => {
  const css = 'main :is(.a,.b,.c,.d,.e){color:red}';
  assert.equal(build(css), css);
});

test('only the longest list in a selector is written out', () => {
  // Two lists multiplied would be thirty-six selectors for one rule.
  const out = selectorsOf(':is(.a, .b, .c, .d, .e, .f) :is(.g, .h, .i, .j, .k, .l, .m) { color: red }');
  assert.equal(out.length, 7);
  assert.ok(out.every(selector => selector.startsWith(':is(.a,.b,.c,.d,.e,.f) .')));
});

test('a list a browser might read differently is left as written', () => {
  // `:is()` forgives an alternative it cannot parse and drops its weight, so
  // what the list weighs can differ by browser. Nothing here guesses.
  for (const css of [
    'main :is(.a,.b,.c,.d,.e,.f:has(img)){color:red}',
    'main :is(.a,.b,.c,.d,.e,.f:focus-visible){color:red}',
    'main :is(.a,.b,.c,.d,.e,:nth-child(2 of .f)){color:red}',
  ]) {
    assert.equal(build(css), css);
  }
});

test('declarations and rule order are untouched', () => {
  assert.equal(
    build('.x{color:blue}main :is(.a,.b,.c,.d,.e,.f){color:red;margin:0}.y{color:green}'),
    '.x{color:#00f}main .a,main .b,main .c,main .d,main .e,main .f{color:red;margin:0}.y{color:green}',
  );
});
