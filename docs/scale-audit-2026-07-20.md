# Scale audit — 2026-07-20

Automated audit for hard-coded scale limits and unbounded-growth risks
above ~15,000 schools. 69 agents; every candidate finding was
adversarially verified by an independent agent instructed to refute it,
and 47 survived.

Severities below are the VERIFIER's corrected severity where it differed
from the finder's; several were downgraded on inspection.

---

# Edify Scale Audit — Ranked Engineering Brief

Target: 15,000+ client schools, no fixed ceiling. Findings ranked correctness-first (wrong numbers) then performance. Duplicates merged by root cause.

---

## TIER 1 — SILENT WRONG NUMBERS (correctness bugs)

### 1. The `[:5000]` export family — five exports silently truncate financial and roster data
**Root cause shared across:**
- `apps/frontend/views/finance_operating_views.py:665,679,701` — batch payout files (advances, partners, reimbursements) handed to the **bank**
- `apps/frontend/views/school_views.py:226` — school directory CSV/XLSX
- `apps/frontend/views/planning_views.py:304` — planning export (via `per_page=5000`)
- `apps/frontend/views/budget_views.py:138` — weekly fund requests CSV

**What breaks:** Every one of these is a country-scoped, unfiltered queryset sliced at 5,000 with no truncation marker in the file, no row-count footer, no UI warning. At 15k schools the school/planning exports lose two thirds of the roster while the KPI strip on the same page shows the true `.count()`. The finance exports are worse: `Activity.Meta.ordering = ["-created_at"]` means truncation drops the **oldest pending advances first** — the payees waiting longest. `ReimbursementClaim.Meta` declares no ordering at all, so its surviving 5,000 is an arbitrary Postgres subset that differs between two downloads of the same data. The advances queryset also has no Activity-status filter, so cancelled/abandoned activities accumulate permanently in the payout queue.

**Fix:**
- Delete the slice; stream with `.iterator(chunk_size=2000)`. Both the `csv.writer` and the `write_only=True` openpyxl workbook already stream compatibly — do not just remove `[:5000]`, that materializes 15k rows in the queryset cache.
- For `planning_views.py:304`, clamp `per_page` in `PlanningDashboardService` and add an explicit export path that bypasses `rows[start_idx:end_idx]`.
- Add explicit `Meta.ordering` to `ReimbursementClaim` and an `order_by("planned_date")` (oldest-first) to the advances export.
- Add a `WeeklyFundRequest` FY filter — `_scoped_base_querysets` applies `fy` to `budget_qs` only, never to `wfr_qs`.

---

### 2. Money KPIs summed over an unordered `[:25]` slice
**`apps/fund_requests/disbursement_dashboard_service.py:331,379`**

**What breaks:** `_partner_items()` and `_reimbursement_items()` slice `[:25]` with **no `order_by()`** — arbitrary rows, unstable between page loads. `get_disbursement_dashboard` derives real money from the truncated list: `total_month` (:929), `pending_disb` (:930), and critically `committed = pending_disb + held_amt` (:1051) feeding `available = allocation - utilized - committed` (:1052). Understated commitments **overstate available cash**. The sibling `_monthly_items`/`_weekly_items` are uncapped, so nothing on screen reveals the asymmetry. `f"{len(queue)} items"` (:955) reports the truncated count as fact.

**Fix:** Aggregate in SQL — `.aggregate(Sum("amount"))` over the full queryset for the KPI figures, keep `[:25]` (with an explicit `order_by`) only for the displayed list, and label it "25 of N". Never derive a total from a display slice.

---

### 3. Drill-down drawers report the slice length as the population count
**Root cause: `len(rows)` where `.count()` was needed.**
- `apps/analytics/pl_analytics_service.py:1905` — `f"{len(rows)} schools"` on a `[:200]` slice
- `apps/analytics/cd_analytics_service.py:2272,2289,2307` — `f"{len(rows)} shown"` on `[:200]`
- `apps/frontend/views/analytics_views.py:302,326,367,405,420` — `[:100]`, and the drawer template carries **no count field at all**

**What breaks:** KPI tile reads "Schools Without Verified SSA: 6,200"; clicking it opens a drawer stating "200 schools" and listing 200. Presented as the answer, on the screen whose entire purpose is auditability of the headline number. Violates the project's own no-fabricated-numbers rule. Worse, `School.Meta.ordering = ["-created_at"]` means the visible rows are the **newest-onboarded** schools — the least useful slice for a remediation worklist; the longest-standing no-SSA schools are structurally unreachable.

