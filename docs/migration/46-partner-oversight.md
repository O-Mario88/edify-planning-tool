# 46. Partner Monitoring, read by Go (first piece: a workspace with no partner work)

Partner Monitoring (`/partner-oversight/`, `apps.frontend.views.oversight_views.partner_oversight_view`,
`apps.planning.partner_oversight_service`, `pages/oversight/partner_oversight.html` with
`partials/oversight/partner_workspace.html`) is one Partner at a time: the schools, clusters and
activities handed to it, by team member, where each stands, the headline tiles, withdrawal requests and,
for the Programme Lead, the Country Director and the operational admins, the partnership register.

The page is large: its rows come from a 2,400-line service (handovers, Partner work made without one,
facilitated group trainings, risks, invoices, Core support), its first tile carries the Partner target
from the Planning Monitor (`apps.planning.planning_monitor`, not yet in Go), and the register reads
engagements and Regional Lead observations. This piece moves the part every seed reader without partner
work sees, exactly, and passes everyone else to the existing application. The rest is backlog item
`partner-oversight-2`.

Go: `platform/backend/internal/partneroversight/` (rules.go, period.go, read.go, service.go, page.go,
page_test.go), one line in `internal/server/server.go`, parity questions in
`cmd/parity/page_partner_oversight.go`, integration tests in `internal/integration/partner_oversight_test.go`.

## 46.1 Who Go answers

| Reader | Go's answer |
|---|---|
| A role without `PARTNER_MONITORING_VIEW` (Business Transformation, Project Coordinator, HR, partners, MFI, Cluster Leader) | not found (`pagegate.ErrNotAvailable`), the feed's 404 |
| CCEO or Programme Lead in their own role, nothing in reach (below) | the page, built by Go |
| CCEO or Programme Lead with anything in reach | passed on (served=false) |
| Country lens (CD, IA, Admin, Accountant, RVP), region lens (RPL), anyone acting | passed on |
| A link with an Export-drawer period (`period_type`, `from_month`, `to_month`, `start_date`, `end_date`), a register drawer to open on load (`engagement`, `step`, `record`, `source`), a register page (`engagement_page`), a year that is not four digits, a week not written `YYYY-Wnn` (01–52), or any non-ASCII text | passed on |

"In reach" is one statement (`read.go anyPartnerWork`), each arm at least as wide as the page's own
source, so when it finds nothing the page has nothing. The ids are the reader and the people they
supervise, in both id spaces (`_both_id_spaces`; a CCEO's supervisees are added too, as the Planning
Monitor counts them):

| Page source | Go's wider condition |
|---|---|
| `build_items` handovers (`_assignment_team_q`, `left_partner_q`, `_still_open` / `_assignment_fy`) | a `partner_assignment` monitored, assigned, at a school held or a cluster run by the ids, not left the Partner, and unscheduled (any date) or scheduled into a year read |
| `_unassigned_partner_activities` | a live partner-delivered `activity` with a Partner, in a year read, monitored/responsible/at a held school/at a run cluster |
| `facilitated_trainings` | a live `activity` with a facilitating Partner, in a year read, responsible or at a run cluster |
| `withdrawal_requests` | a `requested` withdrawal whose supervising PL is in the ids |
| the Partner target (`planning_monitor` → `_monitored_schools`) | a live school held by the ids or in the reader's scope |
| the register (`engagements_visible_to`, `open_observation_follow_ups`), register readers only | an engagement the reader authored, or any strengthen/replace Regional Lead observation |

The years read are the page's FY, and every later year when it is the operational FY
(`planning_horizon` reads it forward to the latest offered or plannable year; Go reads every later year).
No period, status, member or type narrows the guard.

## 46.2 The page Go draws

- Header: eyebrow, title and description; Add Partner Organisation (drawer `/partners/create`) where
  `may_create_partner_organisation` (exported; none of the served roles has it).
- Filters (`period_filter_bar.html` + `partner_filter_fields.html`): the period select has no selected
  option (Alpine sets it), so the feed reads its first, `week`, whatever the period; FY reads the option
  equal to the page year, else the first; Month and Quarter read the defaulted month and quarter; Status
  lists the exported phases with `(0)` and reads the one asked for exactly (no strip), else All. Hidden:
  `member`, `work`, and `program_lead` when given (the view keeps the raw value for a team reader).
