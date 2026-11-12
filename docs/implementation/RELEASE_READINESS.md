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

## Staff and partner teams moved to Go (2026-11-11)

[docs/migration/10-teams.md](../migration/10-teams.md).

| Check | Result | Evidence |
|---|---|---|
| Go integration suite: teams | Pass | roster scoped to the reader; supervisor reassigned under the level rule (HR may, a CD may not for HR, the Admin overrides); a Program Lead's team configured and a CCEO kept to one lead; a Partner Admin adds a member, gives a login, splits schools (open work renamed, delivered work kept), removes them |
| Database role still refuses the dangerous writes | Pass | deleting a partner, a hand-over or an activity; DELETE allowed in source only in `internal/teams`, only on the three link tables |
| The existing chain verifier | Pass | `verify_chain(full=True)`: ok on dev (620 rows) and test (778 rows), including Go's teams audit rows |
| Django relays | Pass | `staff_changed` advances the analytics revision; accounts, admin_users and the matrix test: 273 passed |
| Web build: Users → Supervisor and Team (Admin) | Pass | Program Lead 1: choices limited to Country Directors, saved and audited `admin.supervisor_reassigned` (then put back); Team lists CCEOs with their current lead |
| Web build: Team (Partner Admin) | Pass | add member, give a login with a first password, two schools, remove (login disabled, links removed); audited `partner.member_login_created`, `partner.school_team_member_set`, `admin.user_disabled`; the test account then removed by the Admin |
| iOS and Android Release: Team (Partner Admin) | Pass | the native Team screen opens from More → Users on both; Add member drawer on iOS |
| App tests | Pass | type-check clean; 162 tests |

## Acting leadership moved to Go (2026-11-11)

[docs/migration/11-acting-leadership.md](../migration/11-acting-leadership.md).

| Check | Result | Evidence |
|---|---|---|
| The policy identical on both sides | Pass | `apps/acting/tests/test_policy_export.py`, and `internal/acting` reads the export |
| Go unit tests | Pass | whole months, this one to eleven ahead; Kampala's day; the state is the dates; the confirmation in the web's words; who appoints, cancels and moves a month; when a request is in the acting capacity |
| Go integration suite: acting | Pass | a Program Lead appoints (grant recorded, hint kept, audited), one per seat and month, an outsider refused and the attempt kept, the month moved, the Director's board, cancelled and kept as History; the appointee enters, leaves (audited), switching role leaves it, entering from another held role returns a token; a Country Director appoints a Program Lead of their country; another Lead cannot see it |
| Database role | Pass | cannot delete an appointment or move it to another seat; still cannot read the audit payload, so the acts-under list stays on the web |
| The existing chain verifier | Pass | `verify_chain(full=True)`: ok, 870 rows on the test database, with Go's acting rows |
| Django | Pass | the relay sends the acting notifications (2 tests); accounts, admin_users, acting and the matrix test: 423 passed; ruff, format, bandit clean |
| Web build | Pass | pl1 appointed Deo M. Acting PL for November 2026 in the app; the web's page listed it and the web presented Deo as "CCEO · Acting PL · November 2026"; the existing notifications went out; in the app Deo's Work as showed the appointment, switching to CCEO left it on both app and web; pl1 cancelled it with a reason, kept in History |
| iOS Release | Pass | pl1 appointed Deo M. Acting PL for November through the drawer (both steps, the web's wording); Deo's More read "CCEO · Acting PL · November 2026", Work as switched to CCEO and back, the tabs following (Oversight in the acting capacity, Schools as CCEO); then cancelled from the app and kept in History |
| Android Release | Pass | Deo's More showed the acting capacity ticked and the Oversight tab; switching to CCEO gave the CCEO card and tabs. The emulator was starved (Android's own "System UI isn't responding"), so the Acting Leadership screen itself was checked on iOS and the web build, not here |

Found and fixed on the iPhone: switching into or out of the acting capacity
left the menu and bottom tabs as they were until the app restarted. The app
reloaded its menu only when the role's name changed, and an acting capacity
keeps the name ("CCEO"); it now reloads on the capacity too.

## School Directory read by Go (2026-11-11)

[docs/migration/12-school-directory.md](../migration/12-school-directory.md).