**Note:** `risk_list` already returns `{"rows": ..., "total": len(rows)}` (pl_analytics_service.py:1641) and `pl_dashboard_service.py:146-165` consumes it with proper pagination. The analytics drilldowns discard `data["total"]`. The district drill at `pl_analytics_service.py:1820` does it correctly with `len(scoped.school_ids)`. The correct pattern exists in-repo, three times.

**Fix:** Return `total` from a separate `.count()`, render "Showing 200 of 6,200", wire the existing paginator. Add `order_by` on the actual risk dimension (`average_score` for low-SSA — it is queried and then never used to order).

---

### 4. Additional live 500s found in the same drilldown path
**`apps/frontend/views/analytics_views.py:334,373,412`**

`s.account_owner.user.name` — but `apps/schools/models.py:94` defines `account_owner_id` as a plain `CharField`. There is no `account_owner` field or property. The `no_ssa` / `not_visited` / `not_trained` drawers raise `AttributeError` on the first row against a populated DB. A prior fix added `select_related("account_owner__user")` at lines 226-229 and missed the attribute access three lines below.

**Fix:** Resolve owner names via a batched `User.objects.filter(id__in=owner_ids)` dict lookup keyed on `account_owner_id`.

---

### 5. My Plan CSV capped at 75 rows by display slices leaking into export
**`apps/projects/my_plan_service.py:634` → `apps/frontend/views/extended_views.py:1678`**

`get_my_plan` returns `visits[:25]`, `trainings[:25]`, `partner_activities[:25]` for three UI cards. The export concatenates exactly those three context keys instead of re-querying — hard 75-row ceiling. Meanwhile `period_count` uses the unsliced `len(activities)`, so the page shows "412 activities this period" above a 75-row download. Secondary: any activity type in neither `VISIT_TYPES` nor `TRAINING_TYPES` is omitted from the CSV entirely at any scale.

**Fix:** Follow the pattern the sibling already uses — `apps/projects/planning_service.py:745` sets `export_rows = all_filtered_rows`, deliberately distinct from paginated `page_rows`. Add the same key here.

---

### 6. Per-project "Next Follow-Up" derived from a global `[:200]` slice
**`apps/projects/dashboard_service.py:300`**

The slice is applied to activities across **all** projects ordered by `scheduled_date`, then bucketed per project. The 200 earliest upcoming activities cluster into the next few days, so once the estate has >200 near-term scheduled activities, only projects in that window get a date — every other project renders a blank cell despite having follow-ups scheduled. A single large cohort starves every other project. Blank reads as "nothing scheduled", violating the honest-empty-state rule.

**Fix:** `.values("project_id").annotate(next_date=Min("scheduled_date"))` — one query, correct for all projects. `Index(fields=["scheduled_date"])` already exists to serve it.

---

### 7. Recipient picker silently hides the longest-tenured staff
**`apps/messaging/services.py:356`**

`allowed[:100]`, and `apps/accounts/models.py:159` sets `Meta.ordering = ["-created_at"]` — so it is deterministically the **100 newest accounts**, permanently hiding tenured staff. `can_message_recipient` ends in a bare `return True` for CD/PL/CCEO/Accountant/IA/Admin senders, so the filter removes nobody. No search endpoint exists anywhere in the codebase (`search_context_records` searches records, not users), no partiality indicator in the `<select>`.

**Fix:** Add a typeahead endpoint against `User` (mirror `apps/search/services.py`, already bounded to `[:20]`) and drop the blind slice.

---

## TIER 2 — PAGES THAT WILL NOT RENDER AT SCALE

### 8. `/system-health` iterates every batch ever created with two nested N+1s
**`apps/system_health/services.py:636`**

`DailyVisitBatch.objects.all()` — no FY, date, or status filter, on a table with `UniqueConstraint(["responsible_user","visit_date"])` that grows monotonically with staff-days and is never pruned. Inside: `_batch.activities.filter(...)` per batch, then `_a.school.district.district_type` per member activity — `select_related("school")` builds a **distinct School instance per row**, so no relation cache is shared and the district FK fires per activity. Plus a `SecondaryDistrictGroup` aggregate per batch. ~5-7 queries per batch × every batch ever. Uncached, no scoping. The function's own docstring (:238) claims "Every check is a DB aggregation, not a Python loop."