- `_period_filters` as `period.go`: year default `get_operational_fy()` (UTC); the reference day is
  Kampala's today when its FY is the page year, else 1 October before it; the week, month and quarter
  default from it; an explicit `period` wins, else month, quarter, then FY.
- Team-member tabs: All team members, then `program_lead_members(team_lead_user_id)` — the first live
  profile of the reader's account holding Program Lead, by key, then their reporting lines by name — each
  with count 0; `member` not on the strip reads All. Hrefs as the template writes them.
- Work tab: `work_tabs` with no tables — the one asked for (not Core), else Schools assigned.
- Tiles: `_partner_kpis` over no work, as `professional_kpis` splits them, exported as rendered
  (`zero_tiles`, `zero_tiles_with_target`). The target sentence is there when the reader leads a team in
  the planning roster (`country_oversight.rules.roster`: live profile, active account, planning role
  Programme Lead): the monitor then has people and, with no school, every total is 0. A CCEO has none.
- The empty state (`components/empty_state.html`, the feed reads its message).
- Register readers (here the Programme Lead): its title; its tiles (`ENGAGEMENT_METRIC_WORDS`, lifted, the
  observations tile for the Programme Lead) through `schoolprofile.Strip`; the empty table with the
  recorder's or the reader's words.

## 46.3 Rules exported, not restated

`manage.py export_partner_oversight_rules` writes `internal/partneroversight/rules.json`; drift test
`apps/planning/test_partner_oversight_rules_export.py`. Per role, by the page's own gates: page,
lens, own work only, Add Partner Organisation, register, records engagements, observations tile. Also:
Status phases, work tabs and the Core tab, planning and roster lead roles, partner delivery, the
requested withdrawal state, the left-the-Partner statuses and `returned_to_staff`, the partner-action
recommendations, the register's words, autoload and page params, the rendered zero tiles, the feed's
unpassed query keys.

Behaviour-neutral lifts to module constants: `oversight_views.PARTNER_STATUS_FILTER_KEYS`,
`partner_engagement_views.ENGAGEMENT_METRIC_WORDS`, `support_responsibility.LEFT_PARTNER_STATUSES`.

Grants (appended to `platform/deploy/db/roles.sql`): `activity.facilitating_partner_id`,
`partner_assignment_withdrawal (state, supervising_pl_id)`, `partner_engagement.author_id`,
`cce_regional_engagement.recommendation`. Ids, states and one word; no reasons, notes or text.

## 46.4 What was found by comparing

- The seed's field officers are not empty: cceo1 (Moses K. on pl2's team) holds five completed FY 2026
  handovers. A first guard with no year passed every officer on; the guard now reads the page's years, so
  the officers are Go's for FY 2027 and later and passed on for FY 2026 (where the existing page lists
  that work), and so is pl2's team.
- `fy=abc` is a 500 on the existing page (`get_fy_date_range`); Go passes it on rather than copy a crash.

## 46.5 Proving it is the same

`cmd/parity/page_partner_oversight.go` asks each account 36 questions (42 where the strip names team
members): the page as it opens, every period, FY (2025, 2026, 2028, 1999, `abc`, padded), month (3, 13,
`abc`), quarter (Q3, `q2`, Q9), week (`2026-W02`, `2026-W2`, nonsense), status (two phases, `xyz`), work
tab (visits, clusters, core, bogus), member (all, nobody, each on the strip), `program_lead`, `partner`,
`period_type=fy`, `engagement_page=2` and two combinations. Own Django on 8182 over `edify_gorn_dev`.

Go-only gateway (no existing application behind it), all 29 accounts, `-pause 20s`:

```
coordinator@edify.org              36 questions, 0 differing

1062 answers compared, 356 differing
```

