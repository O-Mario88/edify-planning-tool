const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');

// Every click is answered at once (owner, 2026-10-08): the real script, run
// against the few DOM parts it reads.
function harness() {
  const handlers = { window: {}, document: {} };
  const timers = [];
  const rootAttrs = new Map();
  const root = {
    setAttribute: (k, v) => rootAttrs.set(k, v),
    removeAttribute: k => rootAttrs.delete(k),
    hasAttribute: k => rootAttrs.has(k),
  };
  const location = { origin: 'https://edify.test', pathname: '/dashboard', search: '' };

  function classes(initial) {
    const set = new Set(initial);
    return { add: k => set.add(k), remove: k => set.delete(k), contains: k => set.has(k), set };
  }

  function link(href, { classNames = [], attrs = {}, menu = null, origin = location.origin } = {}) {
    const url = new URL(href, location.origin + location.pathname);
    const el = {
      origin, pathname: url.pathname, search: url.search, href: url.href,
      target: attrs.target || '',
      classList: classes(classNames),
      hasAttribute: k => k in attrs,
      closest: sel => (sel === 'a[href]' ? el : sel === 'nav, aside, ul' ? menu : null),
    };
    return el;
  }

  function menu(...links) {
    return { querySelector: sel => links.find(l => l.classList.contains(sel.slice(1))) || null };
  }

  const window = {
    addEventListener(name, fn) { (handlers.window[name] ||= []).push(fn); },
  };
  const document = {
    documentElement: root,
    addEventListener(name, fn) { (handlers.document[name] ||= []).push(fn); },
  };
  vm.runInNewContext(fs.readFileSync('static/js/click-feedback.js', 'utf8'), {
    window, document, location,
    setTimeout: fn => { timers.push(fn); return timers.length; },
    clearTimeout: id => { if (id) timers[id - 1] = () => {}; },
    URLSearchParams, FormData: class { constructor(form) { this.form = form; } *[Symbol.iterator]() { yield* (this.form.fields || []); } },
  });

  function fire(target, name, event) {
    (handlers[target][name] || []).forEach(fn => fn(event));
    return event;
  }
  return {
    link, menu,
    loading: () => root.hasAttribute('data-edify-loading'),
    click: (el, extra = {}) => fire('window', 'click', { target: el, button: 0, defaultPrevented: false, ...extra }),
    submit: (form, extra = {}) => fire('window', 'submit', { target: form, defaultPrevented: false, ...extra }),
    htmx: (name, verb, type) => fire('document', name, { detail: { requestConfig: { verb, triggeringEvent: type ? { type } : null } } }),
    pageshow: () => fire('window', 'pageshow', {}),
    beforeunload: event => fire('window', 'beforeunload', event),
    runTimers: () => timers.splice(0).forEach(fn => fn()),
  };
}

test('a sidebar link is answered in the same turn: the line, and the entry reads as chosen', () => {
  const h = harness();
  const current = h.link('/dashboard', { classNames: ['app-sidebar__item', 'app-sidebar__item--active'] });
  const pressed = h.link('/my-plan', { classNames: ['app-sidebar__item'] });
  const nav = h.menu(current, pressed);
  current.closest = pressed.closest = sel => (sel === 'nav, aside, ul' ? nav : sel === 'a[href]' ? pressed : null);

  h.click(pressed);

  assert.equal(h.loading(), true);
  assert.equal(pressed.classList.contains('app-sidebar__item--active'), true);
  assert.equal(current.classList.contains('app-sidebar__item--active'), false);
});

test('a page that stays gives the menu back as it was', () => {
  const h = harness();
  const current = h.link('/dashboard', { classNames: ['app-sidebar__item', 'app-sidebar__item--active'] });
  const pressed = h.link('/my-plan', { classNames: ['app-sidebar__item'] });
  const nav = h.menu(current, pressed);
  pressed.closest = sel => (sel === 'nav, aside, ul' ? nav : sel === 'a[href]' ? pressed : null);
  h.click(pressed);

  h.pageshow();

  assert.equal(h.loading(), false);
  assert.equal(current.classList.contains('app-sidebar__item--active'), true);
  assert.equal(pressed.classList.contains('app-sidebar__item--active'), false);
});

test('any other link that leaves the page shows the line and touches no menu', () => {
  const h = harness();
  const row = h.link('/schools/abc', { classNames: ['font-semibold'] });
  h.click(row);
  assert.equal(h.loading(), true);
  assert.equal(row.classList.set.size, 1);
});

test('a click that goes nowhere shows nothing', () => {
  const cases = {
    'the page it is already on': h => h.click(h.link('/dashboard')),
    'only a place on this page': h => h.click(h.link('/dashboard#schools')),
    'a new tab': h => h.click(h.link('/login', { attrs: { target: '_blank' } })),
    'held with a modifier key': h => h.click(h.link('/my-plan'), { ctrlKey: true }),
    'the middle button': h => h.click(h.link('/my-plan'), { button: 1 }),
    'cancelled by the page': h => h.click(h.link('/my-plan'), { defaultPrevented: true }),
    'a file to save': h => h.click(h.link('/my-plan?export=xlsx')),
    'a download route': h => h.click(h.link('/fund-approvals/invoices/abc/download')),
    'a download link': h => h.click(h.link('/report', { attrs: { download: '' } })),
    'htmx takes it': h => h.click(h.link('/panel', { attrs: { 'hx-get': '/panel' } })),
    'another site': h => h.click(h.link('https://example.org/x', { origin: 'https://example.org' })),
    'not a link': h => h.click({ closest: () => null }),
  };
  for (const [name, run] of Object.entries(cases)) {
    const h = harness();
    run(h);
    assert.equal(h.loading(), false, name);
  }
});

test('a form the browser submits shows the line; one htmx took over does not', () => {
  const h = harness();
  const form = { getAttribute: () => null, action: 'https://edify.test/calendar', method: 'get', target: '', fields: [['month', '10']] };
  h.submit(form);
  assert.equal(h.loading(), true);

  const taken = harness();
  taken.submit(form, { defaultPrevented: true });
  assert.equal(taken.loading(), false);

  const file = harness();
  file.submit({ ...form, fields: [['export', 'csv']] });
  assert.equal(file.loading(), false);
});

test('a click that asks htmx for part of a page holds the line until every answer is in', () => {
  const h = harness();
  h.htmx('htmx:beforeSend', 'get', 'click');
  h.htmx('htmx:beforeSend', 'get', 'click');
  assert.equal(h.loading(), true);
  h.htmx('htmx:afterRequest', 'get', 'click');
  assert.equal(h.loading(), true);
  h.htmx('htmx:afterRequest', 'get', 'click');
  assert.equal(h.loading(), false);
});

test('typing in a search box, a save and a page loading its own parts are not clicks', () => {
  for (const [verb, type] of [['get', 'keyup'], ['get', 'load'], ['get', null], ['post', 'click']]) {
    const h = harness();
    h.htmx('htmx:beforeSend', verb, type);
    assert.equal(h.loading(), false, `${verb} on ${type}`);
  }
});

test('the line gives up by itself when nothing ever answers', () => {
  const h = harness();
  h.click(h.link('/my-plan'));
  h.runTimers();
  assert.equal(h.loading(), false);
});

test('"Leave this page?" answered No takes the line away', () => {
  const h = harness();
  h.click(h.link('/my-plan'));
  h.beforeunload({ returnValue: 'unsaved', defaultPrevented: true });
  h.runTimers();
  assert.equal(h.loading(), false);
});
