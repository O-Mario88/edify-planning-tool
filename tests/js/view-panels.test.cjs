// The dashboard panel cache must never leave an empty workspace (controls
// audit F-08, 2026-09-14). Runs the real script against a minimal DOM.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');

function setup() {
  const listeners = {};
  const state = { attached: true };
  const panel = { remove() { state.attached = false; }, setAttribute() {} };
  const host = {
    querySelector: () => (state.attached ? panel : null),
    matches: () => true,
    appendChild(node) { if (node === panel) state.attached = true; },
  };
  const tab = { getAttribute: () => '/dashboard?view=overview', classList: { toggle() {} }, setAttribute() {}, dataset: {} };
  const document = {
    readyState: 'complete',
    querySelector(selector) {
      if (selector === '[data-dashboard-live]') return null;
      if (selector === '[data-dashboard-view-shell]') return host;
      if (selector === '[data-dashboard-views] .edify-section-nav__link.is-active') return tab;
      if (selector === '[data-dashboard-views]') return { querySelectorAll: () => [tab], querySelector: () => tab };
      return null;
    },
    addEventListener(name, fn) { (listeners[name] ||= []).push(fn); },
  };
  const window = {
    location: { origin: 'http://test', href: 'http://test/dashboard?view=overview' },
    addEventListener() {},
    history: { pushState() {} },
  };
  vm.runInNewContext(fs.readFileSync('static/js/view-panels.js', 'utf8'), { document, window, URL });
  const emit = (name, detail) => (listeners[name] || []).forEach((fn) => fn({ detail: { target: host, ...detail } }));
  return { state, emit };
}

test('a failed tab response keeps the last good panel', () => {
  const h = setup();
  h.emit('htmx:beforeSwap', { shouldSwap: false, isError: true, xhr: { status: 500 } });
  h.emit('htmx:afterRequest', { successful: false });
  assert.equal(h.state.attached, true);
});

test('a swap cancelled after parking puts the panel back', () => {
  const h = setup();
  h.emit('htmx:beforeSwap', { shouldSwap: true, isError: false, xhr: { status: 200 } });
  assert.equal(h.state.attached, false, 'a committed swap parks the panel');
  // A later listener cancelled the swap, so nothing arrived in the shell.
  h.emit('htmx:afterRequest', { successful: true });
  assert.equal(h.state.attached, true);
});
