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

/* The sign-in form is limited per client address (RATE_LIMIT_LOGIN_PER_MIN,
 * 10 a minute by default, counted in fixed one-minute windows). A browser run
 * signs in from one address far more often than a person does, and a refused
 * attempt used to surface twenty seconds later as a misleading "navigated to
 * /login" timeout. Wait out the window instead, a bounded number of times. */
const THROTTLED_ATTEMPTS = 3;
const NAVIGATION_BUDGET_MS = 20_000;

async function submitCredentials(page, email, password) {
  await page.goto('/login');
  await page.getByLabel('Email address').fill(email);
  await page.locator('#current-password').fill(password);
  // Submitting navigates to the landing page and waits for it, so both waits
  // get the navigation budget (playwright.config.js), not the ten-second action
  // budget: the first sign-in on a cold server, or a role dashboard rendered
  // cold on a shared runner, can need more.
  const [response] = await Promise.all([
    page.waitForResponse(response =>
      response.request().method() === 'POST' && new URL(response.url()).pathname === '/login',
      { timeout: NAVIGATION_BUDGET_MS }),
    page.getByRole('button', { name: 'Access workspace' }).click({ timeout: NAVIGATION_BUDGET_MS }),
  ]);
  return response.status();
}

async function signIn(page, email, password, { acceptRequiredAgreements = true } = {}) {
  for (let attempt = 1; ; attempt += 1) {
    if ((await submitCredentials(page, email, password)) !== 429) break;
    if (attempt === THROTTLED_ATTEMPTS) {
      throw new Error(`Sign-in for ${email} was rate limited ${attempt} times; raise RATE_LIMIT_LOGIN_PER_MIN for this server.`);
    }
    await page.waitForTimeout(60_000 - (Date.now() % 60_000) + 1_000);
  }
  await page.waitForURL(url => !url.pathname.endsWith('/login') && url.pathname !== '/');
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
