/* Close the drawer which saved, never whichever drawer happens to be open
 * when its response arrives. GETs, previews and validation remain open. */
(function () {
  'use strict';
  if (window.EdifyDrawerSubmit) return;
  const requests = new WeakMap();
  const submitted = new WeakSet();
  const closing = new WeakSet();
  const rootSelector = '[data-edify-drawer], .edify-drawer-root, .edify-popup-dialog';

  function drawerFor(element) {
    if (!element?.closest) return null;
    const root = element.closest(rootSelector);
    if (root) return root;
    const host = element.closest('#drawer-container');
    if (!host) return null;
    let child = element;
    while (child.parentElement && child.parentElement !== host) child = child.parentElement;
    return child === host ? null : child;
  }

  function hasCloseTrigger(xhr) {
    return ['HX-Trigger', 'HX-Trigger-After-Swap', 'HX-Trigger-After-Settle'].some(header => {
      const raw = xhr.getResponseHeader(header);
      if (!raw) return false;
      try {
        const parsed = JSON.parse(raw);
        if (typeof parsed === 'string') return parsed === 'close-drawer';
        return parsed && Object.prototype.hasOwnProperty.call(parsed, 'close-drawer');
      } catch (_) { return raw.split(',').some(name => name.trim() === 'close-drawer'); }
    });
  }

  function savedResponse(xhr) {
    if (xhr.status < 200 || xhr.status >= 300) return false;
    if (hasCloseTrigger(xhr)) return true; // explicit server completion contract
    const text = (xhr.responseText || '').trim();
    if (!text || xhr.status === 204) return true;
    if (/json/i.test(xhr.getResponseHeader('Content-Type') || '')) {
      try {
        const result = JSON.parse(text);
        return result.success === true || result.saved === true;
      } catch (_) { return false; }
    }
    const response = new DOMParser().parseFromString(text, 'text/html');
    // A returned form is validation or another step, not final completion.
    if (response.querySelector('form, [aria-invalid="true"], .errorlist, .invalid-feedback, [data-form-errors], [data-drawer-stay-open], [role="alert"]')) return false;
    if (response.querySelector('[data-tone="error"], [data-tone="danger"], .text-rose-700, .text-red-700, .alert-danger')) return false;
    return true;
  }

  function closeSaved(root) {
    if (!root?.isConnected || closing.has(root)) return;
    closing.add(root);
    const host = root.closest('#drawer-container');
    let focus = null;
    if (window.Alpine && root._x_dataStack) {
      const state = window.Alpine.$data(root);
      focus = state.previousFocus;
      if ('isDirty' in state) state.isDirty = false;
      if ('confirmDiscard' in state) state.confirmDiscard = false;
      if ('active' in state) state.active = false;
      if ('open' in state) state.open = false;
    }
    root.dataset.drawerSaved = 'true';
    // The root reference is captured, so this cannot remove a replacement.
    window.setTimeout(() => {
      root.remove();
      const another = host?.querySelector(rootSelector);
      if (!another && (!host || host.children.length === 0)) {
        window.__edifyDrawerBackground?.sync();
        if (focus?.isConnected) focus.focus();
      }
    }, 300);
  }

  document.addEventListener('submit', event => {
    if (drawerFor(event.target)) submitted.add(event.target);
  }, true);

  document.addEventListener('htmx:beforeRequest', event => {
    const detail = event.detail || {};
    const source = detail.elt || event.target;
    const root = drawerFor(source);
    if (!root || !detail.xhr) return;
    const form = source.matches?.('form') ? source : source.closest?.('form');
    const verb = String(detail.requestConfig?.verb || '').toLowerCase();
    const trigger = detail.requestConfig?.triggeringEvent;
    const preview = /\/(preview|validate|options|search)(?:[/?]|$)/.test(detail.requestConfig?.path || '');
    const isSubmit = (source === form && (submitted.has(form) || trigger?.type === 'submit')) ||
      source.matches?.('button[type="submit"], input[type="submit"]');
    if (form && source === form) submitted.delete(form);
    const request = {root, host: root.closest('#drawer-container'), form, source,
      mutation: !preview && ['post', 'put', 'patch', 'delete'].includes(verb), isSubmit};
    // Listen on the source as well as tracking the XHR: once a drawer has
    // been replaced, events on its old form no longer reach document.
    const guardResponse = responseEvent => {
      if (responseEvent.detail?.xhr !== detail.xhr) return;
      if (!root.isConnected && request.host?.childElementCount) {
        // A late OOB clear, redirect or retarget must not replace a new drawer.
        responseEvent.preventDefault();
      }
    };
    source.addEventListener('htmx:beforeOnLoad', guardResponse);
    request.cleanup = () => source.removeEventListener('htmx:beforeOnLoad', guardResponse);
    requests.set(detail.xhr, request);
  });

  // HTMX's server event may bubble from a detached/replaced request element.
  // Handle it by XHR below instead of letting it close a newer drawer globally.
  document.addEventListener('close-drawer', event => {
    if (event.detail?.elt) event.stopImmediatePropagation();
  }, true);

  document.addEventListener('htmx:afterRequest', event => {
    const detail = event.detail || {};
    const xhr = detail.xhr;
    const request = xhr && requests.get(xhr);
    if (!request) return;
    requests.delete(xhr);
    request.cleanup();
    if (!request.mutation || detail.failed || xhr.status < 200 || xhr.status >= 300) return;
    if (request.form?.hasAttribute('data-drawer-stay-open') || request.source?.hasAttribute('data-drawer-stay-open')) return;
    if ((hasCloseTrigger(xhr) || request.isSubmit) && savedResponse(xhr)) closeSaved(request.root);
  });

  window.EdifyDrawerSubmit = Object.freeze({closeSaved, savedResponse, hasCloseTrigger});
})();
