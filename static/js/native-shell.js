/*
 * The Edify iOS and Android app (mobile/, Capacitor) loads this site in its
 * web view. This script is what makes that page behave like an app there, and
 * does nothing at all in a browser: every step waits on window.Capacitor
 * saying this is the native app.
 *
 *   • The Android back button closes an open drawer or dialog first, then goes
 *     back a page, and on Home leaves the app in the background rather than
 *     closing it.
 *   • A link that opens the app (a notification, a link to the Edify site,
 *     or edify://open/<path>) opens that page of THIS site and nothing
 *     else: `internalPath` refuses any other host, so a crafted link cannot
 *     send the web view somewhere that is not Edify. The page it opens still
 *     runs its own sign-in and permission checks.
 *   • <html> carries data-native-app="ios|android" for styles that need it.
 *   • On iOS the page keeps its scale when a field is tapped (holdScale).
 *   • Coming back to the app fires `edify-app-resume` on the document.
 *
 * No credentials or tokens pass through here; the session stays the site's
 * own cookie.
 */
(function (root) {
  "use strict";

  var APP_SCHEME = "edify:";
  var APP_SCHEME_HOST = "open";
  var HOME_PATH = "/home";

  /**
   * The same-site path a link that opened the app should show, or null.
   * `origin` is this page's origin (the Edify site the app opened).
   */
  function internalPath(raw, origin) {
    var url;
    try {
      url = new URL(String(raw || ""));
    } catch (error) {
      return null;
    }
    var path;
    if (url.protocol === APP_SCHEME) {
      if (url.host !== APP_SCHEME_HOST) return null;
      path = url.pathname || "/";
    } else if (url.protocol === "https:" && url.origin === origin) {
      path = url.pathname || "/";
    } else {
      return null;
    }
    // One leading slash and no backslash: "//elsewhere" or "/\elsewhere" is
    // read by a browser as another host.
    if (path.charAt(0) !== "/" || path.charAt(1) === "/" || path.indexOf("\\") !== -1) {
      return null;
    }
    return path + url.search + url.hash;
  }

  /**
   * iOS zooms the whole page into any field whose text is under 16px, and the
   * site's compact filters are 12px: in the app every filter tap zoomed the
   * page and left it zoomed. Inside the app only, the page keeps its scale.
   * A browser is never sent this script, so its pinch zoom is untouched.
   */
  function holdScale(doc) {
    var meta = doc.querySelector('meta[name="viewport"]');
    if (!meta) return;
    var content = meta.getAttribute("content") || "";
    if (/maximum-scale/.test(content)) return;
    meta.setAttribute("content", content + ", maximum-scale=1");
  }

  function openOverlay(doc) {
    var drawers = doc.getElementById("drawer-container");
    if (drawers && drawers.children.length) return true;
    var modals = doc.querySelectorAll('dialog[open], [aria-modal="true"]');
    for (var i = 0; i < modals.length; i += 1) {
      if (modals[i].offsetParent !== null || modals[i].tagName === "DIALOG") return true;
    }
    return false;
  }

  function start(win) {
    var cap = win.Capacitor;
    if (!cap || typeof cap.isNativePlatform !== "function" || !cap.isNativePlatform()) {
      return false;
    }
    var doc = win.document;
    var platform = cap.getPlatform();
    doc.documentElement.setAttribute("data-native-app", platform);
    if (platform === "ios") holdScale(doc);

    var App = cap.Plugins && cap.Plugins.App;
    if (!App || typeof App.addListener !== "function") return true;

    App.addListener("backButton", function (event) {
      if (openOverlay(doc)) {
        // The shell and every drawer already close on Escape.
        doc.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
        return;
      }
      if (event && event.canGoBack && win.location.pathname !== HOME_PATH) {
        win.history.back();
        return;
      }
      if (typeof App.minimizeApp === "function") App.minimizeApp();
    });

    // Back in front after a while away: the page brings itself up to date
    // (Home's Priority actions reload on this; templates/partials/home/queue.html).
    App.addListener("resume", function () {
      doc.dispatchEvent(new win.CustomEvent("edify-app-resume"));
    });

    App.addListener("appUrlOpen", function (event) {
      var path = internalPath(event && event.url, win.location.origin);
      if (path) win.location.assign(path);
    });
    return true;
  }

  var api = { internalPath: internalPath, start: start };
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else {
    root.EdifyNativeShell = api;
    start(root);
  }
})(typeof window !== "undefined" ? window : this);
