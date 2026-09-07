/*
 * A dashboard view, once loaded, stays loaded.
 *
 * THE DEFECT THIS FIXES (owner, 2026-09-07)
 *
 * "The map and operation tabs are very slow to respond… all roles have the
 * same issues." Measured: a switch costs the server 300-700ms and 141 queries,
 * and it costs the same whichever panel it is about to render, because the
 * view rebuilds the whole dashboard either way. Pressing back and forth
 * between two views the reader has already seen paid that bill every time.
 *
 * The press itself now answers immediately (the rail highlights on click), but
 * the content still arrived a second later. This is the other half: the panel
 * a reader has already loaded is kept, so going back to it costs nothing at
 * all. Only the first visit to each view touches the network.
 *
 * HOW IT HOLDS A PANEL
 *
 * A parked panel is detached and kept in a JS map keyed by its view. Detaching
 * is what makes it safe to hold: a panel left in the document with
 * `display: none` still has a size of zero, and ApexCharts watches its own
 * parent — a zero-size parent is what makes it write width="NaN" into its SVG
 * (see the drawer work in drawers.css). So the charts are destroyed before the
 * panel leaves, and rebuilt when it comes back.
 *
 * Rebuilt by Alpine, not by this file. Re-attaching a subtree makes Alpine
 * initialise it again, which re-runs the `x-init` that drew each chart and the
 * map in the first place. That is why this file is short: it moves nodes and
 * gets out of the way. What it must do is destroy the charts on the way out,
 * because nothing else will — htmx is not involved in a switch between two
 * panels that are already in hand, so the teardown that rides on `htmx:beforeSwap`
 * never runs.
 *
 * WHAT STILL COSTS A REQUEST
 *
 * The first visit to each view, and every reload of the page — a parked panel
 * lives in memory, not in storage. That is the point: it holds what the reader
 * has already waited for, and never serves them something older than the page
 * they are on.
 */
(function () {
  "use strict";

  if (window.__edifyViewPanels) return;

  /* view name -> the detached panel element for it */
  var parked = new Map();
  /* Which view the panel currently in the shell belongs to. */
  var current = null;

  function shell() {
    return document.querySelector("[data-dashboard-view-shell]");
  }

  function panelOf(host) {
    return host ? host.querySelector('[role="tabpanel"]') : null;
  }

  /* The view a tab points at: every tab is a real URL carrying the dashboard's
     own filters, and `view` is the one parameter that names the panel.

     Note what is NOT used to answer "which panel is in the shell": the rail.
     The pressed tab highlights before the request goes out, so between the
     press and the response the rail names the view being fetched, not the one
     on screen — parking by the rail files every panel under its successor's
     name and the hold never works. `current` is the shell's own answer, and it
     changes only when the shell does. */
  function viewOf(url) {
    try {
      var parsed = new URL(url, window.location.origin);
      /* A dashboard's views are one path with `?view=`; the Priorities page's
         two views are two real routes (owner, 2026-09-07), so the path names
         the view when the parameter does not. Either way a view has one name,
         which is all the map below needs. */
      return parsed.searchParams.get("view") || parsed.pathname;
    } catch (error) {
      return null;
    }
  }

  function currentView() {
    var active = document.querySelector(
      "[data-dashboard-views] .edify-section-nav__link.is-active"
    );
    return active ? viewOf(active.getAttribute("href")) : null;
  }

  function park(view) {
    var panel = panelOf(shell());
    if (!panel || !view) return;
    /* Charts first: they are destroyed while the panel still has its size, so
       none of them ever sees a zero-width parent. */
    if (window.EdifyChartSystem && window.EdifyChartSystem.destroyInside) {
      window.EdifyChartSystem.destroyInside(panel);
    }
    panel.remove();
    parked.set(view, panel);
  }

  function show(view) {
    var host = shell();
    var panel = parked.get(view);
    if (!host || !panel) return false;
    parked.delete(view);
    host.appendChild(panel);
    current = view;
    return true;
  }

  /* The rail is server-rendered, and a switch that never reaches the server has
     to keep it honest by itself. The tab already highlights on press; this sets
     the parts a swap would have brought back. */
  function markRail(view) {
    var rail = document.querySelector("[data-dashboard-views]");
    if (!rail) return;
    rail.querySelectorAll(".edify-section-nav__link").forEach(function (tab) {
      var chosen = viewOf(tab.getAttribute("href")) === view;
      tab.classList.toggle("is-active", chosen);
      tab.setAttribute("aria-selected", chosen ? "true" : "false");
      tab.setAttribute("tabindex", chosen ? "0" : "-1");
      tab.dataset.serverActive = chosen ? "true" : "false";
    });
    var panel = panelOf(shell());
    if (panel) {
      var active = rail.querySelector(".edify-section-nav__link.is-active");
      if (active && active.id) panel.setAttribute("aria-labelledby", active.id);
    }
  }

  document.addEventListener(
    "click",
    function (event) {
      var tab = event.target.closest(
        "[data-dashboard-views] .edify-section-nav__link"
      );
      if (!tab) return;
      var view = viewOf(tab.getAttribute("href"));
      if (!view || !parked.has(view)) return;

      /* Held in hand: no request, and htmx must not make one either. */
      event.preventDefault();
      event.stopPropagation();

      park(current);
      if (!show(view)) return;
      markRail(view);
      /* The tabs are real URLs — a deep link, the back button and a press all
         land on the same page — so a switch that skips the network still has
         to move the address bar. */
      try {
        window.history.pushState({}, "", tab.getAttribute("href"));
      } catch (error) {
        /* A blocked history write is not a reason to fail the switch. */
      }
    },
    /* Capture: htmx listens on the element itself, so this has to run first to
       be able to stop it. */
    true
  );

  /* htmx replaces the whole shell — rail and panel together — so a panel that
     is to survive has to leave before the swap and be recorded after it. */
  document.addEventListener("htmx:beforeSwap", function (event) {
    var target = event.detail && event.detail.target;
    if (!target || !target.matches("[data-dashboard-view-shell]")) return;
    park(current);
  });

  document.addEventListener("htmx:afterSettle", function (event) {
    var target = event.detail && event.detail.target;
    if (!target || !target.matches("[data-dashboard-view-shell]")) return;
    /* The rail that just arrived is the server's, so it is honest again. */
    current = currentView() || viewOf(window.location.href);
    /* The view that just arrived is in the shell, not in the map. */
    if (current) parked.delete(current);
  });

  /* The address bar can move without a press — the back button. Whatever it
     lands on, the panel in hand may be the wrong one. */
  window.addEventListener("popstate", function () {
    var view = viewOf(window.location.href);
    if (!view || !parked.has(view) || view === current) return;
    park(current);
    if (show(view)) markRail(view);
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      current = currentView();
    });
  } else {
    current = currentView();
  }

  window.__edifyViewPanels = {
    parked: parked,
    held: function () {
      return Array.from(parked.keys());
    },
  };
})();
