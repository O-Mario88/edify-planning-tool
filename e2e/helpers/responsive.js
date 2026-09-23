// The responsive screen matrix and the one in-page measurement every
// responsive check shares, so the platform crawl and the per-family regression
// spec count a wrapped button, an overflowing page or a crushed table the same
// way.

// The thirteen geometries the responsive standard names (2026-09-23). Touch
// geometries are measured in a touch context (coarse pointer, mobile viewport
// meta honoured); the rest in a desktop context.
const GEOMETRIES = [
  { key: 'mobile-320', width: 320, height: 568, touch: true, band: 'mobile' },
  { key: 'mobile-360', width: 360, height: 800, touch: true, band: 'mobile' },
  { key: 'mobile-390', width: 390, height: 844, touch: true, band: 'mobile' },
  { key: 'mobile-430', width: 430, height: 932, touch: true, band: 'mobile' },
  { key: 'tablet-768', width: 768, height: 1024, touch: true, band: 'tablet' },
  { key: 'tablet-834', width: 834, height: 1194, touch: true, band: 'tablet' },
  { key: 'tablet-1024x768', width: 1024, height: 768, touch: true, band: 'tablet' },
  { key: 'square-1024', width: 1024, height: 1024, touch: true, band: 'tablet' },
  { key: 'laptop-1280', width: 1280, height: 800, touch: false, band: 'desktop' },
  { key: 'laptop-1366', width: 1366, height: 768, touch: false, band: 'desktop' },
  { key: 'desktop-1440', width: 1440, height: 900, touch: false, band: 'desktop' },
  { key: 'desktop-1920', width: 1920, height: 1080, touch: false, band: 'desktop' },
  { key: 'ultrawide-2560', width: 2560, height: 1440, touch: false, band: 'desktop' },
];

const TOUCH_CONTEXT = { isMobile: true, hasTouch: true, deviceScaleFactor: 2 };
const DESKTOP_CONTEXT = { isMobile: false, hasTouch: false, deviceScaleFactor: 1 };

