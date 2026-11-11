# Release readiness — app icon, launch screen and sign-in

Branch `feature/edify-go-rn-migration`, development environment only (local
Django identity on :8010, Go gateway on :8090, dev database `edify_gorn_dev`).
Nothing here touched production. Checklist: [ENTERPRISE_EXPERIENCE_CHECKLIST.md](ENTERPRISE_EXPERIENCE_CHECKLIST.md).

Tested 2026-11-11 on Release builds with development endpoints:

- iOS: `Edify.app`, Release, iPhone 18 Pro simulator (iOS 26).
- Android: `app-release.apk`, Pixel 9 emulator, Android 16 (API 36). The
  emulator draws with software rendering (its log: "forcing software
  rendering for GLES").

**Verdict: NOT YET VERIFIED.** Everything below passed except the cold-start
target, which was missed on the simulator and emulator, and has not been
measured on physical phones.

## The brief's tests

| # | Test | Result | Evidence |
|---|------|--------|----------|
| 1 | App icon appears correctly on iOS | Pass | Simulator home screen: new "Edify" icon, rounded, wordmark centred, wave intact. |
| 2 | App icon appears correctly on Android | Pass | Pixel 9 app drawer: "Edify" round adaptive icon. |
| 3 | Android adaptive icon is not cropped | Pass | Wordmark sits inside the 72 dp safe zone; drawer icon shows the whole word and the wave. |
| 4 | Icon recognisable at small sizes | Pass | `platform/mobile/assets/brand/previews/icon-sizes.png` (40 px iOS, 48 px Android). |
| 5 | Native launch screen displays correctly | Pass | iOS: navy with "edify │ Planning & Monitoring". Android: navy with the wordmark. |
| 6 | No unwanted flashing at launch | Pass | Android frame-by-frame capture: launcher → navy launch screen → Home, no white or black frame between. iOS: one black frame on the very first launch after installing a build that was not signed (fixed by ad hoc signing); none after. |
| 7 | No artificial delay | Pass | No timer holds the launch screen; it hides as soon as the saved sign-in is confirmed. |
| 8 | Valid sessions restore | Pass | Both platforms: after a full quit and relaunch, the app opens straight on the CCEO Home with no sign-in. |
| 9 | Expired sessions are rejected | Pass (unit) | `launch.test.ts`: unauthenticated → Sign in, saved sign-in cleared. Not forced on a device. |
| 10 | Users reach their role's home | Pass (unit + device for CCEO) | `landing.test.ts` mirrors `apps/core/landing.py`; CCEO landed on Home on both platforms. Other roles not signed in on a device. |
| 11 | Users cannot open unauthorised screens | Unchanged | The gateway still authorises every request; menus come from the person's permissions. |
| 12 | Sign-out clears protected state | Pass | iOS: Sign out → Sign in; tokens cleared; identity log shows `POST /api/auth/logout 200` (refresh token revoked). Only the remembered address was kept, as on the web. |
| 13 | Network failures handled clearly | Pass (unit) | Offline or server fault at launch → "Edify could not be reached" with Try again; sign-in kept. Not forced on a device. |
| 14 | Sign-in works on small phones | Pass | Phone layout measured at 390×844 against the web page (within 0.5 px); used on both devices. |
| 15 | Keyboard does not cover the action | Pass (after fix) | iOS: the button was hidden by the keyboard; now the form scrolls so "Access workspace" stays above it (verified on the simulator). |
| 16 | Public loan application opens without sign-in | Pass | `GET :8090/loans/apply` 200 and `/loans/track` 200 with no session. |
| 17 | Secure statements stay reachable through verification | Pass | Integration `TestASchoolOpensOnlyItsOwnStatementWithACode`. |
| 18 | iOS and Android builds verified | Pass | Both Release builds built, installed and used as above. Physical devices not tested. |
| 19 | Startup measured | **Target missed / not representative** | See below. |
| 20 | Production data not modified | Pass | Dev database only; `src/config/environment.ts` refuses production hosts. |

## Startup measurements

Proposed targets: cold launch ≤ 3 s p95, warm launch ≤ 1.5 s p95.

| Measurement | Runs | Result | Method |
|---|---|---|---|
| Android cold → Sign in (no session) | 7 | 2.30–3.46 s | On-device pixel sampling every ~154 ms from `am start` |
| Android cold → Home (saved session) | 7 | 2.93–3.74 s | Same |
| Android warm → Home | 7 | 0.90–1.36 s | Same, app resumed from the background |
| iOS cold → Home data answered (saved session) | 4 (+1) | 2.99–3.18 s | Launch command to the gateway's completed `GetHome` request; the first run after install took 8.8 s and is left out as a one-off |
| iOS warm | — | Not measured | The simulator's screenshot sampler takes 1.5 s, too slow to time it |

Where the iOS time goes, from the system log for one launch:

1. About 2.5 s from the launch command to the app's first log line. This is
   the simulator starting the process; none of the app's code has run yet.
2. About 0.3 s to read the keystore and send the session check.
3. About 0.12 s for the gateway to answer the session, menu and Home.

The app's own share is under half a second. The cold-start target is still
reported as missed, because these runs are over 3 s. A simulator on a laptop
and a software-rendered emulator are not representative phones. The brief
asks for measurements on representative supported phones, and none were
available here.

Changes made during measurement: the session check now runs while the fonts
load instead of after them (no measurable change on the simulator), and the
launch now reaches Sign in even if the phone's keystore cannot be read.

## Sign-in moved to Go (2026-11-11)

The app now signs in through the Go gateway's `SignInService`
([docs/migration/08-sign-in.md](../migration/08-sign-in.md)); the brief's
tests 8, 9, 12 and 13 above now run against Go.

| Check | Result | Evidence |
|---|---|---|
| Go unit tests against values made by the existing code | Pass | `internal/signin`, `internal/audit`: bcrypt and PBKDF2 hashes, TOTP code, encrypted secret, audit hashes all produced by the existing application |
| Go integration suite (test database, real gateway role) | Pass | sign-in, lockout at 10, refusal reasons, rate limit, code by email, refresh reuse, sign-out, reset link once, invitation once, figures, chain recomputed |
| The existing chain verifier over Go's rows | Pass | `verify_chain(full=True)`: ok, 572 rows, 90 written by Go |
| One session across both systems | Pass | dev database: Go session accepted by `/api/auth/me`, rotated by the existing refresh, then by Go; the spent token refused across both |
| Admin alert from a Go sign-in | Pass | five wrong passwords through Go raised the existing "Failed-login threshold" incident |
| Web build: code step | Pass | wrong code refused with the server's words; right code opened Home |
| iOS Release: sign in through Go | Pass | `SignIn 200`, CCEO Home |
| Android Release: saved session renewed, sign out, sign in | Pass | `RefreshSession 200` on the session saved before the update, `SignOut 200`, `SignIn 200`, CCEO Home |
| An app sign-in is recorded as a phone, not a desktop | Pass (Android) | `login_event.device = mobile`; the app now declares phone or tablet, because its HTTP library names itself, not the device. Not re-checked on iOS (the iOS build predates this fix; unit-tested). |
| Django accounts suite after the change | Pass | 250 passed |

Not yet: the web's own sign-in page (production cutover, needs approval),
user creation and account lifecycle, role switching.

## Accounts and roles moved to Go (2026-11-11)

[docs/migration/09-accounts-and-roles.md](../migration/09-accounts-and-roles.md).

| Check | Result | Evidence |
|---|---|---|
| Permission matrix identical on both sides | Pass | `apps/core/test_rbac_matrix_export.py` (Django) and `internal/rbac` (Go) over the exported matrix |
| Go integration suite: accounts | Pass | role switch kept across a renewed session and refused for an unheld role; non-Admin refused; invite → accept → sign in; Admin-chosen password blocks every call until replaced; role changes under the Admin/CCEO rules; suspend ends sessions; unlock and temporary password; removal frees the address, the last Admin stays |
| Database role still refuses the dangerous writes | Pass | superuser and staff flags, second-factor enrolment, ids, deleting accounts, sessions or audit rows |
| The existing chain verifier | Pass | `verify_chain(full=True)`: ok, 715 rows |
| Django relays for what follows a change | Pass | 4 tests; on the dev servers `account_deleted` and `roles_changed` both answered ok |
| Web build: Work as | Pass | CCEO ⇄ Program Lead; saved on the account and audited; the account reopened in the new role after signing in again |
| Web build: Users (Admin) | Pass | 42 accounts listed; Add user with a first password; the new person held at Password Change Required, a mismatch refused in the existing words, then Home; Remove account |
| iOS and Android Release: Work as | Pass | both switched CCEO ⇄ Program Lead (menu and Oversight tab followed) |
| Django suites after the change | Pass | accounts, admin_users and the matrix test: 272 passed |

Found and fixed while checking: the role switcher's spinner stayed after a
successful switch; the Users screen's filter tabs and the shared drawer
buttons had no accessible names. The development identity server had to be
restarted to serve the new relay route (it runs without reloading).

## Open items

- Measure cold and warm start on physical iPhones and Android phones.
- Sign in as each role on a device (only CCEO and Cluster Leader were used).
- Role switching in the app (needs an identity API; part of moving sign-in to Go).
- iPad and desktop-window layouts were measured in the browser build, not on
  an iPad.
