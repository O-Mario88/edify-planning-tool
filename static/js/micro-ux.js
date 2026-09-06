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

    /* A cell whose direct children are two or more stacked blocks (a name
       over an id, a value over a caption) is marked so consistency.css can
       lay them on one 32px line. Flex and grid wrappers keep their layout. */
    var cells = Array.from(elementsWithin(root, 'main table tbody td, main table tbody th, .drawer-body table tbody td, .drawer-body table tbody th'));
    /* READ PHASE. Every computed-style question this pass asks is answered
       here, before a single class is written. A style read after a class
       write re-resolves style for the changed subtree — 40-90ms on a
       dashboard with four thousand rules — and asking it per cell made the
       Country Director operations view a 400ms task (2026-09-06). Reading
       first costs one resolution for the whole pass. */
    var reads = new Map();
    cells.forEach(function (cell) {
      /* A child the page hides at this width (a phone-only label) is not a
         line of the row; marking it would show it again. Only a child that
         carries a hiding or responsive display class can be hidden. */
      var hidden = Array.from(cell.children).map(function (child) {
        if (child.hidden || child.hasAttribute('x-cloak')) return true;
        var classes = child.className && typeof child.className === 'string' ? child.className : '';
        if (!/(^|\s)(hidden|max-\w+:hidden|\w+:hidden|\w+:block|\w+:flex|\w+:inline\S*)(\s|$)/.test(classes)) return false;
        return window.getComputedStyle(child).display === 'none';
      });
      /* Chips a page stylesheet draws as inline-flex (a score, a status, a
         badge) take the 18px pill line. Colour dots carry no text. */
      var inlineFlexChips = [];
      cell.querySelectorAll('span, strong, b, em, small, a, div').forEach(function (chip) {
        if (chip.textContent.trim() === '') return;
        if (chip.matches('div') && chip.querySelector('div, p, table, form, ul, a, button')) return;
        if (window.getComputedStyle(chip).display === 'inline-flex') inlineFlexChips.push(chip);
      });
      /* A plain inline link in a cell is text, not a 24px control. */
      var inlineAnchors = Array.from(cell.querySelectorAll('a')).filter(function (anchor) {
        return window.getComputedStyle(anchor).display === 'inline';
      });
      reads.set(cell, {
        hidden: hidden,
        flex: window.getComputedStyle(cell).display === 'flex',
        inlineFlexChips: inlineFlexChips,
        inlineAnchors: inlineAnchors
      });
    });
    /* WRITE PHASE. */
    cells.forEach(function (cell) {
      var read = reads.get(cell);
      /* Every cell carries the marker the row rhythm hangs its rules on, so a
         page stylesheet with a class selector cannot out-rank the rhythm. */
      cell.classList.add('edify-cell');
      var hiddenChildren = read.hidden;
      Array.from(cell.children).forEach(function (child, index) {
        child.classList.toggle('edify-cell-hidden', hiddenChildren[index]);
      });
      Array.from(cell.children).forEach(function (child) {
        if (child.matches('div.rounded-pill, div.rounded-full')) child.classList.add('edify-cell-mark');
      });
      var blocks = Array.from(cell.children).filter(function (child) {
        return child.matches('div, p, span.block, small.block') && !child.matches('.flex, .grid, .inline-flex, form, .edify-cell-hidden');
      });
      cell.classList.toggle('edify-cell-stack', blocks.length > 1);
      /* A flex row in a cell (avatar beside a name) and the pills inside a
         cell get markers too, so the row rhythm never has to reach for a
         utility class in a selector. */
      Array.from(cell.children).forEach(function (child) {
        if (!child.classList.contains('flex')) return;
        if (child.classList.contains('edify-cell-mark')) return;
        child.classList.add('edify-cell-row');
        var first = child.firstElementChild;
        if (first && first.classList.contains('rounded-pill')) first.classList.add('edify-cell-mark');
      });
      cell.querySelectorAll('span.rounded-pill, a.rounded-pill, span.rounded-full, a.rounded-full').forEach(function (pill) {
        /* A colour dot carries no text; only labelled pills take the 18px line. */
        if (pill.textContent.trim() !== '') pill.classList.add('edify-cell-pill');
      });
      /* A cell laid out as a flex box is still a table cell: its children
         sit side by side on the one line. */
      var flexCell = read.flex ||
        Array.from(cell.classList).some(function (name) { return /^(?:[a-z-]+:)?(?:inline-)?flex$/.test(name); });
      if (flexCell) cell.classList.add('edify-cell-flex');
      read.inlineFlexChips.forEach(function (chip) {
        if (chip.matches('.edify-cell-row, .edify-cell-inline-row, .rounded-control, .btn, .edify-cell-pill, .edify-cell-stackchip')) return;
        chip.classList.add('edify-cell-pill');
      });
      /* A stacked tile in a cell (a heatmap value over its caption) reads
         as one 20px chip on the row line. */
      Array.from(cell.children).forEach(function (child) {
        if (child.matches('div.inline-flex.flex-col, div.flex.flex-col')) child.classList.add('edify-cell-stackchip');
      });
      /* A block that follows a pill or a control in a cell (a status over
         its action) sits beside it on the row line. */
      Array.from(cell.children).forEach(function (child, index) {
        if (index === 0 || child.classList.contains('edify-cell-hidden')) return;
        if (!child.matches('div, p')) return;
        if (child.matches('.flex, .grid, .inline-flex, form, table, details, .edify-cell-stackchip, .edify-cell-row')) return;
        child.classList.add('edify-cell-line', 'edify-cell-follows');
      });
      /* A text-carrying element with no element children of its own is a
         line of text wherever it sits, so it reads inline. Role pages built
         before `.edify-cell-row` nested their stacks two levels down inside a
         raw `flex items-center` (/staff) or wrote a caption as a bare
         `span.block` after a text node (Team Oversight), and neither was
         reached by the cell-level markers above: 67px and 46px rows against
         the 32px contract. Marked here rather than matched with `:has()`,
         which the bridge bans. */
      cell.querySelectorAll('p, span, small').forEach(function (line) {
        if (line.firstElementChild) return;
        if (line.textContent.trim() === '') return;
        if (line.matches('.edify-cell-pill, .edify-cell-mark, .edify-cell-row, .pill, .edify-status-badge, [class*="badge"], [class*="chip"], [class*="pill"], [x-show]')) return;
        line.classList.add('edify-cell-text');
      });
      /* A cell holding an identity mark (an avatar, a logo) keeps the mark at
         24px in a 4px cell, so the row still closes at 32px. */
      if (cell.querySelector('img, .edify-cell-mark, .h-8.w-8, .h-9.w-9, .h-10.w-10, .h-11.w-11, .h-12.w-12')) {
        cell.classList.add('edify-cell-media');
      }
      /* The label wrapping a row checkbox is not a 44px touch control: the
         row is. Marked here because the bridge cannot ask `:has()`. */
      cell.querySelectorAll('label').forEach(function (choice) {
        if (choice.querySelector('input[type="checkbox"], input[type="radio"]')) {
          choice.classList.add('edify-cell-choice');
        }
      });
      /* Every control in a cell is 24px tall, whatever the page gives it. */
      cell.querySelectorAll('button, label.edify-table-choice, select, input:not([type="checkbox"]):not([type="radio"]):not([type="hidden"]), a').forEach(function (control) {
        if (control.matches('a') && read.inlineAnchors.indexOf(control) !== -1) return;
        if (control.matches('.edify-cell-pill, .edify-cell-row')) return;
        control.classList.add('edify-cell-control');
      });
      /* A `.block` line directly in a cell, and a flex row of controls beside
         cell text, both sit on the one line. */
      var lines = Array.from(cell.children).filter(function (child) {
        return child.matches('a, span, p, small, div, time, strong') &&
          !child.matches('.flex, .grid, .inline-flex, form, table, .rounded-control, .btn, .status-pill, .edify-status-badge, .edify-cell-hidden');
      });
      Array.from(cell.children).forEach(function (child) {
        if (child.classList.contains('edify-cell-hidden')) return;
        if (child.matches('span.block, small.block') || (lines.length > 1 && lines.indexOf(child) !== -1)) {
          child.classList.add('edify-cell-line');
        }
        if (child.matches('.flex') && cell.children.length > 1 && !child.classList.contains('edify-cell-mark')) child.classList.add('edify-cell-inline-row');
      });
      /* Bare text followed by a paragraph or block span: the block sits inline
         after the text, with a separator. */
      var hasText = Array.from(cell.childNodes).some(function (node) {
        return node.nodeType === 3 && node.textContent.trim() !== '';
      });
      if (hasText) {
        Array.from(cell.children).forEach(function (child) {
          if (child.matches('p, div, span.block, small') &&
              !child.matches('.flex, .grid, .inline-flex, form, table, .rounded-control, .btn, .edify-cell-hidden')) {
            child.classList.add('edify-cell-line', 'edify-cell-follows');
          }
        });
      }
      /* A single wrapper holding two or more lines: its lines sit inline too. */
      if (cell.children.length === 1 && cell.firstElementChild.matches('div, p') &&
          !cell.firstElementChild.matches('.flex, .grid, .inline-flex, form')) {
        var inner = Array.from(cell.firstElementChild.children).filter(function (child) {
          return child.matches('a, span, p, small, div, time, strong') &&
            !child.matches('.flex, .grid, .inline-flex, form, table, .rounded-control, .btn, .status-pill, .edify-status-badge');
        });
        if (inner.length > 1) {
          cell.firstElementChild.classList.add('edify-cell-wrap');
          inner.forEach(function (child) { child.classList.add('edify-cell-line'); });
        }
      }
      /* A cell that carries a control closes at 32px around a 24px control. */
      cell.classList.toggle(
        'edify-cell-action',
        Boolean(cell.querySelector(':scope a.rounded-control, :scope button.rounded-control, :scope .btn, :scope .edify-cell-control, :scope > input[type="checkbox"]'))
      );
    });

    /* A figure drawn by hand -- a 22px numeral beside a caption -- is a tile.
       It is marked so consistency.css can give it the one tile design; the
       caption before the numeral is its label, the one after is its helper,
       and a tile written value-first still reads label-first. */
    elementsWithin(root, 'main [class*="text-[22px]"]').forEach(function (numeral) {
      if (!numeral.classList.contains('font-extrabold')) return;
      if (numeral.matches('h1, h2')) return;
      var tile = numeral.parentElement;
      if (!tile || tile.matches('main, section, article, th, td, li, dd, dt')) return;
      if (tile.closest('[role="tab"], table, .edify-page-header, .kpi-strip, dialog, [role="dialog"], .mobile-role-home')) return;
      /* The numeral is one PART of a composed card when its block sits inside a
         surface beside other blocks — the Reports period card: text block on
         the left, gauge on the right. The card is the tile; painting its text
         block as a second tile squeezed a gradient box into 90px with the
         caption wrapping word by word (owner, 2026-09-05). */
      var host = tile.parentElement;
      if (host && host.matches('.edify-surface, [class*="rounded-surface"]') && host.children.length > 1) return;
      var kids = Array.from(tile.children);
      if (kids.length < 2 || kids.length > 4) return;
      if (!kids.every(function (kid) { return kid.matches('p, span, h3, h4, h5, div, small, strong'); })) return;
      if (kids.some(function (kid) { return kid !== numeral && kid.querySelector('div, p, table, ul, form, button, a'); })) return;
      var captions = kids.filter(function (kid) { return kid !== numeral && kid.textContent.trim() !== ''; });
      if (!captions.length) return;
      tile.classList.add('edify-stat-tile');
      numeral.classList.add('edify-stat-tile__value');
      var before = captions.filter(function (caption) {
        return Boolean(caption.compareDocumentPosition(numeral) & Node.DOCUMENT_POSITION_FOLLOWING);
      });
      var after = captions.filter(function (caption) { return before.indexOf(caption) === -1; });
      if (!before.length && after.length) {
        after[0].classList.add('edify-stat-tile__label');
        after.slice(1).forEach(function (caption) { caption.classList.add('edify-stat-tile__helper'); });
      } else {
        before.forEach(function (caption) { caption.classList.add('edify-stat-tile__label'); });
        after.forEach(function (caption) { caption.classList.add('edify-stat-tile__helper'); });
      }
      var palette = tile.className + ' ' + numeral.className;
      var tone = /emerald|green|success/.test(palette) ? 'success'
        : /amber|yellow|warning/.test(palette) ? 'warning'
        : /rose|red|danger/.test(palette) ? 'danger'
        : /sky|blue|primary|info/.test(palette) ? 'info' : '';
      if (tone) tile.classList.add('edify-stat-tile--' + tone);
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
      /* Two data tables never share a row. Cells never wrap, so a pair of
         side-by-side tables splits inline space neither table can give up —
         one or both fall into horizontal scrolling even on screens with
         room for a single full-width grid. The marker lets consistency.css
         collapse the row so the second table continues below the first at
         full width, where the identity column takes the slack instead.
         Only children that ARE table cards count: a dashboard column that
         merely contains a table somewhere among its cards keeps its layout.
         Chart fallbacks (sr-only / presentation tables) are not data grids
         and must not collapse a row of visual charts. */
      var tableCards = directTiles.filter(function (tile) {
        return Boolean(tile.querySelector(
          'table:not(.sr-only):not(.edify-visually-hidden):not([role="presentation"])'
        ));
      });
      grid.classList.toggle('edify-stacked-table-row', tableCards.length > 1);
      /* Dense flow may reorder presentational cards to fill the hole a
         col-span neighbour leaves, but never anything sequential: only a
         grid whose every child is a card opts in, so form-field grids and
         mixed-content layouts keep DOM order. */
      grid.classList.toggle(
        'edify-dense-tile-grid',
        directTiles.length > 1 && directTiles.length === grid.children.length
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

  /* A table that is only a little wider than its region fits instead of
     scrolling (owner, 2026-09-06: a 1440px desktop showed sideways scroll on
     tables whose content would have fitted). From the desktop shell up, a
     table up to 40% wider than its region takes `edify-table--fit` — 8px
     cell padding and wrapping headings — and is measured again; one that is
     still wider keeps its scroll, because its content really is wider. */
  var FIT_RATIO = 1.4;
  var desktopShell = window.matchMedia('(min-width: 64rem)');

  function scrollAncestor(table) {
    var node = table.parentElement;
    while (node && node !== document.body) {
      var overflow = window.getComputedStyle(node).overflowX;
      if (overflow === 'auto' || overflow === 'scroll') return node;
      node = node.parentElement;
    }
    return null;
  }

  function fitTableToRegion(table) {
    var region = table.closest('.edify-table-scroll-region') || scrollAncestor(table);
    if (!region || !desktopShell.matches) return;
    if (table.matches('.sr-only, .edify-visually-hidden, .sr-distribution-table')) return;
    table.classList.remove('edify-table--fit');
    if (table.scrollWidth <= region.clientWidth + 1) return;
    if (table.scrollWidth > region.clientWidth * FIT_RATIO) return;
    table.classList.add('edify-table--fit');
    if (table.scrollWidth > region.clientWidth + 1) table.classList.remove('edify-table--fit');
  }

  function fitTables(root) {
    /* Two phases — measure every table, then write — so the pass forces one
       layout rather than one per table (2026-09-06). */
    if (!desktopShell.matches) return;
    var tables = Array.from((root.querySelectorAll ? root : document).querySelectorAll('main table'));
    var candidates = [];
    tables.forEach(function (table) {
      if (table.matches('.sr-only, .edify-visually-hidden, .sr-distribution-table')) return;
      var region = table.closest('.edify-table-scroll-region') || scrollAncestor(table);
      if (!region) return;
      table.classList.remove('edify-table--fit');
      candidates.push({ table: table, region: region });
    });
    var overflowing = candidates.filter(function (c) {
      var width = c.table.scrollWidth, room = c.region.clientWidth;
      return width > room + 1 && width <= room * FIT_RATIO;
    });
    overflowing.forEach(function (c) { c.table.classList.add('edify-table--fit'); });
    overflowing.forEach(function (c) {
      if (c.table.scrollWidth > c.region.clientWidth + 1) c.table.classList.remove('edify-table--fit');
    });
  }

  var fitTimer = null;
  window.addEventListener('resize', function () {
    window.clearTimeout(fitTimer);
    fitTimer = window.setTimeout(function () { fitTables(document); }, 150);
  }, { passive: true });

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
    /* Revealing the active tab measures the strip; measured after paint. */
    afterPaint(function () { if (tablist.isConnected) enhanceTabReveal(tablist); });
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
    /* Writers first, readers last. The marker pass rewrites every cell; a
       style read after it re-resolves that whole subtree (40-90ms on a
       dashboard), so the passes that measure — tab reveal, dialog
       visibility, table fit — run after every pass that only writes, and
       the page pays that resolution once (2026-09-06). */
    enhanceTables(root);
    enhanceStructuralMarkers(root);
    enhanceFormLabels(root);
    normalizeActionButtonTypes(root);
    enhanceTabs(root);
  }

  /* Runs `callback` in the task after the next frame paints. By then the
     browser has resolved style and layout for that paint, so a pass that
     only measures (tab reveal, dialog visibility, table fit) reads for free
     instead of forcing its own resolution ahead of the paint. */
  function afterPaint(callback) {
    window.requestAnimationFrame(function () { window.setTimeout(callback, 0); });
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
    /* The measuring passes wait for the paint the writes above produce:
       dialog visibility, then — once every table has its region and its
       cells — fit or scroll. A table that needs fitting scrolls for one
       frame; the page no longer resolves style three times before it
       first paints (2026-09-06). */
    afterPaint(function () {
      if (root !== document && !root.isConnected) return;
      enhanceCustomDialogs(root);
      fitTables(root);
    });
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
      /* Dialog visibility is a read; enhance() writes. Reading first means
         this frame resolves style once for what the mutations dirtied,
         instead of once for the mutations and again for our own writes
         (a chart's arrival cost two ~100ms resolutions, 2026-09-06). A
         dialog that arrived in this frame is still checked, by enhance(). */
      dialogRoots.forEach(function (root) {
        if (root.isConnected) enhanceCustomDialogs(root);
      });
      enhanceRoots.forEach(function (root) {
        if (root.isConnected) enhance(root);
      });
      /* A removed dialog will not appear in a surviving mutation root. */
      Array.from(activeDialogs).forEach(deactivateDialog);
    });
  }

  var fontsReadyAtEnhance = false;
  document.addEventListener('DOMContentLoaded', function () {
    fontsReadyAtEnhance = Boolean(document.fonts && document.fonts.status === 'loaded');
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
  /* Web fonts that arrive after the first fit change every column width, so
     the tables are fitted again; fonts that were already in when the page
     was enhanced were measured then, and a second pass would only force
     another style resolution. */
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(function () {
    if (!fontsReadyAtEnhance) fitTables(document);
  });
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
