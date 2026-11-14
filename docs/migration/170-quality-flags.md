# 170. Quality Flags, read by Go

Owner, 2026-11-13: "I want django completely replaced by Go". Quality Flags
(`/quality-checks`, `extended_views.quality_checks_view`,
`apps.flags.services`, `pages/quality_checks/index.html`) is answered by
`platform/backend/internal/qualityflags`. Raising, acknowledging and resolving
a flag still post to the existing application, and the Resolve drawer is
still the existing application's.

| Part | Existing rule it ports |
|---|---|
| Who may open it | `require_page_permission("quality_checks")` and the feed's `can_open_url` (Admin, Country Director, Impact Assessment, Programme Lead), exported by `manage.py export_quality_flags_rules` (`apps/flags/test_quality_flags_rules_export.py`) |
| Whose flags | `flags_visible_to`: the Country Director's raised, the Programme Lead's assigned, Admin's every flag, nobody else's. Impact Assessment reads the flags raised by people whose People record is in its country (the service, any record), then again those of live records in its scope country (the view). A reader with no country reads all of them |
| The form | For the Country Director and Admin, "Raise a Flag": what a drill-down handed it (`scope_name` as "About: …" and its caption, `assign_to` selecting a Programme Lead it names, `category`, `note`, each stripped). The Programme Leads are `program_leads`: active and live, by name, and a Country Director's are bounded to their country |
| The register | The 50 most recent flags, newest first; its 50-row pager therefore never shows. Each row: `firstof` scope, category, "Flag"; the note (else "—") and " · " the recommendation; the raiser's name (else "—") · the day raised (`j M Y`, Nairobi); the assignee's account name (else "—"); the priority through `|title`; the due day as filed (else "—"); the status's label (an unknown one as filed); the resolution note (else "—"). Whitespace collapses as the feed reads it |
| Actions | For the Programme Lead and Admin, a last column. On the reader's own open flag (any flag for Admin) the feed reads only the menu's Resolve drawer (key "menu", not primary), not the Acknowledge form. An acknowledged flag gets the Resolve button (primary). A resolved flag, or another lead's, gets an empty cell |
| None | The empty state's one cell, "No quality flags raised", with no columns |

The count beside the card's title ("3 flags · the 50 most recent") is a span
the feed does not read, so neither answer carries it. A To-Do's `?resolve=`
link opens the drawer on load in the browser. As a page it is the same page,
because the loader `div` is hidden.

`deploy/db/roles.sql` grants `edify_gateway_ro` a flag's raiser, assignee,
scope name, category, note, recommendation, priority, due day, status,
resolution note and time, but not its scope's type and id.

Proof: `cmd/parity -screen page -path /quality-checks` for all 29 accounts
(the seed holds no flags: the form and the empty register).
`internal/qualityflags/testdata/golden.py` files 56 flags in the test database
(every status and an unknown one, each priority, missing names, an assignee
without an account, another raiser, more than 50).
`internal/integration/quality_flags_test.go` compares Go's answers whole
(`EDIFY_QUALITY_FLAGS_GOLDEN`, the same day).
