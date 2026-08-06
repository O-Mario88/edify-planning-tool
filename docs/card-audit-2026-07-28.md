# Edify — Platform Card Audit (2026-07-28)

Response to the platform-wide mandate to make every card, panel, widget and
information surface purposeful, unique, traceable and tested.

This records **what was measured, what was found, what was fixed, and what
remains**. It does not claim the mandate is complete — §8 states what is
outstanding, because most of the surface has not been touched.

---

## 1. Method, and three corrections to it

The audit is driven by a scanner committed as a permanent tool:

```bash
python manage.py build_card_inventory
```

It writes `docs/platform-card-inventory.json` and is covered by
`apps/system_health/test_card_inventory.py`.

### What counts as a card here

`templates/components/card.html` calls itself *"the single source for all card
surfaces"*. It is included **twice** across 875 templates. Every other card is
a hand-rolled stack of utilities — `edify-surface rounded-surface border
border-slate-100 shadow-sm p-5 space-y-3` and a hundred near-identical
variants. There is no component to enumerate and no attribute to key on.

So the scan treats a card as **a bordered surface that introduces itself with a
heading**. A surface with no heading is a layout wrapper, not an information
card. The heading is what makes a card auditable: it is the card's claim about
what it contains, and it is what two cards must not share on one page.

### The three corrections

Each was a wrong answer the scanner gave before it was fixed. They are recorded
because the fixed numbers are only trustworthy if the failures are visible.

| Wrong answer | Cause | Effect |
|---|---|---|
| 616 cards; **40** pages repeat a title | Nested wrappers (icon box, flex row, card) each claimed the same heading | One card counted 2–3×; 38 of the 40 "duplicate pages" were fictional |
| Reports page has two cards titled **"/"** | `<h3>{{ period.achieved }} / {{ period.target }}</h3>` — a KPI *figure* in a heading tag | A value read as a title |
| **0** pages repeat a title | Crude "is there an `{% else %}` between them" test | Suppressed the **genuine** duplicate on the Admin dashboard, 78 lines and several unrelated conditionals apart |

The third is the one that mattered: a scan that misses a real defect is worse
than one that reports a false one. Duplicate detection now compares **branch
paths** — two cards are alternatives only when they sit in different arms of
*the same* conditional, which is exactly the card/empty-state pairing §31 asks
for. Both directions are pinned by tests.

## 2. The measured surface

| Measure | Value |
|---|---|
| Titled cards | **555** |
| Templates containing them | 202 |
| Distinct card titles | 525 |
| Cards carrying a `data-card-key` | **0** |
| Untitled surfaces (layout wrappers) | 1,000 |
| **Pages repeating a card title** | **0** (was 1) |
| Titles used on several pages | 23 |
| Ambiguous titles from the §22 list | **0** |

Two results are worth stating plainly because they contradict the mandate's
assumptions:

* **Same-page card duplication was almost absent.** Exactly one real instance
  existed platform-wide, and it is fixed. The mandate's "required 0" was
  already nearly met.
* **No card uses an ambiguous title** from the §22 list (`Overview`, `Summary`,
  `Performance`, `Progress`, `Status`, `Insights`, `Activity`, `Budget`,
  `Information`). Titles here are mostly specific already — "Schools Needing
  Urgent Attention", "Cluster Activities This Week", "Budget & Fund Request
  Snapshot".

## 3. Defects found and fixed

### 3.1 The Admin dashboard rendered one card twice — FIXED

`templates/pages/dashboards/main.html` carried two `<section>` cards, in the
main column and in the right rail, both titled **"Team Target Progress"**, both
looping the same `team_targets`, both emitting the same rows with the same
numbers. Only a `--rail` modifier class differed.

Confirmed live: both rendered, each with 3 identical rows. A screen reader read
the whole list out twice.

This is §8's *exact duplicate* and §19's "remove side panels that merely mirror
the main content". **The rail copy is removed**; the main-column card owns the
information. The dashboard went from 14 panels to 13.

