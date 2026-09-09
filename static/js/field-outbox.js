/* Field outbox: keeps a field officer's actions when the network cannot.

   A CCEO completes a visit on a phone that often has no signal at the school.
   Without this, the start/complete/evidence POSTs fail and the work is
   re-entered later from memory, or not at all. The outbox stores the exact
   multipart body -- files included -- in IndexedDB and replays it, in order,
   when the connection returns. Scope is the field-action routes below and
   nothing else: replaying an arbitrary POST later (a fund approval, a
   reschedule) is not obviously what the person meant, so everything else
   keeps platform-status.js's "you are offline, try again".

   Nothing here is authoritative. The server validates a replayed request as
   it would a live one; a rejection is kept and surfaced, never dropped. */
(function () {
  'use strict';

  if (window.__edifyFieldOutboxInstalled || !window.indexedDB) return;
  window.__edifyFieldOutboxInstalled = true;

  var DB_NAME = 'edify-outbox';
  var STORE = 'requests';
  var SYNC_TAG = 'edify-outbox';
  var CSRF_FIELD = 'csrfmiddlewaretoken';
  var ROUTES = [
    /^\/activities\/[^/]+\/(start|complete|evidence|attendance|ssa-upload|salesforce-id|submit|partner-ssa-complete)\/action$/,
    /^\/my-plan\/[^/]+\/(complete|accountability)$/
  ];
  var LABELS = {
    start: 'Start activity', complete: 'Complete activity', evidence: 'Evidence upload',
    attendance: 'Attendance sheet', 'ssa-upload': 'SSA form', 'salesforce-id': 'Salesforce ID',
    submit: 'Submit for review', 'partner-ssa-complete': 'Partner SSA completion',
    accountability: 'Accountability'
  };

  /* -- storage --------------------------------------------------------- */

  function openDb() {
    return new Promise(function (resolve, reject) {
      var request = indexedDB.open(DB_NAME, 1);
      request.onupgradeneeded = function () {
        // Auto-increment keys are the replay order: getAll() returns them
        // ascending, which is the order the person did things in.
        request.result.createObjectStore(STORE, { keyPath: 'id', autoIncrement: true });
      };
      request.onsuccess = function () { resolve(request.result); };
      request.onerror = function () { reject(request.error); };
    });
  }

  function withStore(mode, work) {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE, mode);
        var request = work(tx.objectStore(STORE));
        tx.oncomplete = function () { db.close(); resolve(request && request.result); };
        tx.onerror = tx.onabort = function () { db.close(); reject(tx.error); };
      });
    });
  }

  function listAll() { return withStore('readonly', function (s) { return s.getAll(); }); }
  function save(entry) { return withStore('readwrite', function (s) { return s.put(entry); }); }
  function discard(id) { return withStore('readwrite', function (s) { return s.delete(id); }); }

  /* -- what qualifies --------------------------------------------------- */

  function pathOf(target) {
    try { return new URL(target, window.location.href).pathname; } catch (e) { return ''; }
  }

  function actionOf(path) {
    var match = ROUTES[0].exec(path) || ROUTES[1].exec(path);
    return match ? match[1] : null;
  }

  function formOf(element) {
    if (!element || !element.tagName) return null;
    return element.tagName === 'FORM' ? element : element.closest('form');
  }

  function isFieldPost(detail) {
    var config = (detail && detail.requestConfig) || {};
    return String(config.verb || '').toLowerCase() === 'post' && actionOf(pathOf(config.path)) !== null;
  }

  /* The body is captured at the moment of submission, so the entry holds what
     the person actually chose -- the File blobs included; IndexedDB stores
     them as-is. The CSRF field is dropped: Django rotates the token, so the
     one valid at replay time is read from the cookie then. */
  function entryFor(form, path) {
    var fields = [];
    new FormData(form).forEach(function (value, name) {
      if (name === CSRF_FIELD) return;
      // An untouched <input type="file"> serialises as a nameless, empty
      // File. Replaying that part makes the server see an upload with no
      // extension and refuse the whole action; the live form never sends it.
      if (value instanceof File && !value.name && !value.size) return;
      fields.push({ name: name, value: value });
    });
    var subtitle = document.getElementById('drawer-subtitle');
    return {
      path: path,
      label: LABELS[actionOf(path)] || 'Field action',
      subject: (subtitle && subtitle.textContent.trim()) || ('Activity ' + (path.split('/')[2] || '').slice(0, 8)),
      createdAt: Date.now(),
      fields: fields,
      status: 'queued',
      message: ''
    };
  }

  function queue(form, path) {
    return save(entryFor(form, path)).then(function () {
      notify('Saved offline — will send when you are back online.');
      announce('Saved offline. It will send when you are back online.');
      // The drawer's own close asks "discard changes?" -- nothing is being
      // discarded, so bypass it.
      window.dispatchEvent(new CustomEvent('close-drawer'));
      requestSync();
      return refresh();
    }).catch(function () {
      notify('This could not be saved on your phone. Reconnect and try again.', 'error');
    });
  }

  /* Capture phase on document, so this runs before platform-status.js's
     bubble-phase offline handler cancels the request with "reconnect and try
     again". Once a request is taken here nothing else should react to it. */
  document.addEventListener('htmx:beforeRequest', function (event) {
    var form = formOf(event.detail && event.detail.elt);
    if (!form || navigator.onLine || !isFieldPost(event.detail)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    queue(form, pathOf(event.detail.requestConfig.path));
  }, true);

  /* `navigator.onLine` is optimistic: a phone can report a connection and
     still reach nothing. A request that dies on the wire is queued too. HTMX
     has already fired afterRequest by now, so pending states are cleared. */
  document.addEventListener('htmx:sendError', function (event) {
    var form = formOf(event.detail && event.detail.elt);
    if (!form || !isFieldPost(event.detail)) return;
    event.stopImmediatePropagation();
    queue(form, pathOf(event.detail.requestConfig.path));
  }, true);

  /* -- replay ------------------------------------------------------------ */

  function csrfToken() {
    var token = '';
    document.cookie.split(';').forEach(function (part) {
      var at = part.indexOf('=');
      if (at === -1 || part.slice(0, at).trim() !== 'csrftoken') return;
      try { token = decodeURIComponent(part.slice(at + 1)); } catch (e) { token = part.slice(at + 1); }
    });
    return token;
  }

  function bodyOf(entry, token) {
    var body = new FormData();
    entry.fields.forEach(function (field) {
      if (field.value instanceof Blob) body.append(field.name, field.value, field.value.name || 'upload');
      else body.append(field.name, field.value);
    });
    body.append(CSRF_FIELD, token);
    return body;
  }

  function textOf(html) {
    var doc = new DOMParser().parseFromString(html, 'text/html');
    return (doc.body.textContent || '').replace(/\s+/g, ' ').trim();
  }

  function signedOut(res) {
    if (res.status === 401 || res.status === 419) return true;
    return res.redirected && pathOf(res.url) === '/login';
  }

  var sent = 0;

  // Resolves true when replay should halt: nothing later may go before this.
  function send(entry) {
    var token = csrfToken();
    return fetch(entry.path, {
      method: 'POST',
      body: bodyOf(entry, token),
      credentials: 'same-origin',
      // The views answer an HTMX request with a status that means something
      // (200 done, 4xx rejected) rather than a redirect to a page.
      headers: { 'X-CSRFToken': token, 'HX-Request': 'true' }
    }).then(function (res) {
      if (signedOut(res)) return true;
      if (res.ok) {
        sent += 1;
        return discard(entry.id).then(function () { return false; });
      }
      if (res.status < 500) {
        // The server said no. That needs a person, not a retry: keep the
        // entry, keep its reason, and step past it.
        return res.text().then(function (html) {
          entry.status = 'attention';
          entry.message = textOf(html).slice(0, 200) || ('Rejected (' + res.status + ')');
          return save(entry);
        }).then(function () { return false; });
      }
      return true;
    }, function () { return true; });
  }

  var replaying = false;

  function replay() {
    if (replaying || !navigator.onLine) return Promise.resolve();
    replaying = true;
    sent = 0;
    function sendQueued() {
      return listAll().then(function (entries) {
        // Read inside the cross-tab lock: another tab may already have sent
        // these entries while this tab was waiting for its turn.
        return entries.filter(function (e) { return e.status !== 'attention'; })
          .reduce(function (chain, entry) {
            return chain.then(function (halted) { return halted || send(entry); });
          }, Promise.resolve(false));
      });
    }
    // Background Sync wakes every open tab. A per-page boolean alone allowed
    // them to POST the same saved action concurrently.
    var delivery = navigator.locks
      ? navigator.locks.request('edify-field-outbox-replay', sendQueued)
      : sendQueued();
    return delivery.then(function () {
      replaying = false;
      if (sent) notify('Sent ' + sent + ' saved ' + (sent === 1 ? 'action' : 'actions') + '.');
      return refresh();
    }, function () { replaying = false; });
  }

  function requestSync() {
    if (!('serviceWorker' in navigator) || !('SyncManager' in window)) return;
    navigator.serviceWorker.ready
      .then(function (registration) { return registration.sync.register(SYNC_TAG); })
      .catch(function () { /* the online event and page load cover it */ });
  }

  /* -- surfaces ---------------------------------------------------------- */

  function notify(message, tone) {
    var container = document.getElementById('toast-container');
    if (!container) return;
    var toast = document.createElement('div');
    toast.className = 'pointer-events-auto flex items-center justify-between gap-3 px-4 py-3 rounded-surface border shadow-lg max-w-sm text-[12px] font-semibold ' +
      (tone === 'error' ? 'bg-rose-50 text-rose-700 border-rose-200' : 'bg-slate-50 text-slate-700 border-slate-200');
    toast.textContent = message;
    container.appendChild(toast);
    window.setTimeout(function () { toast.remove(); }, 6000);
  }

  function announce(message, priority) {
    document.dispatchEvent(new CustomEvent('edify:announce', {
      detail: { message: message, priority: priority || 'polite' }
    }));
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  }

  function renderList(entries) {
    var list = document.querySelector('[data-field-outbox-list]');
    var empty = document.querySelector('[data-field-outbox-empty]');
    if (!list) return;
    list.textContent = '';
    entries.forEach(function (entry) {
      var stuck = entry.status === 'attention';
      var item = el('li', 'flex items-start justify-between gap-3');
      var copy = el('div');
      copy.appendChild(el('p', 'text-slate-800', entry.label + ' — ' + entry.subject));
      copy.appendChild(el('p', 'font-medium text-slate-500', new Date(entry.createdAt).toLocaleString()));
      copy.appendChild(stuck
        ? el('p', 'font-medium text-rose-700', 'Needs attention: ' + entry.message)
        : el('p', 'font-medium text-slate-500', 'Waiting to send'));
      item.appendChild(copy);
      if (stuck) {
        // Only a rejected entry can be discarded: the server has already said
        // it will not take it, so dropping it loses nothing that could send.
        var button = el('button', 'btn btn-secondary h-8', 'Discard');
        button.type = 'button';
        button.addEventListener('click', function () { discard(entry.id).then(refresh); });
        item.appendChild(button);
      }
      list.appendChild(item);
    });
    list.hidden = entries.length === 0;
    if (empty) empty.hidden = entries.length > 0;
  }

  function refresh() {
    return listAll().then(function (entries) {
      var count = entries.length;
      var attention = entries.filter(function (e) { return e.status === 'attention'; }).length;
      document.querySelectorAll('[data-field-outbox-count]').forEach(function (node) {
        node.textContent = String(count);
      });
      document.querySelectorAll('[data-field-outbox-badge]').forEach(function (badge) {
        badge.hidden = count === 0;
      });
      // The connectivity banner's own copy says changes cannot be sent, which
      // is not what happened to these.
      var detail = document.querySelector('#edify-connectivity-status [data-connectivity-detail]');
      if (detail && count && !navigator.onLine) {
        detail.textContent = count + ' saved ' + (count === 1 ? 'action is' : 'actions are') +
          ' kept on this phone and will send when you reconnect.';
      }
      if (attention) {
        announce(attention + ' saved ' + (attention === 1 ? 'action needs' : 'actions need') +
          ' attention. Open Pending uploads to review.', 'assertive');
      }
      renderList(entries);
      return entries;
    }).catch(function () { return []; });
  }

  // The fallback page is titled for the moment it is usually seen. Reached
  // deliberately, online, it is the place to review what is still queued.
  function retitle() {
    var page = document.querySelector('[data-offline-page]');
    if (!page) return;
    var online = navigator.onLine && !page.hasAttribute('data-navigation-failed');
    document.querySelector('[data-offline-title]').textContent = online ? 'Pending uploads' : 'You are offline';
    document.querySelector('[data-offline-description]').textContent = online
      ? 'Actions saved on this device are listed below and send in the order you saved them.'
      : 'Your saved actions are kept on this device and will send when the connection returns.';
  }

  /* -- lifecycle --------------------------------------------------------- */

  window.addEventListener('online', function () {
    var page = document.querySelector('[data-offline-page]');
    if (page) page.removeAttribute('data-navigation-failed');
    retitle(); refresh().then(replay);
  });
  window.addEventListener('offline', function () { retitle(); refresh(); });
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.addEventListener('message', function (event) {
      if (event.data && event.data.type === 'edify-outbox-replay') replay();
    });
  }

  // Deferred script: the document is parsed by the time this runs.
  retitle();
  refresh().then(replay);

  window.EdifyFieldOutbox = Object.freeze({ replay: replay, refresh: refresh });
})();
