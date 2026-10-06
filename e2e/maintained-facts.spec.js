// Five things the stylesheets used to ask of an ancestor with `:has()` are
// kept on that ancestor as attributes by micro-ux.js (audit, 2026-10-05: asked
// with `:has()` and answered for any element beneath, they made a browser
// restyle a whole phone page whenever anything was added to it):
//
//   table[data-edify-select-column]       a body row starts with a selection box
//   tr > [data-edify-box-cell]            the row's first cell holds a box itself
//   .edify-head-row[data-edify-head-run]  the heading row holds no block
//   [data-edify-tablist][data-edify-beside-link]   the rail's next element is a.btn
//   search[data-edify-has-submit]         the search box holds its submit button
//                                         (layouts/shell.html writes this one too)
//
// An attribute does not follow the page by itself the way `:has()` does. This
// holds each one to the selector it replaced while the page is changed under
// it: before the next frame, every time.
const { test, expect } = require('@playwright/test');
const { signIn } = require('./helpers/auth');

const password = process.env.EDIFY_E2E_PASSWORD || 'edify';

test.use({ video: 'off', trace: 'off', serviceWorkers: 'block' });

// What each attribute must equal, as the selector the rule carried.
const FACTS = `(() => {
  const BOX = ':is(input[type="checkbox"], input[type="radio"], .edify-table-choice)';
  const facts = [
    ['table', ':has(> tbody > tr > :first-child > ' + BOX + ', > tbody > tr > :first-child > label > :is(input[type="checkbox"], input[type="radio"]))', 'data-edify-select-column', false],
    // Asked of every cell, so a mark left on a cell that is no longer the first is caught too.
    ['table > :is(thead, tbody, tfoot) > tr > *', ':first-child:has(> ' + BOX + ')', 'data-edify-box-cell', false],
    ['.edify-head-row', ':has(> :is(p, div, ul, dl, form))', 'data-edify-head-run', true],
    ['[data-edify-tablist]', ':has(+ a.btn)', 'data-edify-beside-link', false],
    ['search, .edify-topbar__search', ':has(.edify-search-submit)', 'data-edify-has-submit', false],
  ];
  window.disagreements = () => {
    const wrong = [];
    for (const [anchor, has, attribute, inverted] of facts) {
      for (const element of document.querySelectorAll(anchor)) {
        const truth = element.matches(has) !== inverted;
        if (truth !== element.hasAttribute(attribute)) wrong.push(attribute + ' on <' + element.tagName.toLowerCase() + ' id="' + element.id + '"> is ' + !truth);
      }
    }
    return wrong;
  };
  // The observer that keeps the facts runs in the same turn as the change; one turn later everything must agree.
  window.changed = async (change) => { change(); await new Promise((resolve) => setTimeout(resolve, 0)); return window.disagreements(); };
})();`;

