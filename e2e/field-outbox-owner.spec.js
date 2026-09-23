const { test, expect } = require('@playwright/test');
const { signIn } = require('./helpers/auth');

/* The offline outbox replays a saved field action only under the account that
 * saved it. IndexedDB outlives a sign-out, so on a phone shared by two
 * officers the second one's first page load used to POST the first one's
 * saved "start/complete activity" with the second one's session and CSRF
 * token (frontend audit, 2026-09-23). Entries saved before owners were
 * recorded keep their old behaviour so no queued work is stranded by a
 * deploy.
 */
test('saved field actions replay only for the account that saved them', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-desktop', 'IndexedDB behaviour is exercised once.');
  await signIn(page, 'cceo@edify.org', 'edify', { acceptRequiredAgreements: false });
  await page.goto('/dashboard');
  await page.evaluate(() => EdifyFieldOutbox.ready);
  const owner = await page.evaluate(() => document.body.getAttribute('data-edify-outbox-owner'));
  expect(owner).toMatch(/^[0-9a-f]{24}$/);

  const requests = [];
  await page.route(/\/activities\/owner-/, route => {
    requests.push(new URL(route.request().url()).pathname);
    return route.fulfill({ status: 200, body: 'ok' });
  });
  await page.evaluate(async owner => {
    const db = await new Promise((resolve, reject) => {
      const r = indexedDB.open('edify-outbox', 1);
      r.onsuccess = () => resolve(r.result); r.onerror = () => reject(r.error);
    });
    await new Promise((resolve, reject) => {
      const tx = db.transaction('requests', 'readwrite'), store = tx.objectStore('requests');
      const base = { label: 'Start activity', createdAt: Date.now(), fields: [], status: 'queued', message: '' };
      store.put({ ...base, owner, path: '/activities/owner-mine/start/action', subject: 'Mine' });
      store.put({ ...base, owner: 'someone-else-00000000000', path: '/activities/owner-theirs/start/action', subject: 'Theirs' });
      store.put({ ...base, path: '/activities/owner-legacy/start/action', subject: 'Legacy' });
      tx.oncomplete = resolve; tx.onerror = () => reject(tx.error);
    });
    db.close();
    await EdifyFieldOutbox.replay();
  }, owner);

  expect(requests).toEqual(['/activities/owner-mine/start/action', '/activities/owner-legacy/start/action']);
  const remaining = await page.evaluate(async () => {
    const db = await new Promise(resolve => { const r = indexedDB.open('edify-outbox', 1); r.onsuccess = () => resolve(r.result); });
    const all = await new Promise(resolve => { const r = db.transaction('requests').objectStore('requests').getAll(); r.onsuccess = () => resolve(r.result); });
    db.close();
    return all.map(entry => entry.subject);
  });
  // The other officer's action is kept for them, not sent and not dropped.
  expect(remaining).toEqual(['Theirs']);
  await expect(page.locator('[data-field-outbox-count]').first()).toHaveText('0');
});
