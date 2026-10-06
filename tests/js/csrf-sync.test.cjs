// A page that was open before a sign-in holds a token Django has since
// replaced (production, 2026-10-05: "CSRF verification failed"). csrf-sync.js
// copies the cookie's token over the rendered ones; these run the real script
// against a page whose cookie changes underneath it.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');

function setup(cookie) {
  const handlers = { document: {}, window: {} };
  const field = { value: 'rendered-before-sign-in' };
  const meta = { content: 'rendered-before-sign-in', setAttribute(k, v) { this[k] = v; } };
  const body = { attrs: {}, setAttribute(k, v) { this.attrs[k] = v; } };
  const document = {
    cookie, body, hidden: false,
    querySelectorAll: () => [field],
    querySelector: () => meta,
    addEventListener(name, fn) { handlers.document[name] = fn; },
  };
  const window = { addEventListener(name, fn) { handlers.window[name] = fn; } };
  vm.runInNewContext(fs.readFileSync('static/js/csrf-sync.js', 'utf8'), { document, window });
  return { document, field, meta, body, handlers };
}

test('a sign-in completed in another tab reaches this one when it is returned to', () => {
  const page = setup('csrftoken=first');
  page.handlers.document.DOMContentLoaded();
  assert.equal(page.field.value, 'first');

  page.document.cookie = 'edify_email=a%40b.c; csrftoken=second';
  page.handlers.window.focus();
  assert.equal(page.field.value, 'second');
  assert.equal(page.meta.content, 'second');
  assert.equal(page.body.attrs['hx-headers'], '{"X-CSRFToken":"second"}');

  page.document.cookie = 'csrftoken=third';
  page.handlers.document.visibilitychange();
  assert.equal(page.field.value, 'third');
});

test('a native form takes the current token as it is submitted', () => {
  const page = setup('csrftoken=first');
  page.document.cookie = 'csrftoken=second';
  const form = { method: 'post', querySelectorAll: () => [page.field] };
  page.handlers.document.submit({ target: form });
  assert.equal(page.field.value, 'second');
});

test('a page with no cookie keeps the token it was rendered with', () => {
  const page = setup('');
  page.handlers.window.pageshow();
  assert.equal(page.field.value, 'rendered-before-sign-in');
});

test('the sign-in pages load it', () => {
  const layout = fs.readFileSync('templates/layouts/login.html', 'utf8');
  assert.ok(layout.indexOf('js/csrf-sync.js') > -1);
  assert.ok(layout.indexOf('js/csrf-sync.js') < layout.indexOf('js/login.js'));
});
