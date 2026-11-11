# 12. The School Directory, read by Go

Owner brief "Final backend responsibility and language boundaries"
(2026-11-11): "School Directory and School Profiles". Fifth piece of that
brief, after [sign-in](08-sign-in.md), [accounts and roles](09-accounts-and-roles.md),
[teams](10-teams.md) and [acting leadership](11-acting-leadership.md). This
piece moves the directory's read. School profiles and the directory's writes
(take, cluster, project, owner, add, upload) are the next pieces.

## 12.1 What moved

`SchoolDirectoryScreenService.GetSchoolDirectory`
(`platform/proto/edify/screens/v1/school_directory.proto`, unchanged) is now
answered by `platform/backend/internal/schooldirectory`, a port of the
existing page (the directory view, its scope, `data_gaps`, the visit status
and the SSA summary) reading the existing tables. Before, the gateway passed
it to the existing application's `/api/mobile/v1/school-directory`.

| Part of the page | Existing rule it ports |
|---|---|
| Who may open it | `RolePermissionService.can_view_page(…, "school_directory")`: Admin, Country Director, Impact Assessment, Regional Program Lead, Program Lead, CCEO, Project Coordinator. Opening a profile: `can_open_url(…, "/schools/0")` |
| Whose schools | an Admin, Country Director or Impact Assessment officer reads the country; an Impact Assessment assistant overseen by an IA officer, a CCEO or a Program Lead reads their portfolio (own schools, temporary cover, their team, schools in their own clusters); a Regional Program Lead their regions and regional reach; a Project Coordinator their projects' schools. The country is read from the staff profile, trimmed |
| Which schools | operating only (`active`, `reopened`), not deleted; a school with no place counts for the country |
| Search | `UPPER(…) LIKE UPPER(…)` over the name, School ID, district, sub-county, uploaded texts, owner's name and cluster name, with Django's escaping of `%`, `_` and `\` |
| Filters | fiscal year, district, sub-county (valid only inside the district), school type, cluster status, project status, the unheld option ("Nobody Holds It (n)") |
| Tabs and data gaps | the five tabs and the gap counts, the gaps counted before the gap filter is applied, as the page does |
| Each row | SSA average and band (the latest confirmed SSA of the year, the web's bands and tones), the urgent / performing-well / warning groups, visits and trainings counted, the visit status and its next date, training coverage, the cluster |
| Order | by name; a country or regional reader by owner (Program Lead, then officer), then name |
| Pages | 50 a page; a page past the end shows the last |
| Row Actions | one menu: take or complete, schedule (Impact Assessment), change cluster or add to cluster, reassign owner, add to project ("No active project available." when there is none) |
| Header | Add School for whoever may create or upload and is not a regional reader; transfer for whoever holds `school.ownershipTransfer`; read only for a Regional Program Lead |

The rules the page reads from the existing code (role groups, school and
training types, statuses, labels, tones, intervention groups, tabs, which
roles may open the page) are exported to
`internal/schooldirectory/rules.json` by
`manage.py export_school_directory_rules`.
`apps/schools/test_school_directory_rules_export.py` fails when the two
differ.

Numbers are worked out as Python works them: the SSA average is summed with
Python 3.13's compensated `sum()` and rounded with `round(x, 1)`, so a school
whose true average is 6.85 reads 6.8 on both.

## 12.2 Proving it is the same

`platform/backend/cmd/parity` signs real seed accounts in through the gateway
and asks Go and the existing application the same questions: every filter,
tab, gap and search in a matrix, then every page of each account's whole
list. Both answers are decoded into the same contract message and compared
field by field. Development only: it refuses any address not on this machine.

```bash
EDIFY_PARITY_PASSWORD=… go run ./cmd/parity -users cceo@edify.org,pl1@edify.org -pause 20s
```

| Run | Compared | Differing | Existing app failed, Go answered |
|---|---|---|---|
| 1 | 230 | 0 | 4 |
| 2 | 437 | 0 | 8 |

All 29 seed accounts that may open the page were covered.

## 12.3 Differences, each stricter or clearer

- **Each school once across the pages.** 700 seed schools share 52 names. The
  existing page orders by name only, so the database may return ties in a
  different order on each page: one officer's 700 schools list 14 schools
  twice and 14 never. Go orders ties by School ID. The parity tool compares a
  run of one name as a set, so this is the only difference it allows.
- **The project status filter works.** On the existing page, filtering by
  project status fails (`ProgrammingError: missing FROM-clause entry for
  table "school"`, from `data_gaps.counts` over a `.distinct()` list with an
  `Exists(OuterRef)`). Go answers it. This is a bug in the existing
  application, left as it is there.
- **Someone acting is served by the existing application.** The existing
  page applies the acting capacity (`ActingCapacityMiddleware`). Until the
  directory takes the acting seat over, a request made in an acting capacity
  is passed to the existing application as before.
- **`is_superuser` is not read.** The web treats a superuser like an Admin in
  places (taking and transferring schools). Go goes by the active role only.
  The seed has no superuser.

## 12.4 What still happens in the existing application

- Every write from the directory: take, complete, schedule, cluster, project,
  owner, add, upload. The app's native drawers still call the existing
  application, and the rest open the web.
- Export (Excel, CSV) opens the web.
- School profiles (`/schools/<id>`).

## 12.5 What the database role may do

`platform/deploy/db/roles.sql`, section `internal/schooldirectory`: the
read-only gateway role may SELECT the columns the page reads from `school`,
`region`, `district`, `sub_county`, `cluster`, `staff_profile`, `user`,
`staff_supervisor_assignment`, `temporary_coverage_assignment`,
`staff_geography_assignment`, `project`, `project_school_assignment`,
`project_staff_assignment`, `project_staff_capacity`, `ssa_record`,
`ssa_score`, `activity` and `cluster_activity_attendance`. Nothing else, and
no write. The package writes nothing (the source scan in `internal/dbguard`
allows it no table).
