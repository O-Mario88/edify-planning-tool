/* Phone notifications in the page (owner, 2026-10-10; apps.notifications.push).
 *
 * The server pushes each notification to the devices a user subscribed on,
 * and the service worker (/sw.js) shows it in the phone's tray. This is the
 * page's half:
 *
 *  - the control that turns notifications on for this device and says, in
 *    words, why it cannot when it cannot (blocked in the browser, not
 *    installed on an iPhone, not set up on this server);
 *  - keeping the server's copy of this device's subscription current, since
 *    a browser may replace it at any time;
 *  - the foreground: when a notification arrives while the app is being
 *    looked at, the bell count moves and one line says what arrived, in
 *    place of a tray notification;
 *  - clearing from the tray what was read somewhere else, and everything on
 *    sign-out, when the device also stops being sent the user's notices.
 *
 * Controls are plain attributes, so any page or drawer can carry them:
 *   [data-push-toggle]   a button: "Turn on phone notifications" / "Turn off"
 *   [data-push-status]   the sentence beside it
 */
(function () {
  'use strict';
  if (window.EdifyPush) return;
  var doc = document, nav = navigator;
  var API = '/api/notifications/push/';
  var OFF_KEY = 'edify-push-off', SYNCED_KEY = 'edify-push-synced';
  var config = null, busy = false, lastCount = null;

  function supported() {
    return 'serviceWorker' in nav && 'PushManager' in window && 'Notification' in window;
  }

  // An iPhone or iPad delivers web notifications only to an app added to
  // the Home Screen, never to a Safari tab.
  function needsInstall() {
    var apple = /iPhone|iPad|iPod/.test(nav.userAgent) || (nav.platform === 'MacIntel' && nav.maxTouchPoints > 1);
    var standalone = (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches) || nav.standalone === true;
    return apple && !standalone;
  }

  function token() {
    var match = doc.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : '';
  }

  function call(path, body, keepalive) {
    return fetch(API + path, {
      method: body ? 'POST' : 'GET',
      credentials: 'same-origin',
      keepalive: !!keepalive,
      headers: body ? { 'Content-Type': 'application/json', 'X-CSRFToken': token() } : {},
      body: body ? JSON.stringify(body) : undefined,
    }).then(function (res) {
      if (!res.ok && res.status !== 409 && res.status !== 400) throw new Error('push ' + res.status);
      return res.json();
    });
  }

  function keyBytes(key) {
    var padded = key + '==='.slice(0, (4 - (key.length % 4)) % 4);
    var text = atob(padded.replace(/-/g, '+').replace(/_/g, '/'));
    var bytes = new Uint8Array(text.length);
    for (var i = 0; i < text.length; i += 1) bytes[i] = text.charCodeAt(i);
    return bytes;
  }

  function registration() {
    return nav.serviceWorker.ready;
  }

  function current() {
    if (!supported()) return Promise.resolve(null);
    return registration().then(function (reg) { return reg.pushManager.getSubscription(); });
  }

  function loadConfig() {
    if (config) return Promise.resolve(config);
    return call('config').then(function (data) { config = data; return data; });
  }

  // What this device can do, in one word (the status sentence is made of it).
  function state() {
    if (!supported()) return Promise.resolve(needsInstall() ? 'install' : 'unsupported');
    if (needsInstall()) return Promise.resolve('install');
    return loadConfig().then(function (data) {
      if (!data.enabled) return 'unavailable';
      if (Notification.permission === 'denied') return 'blocked';
      return current().then(function (sub) { return sub ? 'on' : 'off'; });
    }).catch(function () { return 'offline'; });
  }

  var WORDS = {
    on: ['Turn off on this device', 'On for this device: you are told here even when Edify is closed.'],
    off: ['Turn on phone notifications', 'Off for this device. Turn on to be told here even when Edify is closed.'],
    blocked: ['', 'Blocked in this browser. Allow notifications for Edify in the browser or phone settings, then come back.'],
    install: ['', 'On an iPhone or iPad, add Edify to the Home Screen (Share, then Add to Home Screen) and open it from there to get notifications.'],
    unsupported: ['', 'This browser cannot show phone notifications. The bell still holds every notification.'],
    unavailable: ['', 'Phone notifications are not set up on this server yet. The bell still holds every notification.'],
    offline: ['', 'Phone notifications could not be checked just now. Try again when you are back online.'],
  };

  function paint() {
    var toggles = doc.querySelectorAll('[data-push-toggle]'), notes = doc.querySelectorAll('[data-push-status]');
    if (!toggles.length && !notes.length) return;
    state().then(function (now) {
      var words = WORDS[now] || WORDS.offline;
      Array.prototype.forEach.call(toggles, function (button) {
        button.hidden = !words[0];
        button.textContent = words[0];
        button.setAttribute('data-push-state', now);
        button.disabled = busy;
      });
      Array.prototype.forEach.call(notes, function (note) {
        note.textContent = words[1];
        note.setAttribute('data-push-state', now);
      });
    });
  }

  function record(sub, announce) {
    var json = sub.toJSON();
    return call('subscribe', { endpoint: json.endpoint, keys: json.keys, announce: !!announce }).then(function (res) {
      try { localStorage.setItem(SYNCED_KEY, json.endpoint + '|' + Date.now()); } catch (_) { /* private mode */ }
      return res;
    });
  }

  function enable() {
    if (busy) return Promise.resolve();
    busy = true; paint();
    return Notification.requestPermission().then(function (permission) {
      if (permission !== 'granted') return null;
      return loadConfig().then(function (data) {
        if (!data.enabled) return null;
        return registration().then(function (reg) {
          return reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(data.key) });
        }).then(function (sub) {
          try { localStorage.removeItem(OFF_KEY); } catch (_) { /* private mode */ }
          return record(sub, true);
        });
      });
    }).catch(function (error) {
      announce('Phone notifications could not be turned on: ' + ((error && error.message) || 'try again') + '.');
    }).then(function () { busy = false; paint(); });
  }

  function disable(reason) {
    return current().then(function (sub) {
      if (!sub) return null;
      var endpoint = sub.endpoint;
      return sub.unsubscribe().catch(function () { return false; }).then(function () {
        return call('unsubscribe', { endpoint: endpoint, reason: reason || '' }, reason === 'signed_out');
      });
    }).catch(function () { return null; });
  }

  // The browser may hand out a new subscription at any time; the server's
  // copy is refreshed once a day, and at once when the worker says so.
  function sync(force) {
    if (!supported() || needsInstall() || Notification.permission !== 'granted') return;
    var off = false;
    try { off = localStorage.getItem(OFF_KEY) === '1'; } catch (_) { /* private mode */ }
    if (off) return;
    loadConfig().then(function (data) {
      if (!data.enabled) return null;
      tidy(data.unread);
      return current().then(function (sub) {
        if (!sub) return null;
        var seen = '';
        try { seen = localStorage.getItem(SYNCED_KEY) || ''; } catch (_) { /* private mode */ }
        var parts = seen.split('|');
        if (!force && parts[0] === sub.endpoint && Date.now() - Number(parts[1] || 0) < 86400000) return null;
        return record(sub, false);
      });
    }).catch(function () { /* offline: the next page tries again */ });
  }

  // What this device's tray still shows but was read somewhere else.
  function tidy(unread, clear) {
    if (!nav.serviceWorker || !nav.serviceWorker.controller) return;
    nav.serviceWorker.controller.postMessage({ type: 'edify-notifications-sync', unread: unread || [], clear: !!clear });
  }

  // ── The foreground ────────────────────────────────────────────────────
  function badge(count) {
    var host = doc.getElementById('notification-badge-container');
    if (!host || count === lastCount) return;
    lastCount = count;
    host.textContent = '';
    if (count > 0) {
      var mark = doc.createElement('span');
      mark.id = 'notification-badge-count';
      mark.className = 'notification-badge absolute top-1 right-1';
      mark.textContent = count > 99 ? '99+' : String(count);
      host.appendChild(mark);
    }
  }

  function recount() {
    if (doc.hidden || !doc.getElementById('notification-badge-container')) return;
    fetch('/api/notifications/unread-count', { credentials: 'same-origin' })
      .then(function (res) { return res.ok ? res.json() : null; })
      .then(function (data) { if (data && typeof data.count === 'number') badge(data.count); })
      .catch(function () { /* offline */ });
  }

  // One line in the page's own message area, with the way to the record.
  function announce(text, url) {
    var host = doc.getElementById('toast-container');
    if (!host) return;
    var line = doc.createElement('div');
    line.className = 'pointer-events-auto flex items-center justify-between gap-3 px-4 py-3 rounded-surface border shadow-lg max-w-sm text-[12px] font-semibold edify-surface edify-border edify-text';
    line.setAttribute('role', 'status');
    line.setAttribute('data-push-line', '');
    var words = doc.createElement(url ? 'a' : 'span');
    if (url) words.href = url;
    words.textContent = text;
    var close = doc.createElement('button');
    close.type = 'button';
    close.className = 'text-current opacity-70 hover:opacity-100 -my-1 -mr-2 flex h-8 w-8 shrink-0 items-center justify-center text-[16px]';
    close.setAttribute('aria-label', 'Dismiss notification');
    close.textContent = '×';
    close.addEventListener('click', function () { line.remove(); });
    line.appendChild(words); line.appendChild(close);
    host.appendChild(line);
    setTimeout(function () { line.remove(); }, 8000);
  }

  if (nav.serviceWorker) {
    nav.serviceWorker.addEventListener('message', function (event) {
      var data = event.data || {};
      if (data.type === 'edify-push-resubscribe') { sync(true); return; }
      if (data.type !== 'edify-notification') return;
      recount();
      // The tray said it already unless this page was the one in front.
      if (!data.shown && !doc.hidden) announce(data.title + (data.body ? ': ' + data.body : ''), data.url);
    });
  }

  doc.addEventListener('click', function (event) {
    var button = event.target.closest && event.target.closest('[data-push-toggle]');
    if (!button) return;
    event.preventDefault();
    if (button.getAttribute('data-push-state') === 'on') {
      busy = true; paint();
      try { localStorage.setItem(OFF_KEY, '1'); } catch (_) { /* private mode */ }
      disable('').then(function () { busy = false; paint(); });
    } else {
      enable();
    }
  });

  // A notification opens its record directly (owner, 2026-10-10: "open the
  // link direct not go through notification page"): the click is not held
  // up or sent round by an address of its own; it is marked read by a
  // request that outlives the page being left.
  doc.addEventListener('click', function (event) {
    var item = event.target.closest && event.target.closest('[data-notification-read]');
    if (!item || event.target.closest('button')) return;
    fetch('/api/notifications/' + encodeURIComponent(item.getAttribute('data-notification-read')) + '/read', {
      method: 'PATCH', credentials: 'same-origin', keepalive: true, headers: { 'X-CSRFToken': token() },
    }).catch(function () { /* still unread: it stays in the bell */ });
  }, true);

  // Signing out on a device ends that device's notifications: the next
  // person to use it must not be told the last one's work.
  doc.addEventListener('submit', function (event) {
    var form = event.target;
    if (!form || !form.matches || !form.matches('form[action="/logout"]') || form.dataset.pushCleared) return;
    if (!supported() || Notification.permission !== 'granted') return;
    event.preventDefault();
    form.dataset.pushCleared = '1';
    tidy([], true);
    var done = false;
    function go() { if (!done) { done = true; form.submit(); } }
    disable('signed_out').then(go, go);
    setTimeout(go, 1500);
  }, true);

  doc.addEventListener('visibilitychange', function () { if (!doc.hidden) recount(); });
  doc.addEventListener('htmx:afterSettle', paint);
  setInterval(recount, 90000);
  function start() { paint(); sync(false); }
  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', start); else start();

  window.EdifyPush = Object.freeze({ state: state, enable: enable, disable: disable, sync: sync });
})();