### 3.2 Two quick actions promised different things and did the same — FIXED

The Admin **Quick Actions** card offered:

| Label | Destination |
|---|---|
| Schedule Activity | `/planning` |
| **Add School Visit** | **`/planning`** |
| Create Cluster | `/clusters` |
| New Request | `/fund-requests/weekly` |

`/planning` takes filters for district, staff, school type, readiness and SSA
status — but **no activity-type parameter**, so nothing could have made the two
links differ. "Add School Visit" named a flow that does not exist and landed on
the same page as the link beside it.

Removed. Three actions remain, each with a distinct destination.

## 4. What was checked and found *not* to be a defect

Recorded because each looked like a finding and would have been wrong to report.

**Hardcoded card borders are not a dark-mode bug.** 458 card surfaces use
`border-slate-*` against 111 using `border-[var(--edify-border)]`, across 170
files — which looks like a mass theming failure. In dark mode
`border-slate-100` computes to `oklab(… / 0.0367)` — **white at 3.7% opacity**,
a correct dark border. Tailwind remaps it. This is a *consistency* issue worth
tidying, not a correctness one.

**"Attention Needed" beside "Next Recommended Action" is defensible.**
`recommended_action` is derived from the same three counts as `attention_items`
(the code says so), so it looked like §15 duplication. But it prioritises them
into a single directive with a CTA, and §1 lists *a queue* and *a next action*
as separate valid card purposes, while §20 explicitly allows a risk or
recommendation card alongside operational cards. There is also no duplicated
backend logic — both read the same local counts, satisfying §49. Left alone;
flagged for a product decision rather than removed unilaterally.

**Static/mock card data is already governed.** `apps/core/tests/test_mock_purge.py`
enforces "empty DB → empty arrays (no demo fallback)" and "dashboards do not
show fake counts". The mandate's static/mock prohibition is substantially
covered by an existing guarantee rather than needing a new one.

## 5. Guard tests added

`apps/system_health/test_card_inventory.py` — 17 tests:

* heading cleaning (a value heading is not a title; punctuation is not a title)
* branch-path computation (two arms of one conditional differ; an unrelated
  conditional does not link two lines)
* duplicate detection in **both** directions — a card and its empty state are
  not a duplicate; an unrelated conditional does not excuse a real one
* the live assertion: **no page renders the same card title twice**

Verified non-vacuous: restoring the Admin duplicate makes
`test_no_page_renders_the_same_card_title_twice` fail.

## 6. Files changed

```
apps/system_health/card_inventory.py                           (new)
apps/system_health/management/commands/build_card_inventory.py (new)
apps/system_health/test_card_inventory.py                      (new)
templates/pages/dashboards/main.html   (duplicate card + duplicate action removed)
docs/card-audit-2026-07-28.md                                  (this file)
docs/platform-card-inventory.json                              (generated)
```

## 7. Verification

* 125 tests across `system_health`, `command_center`, mock-purge, dashboard
  rows, design-system and navigation: **pass**.
* Live browser: Admin dashboard renders 13 panels, no repeated title, three
  quick actions with three distinct destinations.
* `ruff check .`: clean.

---

# Pass 2 — working the outstanding list in order

Items 1–6 of §8 below were taken sequentially. Items 1 and 6 were done together:
a card only gets an identity if there is one component that stamps it.

## P2.1 — Card registry + canonical component (items 1 and 6)

`apps/core/cards/` now mirrors `apps/core/metrics/`:

* **`CardSpec`** — key, title, purpose, the user question, card type (§10's
  controlled family), owning page, allowed roles, scope, service, source
  models, period, filter behaviour, empty message, drill-down, `does_not_mean`,
  refresh events. Validation refuses an ambiguous title, an unknown role, a
  missing empty message, and a missing drill-down without a stated reason.
