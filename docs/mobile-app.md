# Edify for iOS and Android

The phone app is the Edify web app in a native shell (Capacitor 8). There is
one app, one server, one database: every page, permission, calculation and
record stays on the Django site. The shell adds what a website cannot do on
its own: an installable icon, a launch screen, the Android back button,
`edify://` links, the native status bar and keyboard, and an offline screen.

```
mobile/
  capacitor.config.js       app id, name, the server it opens, plugin settings
  package.json              Capacitor and plugin versions (pinned)
  www/                      the two pages bundled in the app: launch, offline
  ios/  android/            the native projects (generated, then customised)
  scripts/make-assets.py    icons and launch screens from static/images/
  scripts/stamp-server.cjs  writes the server into the offline page on sync
  test/                     config tests (npm test)
static/js/native-shell.js   the site's side of the bridge; inert in a browser
```

## What the app opens

`capacitor.config.js` sets `server.url` to `https://edifyplanning.app/home`.
`/home` is the phone's first tab (Home): what needs you now, what is coming up
and where to go. A signed-out person is sent to the normal sign-in page and
back to Home afterwards. The session is the site's own cookie inside the web
view; the app stores no password or token of its own.

Point a build at another server when syncing:

```bash
EDIFY_SERVER_URL=https://staging.example.org npm run sync
```