**Fix:** Bound to the current FY, then `.select_related("school__district")` and `prefetch_related` the activities; move the counts to `.values("daily_visit_batch_id").annotate(Count(...))`. Same function has two more unbounded loops: `EvidenceRecord` with an `os.path.exists` syscall per row (:252) and a per-`WeeklyFundRequest` `Sum` aggregate (:577).

---

### 9. Cluster dashboard — ~5 queries per school in the entire database
**`apps/clusters/services.py:1122` (+ `services.py:879` `cluster_planning`, same root cause)**

`for c in filtered_qs` over every cluster, and inside each: `for s in schools: _latest_confirmed_ssa(s)`. Then `cluster_intervention_summary(c.id)` (:720) and `cluster_weakest_interventions(c.id)` (:776) **independently re-fetch the same schools and re-run `_latest_confirmed_ssa(s)` again**, plus `latest.scores.all()` per school. Three SSA lookups + two score fetches per school, summed across all clusters = the whole school population. `latest_applicable_record` (apps/ssa/services.py:247) builds a fresh queryset and calls `.first()`, so a prefetch cache can never survive.

`cluster_planning` (:879) adds ~12 queries per cluster with no slice — while the sibling `list_clusters` (:65) carries an explicit `[:1000]  # safety bound` and already implements the correct batched `.values("cluster_id").annotate(count=Count("id"))`.

Worst caller: `ClusterRecommendationService.get_recommendation` (:1443) runs `cluster_planning(user)` for **all** clusters then does `next(p for p in planning_list if p["id"] == cluster_id)` — discarding every row but one, to produce four strings. Live from the HTMX planner drawer (`cluster_views.py:567`). `Paginator(cards, 5)` at `cluster_views.py:141` paginates the finished list, so page 2 pays the full cost again.

**Fix:**
- Replace `for s in schools: _latest_confirmed_ssa(s)` with the `Prefetch` pattern **already in this file** at `apps/clusters/services.py:470-485`: `Prefetch("ssa_records", queryset=...prefetch_related("scores"), to_attr="confirmed_ssa_records")`.
- Collapse `cluster_planning`'s 12 per-cluster queries into one `.values("cluster_id").annotate(...)` pass with conditional `Count(..., filter=Q(...))`, plus `Max`/`Min` for the two `.first()` date lookups — mirroring `list_clusters:68-85`.
- Give `get_recommendation` a single-cluster code path.

---

### 10. `ssa_improvement()` — one School query per school in scope, run twice per request
**`apps/analytics/decision_engine.py:92-101`**

`_scoped_school_ids` (:34) returns every non-deleted school id for `country_scope` **or** `can_view_summary_only` — CD, IA, Program Accountant, Admin, RVP. The loop then issues `School.objects.filter(id=sid).values(...).first()` per school despite already holding the ids. The two FY aggregates above it are correctly batched, making this the sole bottleneck. `recommendations()` calls `ssa_improvement()` again at :323, and `role_analytics.py:40,57,75,96,111` call **both** — so one role-overview request runs the loop twice: up to ~30,000 sequential queries. The `[:50]` truncation at :127-128 is applied after the loop, and `improvedSchoolIds`/`declinedSchoolIds` (:129-130) serialize the untruncated lists into the JSON payload.

**Fix:** Hoist one batched `School.objects.filter(id__in=matched_ids).values("id","school_id","name","district__name")` above the loop into a dict. Truncate the id lists too. Add the same `cache.get`/`cache.set(timeout=300)` wrapper the sibling views in `apps/analytics/views.py:39-68` already use — `AnalyticsSsaImprovementView`, `AnalyticsRecommendationsView` and `AnalyticsRoleOverviewView` are the three uncached outliers.

---

### 11. Champion eligibility — ~12 queries per Core profile plus a write on every GET
**`apps/core_schools/champion_services.py:117`**

`CoreSchoolProfile.objects.all()` unscoped, unpaginated, and `calculate_score(school)` fires 12 sequential queries per profile. The `select_related("core_plan")` is dead weight — `calculate_score` re-queries `CorePlan` independently at :15-17.

**Write amplification is permanent, not one-time:** the guard is `if profile.champion_status not in ["Champion", "Approved Champion"]`, so a school already at `"Potential Champion"` fails the check and is **re-saved on every page load**. Unbounded writes on a GET.

