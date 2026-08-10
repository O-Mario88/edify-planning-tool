/* Keep rendered CSRF tokens aligned with Django's current CSRF cookie.

   Django rotates that cookie when a login completes. A page left open in
   another tab still contains the previous token, so its next legitimate POST
   would otherwise fail with "CSRF token from POST incorrect". Native forms
   are synchronized at submit time; HTMX requests are synchronized when their
   request configuration is assembled. */
(function () {
  "use strict";

  var COOKIE_NAME = "csrftoken";
  var FIELD_NAME = "csrfmiddlewaretoken";

  function currentToken() {
    var token = null;

    document.cookie.split(";").forEach(function (part) {
      var separator = part.indexOf("=");
      if (separator === -1) return;

      var name = part.slice(0, separator).trim();
      if (name !== COOKIE_NAME) return;

      var value = part.slice(separator + 1);
      try {
        token = decodeURIComponent(value);
      } catch (error) {
        token = value;
      }
    });

    return token;
  }

  function sync(root) {
    var token = currentToken();
    if (!token) return null;

    var scope = root && root.querySelectorAll ? root : document;
    if (scope.matches && scope.matches('input[name="' + FIELD_NAME + '"]')) {
      scope.value = token;
    }
    scope.querySelectorAll('input[name="' + FIELD_NAME + '"]').forEach(function (field) {
      field.value = token;
    });

    var meta = document.querySelector('meta[name="csrf-token"]');
    if (meta) meta.setAttribute("content", token);

    if (document.body) {
      document.body.setAttribute(
        "hx-headers",
        JSON.stringify({ "X-CSRFToken": token })
      );
    }

    return token;
  }

  document.addEventListener("DOMContentLoaded", function () {
    sync(document);
  });

  window.addEventListener("pageshow", function () {
    sync(document);
  });

  document.addEventListener(
    "submit",
    function (event) {
      var form = event.target;
      if (!form || String(form.method || "get").toLowerCase() === "get") return;
      sync(form);
    },
    true
  );

  document.addEventListener("htmx:load", function (event) {
    sync(event.target || document);
  });

  document.addEventListener("htmx:configRequest", function (event) {
    var token = sync(event.target || document);
    if (!token || !event.detail) return;

    event.detail.headers = event.detail.headers || {};
    event.detail.headers["X-CSRFToken"] = token;

    if (event.detail.parameters && FIELD_NAME in event.detail.parameters) {
      event.detail.parameters[FIELD_NAME] = token;
    }
    if (
      event.detail.unfilteredParameters &&
      FIELD_NAME in event.detail.unfilteredParameters
    ) {
      event.detail.unfilteredParameters[FIELD_NAME] = token;
    }
  });
})();