* **`CARD_REGISTRY`** — the Admin Main Dashboard's 13 cards, registered.
* **`render_card()`** — binds records to a spec, enforces the role check
  (`CardNotPermitted`), and keeps *empty* and *errored* distinct so "nothing to
  do" can never stand in for "this failed to load".
* **`components/registered_card.html`** plus `registered_card_attrs.html` and
  `registered_card_header.html`. The attrs fragment is the migration path: an
  existing hand-rolled surface takes on `data-card-key` and friends **without**
  being rewritten first, which is what makes 555 cards tractable one at a time.

All 13 Admin cards now render with unique, registered keys.

## P2.2 — The 1,000 untitled surfaces (item 2)

Classified rather than guessed. The scan now splits the number by cause:

| Class | Count | What it is |
|---|---|---|
| chrome | 237 | icon discs, pills, avatars, buttons borrowing a card's rounding |
| nested | 380 | a region inside a card the parent heading already titles |
| headless | 379 | no heading above or below |

A 14-sample read of the *headless* group found **no missed information cards**:
they are filter controls, flash alerts, empty-state blocks, KPI sub-tiles and
action footers — all correctly outside a *card* scan.

Two scanner bugs fixed on the way:

* `\bw-\d\b` could not match inside `w-12` (the trailing word boundary falls
  between two digits), so **every 3rem icon wrapper on the platform** counted as
  an untitled card.
* `has_card_key` only inspected the matched `class="…"` text, so every migrated
  card reported as unregistered. It now reads the whole opening tag, including
  the attrs include.

**Conclusion: the "1,000 unaudited surfaces" was a measurement artefact.** The
scan's decision to skip them is correct.

## P2.3 — The 23 cross-page titles (item 3)

`accounts/dashboard.html` and `partials/disbursements/root.html` share **six**
titles — not an include relationship; two separate finance templates.

**Fixed — one title, two periods.** Both carried a card titled *"Disbursement
Status"*, but one is FY-scoped (`subline="total this FY"`) and the other
month-scoped (`subline="total this month"`). §7 permits period-scoped
repetition; §22 requires the title to say which period. Now *"Disbursement
Status This Financial Year"* and *"Disbursement Status This Month"*.

**Flagged, not fixed — a definitional disagreement about money.** Both pages
carry *"This Month Overview"* with a row labelled "Approved (Not Disbursed)":

| Page | Computation |
|---|---|
| `accounts/dashboard` | `_month_sum("Pending Disbursement")` |
| `disbursements/root` | `pending_disb + held_amt` — **includes Held** |

Same title, same month, same row label, two definitions. They agree today only
because nothing is in the Held bucket this month; the first held request makes
the two finance pages disagree. Whether held money is "approved but not
disbursed" is a finance decision, not a refactor — **this needs an owner's
ruling.**

## P2.4 — States, drill-downs and contracts (item 4)

`apps/core/tests/test_card_contracts.py` checks the registry against the real
app rather than against itself:

* every declared drill-down **resolves** to a view and is an absolute path;
* an Admin can actually **open** every Admin card's drill-down (200, following
  redirects);
* a card's `allowed_roles` never exceeds its owning page's `PAGE_PERMISSIONS`;
* empty and errored render distinguishably;
* every empty message is a written sentence, not "No data".

## P2.5 — Performance, mobile, accessibility (item 5)

**Two N+1 loops found and fixed** in `command_center/dashboard_service.py`:

* `weekly_progress` — 2 COUNTs × 5 weeks = 10 queries, now **one** read of
  `(planned_date, status)` bucketed in Python.
* `cluster_performance` — per cluster: a school-id read, an SSA average and 2
  COUNTs = ~20 queries for a five-row table, now **three** grouped queries.

| | Before | After |
|---|---|---|
| Admin `/dashboard` queries | 76 | **54** |
| `COUNT(*)` on `activity` | 37 | **17** |

Values verified **identical** before and after. While optimising I had replaced
an average over all SSA records with a mean-of-school-means — a different
number whenever schools hold unequal record counts. Caught and reverted to
carrying `Sum` and `Count` per school so the cluster average recombines exactly.

