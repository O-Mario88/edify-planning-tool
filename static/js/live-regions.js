/* Regions a page reads again by itself: `data-live-region` (it needs an id).
 *
 * Owner, 2026-10-14: "behave like salesforce where a user has to refresh for
 * the data to be updated", and of one's own saves: "everything is updated
 * upon refresh icon clicked. so that the save, reschedule, schedule,
 * complete, cancel... functionalities can be fast". So nothing here follows
 * the plan any more: the stream at /api/realtime/stream is not opened, and a
 * save made from the page reads nothing (apps.core.htmx_saved). The page
 * shows what it showed until Refresh — the browser's, or the installed app's
 * beside Back and Forward. From 2026-10-05 to 2026-10-14 every change anybody
 * made, and every save of one's own, read the page again.
 *
 * What remains is a page finishing itself: a section whose figures are still
 * being worked out asks for its region again (EdifyLive.refresh — Country
 * Planning Oversight's settle). Nothing is swapped under an open drawer, a
 * ticked activity, an open Actions menu or a field in use: it waits.
 * Rationale: docs/ui-components.md, "Live regions". */
(function () {
  'use strict';
  if (window.EdifyLive) return;
  var doc = document, REGION = '[data-live-region][id]';
  var wanted = false, loading = false;

  function regions() { return doc.querySelectorAll(REGION); }

  function busy() {
    var host = doc.getElementById('drawer-container');
    if (host && host.childElementCount) return true;
    if (doc.querySelector('input[data-activity-pick]:checked, input[data-school-pick]:checked, ' + REGION + ' td input[type="checkbox"]:checked:not(:disabled), ' + REGION + ' .row-menu__trigger[aria-expanded="true"]')) return true;
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
      // Settled a moment later, as htmx does: Alpine must see the region
      // first, or the menus inside it are left dead.
      setTimeout(function () { window.htmx.trigger(node, 'htmx:afterSettle'); }, 20);
    }
  }

  function refresh() {
    wanted = true;
    if (loading || doc.hidden || !regions().length || busy()) return;
    wanted = false;
    loading = true;
    fetch(location.href, { credentials: 'same-origin', headers: { 'X-Requested-With': 'EdifyLive' } })
      .then(function (response) {
        // Signed out, or the page is gone: nothing to bring in.
        return response.ok && !response.redirected ? response.text() : '';
      })
      .then(function (html) {
        loading = false;
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

  // A save leaves the page as it is: Refresh brings it up to date.
  function saved() {}

  doc.addEventListener('visibilitychange', function () {
    if (!doc.hidden && wanted) refresh();
  });
  setInterval(function () { if (wanted) refresh(); }, 1000);

  window.EdifyLive = Object.freeze({ refresh: refresh, busy: busy, saved: saved });
})();
