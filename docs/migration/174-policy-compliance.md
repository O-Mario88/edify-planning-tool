# 174. Policy and Manual Compliance, read by Go

Owner, 2026-11-13: "I want django completely replaced by Go". Policy and
Manual Compliance (`/policy-compliance`, `apps.documents.views.compliance_view`,
`apps.documents.compliance.PolicyComplianceService`,
`pages/documents/compliance.html`) is answered by
`platform/backend/internal/policycompliance`. Answering a policy comment stays
with the existing application.

| Part | Existing rule it ports |
|---|---|
| Who may open it | `require_page_permission("policy_compliance")` and the feed's `can_open_url`, with each role's workspace strip (the Programme Lead's Performance & Coaching), whether it reads comments (`policies.review_comments`) and its `_scope_note`, exported by `manage.py export_policy_compliance_rules` (`apps/documents/test_policy_compliance_rules_export.py`). A role the page opens that `_scope_user_ids` has no scope for (Impact Assessment) is refused with a 403, as the feed's API answers its `Forbidden` |
| Whose answers | `_scope_user_ids`. Admin and the RVP read everyone. Human Resources reads its people reach (`scope_profiles` over live People records, `hrregister.PeopleReachProfiles`). A Country Director reads the live People records of their own record's country, and none without one. A Programme Lead reads their supervisees (acting appointments are passed on by the screens service) |
| Rows | Acknowledgements of readable documents (published, effective), filtered by `document`, `state` and `role` as sent, newest first, the first 1,000, 50 a page (`rows_page`, the shared pager). Each row: the person's name (else their id); the role at acknowledgement (else "—"); the policy; "v" and the version number; first opened (`d M`, Nairobi); active reading time "of" required (`_humanise`); the viewer completion (`reading_completion_key`), read as a badge; the state's label. With none, the empty line in one cell |
| Figures | Accepted and Overdue (pending past their due day), from the registry's labels, as counts with thousands separators and their drill-down links. Required, Pending, the 1,000-row note when the table is cut, and Declined, counted over the whole scope |
| Filters | Policy (readable documents needing acknowledgement, by title) and Status, each reading as the option selected, so an unknown value selects none |
| Comments | For a reader of comments, the queue's card ("No comments awaiting review.") |

A reader whose comment queue holds comments is passed on to the existing
application. That is any comment not archived; for a Country Director, only
those whose author has no country, because the queue filters on the
account's absent `country`, an owner defect. Go does not read the private
text yet (BACKLOG `policy-compliance-comments`).

`deploy/db/roles.sql` grants `edify_gateway_ro` an acknowledgement's reading
time, attestation, due day, role and time; a policy's required reading; and a
comment's status and author's country, never its text.

Proof: `cmd/parity -screen page -path /policy-compliance` for all 29 accounts
over dev's 78 acknowledgements. `internal/policycompliance/testdata/golden.py`
files three policies (one timing its readers, one not, one draft left out)
and 95 acknowledgements in every state: full, partial, none and offline
reading, overdue, and blank roles. `internal/integration/policy_compliance_test.go`
compares Go's answers whole (`EDIFY_POLICY_COMPLIANCE_GOLDEN`, the same day).
