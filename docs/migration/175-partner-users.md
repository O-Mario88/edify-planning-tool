# 175. The Partner Admin's Users page, read by Go

Owner, 2026-11-13: "I want django completely replaced by Go". Users
(`/partner/users`, `partner_views.partner_users_view`, `_team_roster`,
`pages/partner/users.html`, `partials/partners/team_table.html`) is answered
by `platform/backend/internal/partnerusers`. It is built on the gateway's own
partner team service (`internal/teams`, which already ports
`apps.partners.member_logins` and `school_team` for the app's Team screen).
Adding, removing and changing members stay with their drawers and forms.

| Part | Existing rule it ports |
|---|---|
| Who may open it | `require_page_permission("partner_users")` and the feed's `can_open_url` (Admin, Impact Assessment, Partner Admin, Partner Field Officer), exported by `manage.py export_partner_users_rules` (`apps/partners/test_partner_users_rules_export.py`) |
| Whose team | The reader's own organisation (`resolve_partner_ids`, `teams` `ownPartner`), when they lead it (`leads_team`). Otherwise, with no organisation or one they don't lead, `render_access_denied` sends a page load to `/dashboard`, and so does Go |
| Header | "Add member" opens the member drawer for whoever manages the roster |
| The card | "Team members" and the "N on the roster" line. With nobody, that line is the panel's subtitle and the empty state's message its one item |
| A row | Live members, by role then name. Name and title run together as the feed reads them; the role's label; phone and email run together, linked to the email (else "—"); the login (email · Active / Invited / Deactivated, a deleted account none, else "No login"); and how many of the organisation's held schools the member looks after. The Actions menu is read as its two drawer buttons (Assign schools; Reset password or Set up login), not its forms (activate or deactivate the login, Remove) |
| Pager | 50 a page under `roster_page`, the shared pager |

No grant is new: the team service already reads these tables.

Proof: `cmd/parity -screen page -path /partner/users` with `EW_USERS` naming
the partner accounts (the default 29 hold none) and the staff accounts the
page refuses or redirects. `internal/partnerusers/testdata/golden.py` files 56
members (staff and volunteers, logins in every state including a deleted
one, a member who left, schools held and one not held).
`internal/integration/partner_users_test.go` compares Go's answers whole
(`EDIFY_PARTNER_USERS_GOLDEN`, the same day).
