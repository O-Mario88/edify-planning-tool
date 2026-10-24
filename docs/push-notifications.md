# Push notifications: browsers and the Edify app

Every Edify notification is one record, the bell's. Push gives a copy of it to
the person's devices so they can act the moment it arrives, even with Edify
closed:

| Device | How | Status |
|---|---|---|
| Desktop and laptop browsers (Chrome, Edge, Firefox, Safari on macOS) | Web Push (`apps/notifications/webpush.py`, service worker at `/sw.js`) | Works once the VAPID keys are set |
| Android phone browser, iPhone/iPad web app added to the Home Screen | Web Push | Same keys |
| Edify app on Android | Firebase Cloud Messaging (`apps/notifications/fcm.py`) | Works once Firebase is set up |
| Edify app on iPhone | Firebase, which hands it to Apple's push service (APNs) | Works once Firebase and the APNs key are set up |

On an iPhone, a Safari tab cannot receive web notifications. The page says so
and tells the person to add Edify to the Home Screen or use the app.

## What is sent, to whom

The send path is the same for every device (`apps/notifications/push.py`):

1. A notification is saved, or re-fired for the same unresolved condition.
2. For each of the recipient's live devices this server can reach, one
   `NotificationDelivery` row (channel `push`) and one outbox event are
   written in the same transaction. They are sent right after commit, and the
   outbox drain retries anything that fails.
3. Just before sending, the copy is skipped (and the row says why) when:
   - the notification was read or resolved, or is more than a day old;
   - the account was deactivated;
   - the person's role can no longer open the page the notification leads to;
   - someone else has since signed in on the device;
   - the person turned push off (urgent notices are sent regardless, as for
     email).
4. The provider's answer is recorded: `accepted` (never claimed as
   "delivered"), `retry_scheduled`, or `failed`. A device the provider says
   is gone (browser permission withdrawn, app removed, token replaced) is
   marked revoked and never sent to again.

A tap opens `/notifications/<id>/open`. That marks the notification read and
goes to its record, in the browser or inside the app.

Lock screens show the notification's title and line on an unlocked phone.
Android marks Edify's notifications private, so a locked phone shows only
that Edify has something. iPhones hide previews while locked by default.

## Where people turn it on and off

- **This device:** the switch under the bell, in Settings → Notifications, and
  in "How you are told" on the notification centre. In the app, after sign-in
  the page explains notifications once and offers Turn on. Only then does the
  phone ask.
- **The phone's own settings:** in the app, Edify is an app in the phone's
  notification settings like any other (iPhone: Settings → Notifications →
  Edify, for banners, sounds, the lock screen and Focus; Android: App info →
  Notifications → "Edify notifications"). If notifications are off there, the
  switch reads "Open phone settings" and goes straight to that page. Coming
  back with them allowed turns push on without another step.
- **All devices at once:** "Send push notifications" in "How you are told"
  (`/notifications/#delivery-settings`), beside the email switch.
- Signing out on a device ends that device's notifications and clears its tray.

## Credentials the owner must create

None of these belong in the repository. The server ones go in each
environment's variables: locally in `.env`, and in production in the
DigitalOcean App Platform encrypted variables (`DEPLOY.md`, section 2). Set
them on the web service **and** on the scheduler/worker component, because
the outbox drain also sends.

### 1. Web Push key pair (VAPID): browsers

1. Run `python manage.py generate_vapid_keys` once per environment (local,
   staging and production each get their own pair).
2. Set the two lines it prints, plus a contact address:
   - `WEBPUSH_VAPID_PUBLIC_KEY`
   - `WEBPUSH_VAPID_PRIVATE_KEY` (encrypted variable)
   - `WEBPUSH_SUBJECT=mailto:<an inbox someone reads>`
3. Keep the pair. Every browser subscribes with the public key, so a new pair
   stops every device that already turned notifications on.

### 2. Firebase project: the Edify app

1. At <https://console.firebase.google.com>, create a project (for example
   "Edify"). Google Analytics is not needed.
2. **Android app:** Project settings → General → Add app → Android, package
   name `app.edifyplanning.mobile`. Download **`google-services.json`** and put
   it at `mobile/android/app/google-services.json`. It is git-ignored; the
   Android build picks it up on its own (`mobile/android/app/build.gradle`).
3. **iOS app:** Add app → Apple, bundle id `app.edifyplanning.mobile`.
   Download **`GoogleService-Info.plist`** and, in Xcode, drag it into
   `App/App` with "Add to target: App" ticked. It is git-ignored.
4. **Server key:** Project settings → Service accounts → Generate new private
   key. This downloads a JSON file. Set **one** of:
   - `FCM_SERVICE_ACCOUNT_JSON`: the file's contents base64-encoded on one
     line (`base64 -i key.json | tr -d '\n'`), as an encrypted variable; or
   - `FCM_SERVICE_ACCOUNT_FILE`: the path of the file on the server.

   Then delete the downloaded copy from your laptop. Anyone holding this key
   can send notifications to every Edify phone.

### 3. Apple Push Notifications key (APNs): iPhones

1. At <https://developer.apple.com/account/resources/authkeys/list>, under
   Keys, press +, name it "Edify push", tick **Apple Push Notifications
   service (APNs)**, then Continue and Register.
2. Download the **`.p8`** file (Apple lets you download it only once), and
   note the **Key ID** and your **Team ID** (top right of the developer site).
3. In Firebase: Project settings → Cloud Messaging → Apple app configuration →
   APNs Authentication Key → Upload: the `.p8`, Key ID and Team ID. The `.p8`
   goes only to Firebase, never to the Edify server or the repository.
4. In Xcode, App target → Signing & Capabilities → + Capability → **Push
   Notifications**. Xcode adds the `aps-environment` entitlement.

### 4. Build the app with push

With the `mobile/` changes from `feat/mobile-app-home` applied, in `mobile/`:

1. Run `npm install` (adds `@capacitor/push-notifications` 8.1.3 and updates
   the lock file), then `npm run sync`.
2. iPhone only, in Xcode: File → Add Package Dependencies →
   `https://github.com/firebase/firebase-ios-sdk`, and add the
   **FirebaseMessaging** product to the App target. `AppDelegate.swift` turns
   Firebase on only when this package and `GoogleService-Info.plist` are
   present. An iPhone build without them runs normally, and the server
   refuses its Apple-only token with a reason.

## Checking it

- `/api/notifications/push/config` (signed in) answers `enabled` (browsers)
  and `app` (the phone app).
- Turning a device on sends it "Phone notifications are on", through the same
  path as every other notification.
- System health → Notifications (administrators) says whether browsers and
  the app are set up, how many devices there are, and how many are failing
  or were removed this week. Each push copy's fate is on its
  `NotificationDelivery` row (channel `push`).
- Without credentials nothing is sent and nothing claims to have been. The
  page says notifications are not set up on this server yet.
