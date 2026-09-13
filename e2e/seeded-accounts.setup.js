const { test } = require('@playwright/test');
const { signIn } = require('./helpers/auth');
const { localRoleAccounts, isDisposableTarget } = require('./helpers/accounts');

// Journeys sign in with acceptRequiredAgreements:false and fail on the
// first-login agreement gate. They used to pass only because the role route
// audit — alphabetically first, Chromium only — happened to accept every
// account's agreements earlier in the same database, so a spec run on its own,
// a shard, or a non-Chromium project met the gate. Every browser project
// depends on this project instead, and it runs once per run (and per shard).
test.use({ video: 'off' });
test.skip(({ baseURL }) => !isDisposableTarget(baseURL), 'Only a disposable local database has its agreements accepted.');

const password = process.env.EDIFY_E2E_PASSWORD || 'edify';

for (const [accountRole, , email] of localRoleAccounts) {
  test(`${accountRole} account has cleared its first-login agreements`, async ({ page }) => {
    await signIn(page, email, password, { acceptRequiredAgreements: true });
  });
}
