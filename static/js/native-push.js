/* Push in the Edify app on a phone (brief, 2026-10-23; apps.notifications.fcm).
 *
 * The app's web view cannot use Web Push, so in the app (the server sends
 * this script only when the user agent says EdifyApp, and only on signed-in
 * pages) the phone's own push service is used through Capacitor's
 * PushNotifications plugin: Firebase on Android, Apple's push service by way
 * of Firebase on an iPhone.
 *
 *  - After sign-in, once, the page says what notifications are for and
 *    offers to turn them on; only then does the phone ask its own question.
 *    When allowed, the app registers and hands the server its device token,
 *    for whoever is signed in.
 *  - A tap on a notification opens its record inside the app.
 *  - While the app is open, an arriving notification moves the bell and says
 *    what arrived in the page (push-notifications.js), not in the tray.
 *  - Signing out ends this phone's notifications for that person.
 *  - The phone's own notification setting for Edify is the one switch
 *    (owner, 2026-10-25): allowed there, notifications are on; the page
 *    offers the way to that setting and has no off switch of its own, and
 *    coming back from it picks up the new answer.
 *
 * The page's device control ([data-push-toggle], push-notifications.js)
 * drives this through window.EdifyAppPush.
 */
(function () {
  'use strict';
  if (window.EdifyAppPush) return;
  var cap = window.Capacitor;
  if (!cap || typeof cap.isNativePlatform !== 'function' || !cap.isNativePlatform()) return;
  var PushNotifications = cap.Plugins && cap.Plugins.PushNotifications;
  if (!PushNotifications) return; // an app build from before push was added
  var doc = document;
  var REGISTER = '/api/notifications/push/app/register';
  var UNREGISTER = '/api/notifications/push/app/unregister';
  var ASKED_KEY = 'edify-app-push-asked', TOKEN_KEY = 'edify-app-push-token';
  var DAY = 86400000;
  var platform = typeof cap.getPlatform === 'function' ? cap.getPlatform() : '';
  var script = doc.currentScript;
  var user = (script && script.getAttribute('data-user')) || '';
  var failed = false, configured = null;

  // Whether this build of the app can receive notifications at all. An
  // Android build reaches Firebase only when it was built with
  // google-services.json, and without it asking Firebase for a token closes
  // the app, so Android asks its native plugin first (EdifySettingsPlugin's
  // pushReady). An iPhone build always can: it hands over Apple's own token.
  var buildReady = (function () {
    if (platform !== 'android') return Promise.resolve(true);
    var settings = (cap.Plugins || {}).EdifySettings;
    if (!settings || typeof settings.pushReady !== 'function') return Promise.resolve(false);
    return settings.pushReady().then(function (r) { return !!(r && r.ready); }, function () { return false; });
  })();

  function read(key) { try { return localStorage.getItem(key) || ''; } catch (_) { return ''; } }
  function write(key, value) { try { localStorage.setItem(key, value); } catch (_) { /* private mode */ } }
  function forget(key) { try { localStorage.removeItem(key); } catch (_) { /* private mode */ } }
  function noop() { return null; }

  function csrf() {
    var match = doc.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : '';
  }

  function call(url, body, keepalive) {
    return fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      keepalive: !!keepalive,
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
      body: JSON.stringify(body),
    }).then(function (res) {
      if (res.status === 409) configured = false;
      return res.json().catch(noop);
    });
  }

  // "token|user|when": the token this phone last gave the server, and for whom.
  function remembered() {
    var parts = read(TOKEN_KEY).split('|');
    return { token: parts[0] || '', user: parts[1] || '', at: Number(parts[2] || 0) };
  }

  function repaint() { if (window.EdifyPush && window.EdifyPush.paint) window.EdifyPush.paint(); }

  function record(token) {
    if (!token) return;
    var seen = remembered();
    // Refreshed once a day, and at once for another person or a new token.
    if (seen.token === token && seen.user === user && Date.now() - seen.at < DAY) return;
    call(REGISTER, { token: token, platform: platform }).then(function (res) {
      failed = !(res && res.ok) && configured !== false;
      if (res && res.ok) write(TOKEN_KEY, token + '|' + user + '|' + Date.now());
      repaint();
    }).catch(function () { /* offline: the next page tries again */ });
  }

  // Where a tap goes: only this application's own pages.
  function open(url) {
    var safe = typeof url === 'string' && url.charAt(0) === '/' && url.charAt(1) !== '/';
    window.location.assign(safe ? url : '/notifications');
  }

  function permission() {
    return PushNotifications.checkPermissions().then(function (p) { return p.receive; });
  }

  function register() {
    return buildReady.then(function (ready) {
      return ready ? PushNotifications.register() : null;
    }).catch(function () { failed = true; repaint(); });
  }

  // ── What the page's switch asks ──────────────────────────────────────────
  function state() {
    if (configured === false) return Promise.resolve('unavailable');
    return buildReady.then(function (ready) {
      return ready ? permission() : 'app-unavailable';
    }).then(function (receive) {
      if (receive === 'app-unavailable') return receive;
      if (receive === 'denied') return 'app-blocked';
      if (receive !== 'granted') return 'off';
      return failed ? 'app-error' : 'app-on';
    }).catch(function () { return 'app-error'; });
  }

  function enable() {
    failed = false;
    return buildReady.then(function (ready) {
      // The phone is not asked for notifications this build cannot receive.
      return ready ? PushNotifications.requestPermissions() : null;
    }).then(function (p) {
      return p && p.receive === 'granted' ? register() : null;
    }).catch(noop);
  }

  // Edify's own notification settings on the phone, through the app's small
  // native plugin (iPhone: EdifyBridgeViewController.swift; Android:
  // MainActivity), which lands on Edify's page itself. An iPhone build from
  // before the plugin falls back to the app's page in Settings.
  function openSettings() {
    var plugins = cap.Plugins || {};
    if (plugins.EdifySettings) {
      return plugins.EdifySettings.openNotificationSettings().catch(function () {
        if (platform === 'ios') window.location.href = 'app-settings:';
      });
    }
    if (platform === 'ios') window.location.href = 'app-settings:';
    return Promise.resolve(null);
  }

  function disable(reason) {
    var token = remembered().token;
    forget(TOKEN_KEY);
    return Promise.all([
      token ? call(UNREGISTER, { token: token, reason: reason || '' }, reason === 'signed_out').catch(noop) : null,
      // Nothing of this person's stays in the tray.
      PushNotifications.removeAllDeliveredNotifications().catch(noop),
    ]).then(function () {
      return buildReady;
    }).then(function (ready) {
      // A fresh token for whoever signs in next, from a build that has one.
      return ready ? PushNotifications.unregister() : null;
    }).catch(noop);
  }

  // Said before the phone asks, once: what notifications are for, and that
  // the choice can be changed (Settings, or the switch under the bell).
  function ask() {
    var host = doc.getElementById('toast-container');
    if (!host || doc.querySelector('[data-app-push-ask]')) return;
    var card = doc.createElement('div');
    card.setAttribute('data-app-push-ask', '');
    card.setAttribute('role', 'dialog');
    card.setAttribute('aria-label', 'Turn on notifications');
    card.className = 'pointer-events-auto max-w-sm space-y-3 rounded-surface border p-4 shadow-lg edify-surface edify-border edify-text';
    var title = doc.createElement('p');
    title.className = 'text-[14px] font-bold';
    title.textContent = 'Know the moment work needs you';
    var words = doc.createElement('p');
    words.className = 'text-[13px] text-slate-500';
    words.textContent = 'Edify can tell this phone about approvals, returns and To-Dos, even when the app is closed. A locked phone only shows that Edify has something. You can change this in Settings.';
    var row = doc.createElement('div');
    row.className = 'flex justify-end gap-2';
    function button(label, primary, then) {
      var b = doc.createElement('button');
      b.type = 'button';
      b.className = 'btn h-9 ' + (primary ? 'btn-primary' : 'btn-secondary');
      b.textContent = label;
      b.addEventListener('click', function () { write(ASKED_KEY, '1'); card.remove(); then(); });
      return b;
    }
    row.appendChild(button('Not now', false, repaint));
    row.appendChild(button('Turn on', true, function () { enable().then(repaint); }));
    card.appendChild(title); card.appendChild(words); card.appendChild(row);
    host.appendChild(card);
  }

  // ── Starting on each signed-in page ──────────────────────────────────────
  function listen() {
    return PushNotifications.removeAllListeners().catch(noop).then(function () {
      PushNotifications.addListener('registration', function (token) { record(token && token.value); });
      PushNotifications.addListener('registrationError', function () { failed = true; repaint(); });
      PushNotifications.addListener('pushNotificationReceived', function (note) {
        var data = (note && note.data) || {};
        if (window.EdifyPush && window.EdifyPush.foreground) {
          window.EdifyPush.foreground({ title: note.title || data.title || 'Edify', body: note.body || data.body || '', url: data.url });
        }
      });
      PushNotifications.addListener('pushNotificationActionPerformed', function (action) {
        var data = (action && action.notification && action.notification.data) || {};
        open(data.url);
      });
    });
  }

  function start() {
    if (platform === 'android') {
      // The name a person sees in the phone's notification settings
      // (fcm.ANDROID_CHANNEL); high importance shows it as a banner.
      PushNotifications.createChannel({
        id: 'edify', name: 'Edify notifications', description: 'Work that needs you in Edify',
        // 0 is "private": a locked phone shows Edify, not the words.
        importance: 4, visibility: 0,
      }).catch(noop);
    }
    buildReady.then(function (ready) {
      // A build that cannot receive them is never offered them.
      return ready ? listen().then(permission) : null;
    }).then(function (receive) {
      if (receive === 'granted') return register();
      // Offered once, after sign-in; the switch stays in Settings and under
      // the bell for anyone who said not now.
      if ((receive === 'prompt' || receive === 'prompt-with-rationale') && read(ASKED_KEY) !== '1') ask();
      return null;
    }).then(repaint, repaint);
  }

  // Back from the phone's settings (or anywhere else): its answer may have
  // changed, so register if it now allows notifications.
  doc.addEventListener('visibilitychange', function () {
    if (doc.hidden) return;
    permission().then(function (receive) {
      if (receive === 'granted') { failed = false; return register(); }
      return null;
    }).then(repaint, repaint);
  });

  window.EdifyAppPush = Object.freeze({ state: state, enable: enable, disable: disable, openSettings: openSettings });
  repaint();
  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', start); else start();
})();
