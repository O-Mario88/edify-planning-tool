/**
 * /schools on the Next.js app against /schools on the existing web, for the
 * same seed account: the visible header, filters, tabs, list and pager, the
 * order of the page's blocks, and screenshots of both. Development only.
 */
import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';

const DJANGO = process.env.EDIFY_COMPARE_DJANGO_URL ?? 'http://localhost:8010';
const NEXT = process.env.EDIFY_COMPARE_WEB_URL ?? 'http://localhost:3000';
const GATEWAY = process.env.EDIFY_COMPARE_GATEWAY_URL ?? 'http://127.0.0.1:8090';
const PASSWORD = process.env.EDIFY_COMPARE_PASSWORD ?? '';
const OUT = process.env.EDIFY_COMPARE_OUT ?? 'test-results';
const ACCOUNTS = (process.env.EDIFY_COMPARE_ACCOUNTS ?? 'cceo@edify.org').split(',');
const QUERIES = (process.env.EDIFY_COMPARE_QUERIES ?? '|tab=unclustered|page=2').split('|');

for (const url of [DJANGO, NEXT, GATEWAY]) {
  const host = new URL(url).hostname;
  if (!['localhost', '127.0.0.1'].includes(host)) throw new Error(`Refusing to compare against ${url}: development only`);
}

interface PageReading {
  header: string[];
  buttons: string[];
  filters: string[];
  tabs: string[];
  listed: string;
  rows: string[];
  pager: string[];
  blocks: string[];
}

const squash = (text: string | null | undefined) => (text ?? '').replace(/\s+/g, ' ').trim();

async function signInDjango(page: Page, email: string) {
  await page.goto(`${DJANGO}/login`);
  await page.getByLabel('Email address').fill(email);
  await page.locator('#current-password').fill(PASSWORD);
  await Promise.all([
    page.waitForURL((url) => !url.pathname.endsWith('/login')),
    page.getByRole('button', { name: 'Access workspace' }).click(),
  ]);
}

async function signInNext(page: Page, email: string) {
  await page.goto(`${NEXT}/login`);
  await page.getByLabel('Email address').fill(email);
  await page.locator('#current-password').fill(PASSWORD);
  await Promise.all([
    page.waitForURL((url) => !url.pathname.endsWith('/login')),
    page.getByRole('button', { name: 'Access workspace' }).click(),
  ]);
}

