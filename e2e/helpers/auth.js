async function completeRequiredAgreements(page) {
  for (let step = 0; step < 4; step += 1) {
    const pathname = new URL(page.url()).pathname;
    if (!pathname.startsWith('/documents/') && !pathname.startsWith('/policy-agreement')) return;

    const agreement = page.getByRole('button', { name: /^(I Accept|I Believe)/ }).first();
    if (await agreement.count()) {
      await Promise.all([
        page.waitForURL(url => new URL(url).pathname !== pathname),
        agreement.click(),
      ]);
      continue;
    }

    /* The agreement centre redirects canonical onboarding documents on load.
     * Give that server redirect one bounded chance before declaring the seeded
     * account unusable; silently crawling the interstitial is a false pass. */
    if (pathname === '/policy-agreement') {
      await page.waitForTimeout(250);
      continue;
    }
    throw new Error(`Required agreement at ${pathname} has no accept action.`);
  }
  throw new Error(`Required agreement loop did not clear: ${page.url()}`);
}

async function signIn(page, email, password, { acceptRequiredAgreements = true } = {}) {
  await page.goto('/login');
  await page.getByLabel('Email address').fill(email);
  await page.locator('#current-password').fill(password);
  await Promise.all([
    page.waitForURL(url => !url.pathname.endsWith('/login') && url.pathname !== '/'),
    page.getByRole('button', { name: 'Access workspace' }).click(),
  ]);
  if (acceptRequiredAgreements) {
    await completeRequiredAgreements(page);
    return;
  }

  const pathname = new URL(page.url()).pathname;
  if (pathname.startsWith('/documents/') || pathname.startsWith('/policy-agreement')) {
    throw new Error(
      `Account requires a state-changing agreement at ${pathname}; ` +
      'production read-only smoke refuses to accept it.'
    );
  }
}

module.exports = { signIn };
