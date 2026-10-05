/*
 * A table's columns never run into each other.
 *
 * Owner, 2026-10-05, of the Planning list: "make sure the columns are not
 * overlapping into each other ... and any other table in the platform with
 * that issue". A cluster's name ("Greater Abako Cluster") ran out of the
 * Cluster column and across the Visit Plan Status chip beside it.
 *
 * Every table is held to one line and may not clip a cell (consistency.css,
 * EVERY TABLE STAYS ON ONE LINE): a column grows to what it holds and the
 * table scrolls sideways. A table that FIXES its column widths cannot grow a
 * column, so there a long value has nowhere to go but over its neighbour —
 * unless the cell is given the weight to end in an ellipsis instead. Two
 * tables fixed their widths without it:
 *
 *  - Planning's Cluster column. Its own ellipsis rule lost to the one-line
 *    rule's !important.
 *  - Core Schools' Core Trained, Core Graduate and Champion tables, which
 *    fixed seven columns by percentage and expected to wrap. They are
 *    ordinary tables again and size to what they hold.
 *
 * Asserted on the rendered geometry with a value longer than any the seed
 * holds: after it is written into a cell, no text in the table may paint past
 * the right edge of its own cell unless something clips it there.
 */
const { test, expect } = require('@playwright/test');
const { signIn } = require('./helpers/auth');

const LONG = 'Greater Abako and Alebtong Municipal Cluster of Schools';

/** Text that paints past its own cell, per table: [{ table, column, text, by }]. */
function spills() {
  const out = [];
  const clipped = (el, cell) => {
    for (let node = el; node; node = node.parentElement) {
      if (getComputedStyle(node).overflowX !== 'visible') return true;
      if (node === cell) break;
    }
    return false;
  };
  const unseen = (el, cell) => {
    for (let node = el; node; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (style.visibility === 'hidden' || style.opacity === '0') return true;
      if (node !== cell && (style.position === 'absolute' || style.position === 'fixed')) return true;
      const closed = node.parentElement && node.parentElement.closest('details:not([open])');
      if (closed && cell.contains(closed) && !node.closest('summary')) return true;
      if (node === cell) break;
    }
    return false;
  };
  for (const table of document.querySelectorAll('main table')) {
    if (!table.getClientRects().length) continue;
    const headings = table.tHead && table.tHead.rows[0] ? [...table.tHead.rows[0].cells] : [];
    for (const row of [...table.rows].slice(0, 40)) {
      for (const cell of row.cells) {
        if (cell.colSpan > 1 || !cell.getClientRects().length) continue;
        const box = cell.getBoundingClientRect();
        const walker = document.createTreeWalker(cell, NodeFilter.SHOW_TEXT);
        for (let text = walker.nextNode(); text; text = walker.nextNode()) {
          const parent = text.parentElement;
          if (!text.nodeValue.trim() || !parent.getClientRects().length) continue;
          if (parent.closest('.sr-only, .edify-visually-hidden, [role="menu"], .row-menu__list')) continue;
          const range = document.createRange();
          range.selectNodeContents(text);
          const by = range.getBoundingClientRect().right - box.right;
          if (by > 2 && !clipped(parent, cell) && !unseen(parent, cell)) {
            out.push({
              table: table.getAttribute('aria-label') || table.className,
              column: headings[cell.cellIndex] ? headings[cell.cellIndex].textContent.trim() : String(cell.cellIndex),
              text: text.nodeValue.trim().slice(0, 40),
              by: Math.round(by),
            });
          }
        }
      }
    }
  }
  return out;
}

/** Write a long value into the first few body cells under each named heading. */
function lengthen({ columns, value }) {
  let written = 0;
  for (const table of document.querySelectorAll('main table')) {
    if (!table.getClientRects().length || !table.tHead || !table.tHead.rows[0]) continue;
    const wanted = [...table.tHead.rows[0].cells]
      .filter((heading) => columns.includes(heading.textContent.trim().toLowerCase()))
      .map((heading) => heading.cellIndex);
    const rows = [...table.tBodies].flatMap((body) => [...body.rows])
      .filter((row) => row.getClientRects().length && [...row.cells].every((cell) => cell.colSpan === 1));
    for (const row of rows.slice(0, 5)) {
      for (const index of wanted) {
        const cell = row.cells[index];
        if (!cell) continue;
        const walker = document.createTreeWalker(cell, NodeFilter.SHOW_TEXT);
        for (let text = walker.nextNode(); text; text = walker.nextNode()) {
          if (text.nodeValue.trim() && text.parentElement.getClientRects().length) {
            text.nodeValue = value;
            written += 1;
            break;
          }
        }
      }
    }
  }
  return written;
}

const PAGES = [
  { path: '/planning', table: 'table.school-plan-table--selectable', columns: ['cluster', 'school name'] },
  { path: '/core-schools', table: 'table.core-lifecycle-table', columns: ['school name', 'district', 'planned activities'] },
];

for (const viewport of [{ width: 1440, height: 950 }, { width: 1100, height: 800 }, { width: 390, height: 844 }]) {
  test(`no table column runs into the next at ${viewport.width}px`, async ({ page }) => {
    test.setTimeout(120_000);
    await signIn(page, 'cceo@edify.org', 'edify', { acceptRequiredAgreements: false });
    await page.setViewportSize(viewport);
    for (const target of PAGES) {
      await page.goto(target.path);
      await expect(page.locator(`${target.table} tbody tr`).first(), `${target.path} lists schools`).toBeVisible();
      await page.waitForTimeout(600);
      expect(await page.evaluate(spills), `${target.path} as it loads`).toEqual([]);

      const written = await page.evaluate(lengthen, { columns: target.columns, value: LONG });
      expect(written, `${target.path}: a long value was written into its columns`).toBeGreaterThan(0);
      await page.waitForTimeout(200);
      expect(await page.evaluate(spills), `${target.path} with a long value`).toEqual([]);
    }
  });
}
