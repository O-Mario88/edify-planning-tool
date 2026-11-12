# 19. Escalations, read by Go

Owner brief "Final backend responsibility and language boundaries"
(2026-11-11): Go as the application backend. Escalations is the upward
decision channel: a CCEO or Project Coordinator raises to their Programme
Lead, a Programme Lead to the Country Director, the Country Director to the
RVP, and the addressee decides (`apps.flags.escalation_service`).

| Piece | What moves | State |
|---|---|---|
| 1 | The Escalations page (`/escalations`) as it opens: the raise form, the four lists, each escalation's opened detail, and their pages | This document |
| — | Raising, acknowledging and deciding (the page's POST, `raise_escalation`, `acknowledge`, `resolve`) and their notifications | Still the existing application's |

## 19.1 What moved

`PageScreenService.GetPage` is answered by
`platform/backend/internal/escalations` for the path `/escalations`, for
someone working in their own role. Go builds the blocks the existing feed
reads from `templates/pages/escalations/index.html` and `_table.html`.

| Part | Existing rule it ports |
|---|---|
| Who may open it | `require_page_permission("escalations")` and the feed's `can_open_url`: CCEO, Project Coordinator, Program Lead, Country Director, RVP, Admin and Impact Assessment (who opens what Admin opens, raises nothing and decides nothing, so the page holds no blocks). Anyone else is not found |
| The header | "Leadership", "Escalations", and the line by what the reader may do (`can_decide`, `can_raise`, the RVP's own words; "routed to your None" for a reader who may do neither, as the template writes it). The figures beside it are the header's own and the feed does not read them |
| Whose escalations | `visible_to`: what the reader raised; what is addressed to them (named to them at the level they decide for, or addressed to that level with no one named, inside their country below the RVP: `_addressed_to_me_q`); for the Country Director, the country's Programme Lead items and what the country sent to the RVP; everything for Admin. The newest first |
| Who decides | `_decidable_ids`: Admin every one; otherwise those addressed to the reader that they did not raise |
| The raise form | For a raiser (`addressee_for`): "Escalate to {supervisor}, your {level}" when `resolve_addressee` names one (the first supervisor link, by id, whose account holds the level's role), else "Escalate to the {level}"; the line for that level, and "No supervisor is on file…" below the RVP when no one is named; Category (the drill-down's category when it is one, else the first), Severity (Normal), Subject and What is happening (the drill-down's, stripped), Decision you are asking for, Needed by; "Send to {level}"; saved by the app (`canSave`) |
| The lists | Awaiting your decision (a decider; open and decidable), Raised by you (a raiser; everything they raised), Received by your Programme Leads (open, not decidable, not theirs) and Recently decided (closed, not theirs, the first 20); the first two with their empty states |
| A row | Severity in capitals and the status as pills (the decision once resolved, "None" for one that is not a decision; Overdue once open longer than its severity's wait, `SLA_DAYS`; Acknowledged; Open), subject, category's words (the stored value when not one), raiser or a dash (not on Raised by you), the level's words, the age in whole days (`age_days`) and the day it is needed by |
| Opened | The detail row, read as one panel: what is happening, what is asked for, who raised it and when, and for a resolved one the level's decision, its words, the reasoning ("None" when none is recorded) and the day. A line followed by a figure ("5", "—") is read as one data row, as the feed pairs them. The decide forms beside them are not read |
| Pages | Fifty rows a list, all four sharing one parameter (`escalation_rows_page`), each list's pager read as a panel under its table (16.1) |

Each role's door, the level it raises to and decides for, who decides
everything and who reads the country's board, the levels with their words
and roles, the categories, decisions and severities, each severity's wait,
the statuses, the page size and the query keys the feed drops are exported
to `internal/escalations/rules.json` by `manage.py export_escalations_rules`;
`apps/flags/test_escalations_rules_export.py` fails when the two differ. The
page's sentences live in the template and are written in Go. The page reader's
pairing of a label and a figure is shared with the school profile
(`schoolprofile.PairedItems`, `export_escalations.go`).

## 19.2 Proving it is the same

`cmd/parity -screen page -path /escalations` asks the Go-only gateway and
the existing feed the same 19 questions as each account: the page as it
opens; the shared page 2, "abc" and -1; a drill-down's subject with markup
and padding, a detail on two lines, every category, one in capitals, one
padded, a scope name alone, a key the page does not read, and a whole
drill-down together.

All 29 seed accounts against a gateway with no existing application behind
it. The run's last lines:

    pl4@edify.org                      19 questions, 0 differing
    coordinator@edify.org              19 questions, 0 differing

    551 answers compared, 0 differing

Nineteen answers for each account; the Business Transformation Officer is
turned away by both.

The development database holds no escalations, so that run proves the gate,
the header for every role, the raise form for every raiser (a named
supervisor for the seeded officers, none for the coordinator and the leads)
with every prefill, and the empty states. Two things cover the rest.

**The existing feed's answers over 136 escalations, compared in the test
database.** `agent3_escalation_golden.py` (kept in the session scratchpad)
points the existing application at the local test database, files 136
escalations there (`gpe…`: thirteen routes, officer to named and unnamed
Programme Leads, in and out of the country, the coordinator, leads to the
Country Director named and not, the Country Director and Admin to the RVP in
two countries, Impact Assessment, a lead to themself; every status and
decision and one that is not a decision; four severities and one unknown;
every category and one unknown; details that are a figure, a dash, spaced,
with markup and on two lines; reasonings missing and a figure; names
missing and empty; due days around today; and 56 more role-addressed
Programme Lead items so the lists page), asks the feed seven questions as
each of 34 accounts, writes the rows and the answers to a file and deletes
the rows. Each row was filed at least three hours from a whole day of age,
so the ages hold for an hour. `TestEscalationsMatchTheExistingFeedOverManyEscalations`
(`internal/integration/escalations_test.go`) files the same rows, asks Go
the same questions and compares each answer as a whole message; it is
skipped unless `EDIFY_ESCALATIONS_GOLDEN` names that file, and when the file
is more than an hour old. It printed:

    escalations_test.go:148: 238 answers of 34 accounts compared, 0 differing

That run reaches every list for every reader, the pagers (Admin's 76
awaiting, the Country Director's 60 received, a lead's 51), the page
clamped for a short list, Overdue by severity, the country rules of the
inbox and the Country Director's board, the RVP reading every country, a
named supervisor and none, and the paired lines.

**Unit tests** (`internal/escalations/page_test.go`) hold the exported doors,
the header for each kind of reader, the inbox's named, role and country
rules, the status pill's order, an unknown severity's wait, the raise form's
title, line and prefill, the paired lines of an opened row and the shared
page parameter.

## 19.3 What is left

- A raise card whose title and line run past 400 characters (a supervisor
  name of a hundred characters or more) is read by the feed as a section
  holding a form rather than as the form (`page_forms.INTRO_LIMIT`); Go
  always writes the form. No account comes near it.
- Escalations raised at the same instant have no order between them.
- Raising, acknowledging and deciding stay the existing application's.