**Fix:** Batch the 12 lookups into annotated aggregates over the whole profile set; paginate the view; add `"Potential Champion"` to the guard list; move `evaluate_all` off the request path into a management command.

---

### 12. `list_candidates()` — one SSA query per client school
**`apps/core_schools/services.py:103`**

Selects all `client`/`potential_core`/`potential_champion` schools — and `SchoolType.CLIENT` is the model **default**, so this *is* the 15,000+ population — then runs a per-school `.order_by().first()` just to test `average_score >= 7.0`, discarding ~95%. `principal` is accepted and never used. Live at `/api/core/candidates` (config/urls.py:126) behind `IsAuthenticated + planning.view`, which six roles hold; no UI consumer found, which is the only thing capping severity.

**Fix:** Single joined query — annotate the latest confirmed record per school via `Subquery`/`OuterRef` and filter `average_score__gte=7.0` in SQL.

---

### 13. `_count_ssa_for_staff` — one SsaScore query per SSA record, inside a per-staff loop
**`apps/targets/performance.py:226` (+ `:326` `_drilldown_ssa`, same shape)**

Loops confirmed SsaRecords issuing `SsaScore...values("intervention").distinct().count()` per record just to check it equals 8. `performance_views.py:113-127` and `:161-170` iterate **every active StaffProfile** unpaginated, and since assignments partition the school population, total queries = the org-wide confirmed-SSA set (15k-60k per FY given the `quarter` field). `confirmed.values("id")` at :224 strips model instances, making prefetch structurally impossible. The module docstring (:16) asserts "All counts are DB aggregations... never Python loops."

**Fix:** One `GROUP BY`/`HAVING` — `.annotate(n=Count("scores__intervention", distinct=True)).filter(n__gte=8).count()`. The existing `uniq_ssa_record_intervention` composite index already serves it. Live and ungated at `/api/performance/*` but with no current UI consumer.

---

### 14. Map view — 15k markers inlined in one HTML document
**`apps/frontend/views/extended_views.py:1373,1385,1404`**

`school_queryset(scope)` returns the whole table for country scope; all rows are `json.dumps`'d inline into the document (`templates/pages/map/index.html:49-59`), then one `L.circleMarker` per point with an **eagerly-built** `bindPopup` string, no clustering, no canvas renderer, no viewport bbox, plus `fitBounds` over the full array. `config/settings/base.py:120-138` has no `GZipMiddleware`, so the multi-MB JSON ships uncompressed absent a proxy.

Separately: `SchoolGeoPoint.objects.all()` (:1385) is **unscoped for every role** — `school_id` is `unique=True`, so a CCEO with 30 schools still pays a full-table read that scales with the national count. That is the direct violation of "small scope must stay small".

**Fix:** Scope the `SchoolGeoPoint` read with `filter(school_id__in=school_ids)` and `.values()`. Add a bbox/zoom query param, server-side clustering, and Leaflet's canvas renderer with lazy popups. The adjacent directory already paginates at `school_views.py:357`.

---

### 15. Unmatched-SSA queue — 25 × 15,000 `<option>` elements per page
**`apps/frontend/views/extended_views.py:2697`** → `templates/pages/admin/unmatched_ssa_queue.html:118`

`schools_list` is the entire School table (full wide model instances, no `.only()`), rendered inside the per-row `<form>` loop. Records are capped at `DEFAULT_PAGE_SIZE = 25` (`apps/ssa/unmatched_service.py:33`), so the page emits ~375,000 option nodes — ~25 MB uncompressed. Already ~1.65 MB at today's ~1k schools.

Note `apps/ssa/unmatched_service.py`'s docstring documents a prior audit fix that removed the unbounded per-row `name__icontains` scan on this exact page — the fix addressed the query axis and left the rendering axis.

**Fix:** Typeahead against `apps/search/services.py` (already `[:20]`). Cheap interim: render the `<select>` once outside the loop and clone client-side, scoped to `school_type="client"` + the record's `district_raw`.

---

### 16. Schedule-activity form — every school in the database in one `<select>`
**`apps/frontend/views/planning_views.py:1276`** → `templates/pages/planning/schedule.html:45`

Unscoped `School.objects.filter(deleted_at__isnull=True)`, full model instances, one `<option>` each. A CCEO with 40 assigned schools is served all 15,000 — a ~1.5 MB form they open many times a day, and an information disclosure (every school name and ID to anyone holding the `planning` permission). The sibling drawer at `planning_views.py:487` does it correctly with `get_scoped_object_or_404`.

