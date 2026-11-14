# 60 — Page header actions (Export, Plan Field Event, Recent changes …)

The buttons in a page's header band now reach the app and the web, from the
Django feed and from Go alike. Before this, the feed's reader
(`apps/mobile_feed/page_blocks.py` `_header`) read only the
`edify-page-header__controls` slot, and in it only `<button>`s and links with
the `btn` class, so:

- Planning offered nothing: its Export, Plan Field Event and Recent changes
  sit in a plain row beside the lead, outside the controls slot;
- every link drawn as an action button (`a.edify-action-button`) was skipped:
  Clusters' Export, Cluster Oversight's Download CSV and Scoring, Core School
  Oversight's Download CSV, Staff Activity's Export, Team Performance's Set
  Country Targets;
- Planning Oversight's trainings view draws its ceiling doors in the page
  header's `aside` slot, also outside controls;
- the page's one primary button (`edify-action-button primary`) was read as
  plain: Create Cluster, Follow-up Queue, the ceiling doors.

## The contract (additive)

`PageAction.download = 8` (bool): the button downloads a file (an export)
instead of opening a page. The web marks the link `download`
(`platform/web/src/components/blocks/PageHeader.tsx`); the app can hand it to
the system. Generated code regenerated for Go, web and
`platform/mobile/src/gen` (generated files only).

## The reader (Django feed)

