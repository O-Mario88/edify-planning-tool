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

## School Profiles, Core schools and the Core School tab, read by Go (2026-11-12)

[docs/migration/13-school-profiles.md](../migration/13-school-profiles.md),
13.10 and 13.11: the Core package's 2 + 2 rule in a Core school's header,
its package on Details, every engine tab at a Core school, and the Core
School tab of any Core-lifecycle school.

| Check | Result | Evidence |
|---|---|---|
| The rules identical on both sides | Pass | `apps/schools/test_school_profile_rules_export.py` (now with the package split's vocabularies, the slot states, the Core Schools door, and the Core School tab's words and statuses) |
| Parity with the existing page | Pass | against a gateway with no existing application behind it: every tab on all 700 of the CCEO's schools, Core included, every Go answer identical; Details, Participation and the Core School tab for all 29 accounts (3,826 each), none differing, the only profiles passed on the two schools with a Business Transformation record |
| Records the seed lacked | Made in dev | every seeded Core package was open: at 1006, through the existing web app as the CCEO, two staff core visits and four hand-overs to Literacy Uganda (the staff half full, the partner's half taken), and three SSA recommendations through the existing service (accepted, deferred, generated) |
| Go unit tests | Pass | package work by shape and deliverer, a hand-over's kind, each side's two closing its door, a slot's state; the Core School tab's package share, attendance rounding, headcounts, Champion checks and review, recommendations with and without Plan support |
| Go integration suite | Pass | a Core school's Core School tab and Details are Go's, its Schedule opening the Core Schools drawer |
| Django and Go checks | Pass | ruff, format, bandit clean; `go vet`, `gofmt`, `go test -race ./...` |
| iOS Release | Pass | cceo@: school 1006 from Go: "Staff visits complete", Assign to Partner greyed; the Core School tab with "Staff: 2 visits, 0 trainings · Partner: 2 visits, 2 trainings" and the recommendations with Plan support |
| Android Release | Not run | the emulator hung repeatedly (window manager stuck; cold boots on host and software graphics both froze under load); the same block kinds were checked on Android in the earlier pieces |

## School Profiles, closed schools, read by Go (2026-11-12)

[docs/migration/13-school-profiles.md](../migration/13-school-profiles.md),
13.12: every tab of a temporarily or permanently closed school.

| Check | Result | Evidence |
|---|---|---|
| The rules identical on both sides | Pass | `apps/schools/test_school_profile_rules_export.py` (now with the operational statuses and closure reasons) |
| Parity with the existing page | Pass | school 1078 for all 29 accounts on all eight tabs against a gateway with no existing application behind it: 232 answers, none differing (refusals included); the CCEO's 699 open schools again for Details and Overview, none differing |
| Records the seed lacked | Made in dev | school 1078 closed temporarily through the existing web app as the CCEO, its reason marked "[Go parity check]" |
| Go integration suite | Pass | a school closed for the test reads "Back to Closed Schools", has no Schedule, Assign to Partner or Close School, and opens on its banner |
| Django and Go checks | Pass | ruff, format, bandit clean; `go vet`, `gofmt`, `go test -race ./...` |
| iOS Release | Pass | cceo@: Closed Schools → 1078 from Go: the banner, Edit Details and Add to Project only, "Status: Closed" |
| Android Release | Not run | the emulator hangs (see the Core section) |

## School Profiles, Business Transformation and the loans strip, read by Go (2026-11-12)

[docs/migration/13-school-profiles.md](../migration/13-school-profiles.md),
13.13: the Business Transformation panel on Details and the loans strip on
the Overview, so every school's profile is now read by Go.

| Check | Result | Evidence |
|---|---|---|
| The rules identical on both sides | Pass | `apps/schools/test_school_profile_rules_export.py` (now with the case and loan statuses, the sensitive-view and case-manager doors) |
| Parity with the existing page | Pass | against a gateway with no existing application behind it: schools 1001 and 1002 (a case and a loan each) for all 29 accounts on all eight tabs, 464 answers, none differing; every directory school for all 29 accounts on Overview and Details, 3,822 each, none differing, none passed on |
| Lines the seed has no record for | Unit tests | a case's response, practice and compliance assessments, repayment snapshots, EdTech loans: built from the template's words |
| Go unit tests | Pass | money shortened as the strip shortens it ("UGX 38.5M", half-even, zeros trimmed); a loan's lines with and without the sensitive view |
| Go integration suite | Pass | a school with a case and a loan is Go's on Details and Overview |
| Django and Go checks | Pass | ruff, format, bandit clean; `go vet`, `gofmt`, `go test -race ./...` |
| iOS Release | Pass | cceo@: school 1001's Overview from Go: "1 loan", "UGX 38.5M", "1 case" |
| Android Release | Not run | the emulator hangs (see the Core section) |

## Clusters page read by Go (2026-11-12)

[docs/migration/14-districts-and-clusters.md](../migration/14-districts-and-clusters.md),
piece 1 of M2: whose clusters, the filters, the strip, the cards with their
menus, and the pages of `/clusters`.

| Check | Result | Evidence |
|---|---|---|
| The rules identical on both sides | Pass | `apps/clusters/test_cluster_page_rules_export.py` (each role's doors, the statuses and activity types each figure counts, the interventions, the strip's labels) |
| Parity with the existing page | Pass | all 29 accounts against a gateway with no existing application behind it, 870 answers (the page as it opens, every filter value it offers, searches, later and out-of-range pages, years and quarters, the two roles turned away), none differing |
| Records the seed lacked | Made in dev | seven clusters "[Go parity check] Cluster 1–7" through the existing services as the CCEO: covered sub-counties out of order, one with none, leaders with stray spaces, a phone, one facilitated by Literacy Uganda; five pages |
| Go unit tests | Pass | the risk's order (every branch, Needs Attention and Healthy included), the weakest four and their ties, Django's elided pages and `int()` page numbers, half-even shares, the figures' formats, a card's facts and colours, the sub-county fallbacks, the empty strip, the figure filters, the role gate |
| Go integration suite | Pass | the officer's own clusters with their doors and total, the risk filter, an officer with none offered Create Cluster, a Project Coordinator turned away |
| Django and Go checks | Pass | ruff, format, bandit clean; the cluster suites (56 tests) after the planning statuses became module constants; `go vet`, `gofmt`, `go test -race ./...`, the integration suite |
| iOS Release | Pass | cceo@: More → Clusters from Go (the gateway ran the page's own statements at the moment of the request): 22 clusters, "Mukono, Nakisunga, Goma Division, Kasawo", "District-level cluster", "Facilitated by: Literacy Uganda", an opened card's "No confirmed SSA scores are available yet." |
| Android Release | Not run | the emulator hangs (see the Core section) |

## A cluster card's schools read by Go (2026-11-12)

[docs/migration/14-districts-and-clusters.md](../migration/14-districts-and-clusters.md),
14.4: the list a cluster card loads when it opens, with the planning badges,
the visit lock, who supports each school and its Next Activity.

| Check | Result | Evidence |
|---|---|---|
| The rules identical on both sides | Pass | `apps/planning/test_school_planning_rules_export.py`, `apps/clusters/test_cluster_page_rules_export.py` |
| Parity with the existing page | Pass | all 22 clusters for all 29 accounts on a gateway with no existing application behind it, four years each: 2,552 answers, none differing (four accounts re-asked after two grants were restored: 352, none differing) |
| Go unit tests | Pass | badge buckets and kinds, chip words and order, a meeting as planned training, the day of a scheduled instant, a cell's chips read side by side, a row's doors, links, tick and facts |
| Go integration suite | Pass | the officer's cluster's schools with their rows and bar; another officer turned away |
| Django and Go checks | Pass | ruff, format, bandit clean; `go vet`, `gofmt`, `go test -race ./...` |
| iOS Release | Pass | cceo@: Clusters page 2 → Cluster C → Show details: "Schools in Cluster (6)" and its rows, through the main gateway, which sends this path to Go before any fallback (the database did not show which process answered this time, so the Go-only parity above is the proof of the answer) |
| Android Release | Not run | the emulator hangs |

## Cluster Oversight, Closed Schools and Programme Schools read by Go (2026-11-12)

Built by two agents in their own worktrees and branches, then merged into the
migration branch by the coordinator ([15](../migration/15-cluster-oversight.md),
[16](../migration/16-closed-schools.md), [17](../migration/17-programme-schools.md)).

| Check | Result | Evidence |
|---|---|---|
| The rules identical on both sides | Pass | `apps/clusters/test_cluster_oversight_rules_export.py`, `apps/schools/test_closed_schools_rules_export.py`, `apps/schools/test_programme_schools_rules_export.py` |
| Parity, re-run by the coordinator on the merged build | Pass | all 29 accounts on a gateway with no existing application behind it: Closed Schools 580 answers, Programme Schools 891, none differing; Cluster Oversight 725 answers at `/cluster-oversight/` and 29 at each address the feed refuses, none differing |
| Beyond the seed | Pass | the agents' golden comparisons: Cluster Oversight 17 pages built by the unmodified Django code from synthetic records; Closed Schools 403 answers over 530 closures in the test database; both school pages on a varied private copy (302 and 200 answers, none differing once tied rows are set aside) |
| Django and Go checks | Pass | ruff, format, bandit clean; the cluster suites (313 tests) after `workspace.py`'s Command Center words became module constants; `go vet`, `gofmt`, `go test -race ./...`, the integration suite |
| Known differences kept on purpose | — | ties with no order in the existing code (same-day closures, same-named programme schools) can come back in either order on both sides; see the documents' "looked wrong" lists |
| iOS / Android Release | Not run | not checked on a device for these three pages |

## The Planning page read by Go (2026-11-12)

[docs/migration/24-planning-page.md](../migration/24-planning-page.md): the
first piece of M4.

| Check | Result | Evidence |
|---|---|---|
| The rules identical on both sides | Pass | `apps/planning/test_planning_page_rules_export.py` (doors, menus, strip labels, the counted-visit rules, the planning service's lists now module constants) |
| Parity with the existing page | Pass | all 29 accounts on a gateway with no existing application behind it, every tab: 1,431 answers, none differing; rows with the same name compared in School ID order (104 answers held such rows; the existing page gives them no order) |
| Go unit tests | Pass | the pager window, quarters, how the view reads its filters, group headings, tab links, fact colours, a row's facts, links and doors, the empty states, the bar |
| Go integration suite | Pass | the officer's Client tab with its rows and bar, the Clusters tab's cards, a priority allocation passed on, a role without Planning turned away |
| Django and Go checks | Pass | ruff, format, bandit clean; the planning suites (1,680 tests) after the service's inline lists became module constants; `go vet`, `gofmt`, `go test -race ./...` |
| iOS Release | Pass | cceo@: More → Planning through the main gateway (answered in 0.3 s): the strip, "Your FY2027 visits: 7 of 560 planned.", Client and Core tabs with the rest under More |
| Android Release | Not run | the emulator hangs |

## The Decision Log, Escalations, My Actions and Core School Oversight read by Go (2026-11-12)

Built by two agents in their own worktrees and branches, then merged into the
migration branch by the coordinator ([18](../migration/18-decision-log.md),
[19](../migration/19-escalations.md), [21](../migration/21-my-actions.md),
[22](../migration/22-core-schools-oversight.md)). Field Debriefs
([20](../migration/20-field-debriefs.md)) and Team Performance were not moved.

| Check | Result | Evidence |
|---|---|---|
| The rules identical on both sides | Pass | `apps/audit/test_decision_log_rules_export.py`, `apps/flags/test_escalations_rules_export.py`, `apps/planning/test_my_actions_rules_export.py`, `apps/core_schools/test_core_oversight_rules_export.py` |
| Parity, re-run by the coordinator on the merged build | Pass | all 29 accounts on a gateway with no existing application behind it: Decision Log 783 answers, Escalations 551, My Actions 406, Core School Oversight 2,117 (and 29 at each address the feed refuses), none differing; Cluster Oversight 725 and Planning 1,431 re-checked on the same build, none differing |
| Beyond the seed | Pass | the agents' golden comparisons from the unmodified Django feed over synthetic rows in the test database (all removed afterwards): Decision Log 578 answers, Escalations 238, My Actions 350; Core School Oversight 40 pages, none differing |
| The gateway still cannot read the audit chain's payloads | Pass | the branch had granted `audit_log.payload`, which `TestGatewayRoleCanNeitherWriteNorReadSecrets` refuses. The Decision Log now reads `gateway_read.decision_audit` (`platform/deploy/db/decision_log_roles.sql`: its own schema and NOLOGIN owner, the decision rows only, their subject keys only); `TestTheDecisionLogViewShowsOnlyDecisions` checks it against the exported rules. A new database object: production needs the owner's approval at cutover |
| Learning scores add as Python adds | Pass | Go may fuse a multiply and an add (arm64 does); the learning sums of Cluster Oversight and the Core School tab now round each product first; tests use sums where the fused answer differs |
| Django and Go checks | Pass | ruff, format, bandit clean; core_schools, audit and flags suites (368 tests) after their inline lists became module constants; `go vet`, `gofmt`, `go test -race ./...`, the integration suite |
| iOS / Android Release | Not run | not checked on a device for these pages |

## My Plan, first piece, read by Go (2026-11-12)

[docs/migration/25-my-plan.md](../migration/25-my-plan.md): the page for a
staff member who holds nothing yet. Everyone else's My Plan is still the
existing application's.

| Check | Result | Evidence |
|---|---|---|
| The rules identical on both sides | Pass | `apps/my_plan/test_my_plan_rules_export.py` (the strip's tiles, month and quarter choices and the export keys, now module constants) |
| Parity, re-run by the coordinator on the merged build | Pass | the 5 accounts Go answers or refuses (Admin, Country Director, Impact Assessment, Project Coordinator, Business Transformation), gateway with no existing application behind it: 335 answers, none differing; the agent also showed all 29 accounts unchanged with the existing application behind the gateway (1,943 answers, none differing) |
| The plan's counts (piece 2) | Pass | `TestThePlanIsCountedAsTheExistingPageCountsIt`: Go against `get_frontend_context` itself on dev, re-run by the coordinator for cceo@, pl1@ and admin@: 162 plans counted, none differing; parity on the merged build for the 5 accounts Go answers: 335 answers, none differing |
| Django and Go checks | Pass | ruff, format, bandit clean; the my_plan suite (106 tests); `go vet`, `gofmt`, `go test -race ./...`, the integration suite | (re-run after piece 2: 106 tests, the integration suite, race)
| iOS / Android Release | Not run | not checked on a device |

## Open items

- Measure cold and warm start on physical iPhones and Android phones.
- Sign in as each role on a device (only CCEO and Cluster Leader were used).
- Role switching in the app (needs an identity API; part of moving sign-in to Go).
- iPad and desktop-window layouts were measured in the browser build, not on
  an iPad.