/** The gateway's own answer, asked directly: the rows the page must show, in order. */
async function gatewayRows(email: string, query: string): Promise<string[]> {
  const call = async (method: string, body: unknown, token = '') => {
    const response = await fetch(`${GATEWAY}/${method}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error(`${method}: HTTP ${response.status}`);
    return response.json();
  };
  const signIn = await call('edify.identity.v1.SignInService/SignIn', { email, password: PASSWORD });
  const params = Object.fromEntries(new URLSearchParams(query));
  const answer = await call(
    'edify.screens.v1.SchoolDirectoryScreenService/GetSchoolDirectory',
    { tab: params.tab ?? '', page: Number(params.page ?? 0) },
    signIn.session.accessToken,
  );
  return (answer.schools ?? []).map((school: { schoolId: string }) => school.schoolId);
}

async function readDjango(page: Page): Promise<PageReading> {
  return page.evaluate(() => {
    const q = (s: string, root: ParentNode = document) => Array.from(root.querySelectorAll<HTMLElement>(s));
    const t = (e: Element | null | undefined) => (e?.textContent ?? '').replace(/\s+/g, ' ').trim();
    const selectText = (s: HTMLSelectElement) => t(s.selectedOptions[0]);
    const blocks: string[] = [];
    if (document.querySelector('.edify-page-header')) blocks.push('header');
    if (document.querySelector('#filters-form')) blocks.push('filters');
    if (document.querySelector('#kpi-cards-row .context-metrics')) blocks.push('strip');
    if (document.querySelector('[role=tablist][aria-label="School directory views"]')) blocks.push('tabs');
    if (document.querySelector('.school-directory-listbar')) blocks.push('table');
    if (document.querySelector('.school-directory-pagination')) blocks.push('pager');
    return {
      header: [t(document.querySelector('.edify-page-eyebrow')), t(document.querySelector('.edify-page-title')), t(document.querySelector('.edify-page-header__description'))],
      buttons: q('.edify-page-header__controls > a, .edify-page-header__controls > button, .edify-page-header__controls > div > button').map(t),
      filters: q('#filters-form select').map((s) => `${s.getAttribute('aria-label')}=${selectText(s as HTMLSelectElement)}`),
      tabs: q('[role=tablist][aria-label="School directory views"] [role=tab]').filter((e) => e.checkVisibility()).map(t),
      listed: t(document.querySelector('.school-directory-listbar__count')),
      rows: q('.school-directory-row').map((row) => {
        const id = t(row.querySelector('.school-record-row__school-id')).replace(/^School ID /, '');
        const facts = q('[data-fact] dd', row).map(t);
        const visit = t(row.querySelector('[data-visit-status] .edify-badge'));
        return [id, t(row.querySelector('.school-record-row__title')), facts[0] ?? '', facts[2] ?? '', visit].join(' | ');
      }),
      pager: [t(document.querySelector('.school-directory-pagination > div')), ...q('.school-directory-pagination [aria-current=page], .school-directory-pagination .flex.items-center.gap-1.text-\\[12px\\] > *').map(t)],
      blocks,
    };
  });
}

async function readNext(page: Page): Promise<PageReading> {
  return page.evaluate(() => {
    const q = (s: string, root: ParentNode = document) => Array.from(root.querySelectorAll<HTMLElement>(s));
    const t = (e: Element | null | undefined) => (e?.textContent ?? '').replace(/\s+/g, ' ').trim();
    const header = document.querySelector('[data-block=header]');
    return {
      header: q('p, h1', header ?? document).map(t),
      buttons: q('[data-block=header] a, [data-block=header] button').map(t),
      filters: q('[data-block=filters] select').map((s) => `${s.getAttribute('aria-label')}=${t((s as HTMLSelectElement).selectedOptions[0])}`),
      tabs: q('[data-block=tabs] [role=tab]').filter((e) => e.checkVisibility()).map(t),
      listed: t(document.querySelector('[data-block=table] .ml-auto')),
      rows: q('li[data-row]').map((row) => {
        const fact = (name: string) => t(row.querySelector(`[data-fact=${name}]`));
        return [row.dataset.row ?? '', t(row.querySelector('h2')), fact('district'), fact('cluster'), fact('visit')].join(' | ');
      }),
      pager: [t(document.querySelector('[data-block=pager] p')), ...q('[data-block=pager] div > *').map(t).filter((x) => x !== 'Prev' && x !== 'Next')],
      blocks: q('[data-block]').map((e) => e.dataset.block ?? ''),
    };
  });
}

function compare(label: string, django: unknown, next: unknown): boolean {
  const same = JSON.stringify(django) === JSON.stringify(next);
  console.log(`  ${same ? 'SAME     ' : 'DIFFERENT'} ${label}`);
  if (!same) {
    console.log(`    django: ${JSON.stringify(django).slice(0, 600)}`);
    console.log(`    next:   ${JSON.stringify(next).slice(0, 600)}`);
  }
  return same;
}

test.describe.configure({ mode: 'serial' });

for (const email of ACCOUNTS) {
  test(`/schools matches the existing web for ${email}`, async ({ browser }, info) => {
    test.skip(!PASSWORD, 'EDIFY_COMPARE_PASSWORD is not set');
    const viewport = info.project.use.viewport ?? { width: 1440, height: 1000 };
    const width = viewport.width;
    const django = await browser.newPage({ viewport });
    const next = await browser.newPage({ viewport });
    await signInDjango(django, email);
    await signInNext(next, email);
    const results: boolean[] = [];
    for (const query of QUERIES) {
      const suffix = query ? `?${query}` : '';
      await django.goto(`${DJANGO}/schools${suffix}`, { waitUntil: 'networkidle' });
      await next.goto(`${NEXT}/schools${suffix}`, { waitUntil: 'networkidle' });
      const tag = `${email.split('@')[0]}_${width}_${query.replace(/[^a-z0-9]+/gi, '-') || 'open'}`;
      await django.screenshot({ path: `${OUT}/agent10_compare_django_${tag}.png`, fullPage: false });
      await next.screenshot({ path: `${OUT}/agent10_compare_next_${tag}.png`, fullPage: false });
      const a = await readDjango(django);
      const b = await readNext(next);
      console.log(`${email} at ${width}px, /schools${suffix}`);
      results.push(compare('header text', a.header, b.header));
      results.push(compare('filters (label=selected)', a.filters, b.filters));
      results.push(compare('tabs and counts (the visible ones; a phone folds the rest into More)', a.tabs, b.tabs));
      results.push(compare('listed count', squash(a.listed).toUpperCase(), squash(b.listed).toUpperCase()));
      const nameOf = (row: string) => row.split(' | ')[1] ?? '';
      const idOf = (row: string) => row.split(' | ')[0] ?? '';
      results.push(compare(`row names in order (${a.rows.length} vs ${b.rows.length} rows)`, a.rows.map(nameOf), b.rows.map(nameOf)));
      const djangoById = new Map(a.rows.map((row) => [idOf(row), row]));
      const shared = b.rows.filter((row) => djangoById.has(idOf(row)));
      results.push(compare(`rows of the ${shared.length} schools on both pages: id | name | district | cluster | visit`, shared.map((row) => djangoById.get(idOf(row))), shared));
      results.push(compare('the Next.js rows are the gateway answer, in order (school IDs)', await gatewayRows(email, query), b.rows.map(idOf)));
      compare(
        'which school of a same-name group sits on this page and in what order (name ties are not ordered on either side)',
        a.rows.map(idOf),
        b.rows.map(idOf),
      );
      results.push(compare('pager (summary and page numbers)', a.pager.filter((x) => !/^Rows per page|^\d+( \d+)+$/.test(x)), b.pager));
      compare('rows-per-page chooser (known gap: the contract has no page size)', a.pager.filter((x) => /^Rows per page|^\d+( \d+)+$/.test(x)), []);
      compare('header buttons (known gap: Upload Center / Add SSA Score are not in the contract)', a.buttons, b.buttons);
      compare('block order (known gap: the KPI strip is not in the contract)', a.blocks, b.blocks);
    }
    await django.close();
    await next.close();
    expect(results.every(Boolean), 'every compared part is the same').toBe(true);
  });
}
