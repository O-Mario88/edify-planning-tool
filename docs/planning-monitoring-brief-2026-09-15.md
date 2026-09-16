# Planning & Monitoring brief — implementation record

**Brief dated 2026-09-15. Implemented 2026-09-15 to 2026-09-16, on `main`.**

Twenty-one sections, each a complaint about something the platform did or
refused to do. This is what was actually wrong in each case, what changed, and
how it was proved — in the browser, against the seeded demo data, not only in
tests.

---

## 1. Root causes

| § | The complaint | What was actually wrong |
|---|---|---|
| 2 | Admin cannot find Users or Upload | Both pages existed and were reachable. `nav_cadence.py` ranked them below a dozen reference links, so they sat at the bottom of a long sidebar. A ranking bug, not a missing page. |
| 3 | IA cannot add a partner | `partner_services.onboard` minted a Partner Admin **login** as part of creating the **organisation**, so the whole act needed user-administration authority. One permission was doing two jobs. |
| 4–5 | Add to Cluster fails | Three separate faults: an absolute same-district rule with no way to govern an exception; a picker that offered clusters the save would refuse; and no path at all for a school already in a cluster. |
| 6 | Follow-up visits blocked | The prerequisite was hardcoded in the scheduling service. No setting, no country, no year — nothing to turn off. |
| 7–8 | No school coverage view | Never built. Team Oversight answered "how is my team doing", never "which schools have nothing planned". |
| 9 | "Scheduled for Visit" is wrong | It was an editable boolean on the school record that drifted from the activities it claimed to describe. |
| 10 | Cannot reassign an owner | No such concept. Ownership was a column, changed by editing the school, with no preview, no history and no answer for the open work. |
| 11 | Cannot plan FY2027 | No FY2027 rate card, and `initialize_default_catalogue_view` ignored the FY the user had selected. |
| 12 | Cluster meetings missing from My Plan | Four faults, the last found in the browser on the final day: My Plan's FY select was hardcoded 2023–2026; the Clusters drawer created meetings with no catalogue item and did not redirect; the Project My Plan dropped meetings; **and the cluster page's own "Schedule Cluster Meeting" button pointed at `/planning`, the dashboard, while the form at `/planning/schedule` posted back to its own GET view and recorded nothing.** |
| 13 | Add to Project fails | The guard required the person adding the school to be assigned to the project — so the officer who owned the school was offered no projects and refused if they tried. |

## 2. Journeys walked in the browser

All ten §19 journeys were run against `127.0.0.1:8000` with the seeded demo
accounts. Screenshots: `outputs/brief-evidence-2026-09-16/` (git-ignored).

| # | Journey | Result |
|---|---------|--------|
| 1 | Admin finds Users and Upload | Both 200, both at the top of DAILY |
| 2 | IA creates a partner organisation | "Border Support Alliance" created, profile reads "User setup pending", IA offered no "Set up login" and is bounced from `/admin-panel/users`; the CD sees the three-mode login drawer |
| 3 | Cross-district cluster | CD approved Buikwe as a neighbouring district for Cluster A (audited, reason recorded); the CCEO added the border school; the school's district is unchanged and the membership is marked cross-district |
| 4 | Follow-up with no prior training | Scheduled; picker optional; note reads "No prior training recorded"; 2 cost lines, 62,000 UGX |
| 5 | Planned schools and coverage | Totals reconcile across week / month / quarter / FY; reasons are "School not attached to a cluster" and "No cluster training planned"; the PL's To-Do names 693 schools and opens the filtered table |
| 6 | Scheduled for Visit | Derived in Directory, School 360 and Coverage; no editable toggle anywhere |
| 7 | Ownership transfer | School owner moved with 3 open activities, district unchanged, audited with previous/new; IA moved the Buikwe district portfolio after a preview |
| 8 | FY2027 planning | CD carried FY2026 rates forward (25 rates, provisional); an October 2026 visit saved as **FY2027 Q1**, priced against the FY2027 catalogue, and My Plan opened on FY2027 |
| 9 | Cluster meeting | Scheduled from Cluster A's own page; owned by the cluster's CCEO; catalogue item and six cost lines; visible in My Plan and the Calendar |
| 10 | Add school to project | The owning CCEO added their school to CCSEL; the coordinator's portfolio lists it and their To-Do says it has nothing planned; the school's owner, district and cluster are untouched |

## 3. What is governed, and by whom

* `CLUSTER_CATCHMENT_MANAGE` — Country Director approves a neighbouring
  district for a cluster. Nobody else, and never implicitly.
* `PLANNING_POLICY_MANAGE` — opens a fiscal year and sets the follow-up rule.
* `PARTNER_ORGANISATION_CREATE` / `_EDIT` — CD, IA, Admin.
* `PARTNER_USER_MANAGE` — CD and Admin only. This is the split that fixes §3.
* `SCHOOL_OWNERSHIP_TRANSFER`, `DISTRICT_PORTFOLIO_TRANSFER`,
  `OPEN_ACTIVITY_TRANSFER` — Admin and IA.

## 4. Deliberate limitations

* **The coverage tables hold 100 rows.** Deriving each school's visit and
  training state is not free, so the tables show the first hundred by name and
  say so in their headings; the counts above them are the true ones.
* **FY2027 rates are provisional.** They were carried forward from FY2026 and
  are labelled "Provisional: Carried forward from FY2026 v55". The CD replaces
  them with real FY2027 rates before delivery starts on 1 October 2026.
* **IA sees the coverage To-Do on `/todos`, not on its dashboard.** The IA home
  page is outcomes-first and carries no To-Do panel; that is a pre-existing
  design decision, not something this brief changed.
* **FY2026 and FY2027 policies were opened by migration**, so there is no
  `fy.planning_opened` audit row for them. A year opened through the page is
  audited and announced.
* **The derived visit status is not on the SSA-effectiveness analytics page.**
  It is shown in the School Directory, School 360, Planning, Team Oversight ·
  Schools & Coverage and the Project Coordinator's portfolio — all reading the
  same `apps.schools.school_status.visit_statuses`. The analytics page asks a
  different question ("are visits reaching the right schools with enough
  quality and frequency"), and the counting surface for visit status is the
  Coverage workspace.
* **Target reconciliation is flagged, never rewritten.** A transfer that
  affects an approved allocation lists it for the amendment workflow.
