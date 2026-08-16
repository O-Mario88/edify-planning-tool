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
      'You can continue. Any action that did not finish still needs to be submitted.';
    banner.hidden = false;
    announce('Connection restored. You can continue.', 'polite');
    restoredTimer = window.setTimeout(function () { banner.hidden = true; }, 5000);
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
    if (navigator.onLine) return;
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
    }
  });

  window.EdifyPlatformStatus = Object.freeze({
    showOffline: showOffline,
    showRestored: showRestored,
    showSessionExpired: showSessionExpired
  });
})();