**Fix:** Apply `school_queryset(resolve_user_scope(request.user))` and a typeahead.

---

## TIER 3 — MISSING INDEXES / QUERY SHAPE

### 17. `Activity.attended_school_ids` ArrayField has no GIN index but is queried with `__overlap`
**`apps/activities/models.py:165`**

The only `GinIndex` in the entire project is `school_name_trgm_idx`. `&&` on an unindexed array is a nested loop over both operands. Worst site is **`apps/analytics/impact_engine.py:227`**: `Q(school_id__in=school_ids) | Q(attended_school_ids__overlap=school_ids)` where `school_ids` is all 15k. Cluster activities carry `school_id = NULL`, so the first OR arm evaluates NULL (not TRUE) and **cannot short-circuit** — every cluster row is compared against a 15,000-element constant array: O(rows × 15k) element comparisons. The OR also blocks a BitmapOr, so the indexed `school` FK is useless too.

Second site `apps/frontend/view_models.py:87` runs on every `/schools` render and fires on **every debounced keystroke** (`school_views.py:441`, `keyup delay:300ms`).

**Fix:** `GinIndex(fields=["attended_school_ids"])` in `Activity.Meta.indexes`. Split the OR in `impact_engine` into two queries unioned in Python so each arm gets its own index.

**Why the gate missed it:** `apps/system_health/test_load_scale.py` seeds only Schools/SsaRecords/SsaScores — grep for `Activity` returns nothing. And `_assert_scale_invariant` asserts *query count* stability, so an O(1)-query / O(N)-row-scan page passes by construction.

---

### 18. `Activity.monitored_by_staff_id` unindexed, always OR'd with an indexed column
**`apps/activities/models.py:73`**

A Postgres BitmapOr requires an index on **both** arms; one unindexed arm collapses the plan to a seq scan. `apps/frontend/views/dashboard_views.py:414` builds `cc_activities` with only `deleted_at__isnull=True` plus the OR — **no FY, no date, no status bound**, so the candidate set is the entire historical activity table. It is then re-executed **8 times** per CCEO dashboard load (counts at :453,454,457,459; lists at :497,548,575,607). The list queries have `LIMIT 8/10` but `ORDER BY planned_date`, which is also unindexed, so the limit does not avoid the full sort.

**Fix:** Add `models.Index(fields=["monitored_by_staff_id"])`, and add an FY bound to the `cc_activities` base queryset so degradation plateaus instead of compounding forever. Same unindexed-OR at `apps/my_plan/services.py:134,444`.

---

### 19. Calendar's `scheduled_date__date__range` is non-sargable, and its OR arm lands on unindexed `planned_date`
**`apps/frontend/views/extended_views.py:247`**

`USE_TZ = True` (`config/settings/base.py:246`) compiles `__date__range` into `(scheduled_date AT TIME ZONE ...)::date BETWEEN`, which the plain `Index(fields=["scheduled_date"])` can never serve. The other OR arm is `planned_date`, unindexed. And the scope filter added at :285 is *itself* an OR with the unindexed `monitored_by_staff_id`. **Every access path is a seq scan**, on a page `navigation.py:107` grants to `ALL_ROLES`, fired on every month navigation.

**Fix:** Rewrite as a half-open datetime range on `scheduled_date` (`__gte=start_dt, __lt=end_dt`) so the existing btree applies; add `Index(fields=["planned_date"])` and the `monitored_by_staff_id` index from #18. Same non-sargable shape at `budget_views.py:522-525`.

---

### 20. `Activity.planned_month` unindexed, hit by 24 sequential counts
**`apps/analytics/analytics_dashboard_service.py:534`**

12-month loop × 2 `.count()` calls, each filtering an FY-scoped set by an unindexed integer — the `(fy, quarter)` index narrows to FY but `planned_month` is a heap post-filter. Uncached: `analytics_views.py:41` calls `get_analytics_data` directly, and :85-86 re-runs it on every HTMX filter swap. Same function repeats the pattern for districts (:581), regions (:618), clusters (:646), staff (:804).

**Fix:** One query — `.values("planned_month").annotate(planned=Count("id"), achieved=Count("id", filter=Q(status__in=ACHIEVED_STATUSES)))` replaces all 24. Add `Index(fields=["fy","planned_month"])`. Wrap the page in the 300s cache the DRF siblings already use.

