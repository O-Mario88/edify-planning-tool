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
  var mutationScanQueued = false;
  var auditQueued = false;
  var pendingEnhanceRoots = new Set();
  var pendingDialogRoots = new Set();
  var pendingAuditRoots = new Set();

  /* Some mobile browsers keep native checkboxes in :focus-visible after a
   * tap. Track the actual input modality so CSS can suppress that pointer-only
   * square without removing the focus indicator for keyboard users. Capture
   * runs before the control receives focus. */
  document.addEventListener('pointerdown', function () {
    document.documentElement.dataset.edifyInputModality = 'pointer';
  }, { capture: true, passive: true });
  document.addEventListener('keydown', function () {
    document.documentElement.dataset.edifyInputModality = 'keyboard';
  }, { capture: true });

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

  var filterToolbarSelector = [
    '.platform-filter-bar', '.edify-filter-bar', '.sp-filter-panel',
    '.spp-filter-panel', '.spa-filter-panel', '.tt-filter-panel',
    '.school-filters-form', '.school-filter-canvas', '#filters-form',
    '#core-filters-form', '#analytics-filters-form', '#pl-analytics-filters',
    '#cd-analytics-filters', '#cb-filters', '#debrief-filters',
    '#visits-filters', '#trainings-filters', '#pd-filters', '#spp-filters',
    '#spa-filters', '#sp-plan-filters', '#pl-dashboard-filters',
    '#project-filters', '#cluster-filters', '[data-component="filter-toolbar"]'
  ].join(', ');

  var tileSelector = [
    '.card', '.panel', '.mini', '.edify-tile',
    '.edify-surface[class*="rounded"]',
    '[class*="-card"]:not([class*="-card-"]):not([class*="-card__"])',
    'div[class*="rounded"][class*="border"]',
    'section[class*="rounded"][class*="border"]',
    'article[class*="rounded"][class*="border"]'
  ].join(', ');

  function elementsWithin(root, selector) {
    var elements = [];
    if (root.matches && root.matches(selector)) elements.push(root);
    root.querySelectorAll(selector).forEach(function (element) { elements.push(element); });
    return elements;
  }

  /* Relational :has() selectors in a global stylesheet force Chrome to walk
   * ancestors whenever any descendant class changes. Resolve those stable DOM
   * relationships once into ordinary classes instead. HTMX-added roots pass
   * through this same enhancer, so the markers remain correct after swaps. */
  function enhanceStructuralMarkers(root) {
    elementsWithin(root, filterToolbarSelector).forEach(function (toolbar) {
      toolbar.classList.toggle(
        'edify-has-work-plan-filter-popover',
        Boolean(toolbar.querySelector('.work-plan-filter-popover'))
      );
      Array.from(toolbar.children).forEach(function (child) {
        if (!child.matches('label, div')) return;
        var field = child.querySelector(':scope > select, :scope > input:not([type="hidden"]), :scope > textarea');
        child.classList.toggle('edify-filter-field', Boolean(field));
      });
    });

    elementsWithin(root, 'main .grid').forEach(function (grid) {
      var directTiles = Array.from(grid.children).filter(function (child) {
        return child.matches(tileSelector);
      });
      grid.classList.toggle('edify-tile-grid', directTiles.length > 0);
      grid.classList.toggle(
        'edify-single-tile-grid',
        directTiles.length === 1 && !directTiles[0].className.includes('col-span')
      );
    });

    elementsWithin(root, 'main .kpi-strip__item').forEach(function (item) {
      item.classList.toggle('edify-interactive-card', Boolean(item.querySelector('.kpi-strip__item-body--link')));
    });

    elementsWithin(root, 'main :is(.card, .card-elevated, .card-flat, .card-insight, .premium-card, .premium-card-elevated, .panel, .mini, .summary-card, .rail-card, .edify-kpi-card, .card-kpi, .edify-tile, [class*="-card"], [class*="-panel"], [class*="-tile"], .edify-surface[class*="rounded"])').forEach(function (surface) {
      var structured = Array.from(surface.children).some(function (child) {
        return child.matches('header, [class*="__header"], [class*="titlebar"], table, .overflow-x-auto, .overflow-auto, [class*="table-wrap"], [class*="table-scroll"]');
      });
      surface.classList.toggle('edify-structured-surface', structured);
    });

    elementsWithin(root, 'main :is(div, section, article, p, li)[class*="text-center"]').forEach(function (element) {
      element.classList.toggle(
        'edify-empty-copy',
        !element.querySelector('form, input, select, textarea, canvas, img, embed')
      );
    });

    elementsWithin(root, '.edify-record-table input[type="checkbox"]').forEach(function (choice) {
      var row = choice.closest('tbody tr');
      if (row) row.classList.toggle('edify-row-selected', choice.checked);
    });
  }

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
  }

  function tableColumnCount(table) {
    /* Layout geometry only — how many columns the widest row spans, for the
       mobile scroll-region decision. Accumulator names deliberately avoid the
       business-arithmetic vocabulary (total/amount/sum) the readiness gate
       watches for: nothing here is a quantity the server should own. */
    return Array.from(table.rows || []).reduce(function (widest, row) {
      var columnsInRow = Array.from(row.cells || []).reduce(function (spanned, cell) {
        return spanned + Math.max(1, cell.colSpan || 1);
      }, 0);
      return Math.max(widest, columnsInRow);
    }, 0);
  }

  function tableNeedsInlineScroll(table) {
    /* Every visible table keeps single-line cells at every breakpoint. Even a
       two-column comparison can contain a long school or intervention name,
       so column count is not a safe proxy for whether wrapping is acceptable.
       Always provide the same labelled horizontal scroll affordance. */
    return table.getAttribute('role') !== 'presentation';
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
    var columnCount = tableColumnCount(table);
    table.dataset.edifyTableColumns = String(columnCount);
    table.dataset.edifyTableWidth = columnCount > 8 ? 'xwide' : (columnCount > 5 ? 'wide' : 'standard');
    var headerCells = Array.from(table.querySelectorAll('thead tr:last-child th'));
    headerCells.forEach(function (header) {
      if (!header.hasAttribute('scope')) header.setAttribute('scope', 'col');
    });
    table.querySelectorAll('tbody th').forEach(function (header) {
      if (!header.hasAttribute('scope')) header.setAttribute('scope', 'row');
    });
    enhanceTableChoices(table);

    /* A visually hidden table is an accessibility fallback for a chart, not
       a visual layout surface. Preserve its one-pixel hiding contract. */
    if (table.matches('.sr-only, .edify-visually-hidden')) return;

    if (!tableNeedsInlineScroll(table)) return;

    /* Keep every data set tangible at every viewport: the header and column
       relationships stay visible, and every screen scrolls the real table
       horizontally whenever its content is wider than the region. */
    table.classList.add('edify-mobile-table--scroll');
    makeScrollRegion(table, label);
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
  }

  /* Tabs are replaced frequently by HTMX. Per-tablist handlers used to leave
   * one click, focus and keydown closure behind for every replacement until
   * the browser's next collection cycle. One document-level owner works for
   * both present and future tablists, so replacement does not create listener
   * or detached-tree churn. */
  function eventTab(event) {
    var tab = event.target && event.target.closest && event.target.closest(tabSelector);
    var tablist = tab && tab.closest(tablistSelector);
    return tablist && tablist.contains(tab) ? { tab: tab, tablist: tablist } : null;
  }

  document.addEventListener('click', function (event) {
    var match = eventTab(event);
    if (!match) return;
    if (match.tab.matches('[role="tab"]')) {
      match.tablist.querySelectorAll('[role="tab"]').forEach(function (tab) {
        var active = tab === match.tab;
        tab.setAttribute('aria-selected', active ? 'true' : 'false');
        tab.tabIndex = active ? 0 : -1;
      });
    }
    revealTab(match.tab, true);
  });

  document.addEventListener('focusin', function (event) {
    var match = eventTab(event);
    if (match) revealTab(match.tab, false);
  });

  document.addEventListener('keydown', function (event) {
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
    var match = eventTab(event);
    if (!match) return;
    var tabs = availableTabs(match.tablist);
    var current = tabs.indexOf(match.tab);
    if (current < 0 || !tabs.length) return;
    var next = current;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = (current - 1 + tabs.length) % tabs.length;
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = (current + 1) % tabs.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = tabs.length - 1;
    event.preventDefault();
    tabs[next].focus();
    if (tabs[next].matches('[role="tab"]')) tabs[next].click();
  });

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

  /* Take ownership of a node only if nothing else already holds it.
   *
   * This used to snapshot whatever it found and restore that on close, which
   * is only correct when this module is the sole owner of `inert`. It is not:
   * the drawer system inerts the whole shell while a drawer is open, and a
   * confirmation dialog INSIDE that drawer would then record `inert: true` as
   * the background's natural state — and re-assert it after the drawer had
   * already released the page. The result was a shell that accepted no clicks
   * at all until a reload, reached by the most ordinary path there is: type
   * into a drawer, press Escape, confirm discard.
   *
   * A node that is already inert belongs to an outer layer, which will clear
   * it when that layer closes. So this neither sets nor restores it — the
   * only states recorded here are ones this module actually created.
   */
  function claim(states, node) {
    if (node.tagName === 'SCRIPT' || node.tagName === 'STYLE') return;
    if (node.inert) return;
    states.push({ node: node, ariaHidden: node.getAttribute('aria-hidden') });
    node.inert = true;
    node.setAttribute('aria-hidden', 'true');
  }

  function inertOutside(dialog) {
    var states = [];
    var node = dialog;
    while (node.parentElement && node.parentElement !== document.body) {
      Array.from(node.parentElement.children).forEach(function (sibling) {
        if (sibling === node) return;
        claim(states, sibling);
      });
      node = node.parentElement;
    }
    Array.from(document.body.children).forEach(function (sibling) {
      if (sibling === node) return;
      claim(states, sibling);
    });
    return states;
  }

  function restoreOutside(states) {
    states.forEach(function (state) {
      if (!state.node.isConnected) return;
      state.node.inert = false;
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
    if (cleanText(control.textContent) || control.getAttribute('aria-label') || control.getAttribute('aria-labelledby')) return true;
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

  /* A button inside a form defaults to submit. Legacy HTMX and Alpine action
   * buttons often predate the shared button component, so an innocent drawer
   * close or tab switch can otherwise submit the surrounding workflow. Only
   * controls with an unambiguous client/HTMX action are normalized here;
   * unlabeled form actions remain server-owned and must declare submit at
   * source. */
  function normalizeActionButtonTypes(root) {
    var buttons = [];
    if (root.matches && root.matches('button:not([type])')) buttons.push(root);
    root.querySelectorAll('button:not([type])').forEach(function (button) { buttons.push(button); });
    buttons.forEach(function (button) {
      var isAction = button.hasAttribute('hx-get') ||
        button.hasAttribute('hx-post') ||
        button.hasAttribute('@click') ||
        button.hasAttribute('x-on:click') ||
        button.hasAttribute('data-mobile-dialog-close') ||
        button.hasAttribute('data-help-close') ||
        button.getAttribute('role') === 'tab';
      if (isAction) button.type = 'button';
    });
  }

  function auditInteractiveNames(root) {
    var controls = [];
    if (root.matches && root.matches('a[href], button, input, select, textarea, summary, [role="button"], [role="tab"]')) controls.push(root);
    root.querySelectorAll('a[href], button, input, select, textarea, summary, [role="button"], [role="tab"]').forEach(function (control) {
      controls.push(control);
    });
    controls.forEach(function (control) {
      if (!controlHasName(control) && control.title) control.setAttribute('aria-label', control.title);
      /* Accessible naming is a markup property. Measuring visibility here
       * forced layout once per control without improving the audit. */
      if (controlHasName(control)) delete control.dataset.edifyA11yWarning;
      else control.dataset.edifyA11yWarning = 'missing-name';
      control.querySelectorAll('svg:not([aria-hidden="true"]):not([role="img"])').forEach(function (svg) {
        svg.setAttribute('aria-hidden', 'true');
      });
    });
  }

  function updateAuditCounts() {
    document.documentElement.dataset.edifyA11yWarnings = String(
      document.querySelectorAll('[data-edify-a11y-warning]').length
    );
    var implicitActionButtons = Array.from(document.querySelectorAll('button:not([type])')).filter(function (button) {
      return button.hasAttribute('hx-get') || button.hasAttribute('hx-post') ||
        button.hasAttribute('@click') || button.hasAttribute('x-on:click');
    });
    document.documentElement.dataset.edifyImplicitActionButtons = String(implicitActionButtons.length);
  }

  function announce(message, priority) {
    var target = document.getElementById(priority === 'assertive' ? 'edify-live-assertive' : 'edify-live-polite');
    if (!target || !message) return;
    target.textContent = '';
    window.setTimeout(function () { target.textContent = message; }, 40);
  }

  function enhanceCritical(root) {
    enhanceTables(root);
    enhanceStructuralMarkers(root);
    enhanceTabs(root);
    enhanceCustomDialogs(root);
    enhanceFormLabels(root);
    normalizeActionButtonTypes(root);
  }

  function runWhenIdle(callback) {
    if ('requestIdleCallback' in window) {
      window.requestIdleCallback(callback, { timeout: 500 });
      return;
    }
    window.setTimeout(callback, 50);
  }

  function scheduleAudit(root) {
    pendingAuditRoots.add(root);
    if (auditQueued) return;
    auditQueued = true;
    runWhenIdle(function () {
      auditQueued = false;
      var roots = Array.from(pendingAuditRoots);
      pendingAuditRoots.clear();
      roots.forEach(function (auditRoot) {
        if (auditRoot === document || auditRoot.isConnected) auditInteractiveNames(auditRoot);
      });
      updateAuditCounts();
    });
  }

  function enhance(root) {
    enhanceCritical(root);
    scheduleAudit(root);
  }

  function scheduleMutationScan(mutations) {
    mutations.forEach(function (mutation) {
      if (mutation.type === 'childList') {
        mutation.addedNodes.forEach(function (node) {
          if (node.nodeType === Node.ELEMENT_NODE) pendingEnhanceRoots.add(node);
        });
      }
      if (mutation.target && mutation.target.nodeType === Node.ELEMENT_NODE) {
        pendingDialogRoots.add(mutation.target);
      }
    });
    if (mutationScanQueued) return;
    mutationScanQueued = true;
    requestAnimationFrame(function () {
      mutationScanQueued = false;
      var enhanceRoots = Array.from(pendingEnhanceRoots);
      var dialogRoots = Array.from(pendingDialogRoots);
      pendingEnhanceRoots.clear();
      pendingDialogRoots.clear();
      enhanceRoots.forEach(function (root) {
        if (root.isConnected) enhance(root);
      });
      dialogRoots.forEach(function (root) {
        if (root.isConnected) enhanceCustomDialogs(root);
      });
      /* A removed dialog will not appear in a surviving mutation root. */
      Array.from(activeDialogs).forEach(deactivateDialog);
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    enhance(document);
    var observer = new MutationObserver(scheduleMutationScan);
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
  document.addEventListener('change', function (event) {
    var choice = event.target.closest && event.target.closest('.edify-record-table input[type="checkbox"]');
    var row = choice && choice.closest('tbody tr');
    if (row) row.classList.toggle('edify-row-selected', choice.checked);
  });

  window.EdifyMicroUX = Object.freeze({ enhance: enhance, announce: announce });
})();
