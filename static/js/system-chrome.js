/* The phone's address bar (<meta name="theme-color">) and, in the iOS and
 * Android app, its status bar take the page canvas, --edify-bg, once the
 * styles exist and after a theme switch (tests/js/system-chrome.test.cjs). */
(function (root) {
  "use strict";

  /** "#abc" or "#aabbcc" as "#aabbcc"; null for anything else. */
  function hexOf(value) {
    var text = String(value || "").trim().toLowerCase();
    var m = /^#([0-9a-f])([0-9a-f])([0-9a-f])$/.exec(text);
    if (m) return "#" + m[1] + m[1] + m[2] + m[2] + m[3] + m[3];
    return /^#[0-9a-f]{6}$/.test(text) ? text : null;
  }

  /** Whether dark icons read on this colour. */
  function isLight(hex) {
    var n = parseInt(hex.slice(1), 16);
    return 0.2126 * ((n >> 16) & 255) + 0.7152 * ((n >> 8) & 255) + 0.0722 * (n & 255) > 150;
  }

  function apply(win) {
    var doc = win.document;
    var color = hexOf(win.getComputedStyle(doc.documentElement).getPropertyValue("--edify-bg"));
    if (!color) return null;
    var meta = doc.querySelector('meta[name="theme-color"]');
    if (meta && meta.content !== color) meta.content = color;
    var cap = win.Capacitor;
    var bar = cap && cap.isNativePlatform && cap.isNativePlatform() && cap.Plugins && cap.Plugins.StatusBar;
    if (bar) {
      // Capacitor's LIGHT is dark text, for a light bar. iOS draws the page
      // under its status bar; only Android paints one.
      bar.setStyle({ style: isLight(color) ? "LIGHT" : "DARK" });
      if (cap.getPlatform() === "android") bar.setBackgroundColor({ color: color });
    }
    return color;
  }

  function start(win) {
    var doc = win.document;
    var run = function () {
      try {
        apply(win);
      } catch (error) {
        /* The bars keep their colour. */
      }
    };
    if (doc.readyState === "loading") doc.addEventListener("DOMContentLoaded", run, { once: true });
    else run();
    win.addEventListener("pageshow", run);
    if (win.MutationObserver) {
      var timer;
      new win.MutationObserver(function () {
        win.clearTimeout(timer);
        timer = win.setTimeout(run, 450); // after the 400ms theme fade
      }).observe(doc.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    }
  }

  var api = { hexOf: hexOf, isLight: isLight, apply: apply, start: start };
  if (typeof module === "object" && module.exports) module.exports = api;
  else {
    root.EdifySystemChrome = api;
    start(root);
  }
})(typeof window !== "undefined" ? window : this);
