/* Browser-side defect detection.
 *
 * A dead button is invisible to the server: the request that would have proved
 * it never happens. So the page itself reports what it sees — a control that
 * fires nothing, a script that threw, an HTMX swap that failed — and the
 * backend turns each unique one into a System Incident with a route, a
 * component and a next action.
 *
 * Three rules keep this from becoming noise or a leak:
 *   1. Nothing is sent that the user typed. Only the control's identity, the
 *      route, and an error message.
 *   2. Each defect signature reports once per page load; the server
 *      deduplicates the rest across sessions.
 *   3. Failure to report is silent — a broken beacon must never become a
 *      second visible fault on top of the first.
 */
(function () {
  "use strict";

  var ENDPOINT = "/support/client-defect";
  var reported = new Set();
  // A click that legitimately does nothing visible (a tab, a disclosure) is
  // common, so a control is only "dead" when it claims an action and produces
  // no navigation, no request and no DOM change.
  var DEAD_BUTTON_GRACE_MS = 1200;

  function csrf() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? m[1] : "";
  }

  function send(kind, component, detail) {
    var key = kind + "|" + component;
    if (reported.has(key)) return;
    reported.add(key);
    try {
      fetch(ENDPOINT, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrf(),
        },
        body: JSON.stringify({
          kind: kind,
          route: window.location.pathname,
          component: component,
          detail: detail || {},
        }),
        keepalive: true,
      }).catch(function () {
        /* reporting a defect must never raise one */
      });
    } catch (e) {
      /* ignore */
    }
  }

  function identify(el) {
    if (!el) return "unknown";
    return (
      el.getAttribute("data-card-key") ||
      el.id ||
      el.getAttribute("name") ||
      (el.textContent || "").trim().slice(0, 40) ||
      el.tagName.toLowerCase()
    );
  }

  /* ── Uncaught script errors ─────────────────────────────────────────────── */
  window.addEventListener("error", function (event) {
    if (!event || !event.message) return;
    send("js_exception", (event.filename || "inline").split("/").pop(), {
      message: String(event.message).slice(0, 300),
    });
  });

  window.addEventListener("unhandledrejection", function (event) {
    var reason = event && event.reason;
    send("js_exception", "promise", {
      message: String((reason && reason.message) || reason || "").slice(0, 300),
    });
  });

  /* ── Failed HTMX exchanges ──────────────────────────────────────────────── */
  document.body.addEventListener("htmx:responseError", function (event) {
    var status = event.detail && event.detail.xhr && event.detail.xhr.status;
    // 403 from the Admin read-only gate is the system working as designed.
    if (status === 403) return;
    send("htmx_failure", identify(event.detail && event.detail.elt), {
      status: String(status || ""),
    });
  });

  document.body.addEventListener("htmx:sendError", function (event) {
    send("htmx_failure", identify(event.detail && event.detail.elt), {
      message: "network error",
    });
  });

  document.body.addEventListener("htmx:timeout", function (event) {
    send("frozen_screen", identify(event.detail && event.detail.elt), {
      message: "request timed out",
    });
  });

  /* ── Dead buttons ───────────────────────────────────────────────────────── */
  document.addEventListener(
    "click",
    function (event) {
      var el = event.target.closest(
        "button, [role='button'], a[href], [hx-get], [hx-post]"
      );
      if (!el || el.disabled) return;

      // Statically dead: it looks like an action and names no destination.
      var href = el.getAttribute("href");
      if (href === "#" || (href || "").startsWith("javascript:")) {
        if (!el.hasAttribute("x-on:click") && !el.hasAttribute("@click")) {
          send("dead_button", identify(el), { target: href || "" });
          return;
        }
      }

      // Anything that declares a handler, a request or a destination is
      // presumed live — only a bare control is watched.
      if (
        el.type === "submit" ||
        el.form ||
        el.hasAttribute("hx-get") ||
        el.hasAttribute("hx-post") ||
        el.hasAttribute("x-on:click") ||
        el.hasAttribute("@click") ||
        el.hasAttribute("onclick") ||
        (href && href !== "#")
      ) {
        return;
      }

      var before = document.body.innerHTML.length;
      var url = window.location.href;
      window.setTimeout(function () {
        if (window.location.href !== url) return; // navigated
        if (document.body.innerHTML.length !== before) return; // rendered
        send("dead_button", identify(el), { message: "click produced no change" });
      }, DEAD_BUTTON_GRACE_MS);
    },
    true
  );
})();
