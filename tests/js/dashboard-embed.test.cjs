/*
 * A page a dashboard carries keeps its links in place (owner, 2026-09-29: the
 * Programme Lead's Planning Monitor and Staff Activity Log moved onto the
 * dashboard). A figure's drill-down and the table pager are plain links the
 * page's fragment was written with; on the dashboard they must refill the
 * section, not leave the dashboard — and the pager's bare "?…" names the page
 * the fragment came from, not /dashboard. These tests run the script against
 * a minimal DOM.
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const SOURCE = fs.readFileSync(
  path.join(__dirname, '../../static/js/dashboard-embed.js'),
  'utf8'
);

function stage({ linkHref, attrs = {}, inEmbed = true, event = {} }) {
  const ajax = [];
  const target = { id: 'oversight-workspace' };
  const host = {
    getAttribute(name) {
      return {
        'data-dashboard-embed': '/planning-monitor/',
        'data-embed-target': '#oversight-workspace',
      }[name] || null;
    },
  };
  const link = {
    target: '',
    getAttribute: (name) => (name === 'href' ? linkHref : attrs[name] || null),
    hasAttribute: (name) => name in attrs,
    closest(selector) {
      if (selector === 'a[href]') return this;
      if (selector === '[data-dashboard-embed]') return inEmbed ? host : null;
      return null;
    },
  };
  const listeners = {};
  const context = {
    window: {
      location: { href: 'https://edify.test/dashboard?fy=2026' },
      htmx: {
        ajax(verb, url, options) {
          ajax.push({ verb, url, options });
        },
      },
    },
    document: {
      addEventListener(type, handler, capture) {
        listeners[type] = { handler, capture };
      },
      querySelector: (selector) => (selector === '#oversight-workspace' ? target : null),
    },
    URL,
  };
  context.self = context;
  vm.createContext(context);
  vm.runInContext(SOURCE, context);

  const prevented = [];
  listeners.click.handler({
    target: link,
    button: 0,
    defaultPrevented: false,
    metaKey: false,
    ctrlKey: false,
    shiftKey: false,
    altKey: false,
    ...event,
    preventDefault() {
      prevented.push(true);
    },
  });
  return { ajax, prevented, target, capture: listeners.click.capture };
}

test('the pager refills the section from the page it came from', () => {
  const result = stage({ linkHref: '?view=monitor&fy=2027&gap=no_visit&gap_page=2' });
  assert.equal(result.prevented.length, 1);
  assert.equal(result.ajax.length, 1);
  const { verb, url, options } = result.ajax[0];
  assert.equal(verb, 'GET');
  assert.equal(url, '/planning-monitor/?view=monitor&fy=2027&gap=no_visit&gap_page=2');
  assert.equal(options.target, result.target);
  assert.equal(options.swap, 'innerHTML');
  assert.equal(options.headers['X-Edify-Embed'], 'dashboard');
});

test("a figure's drill-down stays on the dashboard", () => {
  const result = stage({ linkHref: '/planning-monitor/?view=monitor&fy=2027&gap=no_training' });
  assert.equal(result.ajax[0].url, '/planning-monitor/?view=monitor&fy=2027&gap=no_training');
});

test('it answers before the pager script, in the capture phase', () => {
  assert.equal(stage({ linkHref: '?gap_page=2' }).capture, true);
});

test('links to other pages, htmx links and modified clicks are left alone', () => {
  for (const result of [
    stage({ linkHref: '/schools/42' }),
    stage({ linkHref: '/planning-monitor/?view=execution', attrs: { 'hx-get': '/planning-monitor/?view=execution' } }),
    stage({ linkHref: '?gap_page=2', event: { metaKey: true } }),
    stage({ linkHref: '?gap_page=2', inEmbed: false }),
  ]) {
    assert.deepEqual(result.ajax, []);
    assert.deepEqual(result.prevented, []);
  }
});
