/* Platform resilience states: visible connectivity and session-expiry UX.
 * The server remains authoritative; this layer prevents silent failure and
 * preserves the current DOM while a user reconnects or signs in again. */
(function () {
  'use strict';

  if (window.__edifyPlatformStatusInstalled) return;
  window.__edifyPlatformStatusInstalled = true;

  var restoredTimer = null;

  function announce(message, priority) {
    if (window.EdifyMicroUX) {
      window.EdifyMicroUX.announce(message, priority);
      return;
    }
    var id = priority === 'assertive' ? 'edify-live-assertive' : 'edify-live-polite';
    var target = document.getElementById(id);
    if (target) target.textContent = message;
  }

  function connectivityBanner() {
    return document.getElementById('edify-connectivity-status');
  }

  function showOffline() {
    window.clearTimeout(restoredTimer);
    var banner = connectivityBanner();
    if (!banner) return;
    banner.dataset.state = 'offline';
    banner.querySelector('[data-connectivity-title]').textContent = 'You are offline';
    banner.querySelector('[data-connectivity-detail]').textContent =
      'Changes cannot be sent. Keep this page open and reconnect to continue.';
    banner.hidden = false;
  }

  function showRestored() {
    var banner = connectivityBanner();
    if (!banner || banner.hidden) return;
    banner.dataset.state = 'restored';
    banner.querySelector('[data-connectivity-title]').textContent = 'Connection restored';
    banner.querySelector('[data-connectivity-detail]').textContent =
      'You can continue. Check whether your last action completed before submitting it again.';
    banner.hidden = false;
    announce('Connection restored. You can continue.', 'polite');
    restoredTimer = window.setTimeout(function () { banner.hidden = true; }, 5000);
  }

  var busyTimer = null;

  // The web process refused the request before it ran (apps.core.concurrency):
  // nothing was changed, and the same action succeeds once the peak passes.
  function showBusy(retryAfterSeconds) {
    var banner = connectivityBanner();
    if (!banner || banner.dataset.state === 'offline') return;
    window.clearTimeout(restoredTimer);
    window.clearTimeout(busyTimer);
    banner.dataset.state = 'busy';
    banner.querySelector('[data-connectivity-title]').textContent = 'The platform is busy';
    banner.querySelector('[data-connectivity-detail]').textContent =
      'Many people are working at once. Nothing was changed. Try again in a few seconds.';
    banner.hidden = false;
    announce('The platform is busy. Nothing was changed. Try again in a few seconds.', 'assertive');
    busyTimer = window.setTimeout(function () {
      if (banner.dataset.state === 'busy') banner.hidden = true;
    }, (Math.max(retryAfterSeconds || 0, 5) + 3) * 1000);
  }

  function showSessionExpired() {
    var dialog = document.getElementById('edify-session-expired-dialog');
    if (!dialog || dialog.open) return;
    if (typeof dialog.showModal === 'function') dialog.showModal();
    else dialog.setAttribute('open', '');
    announce('Your session expired. Sign in to continue. Your current page remains open.', 'assertive');
  }

  function responseIsLogin(xhr) {
    if (!xhr || !xhr.responseURL) return false;
    try {
      return new URL(xhr.responseURL, window.location.href).pathname === '/login';
    } catch (error) {
      return false;
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    var close = document.querySelector('[data-session-dialog-close]');
    if (close) close.addEventListener('click', function () {
      var dialog = document.getElementById('edify-session-expired-dialog');
      if (dialog && typeof dialog.close === 'function') dialog.close();
      else if (dialog) dialog.removeAttribute('open');
    });
    if (!navigator.onLine) showOffline();
  });

  window.addEventListener('offline', function () {
    showOffline();
    announce('You are offline. Changes cannot be sent until you reconnect.', 'assertive');
  });
  window.addEventListener('online', showRestored);

  document.addEventListener('htmx:beforeRequest', function (event) {
    // The upload drawer opens offline: sw.js answers it.
    if (navigator.onLine || /^\/activities\/[^/]+\/evidence$/.test(event.detail.pathInfo.requestPath)) return;
    event.preventDefault();
    showOffline();
    announce('This action was not sent because you are offline. Reconnect and try again.', 'assertive');
  });

  document.addEventListener('htmx:beforeSwap', function (event) {
    var xhr = event.detail && event.detail.xhr;
    if (!xhr) return;
    if (xhr.status === 401 || xhr.status === 419 || responseIsLogin(xhr)) {
      event.detail.shouldSwap = false;
      event.detail.isError = false;
      showSessionExpired();
      return;
    }
    if (xhr.status === 503 && xhr.getResponseHeader('Retry-After')) {
      event.detail.shouldSwap = false;
      event.detail.isError = false;
      showBusy(parseInt(xhr.getResponseHeader('Retry-After'), 10));
    }
  });

  function showRequestError(event) {
    var xhr = event.detail && event.detail.xhr;
    if (xhr && (xhr.status === 401 || xhr.status === 419 || responseIsLogin(xhr) ||
        (xhr.status === 503 && xhr.getResponseHeader('Retry-After')))) return;
    var notice = document.getElementById('edify-request-error');
    if (!notice) {
      notice = document.createElement('div');
      notice.id = 'edify-request-error';
      notice.className = 'edify-request-error';
      notice.setAttribute('role', 'alert');
      var copy = document.createElement('p');
      copy.setAttribute('data-request-error-copy', '');
      var dismiss = document.createElement('button');
      dismiss.type = 'button';
      dismiss.className = 'btn btn-secondary';
      dismiss.textContent = 'Dismiss';
      dismiss.addEventListener('click', function () { notice.remove(); });
      notice.append(copy, dismiss);
      document.body.appendChild(notice);
    }
    var message = event.type === 'htmx:timeout' ? 'The request took too long.' :
      event.type === 'htmx:sendError' ? 'The connection was interrupted.' : 'The request could not be completed.';
    notice.querySelector('[data-request-error-copy]').textContent =
      message + ' Your current entries remain on this page. Check whether the action completed before trying again.';
  }
  ['htmx:responseError', 'htmx:sendError', 'htmx:timeout'].forEach(function (name) {
    document.addEventListener(name, showRequestError);
  });

  window.EdifyPlatformStatus = Object.freeze({
    showOffline: showOffline,
    showRestored: showRestored,
    showSessionExpired: showSessionExpired,
    showBusy: showBusy
  });
})();