Two further latent status-set bugs fixed: `weekly_progress` and `_target_row`
both filtered on a local `["completed", "ia_verified", "closed"]`, omitting
`accountant_confirmed` — work that stopped counting as done once it reached the
accountant.

**Mobile and accessibility**, verified in a real browser at **360px, 430px and
desktop**: no horizontal page scroll, no card overflow, no clipped titles, no
nested interactive elements, no duplicate HTML ids, every card a `<section>`
with a resolving `aria-labelledby`. One reported "clipped title" was a false
positive — an `sr-only` heading is 1px wide by design.

Query budget and the accessibility invariants are now pinned by tests
(`DashboardQueryBudgetTest`, `CardAccessibilityTest`). The loop detector
compares a 400-character SQL prefix, not 70: at 70 every
`SELECT COUNT(*) FROM "activity" WHERE …` collapses into one "shape" regardless
of its filter, which made thirteen genuinely different counts look like a
thirteen-iteration loop.

## P2.6 — Where the mandate stands after pass 2

Done: items 1, 2, 3 (classified; one fixed, one escalated), 4 and 5 **for the
registered surface**, and 6's structural half.

Still open, and the honest limit of this pass:

1. **13 of 555 cards are registered.** The mechanism, the component, the
   migration path and the guards exist and are proven on one page. The
   remaining 542 have not been migrated, so §§4/25/30–34 hold for the Admin
   dashboard and nowhere else.
2. **The "Approved (Not Disbursed)" definition needs a finance ruling** before
   either page can be called correct.
3. **Cache-key scoping and real-time refresh (§50) remain unexamined.** No card
   is cached today on the surface reviewed, so there was nothing to check — but
   that is an observation about one page, not the platform.
4. **The remaining 21 cross-page titles** are catalogued in
   `docs/platform-card-inventory.json` and unclassified.
5. **Per-page card-purpose contracts (§55)** exist for the 13 registered cards
   (as registry entries) and for no other page.

---

# Pass 3 — query-shape sweep across the remaining dashboards

Pass 2 left the Admin dashboard at 54 queries while CD and RVP sat at ~245. This
pass profiled every role dashboard and swept for the same defect class.

## P3.1 — What the profile showed

Tracing which source line issues each query, the hotspots were:

| Role | Queries | Dominant source |
|---|---|---|
| CountryDirector | 245 | `targets/my_targets.py:326` ×27 |
| RegionalVicePresident | 246 | same ×27, plus `rvp_dashboard_service.py:402-404` ×12 each |
| Program Lead | 144 | spread, nothing above ×4 |

## P3.2 — Two things checked and found **not** to be defects

