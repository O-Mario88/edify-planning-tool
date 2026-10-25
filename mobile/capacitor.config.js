/*
 * Edify for iOS and Android.
 *
 * The app is the Edify web app itself: the native shell opens the hosted site
 * at /home, and every page, permission and record stays on the server. Nothing
 * here is a secret, and nothing secret belongs here — signing keys and push
 * credentials live with the release owner (docs/mobile-app.md).
 *
 * EDIFY_SERVER_URL picks the server at `cap sync` time:
 *   production (default)  https://edifyplanning.app
 *   a staging host        EDIFY_SERVER_URL=https://staging.example npx cap sync
 *   a laptop on the LAN   EDIFY_SERVER_URL=http://192.168.1.20:8000 npx cap sync
 * Plain http is accepted only for a local or private-network address, so a
 * release build can never be pointed at an unencrypted server by mistake.
 */
const PRODUCTION_URL = "https://edifyplanning.app";
const START_PATH = "/home";

function resolveServer(raw) {
  const url = new URL(raw || PRODUCTION_URL);
  const host = url.hostname;
  const local =
    host === "localhost" ||
    host === "127.0.0.1" ||
    host === "10.0.2.2" || // the Android emulator's address for its host
    /^192\.168\./.test(host) ||
    /^10\./.test(host);
  if (url.protocol !== "https:" && !(url.protocol === "http:" && local)) {
    throw new Error(`EDIFY_SERVER_URL must be https (got ${url.origin})`);
  }
  return { origin: url.origin, cleartext: url.protocol === "http:" };
}

const server = resolveServer(process.env.EDIFY_SERVER_URL);

/** @type {import('@capacitor/cli').CapacitorConfig} */
module.exports = {
  appId: "app.edifyplanning.mobile",
  appName: "Edify",
  // Only the launch and offline pages ship in the app; everything else is
  // the live site.
  webDir: "www",
  server: {
    url: `${server.origin}${START_PATH}`,
    // The site's own host. On iOS a page stays in the app only when its
    // address starts with `url` (…/home) or its host is listed here, so
    // without it sign-in and every other page would open in Safari.
    allowNavigation: [new URL(server.origin).hostname],
    cleartext: server.cleartext,
    // Shown when the site cannot be reached at all (no network, server down).
    errorPath: "offline.html",
  },
  // Identifies the app to the server's logs without changing the browser
  // the site sees.
  appendUserAgent: "EdifyApp",
  // Behind the page while the next one loads: the page's own background, so
  // moving between pages never flashes a colour of its own (2026-10-24).
  backgroundColor: "#dbe4eb",
  ios: {
    // The page handles the notch and home indicator itself (viewport-fit=cover
    // and env(safe-area-inset-*) in the site's styles).
    contentInset: "never",
  },
  android: {
    allowMixedContent: false,
    webContentsDebuggingEnabled: false,
  },
  plugins: {
    SplashScreen: {
      launchAutoHide: true,
      launchShowDuration: 600,
      // The sidebar's navy, as the launch screen is drawn (scripts/make-assets.py).
      backgroundColor: "#001d39",
      showSpinner: false,
    },
    StatusBar: {
      // The launch screen's navy with light icons, so the first frame is one
      // colour. From there the site takes over (static/js/system-chrome.js):
      // an iPhone runs the page under the bar and its icons follow the top of
      // the page; Android's bars take the page's own top and bottom colours
      // (EdifyChromePlugin). overlaysWebView stays false because the setting
      // is shared, and Android lays the page out between its bars.
      style: "DARK",
      backgroundColor: "#001d39",
      overlaysWebView: false,
    },
    PushNotifications: {
      // A notification that arrives while Edify is open is the page's to
      // show (static/js/native-push.js); the tray is for when it is not.
      presentationOptions: [],
    },
    Keyboard: {
      // The page shrinks above the keyboard, so a field being typed into and
      // the form's buttons stay visible; the bottom bar steps aside
      // (templates/components/mobile_bottom_nav.html).
      resize: "native",
      resizeOnFullScreen: true,
    },
  },
};

module.exports.resolveServer = resolveServer;
