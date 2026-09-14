/* Shared record lists: readable cards on phones, comparative tables on desktop.
 * Reuse the original cells and controls; never clone forms, IDs or listeners. */
(() => {
  'use strict';
  const mounted = new WeakMap();
  function cleanup(table) {
    mounted.get(table)?.remove();
    mounted.delete(table);
    table.querySelectorAll('.edify-record-field-label').forEach(label => label.remove());
    table.classList.remove('edify-adaptive-records');
    delete table.dataset.recordView;
  }
  function enhance(root, preferredView) {
    const tables = [...(root.querySelectorAll?.('table.edify-record-table') || [])];
    if (root.matches?.('table.edify-record-table')) tables.unshift(root);
    tables.forEach(table => {
      if (!table.closest('#main-content') || mounted.has(table) || table.dataset.mobileTable === 'comparison') return;
      const heads = [...table.querySelectorAll(':scope > thead > tr')];
      if (heads.length !== 1 || table.tFoot) return;
      const headers = [...heads[0].cells];
      const rows = [...table.querySelectorAll(':scope > tbody > tr')];
      if (headers.length < 3 || headers.some(h => h.colSpan !== 1 || h.rowSpan !== 1)) return;
      if (!rows.length || rows.some(r => r.cells.length !== headers.length || [...r.cells].some(c => c.colSpan !== 1 || c.rowSpan !== 1))) return;
      table.classList.add('edify-adaptive-records');
      const selectedView = preferredView === 'table' ? 'table' : 'cards';
      table.dataset.recordView = selectedView;
      table.setAttribute('role', 'table');
      table.querySelectorAll(':scope > thead, :scope > tbody').forEach(group => group.setAttribute('role', 'rowgroup'));
      heads[0].setAttribute('role', 'row');
      headers.forEach(cell => cell.setAttribute('role', 'columnheader'));
      rows.forEach(row => {
        row.setAttribute('role', 'row');
        [...row.cells].forEach((cell, i) => {
          cell.setAttribute('role', cell.tagName === 'TH' ? 'rowheader' : 'cell');
          const label = document.createElement('span');
          label.className = 'edify-record-field-label';
          label.setAttribute('aria-hidden', 'true');
          label.textContent = headers[i].textContent.trim() || 'Selection';
          cell.prepend(label);
        });
      });
      const controls = document.createElement('div');
      controls.className = 'edify-record-view-controls';
      controls.setAttribute('role', 'group');
      const title = table.caption?.textContent.trim() || table.closest('section, article, main')?.querySelector('h1, h2, h3')?.textContent.trim() || 'Records';
      controls.setAttribute('aria-label', title + ' display');
      const hint = document.createElement('span');
      hint.textContent = 'View records as';
      controls.append(hint);
      ['cards', 'table'].forEach(view => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'btn btn-secondary';
        button.textContent = view === 'cards' ? 'Cards' : 'Table';
        button.setAttribute('aria-pressed', String(view === selectedView));
        button.addEventListener('click', () => {
          table.dataset.recordView = view;
          controls.querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', String(b === button)));
        });
        controls.append(button);
      });
      const region = table.closest('[data-table-scroll-region], .overflow-x-auto, .overflow-auto') || table;
      region.before(controls);
      mounted.set(table, controls);
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => enhance(document));
  else enhance(document);
  document.addEventListener('htmx:load', e => {
    const root = e.detail.elt;
    const parentTable = root.closest?.('table.edify-record-table');
    if (parentTable) {
      const view = parentTable.dataset.recordView;
      cleanup(parentTable);
      enhance(parentTable, view);
    }
    else enhance(root);
  });
  document.addEventListener('htmx:beforeCleanupElement', e => {
    const root = e.detail.elt;
    if (root.matches?.('table.edify-record-table')) cleanup(root);
    root.querySelectorAll?.('table.edify-record-table').forEach(cleanup);
  });
})();