| Check | Result | Evidence |
|---|---|---|
| The rules identical on both sides | Pass | `apps/schools/test_school_directory_rules_export.py`, and `internal/schooldirectory` reads the export |
| Parity with the existing page | Pass | `cmd/parity` over all 29 seed accounts that may open it: 667 answers compared field by field, none differing. 12 answers the existing page could not give (its project status filter fails); Go gave them |
| Go unit tests | Pass | SSA bands, Python's sum and rounding, the score groups, thousands, the last page, the October year, owner ranking, search escaping, row Actions by role, who may open the page |
| Go integration suite: directory | Pass | an officer reads their own schools 50 a page, each school once, found by School ID; the Admin reads every operating school; a partner admin is refused; someone acting is passed to the existing application |
| Database role | Pass | column SELECT only, on the tables listed in the doc; the package writes nothing |
| Django | Pass | the export test, the acting export and the directory controls audit: 7 passed; ruff, format, bandit clean |
| Web build | Pass | cceo@: 700 schools, page 1 of 14, answered by Go in about 60 ms with no call to the existing application; the project status "Assigned" filter gives 26 schools; a row's Actions menu opens below its button |
| iOS Release | Pass | cceo@: Schools tab, 700 schools, same-named schools in School ID order, answered by Go in 73 ms; a row's Actions menu (Add to Cluster, Add to Project) opens below its button |
| Android Release | Pass | Deo M. (CCEO, holds no school): the existing page's "No schools are assigned to you yet.", answered by Go in 21 ms |

## School Profiles, first piece, read by Go (2026-11-12)

[docs/migration/13-school-profiles.md](../migration/13-school-profiles.md): the
Details tab of an open, non-Core school without Business Transformation
records, with the header, doors and visit rule every tab shares.

| Check | Result | Evidence |
|---|---|---|
| The rules identical on both sides | Pass | `apps/schools/test_school_profile_rules_export.py`, and `internal/schoolprofile` reads the export |
| Parity with the existing page | Pass | `cmd/parity -screen profile` over all 29 accounts that may open a profile: 3,826 Details tabs compared field by field (3,308 of non-Core schools), none differing, refusals included; two schools first put in the lock states the seed lacked, through the existing web app |
| Go unit tests | Pass | the visit rule (open, staff visit, partner waiting and dated, two partners, no partner name, Champion, both doors closed); Django's `floatformat` and Python's `str(float)` checked against Django's own answers; Kampala's dates and year; action keys; the tab strip; the SSA badge; data quality tones; each role's doors |
| Go integration suite: profiles | Pass | Go answers an officer's Details tab with no existing application behind it; another tab and a Core school are passed on; another officer's school and an unknown one are not found; a partner admin is refused; the Admin sees the Danger Zone and Reassign Owner |
| Database role | Pass | column SELECT only; of `bt_case` and `bt_mfi_loan` only `school_id`; the gateway still cannot read the audit payload |
| Django | Pass | both rules exports current; ruff, format, bandit clean |
| Web build | Pass | cceo@: Kimenyedde Church of Uganda Primary's Details tab from Go, "Awaiting schedule from partner", Assign to Partner and Enter SSA Score greyed |
| iOS Release | Pass | cceo@: Central Division Church of Uganda Primary, Overview from the existing application, Details from Go |
| Android Release | Pass | cceo@: KCCA UMEA Primary School's Details tab from Go, "Staff visit scheduled", Assign to Partner and Enter SSA Score greyed |

## School Profiles, the profile engine's tabs, read by Go (2026-11-12)

[docs/migration/13-school-profiles.md](../migration/13-school-profiles.md),
13.6 and 13.7: the Overview (and a profile opened with no tab), Projects,
Stories and Academic, for the same schools as the Details tab.

