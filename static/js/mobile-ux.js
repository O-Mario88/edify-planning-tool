/* Edify mobile UX foundation.
 *
 * Server-rendered HTML remains the source of truth. This file supplies native
 * dialog orchestration, Safari light-dismiss fallback, focus restoration, and
 * privacy-safe product measurement hooks. It never owns workflow data.
 */
(function () {
  'use strict';

  var sessionStartedAt = performance.now();
  var reachedDepth = new Set();
  var dialogOpeners = new WeakMap();
  var desktopFilterQuery = window.matchMedia('(min-width: 64rem)');

  function emit(name, detail) {
    var payload = Object.assign({
      name: name,
      path: window.location.pathname,
      elapsedMs: Math.round(performance.now() - sessionStartedAt),
      viewport: window.innerWidth < 768 ? 'mobile' : (window.innerWidth < 1024 ? 'tablet' : 'desktop')
    }, detail || {});

    window.dispatchEvent(new CustomEvent('edify:mobile-ux', { detail: payload }));
    if (window.performance && typeof window.performance.mark === 'function') {
      performance.mark('edify-mobile-ux:' + name);
    }
  }

  function dialogById(id) {
    if (!id) return null;
    var dialog = document.getElementById(id);
    return dialog && dialog.tagName === 'DIALOG' ? dialog : null;
  }

  function openDialog(trigger) {
    var dialog = dialogById(trigger.getAttribute('data-mobile-dialog-open'));
    if (!dialog || dialog.open) return;
    dialogOpeners.set(dialog, trigger);
    if (typeof dialog.showModal === 'function') dialog.showModal();
    else dialog.setAttribute('open', '');
    emit('filter-sheet-open', { id: dialog.id });
  }

  function closeDialog(button) {
    var dialog = button.closest('dialog');
    if (!dialog) return;
    if (typeof dialog.close === 'function') dialog.close();
    else {
      dialog.removeAttribute('open');
      restoreDialogFocus(dialog);
    }
  }

  function restoreDialogFocus(dialog) {
    var opener = dialogOpeners.get(dialog);
    if (opener && opener.isConnected) opener.focus();
    dialogOpeners.delete(dialog);
  }

  function enhanceDialogs(root) {
    root.querySelectorAll('dialog[data-mobile-sheet]').forEach(function (dialog) {
      if (dialog.dataset.mobileSheetReady === 'true') return;
      dialog.dataset.mobileSheetReady = 'true';
      dialog.addEventListener('close', function () {
        restoreDialogFocus(dialog);
        emit('filter-sheet-close', { id: dialog.id });
      });

      /* `closedby` is not supported in Safari yet. A backdrop click targets
         the dialog itself; checking its content rectangle prevents clicks on
         the sheet's own padding/background from closing it. */
      if (typeof HTMLDialogElement === 'undefined' || !('closedBy' in HTMLDialogElement.prototype)) {
        dialog.addEventListener('click', function (event) {
          if (event.target !== dialog) return;
          var rect = dialog.getBoundingClientRect();
          var inside = rect.top <= event.clientY && event.clientY <= rect.bottom &&
            rect.left <= event.clientX && event.clientX <= rect.right;
          if (!inside && typeof dialog.close === 'function') dialog.close();
        });
      }
    });
  }

  /* Render disclosures open for desktop/no-JavaScript access, then collapse
     them on phones. Crossing the breakpoint keeps visible and semantic state
     aligned instead of relying on CSS to imitate a closed details element. */
  function syncFamilyFilters(root) {
    root.querySelectorAll('details.mobile-family-filter').forEach(function (details) {
      details.open = desktopFilterQuery.matches;
    });
  }

  function noteFirstAction() {
    var first = document.querySelector('[data-mobile-primary-action], [data-mobile-action]');
    if (!first) return;
    var rect = first.getBoundingClientRect();
    document.documentElement.dataset.mobileFirstActionTop = String(Math.round(rect.top + window.scrollY));
    emit('first-action-ready', {
      top: Math.round(rect.top + window.scrollY),
      inFirstViewport: rect.top >= 0 && rect.top <= window.innerHeight
    });
  }

  function noteScrollDepth() {
    var root = document.querySelector('.edify-workspace') || document.scrollingElement;
    if (!root) return;
    var available = root.scrollHeight - root.clientHeight;
    if (available <= 0) return;
    var depth = Math.round((root.scrollTop / available) * 100);
    [25, 50, 75, 100].forEach(function (threshold) {
      if (depth >= threshold && !reachedDepth.has(threshold)) {
        reachedDepth.add(threshold);
        emit('scroll-depth', { percent: threshold });
      }
    });
  }

  document.addEventListener('click', function (event) {
    var opener = event.target.closest('[data-mobile-dialog-open]');
    if (opener) {
      event.preventDefault();
      openDialog(opener);
      return;
    }

    var closer = event.target.closest('[data-mobile-dialog-close]');
    if (closer) {
      event.preventDefault();
      closeDialog(closer);
      return;
    }

    var action = event.target.closest('[data-mobile-action]');
    if (action) emit('action', { action: action.dataset.mobileAction || 'unknown' });
  });

  var scrollQueued = false;
  document.addEventListener('scroll', function () {
    if (scrollQueued) return;
    scrollQueued = true;
    requestAnimationFrame(function () {
      noteScrollDepth();
      scrollQueued = false;
    });
  }, { passive: true, capture: true });

  document.addEventListener('DOMContentLoaded', function () {
    enhanceDialogs(document);
    syncFamilyFilters(document);
    requestAnimationFrame(noteFirstAction);
  });

  document.addEventListener('htmx:afterSettle', function (event) {
    enhanceDialogs(event.target);
    syncFamilyFilters(event.target);
    requestAnimationFrame(noteFirstAction);
  });

  desktopFilterQuery.addEventListener('change', function () {
    syncFamilyFilters(document);
  });

  window.EdifyMobileUX = Object.freeze({
    emit: emit,
    enhanceDialogs: enhanceDialogs,
    syncFamilyFilters: syncFamilyFilters
  });
})();