Plain `http://` is refused except for `localhost`, `10.0.2.2` (the Android
emulator's address for the computer) and private `192.168.*` / `10.*`
addresses, so a release build cannot be pointed at an unencrypted server.

| Setting | Value |
|---|---|
| App id (bundle id / package name) | `app.edifyplanning.mobile` (changeable until the first store upload, permanent after) |
| Display name | Edify |
| Start page | `/home` |
| Link scheme | `edify://open/<path>`, e.g. `edify://open/my-plan/<id>` |
| Launch screen | the sidebar's navy gradient (`#001d39` → `#062847` → `#0a4d86`), white wordmark (`scripts/make-assets.py`) |
| Status bar | the page canvas (`--edify-bg`, `#dbe4eb` light): dark icons on a light canvas, light ones on a dark theme, set by the site (`static/js/system-chrome.js`) |
| Web view background | `#dbe4eb`, the page's own, so moving between pages never flashes another colour |
| App icon | the PWA icon artwork (`static/images/app-icon-source.png`) on `#2d4862` |

## Build it

Prerequisites: Node 22+, Xcode (iOS), Android Studio with a JDK 17+ and the
Android SDK (Android). No CocoaPods: the iOS project uses Swift Package Manager.

```bash
cd mobile
npm ci
npm test
npm run sync          # stamps the offline page and copies config into both projects
```

iOS:

```bash
npm run open:ios      # opens Xcode; pick a simulator or device and Run
```

From the command line (no signing, simulator):

```bash
xcodebuild -project ios/App/App.xcodeproj -scheme App -configuration Debug -sdk iphonesimulator -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build
```

Android:

```bash
npm run open:android  # opens Android Studio; Run on an emulator or device
```

```bash
cd android && ./gradlew assembleDebug
```

Icons and launch screens, after `npx cap add` or a Capacitor upgrade:

```bash
../.venv/bin/python scripts/make-assets.py
```

### A local server on a device

```bash
EDIFY_SERVER_URL=http://192.168.1.20:8000 npm run sync
```

Run Django on `0.0.0.0:8000` and add the address to `ALLOWED_HOSTS` and
`CSRF_TRUSTED_ORIGINS` in your local environment. The Android emulator reaches
the computer at `http://10.0.2.2:8000`.

## Native behaviour

| Behaviour | Where | Notes |
|---|---|---|
| Android back button | `static/js/native-shell.js` | Closes an open drawer or dialog first, then goes back a page; on Home it puts the app in the background. |
| Links that open the app | `native-shell.js`, iOS `CFBundleURLTypes`, Android intent filter | Only paths of the site the app opened are followed; any other host is refused. The page still runs its own sign-in and permission checks. |
| Offline | `www/offline.html` (`server.errorPath`) | Shown when the site cannot be reached. Says nothing was lost; "Try again" reopens Home. Field actions saved offline stay in the site's own outbox (`static/js/field-outbox.js`). |
| Camera and photos | iOS `NSCameraUsageDescription`, `NSPhotoLibraryUsageDescription`; Android `CAMERA` | Asked only when someone chooses to photograph or pick evidence in an upload field. |
| Keyboard | `Keyboard.resize: native` | The page shrinks above the keyboard; the bottom bar steps aside while typing. |
| Safe areas | site CSS (`viewport-fit=cover`, `env(safe-area-inset-*)`) | Notch and home indicator handled by the pages themselves. |
| Backups | Android `allowBackup=false`, `data_extraction_rules.xml` | The sign-in cookie never leaves the phone in a backup or device transfer. |

## Push notifications (next stage, needs credentials)

The site already has in-app notifications (read state, unread count, links)
and Web Push for browsers (`apps.notifications.push`,
`static/js/push-notifications.js`). Web Push does not reach an app's web view,
so native push needs:

1. `@capacitor/push-notifications` added to `mobile/`.
2. A device-token model and an endpoint beside `PushSubscription`
   (register on sign-in, refresh, revoke on sign-out or account change).
3. A sender for FCM (Android) and APNs (iOS) in `apps.notifications.push`,
   honouring each person's notification preferences, recording the
   provider's answer, and never putting school, staff or finance detail in
   lock-screen text.
4. Asking permission after explaining it, not on first launch.

Credentials it needs, none of which belong in the repository:

- Firebase project, `google-services.json` (Android) and a service-account key
  on the server.
- APNs key (`.p8`), key id and team id, on the server; the Push Notifications
  capability on the app id.

## Universal links and App Links (next stage)

`https://edifyplanning.app/...` links can open the app once the site serves
`/.well-known/apple-app-site-association` (needs the Apple team id) and
`/.well-known/assetlinks.json` (needs the release signing certificate's
SHA-256), and the iOS Associated Domains capability is enabled. Until then
`edify://open/<path>` works.

## Releasing

| Need | Who |
|---|---|
| Apple Developer Program membership (organisation) | Edify |
| Google Play Console account (organisation) | Edify |
| iOS signing: distribution certificate, provisioning profile for `app.edifyplanning.mobile` | release owner, in Xcode / App Store Connect |
| Android upload key (`.jks`) and Play App Signing | release owner; never committed |
| Privacy policy URL; App Store privacy labels and Play data-safety form (account, school and activity data, photos chosen as evidence) | Edify |
| Store listing: name, description, screenshots (6.7" and 6.1" iPhone, phone and 7" tablet for Play), support URL | Edify |

Versioning: set the marketing version and build number in Xcode
(`MARKETING_VERSION`, `CURRENT_PROJECT_VERSION`) and `versionName` /
`versionCode` in `android/app/build.gradle`; raise the build number on every
upload.

Internal testing: TestFlight (iOS) and an internal testing track (Play).

### Store review risk

Apple's guideline 4.2 turns down apps that are only a website. Edify's case
for review rests on what the app adds: the task-first Home, native back and
link handling, camera evidence capture, the offline screen, and (next stage)
native push. Ship push before the first App Store submission.

## What has and has not been verified

| Check | Result (2026-10-21) |
|---|---|
| `npm test` in `mobile/` (config) | passes |
| `node --test tests/js/native-shell.test.cjs` (bridge) | passes |
| iOS simulator build (Xcode 27, `CODE_SIGNING_ALLOWED=NO`) | **BUILD SUCCEEDED** |
| Running on an iOS simulator | not run: no simulator runtime installed (Xcode → Settings → Components) |
| Android build | not run: no JDK or Android SDK on the build machine |
| Physical devices, push | not run |