**The per-user ledger rebuild is not redundant.** `per_user_monthly_series`
calls `TargetAchievementService.rebuild()` once per user, which looked like the
waste its own docstring warns about ("calling `pooled_monthly_series` once per
subset would re-run rebuild() for the same person as many times as they appear
across subsets"). Measured: **9 calls for 9 distinct users** on both CD and RVP.
The callers already follow the documented guidance. Removing the read-path
rebuild entirely is a *freshness* trade — a 30-minute job already rebuilds these
ledgers — not a safe optimisation, so it was left alone.

**The CD dashboard's monthly chart is already optimal.** It uses `TruncMonth`
plus conditional `Count(filter=…)`, returning twelve rows from one query.

## P3.3 — The RVP monthly chart: 36 queries → 1

`rvp_dashboard_service.execution_timeline` looped over twelve months running
three COUNTs each — **36 queries to draw one chart** — while the grouped
`validated_by_month` read sat six lines above it.

Rewritten to the **CD dashboard's** pattern rather than my own first attempt.
The first version pulled the year's activities into Python and bucketed them
with `bisect`; that is also one query, but it carries every row across the wire
for a twelve-point chart. At the platform's 15k-school target that is the wrong
trade. Counting in SQL returns twelve rows regardless.

All four series (`planned`, `completed`, `verified`, `achievement`) verified
identical before and after. **RVP: 246 → 211 queries, 415ms → 350ms.**

## P3.4 — `cluster_planning`: ~12 queries per cluster → 7 total

The worst N+1 found anywhere. Each cluster row ran its own: five school counts,
three activity counts, two ordered `.first()` reads for last/next meeting, and
two school-id set reads.

| | 3 clusters | 15 clusters |
|---|---|---|
| Before | 38 queries | **182 queries** |
| After | 7 | **7** |

On the seeded data: **51 → 7 queries, 61ms → 14ms, byte-identical output**
(compared as sorted JSON). The cost is now constant in cluster count, so a
fifty-cluster deployment pays the same seven reads instead of ~640.

`apps/clusters/test_cluster_planning_queries.py` pins the *shape*, not a
number: it builds 3 clusters, measures, adds 12 more, and asserts the count is
unchanged. A bare threshold can always be argued upward; "adding clusters must
not add queries" cannot. Verified non-vacuous — on the old code it reports
`38 != 182`.

Writing that test surfaced a fixture trap worth recording: `School.save()`
reconciles `cluster_id` against sub-county coverage, so a school created with
`cluster_id=…` but no sub-county has its cluster **silently cleared**. The
fixture has to assign schools the way production does, through a shared
sub-county, or every row returns zero schools.

## P3.5 — Dashboard query profile after three passes

| Role | Queries | ms |
|---|---|---|
| Accountant (redirect) | **2** | 2 |
| Admin | **54** | 110 |
| CCEO | 80 | 157 |
| Program Lead | 144 | 459 |
| RegionalVicePresident | **211** | 372 |
| CountryDirector | 245 | 555 |

CD and PL remain the heaviest. CD's cost is dominated by the per-user ledger
rebuild described in P3.2 — a deliberate freshness trade, not a defect, and
changing it needs a product decision about acceptable staleness rather than a
refactor.

192 tests green across clusters, analytics, leadership surfaces, route-crawl,
command centre, cards and system health. Two failures in
`apps.frontend.tests` (`test_assign_partner_action_saves_when_no_cost_rate_is_configured`
and its bulk twin) **pre-date this work** — confirmed by re-running them with
these changes stashed.

---

# Pass 4 — widening the sweep beyond dashboards

Profiling every heavy route, not just dashboards, put `/analytics/country-director`
(332 queries) and `/clusters` (214) above every dashboard.

## P4.1 — `/clusters`: the canonical SSA lookup, called ninety times

`latest_applicable_record(school)` — *the* canonical "newest CONFIRMED SSA"
rule — was being called inside a per-school loop, and each result then had
`latest.scores.all()` read off it. **Ninety round trips on one page load**, in
two near-identical blocks (`cluster_weakest_interventions` and
`cluster_intervention_summary`).

Added `latest_applicable_records(schools, with_scores=True)` in
`apps/ssa/services.py`, beside the original: same rule, same
`(-date_of_ssa, -created_at)` tiebreak, one `DISTINCT ON (school_id)` query for
the whole set, scores prefetched. Schools with no confirmed record are **absent
from the mapping** rather than present with a zero — a missing measurement must
never read as a bad one.

**`/clusters`: 214 → 102 queries, 224ms → 160ms**, cluster intervention output
byte-identical.

`apps/ssa/test_latest_applicable_records.py` (8 tests) pins the batched twin
against the canonical original: the newest confirmed record wins, an
unconfirmed upload never wins, a deleted record is ignored, a school with no
confirmed record is absent rather than zero, one query serves every school, and
prefetched scores cost no further queries. A batched twin that quietly
disagrees with its original would change which schools look like they need
support.

## P4.2 — CD Analytics: 332 → 273 queries

Two fixes, and one deliberate refusal.

**Cluster activity counts (−36).** Another per-cluster loop running two COUNTs
each, now one grouped read.

**The SSA aggregates in the same loop were left alone, on purpose.**
`_cluster_membership` unions `School.cluster_id` with activity-derived
`(cluster, school)` pairs, so a school can belong to a cluster its own
`cluster_id` column does not name. Grouping those aggregates by
`school__cluster_id` in SQL would have been faster and would have quietly used
a *different membership* — changing the numbers. Recorded rather than done.

**Staff-to-user resolution (−23).** `_weighted_achievement` runs 28 times on one
render — country, per PL team, per CCEO row — and each re-ran the same
`StaffProfile → user_id` lookup.

The first attempt memoised on the whole roster and barely helped: those 28
rosters are mostly *different subsets of the same nine people*, eighteen of
them a single CCEO each, so eighteen distinct keys each missed. Re-keyed **per
staff member**, so a person is resolved once however many subsets they appear
in, and only genuinely unseen ids reach the database — in one query, not one
each. Outside a request (jobs, commands, direct calls in tests) there is no
store and the behaviour is exactly as before.

## P4.3 — Route profile after four passes

| Role | Route | Queries | ms |
|---|---|---|---|
| Admin | /dashboard | **54** | 102 |
| CD | /clusters | **102** (was 214) | 160 |
| PL | /analytics/program-lead | 154 | 595 |
| CD | /team-targets | 180 | 436 |
| RVP | /dashboard | **209** (was 246) | 356 |
| RVP | /analytics | 223 | 498 |
| CD | /dashboard | 243 | 553 |
| CD | /analytics/country-director | **273** (was 332) | 719 |

Every change verified output-identical before and after — sorted-JSON
comparison for the cluster and CD analytics payloads, series-by-series for the
RVP chart.

**What remains, and why.** The largest single cost left on CD surfaces is the
per-user `TargetAchievementService.rebuild()` in `per_user_monthly_series`
(P3.2): 9 users × ~6 queries on every load. It is not redundant — measured 9
calls for 9 distinct users — and a 30-minute job already rebuilds these
ledgers, so removing it from the read path is a **freshness decision** about
acceptable staleness, not a refactor. That is the next real win on CD, and it
needs an owner's call rather than an optimisation.

## 8. Original outstanding list (pass 1)

This pass built the measurement tool and fixed what it proved. The large
majority of §§3–5 and §§9–53 is untouched:

1. **No card registry exists.** 0 of 555 cards carry a `data-card-key`, and
   there is no equivalent of `apps/core/metrics` for cards — no canonical
   title, purpose, owning page, data contract, drill-down or allowed-roles
   declaration. §4's "no unregistered card may render" is not enforceable yet.
2. **1,000 untitled surfaces are unaudited.** The scan deliberately skips them
   as layout wrappers, but some are certainly cards whose heading sits outside
   the 10-line window, and some are genuine cards with no heading at all —
   which is itself a §22 defect.
3. **23 titles appear on several pages** and none has been classified against
   §7/§8. `Quick Actions` (6 templates) and `Attention Needed` (4) are the
   largest; each needs the "different role, scope, period, decision or action?"
   test applied.
4. **Card-level states, drill-downs and contracts are unverified.** §§25, 30–34
   (data contract, drill-down count agreement, loading/empty/error states) have
   not been checked for a single card.
5. **Not examined at all**: per-card query budgets (§51), cache key scoping
   (§50), real-time refresh (§50), mobile card behaviour at 360/390/430px
   (§41), card-level accessibility beyond the duplicate-announcement issue
   fixed in 3.1 (§52), and the page-by-page contract §55 requires.
6. **`components/card.html` is used twice.** Consolidating 555 hand-rolled
   surfaces onto a canonical component is the structural fix underneath most of
   the above, and it has not been started.

Item 1 is the prerequisite for most of the rest, exactly as the metric registry
was for the KPI audit — without an identity per card, none of the duplication,
scope, drill-down or state rules can be enforced by a test.
