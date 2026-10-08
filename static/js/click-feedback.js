/* Every click is answered at once (owner, 2026-10-08): a line across the top
   of the window while the next page or part is fetched, and the menu entry
   pressed takes the chosen look. Why, and what is covered: base.html and
   docs/ui-components.md, "A click is answered at once". */
(function () {
  "use strict";

  if (window.__edifyClickFeedback) return;
  window.__edifyClickFeedback = true;

  var root = document.documentElement;
  var NAV = ["app-sidebar__item", "edify-bottom-nav__item"];
  var chosen = null;
  var fetching = 0;
  var giveUp = 0;

  function show() {
    root.setAttribute("data-edify-loading", "");
    clearTimeout(giveUp);
    // A download leaves the page where it is and fires nothing.
    giveUp = setTimeout(hide, 12000);
  }

  function hide() {
    clearTimeout(giveUp);
    fetching = 0;
    root.removeAttribute("data-edify-loading");
    if (!chosen) return;
    chosen[0].classList.remove(chosen[2]);
    if (chosen[1]) chosen[1].classList.add(chosen[2]);
    chosen = null;
  }

  function choose(link) {
    var base = NAV.filter(function (name) { return link.classList.contains(name); })[0];
    if (!base) return;
    var active = base + "--active";
    var current = link.closest("nav, aside, ul");
    current = current && current.querySelector("." + active);
    if (current === link) return;
    if (current) current.classList.remove(active);
    link.classList.add(active);
    chosen = [link, current, active];
  }

  function isFile(url) {
    return /[?&](export|download|format)=|\/(export|download)(\/|\?|$)|\.(csv|xlsx?|pdf|docx?|zip)(\?|$)/i.test(url);
  }

  function clicked(event) {
    var config = event.detail && event.detail.requestConfig;
    var trigger = config && config.triggeringEvent;
    return config && config.verb === "get" && trigger && trigger.type === "click";
  }

  // On window: after every handler that may have cancelled the click.
  window.addEventListener("click", function (event) {
    if (event.defaultPrevented || event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    var link = event.target.closest && event.target.closest("a[href]");
    if (!link || link.origin !== location.origin || link.hasAttribute("download")) return;
    if (link.target && link.target !== "_self") return;
    if (link.hasAttribute("hx-get") || link.hasAttribute("hx-post") || link.closest("[hx-boost]")) return;
    if (link.pathname === location.pathname && link.search === location.search) return;
    if (isFile(link.href)) return;
    choose(link);
    show();
  });

  window.addEventListener("submit", function (event) {
    var form = event.target;
    if (event.defaultPrevented || !form || !form.getAttribute) return;
    if (form.target && form.target !== "_self") return;
    if (form.method === "dialog" || isFile(form.action + "?" + new URLSearchParams(new FormData(form)))) return;
    show();
  });

  document.addEventListener("htmx:beforeSend", function (event) {
    if (!clicked(event)) return;
    fetching += 1;
    show();
  });
  ["htmx:afterRequest", "htmx:sendError", "htmx:timeout"].forEach(function (name) {
    document.addEventListener(name, function (event) {
      if (!fetching || !clicked(event)) return;
      fetching -= 1;
      if (!fetching) hide();
    });
  });

  window.addEventListener("pageshow", hide);
  // "Leave this page?" answered No: the timer runs once that is closed.
  window.addEventListener("beforeunload", function (event) {
    setTimeout(function () {
      if (event.defaultPrevented || event.returnValue) hide();
    }, 0);
  });
})();
