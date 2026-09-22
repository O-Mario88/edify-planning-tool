/*
 * A paginated link keeps the tab the reader chose (owner, 2026-09-22).
 *
 * Oversight shows one person's tables inside a tab panel, and the tab is a
 * browser-side choice written into the URL. The pager under the table is a
 * link the server wrote before any tab was touched, so following it used to
 * replace the whole query and drop the officer — page two came back on the
 * Programme Lead's own rows. The script under test carries the registered tab
 * parameters onto the link; these tests run it against a minimal DOM.
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const SOURCE = fs.readFileSync(
  path.join(__dirname, '../../static/js/table-pagination.js'),
  'utf8'
);

/* The smallest DOM the script actually touches: one delegated click listener,
   links that can answer `closest`, a location that records where it is sent. */
function stage({ href, linkHref, viewParams, fragment }) {
  const assigned = [];
  const replaced = [];
  const ajax = [];

  const host = fragment
    ? { getAttribute: (name) => (name === 'data-pager-fragment' ? fragment : null) }
    : null;

  const link = {
    target: '',
    getAttribute: (name) => (name === 'href' ? linkHref : null),
    hasAttribute: () => false,
    closest(selector) {
      if (selector === '[data-pager-fragment]') return host;
      return this;
    },
  };

  const listeners = {};
  const context = {
    window: {
      location: {
        href,
        assign(to) {
          assigned.push(to);
        },
      },
      history: {
        replaceState(_state, _title, to) {
          replaced.push(String(to));
        },
      },
      htmx: fragment
        ? {
            ajax(verb, url, options) {
              ajax.push({ verb, url, options });
            },
          }
        : undefined,
    },
    document: {
      addEventListener(type, handler) {
        listeners[type] = handler;
      },
    },
    URL,
  };
  if (viewParams) context.window.__edifyUrlViewParams = new Set(viewParams);
  context.self = context;
  vm.createContext(context);
  vm.runInContext(SOURCE, context);

  const prevented = [];
  listeners.click({
    target: link,
    button: 0,
    defaultPrevented: false,
    metaKey: false,
    ctrlKey: false,
    shiftKey: false,
    altKey: false,
    preventDefault() {
      prevented.push(true);
    },
  });

  return { assigned, replaced, ajax, prevented, host };
}

test('carries the officer the tab strip put in the URL onto the next page', () => {
  const result = stage({
    href: 'https://edify.test/team-planning-oversight/?owner=all&activity=all&officer=CCEO-7',
    linkHref: '?owner=all&activity=all&g2_page-cv=2',
    viewParams: ['officer', 'lead', 'cceo'],
  });

  assert.equal(result.assigned.length, 1);
  const sent = new URL(result.assigned[0]);
  assert.equal(sent.searchParams.get('officer'), 'CCEO-7');
  assert.equal(sent.searchParams.get('g2_page-cv'), '2');
  assert.equal(sent.searchParams.get('owner'), 'all');
});

test("the server's link wins for every parameter it names", () => {
  // A filter the reader has just changed is in the link and must not be
  // overwritten by the stale one still sitting in the address bar.
  const result = stage({
    href: 'https://edify.test/team-planning-oversight/?officer=CCEO-7&lead=PL-1',
    linkHref: '?officer=CCEO-9&g1_page=2',
    viewParams: ['officer', 'lead'],
  });

  const sent = new URL(result.assigned[0]);
  assert.equal(sent.searchParams.get('officer'), 'CCEO-9');
  assert.equal(sent.searchParams.get('lead'), 'PL-1');
});

test('carries nothing that no tab strip registered', () => {
  // A district the reader has just cleared stays cleared: only parameters a
  // strip owns are carried, and the browser follows its own link otherwise.
  const result = stage({
    href: 'https://edify.test/team-planning-oversight/?district=Kampala',
    linkHref: '?g1_page=2',
    viewParams: ['officer'],
  });

  assert.deepEqual(result.assigned, []);
  assert.deepEqual(result.prevented, []);
});

test('with no strip on the page the link is left exactly as written', () => {
  const result = stage({
    href: 'https://edify.test/schools?district=Kampala',
    linkHref: '?district=Kampala&page=2',
  });

  assert.deepEqual(result.assigned, []);
  assert.deepEqual(result.prevented, []);
});

test('a table inside a fetched fragment re-asks for the fragment, not the page', () => {
  // The Country Director's team panel: rebuilding the whole country oversight
  // page to turn one table's page is a second of work for nothing, and the
  // fragment's own URL is the only one that reaches the table.
  const result = stage({
    href: 'https://edify.test/country-planning-oversight/?lead=PL-2',
    linkHref: '?period=month&fy=2026&g1_page-cv=3',
    viewParams: ['lead'],
    fragment: '/country-planning-oversight/team/PL-2?period=month&fy=2026',
  });

  assert.deepEqual(result.prevented, [true]);
  assert.deepEqual(result.assigned, []);
  assert.equal(result.ajax.length, 1);
  assert.equal(result.ajax[0].verb, 'GET');
  const asked = new URL(result.ajax[0].url, 'https://example.test');
  assert.equal(asked.pathname, '/country-planning-oversight/team/PL-2');
  assert.equal(asked.searchParams.get('g1_page-cv'), '3');
  assert.equal(asked.searchParams.get('lead'), 'PL-2');
  assert.equal(result.ajax[0].options.target, result.host);

  // The address bar still describes the page, so a refresh lands on it.
  assert.equal(result.replaced.length, 1);
  assert.match(result.replaced[0], /g1_page-cv=3/);
  assert.match(result.replaced[0], /lead=PL-2/);
});
