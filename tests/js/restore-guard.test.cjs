// A page brought back from the back/forward cache shows nothing until the
// server says this browser is still signed in (static/js/restore-guard.js,
// 2026-10-24). Pages were already allowed into that cache and Home joined
// them, so on a shared phone "Back" after signing out could otherwise show
// the last person's page.
const { test } = require('node:test');
const assert = require('node:assert/strict');

const { check } = require('../../static/js/restore-guard.js');

function fakeWindow(answer) {
  const attrs = new Set();
  const calls = [];
  const win = {
    document: {
      documentElement: {
        setAttribute: name => attrs.add(name),
        removeAttribute: name => attrs.delete(name),
      },
    },
    location: {
      pathname: '/my-plan',
      search: '?status=overdue',
      replace: to => calls.push(['replace', to]),
    },
    fetch: async url => {
      calls.push(['fetch', url]);
      if (answer instanceof Error) throw answer;
      return { ok: true, json: async () => answer };
    },
  };
  return { win, attrs, calls };
}

test('a restored page stays hidden until the session is confirmed, then shows', async () => {
  const { win, attrs, calls } = fakeWindow({ signedIn: true });
  const pending = check(win);
  assert.ok(attrs.has('data-restore-check'), 'hidden while asking');
  await pending;
  assert.equal(attrs.has('data-restore-check'), false);
  assert.deepEqual(calls, [['fetch', '/login/state']]);
});

test('a restored page of a session that has ended goes to sign in instead', async () => {
  const { win, attrs, calls } = fakeWindow({ signedIn: false });
  await check(win);
  assert.ok(attrs.has('data-restore-check'), 'never shown');
  assert.deepEqual(calls[1], ['replace', '/login']);
});

test('with no network the page is shown as it was: there is nothing to ask', async () => {
  const { win, attrs } = fakeWindow(new Error('offline'));
  await check(win);
  assert.equal(attrs.has('data-restore-check'), false);
});
