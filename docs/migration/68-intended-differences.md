# 68. Intended differences: Go fixes the existing application's defects

Owner, 2026-11-13: "Can you fix those from the go side" (the defects the
migration's comparisons found in the existing application). Go does the
correct thing instead of copying a defect. A corrected answer no longer
matches the existing one, so the comparison tools would report it; this
piece lets them accept exactly those differences and nothing else.

## 68.1 The list

`platform/backend/internal/parity/intended.json`, embedded in the tools. Each
entry names:

| Field | What |
|---|---|
| `id` | the name printed beside an accepted difference |
| `tool` | `page`, `profile`, `navigation`, `directory`, `notifications` or `shadow` |
| `where` | the page path (as the tool prints it) or the save scenario (`-scenario`) |
| `questions` | the questions it shows on, each exactly: a page's query as printed (`(as it opens)` for none), or a shadow table |
| `fields` | the field paths (`.blocks[1].filters[0].options[1].selected`, `error` for a refused or failed side) or shadow columns, each exactly |
| `existing`, `go` | patterns the two values must each match whole |
| `defect` | what is wrong in the existing application |
| `decision` | the owner's decision, quoted and dated |
| `test` | the unit test proving Go's corrected behaviour, `<package dir>.<TestName>` |

`parity.Load` refuses an entry with a field missing, an unknown tool, the same
two patterns, a pattern that does not compile, an unknown key, or an id listed
twice. `TestTheCheckedInListLoadsAndEveryEntryHasItsTest` fails when an
entry's test does not exist.

## 68.2 How the tools use it

- `cmd/parity -screen page`: a difference is accepted only when its tool,
  path, question and field are listed and both values match their patterns
  whole. The answer is printed `INTENDED` with the entry's id; every other
  difference in the same answer still prints `DIFFERS` and fails the run. The
  summary adds `N answers held only intended differences`.
- `cmd/shadow -scenario <name>`: a row only one copy holds is paired with a
  row only the other holds when they differ only in listed columns; such a
  table prints `same but as intended`. Unpaired rows still differ. Without
  `-scenario` no entry applies.
- Not wired yet: `-screen profile`, `navigation`, `directory` and
  `cmd/notificationparity` (they print and fail as before). Wire each when the
  first fix needs it.

## 68.3 Adding a fix

1. Write the unit test of the corrected behaviour first, then the fix.
2. Add the entry, as narrow as the difference: the exact questions and
   fields, patterns that match only the defect and the correction.
3. Run the comparison; the difference prints `INTENDED`, nothing else moves.

Proved by `internal/parity` (exact match, near misses on question, field,
page, tool, direction and partial pattern, shadow row pairing, refused
entries, every entry's test exists) and
`cmd/parity.TestComparePagesSetsAsideOnlyAListedDifference`.

## 68.4 Additions (coordinator, 2026-11-13)

- `"questions": ["*"]` matches every question on the entry's page; the field
  and both values must still match exactly (first used by the period-select
  fixes, where the difference shows wherever the page opens on a non-week
  period).
- `"relation": "deduplicated"` instead of the two patterns: Go's value (a JSON
  list) must be the existing list with its repeats removed, first-seen order,
  and the existing list must hold a repeat. First used by
  go-fix-notification-categories.
- `cmd/notificationparity` compares the filters field by field and accepts a
  listed one. Run for admin@ on edify_gorn_dev: `32 compared, 12 differing`,
  32 answers with the category list accepted as intended; the 12 differing are
  one live incident's "seen 182×/183×" counter changing between the two reads
  (the same as agent 33's run), not the fix.

## 68.5 Additions (2026-11-14)

- `"relation": "reordered"` on a list field (`.blocks[3].table.rows`): Go's
  list must hold exactly the existing items, each as often, in another order.
  `cmd/parity` compares such a field whole before walking its items; when the
  entry accepts it the existing list stands in for Go's, so the items compare
  as usual and any other difference in them still fails. First used by
  `go-allocations-plan-order` (owner, 2026-11-14: "Yes, plan order"): the
  existing Priorities page leaves its distributed priorities in whatever
  order the database planner returns; Go lists them in the plan's order.

## 68.6 A difference no answer shows: the country Budget writes nothing (2026-11-14)

Owner, 2026-11-14, asked whether the country Budget should stay with the
existing application because its read writes: "Go reads it anyway".

The existing page (`budget_view` → `get_country_monthly_budget`) creates the
month's `monthly_work_plan_budget` row when there is none
(`_get_or_create_budget`) and, while the month is not locked, writes its live
totals back on every read (`_recompute_if_live`, `_apply_live_envelope`).
`internal/budgetpage` (country.go) writes neither. It shows what that read
would leave behind: a month with no row is a Draft, and a live month's
request and operating requirement are its planned lines' cost
(`_program_source`'s program total); a locked month shows its stored totals.

So the answers are the same (golden: a live, a locked, an approved and an
unrecorded month, 28 answers of 9 accounts, 0 differing) and no `intended.json`
entry is needed; what differs is the database after the read:

- A month first opened through Go has no row until the existing application
  makes one: its Budget page (the read Go replaces there), the plan sources
  drawer (`get_plan_sources`) and a Program Lead request's approval
  (`approve_pl_monthly_request`) call `_get_or_create_budget`. The month's
  actions (`send_to_rvp`, `approve`, `return_budget`,
  `set_envelope_allocation`, `add_admin_line`) take the row's id, which the
  web page has from its own read; the app does not show those forms (the
  feed reads none of them), so Go's page never needs the id.
- A live month's stored totals are as fresh as its last read through Django.
  Three readers show them without recomputing: the RVP approvals drawer's
  returned months (`rvp_views`, `returned_by_rvp` is live), System Health's
  annual reconciliation (the sum of every month's `program_total`), and the
  monthly budget list (`monthly_work_plan.services.list_budgets`). Locked
  months, which the approval itself reads, are never recomputed by either.

## 68.7 Not a difference: pages whose read writes, and Go writes the same (2026-11-16)

"Go never writes on a read" has these exceptions, each the owner's decision,
because the existing page writes when it is opened and its readers depend on
what that write leaves:

- The Help Centre (owner, 2026-11-16: "Go makes the same writes"): the home
  marks published guides past their review date as review due
  (`mark_review_due_articles`), and on a database with no page-to-guide links
  fills them (`sync_route_contexts`). Not built in Go yet: the app's feed does
  not offer the Help pages.
- My Targets and My Professional Development (owner, 2026-11-16: "Same
  writes"): My Targets rebuilds the reader's achievement ledger
  (`TargetAchievementService.rebuild`), My Professional Development syncs the
  reader's course tracking (`PDCourseTrackingService.sync_all`), each before
  the page reads.

Each such page writes through its own role with exactly the columns the
existing write touches, behind its own switch (off by default, development
and shadow databases only), and is proved by the rows the existing read
leaves behind as well as by the page it answers.
