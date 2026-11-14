# 171. Project Capacity, read by Go

Owner, 2026-11-13: "I want django completely replaced by Go". Project
Capacity (`/projects/capacity`,
`project_capacity_views.project_capacity_view`, `apps.projects.capacity`,
`pages/projects/capacity.html`) is answered by
`platform/backend/internal/projectcapacity`. Setting, editing and
withdrawing stay with the existing application, as do their drawers.

| Part | Existing rule it ports |
|---|---|
| Who may open it | `require_page_permission("project_capacity")` and the feed's `can_open_url` (Admin, Impact Assessment, Project Coordinator), with each role's workspace strip (the coordinator's Projects / Capacity), exported by `manage.py export_project_capacity_rules` (`apps/projects/test_project_capacity_rules_export.py`) |
| Which projects | `_directed_projects`: the live projects (exported statuses) in `scoped_projects` that `projects_directed_by` lets the reader change, by name. Admin reads every one. Impact Assessment with a country reads those reaching it through an enrolled school's region or a live People record running it, plus the unplaced. A coordinator reads those they manage or are actively assigned to |
| The tab | One project a tab when there is more than one; `?project=` stripped, else the first |
| Header | "+ Set Staff Capacity" opens the set drawer on the open project (the feed reads it as not primary), only with a project |
| The project | The rule note, then the card head: name and code as its title and its menu (Manage capacity, View schools, Project details) as links. The figures under the name are a definition list the feed does not read |
| A row | `allocations_by_project`, by name case-folded. The name is a link to `/staff/<id>` for a reader who may open staff profiles. Then the maximum; schools held on the project; remaining (at least 0, strong); utilisation (`round(…, 1)` through `floatformat:"-1"`). Visits Planned (FY of `get_operational_fy`): `staff_plan.visit_tallies` over both id spaces, against the role's 280 / 560 (Programme Lead before CCEO), and "N over" past it in the danger tone (`myplan.VisitTallies`, `myplan.VisitTarget`). Status is Full, Near capacity (at 0.8) or Available, or Blocked on a paused project. The menu's Edit capacity drawer |
| Pager | 50 a page under `staff_page-<project id>`, the shared pager |
| None | The empty state's message |

The app cannot open the staff table's second page. Its page key holds a
hyphen, which the feed's `QUERY_KEY` drops, so the app's pager leads back to
the first 50. This is logged as an owner defect and a go-fix
(`go-fix-capacity-pager`).

`deploy/db/roles.sql` grants `edify_gateway_ro` an allocation's id. The rest
was already granted.

Proof: `cmd/parity -screen page -path /projects/capacity` for all 29 accounts
(the seed holds no allocations).
`internal/projectcapacity/testdata/golden.py` files four projects (active with
55 allocations, paused, scaling with none, closed), 53 staff in every planning
role and none (one People record deleted), enrolments for full, near and
available, and counted visits. A lead is 3 past 280, one visit is under the
account id, and work that must not count is included.
`internal/integration/project_capacity_test.go` compares Go's answers whole
(`EDIFY_PROJECT_CAPACITY_GOLDEN`, the same day).
