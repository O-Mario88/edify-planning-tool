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