| Rule | Where |
|---|---|
| The header band (`.edify-page-header`) is read, not only its controls slot; nothing inside `__lead` is an action | `_header` |
| In the controls slot every `<button>` is an action (as before), and any `a`/`button` with `btn` or `edify-action-button`; beside it only what carries `edify-action-button` (so Escalations' "Swipe for more →" stays out) | `_is_header_action`, `HEADER_BUTTON_CLASSES` |
| Badges are still read from the controls slot only | `_header` |
| Primary: `edify-primary-solid`, or `edify-action-button` with `primary` | `_header_action` |
| Download: a link with the `download` attribute, or whose query names a key the feed never passes (`views.NOT_PASSED`: export, format, csv, xlsx, pdf, download), or whose path ends in `/export` | `_downloads` |
| Href: a link written as a query alone (`{% querystring %}`) is resolved on the page's path; every header href's parameters are put in name order without blank ones (no `?` left when none remain), so the answer does not depend on the order the page was asked in (Go's `url.Values` has none) and matches the gateway, which passes no blank parameter on | `_resolved`; `read(html, later, path)` |

`page_body` passes the page's path to `read`.

## Go

`internal/pageheader` (new): `Key` (the feed's `_slug`), `Drawer`, `Link`,
`Download`, `Href` (name order, no blanks) and `QueryHref` (a
`{% querystring k=v %}` link: the page's own query less the feed's held-back
keys, with k set). Each page package decides which buttons a reader gets:

| Page | Buttons | Gate (exported, never restated) |
|---|---|---|
| `/planning` (planningpage) | Export (download, page query + `export=csv`), Plan Field Event (drawer `/work-plan/add`), Recent changes (drawer) | `doors.field_event` = `has_permission(MANUAL_ACTIVITY_CREATE)` (the view's `can_add_non_school_activity`); `not_passed_query_keys` |
| `/clusters` (clusterpage) | Create Cluster now primary; Export (download) last | existing doors; `not_passed_query_keys` |
| `/cluster-oversight/` (clusteroversight) | Download CSV (`/cluster-oversight/<section>` with fy, area, view, format=csv; not for `reports`), Scoring (link) | `doors.export` = `can_export`, `doors.scoring` = `can_view_page("cluster_scoring")`; `impact_views` |
| `/core-schools-oversight/` (coreoversight) | Download CSV (query less tab/page/format), Download Excel on a plan tab (+ tab, format=xlsx) | `doors.export` = `can_export` |
| `/staff-activity` (staffactivity) | Export (download, `/staff-activity/export` with the query less page/staff_page) first; Follow-up Queue now primary | existing `rules.query.not_passed` |
| `/team-performance/` (teamperformance) | Set Country Targets (link, `?fy=`) | existing `set_targets` (`country_targets.may_set`) |
| `/team-planning-oversight/?view=trainings` (trainingsummary) | + Set Training Capacity, + Set Country Ceiling (primary drawers, `?fy=`) | existing `maySet` / `maySetCountry` |

Rules exports extended (drift tests unchanged, files re-exported):
`export_planning_page_rules` (field_event, not_passed_query_keys),
`export_cluster_page_rules` (not_passed_query_keys),
`export_cluster_oversight_rules` (export, scoring, impact_views),
`export_core_oversight_rules` (export). The Cluster and Core Oversight golden
files (`testdata/golden.json.gz`) were regenerated with their own
`golden.py`, since the existing pages now carry the header buttons.

## What comparing found

A feed dump of every Go-served page for all 29 accounts before and after the
reader change (`$SP/agent35_ripple.py`, 870 pages) moved exactly the
expected headers: Planning (28 accounts, 3 buttons), Clusters (27, Export
added and Create Cluster primary), Cluster Oversight (7), Core School
Oversight (7), Staff Activity (2), Team Performance (2), the trainings view
(6). Calendar, My Plan and Work Plan gained only `download: false` (the proto
default). Nothing outside the headers moved (one Staff Activity count changed
between the two dumps: live activity data, not the reader).

## Parity

All 29 seed accounts, a Go-only gateway (127.0.0.1:8085) against the
existing application (127.0.0.1:8185) over edify_gorn_dev, `-pause 20s`, the
pages' own question sets plus `cmd/parity/page_with_header_actions.go`
(export/csv keys the feed holds back, a blank `q`, an escaped search,
several parameters together). Last lines as printed:

| Path | Last line |
|---|---|
| /planning | 1605 answers compared, 0 differing |
| /clusters | 1044 answers compared, 0 differing |
| /cluster-oversight/ | 928 answers compared, 0 differing |
| /core-schools-oversight/ | 3654 answers compared, 27 differing |
| /staff-activity | 1574 answers compared, 22 differing |
| /team-performance/ | 3494 answers compared, 0 differing |
| /team-planning-oversight/ | 696 answers compared, 0 differing |

No difference is in a header. The 27 on Core School Oversight (one per
account) and 4 of the 22 on Staff Activity (pl1–pl4, the redirect to the
dashboard) are the new blank-`q` question: the parity tool sends `q=` to the
existing feed directly, which keeps it in the strip links
(`?q=&tab=attention`) and the redirect (`?sa=q%3D`), while the gateway drops
blank parameters before any page sees them (`screens.pageQuery`), so in
service the existing page never receives one either. The other 18 on Staff
Activity are the known pass-ons (admin 9, cd 9: weeks with partner
hand-overs, staff-activity-2), unchanged from doc 41.

A question with `format=` was dropped from the set: the existing feed is a
REST framework view, which reads `?format=` as its renderer switch and
answers 404 for `format=xlsx` (admin's /planning differed only there, the
run was stopped and restarted without it). Any page asked with `format=`
through the existing feed is refused this way; worth knowing for the
pass-on.

## Left

- Pages Go does not answer on this branch now get their band's buttons from
  the feed too. Planning Oversight's Team Plan lens (`/team-planning-oversight/`,
  no view) now offers Export, a drawer
  (`/team-planning-oversight/export-drawer?fy=…&month=…&owner=team&period=fy&quarter=…&week=…`,
  pl1; `program_lead=…` for cd). The planning-oversight branches (47) must
  emit it when they merge after this one, or their parity moves.
- The web renders header buttons only on the School Directory page on this
  branch; the Planning and other web pages (agents 23/26) pick up `download`
  when merged.
- The app (platform/mobile) does not yet act on `download`.
