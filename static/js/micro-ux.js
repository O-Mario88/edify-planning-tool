/* Edify platform-wide micro-interaction enhancement.
 *
 * Server HTML remains authoritative. This layer adds semantics that can be
 * derived safely (table headers, captions, tab keys), normalizes custom modal
 * focus behavior, and exposes an audit count for live browser verification.
 */
(function () {
  'use strict';

  if (window.__edifyMicroUXInstalled) return;
  window.__edifyMicroUXInstalled = true;

  var dialogStates = new WeakMap();
  var activeDialogs = new Set();
  var generatedId = 0;
  var scanQueued = false;
  var tablistSelector = [
    '[role="tablist"]',
    '.edify-tab-container',
    '[data-edify-tablist]',
    '.messages-inbox-tabs',
    '.pto-tabs',
    '.sp-period-tabs',
    '.spp-tabs',
    '.tt-segmented',
    '.oversight-entity-tabs',
    '.edify-section-nav__clusters',
    '.edify-section-nav__inner'
  ].join(', ');
  var tabSelector = [
    '[role="tab"]',
    '.edify-tab-btn',
    '[data-edify-tab]',
    '.messages-inbox-tab',
    '.pto-tabs > button',
    '.sp-period-tabs > button',
    '.spp-tabs > button',
    '.tt-segmented > button',
    '.oversight-entity-tabs__link',
    '.edify-section-nav__cluster',
    '.edify-section-nav__link'
  ].join(', ');

  function cleanText(value) {
    return (value || '').replace(/\s+/g, ' ').trim();
  }

  function visible(element) {
    return Boolean(element && element.isConnected && element.getClientRects().length);
  }

  function nearestHeading(element) {
    var container = element.closest('section, article, .card, .edify-surface, main');
    var heading = container && container.querySelector('h1, h2, h3, h4');
    if (!heading) heading = document.querySelector('main h1');
    return cleanText(heading && heading.textContent) || 'Data records';
  }

  function ensureTableCaption(table) {
    var caption = table.querySelector(':scope > caption');
    if (!caption) {
      caption = document.createElement('caption');
      caption.className = 'edify-visually-hidden';
      caption.textContent = nearestHeading(table);
      table.insertBefore(caption, table.firstChild);
    }
    return cleanText(caption.textContent) || 'Data records';
  }

  function updateScrollState(region) {
    var max = Math.max(0, region.scrollWidth - region.clientWidth);
    region.classList.toggle('can-scroll-inline-start', region.scrollLeft > 2);
    region.classList.toggle('can-scroll-inline-end', region.scrollLeft < max - 2);
  }

  function makeScrollRegion(table, label) {
    var region = table.parentElement;
    var alreadySuitable = region && (
      region.classList.contains('overflow-x-auto') ||
      region.classList.contains('overflow-auto') ||
      region.hasAttribute('data-table-scroll-region')
    );

    if (!alreadySuitable) {
      region = document.createElement('div');
      table.parentNode.insertBefore(region, table);
      region.appendChild(table);
    }

    region.classList.add('edify-table-scroll-region');
    region.setAttribute('data-table-scroll-region', '');
    region.setAttribute('role', 'region');
    region.setAttribute('aria-label', 'Scrollable table: ' + label);
    region.setAttribute('tabindex', '0');
    if (region.dataset.edifyScrollReady !== 'true') {
      region.dataset.edifyScrollReady = 'true';
      region.addEventListener('scroll', function () { updateScrollState(region); }, { passive: true });
    }
    requestAnimationFrame(function () { updateScrollState(region); });
  }

  function enhanceTableChoices(table) {
    table.querySelectorAll('input[type="checkbox"], input[type="radio"]').forEach(function (choice) {
      if (choice.closest('label')) return;
      var row = choice.closest('tr');
      var isHeaderChoice = Boolean(choice.closest('thead'));
      var recordCell = row && Array.from(row.querySelectorAll('th, td')).find(function (cell) {
        return !cell.contains(choice) && cleanText(cell.textContent);
      });
      var recordName = cleanText(recordCell && recordCell.textContent);
      var actionName = isHeaderChoice ? 'Select all records' : 'Select ' + (recordName || 'record');
      var wrapper = document.createElement('label');
      wrapper.className = 'edify-table-choice';
      var accessibleText = document.createElement('span');
      accessibleText.className = 'edify-visually-hidden';
      accessibleText.textContent = actionName;
      choice.parentNode.insertBefore(wrapper, choice);
      wrapper.appendChild(choice);
      wrapper.appendChild(accessibleText);
    });
  }

  function enhanceTable(table) {
    if (table.dataset.edifyTableReady === 'true' || table.getAttribute('role') === 'presentation') return;
    table.dataset.edifyTableReady = 'true';

    var label = ensureTableCaption(table);
    var headerCells = Array.from(table.querySelectorAll('thead tr:last-child th'));
    headerCells.forEach(function (header) {
      if (!header.hasAttribute('scope')) header.setAttribute('scope', 'col');
    });
    table.querySelectorAll('tbody th').forEach(function (header) {
      if (!header.hasAttribute('scope')) header.setAttribute('scope', 'row');
    });
    enhanceTableChoices(table);

    /* Compact comparison tables can opt into a fixed, intrinsic-width layout
       that keeps every column visible on phones. They remain semantic tables
       instead of becoming cards or a horizontal scroll region. */
    if (table.matches('[data-mobile-table="fit"]')) {
      table.classList.add('edify-mobile-table--fit');
      return;
    }

    var forceCards = table.matches('[data-mobile-table="cards"]');
    var bodyRows = Array.from(table.querySelectorAll('tbody > tr'));
    var structuralSpan = Array.from(
      table.querySelectorAll('[rowspan], [colspan]:not([colspan="1"])')
    ).some(function (cell) {
      var row = cell.parentElement;
      var isSingleCellEmptyState = row && row.closest('tbody') && row.children.length === 1;
      return cell.hasAttribute('rowspan') || cell.closest('thead') || !isSingleCellEmptyState;
    });
    /* Operational records become labelled cards on narrow screens even when
       they have many columns. Column count alone is not a reason to force a
       phone user into a 44rem horizontal canvas. Only true comparison
       matrices and structurally grouped tables keep horizontal scrolling. */
    var complex = !forceCards && (
      headerCells.length === 0 || Boolean(
        structuralSpan ||
        table.matches('.edify-report-matrix__table, [data-mobile-table="scroll"]')
      )
    );

    if (complex) {
      table.classList.add('edify-mobile-table--scroll');
      makeScrollRegion(table, label);
      return;
    }

    table.classList.add('edify-mobile-table--cards');
    var headers = headerCells.map(function (header) { return cleanText(header.textContent); });

    bodyRows.forEach(function (row) {
      var cells = Array.from(row.children).filter(function (cell) {
        return cell.matches('td, th');
      });
      if (cells.length === 1 && cells[0].hasAttribute('colspan')) {
        row.classList.add('edify-mobile-table__empty-row');
        cells[0].classList.add('edify-mobile-table__empty');
        return;
      }

      cells.forEach(function (cell, index) {
        if (!cell.hasAttribute('data-label') && headers[index]) {
          cell.setAttribute('data-label', headers[index]);
        }
      });
      if (cells[0] && !cells[0].hasAttribute('data-record-title')) {
        cells[0].setAttribute('data-record-title', '');
      }
      var last = cells[cells.length - 1];
      if (last && last.querySelector('a, button, input, select')) {
        last.setAttribute('data-record-action', '');
      }
    });
  }

  function enhanceTables(root) {
    if (root.matches && root.matches('table')) enhanceTable(root);
    root.querySelectorAll('table').forEach(enhanceTable);
  }

  function availableTabs(tablist) {
    return Array.from(tablist.querySelectorAll(tabSelector)).filter(function (tab) {
      return !tab.disabled && tab.getAttribute('aria-disabled') !== 'true';
    });
  }

  function revealTab(tab, revealNext, immediate) {
    var tablist = tab && tab.closest(tablistSelector);
    if (!tablist || tablist.scrollWidth <= tablist.clientWidth + 2) return;

    function alignTab() {
      if (!visible(tab) || !visible(tablist)) return;
      var tabs = availableTabs(tablist);
      var index = tabs.indexOf(tab);
      var next = revealNext && index >= 0 ? tabs[index + 1] : null;
      var stripRect = tablist.getBoundingClientRect();
      var selectedRect = tab.getBoundingClientRect();
      var revealRect = next ? next.getBoundingClientRect() : selectedRect;
      var edge = 8;
      var delta = 0;

      if (selectedRect.left < stripRect.left + edge) {
        delta = selectedRect.left - stripRect.left - edge;
      } else if (revealRect.right > stripRect.right - edge) {
        delta = revealRect.right - stripRect.right + edge;
      }

      if (Math.abs(delta) < 1) return;
      var maximum = Math.max(0, tablist.scrollWidth - tablist.clientWidth);
      var destination = Math.max(0, Math.min(maximum, tablist.scrollLeft + delta));
      tablist.scrollTo({
        left: destination,
        behavior: immediate || window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'
      });
    }

    /* Alpine and HTMX can update active state and element width in the same
       click. Two frames let that settle before measuring. The short follow-up
       closes any remaining pixel gap after smooth scrolling or font loading. */
    requestAnimationFrame(function () {
      requestAnimationFrame(alignTab);
    });
    if (!immediate) window.setTimeout(alignTab, 220);
  }

  function enhanceTabReveal(tablist) {
    if (tablist.dataset.edifyTabRevealReady === 'true') return;
    tablist.dataset.edifyTabRevealReady = 'true';

    tablist.addEventListener('click', function (event) {
      var selected = event.target.closest(tabSelector);
      if (!selected || !tablist.contains(selected)) return;
      revealTab(selected, true);
    });

    tablist.addEventListener('focusin', function (event) {
      var focused = event.target.closest(tabSelector);
      if (!focused || !tablist.contains(focused)) return;
      revealTab(focused, false);
    });

    var active = tablist.querySelector(
      '[role="tab"][aria-selected="true"], .edify-tab-btn.active, [data-edify-tab][aria-pressed="true"], ' +
      '[data-edify-tab][aria-current="true"], [data-edify-tab][aria-current="page"], ' +
      '.messages-inbox-tab[aria-pressed="true"], .pto-tabs > button.is-active, ' +
      '.sp-period-tabs > button.is-active, .spp-tabs > button.is-active, ' +
      '.tt-segmented > button.is-active, .tt-segmented > button[aria-pressed="true"]'
      + ', .oversight-entity-tabs__link.is-active, .edify-section-nav__cluster.is-active, '
      + '.edify-section-nav__link.is-active'
    );
    if (active) revealTab(active, true, true);
  }

  function enhanceTabList(tablist) {
    enhanceTabReveal(tablist);
    if (tablist.dataset.edifyTabsReady === 'true') return;
    tablist.dataset.edifyTabsReady = 'true';
    tablist.addEventListener('keydown', function (event) {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      var tabs = availableTabs(tablist);
      if (!tabs.length) return;
      var current = Math.max(0, tabs.indexOf(document.activeElement));
      var next = current;
      if (event.key === 'ArrowLeft') next = (current - 1 + tabs.length) % tabs.length;
      if (event.key === 'ArrowRight') next = (current + 1) % tabs.length;
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = tabs.length - 1;
      event.preventDefault();
      tabs[next].focus();
    });
  }

  function enhanceTabs(root) {
    if (root.matches && root.matches(tablistSelector)) enhanceTabList(root);
    root.querySelectorAll(tablistSelector).forEach(enhanceTabList);
  }

  function focusables(dialog) {
    return Array.from(dialog.querySelectorAll(
      'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )).filter(visible);
  }

  function nameDialog(dialog) {
    if (dialog.hasAttribute('aria-label') || dialog.hasAttribute('aria-labelledby')) return;
    var heading = dialog.querySelector('h1, h2, h3, h4');
    if (!heading) {
      dialog.setAttribute('aria-label', dialog.getAttribute('role') === 'alertdialog' ? 'Confirmation' : 'Dialog');
      return;
    }
    if (!heading.id) {
      generatedId += 1;
      heading.id = 'edify-dialog-title-' + generatedId;
    }
    dialog.setAttribute('aria-labelledby', heading.id);
  }

  function inertOutside(dialog) {
    var states = [];
    var node = dialog;
    while (node.parentElement && node.parentElement !== document.body) {
      Array.from(node.parentElement.children).forEach(function (sibling) {
        if (sibling === node || sibling.tagName === 'SCRIPT' || sibling.tagName === 'STYLE') return;
        states.push({ node: sibling, inert: sibling.inert, ariaHidden: sibling.getAttribute('aria-hidden') });
        sibling.inert = true;
        sibling.setAttribute('aria-hidden', 'true');
      });
      node = node.parentElement;
    }
    Array.from(document.body.children).forEach(function (sibling) {
      if (sibling === node || sibling.tagName === 'SCRIPT' || sibling.tagName === 'STYLE') return;
      states.push({ node: sibling, inert: sibling.inert, ariaHidden: sibling.getAttribute('aria-hidden') });
      sibling.inert = true;
      sibling.setAttribute('aria-hidden', 'true');
    });
    return states;
  }

  function restoreOutside(states) {
    states.forEach(function (state) {
      if (!state.node.isConnected) return;
      state.node.inert = state.inert;
      if (state.ariaHidden === null) state.node.removeAttribute('aria-hidden');
      else state.node.setAttribute('aria-hidden', state.ariaHidden);
    });
  }

  function activateDialog(dialog) {
    if (activeDialogs.has(dialog) || dialog.matches('.drawer-surface') || !visible(dialog)) return;
    nameDialog(dialog);
    if (!dialog.hasAttribute('tabindex')) dialog.setAttribute('tabindex', '-1');
    var previousFocus = document.activeElement;
    var background = inertOutside(dialog);
    var keyHandler = function (event) {
      if (event.key !== 'Tab') return;
      var items = focusables(dialog);
      if (!items.length) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      var first = items[0];
      var last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    dialog.addEventListener('keydown', keyHandler);
    dialogStates.set(dialog, { previousFocus: previousFocus, background: background, keyHandler: keyHandler });
    activeDialogs.add(dialog);
    requestAnimationFrame(function () {
      if (!visible(dialog)) return;
      var items = focusables(dialog);
      (items[0] || dialog).focus({ preventScroll: true });
    });
  }

  function deactivateDialog(dialog) {
    if (!activeDialogs.has(dialog) || visible(dialog)) return;
    var state = dialogStates.get(dialog);
    activeDialogs.delete(dialog);
    if (!state) return;
    dialog.removeEventListener('keydown', state.keyHandler);
    restoreOutside(state.background);
    if (state.previousFocus && state.previousFocus.isConnected) state.previousFocus.focus({ preventScroll: true });
    dialogStates.delete(dialog);
  }

  function enhanceCustomDialogs(root) {
    var dialogs = [];
    if (root.matches && root.matches('[role="dialog"][aria-modal="true"], [role="alertdialog"][aria-modal="true"]')) dialogs.push(root);
    root.querySelectorAll('[role="dialog"][aria-modal="true"], [role="alertdialog"][aria-modal="true"]').forEach(function (dialog) {
      dialogs.push(dialog);
    });
    dialogs.forEach(function (dialog) {
      nameDialog(dialog);
      if (visible(dialog)) activateDialog(dialog);
    });
    Array.from(activeDialogs).forEach(deactivateDialog);
  }

  function controlHasName(control) {
    if (cleanText(control.textContent) || control.getAttribute('aria-label') || control.getAttribute('aria-labelledby') || control.title) return true;
    if (control.labels && control.labels.length) return true;
    if (control.tagName === 'INPUT' && ['hidden', 'submit', 'button'].includes(control.type)) return true;
    return false;
  }

  function enhanceFormLabels(root) {
    var fields = [];
    if (root.matches && root.matches('input, select, textarea')) fields.push(root);
    root.querySelectorAll('input, select, textarea').forEach(function (field) { fields.push(field); });
    fields.forEach(function (field) {
      if (field.type === 'hidden' || controlHasName(field) || !field.parentElement) return;
      var siblings = Array.from(field.parentElement.children);
      var fieldIndex = siblings.indexOf(field);
      var label = siblings.slice(0, fieldIndex).reverse().find(function (candidate) {
        return candidate.tagName === 'LABEL' && !candidate.htmlFor;
      });
      if (!label) return;
      if (!field.id) {
        generatedId += 1;
        field.id = 'edify-field-' + generatedId;
      }
      label.htmlFor = field.id;
    });
  }

  function auditInteractiveNames(root) {
    var controls = [];
    if (root.matches && root.matches('a[href], button, input, select, textarea, summary, [role="button"], [role="tab"]')) controls.push(root);
    root.querySelectorAll('a[href], button, input, select, textarea, summary, [role="button"], [role="tab"]').forEach(function (control) {
      controls.push(control);
    });
    controls.forEach(function (control) {
      if (!visible(control) || controlHasName(control)) delete control.dataset.edifyA11yWarning;
      else control.dataset.edifyA11yWarning = 'missing-name';
      control.querySelectorAll('svg:not([aria-hidden="true"]):not([role="img"])').forEach(function (svg) {
        svg.setAttribute('aria-hidden', 'true');
      });
    });
    document.documentElement.dataset.edifyA11yWarnings = String(
      document.querySelectorAll('[data-edify-a11y-warning]').length
    );
  }

  function announce(message, priority) {
    var target = document.getElementById(priority === 'assertive' ? 'edify-live-assertive' : 'edify-live-polite');
    if (!target || !message) return;
    target.textContent = '';
    window.setTimeout(function () { target.textContent = message; }, 40);
  }

  function enhance(root) {
    enhanceTables(root);
    enhanceTabs(root);
    enhanceCustomDialogs(root);
    enhanceFormLabels(root);
    auditInteractiveNames(root);
  }

  function scheduleFullScan() {
    if (scanQueued) return;
    scanQueued = true;
    requestAnimationFrame(function () {
      scanQueued = false;
      enhanceCustomDialogs(document);
      enhanceFormLabels(document);
      auditInteractiveNames(document);
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    enhance(document);
    var observer = new MutationObserver(scheduleFullScan);
    observer.observe(document.body, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ['style', 'class', 'hidden', 'open']
    });
  });

  document.addEventListener('htmx:afterSettle', function (event) { enhance(event.target); });
  document.addEventListener('edify:announce', function (event) {
    announce(event.detail && event.detail.message, event.detail && event.detail.priority);
  });
  document.addEventListener('htmx:responseError', function () {
    announce('The action could not be completed. Review the error message and try again.', 'assertive');
  });
  document.addEventListener('htmx:sendError', function () {
    announce('The network request failed. Check your connection and try again.', 'assertive');
  });

  window.EdifyMicroUX = Object.freeze({ enhance: enhance, announce: announce });
})();