---

### 21. `School.account_owner_id` unindexed, hit in an unbounded roster loop
**`apps/schools/models.py:93`** — plain `CharField`, absent from `Meta.indexes`, which indexes eight other filter columns **including `cluster_id`, also a plain CharField**. Clearly an omission.

Real bite is **`apps/hr/services.py:38-44`** (`roster()`): iterates every `StaffProfile` unpaginated and issues one unindexed `School.objects.filter(account_owner_id=sp.id).count()` per row. O(staff × schools) sequentially scanned — ~2.25M rows at 15k schools × 150 staff. The one-shot call sites (`analytics_dashboard_service.py:92`, `staff_views.py:270`, `planning_service.py:180`) are constant-cost per request and not independently a finding.

**Fix:** `models.Index(fields=["account_owner_id"])` (selectivity ~1%, planner will use it) plus replace the roster loop with one `.values("account_owner_id").annotate(Count("id"))` dict lookup.

---

### 22. Staff Directory aggregate has no date floor — scanned set grows forever
**`apps/frontend/views/staff_views.py:99-108`**

`planned_date__lt=today, status__in=["scheduled","in_progress","completion_started"]` with no FY and no scope, on every page render. An activity abandoned in FY1 stays `scheduled` forever, so the scanned set grows with schools × years and never recovers. The KPI is also semantically wrong — staff flagged high-risk today because of three-year-old ghosts.

**Fix:** Not an index on `planned_date` (an open-ended `< today` predicate would not use a plain btree anyway; `Index(fields=["status"])` already gives a bitmap path). Add an FY/date floor to the filter, plus a partial composite index on `(status, planned_date)` restricted to the three open statuses if the aggregate must stay global.

---

## TIER 4 — LINEAR COSTS ON EXECUTIVE PAGES

### 23. CD scope materializes 15k ids, then replays them as `IN` lists ~30× per load
**`apps/analytics/cd_analytics_service.py:110`**

`school_ids = list(schools.values_list("id", flat=True))` on the unfiltered default path, re-embedded as `id__in=` / `school_id__in=` in ~30 statements per CD Analytics load and ~10 per CD dashboard. `psycopg[binary]==3.2.3` uses client-side interpolation, so there is **no 65,535 bind-parameter ceiling** — the cost is Python-side quoting plus ~400KB of SQL text per statement (~12MB/page load).

`_cycle_fys` is unmemoized and called ~17 times per load, each a `SELECT DISTINCT fy ... WHERE school_id IN (<15k literals>)` returning an identical answer. Worse, `cd_dashboard_service.py:360-378` and `:713` bind the queryset lazily then **re-evaluate it inside a `for rid in region_ids` loop** — O(regions × schools).

**Fix:** Keep `schools` as a lazy queryset on `CDScope` so `id__in=` compiles to a subquery. Memoize `_cycle_fys` per scope (cheapest single win). Hoist the region loop's queryset evaluation.

---

### 24. Python loops where SQL aggregates belong — CD/PL dashboards
Shared root cause: pulling id sets into Python to compute set membership.

- **`cd_dashboard_service.py:749`** `priority_schools` — hydrates 15k `select_related(district, region)` instances, builds `visited`/`trained` sets from `values_list("school_id")` **with no `.distinct()`** (so the wire transfer is activity-count-sized, 100k+ rows), scores every row in Python, sorts, returns 6.
- **`cd_analytics_service.py:1611`** `operational_risk` — rebuilds the same 100k-row pulls *again in the same page load* to produce two integers.
- **`cd_analytics_service.py:2290`** `_drill_risk` — same 100k-row `reached` set; the `[:200]` is applied *after* the full scan. Same pattern at `:368` in `kpis()`, which is on the main dashboard load (higher traffic).
- **`cd_analytics_service.py:1298`** `cceo_snapshot` — materializes every FY activity into `activity_info` + two defaultdict-of-sets (~50-70 MB) to produce 12 display rows. `Activity.Meta.ordering = ["-created_at"]` with no `created_at` index forces a full external sort of all 150k rows for an ordering the consumer never uses.
- **`cd_analytics_service.py:970`** `cluster_performance` — 5 queries per cluster (including a redundant second `SsaRecord` read whose average is derivable from the first). **The identical function was already de-N+1'd in the sibling:** `pl_analytics_service.py:1019` carries the comment *"Batch-fetch once instead of ~7 queries per cluster"*, and `test_analytics_query_performance.py` asserts a ceiling for the PL version but not the CD one.

