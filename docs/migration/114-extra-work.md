# 114. Extra Assigned Work, read by Go

Owner, 2026-11-13: "I want django completely replaced by Go". Extra Assigned
Work (`/extra-work`) is one of the app's native pages (the feed's
`NATIVE_PAGES`, url name `extra_work`) that Go did not answer yet.

| Piece | What moves | State |
|---|---|---|
| 1 | The page (`/extra-work`): the reader's assignments and their performance lane, reviews, what the reader handed out, the team's CD work | This document |
| — | Its saves: Assign (drawer), Start, Submit Result (drawer), Verify, Return, Cancel | Still the existing application's |

## 114.1 What moved

`PageScreenService.GetPage` is answered by `platform/backend/internal/extrawork`
for the path `/extra-work`. Go builds the blocks the existing feed reads from
`apps.frontend.views.extra_work_views.extra_work_page`,
`apps.hr.extra_work.performance_summary` and `pages/hr/extra_work.html`.

| Part | Existing rule it ports |
|---|---|
| Who may open it | `require_page_permission("extra_work")` and the feed's `can_open_url`: the CD, Programme Leads, CCEOs, Admin and Impact Assessment. Anyone else is not found, as the feed answers |
| The year | `fy` with its surrounding space stripped, else the operational FY (read in UTC, as `get_operational_fy` reads it). Any other text is a year with nothing in it |
| Assign Extra Work | The header's one button, for the CD and Programme Leads (`extra_work.ASSIGNER_ROLES`), opening `/extra-work/assign-drawer?fy=<year>` |
| The strip | The Programme Lead's Team Assignments strip (Actions Sent, Extra Work) |
| The policy line | When the reader has verified work in the year and the year's scoring policy is not approved |
| Assigned to me | The reader's assignments of the year by due day (at most 100): the line of counts (open, awaiting review, verified, the verified work's points when they are not nothing, "point" for exactly one, overdue, and "showing the 25 soonest of N" past 25), then a table of 50 a page (`extra_work_mine_page`, the shared pager): the task (title, the instruction cut to 140, and for returned work "Returned:" with the reason cut to 110), who assigned it, the due day, the status (with "· Overdue" for open work due before today, Kampala's day) in its tone, and the next step's words (Start; Submit Result; "+N pts" for verified work with points; else a dash) |
| Awaiting my review | Submitted work the reader reviews, by submission (at most 50): the title and the day it was submitted, the outcome cut to 220, the evidence note cut to 160, and the words "Evidence link" when there is one (the feed reads only the words: the address is not shown) |
| Assigned by me | What the reader handed out, by due day (at most 100): the title, the assignee's role and the due day, the status in its tone |
| On my team | The CD's assignments on a Programme Lead's team, by due day (at most 50): the title and the status in its tone |
| Nothing | "No extra work this year" when all four are empty |

The doors, the strip, who may assign, the status labels, the open statuses,
the section limits (read from the view's own slices), the cut lengths and the
"25 soonest" count (read from the template), the page parameter and size and
the query keys the feed drops are exported to `internal/extrawork/rules.json`
by `manage.py export_extra_work_rules`;
`apps/hr/test_extra_work_rules_export.py` fails when the two differ.

## 114.2 Database access

`deploy/db/roles.sql` grants `edify_gateway_ro` the columns the page shows of
`hr_extra_assignment` and the year and status of
`hr_extra_work_scoring_policy`. The evidence link's address is read only to
know that there is one. Applied to `edify_gorn_dev` and `edify_gorn_test`;
production needs the owner's approval at cutover, like every other grant.

## 114.3 Proof

- `cmd/parity -screen page -path /extra-work` for all 29 seed accounts on the
  development copy (the seed holds no assignments, so this proves the doors,
  the button, the strip and the empty page).
- `internal/extrawork/testdata/golden.py` files 72 assignments and two scoring
  policies in `edify_gorn_test` (every status, overdue and not, long words,
  enough for one officer to page, another year), asks the existing feed 16
  questions as six accounts and deletes the rows;
  `internal/integration/extra_work_test.go` files the same rows and compares
  Go's answers whole (`EDIFY_EXTRA_WORK_GOLDEN`).

## 114.4 Defects found, left as the existing application has them

- The line says "showing the 25 soonest of N" whenever more than 25 are
  listed, but the table pages through all of them (50 a page) and the list is
  cut at 100, so the words are wrong both ways. A Go fix waits for the
  intended-differences list (OWNER_DEFECTS).
- The evidence link is whatever the submitter typed, unchecked; on the web it
  is an `href`, so a `javascript:` address would run in the reviewer's
  session. Go never shows the address (OWNER_DEFECTS: the existing
  application should accept only `http(s)` links).