| Check | Result | Evidence |
|---|---|---|
| The rules identical on both sides | Pass | `apps/schools/test_school_profile_rules_export.py` (now with the engine's statuses, change words, requirements by school type, activity kinds) |
| Parity with the existing page | Pass | `cmd/parity -screen profile`: each of the five served tabs on all 700 of the CCEO's schools, none differing; the engine tabs again for FY2026, Q1, Q3, November and an unknown year and period, none differing; the Overview for all 29 accounts that may open a profile, 3,826 compared, none differing (one session expired partway and was compared again) |
| Records the seed lacked | Made in dev | with the existing models, marked "[Go parity check]": four stories, enrolment for two years and four learning results at Central Division Primary School (1000); there a completed in-school training (6 teachers, 2 leaders, focus Leadership) and an overdue donor visit; and a completed online cluster training at Kimenyedde's cluster with its register |
| Go unit tests | Pass | Python's rounding and sum; periods; the line under a strip's figure, cut as the page cuts it (cases from the real Overview); facts naming people; the change rule with and without a published threshold; the best and struggling intervention |
| Go integration suite | Pass | Go answers the Overview, Projects, Stories and Academic with the frame; no tab, an unknown tab and Core School at a client school open the Overview; SSA and Participation are passed on |
| Django and app | Pass | exports current; ruff, format, bandit clean; app type-check clean, 168 tests |
| iOS Release | Pass | cceo@: a school's Overview from Go, the facts reading "Status: Operating" in one line, the strips filled |
| Android Release | Pass | cceo@: Central Division Primary School's Overview from Go: Teachers Trained 6, School Leaders Trained 2, Enrolment Growth +9.4% |

## School Profiles, the SSA tab, read by Go (2026-11-12)

[docs/migration/13-school-profiles.md](../migration/13-school-profiles.md),
13.8: the Intervention Matrix, both SSA charts, the change between confirmed
assessments and the SSA history, for the same schools as the other tabs.

| Check | Result | Evidence |
|---|---|---|
| The rules identical on both sides | Pass | `apps/schools/test_school_profile_rules_export.py` (now with the SSA target, the rule sentence, the 120-day gap, the pairs shown, the verified activity statuses and the fallback rule label); `rules.json` matches a fresh export |
| Parity with the existing page | Pass | `cmd/parity -screen profile -tab ssa` over all 29 accounts that may open a profile: 3,826 compared (3,308 of non-Core schools), none differing; the CCEO's 700 schools again for FY2026, none differing; the other five served tabs compared again on the CCEO's 700 schools after the change, none differing |
| Records the seed lacked | Made in dev | every seeded SSA is dated 9 November 2026, so no pair was ever compared; with the existing models, at Central Division Primary School (1000): a confirmed FY2027 SSA dated 15 March 2027 with all eight scores, a completed coaching visit between the readings (marked "[Go parity check]") and a pending FY2028 SSA |
| Go unit tests | Pass | a pair judged by the country's rule first, then the deployment's, then any move; the mean of the domain thresholds as the school's rule |
| Go integration suite | Pass | Go answers the SSA tab with all eight interventions and "All interventions" in the matrix, and the change and history panels; Participation is still passed on |
| Django and Go checks | Pass | ruff, format, bandit clean; `go vet`, `gofmt`, `go test -race ./...` |
| iOS Release | Pass | cceo@: school 1000's SSA tab from Go: Annual SSA Progress 5.9 and 6.3; "FY2026 vs FY2027 · 9 Nov 2026 → 15 Mar 2027 · 125 days apart", Improved (0.10), 1 activity: Leadership coaching |
| Android Release | Pass | cceo@: school 1026's SSA tab from Go: the matrix, both charts (5.9 and 4.4), "Not compared (readings less than 120 days apart)", and its two confirmed records in the history |

## School Profiles, the Participation tab, read by Go (2026-11-12)

[docs/migration/13-school-profiles.md](../migration/13-school-profiles.md),
13.9: the year's work by kind, training by channel, cluster meetings, the
planned and completed activities with each row's menu, visit findings and
partner support.

| Check | Result | Evidence |
|---|---|---|
| The rules identical on both sides | Pass | `apps/schools/test_school_profile_rules_export.py` (now with the activity list's statuses and words, who may run work, the My Plan door per role and a hand-over's next step); the export stops if `left_partner_q` changes |
| Parity with the existing page | Pass | `cmd/parity -screen profile -tab activities` against a gateway with no existing application behind it: all 29 accounts that may open a profile, 3,826 compared, every answer Go gave identical, the rest passed on by design (426, Core schools); the CCEO's 700 schools for FY2026, Q2, November and an unknown year and period, 597 answered by Go, identical; the other six tabs re-run the same way on those 700, every Go answer identical |
| Records the seed lacked | Made in dev | the seed's school activities were only completed or scheduled; with the existing models at Kimenyedde (1578), marked "[Go parity check] participation": one activity in each other state the list reads, a cluster meeting it is invited to, a group training it attended, a returned and a dated hand-over; at Central Division Primary School (1000) one visit finding |
| Go unit tests | Pass | Django's title and truncation, Python's rounding; the page reader's label-and-figure pairing; each status as the list words it; who may run work (a lead's team read-only, their own and their direct clusters run; a Country Director read-only) |
| Go integration suite | Pass | Go answers Participation with its three tables and the Planned / Completed list; every row opens its activity; the tick bar is present exactly when a row can be ticked |
| Django and Go checks | Pass | ruff, format, bandit clean; `go vet`, `gofmt`, `go test -race ./...` |
| iOS Release | Pass | cceo@: Kimenyedde's Participation tab from Go: the work and channel tables, "Next: Cluster E, 28 Nov.", 7 planned and 7 completed, and Partner Support with "UGX 40,000" |
| Android Release | Pass | cceo@: the same tab, the rescheduled training reading "26 Nov 2026 – 28 Nov", and the four hand-overs |

## Open items

- Measure cold and warm start on physical iPhones and Android phones.
- Sign in as each role on a device (only CCEO and Cluster Leader were used).
- Role switching in the app (needs an identity API; part of moving sign-in to Go).
- iPad and desktop-window layouts were measured in the browser build, not on
  an iPad.
