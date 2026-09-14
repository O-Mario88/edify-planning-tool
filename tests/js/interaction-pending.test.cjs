const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');

// Exercise the real lifecycle script without a browser or server mutation.
function harness() {
  const handlers = {};
  const timers = [];
  const elements = [];
  function element(tag = 'BUTTON', text = 'Save') {
    const attrs = new Map([['hx-post', '/save']]);
    const classes = new Set();
    const el = {
      tagName: tag, dataset: {}, style: { width: '' }, value: text,
      childNodes: [{ textContent: text }],
      get textContent() { return this.childNodes.map(n => n.textContent).join(''); },
      set textContent(value) { this.childNodes = [{ textContent: value }]; },
      getAttribute: k => attrs.has(k) ? attrs.get(k) : null,
      setAttribute: (k, v) => attrs.set(k, v), removeAttribute: k => attrs.delete(k),
      classList: { add: k => classes.add(k), remove: k => classes.delete(k), contains: k => classes.has(k) },
      getBoundingClientRect: () => ({ width: 100 }), closest: () => null,
      matches: () => true, replaceChildren(...nodes) { this.childNodes = nodes; },
    };
    elements.push(el);
    return el;
  }
  const body = { addEventListener(name, fn) { (handlers[name] ||= []).push(fn); }, appendChild() {} };
  const document = { body, addEventListener() {}, createElement: () => element('DIV', '') };
  vm.runInNewContext(fs.readFileSync('static/js/interaction-pending.js', 'utf8'), {
    document, window: { setTimeout: fn => { timers.push(fn); return timers.length; }, clearTimeout() {} },
    navigator: { onLine: true },
  });
  return { element, elements, tick: () => timers.splice(0).forEach(fn => fn()),
    emit(name, xhr, elt, extra = {}) {
      const event = { detail: { xhr, elt, ...extra }, preventDefault() { this.defaultPrevented = true; } };
      (handlers[name] || []).forEach(fn => fn(event));
      return event;
    } };
}
test('unrelated swaps and duplicate error events do not finish another request', () => {
  const h = harness(), a = h.element(), b = h.element(), x = {}, y = {};
  h.emit('htmx:beforeRequest', x, a); h.emit('htmx:beforeRequest', y, b); h.tick();
  h.emit('htmx:afterSwap', x, a);
  assert.equal(b.dataset.edifyPending, '1');
  h.emit('htmx:responseError', x, a); h.emit('htmx:afterRequest', x, a);
  assert.equal(b.dataset.edifyPending, '1');
  assert.equal(h.elements.at(-1).classList.contains('is-active'), true);
  h.emit('htmx:afterRequest', y, b);
  assert.equal(h.elements.at(-1).classList.contains('is-active'), false);
});
test('restores original node identities, width and ARIA state after a replaced target', () => {
  const h = harness(), a = h.element(), x = {};
  const icon = { textContent: '' }, label = { textContent: 'Save' };
  a.childNodes = [icon, label]; a.style.width = '8rem'; a.setAttribute('aria-disabled', 'false');
  h.emit('htmx:beforeRequest', x, a);
  assert.equal(a.textContent, 'Saving…');
  h.emit('htmx:afterRequest', x, h.element('DIV'));
  assert.equal(a.childNodes[0], icon); assert.equal(a.childNodes[1], label);
  assert.equal(a.style.width, '8rem'); assert.equal(a.getAttribute('aria-disabled'), 'false');
  assert.equal(a.getAttribute('aria-busy'), null);
});
test('input submit labels restore and keyboard duplicate submission is refused', () => {
  const h = harness(), a = h.element('INPUT', 'Submit'), x = {};
  h.emit('htmx:beforeRequest', x, a);
  assert.equal(a.value, 'Submitting…');
  assert.equal(h.emit('htmx:beforeRequest', {}, a).defaultPrevented, true);
  h.emit('htmx:timeout', x, a); assert.equal(a.value, 'Submit');
});
test('uses the actual form submitter when a form has several actions', () => {
  const h = harness(), a = h.element('BUTTON', 'Approve'), x = {};
  const form = h.element('FORM'); form.contains = n => n === a; form.querySelector = () => null;
  h.emit('htmx:beforeRequest', x, form, { requestConfig: { triggeringEvent: { submitter: a } } });
  assert.equal(a.textContent, 'Approving…');
  h.emit('htmx:afterRequest', x, form); assert.equal(a.textContent, 'Approve');
});
test('a later cancellation releases pending state without waiting for a response', async () => {
  const h = harness(), a = h.element(), x = {};
  const event = h.emit('htmx:beforeRequest', x, a);
  assert.equal(a.dataset.edifyPending, '1');
  event.preventDefault();
  await Promise.resolve();
  assert.equal(a.dataset.edifyPending, undefined);
  assert.equal(a.textContent, 'Save');
});
