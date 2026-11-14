# 164. Leave Policies, read by Go

Owner, 2026-11-13: "I want django completely replaced by Go". HR Leave
Policies & Holiday Settings (`/leave/policies`) is answered by
`platform/backend/internal/leavepolicies`; its forms (a policy's entitlement,
approver and rules; adding and removing a public holiday) still post to the
existing application.

| Part | Existing rule it ports |
|---|---|
| Who may open it | `require_page_permission("leave_policies")` and the feed's `can_open_url` (Admin, HR, Impact Assessment), exported with each role's strip by `manage.py export_leave_policies_rules` (`apps/hr/test_leave_policies_rules_export.py` keeps the two in step) |
| No policy yet | The existing view writes the default policies on that first read; Go never writes on a read, so it passes such a reader on to the existing application, which then writes them |
| Policies | Every leave type's policy in the order the table holds them (the view reads them unordered): its label as a heading and "Key: <leave type>"; the feed reads none of the form's fields |
| Public holidays | "N added · M national in the next 12 months": N every recorded holiday, M the national calendar's public holidays from today to a year and a day ahead not recorded on the platform, at most 40 (`upcoming_public_holidays`, read through internal/calendarpage's holiday book, shared with the Calendar). Then each recorded holiday by day (its name and "Date: <N j, Y>", Django's en-us date) and each national one (its label, "(expected date)" for an Eid not yet announced, "Date: <l j F Y>", "National calendar"), and the empty "Add Public Holiday" card |

`deploy/db/roles.sql` grants `edify_gateway_ro` a policy's label and key
(recorded holidays were already granted to the Calendar).

Proof: `cmd/parity -screen page -path /leave/policies` for all 29 seed
accounts; `internal/leavepolicies/testdata/golden.py` records four holidays
(a declared day, Christmas, an announced Eid, a past day) in `edify_gorn_test`
and `internal/integration/leave_policies_test.go` compares Go's answers whole
(`EDIFY_LEAVE_POLICIES_GOLDEN`, written the same day).
