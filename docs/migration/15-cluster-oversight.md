# 15. Districts and clusters (M2): Cluster Oversight, read by Go

Owner brief "Final backend responsibility and language boundaries"
(2026-11-11): "District and Cluster management". After the Clusters page
(14-districts-and-clusters.md), this is the page beside it: Cluster
Oversight, as the app opens it.

| Piece | What moves | State |
|---|---|---|
| 1 | Cluster Oversight as it opens (`/cluster-oversight/`): the Command Center, its sections strip, year filter, table and pages | This document |
| — | A section's own address (`/cluster-oversight/<section>`), the scoring page | The app's feed does not open them (15.1); nothing to move until it does |
| — | The CSV downloads, and the weights' save | Still the existing application's |

## 15.1 What the app's feed opens

`apps.mobile_feed.views.NATIVE_PAGES` names `cluster_oversight`, the URL
`/cluster-oversight/`, and not `cluster_oversight_section`. So of the page's
eighteen sections the feed opens one: the page itself, on its Command Center.
Every other address under it is answered "This page is not available" (404)
for every account: `/cluster-oversight/ssa` and the other sections, although
the page's own strip links to them; `/cluster-oversight/scoring`; and
`/cluster-oversight` without its slash, which resolves to nothing. The
redirects (`/cluster-management/…`, `/cluster-oversight/export`) are not
named either, so the feed never answers `{"redirect": …}` for this page.

The page is refused (`cluster_oversight` in `PAGE_ACCESS`) to every role but
CCEO, Program Lead, Impact Assessment, Country Director, Regional Vice
President, Regional Program Lead, Accountant and Admin.

Go answers the same: the page at `/cluster-oversight/`, and "not found" for
every other address under it. Whether the feed opens sections is exported
with the rules (`feed_opens_sections`); the day it does, the drift test
fails, and until Go builds the sections they pass to the existing
application rather than being refused.

## 15.2 What moved

`PageScreenService.GetPage` is answered by
`platform/backend/internal/clusteroversight` for `/cluster-oversight/`, for
someone working in their own role. Anyone in an acting capacity is passed to
the existing application as before.

| Part | Existing rule it ports |
|---|---|
| Who may open it | `require_page_permission("cluster_oversight")` and the feed's `can_open_url` |
| Whose clusters | `cluster_queryset(scope)` without `direct_only`, over every cluster not deleted (any status): a country reader's country; every cluster for a summary reader; otherwise those filed under the reader's or their supervisees' user or staff profile id (`cluster_owner_ids`), those of the whole scope's schools, a lead's team's included, and the ownerless ones in those schools' districts. `schooldirectory.ScopeGeography` derives the whole scope's clusters and districts as `_derive_from_schools` does |
| The year | `fy`, one of `fy_options()` newest first; anything else is the operational year |
| The sections strip | `workspace.SECTIONS`, each a link in the year shown; the Clusters door for a reader `/clusters` lets in; My Clusters only for someone who holds some of the clusters shown and not all |
| A cluster's line | `workspace._command`: district, officer (`_staff_directory`, `_label`), leader, schools (`member_schools`: operating), attendance and schools absent three or more sessions in a row (`profile_insights._attendance_of`: the register and the older list on the activity, a delivered session nobody was ticked at counted against no school), the last delivered meeting or training, the average SSA and least performing intervention (`_ssa_now`, `school_current_scores`), SSA change (`ssa_movement_by_cluster`: `improvement_rows`, then `change_rules.classify_pairs` and `school_verdicts` under the published rules), enrolment growth and learning change (`outcomes`), schools holding a loan (`_funded_schools`), approved stories, Cluster Health and Cluster Impact with their bands (`scores.scorecards` under `current_settings`), and maturity |
| A figure's link | The cluster profile at the tab that explains it, for a reader `/clusters/0` lets in; the loans count only for a reader of the loans page |
| The table's heading | "n clusters · n schools · n% attendance · n schools absent 3+ sessions" |
| Pages | Fifty rows (`TABLE_PAGE_SIZE`), `rows_page` read as `{% paginate %}` reads it and clamped, `make_pagination_window(window_size=1)`, each link keeping the rest of the query (`pager_query`) |

Each role's doors, the sections, the Command Center's columns, note and
empty state, the statuses and activity types each figure counts, the SSA
interventions, the change rule's constants, each score's parts and default
weights, the bands and the maturity levels and defaults are exported to
`internal/clusteroversight/rules.json` by
`manage.py export_cluster_oversight_rules`;
`apps/clusters/test_cluster_oversight_rules_export.py` fails when the two
differ. The Command Center's title, columns, note and empty state were
written inside `workspace._command`; they are now module constants there
(`COMMAND_TITLE`, `COMMAND_COLUMNS`, `COMMAND_NOTE`, `COMMAND_EMPTY`) so the
export reads them. Nothing the page draws changed.