test('the facts kept for the stylesheets follow the page', async ({ page }) => {
  await page.addInitScript(FACTS);
  await signIn(page, 'cceo1@edify.org', password);
  await page.goto('/my-plan');
  await page.waitForLoadState('load');
  await page.waitForTimeout(1500);
  expect(await page.evaluate(() => window.disagreements()), 'as the page opens').toEqual([]);

  const result = await page.evaluate(async () => {
    const steps = [];
    const step = async (name, change, expectAttribute) => {
      const wrong = await window.changed(change);
      steps.push({ name, wrong, attribute: expectAttribute ? expectAttribute() : null });
    };
    const host = document.querySelector('main');

    // A table: a selection box in the first cell of a body row, and only there.
    const table = document.createElement('table');
    table.id = 'fact-table';
    table.innerHTML = '<thead><tr><th>Name</th><th>Value</th></tr></thead><tbody><tr><td><span>A</span></td><td>1</td></tr></tbody>';
    const marked = () => table.hasAttribute('data-edify-select-column');
    await step('a table with no selection box', () => host.appendChild(table), marked);
    await step('a box in a later cell', () => { table.tBodies[0].rows[0].cells[1].innerHTML = '<input type="checkbox">'; }, marked);
    await step('a row that starts with a box', () => { table.tBodies[0].insertAdjacentHTML('beforeend', '<tr><td><input type="checkbox"></td><td>2</td></tr>'); }, marked);
    await step('that row removed', () => table.tBodies[0].rows[1].remove(), marked);
    await step('a radio inside its label', () => { table.tBodies[0].insertAdjacentHTML('afterbegin', '<tr><td><label><input type="radio"></label></td><td>3</td></tr>'); }, marked);
    await step('the body replaced', () => { table.tBodies[0].innerHTML = '<tr><td>plain</td><td>4</td></tr>'; }, marked);
    await step('a box in the header only', () => { table.tHead.rows[0].cells[0].innerHTML = '<input type="checkbox">'; }, marked);
    await step('a marked choice in the first cell', () => { table.tBodies[0].rows[0].cells[0].innerHTML = '<span class="edify-table-choice"></span>'; }, marked);

    // A cell: the first of its row, holding a box itself. The header's does since two steps ago, the body's since one.
    const lead = table.tBodies[0].rows[0];
    const cell = lead.cells[0];
    const holds = () => cell.hasAttribute('data-edify-box-cell');
    await step('the first cell of a row, holding a choice', () => {}, () => `${holds()}:${table.tHead.rows[0].cells[0].hasAttribute('data-edify-box-cell')}`);
    await step('a cell put in front of it', () => lead.insertAdjacentHTML('afterbegin', '<td>first now</td>'), holds);
    await step('that cell removed', () => lead.cells[0].remove(), holds);
    await step('the choice taken out', () => cell.firstElementChild.remove(), holds);
    await step('a box put in by a script', () => { const input = document.createElement('input'); input.type = 'checkbox'; cell.appendChild(input); }, holds);
    await step('the box moved inside a plain label', () => { cell.innerHTML = '<label><input type="checkbox"></label>'; }, holds);
    await step('a footer row that starts with a box', () => table.insertAdjacentHTML('beforeend', '<tfoot><tr><td><input type="radio"></td><td>total</td></tr></tfoot>'), () => table.tFoot.rows[0].cells[0].hasAttribute('data-edify-box-cell'));

    // A heading row: micro-ux marks it; a block among its children ends the run.
    const row = document.createElement('div');
    row.id = 'fact-row';
    row.className = 'flex';
    row.innerHTML = '<h3>Cluster meetings</h3><span>12</span>';
    host.appendChild(row);
    window.EdifyMicroUX.enhance(row);
    const run = () => row.classList.contains('edify-head-row') + ':' + row.hasAttribute('data-edify-head-run');
    await step('a heading row of a title and a count', () => {}, run);
    await step('a paragraph added to it', () => row.insertAdjacentHTML('beforeend', '<p>Planned this year</p>'), run);
    await step('the paragraph removed', () => row.lastElementChild.remove(), run);
    await step('a list added to it', () => row.insertAdjacentHTML('afterbegin', '<ul><li>x</li></ul>'), run);
    await step('the list removed', () => row.firstElementChild.remove(), run);

    // A tab rail: an action as its next element, and not otherwise.
    const toolbar = document.createElement('div');
    toolbar.className = 'edify-view-toolbar';
    toolbar.innerHTML = '<nav data-edify-tablist id="fact-rail"><a data-edify-tab href="#">One</a><a data-edify-tab href="#">Two</a></nav>';
    const rail = toolbar.firstElementChild;
    const beside = () => rail.hasAttribute('data-edify-beside-link');
    await step('a rail alone', () => host.appendChild(toolbar), beside);
    await step('an action after it', () => rail.insertAdjacentHTML('afterend', '<a class="btn" href="#">Open</a>'), beside);
    await step('something between them', () => rail.insertAdjacentHTML('afterend', '<span>or</span>'), beside);
    await step('that removed again', () => rail.nextElementSibling.remove(), beside);
    await step('a link that is not a button', () => { rail.nextElementSibling.remove(); rail.insertAdjacentHTML('afterend', '<a href="#">Open</a>'); }, beside);
    await step('the rail moved in front of an action', () => { toolbar.insertAdjacentHTML('beforeend', '<a class="btn" href="#">Export</a>'); toolbar.insertBefore(rail, toolbar.lastElementChild); }, beside);

    // A search box: its submit button anywhere inside it, and not otherwise.
    const box = document.createElement('search');
    box.id = 'fact-search';
    box.innerHTML = '<form><input type="search"></form>';
    const submits = () => box.hasAttribute('data-edify-has-submit');
    await step('a search box with no button', () => host.appendChild(box), submits);
    await step('a submit button in its form', () => box.firstElementChild.insertAdjacentHTML('beforeend', '<button class="edify-search-submit" type="submit"></button>'), submits);
    await step('the button removed', () => box.querySelector('.edify-search-submit').remove(), submits);
    await step('a button of another kind', () => box.insertAdjacentHTML('beforeend', '<button type="submit">Go</button>'), submits);
    await step('the form replaced by one with the button deep inside', () => { box.innerHTML = '<form><input type="search"><span><button class="edify-search-submit"></button></span></form>'; }, submits);
    const borrowed = document.createElement('div');
    borrowed.id = 'fact-borrowed';
    borrowed.className = 'edify-topbar__search';
    const borrows = () => borrowed.hasAttribute('data-edify-has-submit');
    await step('an element that only borrows the class, holding the search box', () => { host.appendChild(borrowed); borrowed.appendChild(box); }, () => `${borrows()}:${submits()}`);
    await step('the button removed from inside both', () => box.querySelector('.edify-search-submit').remove(), () => `${borrows()}:${submits()}`);

    table.remove(); row.remove(); toolbar.remove(); borrowed.remove();
    return steps;
  });

  for (const step of result) expect(step.wrong, step.name).toEqual([]);
  const attribute = Object.fromEntries(result.map((step) => [step.name, step.attribute]));
  // And the answers are the ones the page's contents call for (the check above only says they agree with the selector).
  expect(attribute['a table with no selection box']).toBe(false);
  expect(attribute['a box in a later cell']).toBe(false);
  expect(attribute['a row that starts with a box']).toBe(true);
  expect(attribute['that row removed']).toBe(false);
  expect(attribute['a radio inside its label']).toBe(true);
  expect(attribute['the body replaced']).toBe(false);
  expect(attribute['a box in the header only']).toBe(false);
  expect(attribute['a marked choice in the first cell']).toBe(true);
  expect(attribute['the first cell of a row, holding a choice']).toBe('true:true');
  expect(attribute['a cell put in front of it']).toBe(false);
  expect(attribute['that cell removed']).toBe(true);
  expect(attribute['the choice taken out']).toBe(false);
  expect(attribute['a box put in by a script']).toBe(true);
  expect(attribute['the box moved inside a plain label']).toBe(false);
  expect(attribute['a footer row that starts with a box']).toBe(true);
  expect(attribute['a heading row of a title and a count']).toBe('true:true');
  expect(attribute['a paragraph added to it']).toBe('true:false');
  expect(attribute['the paragraph removed']).toBe('true:true');
  expect(attribute['a list added to it']).toBe('true:false');
  expect(attribute['the list removed']).toBe('true:true');
  expect(attribute['a rail alone']).toBe(false);
  expect(attribute['an action after it']).toBe(true);
  expect(attribute['something between them']).toBe(false);
  expect(attribute['that removed again']).toBe(true);
  expect(attribute['a link that is not a button']).toBe(false);
  expect(attribute['the rail moved in front of an action']).toBe(true);
  expect(attribute['a search box with no button']).toBe(false);
  expect(attribute['a submit button in its form']).toBe(true);
  expect(attribute['the button removed']).toBe(false);
  expect(attribute['a button of another kind']).toBe(false);
  expect(attribute['the form replaced by one with the button deep inside']).toBe(true);
  expect(attribute['an element that only borrows the class, holding the search box']).toBe('true:true');
  expect(attribute['the button removed from inside both']).toBe('false:false');
});