**Fix:** Push the anti-joins into SQL — `schools.exclude(id__in=completed.filter(...).values("school_id"))[:200]` — and replace the Python bucketing with `.values("cluster_id"/"responsible_staff_id").annotate(Count(..., filter=Q(...)))`. Add `.distinct()` to every membership `values_list`. Port the `pl_analytics_service:1019` batch pattern to the CD copy and extend the query-count test to cover it.

---

### 25. `.filter()` on a prefetched relation discards the prefetch
**`apps/core_schools/core_planning_services.py:1128`**

`plans` is loaded with `.prefetch_related("slots")`, then `p.slots.filter(owner="partner").exists()` — `RelatedManager.filter()` clones the queryset and resets `_result_cache`, so the prefetch is **paid for and then thrown away**, and a fresh EXISTS fires per plan. Line 1128 is the *only* consumer of the prefetch, so both halves of the cost are pure waste.

`core_schools_views.py:80` passes the **unpaginated** `core_schools_qs` — conspicuous because lines 74-75 immediately above correctly pass `page_obj.object_list`. Cost is identical on page 1 and page 500.

**The fix is documented 300 lines above in the same file.** `core_planning_services.py:810-811`: *"calling .filter() here would discard the prefetch and re-query per school"*, with the correct idiom at :815.

**Fix:** `any(sl.owner == "partner" for sl in p.slots.all())`, and pass `page_obj.object_list`.

---

### 26. Id lists materialized and replayed as `IN` clauses, ~40× per Core Schools load
**`apps/core_schools/core_planning_services.py:989,1019`**

`get_intervention_impact` receives the unpaginated queryset and loops all 8 `SsaIntervention` choices. Per iteration: an N-param `CoreActivitySlot` filter, `completed_school_ids` materialized and replayed into `CorePlan.objects.filter(school_id__in=...)`, `plans_for_intervention` iterated as **full model instances** rather than aggregated, then `_staff_partner_split_for_intervention` repeats the whole pattern and replays two more id lists into `SsaScore` aggregates. Net ~40 statements carrying up-to-N `IN` lists and ~24 full id-list transfers per page load. N ≈ 2,500-3,000 (core is ~15% of population), so this is medium, not fatal.

**Fix:** Keep the inner querysets unevaluated so they compile to subqueries; replace the instance iteration with `Avg`/`Count` aggregation.

---

### 27. School import is O(rows × schools)
**`apps/schools/upload_service.py:403` (+ `:25,357,597` geography)**

`School.objects.filter(name__iexact=name).exists()` per row. `iexact` compiles to `UPPER("name") = UPPER(%s)`; the only name index is a `gin_trgm_ops` GIN index which serves LIKE/ILIKE/similarity but **not** an `UPPER()` equality predicate — so each row seq-scans the whole school table. A 15,000-row file against 15,000 schools is ~225M comparisons across 15,000 round trips.

Compounding: `_resolve_geography` issues 1-4 uncached queries per row and is called **twice** per row (validation pass :357, import pass :597), ~8 of the ~11 queries per row. No row cap exists anywhere. The import half is wrapped in a single `transaction.atomic()` (:590) while the staging half is **not** — a timeout mid-loop leaves an orphan `status="staged"` batch with zero rows.

This exact defect was already fixed on the SSA side — `apps/ssa/unmatched_service.py`'s docstring describes it as *"a full-table ILIKE scan each time... unbounded on both axes"* and shows the remedy (district-narrowed candidate pool + trigram ranking, `CANDIDATE_LIMIT = 200`).

**Fix:** Add a functional index — `RunSQL("CREATE INDEX ... ON school (UPPER(name))")` — or denormalize a `name_normalized` column with a plain btree. Memoize `_resolve_geography` in a per-request dict keyed on the raw name (~146 districts, heavily repeated). Chunk the import out of one atomic block, or move it to a background job.

---