Every statement is issued in the shape and order the existing page issues
it (14.1's lesson): a school's learning score is its class results added in
the order they are read, and a school's run of missed sessions depends on
the order of two sessions held the same day.

## 15.3 Proving it is the same

**Against the existing feed, every seed account.** `cmd/parity -screen page
-path /cluster-oversight/` asks the Go-only gateway and the existing feed 25
questions each: the page as it opens; years 2028, 2027, 2026, 2025, 1999,
" 2026 " and "abc"; `rows_page` 1, 2, 999, 0, -1, "abc" and " 2 "; the SSA
area and Impact view the other sections read; two parameters the page does
not have; a year with a page, with an area and view, and with a download's
keys.

All 29 seed accounts: `725 answers compared, 0 differing`, on the first full
run. The three other kinds of address were then asked as they open, 29
accounts each (15.5 gives the lines).

**Against the existing code, for records the seed does not hold.** The
seed's 22 clusters are one officer's; none has a school compared on SSA,
enrolment or learning, no change rule is published, no weights are stored,
one cluster has a Health score, every cluster with schools is "1 · Forming",
and the table is one page. So most of the Command Center cannot be reached
by asking the two applications.

`internal/clusteroversight/testdata/golden.py` reaches it without writing a
record. It makes sets of records from a seeded random source (registers and
older attendance lists, sessions with no date, schools drifting away, SSA
pairs under published rules and under the fallback, readings 119, 120 and
121 days apart, a country's own rule, enrolment from nothing, weighted class
results, a school with two loans, stories filed against a cluster and
against a school, stored weights given as text and as nonsense, 120 and 380
clusters) and has the existing application's own code make the page of
them: `workspace`, `scores`, `profile_insights`, `outcomes`, `change_rules`,
`year_comparison`, the view, the template and the feed's reader, unmodified,
with only the statements stood in for. `page_golden_test.go` gives Go the
same records and expects the same page: 17 pages, among them a Regional Vice
President's and an Accountant's (roles the seed has no account for), all
five maturity levels, every band, and tables of three and eight pages. They
were equal on the first run; changing a rule in Go (the interval, the
planning share, the learner weighting, the order of a school's sessions)
fails between 4 and 16 of them.

What the golden pages do not pin is in `page_test.go`: a move exactly at its
threshold and at the strong score, a country's rule found through stray
spaces, the least performing intervention on a tie, a score with fewer parts
than it needs, stored weights of every kind, the page number and the pager's
window.

Neither proves the statements themselves beyond what the seed holds (which
statuses and types a statement keeps are exported, not restated, but a
statement's joins are Go's own writing). The seed exercises each of them,
but thinly: no change rule is published, and it holds only a handful of
learning results, loans, stories, enrolment figures and register rows.

`schooldirectory.ScopeGeography` was compared with `resolve_user_scope`'s
`cluster_ids` and `district_ids` for nine accounts (four leads, three
officers, Impact Assessment, Admin): the same sets.

## 15.4 Found by comparing

- **The sections cannot be opened in the app** (15.1): the strip the feed
  sends links to seventeen addresses the feed then refuses.
- **With more than fifty clusters the table's note is the pager's
  caption.** The feed takes the first paragraph under a table for its note;
  with a pager that is "Showing 51–100 of 120", and the Command Center's own
  note is lost. Go answers as the feed does.
- **"Schools With Loans" counts loans.** `_funded_schools` asks for distinct
  schools, but the loan model's ordering adds the disbursement date and the
  creation time to what is distinct, so a school with two funded loans is
  counted twice (and Loan Reach can pass 100). Go counts what the page
  counts.
- **`?format=` is the feed's own.** Any `format` but `json` is refused by the
  feed's framework before the page is read (404), where the gateway reads
  the page. It is not a parameter the app sends; it is left out of the
  questions.

## 15.5 The runs

Each is the run's own last line, 29 seed accounts, against a gateway with no
existing application behind it:

```
/cluster-oversight/           725 answers compared, 0 differing
/cluster-oversight/ssa         29 answers compared, 0 differing
/cluster-oversight             29 answers compared, 0 differing
/cluster-oversight/scoring     29 answers compared, 0 differing
```

The last three are "not found" from both for every account.

## 15.6 What is left

- The seventeen sections and the scoring page, when the feed opens them.
- The downloads and the weights' save stay the existing application's.
