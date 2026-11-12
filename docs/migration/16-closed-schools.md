# 16. Closed Schools (the archive), read by Go

Owner brief "Final backend responsibility and language boundaries"
(2026-11-11): Go as the application backend. The School pages move in pieces
(11 to 13: the directory and a school's profile, a closed school's included).
This piece is the archive those closed schools are listed in.

| Piece | What moves | State |
|---|---|---|
| 1 | The Closed Schools page (`/schools/closed`): whose closures, the three figures, the year's closure impact, the search, the table and its pages | This document |
| — | Closing and reopening a school (the profile's drawers and saves) | Still the existing application's |

## 16.1 What moved

`PageScreenService.GetPage` is answered by
`platform/backend/internal/closedschools` for the path `/schools/closed`, for
someone working in their own role. The contract is the generic page; Go
builds the blocks the existing feed reads from
`templates/pages/schools/closed.html`.

| Part | Existing rule it ports |
|---|---|
| Who may open it | `require_page_permission("closed_schools")` and the feed's `can_open_url`: CCEO, Program Lead, Impact Assessment, Country Director, Regional Vice President, Admin. Anyone else is not found, as the feed answers |
| Whose closures | `_closed_archive_scope`: closures not reopened, of the schools the reader's analytics reach (`scoped_school_queryset`: a country reader's country, with unplaced schools reached through their owner; the deployment or its regions for a summary reader; own and team schools for an officer or a lead; deleted schools left out) and, for an officer or a lead, any closure whose recorded owner is the reader or one of their officers, in either id space (`_both_id_spaces`) |
| The search | `q`, stripped, anywhere in the school's name whatever its case; `%`, `_` and `\` are themselves |
| The three figures | Closures and their summed enrolment over every matching closure (not the page on show); the reader's schools still operating (`active_enrollment`'s `schools_active`), which the search does not narrow |
| Closure Impact | For a reader of `closure_impact` (Country Director, RVP, Admin, and Impact Assessment, who opens what Admin opens): `closure_analytics.country_summary` over the operational year (1 October to 1 October, UTC), closures not reopened, of the schools in reach: districts, schools, budget released, activities cancelled, partner hand-overs withdrawn. The money is shortened as every strip shortens it |
| The rows | The latest effective date first, at most 500 (`CLOSED_ARCHIVE_MAX_ROWS`); a summary-only reader (the RVP) is given none, and told so |
| A row | School ID (written by the page's script, so the feed reads it empty), name and official ID (the name a link to the profile for a reader of profiles), district or a dash, the owner's name as recorded or a dash, the effective date, the closure's type and reason words (the stored value where it is not one of the choices), the reason cut to 90 characters as `truncatechars` cuts it, enrolment or "Not recorded" (none, or zero), and View |
| Pages | Fifty rows (`TABLE_PAGE_SIZE`), `closed_page`: not a number is the first, out of range the nearest; `make_pagination_window` with one page either side. The links carry the rest of the query in key order, less the keys the feed never passes |
| Nothing to list | The figures-only line for a summary reader, the search line when a search is on, otherwise the archive's own line |
| The header | "Clear search" with the search cut to 24 characters, while one is on |

Each role's three doors (the page, the impact, profile links), the closure
type and reason words, the operating statuses, the row cap, the page size and
the query keys the feed drops are exported to
`internal/closedschools/rules.json` by `manage.py export_closed_schools_rules`;
`apps/schools/test_closed_schools_rules_export.py` fails when the two differ.
The row cap was a literal in the view; it is now
`school_views.CLOSED_ARCHIVE_MAX_ROWS`, so the export reads it. Nothing it
bounds changed.

The schools an analytics page may read (`scoped_school_queryset`) had no Go
form: the directory's is the operational one, which gives a Country Director
and an RVP nothing. `schooldirectory.AnalyticsReach`
(`export_closedschools.go`) is that rule, from the same scope and the same
country test the directory uses.

Three things were found by comparing, not by reading:

- **The pager is not the table's.** The archive's card has no heading, so the
  feed does not read it as a table card: it reads the table on its own (no
  pager, no note under it) and then the pager as a plain panel of loose lines
  and links: "Showing 1–50 of 500", the current page and each gap as text,
  the runs of page links between them, and Prev and Next with their arrows
  as captions. Go writes that panel. Reading the template said the pager and
  its summary would sit inside the table.
- **The School ID cell is empty in the feed.** The page writes a token its
  script later replaces, so the feed reads no text there. Go writes none.
- **The cut is counted before the spaces are run together.** A reason with
  runs of spaces is cut at 90 stored characters and only then collapsed, so
  fewer than 90 are shown.

## 16.2 Proving it is the same

`cmd/parity -screen page -path /schools/closed` asks the Go-only gateway and
the existing feed the same twenty questions as each account: the page as it
opens; eight searches (matching, upper case, padded, matching nothing, `%`,
`_`, longer than the header shows, and one with a dotted capital I and an
accent); `closed_page` 1, 2, 999, 0, -3, "abc" and " 2 "; two keys the page
does not read; and a search with a page, with and without another key.

All 29 seed accounts and the Regional Vice President (`rvp@edify.org`, the
summary-only reader, who is not among the 29) against a gateway with no
existing application behind it. The run's last lines:

    coordinator@edify.org              20 questions, 0 differing
    rvp@edify.org                      20 questions, 0 differing

    600 answers compared, 0 differing

Twenty answers for each of the 30 accounts; the Project Coordinator and the
Business Transformation Officer are turned away by both.

The run was made again, with the same last lines, after the pager and the
"Clear search" button moved to `closedschools/shared.go` for Programme
Schools (17) to use.

The development database holds one closure, so that run proves the gate, the
scope's two shapes (a reader with the school in reach and one without), the
figures, the impact strip, one row and the searches, and nothing about many
closures. Two things cover the rest.

**The existing feed's answers over 530 closures, compared in the test
database.** `agent2_closed_golden.py` (kept in the session scratchpad, not in
the repository) points the existing application at the local test database,
files 530 closures there (520 open ones on 520 schools, a day apart so their
order is defined, and ten reopened; unknown type and reason words, reasons
that are long, empty, exactly 90 characters, with markup and with combining
accents, enrolment missing, zero and in the millions, owners recorded under
another officer's staff id and another's user id), asks the feed thirteen
questions as each of 31 accounts (the 29, the RVP and a Regional Programme
Lead), writes the rows and the answers to a file and deletes the closures.
`TestTheArchiveMatchesTheExistingFeedOverManyClosures`
(`internal/integration/closed_schools_test.go`) files the same rows, asks Go
the same questions and compares each answer as a whole message; it is skipped
unless `EDIFY_CLOSED_SCHOOLS_GOLDEN` names that file, because the answers
hold the day they were made on. It printed:

    closed_schools_test.go:236: 403 answers of 31 accounts compared, 0 differing

That run reaches the 500-row cap under a count of 520, ten pages and the
pager's gaps, every page in and out of range, the search with a page, the
reopened closures left out of every figure, the owner arm in both id spaces
(an officer with no school in reach reading eleven closures recorded against
them, and their lead reading the same), the RVP's figures without rows, the
impact strip with money in the millions ("UGX 124.16M"), and a role the page
refuses. Only `school_closure` rows were written, and none is left.

**A varied private copy.** For Programme Schools (17.2) the development
database was copied to a private local one and varied; 130 closures were
filed there too (three days apart, thirteen reopened, one at a school whose
record was then deleted, one at a school with no district, every seventh
recorded against another officer's user id). The existing application and a
Go-only gateway were both started against the copy and compared by the same
tool as ten accounts. It printed `200 answers compared, 3 differing`: the
three were the seed's own closure and one filed for the same day, exchanged
(16.3). With that one moved a day it printed:

    200 answers compared, 0 differing

**Unit tests** (`internal/closedschools/page_test.go`,
`schooldirectory/export_closedschools_test.go`) hold what neither database
reaches: a school with no district, no name or no official ID, a reader who
may not open profiles, each lens of `AnalyticsReach`, `truncatechars` on
combining marks, the pager's window at every position, Python's `int()` of a
page number, and the query the pager's links carry.

## 16.3 What is left

- Closures that take effect on the same day have no order between them: the
  page sorts by effective date alone, and so does Go, with the same
  statement shape. Postgres may return such a pair either way, and on the
  private copy it did (three answers of 200, 16.2). Go cannot follow an
  order the existing page does not define; the model's own ordering
  (`-effective_date, -created_at`) is replaced by the view's
  `order_by("-effective_date")`, and restoring the second key there is the
  existing application's to do.
- A school whose record was deleted after it closed is still listed for the
  owner it was recorded against (the owner arm does not ask whether the
  school is deleted) and for nobody else. Go does the same; it reads as an
  oversight in the existing rule rather than a choice.
- Closing and reopening stay the existing application's.