// Runs in the page. Returns counts plus a few examples of each defect, so a
// failure names the control rather than only counting it.
function measureLayout() {
  const EXAMPLES = 4;
  const isShown = element => {
    if (!element.getClientRects().length) return false;
    const rect = element.getBoundingClientRect();
    if (rect.width < 2 || rect.height < 2) return false;
    const style = getComputedStyle(element);
    return style.visibility !== 'hidden' && style.opacity !== '0';
  };
  const hidden = node =>
    Boolean(node.parentElement?.closest('.sr-only, .edify-visually-hidden, .sp-visually-hidden, [hidden], [aria-hidden="true"], template'));

  // The most lines any one run of text inside `element` occupies. A control
  // that stacks a name above a caption is two runs of one line each — a
  // layout, not a wrap — so runs are measured one at a time.
  const linesOf = element => {
    let most = 0;
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if (!node.nodeValue.trim() || hidden(node)) continue;
      const range = document.createRange();
      range.selectNodeContents(node);
      const tops = [...range.getClientRects()]
        .filter(rect => rect.width > 1 && rect.height > 1)
        .map(rect => rect.top)
        .sort((a, b) => a - b);
      let lines = tops.length ? 1 : 0;
      for (let i = 1; i < tops.length; i += 1) {
        if (tops[i] - tops[i - 1] > 4) lines += 1;
      }
      most = Math.max(most, lines);
    }
    return most;
  };
  const label = element =>
    (element.getAttribute('aria-label') || element.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 60);
  const blocky = 'div, p, h1, h2, h3, h4, h5, h6, ul, ol, dl, table, section, article, form';

  // A control whose label wraps is at most two lines of label plus padding;
  // anything taller is a selection card (a theme picker, a record row) whose
  // description is meant to wrap.
  const CARD_HEIGHT = 60;
  const wrapped = (selector, { inlineOnly = false } = {}) => {
    const found = [];
    document.querySelectorAll(selector).forEach(element => {
      if (!isShown(element) || hidden(element.firstChild || element)) return;
      if (inlineOnly && element.querySelector(blocky)) return;
      if (inlineOnly && element.getBoundingClientRect().height > CARD_HEIGHT) return;
      if (linesOf(element) > 1) found.push(label(element));
    });
    return { count: found.length, examples: found.slice(0, EXAMPLES) };
  };

  const main = document.querySelector('main#main-content') || document.querySelector('main');
  const drawer = document.querySelector('#drawer-container');
  const scopes = [main, drawer].filter(Boolean);
  const within = selector => scopes.map(scope => `#${scope.id || 'main-content'} ${selector}`).join(',');

  // Truncated text with no way to read it in full: ellipsis, clipped, and no
  // title or accessible name on it or its control.
  const silentTruncation = [];
  scopes.forEach(scope => scope.querySelectorAll('*').forEach(element => {
    if (element.children.length > 2 || !isShown(element)) return;
    const style = getComputedStyle(element);
    if (style.textOverflow !== 'ellipsis' || element.scrollWidth <= element.clientWidth + 1) return;
    const named = element.closest('[title], [aria-label], [data-full-text]');
    if (!named) silentTruncation.push(`${label(element)} <${element.tagName.toLowerCase()}.${[...element.classList].slice(0, 3).join('.')}>`);
  }));

  // Text below the 12px floor — interface text, and chart or map labels
  // drawn in SVG, counted apart because a chart engine sets its own sizes.
  const tinyText = new Set();
  const tinyChartText = new Set();
  scopes.forEach(scope => {
    const walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const parent = node.parentElement;
      if (!parent || !node.nodeValue.trim() || hidden(node) || !isShown(parent)) continue;
      if (parseFloat(getComputedStyle(parent).fontSize) >= 11.5) continue;
      (parent.closest('svg') ? tinyChartText : tinyText).add(parent);
    }
  });

  // Touch targets under the WCAG 2.2 minimum (24 × 24 CSS px), controls only.
  const smallTargets = [];
  document.querySelectorAll(
    'button, [role="button"], [role="tab"], select, input:not([type="checkbox"]):not([type="radio"]):not([type="hidden"]), a.btn, a[class*="action"]'
  ).forEach(element => {
    // Map regions and chart marks are drawn shapes, not controls.
    if (!isShown(element) || element.closest('p, li > a:only-child, svg')) return;
    const rect = element.getBoundingClientRect();
    if (rect.width < 24 || rect.height < 24) smallTargets.push(label(element) || element.tagName);
  });

  // Tables wider than their region: do they scroll, and does the identity
  // column stay put while they do?
  const tables = { overflowing: 0, scrolling: 0, stickyIdentity: 0, unscrolled: [] };
  scopes.forEach(scope => scope.querySelectorAll('table').forEach(table => {
    if (!isShown(table)) return;
    let region = table.parentElement;
    while (region && region !== scope && !/(auto|scroll)/.test(getComputedStyle(region).overflowX)) {
      region = region.parentElement;
    }
    const scrolls = region && region !== scope;
    const box = scrolls ? region : table.parentElement;
    if (table.scrollWidth <= box.clientWidth + 1) return;
    tables.overflowing += 1;
    if (!scrolls) {
      tables.unscrolled.push(label(table.querySelector('caption, th') || table));
      return;
    }
    tables.scrolling += 1;
    const identity = table.querySelector('tbody tr > :first-child');
    if (identity && getComputedStyle(identity).position === 'sticky') tables.stickyIdentity += 1;
  }));

  const h1 = main?.querySelector('h1');
  const bodyText = main?.querySelector('p');
  return {
    viewport: { width: innerWidth, height: innerHeight },
    documentOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    mainOverflow: main ? main.scrollWidth > main.clientWidth + 1 : false,
    buttons: wrapped(within(
      'button, [role="button"], input[type="submit"], a.btn, a[class*="btn-"], .edify-action-button, .school-record-action, .edify-primary-solid'
    ), { inlineOnly: true }),
    tabs: wrapped(within('[role="tab"], .edify-tab-btn, [data-edify-tab], [class*="tabs__link"]'), { inlineOnly: true }),
    badges: wrapped(within(
      '.edify-badge, .badge, .status-pill, .edify-status-badge, .pill, .planning-indicator, .planning-responsible'
    )),
    navigation: wrapped('.edify-bottom-nav a, .app-sidebar nav a', { inlineOnly: true }),
    tableHeaders: wrapped(within('th')),
    tableCells: wrapped(within('td')),
    silentTruncation: { count: silentTruncation.length, examples: silentTruncation.slice(0, EXAMPLES) },
    tinyText: { count: tinyText.size, examples: [...tinyText].slice(0, EXAMPLES).map(e => `${label(e)} <${e.tagName.toLowerCase()}.${[...e.classList].slice(0, 2).join('.')}>`) },
    tinyChartText: { count: tinyChartText.size, examples: [...tinyChartText].slice(0, EXAMPLES).map(label) },
    smallTargets: { count: smallTargets.length, examples: smallTargets.slice(0, EXAMPLES) },
    tables: { ...tables, unscrolled: tables.unscrolled.slice(0, EXAMPLES) },
    type: {
      h1: h1 ? parseFloat(getComputedStyle(h1).fontSize) : null,
      body: bodyText ? parseFloat(getComputedStyle(bodyText).fontSize) : null,
    },
  };
}

// The defect classes a geometry must be free of. Small touch targets, tiny
// text and silent truncation are reported but graded separately.
const WRAP_KEYS = ['buttons', 'tabs', 'badges', 'navigation', 'tableHeaders', 'tableCells'];

function grade(measure) {
  if (measure.documentOverflow || measure.mainOverflow || measure.tables.unscrolled.length) return 'Fail';
  if (WRAP_KEYS.some(key => measure[key].count > 0)) return 'Partial';
  return 'Pass';
}

async function settle(page) {
  await page.evaluate(() => new Promise(resolve =>
    requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 60)))
  ));
}

module.exports = {
  GEOMETRIES,
  TOUCH_CONTEXT,
  DESKTOP_CONTEXT,
  WRAP_KEYS,
  measureLayout,
  grade,
  settle,
};
