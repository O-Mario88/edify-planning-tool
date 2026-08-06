# Platform search & filter contract

The rule every searchable page follows, and the record of which page searches
what. A control that is not in this table is either not a search or is a
defect.

## The rule

```
base      = scope_service.for_user(request.user)   # role + object scope
filtered  = filters.apply(base, request.GET)       # dropdowns
searched  = search.apply(filtered, request.GET["q"])  # free text
```

**Scope first, search second.** Search may only ever narrow a set the user
could already reach. It must never widen one and then hide the surplus in the
template — a record excluded by scope must never be fetched on behalf of a
query. This is asserted per role in `apps/frontend/test_search_contract.py`,
not assumed from the queryset a view happens to open with.

**The count describes the match set.** Never `page|length`, always
`paginator.count`. A number that moves with `per_page` is describing the
pagination, not the results.

**One persistent search per page.** A page-body search box that duplicates the
top bar means two ids, two submits, and two fields that disagree after a
back-navigation. Where a page's own search is its purpose, it keeps the body
control and sets `topbar_search.hide` instead.

**Local search is drawer-only.** A picker inside a drawer or modal searches an
enclosed dataset, disappears with the drawer, and is exempt from the above.

## Contracts

| Page | Route | Param | Searchable fields | Scope |
|---|---|---|---|---|
| School Directory | `/schools` | `q` | name, School ID, district, sub-county, assigned owner, cluster name, uploaded district/sub-county text | `school_queryset(scope)` |
| Planning | `/planning` | `q` | same field set as the directory | planning scope |
| Core Schools | `/core-schools` | `q` | name, School ID, district, sub-county, assigned owner | `_scoped_schools(user)`, `school_type="core"` |
| Special Projects | `/projects/planning` | `q` | school name/ID, project name, **project code**, district, sub-county, owner, partner | scoped assignments |
| IA verification queue | `/ia/verification/` | `q` | school name/ID, **Salesforce ID**, district, submitting owner | queue + role permission |
| Partner Monitor | `/partners` | `q` | partner name, region, **assigned school** name/ID/district | `resolve_partner_ids(user)` |
| Analytics | `/analytics` | `q` | school name/ID, cluster, responsible staff | `resolve_user_scope` |
| Budget workspaces | `/country-budget/` | `q` | line item, responsible staff | budget scope |
| Submitted budgets | `/country-budget/history` | `q` | month label, FY, status | `_require_read` |
| HR staff surfaces | `/hr/*` | `q` | user name, email, title, department, country | `_profile_scope()` |
| Messages | `/messages` | `q` | thread subject, participants | `can_access_context` |
| Global search | `/search` | `q` | schools, staff, activities | per-model scope |
| Help / glossary | `/help/search`, `/help/glossary` | `q` | article body, glossary term/definition | public to authenticated |

## Two traps this codebase sets

**`Activity.responsible_staff_id` is a dual id-space CharField.** It holds a
`StaffProfile` id on some rows and a `User` id on others. Resolving a staff
name through one space silently matches half the data and looks like it
worked. Resolve both and union the ids. Note it is not a relation at all —
`responsible_staff__user__name` raises `FieldError`, which is what made every
`?q=` on `/analytics` a 500 for as long as the page had no box to type into.

**`School.cluster_id` is a CharField, not a foreign key.** Cluster names
resolve through a subquery. This is also why the directory's search needs no
`distinct()`: every clause is a plain column or a forward FK, so nothing fans
the row out, and a `distinct()` would fight the `order_by("name")`.
