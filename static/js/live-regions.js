/* Pages that keep up with the plan (owner, 2026-10-05: "Every event ...
 * should update in real time and fast"). A region marked `data-live-region`
 * (it needs an id) is read again from the server when the plan this reader
 * sees changes: the stream at /api/realtime/stream says when
 * (apps.activities.live). Nothing is swapped under an open drawer, a ticked
 * activity, an open Actions menu or a field in use: it waits. A hidden tab
 * closes its stream and catches up when it is looked at again.
 * Rationale: docs/ui-components.md, "Live regions". */
(function () {
  'use strict';
  if (window.EdifyLive || !window.EventSource) return;
  var doc = document, REGION = '[data-live-region][id]';
  var stream = null, seen = '', wanted = false, loading = false, soonTimer = 0, retryTimer = 0, notBefore = 0;

  function regions() { return doc.querySelectorAll(REGION); }

  function busy() {
    var host = doc.getElementById('drawer-container');
    if (host && host.childElementCount) return true;
    if (doc.querySelector('input[data-activity-pick]:checked, ' + REGION + ' .row-menu__trigger[aria-expanded="true"]')) return true;
    var at = doc.activeElement;
    return !!(at && at.closest && at.closest(REGION) &&
      at.matches('input:not([type="checkbox"]):not([type="radio"]), textarea, select'));
  }

  function swap(old, fresh) {
    var node = doc.importNode(fresh, true);
    old.replaceWith(node);
    // An imported script does not run; a new one with the same text does.
    Array.prototype.forEach.call(node.querySelectorAll('script'), function (script) {
      var live = doc.createElement('script');
      Array.prototype.forEach.call(script.attributes, function (attr) { live.setAttribute(attr.name, attr.value); });
      live.text = script.text;
      script.replaceWith(live);
    });
    if (window.htmx) {
      window.htmx.process(node);
      window.htmx.trigger(node, 'htmx:load');
      window.htmx.trigger(node, 'htmx:afterSettle');
    }
  }

  function refresh() {
    wanted = true;
    if (loading || doc.hidden || !regions().length || busy() || Date.now() < notBefore) return;
    wanted = false;
    loading = true;
    var began = Date.now();
    fetch(location.href, { credentials: 'same-origin', headers: { 'X-Requested-With': 'EdifyLive' } })
      .then(function (response) { return response.ok && !response.redirected ? response.text() : ''; })
      .then(function (html) {
        loading = false;
        // A busy day does not turn into a page reading itself without pause:
        // it rests for as long as the last read took, a second at least.
        notBefore = Date.now() + Math.max(1000, Date.now() - began);
        if (!html) return;
        // Something was opened while the page was being read: wait again.
        if (busy()) { wanted = true; return; }
        var next = new DOMParser().parseFromString(html, 'text/html');
        Array.prototype.forEach.call(regions(), function (old) {
          var fresh = next.getElementById(old.id);
          if (fresh) swap(old, fresh);
        });
        doc.dispatchEvent(new CustomEvent('edify:live-refreshed'));
      })
      .catch(function () { loading = false; });
  }

  function soon() {
    clearTimeout(soonTimer);
    // Long enough for the rest of one save to commit, no longer.
    soonTimer = setTimeout(refresh, 400);
  }

  function close() {
    if (stream) { stream.close(); stream = null; }
  }

  function open() {
    if (stream || doc.hidden || !regions().length) return;
    stream = new EventSource('/api/realtime/stream');
    stream.onmessage = function (event) {
      var data;
      try { data = JSON.parse(event.data); } catch (_) { return; }
      if (data.type === 'plan.changed') soon();
      // Back after being away: read again only if something changed meanwhile.
      else if (data.type === 'connected' && seen && data.changed && data.changed > seen) soon();
      if (data.at) seen = data.at;
    };
    stream.onerror = function () {
      // Refused (too many tabs, signed out): the browser will not retry.
      if (stream && stream.readyState === 2) {
        close();
        clearTimeout(retryTimer);
        retryTimer = setTimeout(open, 60000);
      }
    };
  }

  doc.addEventListener('visibilitychange', function () {
    if (doc.hidden) close();
    else { open(); if (wanted) refresh(); }
  });
  window.addEventListener('pagehide', close);
  doc.addEventListener('htmx:afterSettle', function () { if (!stream) open(); });
  setInterval(function () { if (wanted) refresh(); }, 1000);
  // Not on a page passed through on the way to another.
  setTimeout(open, 1500);

  window.EdifyLive = Object.freeze({ refresh: refresh, busy: busy });
})();
