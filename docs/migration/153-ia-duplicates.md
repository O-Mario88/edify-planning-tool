# 153. Duplicate Review, read by Go

Owner, 2026-11-13: "I want django completely replaced by Go". Duplicate
Review (`/ia/duplicates/`, `ia_views.ia_duplicates_view`,
`pages/ia/duplicate_review.html`) is answered by
`platform/backend/internal/iapages`, the first of the Impact Assessment review
pages; its decisions (ignore, return to plan, flag for investigation) still
post to the existing application.

| Part | Existing rule it ports |
|---|---|
| Who may open it | `require_page_permission("ia_duplicates")` and the feed's `can_open_url` (Impact Assessment and Admin), exported by `manage.py export_ia_pages_rules` (`apps/activities/test_ia_pages_rules_export.py`) |
| Whose flags | `_ia_reach_q`: the activity is in the reader's country when the scope is country-bound (`activity_country_q`, the Go port the school profile already uses) and, for a reader without the IA verification permission (exported: Impact Assessment holds it), only work an Impact Assessment officer of that country is responsible for — so Admin, holding no verification permission, sees none of the seed's flags. Only potential flags on live activities |
| A flag | The reason; "Flagged <Mon dd, yyyy>" in Nairobi time; each side's first eight characters of its id, type's label, school (else "Cluster-wide"), planned day, owner (`_staff_names`: a live People record's account name, a legacy account id's name, else the id, else "Unassigned") and Salesforce ID (else "Unlinked"); the "Compare Evidence side-by-side" link to `/ia/compare/?activity_id=…`. The badge, buttons and decision forms are not read by the feed |
| Order | None: the flags table has no order and the view sets none, so both read the table as it holds them |
| None | The empty state's message |

`deploy/db/roles.sql` grants `edify_gateway_ro` a flag's activities, status,
reason and time.

Proof: `cmd/parity -screen page -path /ia/duplicates/` for all 29 accounts;
`internal/iapages/testdata/golden.py` flags pairs of the test database's own
activities and `internal/integration/ia_pages_test.go` compares Go's answers
whole (`EDIFY_IA_PAGES_GOLDEN`, the same day).

## 153.2 Returned Activities

`ia_returned_view` (`pages/ia/returned_activities.html`), in the same package:
the live activities in the same IA reach whose status is "returned by IA", the
last changed first, 50 a page (`page`, the shared table pager). Each row: "#"
and the id's first eight characters with the type's label; the School ID (the
`{% school_code %}` token the response middleware fills in, which the feed's
render never runs, so the app reads it empty — "—" without a school); the
school's name as a link to its profile for a reader who may open one (else
"Cluster"); the owner (`_staff_names`, as Duplicate Review); the reasons the
verification gave, joined ("None Specified"); the day and time returned
(`M d, Y H:i`, Nairobi); "Awaiting CCEO" as a badge; and an "Inspect" link to
`/ia/verification/<id>/`. Nothing returned: the empty state's message. The
export button and its download stay with the existing application (the feed
never passes an export key). `deploy/db/roles.sql` grants which activity a
verification belongs to and the reasons it gave.

Proof: `cmd/parity -screen page -path /ia/returned/` for all 29 accounts; the
same golden returns 55 of the test database's activities (each put back as it
was) and compares both pages, two pages of the table and a page that is not a
number.

Found: the School ID column reads empty in the app for every school
(`school_code` writes a token only the browser's middleware fills in);
OWNER_DEFECTS.

## 153.3 Verification History

`ia_history_view` (`pages/ia/verification_history.html`): every verification
of a live activity in the same IA reach, the latest first, 50 a page. Each
row: "#" and the id's first eight characters with the type's label; the
School ID (empty, as Returned Activities); the school's name ("Cluster-wide"
without a school) followed by its cluster's; the partner as a badge ("—"
without one); the owner; who verified it (an account's name, else the id as
stored); the time (`M d, Y H:i`, Nairobi); "Certified" as a badge or
"Excluded"; and the Actions menu ("Workspace" and "View audit timeline", read
by the feed under the key "menu"). Nothing verified: the empty state's
message. `deploy/db/roles.sql` grants a verification's activity, verifier,
time and whether it counts in analytics (not its notes).
