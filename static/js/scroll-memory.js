/*
 * Keep the reader where they were.
 *
 * THE DEFECT THIS FIXES (owner, 2026-09-07)
 *
 * "When you click a tab or pagination, or refresh the page, the page resets to
 * the top" — and "the sidebar has the same behaviour: when you click a menu it
 * resets to the top".
 *
 * The cause is that this application does not scroll the document. The shell
 * pins the top bar and the sidebar and gives the workspace its own scrollbar,
 * so `#main-content` is the scroller and `window.scrollY` never leaves zero.
 * Browsers restore scroll for the DOCUMENT scroller and nothing else, so the
 * one thing the browser would have done for free is the one thing it cannot
 * do here: a refresh, a back, a paginated link — all land at the top of a list
 * the reader had already scrolled through. Measured on /schools: the workspace
 * sat at 781px before a refresh and 0 after it.
 *
 * The sidebar is the same story a second time. Its menu is 1,395px taller than
 * a 620px window, so a Country Director scrolls to reach the lower half of it
 * — and every navigation puts the menu back at the top, away from the item
 * they just used.
 *
 * WHAT IS REMEMBERED, AND WHAT IS NOT
 *
 * The workspace is remembered PER PAGE, keyed by path and not by query string.
 * That is deliberate: page two of a table, or the same table under a different
 * filter, is somewhere the reader arrives from where they already were, and
 * sending them to the top of it is the complaint. A genuinely different page
 * has no entry and opens at the top, as it should.
 *
 * The sidebar is remembered as ONE position, not per page: it is the same menu
 * on every screen, so its place in the list belongs to the session.
 *
 * Both live in sessionStorage, so they last as long as the tab and no longer,
 * and both expire after half an hour — coming back to a screen much later and
 * landing mid-list would be its own surprise.
 *
 * WHAT THIS DOES NOT DO
 *
 * It does not fight the reader. Restoration stops the moment they scroll, and
 * it never runs more than a few frames after a page settles. htmx swaps that
 * replace content in place already hold their position (measured: a tab swap
 * held 600px, pagination held within 70px of 700), so this leaves them alone
 * apart from saving the position they end at.
 */
(function () {
  "use strict";

  if (window.__edifyScrollMemory) return;

  var PREFIX = "edify:scroll:";
  var SIDEBAR_KEY = PREFIX + "sidebar";
  var MAX_AGE_MS = 30 * 60 * 1000;
  /* Long enough to cover a table that renders its rows after the shell, short
     enough that the reader never sees the page move under a deliberate scroll
     of their own. */
  var SETTLE_MS = 900;

  function store() {
    try {
      return window.sessionStorage;
    } catch (error) {
      /* Private windows and locked-down browsers throw on access, not on use.
         Losing the position is a small thing; throwing on every page is not. */
      return null;
    }
  }

  function workspace() {
    return document.getElementById("main-content");
  }

  /* There are two of these: the mobile sidebar's, which is in the markup on
     every page but renders at zero height until its drawer opens, and the
     desktop one. `querySelector` returns the mobile one, which never scrolls
     and never has a position worth keeping — so this takes the one that is
     actually on screen. */
  function sidebar() {
    var containers = document.querySelectorAll(".app-sidebar__nav-container");
    for (var i = 0; i < containers.length; i++) {
      if (containers[i].clientHeight > 0) return containers[i];
    }
    return null;
  }

  /* Path only. Page two of a table and the same table under another filter are
     both "where I already was". */
  function pageKey() {
    return PREFIX + window.location.pathname;
  }

  function read(key) {
    var box = store();
    if (!box) return null;
    try {
      var raw = box.getItem(key);
      if (!raw) return null;
      var saved = JSON.parse(raw);
      if (!saved || typeof saved.top !== "number") return null;
      if (Date.now() - (saved.at || 0) > MAX_AGE_MS) return null;
      return saved.top;
    } catch (error) {
      return null;
    }
  }

  function write(key, top) {
    var box = store();
    if (!box) return;
    try {
      if (!top) {
        /* The top of a page is the default, so recording it would only take up
           room and outlive its usefulness. */
        box.removeItem(key);
        return;
      }
      box.setItem(key, JSON.stringify({ top: Math.round(top), at: Date.now() }));
    } catch (error) {
      /* A full quota must not break scrolling. */
    }
  }

  function save() {
    var main = workspace();
    if (main) write(pageKey(), main.scrollTop || window.scrollY || 0);
    var nav = sidebar();
    if (nav) write(SIDEBAR_KEY, nav.scrollTop);
  }

  var pending = false;
  function saveSoon() {
    if (pending) return;
    pending = true;
    window.requestAnimationFrame(function () {
      pending = false;
      save();
    });
  }

  /* Restoring is a conversation with a page that is still arriving: rows land,
     charts size themselves, and the scrollable height grows for a moment after
     first paint. So the position is re-applied while that settles and abandoned
     as soon as the reader takes over. */
  function restore(element, top) {
    if (!element || !top) return;
    var deadline = Date.now() + SETTLE_MS;
    var surrendered = false;

    function giveUp() {
      surrendered = true;
    }
    element.addEventListener("wheel", giveUp, { once: true, passive: true });
    element.addEventListener("touchstart", giveUp, { once: true, passive: true });
    window.addEventListener("keydown", giveUp, { once: true });

    (function apply() {
      if (surrendered) return;
      var reachable = element.scrollHeight - element.clientHeight;
      if (reachable > 0) {
        var target = Math.min(top, reachable);
        if (Math.abs(element.scrollTop - target) > 1) element.scrollTop = target;
        /* Everything the page was going to add has arrived: the position is
           reachable and holding, so stop touching it. */
        if (element.scrollTop === target && reachable >= top) return;
      }
      if (Date.now() < deadline) window.requestAnimationFrame(apply);
    })();
  }

  function restoreAll() {
    restore(workspace(), read(pageKey()));
    restore(sidebar(), read(SIDEBAR_KEY));
  }

  function watch() {
    var main = workspace();
    if (main && !main.__edifyScrollWatched) {
      main.__edifyScrollWatched = true;
      main.addEventListener("scroll", saveSoon, { passive: true });
    }
    var nav = sidebar();
    if (nav && !nav.__edifyScrollWatched) {
      nav.__edifyScrollWatched = true;
      nav.addEventListener("scroll", saveSoon, { passive: true });
    }
  }

  function start() {
    watch();
    restoreAll();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }

  /* A page that finishes loading taller than it was at DOMContentLoaded — a
     table whose rows arrived late — gets one more attempt at the position. */
  window.addEventListener("load", restoreAll);

  /* `pagehide` rather than `beforeunload`: it fires for a back-forward cache
     entry too, and it does not disqualify the page from that cache. */
  window.addEventListener("pagehide", save);
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") save();
  });

  /* htmx replaces the shell on some navigations, which replaces the elements
     the listeners were on; and a swap that lands new content is the moment the
     saved height changes. */
  document.addEventListener("htmx:afterSettle", function () {
    watch();
    saveSoon();
  });

  window.__edifyScrollMemory = { save: save, restore: restoreAll };
})();
