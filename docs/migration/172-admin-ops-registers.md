# 172. Platform-operations registers, read by Go

Owner, 2026-11-13: "I want django completely replaced by Go". The Admin's
Support Tickets (`/admin-ops/support`), System Incidents
(`/admin-ops/incidents`) and Maintenance Calendar (`/admin-ops/maintenance`)
(`apps.admin_ops.views`, `pages/admin_ops/`) are answered by
`platform/backend/internal/adminops`. Triage, resolving, acknowledging, the
incident's own page and the work they generate stay with the existing
application.

| Part | Existing rule it ports |
|---|---|
| Who may open them | Each page's permission, the feed's `can_open_url`, and the views' `_admin_only` (the role in use is Admin), exported by `manage.py export_admin_ops_rules` (`apps/admin_ops/test_admin_ops_rules_export.py`) |
| Support Tickets | The "Support attention" figures: awaiting triage (submitted) and open (every status but closed, resolved, invalid, cancelled and duplicate), each helper as the note (`brief_helper`). Then the 200 newest tickets, filtered by `?status=` as sent. The feed reads the queue's card as its one resolve form when exactly one ticket is in Verification or Fix Ready and the card shows no more than 400 characters around it (`page_forms._form_of`, counted in characters as `Node.text` collapses them). That form's line is the card's first paragraph, the newest ticket's title. Otherwise the card is a list: each ticket's title, its reporter's role (else "user") · page (else "unknown page") · time (`d M H:i`, Nairobi), and its status as a plain badge, with none of the forms |
| System Incidents | The 200 last seen first, filtered by `?status=` as sent. Each one's title, `firstof` route and component · "last seen" time, its severity (critical "alert", high "caution", others "plain") and its status as badges, and a link to its page. The reference, count and reopened marks are not pills and are not read |
| Maintenance Calendar | Every template by next due day: its name, category · frequency · estimate, and "Next" day. The open maintenance work (preventive or corrective, not done, the 50 newest): reference · title, and status with the scheduled day. Each card's empty line where there is none |
| None | Each register's empty state, read as one item |

The lone-form reading of Support Tickets hides the queue from the app. It is
logged as an owner defect and a go-fix (`go-fix-support-queue`).

`deploy/db/roles.sql` grants `edify_gateway_ro` only what the registers draw:
a ticket's reference, title, category, status, the reporter's role, page and
time, never its description, reporter or browser; an incident's title,
severity, status, route, component and when it was last seen, never its
samples or detail; and the maintenance schedule and work.

Proof: `cmd/parity -screen page` on each path for all 29 accounts (dev holds
incidents; no tickets or open maintenance work).
`internal/adminops/testdata/golden.py` files tickets in every kind of status,
including the lone form, two forms, and one past the card's limit. It also
files incidents of every severity and an unknown one, and maintenance of both
kinds. `internal/integration/admin_ops_test.go` compares Go's answers whole
(`EDIFY_ADMIN_OPS_GOLDEN`, the same day).
