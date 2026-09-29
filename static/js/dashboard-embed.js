/*
 * A page a dashboard carries keeps its links in place (owner, 2026-09-29:
 * the Programme Lead's Planning Monitor and Staff Activity Log moved onto the
 * dashboard; apps/frontend/views/dashboard_embed.py).
 *
 * A dashboard section `[data-dashboard-embed="<page path>"]` holds the page's
 * fragment. htmx already keeps the fragment's own hx- links and forms inside
 * it; this is for the plain links the fragment was written with — a figure's
 * drill-down, the table pager's "?…&page=2" — which would otherwise leave the
 * dashboard (the pager's even resolves against /dashboard). A plain click on
 * a link to the section's own page is fetched into the section instead, with
 * the section's header, and the address bar is left alone. Links elsewhere (a
 * school, an activity) and modified clicks (new tab, download) are the
 * browser's, unchanged.
 *
 * Runs in the capture phase so it answers before table-pagination.js, which
 * would otherwise reload the page for the pager.
 */
(function () {
  "use strict";

  if (window.__edifyDashboardEmbed) return;
  window.__edifyDashboardEmbed = true;

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

  document.addEventListener(
    "click",
    function (event) {
      if (!plain(event) || !window.htmx || !event.target.closest) return;
      var link = event.target.closest("a[href]");
      if (!link || link.target || link.hasAttribute("download")) return;
      // htmx owns its own links.
      if (link.hasAttribute("hx-get") || link.hasAttribute("hx-post")) return;
      var host = link.closest("[data-dashboard-embed]");
      if (!host) return;

      var url;
      var page;
      try {
        page = new URL(host.getAttribute("data-dashboard-embed"), window.location.href);
        var href = link.getAttribute("href");
        // A bare query is the fragment's own ("?…&gap_page=2"): it names the
        // page the fragment came from, not the dashboard it sits on.
        url = new URL(href, href.charAt(0) === "?" ? page : window.location.href);
      } catch (error) {
        return;
      }
      if (url.origin !== page.origin || url.pathname !== page.pathname) return;
      var target = document.querySelector(host.getAttribute("data-embed-target"));
      if (!target) return;

      event.preventDefault();
      window.htmx.ajax("GET", url.pathname + url.search, {
        target: target,
        swap: host.getAttribute("data-embed-swap") || "innerHTML",
        headers: { "X-Edify-Embed": "dashboard" },
      });
    },
    true
  );
})();