### 28. Remaining unpaginated tables (established in-repo pattern simply not applied)
- **`apps/frontend/views/partner_views.py:491`** — renders the partner's entire historical school list, **plus an N+1**: the template reads `s.district.name` and `s.sub_county.name` per row with no `select_related`. 2 extra queries per row → ~4,000 queries at 2,000 schools. Bites at hundreds, not thousands.
- **`apps/frontend/views/extended_views.py:517`** — district detail renders every school in the district; Wakiso/Kampala hold 1,200-1,800 at a 15k estate. No N+1 (template reads local fields only), and `schools.count()` is already computed.
- **`apps/frontend/views/school_views.py:551,603,660,718,787`** — 9 loops running a COUNT per cluster **and** an unprefetched `ac.district.name` per cluster (~2 queries each, not 1). Plateaus at Uganda's sub-county ceiling (~1,500-2,000) because `create_cluster` enforces one active cluster per sub-county.

**Fix:** `Paginator` + `select_related("district","sub_county")`, copying `school_views.py:351-357`. For the cluster dropdowns: `annotate(schools_count=Count("assignments"))` + `select_related("district","sub_county")`.

---

### 29. Impact engine — full-population materialization into pandas
**`apps/analytics/impact_engine.py:226`**

`_scoped_schools` returns all 15k for country scope; `activity_frame` `list()`s every completed activity in the window, then a second full Python pass, then a DataFrame — three concurrent copies. `lo`/`hi` are the **union** of every school's exposure window (~2 years), so the DB returns far more than the per-school windows (re-applied in Python at :272-279) actually use. `_accepted_spend_by_activity` replays every fetched activity id as an `IN` list. Uncached (`impact_views.py:14`), re-run on every HTMX FY swap. See #17 for the array-overlap seq scan that dominates the query cost.

Also `impact_engine.py:516` — the funding scatter emits one `[spend, delta]` point per funded school, unbounded, `json_script`'d into the DOM and handed to ApexCharts (SVG, one node per point). The adjacent quadrant lists are capped at `[:8]` ten lines above, so the cap was considered and skipped.

**Fix:** `.iterator()` into chunked frame construction, per-school date windows in SQL, and hexbin/sample the scatter above ~2,000 points.

---

### 30. Minor — constant-factor Python scan
**`apps/analytics/ssa_performance_service.py:344`** — `next(row["district__name"] for row in schools if ...)` inside the per-district loop: ~1.1M iterations at 15k schools (~0.2s). Real but dwarfed by the same function's unbounded `.values()` materialization (:243) and 15,000-element `IN` clause (`_record_rows`, :110). **Fix:** build `{district_id: district__name}` in the one-pass loop that already exists at :333-335. Fix the bigger two first.

---

## Suggested sequencing

1. **Tier 1 in full** — every one is a wrong number in front of a decision-maker, and most are one-to-three-line fixes (`.count()` instead of `len()`, `.iterator()` instead of `[:5000]`).
2. **#4** — a live 500, cheapest fix in the brief.
3. **#8, #9, #11** — the three pages that will not render; #9 and #11 also hammer the DB.
4. **#17, #18, #19** — three migrations plus one query rewrite; broadest latency win per line changed.
5. **Everything else** by page traffic.

## Two systemic notes

**The scale gate has a structural blind spot.** `apps/system_health/test_load_scale.py` seeds only Schools/SsaRecords/SsaScores — no Activities — and `_assert_scale_invariant` asserts *query count* invariance (`QUERY_SLACK = 4`). Any O(1)-query / O(N)-rows-scanned page passes by construction, which is exactly how #17, #23 and #29 survived. Recommend adding Activity/DailyVisitBatch to the fixture and asserting response *bytes* and peak RSS alongside query count. The CD Analytics and CD Executive pages are not gated at all.

**Several fixes already exist in-repo and were simply not propagated.** `pl_analytics_service.py:1019` (batched cluster perf) vs. the CD copy; `core_planning_services.py:810` (the prefetch comment) vs. :1128; `clusters/services.py:470` (the `Prefetch` + `to_attr` pattern) vs. :1122; `list_clusters:68` (batched annotate + safety bound) vs. `cluster_planning:879`; `planning_service.py:745` (`export_rows` separate from `page_rows`) vs. My Plan; `school_views.py:351` (paginate + select_related) vs. the partner/district/map pages; `ssa/unmatched_service.py` (district-narrowed candidate pool) vs. `schools/upload_service.py:403`. A grep-based lint for `.filter(...).exists()` on prefetched relations, `len(` on sliced lists feeding a count label, and bare `[:5000]` in export paths would catch most of this class going forward.
