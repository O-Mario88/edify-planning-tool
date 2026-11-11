# Enterprise Experience 2.0 — implementation checklist

Persistent record for the owner's Enterprise Experience 2.0 mandate
(2026-11-11) and its extension "Mandatory app icon, native launch screen &
authentication experience". Branch: `feature/edify-go-rn-migration`. Test
results for section A are in [RELEASE_READINESS.md](RELEASE_READINESS.md).

States: **Not Started** · **In Progress** · **Implemented — Not Verified** ·
**Failed Verification** · **Blocked — External Dependency** · **Verified Complete**.

A state of *Verified Complete* names the evidence. Nothing here is marked
verified on the strength of code alone.

## A. App icon, launch screen and sign-in (extension brief)

| # | Item | State | Evidence / note |
|---|------|-------|-----------------|
| A1 | Icon source artwork from the authentic logo | Verified Complete | `platform/mobile/scripts/brand_assets.py` rebuilds the wordmark from `static/images/logo.png` (no new logo); colours and wave in `assets/brand/brand.json`. |
| A2 | iOS icon (light, dark, tinted) | Verified Complete | Simulator home screen, Release build; dark and tinted variants built but not yet viewed. |
| A3 | Android adaptive icon (foreground, background, monochrome) | Verified Complete | Pixel 9 emulator app drawer, uncropped; wordmark inside the 72 dp safe zone. |
| A4 | Icon previews at home-screen sizes | Verified Complete | `assets/brand/previews/icon-sizes.png` (iOS 180–40, Android 192–48, light and dark wallpapers); readable at 40 and 48 px. |
| A5 | Web favicon / manifest colours | Implemented — Not Verified | `assets/favicon.png`, `app.json` `web`. The Django web app keeps its own icons (owner decision, see RELEASE_READINESS). |
| A6 | Native launch screen, iOS | Verified Complete | expo-splash-screen: navy `#062847`, "edify │ Planning & Monitoring" lockup. |
| A7 | Native launch screen, Android | Verified Complete | Navy, wordmark alone (Android 12+ masks the launch image to a circle). |
| A8 | No blank flash; no artificial delay | Verified Complete | Android frame capture; iOS after the signing fix. No timer extends it. |
| A9 | Valid session opens the role's home directly | Verified Complete | Quit and relaunch on both platforms opened Home with no sign-in. |
| A10 | Expired session → sign in; offline → retry, sign-in kept | Implemented — Not Verified | `afterFailedCheck` (unit-tested); `LaunchView` retry screen. |
| A11 | Sign-in screen replicates the web page (desktop, tablet, phone) | Verified Complete | Measured against the live web page at 1440×900, 768×1024, 390×844: every compared element within 0.5 px (phone), 1 px (tablet), 0.1 px (desktop). Tablet shows the figures 2×2 (web tablet swipes them). |
| A12 | Password visibility, Remember me, Forgot password, errors, sign-in code | Implemented — Not Verified | Remember me verified on iOS. Sign-in code step verified in the web build (wrong code refused, right code opened Home); reset link verified by the Go integration suite, not sent from a device. |
| A13 | Secure sign-out (server revocation) | Verified Complete | iOS sign-out; identity log `POST /api/auth/logout 200`. |
| A14 | Role-aware landing | Implemented — Not Verified | `src/landing.ts`: the web's rule (Home; Country Oversight for IA, CD, RVP, RPL when permitted). Cluster Leaders open their portal. Unit-tested. |
| A15 | Account / role switching | Verified Complete | Go AccountService.SwitchRole; More → Work as (docs/migration/09-accounts-and-roles.md). Web build, iOS and Android Release: CCEO ⇄ Program Lead, saved on the account and audited. |
| A16 | Public school forms open without sign-in | Verified Complete | `/loans/apply` and `/loans/track` answer 200 without a session. |
| A17 | Startup measured | Failed Verification | Cold start 2.3–3.7 s (emulator) and 3.0–3.2 s (simulator) against a 3 s target; warm 0.9–1.4 s. Physical phones not measured. |
| A18 | Sign-in and users handled by Go | In Progress | The app signs in through Go's SignInService (docs/migration/08-sign-in.md): password, lockout, second factor, sessions, reset, invitations, figures. Verified: Go unit + integration suites, Django's verify_chain over Go's audit rows, sessions honoured across both systems, iOS and Android sign-in. Not yet: the web's own sign-in page (production cutover, needs approval). User creation, account lifecycle and role switching followed (docs/migration/09-accounts-and-roles.md), then staff and partner teams (docs/migration/10-teams.md) and acting leadership (docs/migration/11-acting-leadership.md). |
| A19 | School Directory read by Go | Verified Complete | Go answers GetSchoolDirectory (docs/migration/12-school-directory.md): scope, filters, tabs, data gaps, rows, row Actions, pages. Verified: parity with the existing application on all 29 seed accounts that may open it (667 answers compared, none differing), Go unit + integration suites, web build, iOS and Android Release. The directory's writes and school profiles are still the existing application's. |
| A20 | School Profiles read by Go (first piece) | Verified Complete | Go answers the Details tab of an open, non-Core school without Business Transformation records, with the shared header, doors, tabs and the one-visit-a-year rule (docs/migration/13-school-profiles.md). Verified: parity on all 29 seed accounts that may open a profile (3,826 compared, none differing), Go unit + integration suites, web build, iOS and Android Release. The other tabs, Core and closed schools and the loan register are still the existing application's. |

## B. Enterprise Experience 2.0 (main mandate)

| # | Item | State |
|---|------|-------|
| B1 | Baseline audit with screenshots per role and viewport | Not Started |
| B2 | Design system (tokens, components, typography) | Not Started |
| B3 | App shell, navigation, global search | Not Started |
| B4 | Flagship workspaces: CCEO, PL, Cluster Leader, CD | Not Started |
| B5 | Remaining role workspaces | Not Started |
| B6 | KPI strip, server-side tables, 360° profiles | Not Started |
| B7 | Real-time (commit-then-publish, reconnection) | Not Started |
| B8 | Performance targets and isolated load tests | Not Started |
| B9 | WCAG 2.2 AA, visual regression, task tests | Not Started |
| B10 | Before/after screenshots for every role; final report | Not Started |
