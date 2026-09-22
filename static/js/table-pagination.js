/*
 * A paginated link keeps the reader where they are.
 *
 * THE DEFECT THIS FIXES (owner, 2026-09-22)
 *
 * "Oversight keeps taking the Programme Leads back to their page when they
 * click the next page on the pagination. A PL should be able to use pagination
 * on every table and reach everything, not loop back to his own plans."
 *
 * Every oversight workspace shows one person's tables inside a tab panel, and
 * the tab is a browser-side choice: the strip sets `activeOfficer` and writes
 * the id into the address bar with replaceState, so switching officers costs no
 * request. The pager under the table is the opposite — a link the SERVER wrote,
 * from the query string it was asked with, before any tab was touched. Its
 * `href` is a whole query ("?owner=…&g2_page-cv=2"), and following it replaces
 * everything in the address bar, the officer included.
 *
 * So page two arrived with the strip back at its first tab: "my-clusters" on
 * Cluster Oversight, "My Core Schools" on Core School Oversight, the first
 * group on Team Planning — the Programme Lead's own rows, every time. Not a
 * pagination bug in the pager: a link that dropped the one parameter nobody had
 * told the server about.
 *
 * WHAT THIS DOES
 *
 * Two things, both only for links inside `.edify-pagination`:
 *
 * 1. It carries the view-state parameters that a tab strip registered
 *    (`window.__edifyUrlViewParams`, written by `tabState` and `urlTabs` in
 *    alpine-components.js) from the live URL onto the link, where the link does
 *    not set them itself. Nothing else is carried: a filter the reader has just
 *    cleared must stay cleared, and the server's link is authoritative for
 *    every parameter it actually names.
 *
 * 2. Where the table lives in a fragment the page fetched for itself — a
 *    `[data-pager-fragment]` element, whose value is the URL it was fetched
 *    from — it re-fetches that fragment in place instead of reloading the whole
 *    page. The Country Director's team panels are the case: rebuilding the
 *    country's oversight page to turn one table's page is a second or more of
 *    work for nothing. The address bar is updated either way, so a refresh, a
 *    bookmark and a forwarded link all land on the same page of the same table.
 *
 * WHAT THIS DOES NOT DO
 *
 * It is inert until a tab strip registers a parameter, and inert for a modified
 * click (new tab, new window, download) — those keep the server's link exactly
 * as written. With no JavaScript at all the links still work: every parameter
 * the server knew about is already in the href, which is why the fragments also
 * carry the current query server-side ({% carry_query %}) rather than relying
 * on this file.
 */
(function () {
  "use strict";

  if (window.__edifyTablePagination) return;
  window.__edifyTablePagination = true;

  var PAGER = ".edify-pagination";

  function registered() {
    return window.__edifyUrlViewParams || null;
  }

  /* The link the reader pressed, if it is a page in a table pager. */
  function pagerLink(target) {
    if (!target || !target.closest) return null;
    var link = target.closest(PAGER + " a[href]");
    return link && link.getAttribute("href") ? link : null;
  }

  /* The server's link, plus the tab parameters it never saw. */
  function wanted(link) {
    var url = new URL(link.getAttribute("href"), window.location.href);
    var params = registered();
    if (!params || !params.size) return url;
    var live = new URL(window.location.href).searchParams;
    params.forEach(function (name) {
      if (url.searchParams.has(name)) return;
      var value = live.get(name);
      if (value) url.searchParams.set(name, value);
    });
    return url;
  }

  function fragmentHost(link) {
    if (!link.closest || !window.htmx) return null;
    var host = link.closest("[data-pager-fragment]");
    if (!host || !host.getAttribute("data-pager-fragment")) return null;
    return host;
  }

  /* The fragment's own URL, asked again with the page the reader chose. */
  function fragmentUrl(host, url) {
    var source = new URL(host.getAttribute("data-pager-fragment"), window.location.href);
    url.searchParams.forEach(function (value, key) {
      source.searchParams.set(key, value);
    });
    return source;
  }

  function plain(event) {
    return (
      !event.defaultPrevented &&
      event.button === 0 &&
      !event.metaKey &&
      !event.ctrlKey &&
      !event.shiftKey &&
      !event.altKey
    );
  }

  document.addEventListener("click", function (event) {
    if (!plain(event)) return;
    var link = pagerLink(event.target);
    if (!link || link.target || link.hasAttribute("download")) return;

    var url;
    try {
      url = wanted(link);
    } catch (error) {
      return; /* An address we cannot parse is the browser's to follow. */
    }

    var host = fragmentHost(link);
    if (host) {
      event.preventDefault();
      var source;
      try {
        source = fragmentUrl(host, url);
        window.history.replaceState(null, "", url);
      } catch (error) {
        window.location.assign(url.href);
        return;
      }
      window.htmx.ajax("GET", source.pathname + source.search, {
        target: host,
        swap: "innerHTML",
      });
      return;
    }

    /* Nothing was added — let the browser follow its own link, so middle-click,
       prefetch and the status bar all still describe what will happen. */
    if (url.href === new URL(link.getAttribute("href"), window.location.href).href) return;
    event.preventDefault();
    window.location.assign(url.href);
  });
})();