Every one of the 356 is a reader or question Go passes on (`go error: unavailable: This screen is not
available here yet`); none is a Go answer that differs. Go's own answers: cceo1–cceo19 28 of 36 each,
pl2–pl4 34 of 42 each (634 answers), plus the 72 refusals of Business Transformation and the Project
Coordinator, all equal. Passed on: cceo, pl1, cd, ia, admin (all questions; partner work in reach or a
country lens), and for the served accounts `fy=2026` and the FY 2026 month question (cceo1's FY 2026 work,
on pl2's team), `fy=abc`, `fy= 2026 ` (Python strips it; Go reads it too but FY 2026 is passed on),
`week=2026-W2`, `week=nonsense`, `period_type=fy`, `engagement_page=2`.

The same gateway with my Django behind it, all 29 accounts:

```
coordinator@edify.org              36 questions, 0 differing

1087 answers compared, 27 differing
```

All 27 are `fy=abc`, one per account that opens the page: the existing page answers 500 and the gateway,
passing it on, words the same failure as "This screen could not be loaded" while the tool prints
"status 500" — the existing application's crash in both columns, not a Go answer.

Unit tests (`page_test.go`): `_period_filters` over 16 queries including the Kampala/UTC day edge
(30 September 22:30 UTC), quarters, work tabs, queries passed on, who is drawn (acting, country and
region lenses refused), status words, and the page for a Lead, an officer, a reader who adds partners and
a register reader. Integration (`partner_oversight_test.go`, on `edify_gorn_a20_test`): cceo1's page,
pl2's page in FY 2028 with team tabs, target and register, and passing on cceo1 in FY 2026, a custom
period and pl1, refusing Business Transformation.

## 46.6 What is left (`partner-oversight-2`)

Everything with rows: handover items (`_item_for`, risks, next actions, costs, withdrawal actions,
Core support, invoices), Partner tabs with follow-up (`partners_needing_follow_up`), the partner header
and its summary chips, work tabs with counts, `workspace_tables` and the facilitated trainings table,
non-zero tiles, the Partner target from the Planning Monitor, the withdrawal queue, the country and region
lenses with Programme Lead tabs, acting readers, register rows, observations and counts, custom periods,
the export drawer, and the other partner pages the backlog item names (Partners list, allowance drawer).
A superuser in a team role reads the country on the web; Go cannot read `is_superuser` (it is protected)
and would draw them as a team reader — there is none in the seed.

## 46.7 Partner work on the team lens (2026-11-18)

Go now draws the page for a field officer or a Programme Lead whose
workspace holds partner work (`internal/partneroversight`).

**The rows** are `partner_oversight_service.build_items` for the team lens:

- **Which work:** every hand-over the team may oversee that is still the
  Partner's (not `left_partner_q`). The team is the reader and, for a lead,
  the people they supervise, in both id spaces. The years read are the
  planning horizon, with a hand-over still open read whichever year it was
  made. Partner-delivered activities that no hand-over points at are read
  too.
- **What each row carries:** the staff directory (the officer, and the
  Country Programme Lead they report to); the activity's day, status,
  evidence, Salesforce, IA and payment; its cost; and the three words of
  `describe_work` (training, purpose, SSA intervention).
- **What follows from them:** the withdrawal its state permits
  (`withdrawal_service.resolve_kind` and `action_label`, with
  `dating_policy`), its risks (`partner_risk_service`), and the completion
  columns (`completion_columns`, a Partner's forms read through
  `gateway_read.activity_evidence_kind`).
- **Narrowing:** the period's month, quarter or week narrows the rows.

**The page** is drawn as the feed reads `partner_workspace.html`:

- **Partner tabs:** each tab's count carries the Country Director
  Analytics' follow-up recommendation, `partners_needing_follow_up`,
  ported (the SSA cycles, each Partner's planned and done work, and its
  schools' SSA movement).
- **Team-member tabs and the Status filter:** the tabs come with their
  counts, and the Status filter counts each phase.
- **Headline tiles:** these come from the rows shown, and the first carries
  the Planning Monitor's Partner target for a Programme Lead. The target is
  read through `planningmonitor.PartnerTargetReader`, which the server
  supplies to this package because the monitor already imports it.
- **The chosen Partner's card:** one table titled with the Partner's name,
  its status chips as the subtitle. The open tab's table holds the Schools
  assigned columns or the activity columns, with each row's link, cells,
  Actions and details. The footnote says when the year reads forward, and
  the response carries the Withdraw selected bar.

`rules.json` gains the vocabularies all of this reads (`work`), and each
role's profile links and Resolve permission. `roles.sql` grants the gateway
three more columns: `partner_assignment.resolution` and
`return_reason_category`, and `activity_catalogue_item.source_name`.

**Still handed on:**

- the country and region lenses;
- work waiting for IA verification, since its reviewer's Verify and Return
  depend on the reader;
- Special Project work, which is its coordinator's;
- a hand-back already decided;
- the Core schools and Clusters tabs;
- group trainings a Partner facilitates;
- withdrawal requests;
- an activity filter;
- a table past one page;
- recorded engagements;
- custom periods.

Proof: `internal/partneroversight/testdata/golden.py`. Over the seed's
completed FY 2026 work and a fixture Partner in this year, the golden files
work in every state the page tells apart:

- waiting for a date, inside and past its grace;
- dated by the Partner ahead;
- dated by staff and passed;
- in progress;
- evidence uploaded;
- an undecided hand-back;
- verified and awaiting payment;
- a Partner training with no hand-over.

It asks cceo1, cceo2, pl1 and pl2 with every Partner, team-member and work
tab, every status and every kind of period. The integration test files the
same rows: **192 answers, 0 differing**. That is after the one recorded
intended difference, `go-fix-period-select-partner`, where Go's period
select shows the period in use. `internal/partneroversight/item_test.go`
covers each state's words, withdrawals and risks.

## 46.8 The country's lens (2026-11-18)

Go now draws the page for the readers it reads through the whole country:
the Country Director, Admin, Impact Assessment, the Accountant and the RVP
(`partner_oversight_service._resolve_scope` "country"). For them:

- **The work** is every Partner's: the hand-overs and Partner activities
  of the country, with no team filter.
- **The Programme Lead strip** is `_program_lead_tabs` over
  `system_program_leads`. There is a tab for every staff member holding the
  Programme Lead role, with the work their teams hold, and Unassigned for
  work no lead supervises. The first tab opens when none is asked for.
  The Partner and team-member tabs, the tiles and the card then read that
  lead's team, and the team-member tabs are the lead's roster.
- **The follow-ups** are read in the reader's scope's country.
- **The Partner target** comes from the reader's own Planning Monitor:
  `ReadCountry` for the country's readers, `ReadRegion` for a region's,
  `Read` for a Programme Lead. A monitor this application does not draw
  hands the page on.
- **The header's Add Partner Organisation** is the primary action, as in
  the existing page; the empty page now marks it too.

A country whose roles come from the registry is not drawn through this lens
yet. The register with engagements in it is still handed on: any engagement
recorded, or any Regional Lead observation asking for one.

Proof: the golden of §46.7 now also asks cd, admin, ia, accountant and rvp,
with every Programme Lead tab and the Partner, team-member, work, status
and period questions under them: **487 answers of 9 accounts, 0
differing**.

Still handed on: the region's lens (the Regional Programme Lead), and the
list in §46.7.

## 46.9 A region's lens (2026-11-18)

The Regional Programme Lead is now drawn as well. They read the Partner
work of their regions (`_resolve_scope` "region"):

- **The rows:** a hand-over, Partner activity, withdrawal request or
  facilitated training whose school or cluster lies in the reader's
  regions.
- **The tabs:** a tab only for a Programme Lead whose team holds that work,
  then Unassigned.
- **The target:** the region's Planning Monitor (`ReadRegion`).

Go's regions for a regional role are every country's (docs/migration/80
§15), which on Uganda's data are the regions the existing scope gives.

The gateway may now read `partner_assignment_withdrawal.school_id` and
`assignment_id` (`roles.sql`), to place a request in a region.

Proof: the golden now also asks regional-lead: **544 answers of 10
accounts, 0 differing**.

## 46.10 The Core schools tab (2026-11-18)

A Partner holding a Core school gets the Core schools tab, and Go now draws
its table (`partner_core_row.html`). The columns are School ID, School
Name, Staff Name, Core support, Purpose of Assignment, Planned date,
Completed date, Cost, Salesforce ID, Evidence, Status and Actions.

- **Core support** is the package slot its activity fills (`V2`, `T1`,
  from `core_activity_slot`).
- **Cost** is the scheduled work's price. Before the work is priced it is
  the Partner's rate from the operational card, `core_partner_visit` or a
  training's `client_partner_visit` (`pricing.OperationalRate`). It reads
  "Rate not set" when the card sets none, and "—" for work taken back.
- **The Actions menu** is View, plus:
  - Withdraw school, for a role that may withdraw partner work
    (`withdraws_partner_work` in `rules.json`), while the Partner has not
    dated the work;
  - Resolve Exception, on a hand-back the reader decides.
- **The details** are Assigned, Training, SSA Intervention, Partner officer,
  District, Execution, IA, Payment and Returned.
- **Selection:** the tick boxes and the Withdraw selected bar appear as on
  Schools assigned.

**Still handed on:**

- a Core school the Partner has not dated, whose slot is the one its
  hand-over holds (`slot_held_by_assignment`);
- work whose form is in but is not complete, whose Confirm completed work
  depends on who may confirm it.

Proof: the golden now asks the Core tab of every reader, over the seed's
nine completed Core hand-overs and a fixture Core school a staff member
dated. That gives 13 Core tables with Withdraw school offered where the
role may: **564 answers of 10 accounts, 0 differing**.

## 46.11 The Clusters tab (2026-11-18)

The Clusters to facilitate tab holds two tables, so the feed reads the
Partner's card part by part, and Go now draws it that way:

- **The card's head:** a panel with the Partner's name as its title. The
  subtitle is the follow-up line ("Needs follow-up: Capacity Review · its
  schools' SSA rose, but its work is below target"), and the status chips
  are its links.
- **The work tabs**, each with its count. Core schools appears only for a
  Partner holding one.
- **Cluster work assigned and Cluster sessions:** each is a section heading
  with its count, then its table. A hand-over names its cluster with the
  cluster's profile link.
- **The note on the years read**, as a panel of its own.

A Partner with a contact person or phone is still handed on there, since
the head would name them, as are group trainings a Partner facilitates.

Proof: the golden now asks the Clusters tab of every reader, over a fixture
cluster hand-over and a cluster meeting the Partner dated with no
hand-over. That gives 28 cluster sections: **584 answers of 10 accounts, 0
differing**.

## 46.12 Trainings a Partner facilitates (2026-11-18)

Group trainings and cluster meetings that a Partner facilitates are the
officer's own work, and the page reads them under that Partner
(`facilitated_trainings`, `FacilitatedTraining`). Go now reads them for the
same team, region or country as the rest of the page, over the years read.
The period does not narrow them, as in the existing page.

**Where they count:**

- the Programme Lead tabs, through their supervising lead, and a region's
  visible leads;
- the Partner tabs;
- the team-member tabs, through the officer;
- the Clusters to facilitate tab.

The team-member and Status filters narrow them as they narrow the Partner's
own work.

**On the Clusters tab** they follow the note on the years read, as
"Trainings and meetings facilitated (N)" and its table:

| Column | What it shows |
|---|---|
| Cluster Name | The training's cluster, or the school for an in-school training |
| District | That place's district |
| Training Name | The course, else its name, else its type |
| SSA Intervention | The intervention it targets |
| Training Date | Its date |
| Salesforce ID | The officer's Salesforce ID |
| Status | Upcoming, Overdue, Completed, Verified, Returned, or what a done status lacks |
| Cost | The facilitation fee from its cost lines |
| Action | "With Impact Assessment" while IA verifies it, else View activity as a plain link |

Overdue rows carry the overdue tone.

**Still handed on:** a training waiting for its Programme Lead's review,
whose Confirm and Return depend on who reads.

The work rows' lone View activity link is now read the same way as the
trainings', as the cell's text and link. The feed reads the record-action
mark on its wrapper, not on the cell.

The hand-overs are read in their model's order (newest first), as are the
Partner activities. Rows sorted alike then tie the same way.

Proof: four fixture trainings (upcoming, overdue, with IA, verified), each
with its facilitation fee: **584 answers of 10 accounts, 0 differing**.

## 46.13 Verify & Confirm and Return (2026-11-18)

Work waiting for IA verification is no longer handed on. Its reviewer's
Actions menu offers Verify & Confirm and Return
(`_partner_review_items.html`), for the readers
`RolePermissionService.can_confirm_partner_activity` names:

- Impact Assessment (`verifies_ia` in `rules.json`, the matrix's
  `ia.verify`), unless it is their own work;
- the Country Director, for work an Impact Assessment officer ran;
- the activity's monitor, in a field role (CCEO, Programme Lead, Project
  Coordinator).

SSA Support (`is_partner_ssa_support_activity`) is verified in its own
drawer, `/activities/<id>/partner-ssa-complete`. The items follow View and
any withdrawal on a hand-over's row, and View activity on a Partner
activity's. A Core school's row offers Return.

Proof: two fixture visits waiting for IA verification, one SSA Support,
monitored by cceo1. cceo1 is offered the review as their monitor and ia as
verifier: **584 answers of 10 accounts, 0 differing**.

## 46.14 The activity filter and decided hand-backs (2026-11-18)

**The activity filter.** An `activity_type` a link carries is no longer
handed on. It narrows the Partner's work and the trainings it facilitates
as `filter_workspace` and `filter_trainings` do. The Status filter's counts
are taken from what remains, and, as in the existing page, the filter bar
carries no hidden field for it.

**A decided hand-back.** A hand-back whose decision is recorded but not yet
made final reads Returned, with the decision under it ("Decision: Staff
will deliver the support", `get_resolution_display`, `resolution_labels` in
`rules.json`). Its row offers View.

Proof: the golden adds a decided hand-back and asks two activity filters of
every reader: **624 answers of 10 accounts, 0 differing**.

## 46.15 Special Project work (2026-11-18)

Special Project work is no longer handed on. It is its Project
Coordinator's to withdraw or reassign (`projects.authority`), and a
Coordinator does not read this page. So, as in `_lock_project_work`, only
the Admin and Impact Assessment (the Admin's operational reach) direct it
here.

For every other reader the work is locked:

- no withdrawal is drawn, and no Withdraw school or Resolve Exception;
- its details read "Special Project: <name> — withdrawals and reassignments
  are its Project Coordinator's".

For the Admin and Impact Assessment the details name the project alone.

Work of a project no SSA intervention measures, and naming no intervention,
reads "general" as its target intervention (`intervention_or_general`,
through `visitgate.ProjectsOutsideSSA`).

Proof: a project hand-over waiting on the Partner and dated project work.
It is locked for every reader but admin and ia: **624 answers of 10
accounts, 0 differing**.

## 46.16 A facilitated training's review (2026-11-18)

A training a Partner facilitates is no longer handed on while it waits for
the officer's Programme Lead (`submitted_to_pl`). Its Action is the review
menu for the readers `pl_review.services.review_rule` lets decide it:

- the Admin;
- a lead, for the work of the staff they supervise, in both id spaces,
  active cover included;
- a lead's own staff work, while the lead role is both held and in use.

The work belongs to its officer, else its monitor. The menu offers Confirm
Verification once the training is complete, then Return, and View activity.
Anyone else reads the plain View activity link.

The supervised staff now travel with the workspace for every lens.

Proof: two fixture trainings waiting for review, one complete and one whose
Salesforce ID is not in, each offered to pl2: **624 answers of 10
accounts, 0 differing**.

## 46.17 The withdrawal queue (2026-11-18)

Withdrawal requests are no longer handed on. A request is one a CCEO raised
about work a Partner has already scheduled
(`partner_oversight_service.withdrawal_requests`). Go draws the queue after
the tiles. It opens with a heading panel, "Withdrawal requests (N)", and its
one line, then a panel for each request. Each panel says:

- the school and the Partner;
- the kind and the reason, plus whose it is when it is not the Partner's;
- the explanation the Partner sees;
- the internal note, when there is one;
- the proposed next step, with the planned cost and "Committed money" when
  the money was locked at withdrawal.

A reader the role rules do not let decide requests (`reviews_withdrawals`)
also reads "Awaiting the supervising Programme Lead's decision."

Which requests a reader sees depends on the lens:

- a team's lens shows the requests addressed to its leads;
- a region's lens shows those whose school, or whose hand-over's cluster,
  is in the region;
- the country's lens shows them all.

Requests come oldest first, at most a hundred. The labels for the reason,
whose it is and the next step are exported from the model's choices into
`rules.json`.

The gateway reads only the columns the queue needs (`roles.sql`).

Proof: one requested withdrawal of a dated hand-over, addressed to pl2:
461 of the **624 answers of 10 accounts** show it, **0 differing**.
