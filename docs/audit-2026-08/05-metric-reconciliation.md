# Metric reconciliation (mandate §21, acceptance gate 11)

68 registered metrics were read against the service each one names
as its single source of computation. **50 disagree with their specification.**

Read the severity honestly: most entries are *declaration* drift — a spec
naming a renamed function, or a `date_basis` label that does not match the
column the query filters. The number on the page is right; the description
of it is wrong. Those still matter (the registry is the platform's answer to
"what does this number mean?") but they do not mislead a reader today.

The ones that change what a reader sees are marked **high** and should be
settled before the client rollout.

## High (14)

### `fund_request_monthly_visits_budget`

- **Implementation:** /Users/omario/Developer/Edify Planning Tool/apps/budget/services.py:1032-1047 (table_kind) consumed at /Users/omario/Developer/Edify Planning Tool/apps/frontend/views/budget_views.py:788-800
- **Discrepancy:** The service does not compute visit spend — it computes residual spend. table_kind() returns "admin" for programme_activity_type=='admin', "meeting" for 2 types, "training" for 6 types, and "standard" for EVERYTHING else (services.py:1047). budget_views.py:791 then folds any unrecognised kind into "standard" as well, and line 795 labels "standard" as visits. So ssa_activity, partner_activity, project_activity, programme_event and every future ActivityType land in the "School Visits" money tile. The canonical vocabulary that would answer this correctly already exists and is ignored: VISIT_TYPES (15 members), SSA_TYPES, PROGRAMME_EVENT_TYPES, OTHER_TYPES at /Users/omario/Developer/Edify Planning Tool/apps/core/activity_types.py:40-101; services.py:1010-1018 re-declares training/meeting as inline literal copies instead. The same money is bucketed "Other"/"SSA Support Visits" by the sibling finance surface at /Users/omario/Developer/Edify Planning Tool/apps/fund_requests/pl_approval_service.py:93-109, so the fund-request band and the PL approval queue disagree by construction. LIVE PROOF (psql edify_pm): fundable, scheduled cost lines for Apr-2026 bucket as standard=UGX 32,936,000, meeting=920,000 — but actual school_visit cost lines total only UGX 21,344,000. UGX 7,912,000 of ssa_activity and UGX 3,680,000 of partner_activity money (35% of the tile) is reported as school-visit spend. The comment at services.py:1032-1039 documents exactly this bug class and fixed only the admin case. Secondary: filter_behaviour is declared FILTERED but budget_views.py:779-787 passes only period/fy/date/budget_scope to budget_workspace, so the band ignores the page's District, Staff, Request-type and Status filters that _scoped_base_querysets applies at budget_views.py:139-151 to the KPI strip directly above it; the correct declaration is PARTIAL.

### `partner_oversight_payment_pending`

- **Implementation:** /Users/omario/Developer/Edify Planning Tool/apps/planning/partner_oversight_service.py:743-750 (with _COMPLETE_STATUSES at :44)
- **Discrepancy:** The spec says IA-verified; the service counts activity status. summarize() filters `i.activity_status in _COMPLETE_STATUSES` where _COMPLETE_STATUSES = ("ia_verified", "accountant_confirmed", "completed", "closed") (:44). "completed" and "closed" carry no IA verification whatsoever. The item already carries the correct field — `ia_status` is populated from activity.ia_verification_status at :350 and :549 — and the fold simply never reads it. The platform's other implementation of this same question gets it right: /Users/omario/Developer/Edify Planning Tool/apps/planning/oversight_service.py:871-885 gates `awaiting_payment` on `i.ia_status == "confirmed"`. LIVE PROOF (psql edify_pm): 92 partner_activity + 138 partner-assigned school_visit rows sit at status='completed' with ia_verification_status='pending' and payment_status='none' — 230 activities that this tile reports to the reader as "verified and awaiting payment", of which zero are IA-verified. This is unverified work presented as verified, on a tile that drills through to the partner-payment queue.

### `impact_accepted_spend`

- **Implementation:** /Users/omario/Developer/Edify Planning Tool/apps/analytics/impact_engine.py:306-318 (_accepted_spend_by_activity), :224-231 and :265-280 (window), :459-521 (funding_impact)
- **Discrepancy:** Three separate breaks. (1) THE DECLARED SERVICE PATH DOES NOT EXIST. There is no `impact_analytics_dashboard` in apps/analytics/impact_engine.py — the function there is `build_dashboard` (:780); the real callable is apps.analytics.decision_engine.impact_analytics_dashboard (/Users/omario/Developer/Edify Planning Tool/apps/analytics/decision_engine.py:390-396), which is what the view actually imports (/Users/omario/Developer/Edify Planning Tool/apps/frontend/views/impact_views.py:16). registry.check() (registry.py:1790+) never resolves the dotted path, so the pointer that is supposed to make the number traceable is dead. I resolved all 16 distinct service paths by AST: three are broken — this one, apps.analytics.ssa_performance_service.ssa_performance_dashboard, and apps.my_plan.services.get_my_plan_context. (2) DATE BASIS IS WRONG. The spec declares EXECUTION_DATE; the service filters and attributes on planned_date only — impact_engine.py:229-231 (`planned_date__gt=lo, planned_date__lte=hi`) and :274-276 (per-school window comparison on act["planned_date"]). There is no execution-date column anywhere in this query. DateBasis's own docstring (apps/core/metrics/spec.py:60-66) names this precise confusion as the reason the enum exists. (3) SOURCE MODELS ARE WRONG. source_models names only activities.Activity, but every shilling comes from fund_requests.AdvanceRequest.accounted_amount and fund_requests.PartnerPayment.amount_paid (impact_engine.py:310-317); Activity is only the join key. Also stage-mixing: AdvanceRequest rows are restricted to ACCEPTED_ADVANCE_STATUSES=("accounted","reimbursed") — genuinely ACCOUNTED — while PartnerPayment rows are summed with no stage qualifier at all (a payment is DISBURSED money), so one tile declared ACCOUNTED sums two different finance stages.

### `my_plan_activities_planned_fy`

- **Implementation:** /Users/omario/Developer/Edify Planning Tool/apps/my_plan/services.py:672 (count) over the queryset built at :538-556
- **Discrepancy:** SCOPE IS NOT owner_ids, and the number it produces is provably wrong. The service builds staff_ids from resolve_user_scope().staff_ids, which is ONLY the StaffProfile id (apps/core/scoping.py:215, :506). The both-id-spaces fallback at services.py:547-551 fires only when that list is EMPTY, so any user who HAS a StaffProfile never matches activities stored under their User id — the exact id-space split the platform documents at apps/activities/services.py:98 and solved with owner_ids() (apps/core/scoping.py:902-922), the helper the spec names and the service never calls. Verified live against edify_pm: all 598 non-deleted activities belong to 46 users who each have a StaffProfile, and every one is stored under the User id. get_frontend_context(cceo17@edify.org, {'period':'fy','fy':'2026'}) returns planned_this_fy=0 while the owner_ids-scoped truth is 13 (same for cceo6, cceo7, pending.nancy.akello). Second, opposite defect on the same line: services.py:545-546 extends staff_ids with scope.supervised_staff_ids, so a Program Lead's "MY activities" tiles also count every supervised CCEO's work — the invariant the sibling function is test-guarded for (apps/my_plan/test_pl_my_plan_is_personal.py asserts zero team leakage, but only against my_plan.services.get(), not against get_frontend_context, which is what the page and all 8 tiles use). Third, the queryset excludes ('closed','cancelled','rejected') at :539-540 and applies every page filter (district/staff/activity_type/status/search q, :595-632) before the count, neither of which the spec declares (excluded_statuses is empty).

### `my_plan_activities_planned_week`

- **Implementation:** /Users/omario/Developer/Edify Planning Tool/apps/my_plan/services.py:657-662, date predicate at :47-58
- **Discrepancy:** Date basis AGREES exactly: _scheduled_in_range (services.py:55-58) is planned_date__range OR (planned_date IS NULL AND scheduled_date date in range) — the declared fallback. What does not agree: (a) the same scope defect as my_plan_activities_planned_fy — StaffProfile-id-only matching plus supervised-staff inclusion (services.py:544-546), which zeroes the tile for every user in the current database; (b) FIXED_CONTEXT is only true of the period — the count runs over `qs`, which has already been narrowed by fy, district, staff, activity_type, status and the free-text search (services.py:538, :595-632), so the tile moves when the user changes any filter other than the period, and reads 0 whenever a non-current FY is selected. FilterBehaviour.PARTIAL exists in the enum and is the honest value; (c) the undeclared exclusion of closed/cancelled/rejected (:539-540) means the tile answers "what have I got left this week", not "what am I committed to delivering this week". Note also that "current week" is the day-of-month block (1-7/8-14/15-21/22-28/29-end, services.py:36-44), not an ISO week — consistent with the page's own week filter, but the spec does not say so.

### `my_plan_activities_planned_month`

- **Implementation:** /Users/omario/Developer/Edify Planning Tool/apps/my_plan/services.py:663-670
- **Discrepancy:** Numerator and date basis agree (calendar-month range on planned_date with the scheduled_date fallback, computed from today rather than the selected month, so the fixed-period claim holds). The scope, undeclared-status-exclusion and partial-filter-behaviour defects described on my_plan_activities_planned_week apply identically — same queryset (services.py:538-556, :595-632), same zeroing in the live database.

### `my_plan_activities_planned_quarter`

- **Implementation:** /Users/omario/Developer/Edify Planning Tool/apps/my_plan/services.py:671
- **Discrepancy:** The numerator and the unusual basis agree exactly — qs.filter(quarter=get_quarter_for_date(today)), a stamp match, and the spec says so rather than hiding it (this is the one place the registry's honesty about a divergent basis is fully earned). It still inherits the family's scope defect (StaffProfile-id-only + supervised staff, services.py:544-546), the undeclared closed/cancelled/rejected exclusion (:539-540) and the partial rather than fixed filter behaviour.

### `my_plan_completion_readiness_pct`

- **Implementation:** /Users/omario/Developer/Edify Planning Tool/apps/my_plan/services.py:707-717 (numerator :708-710, denominator :707)
- **Discrepancy:** The numerator can never contain a 'closed' activity, even though the spec lists 'closed' first among included_statuses. ACTIVE_MY_PLAN_EXCLUDED_STATUSES = ('closed','cancelled','rejected') is subtracted from the base queryset at services.py:20 and :539-540, and COMPLETED_WORK_STATUSES (apps/core/activity_types.py:148-153) contains 'closed' — so the intersection is removed before :708 ever filters on it. The denominator is likewise not "all the user's activities planned within the same period": it drops closed/cancelled/rejected and every page filter (:595-632). Consequence: as a user's work reaches its terminal closed state it leaves numerator AND denominator together, so a person who has closed everything they planned gets NO_DATA ("nothing was planned") rather than 100% — the mirror image of the 0%-for-empty defect the spec's own note was written to prevent. Two things do agree: the ratio is built with MetricValue.ratio so 0/0 renders as an absence not a zero (:714), and the spec's cross-module claim that target credit uses a stricter set is accurate (apps/targets/my_targets.py:55 defines IA_VERIFIED_STATUSES = ('ia_verified','closed','accountant_confirmed') and additionally requires a Salesforce activity id at :606-613). Period is declared MONTH but is the selected period, and the family scope defect applies.

### `Target achievement family (Team Target Achievement, Monthly/Quarterly Targets Achieved, Staff On Track, Activity SF ID Compliance, Core Schools On Track, and the My Targets period cards)`

- **Implementation:** /Users/omario/Developer/Edify Planning Tool/apps/targets/team_targets.py:604-665 and :1040-1075 (hand-built KPI dicts); /Users/omario/Developer/Edify Planning Tool/apps/targets/my_targets.py:836 (MyTargetQueryService.get_page); consumed by /Users/omario/Developer/Edify Planning Tool/apps/frontend/views/staff_views.py:655 and :1262
- **Discrepancy:** The platform's most consequential numbers — the ones that decide whether a person is "On Track" or "High Risk" — are outside the registry entirely. They are built as raw {"key","label","value"} dicts (team_targets.py:604-665), the exact shape spec.py:1-24 was written to abolish, with no key, no declared denominator, no date_basis and no drilldown contract. Two consequences are already visible in the code: (1) the strip carries two different mathematics under near-identical labels — "Team Target Achievement" is a weighted average of each member's per-area percentage (team_wpct, team_targets.py:471-509 via weighted_period_pct at my_targets.py:315-348) while "Monthly Targets Achieved" is a pooled achieved/target ratio (raw_pct, team_targets.py:494-502); a reader cannot tell them apart. (2) empty denominators are rendered as real-looking numbers, which the registry layer forbids: raw_pct returns 0% when no target is set (team_targets.py:501) and sf_compliance returns 100% with a success tone when nothing required a Salesforce id (team_targets.py:541) — both contradict apps/core/metrics/ratio.py:19-24 and the MetricValue.ratio contract these same numbers would have inherited under a spec.

### `ACHIEVED_STATUSES / "achieved" in PerformanceService (staff performance API: /api/performance/my-targets, team-targets, country-targets, hr/staff, drilldown)`

- **Implementation:** /Users/omario/Developer/Edify Planning Tool/apps/targets/performance.py:39 (ACHIEVED_STATUSES), used at :46-95 and :148-196
- **Discrepancy:** The declared tuple and the real tuple differ in both directions: ACHIEVED_STATUSES = ("ia_verified", "closed", "accountant_confirmed") — 'completed' is NOT in it (the docstring names it twice), and 'closed' is in it undocumented. By the module's own account partner activities terminate at 'completed', so every partner-delivered activity scores zero in partner_activities_supervised (:172-174) and in total_completed (:175), while the completion_rate at :475-481 divides that suppressed numerator by total_planned (an unfiltered Count of everything in the window) and reports the result as a staff performance percentage. This is the failure mode the audit brief names, inverted: the definition promises the looser status set and the query applies the stricter one, so genuinely finished work is reported as not done.

### `ssa_high_risk_schools`

- **Implementation:** apps/analytics/ssa_performance_service.py:281-297 (is_high_risk), :304 (fold), :28 (HIGH_RISK_SCORE=4.0)
- **Discrepancy:** The flag is `minimum_score < 4.0` where minimum_score is the school's WEAKEST SINGLE INTERVENTION score (min over SsaScore rows, line 281-286), not the record's average. A school averaging 8.0 with one intervention at 3.5 is counted as High-Risk. Measured on edify_pm, FY2026 latest confirmed records: 9,635 of 15,606 schools flagged by weakest-intervention vs 3,148 by average — a 3.1x overstatement of the tile the CD uses to target urgent intervention. The tile helper even prints "below 4.0" as if it were the average.

### `partner_oversight_payment_pending`

- **Implementation:** apps/planning/partner_oversight_service.py:743-750, with _COMPLETE_STATUSES at :44
- **Discrepancy:** Two independent mismatches. (a) The "verified" test is `activity_status in ("ia_verified","accountant_confirmed","completed","closed")`; apps/core/activity_types.py:137-153 documents "completed" as a status NO production transition writes and which is explicitly NOT IA-verified (it survives only on legacy/seeded rows) — so unverified work is reported as verified-and-payable, the exact defect the registry law names. (b) The "unpaid" test is `payment_status in ("", "none", "pending")`; "pending" is not a PaymentStatus member at all (apps/core/enums.py:381-393) and the real in-flight-but-unpaid states (ia_confirmed, pl_approval_required, pl_approved, accountant_cleared) are all excluded, so work genuinely sitting in the accountant's queue drops off the tile. The accountant's own payable queue uses PARTNER_PAYABLE_STATUSES = ("none","ia_confirmed") with status="ia_verified" (apps/fund_requests/finance_services.py:52; apps/fund_requests/disbursement_dashboard_service.py:526-534), so the two surfaces disagree in both directions.

### `bt_positive_impact`

- **Implementation:** apps/business_transformation/services.py:1621-1634 (counts), :1694-1700 (payload), :1804-1815 (tile)
- **Discrepancy:** Both numerator and denominator are computed from the denormalised column MfiLoan.impact_status (models.py:397-402, default not_due). Nothing in the codebase ever WRITES that column — a grep across apps/ returns only reads and filters (services.py:1430-1431, 1622, 1628, 2565-2566, 2711); register_or_update_loan's `values` dict (services.py:742-774) does not include it and no signal or handler sets it. The declared source LoanImpactAssessment (models.py:757-786, which carries `classification` and IA verification via `ia_status`) is read only by impact_reports_context (services.py:2387) and never by the metric. Consequence: a loan with a completed, IA-verified impact assessment still counts as unassessed, so the denominator is structurally pinned at 0 and the tile renders as permanent no-data. Local DB confirms the shape: 0 of 2 loans have impact_status <> 'not_due' and bt_loan_impact_assessment is empty. Secondary: the denominator `exclude(not_due, baseline_required, due, under_review)` counts INSUFFICIENT_EVIDENCE as a "completed impact assessment".

### `core-school KPI strip (Total Core Schools, Core Schools Ready for Planning, Avg. Core Assessment Score, Visits Scheduled, Trainings Scheduled, Staff vs Partner Performance Delta, Regions Covered)`

- **Implementation:** apps/frontend/views/core_schools_views.py:196-249 (raw dicts), values computed at :137-194
- **Discrepancy:** All seven Core Schools tiles are built as raw {"label": ..., "value": ...} dicts in the view — the exact anti-pattern the registry docstring (registry.py:1-12) says a metric may never be added by. None carries a key, definition, denominator, date basis, drill-down or data state, so there is nothing for the traceability law to check them against and nothing stopping a second page recomputing them differently. The Core Schools page is the largest registry blind spot found in this pass.

## Medium (22)

### `work_plan_plan_derived_budget`

- **Implementation:** /Users/omario/Developer/Edify Planning Tool/apps/frontend/views/work_plan_page.py:405-414 (rendered at :593-597)
- **Discrepancy:** The numerator says "cost lines dated within the selected period"; the service sums every cost line of every activity whose window touches the period, with no line-level date test: `for line in cost_lines: activity_period_cost += amount` (:406-413) then `period_budget += activity_period_cost` (:414). The band placement three lines above does apply the line's own date (`line_month`, :408-411) — so the month bands underneath the tile and the tile itself are computed on two different bases and can disagree on the same page. Compounding it, _window_q (:116-127) admits `Q(planned_date__lt=start, end_date__gte=start)`, so a multi-day activity starting 28 Sep and ending 3 Oct contributes 100% of its cost to BOTH September's and October's Plan-Derived Budget. Also latent: the metric is the only PLANNED-stage money figure that does not require a scheduled activity — budget_workspace requires `activity__scheduled_date__isnull=False` (/Users/omario/Developer/Edify Planning Tool/apps/budget/services.py:922-928) and work_plan_page does not, so the two PLANNED totals for one month are not reconcilable by definition. Additionally, when the reader sets the status filter the exclusion at :254-257 is skipped entirely, so selecting status=cancelled makes this money tile sum cancelled work. Currently masked: the dev DB has 0 rows where a line's planned_date differs from its activity's.

### `fund_request_monthly_admin_budget`

- **Implementation:** /Users/omario/Developer/Edify Planning Tool/apps/budget/services.py:934-940 and :1128-1171, consumed at /Users/omario/Developer/Edify Planning Tool/apps/frontend/views/budget_views.py:788-799
- **Discrepancy:** source_models is wrong for the dominant path. The spec names only activities.ActivityScheduleCostLine, but the admin bucket is built from monthly_work_plan.AdminBudgetLine (services.py:936-940 `AdminBudgetLine.objects.filter(monthly_budget__fy=fy, status="active")`, summed at :1164-1171 from line.total_cost). Only the minority case — a costed programme activity with programme_activity_type=='admin' (services.py:1040) — comes from cost lines. Date basis is wrong for the same reason: admin lines have no planned_date and are placed by parsing `monthly_budget.month_key` into a month start (`_month_start_for_key`, services.py:787-792, applied at :1131-1132), i.e. a month key, not the declared PLANNED_DATE. Also the filter_behaviour=FILTERED declaration is not met — see fund_request_monthly_visits_budget; budget_views.py:779-787 forwards no district/staff/status filter.

### `partner_scheduled_activity_cost`

- **Implementation:** /Users/omario/Developer/Edify Planning Tool/apps/frontend/views/partner_views.py:268 and :377 (rendered at :471-475)
- **Discrepancy:** Two problems. (1) Wrong source of truth: `"cost": activity.est_cost_cents` (:268), summed at :377. Every other PLANNED money metric reads the canonical ActivityScheduleCostLine, and the codebase states why in two places — /Users/omario/Developer/Edify Planning Tool/apps/planning/oversight_service.py:504-511 ("Summed from ActivityScheduleCostLine rather than read from Activity.est_cost_cents so the page and the budget cannot disagree") and /Users/omario/Developer/Edify Planning Tool/apps/my_plan/services.py:1049-1057 ("Preferring the estimate first let a stale est_cost_cents mask the authoritative line total"). There is a dedicated drift detector for exactly this column at /Users/omario/Developer/Edify Planning Tool/apps/system_health/services.py:505-510, which is proof the platform expects it to go stale. It currently reconciles in the dev DB (est=UGX 9,400,000 = line total for partner-assigned activities), so this is latent, not live. (2) "Scheduled" is not enforced: every activity-derived row gets is_pending=False (:271) regardless of date, including rows whose status_label is literally "Awaiting schedule" (:245-246), and total_cost sums `scheduled_rows` = all non-pending rows (:374, :377). So undated partner activities' money is reported as scheduled partner cost, contradicting both the definition and date_basis=PLANNED_DATE.

### `bt_value_disbursed`

- **Implementation:** /Users/omario/Developer/Edify Planning Tool/apps/business_transformation/services.py:1555-1565 (rendered at :1731-1737)
- **Discrepancy:** Numerator and the MFI-confirmed gate agree exactly (`disbursement_confirmed_at__isnull=False`, Sum("disbursed_amount")). The date basis does not: the period window is applied to `disbursement_date` (:1557-1558), not to submission. The spec declares SUBMISSION_DATE, and DateBasis.DISBURSEMENT_DATE exists (apps/core/metrics/spec.py:74) and is the correct value — the sibling bt_new_loans genuinely uses submitted_at (:1668-1670), so the two tiles in the same strip are windowed on different dates while declaring the same one. Secondary: period=FINANCIAL_YEAR is declared, but _selected_period_bounds (:1452-1479) also honours quarter, month and custom windows, so the declared period is only the default.

### `bt_repaid_amount`

- **Implementation:** /Users/omario/Developer/Edify Planning Tool/apps/business_transformation/services.py:1616-1620 (rendered at :1754)
- **Discrepancy:** Numerator, source model and stage agree — Sum("amount_paid_during_period") over RepaymentSnapshot is genuinely a per-period delta, and the UniqueConstraint on (loan, as_of_date) (apps/business_transformation/models.py:565-568) prevents the same snapshot being counted twice. The date basis does not agree: the window is applied to `as_of_date` (:1618-1619), the MFI's reporting date on the snapshot, not to any submission date. DateBasis has no member for a snapshot-as-of date; SUBMISSION_DATE is simply the wrong label, and it also makes this tile look co-windowed with bt_new_loans (submitted_at) and bt_value_disbursed (disbursement_date) when all three use different dates.

### `partner_oversight_scheduled_budget`

- **Implementation:** /Users/omario/Developer/Edify Planning Tool/apps/planning/partner_oversight_service.py:742 (fold), :478-537 (_item_for), :415-435 (_cost_by_activity)
- **Discrepancy:** The scheduled/unscheduled split is honoured correctly (unscheduled items carry planned_cost=None and are excluded by is_scheduled, :114-124, :725, :742). The break is status: the assignment-derived path applies NO activity-status exclusion — _item_for sets stage=STAGE_SCHEDULED for any assignment with a scheduled_activity (:488-489) and takes its full cost (:499-502), so a partner activity that was cancelled, rejected or deferred still sums into a PLANNED money total. The same service excludes exactly those three statuses on its own assignment-less path 200 lines earlier (:294, as a hard-coded literal rather than the canonical NON_FUNDABLE_ACTIVITY_STATUSES at /Users/omario/Developer/Edify Planning Tool/apps/core/activity_types.py:162-166), and budget_workspace excludes them platform-wide (/Users/omario/Developer/Edify Planning Tool/apps/budget/services.py:928). So one cancelled partner activity is counted or not counted purely on whether a PartnerAssignment row points at it. Also _cost_by_activity (:429-431) sums every cost line of the activity with no line-date or fiscal_year restriction, so a re-dated line lands in its parent's period rather than its own (spec declares PLANNED_DATE). Latent: no cancelled/rejected/deferred rows in the current DB.

### `my_plan_visits_scheduled_period`

- **Implementation:** /Users/omario/Developer/Edify Planning Tool/apps/my_plan/services.py:674-692, window built at :637-654
- **Discrepancy:** The type list matches the canonical apps/core/activity_types.VISIT_TYPES member-for-member (all 15), so the numerator is right today — though it is retyped as string literals at services.py:675-691 instead of importing the constant, which is precisely what activity_types.py:21-23 forbids ("a metric that means two things needs two names"); the next enum member added will diverge silently. The declarations that do not hold: period is declared MONTH but the tile counts the SELECTED period, which defaults to week (apps/frontend/views/my_plan_views.py:78 passes period="week"); and date_basis PLANNED_DATE holds only for the week/month branches — for period=quarter the window is the stored `quarter` stamp, not a date at all (services.py:649-651), and for period=fy there is no date filter whatsoever (:652-654). One declared basis, three real ones. The family scope defect applies here too.

### `my_plan_trainings_scheduled_period`

- **Implementation:** /Users/omario/Developer/Edify Planning Tool/apps/my_plan/services.py:693-702
- **Discrepancy:** Numerator agrees — the six literals match canonical TRAINING_TYPES (apps/core/activity_types.py:65-72) exactly, again retyped rather than imported. Same declaration failures as my_plan_visits_scheduled_period: declared period MONTH against a window that is really the selected period (week by default), and declared PLANNED_DATE against a basis that becomes the `quarter` stamp or no date filter at all depending on the period selector (services.py:649-654). Same family scope defect.

### `my_plan_cluster_meetings_scheduled_period`

- **Implementation:** /Users/omario/Developer/Edify Planning Tool/apps/my_plan/services.py:703-705
- **Discrepancy:** Numerator agrees precisely, including the SSA-review member — ('cluster_meeting','cluster_meeting_ssa_review') equals canonical CLUSTER_MEETING_TYPES (apps/core/activity_types.py:75-78). Worth noting because two other engines disagree with it for the same concept (apps/targets/performance.py:41 counts only 'cluster_meeting'; apps/hr/performance_engine.py:174-181 likewise). Declaration failures identical to the other two period tiles: declared MONTH/PLANNED_DATE against a window that is the selected period and a basis that switches to the quarter stamp or to nothing (services.py:637-654). Same family scope defect.

### `MetricSpec.service traceability (all 8 my_plan metrics)`

- **Implementation:** /Users/omario/Developer/Edify Planning Tool/apps/my_plan/services.py:505 (the real entry point is get_frontend_context)
- **Discrepancy:** apps.my_plan.services.get_my_plan_context does not exist anywhere in the repository — grep returns only the eight registry lines that name it. The function that actually computes all eight tiles is get_frontend_context (services.py:505), imported under an alias by the page at apps/frontend/views/my_plan_views.py:15. Nothing in the codebase ever reads MetricSpec.service — not registry.check() (registry.py:1791-1821), not the guard tests (apps/core/tests/test_metric_registry.py), not apps/system_health/kpi_inventory.py — so the field that carries the "every number traces to a real query" law is itself unverified. I resolved all 16 distinct service paths against their modules: two more are also dangling — apps.analytics.ssa_performance_service.ssa_performance_dashboard and apps.analytics.impact_engine.impact_analytics_dashboard (both real entry points are named build_dashboard, at ssa_performance_service.py:215 and impact_engine.py:780). The remaining 13 resolve.

### `"Achieved" school visits / trainings / cluster meetings — cross-engine agreement`

- **Implementation:** /Users/omario/Developer/Edify Planning Tool/apps/targets/my_targets.py:616 vs /Users/omario/Developer/Edify Planning Tool/apps/targets/performance.py:141-147 vs /Users/omario/Developer/Edify Planning Tool/apps/hr/performance_engine.py:145-181
- **Discrepancy:** Three engines, three different numbers for the same words, and no registry entry to arbitrate. DATE BASIS: the ledger credits by planned_date (my_targets.py:616, and it drops rows with a null planned_date at :500) while PerformanceService narrows by scheduled_date (performance.py:141-147, "when the work happened") — the exact planned-vs-execution split DateBasis was created for (spec.py:59-65). EXTRA PREDICATES: the ledger credits on IA status + a Salesforce id (my_targets.py:606-613); PerformanceService additionally demands evidence_status='accepted' for visits and trainings (performance.py:52-70), so a verified visit whose evidence row is not 'accepted' is achieved on one page and not the other. VOCABULARY: "visits" is the canonical 15-member VISIT_TYPES in the ledger and in PerformanceService, but only ('school_visit','core_visit') in the HR appraisal engine (performance_engine.py:145-158, labelled "Verified direct school visits" at :35) — a CCEO's coaching, follow-up and in-school-support visits earn target credit and no appraisal credit; "cluster meetings" is the canonical pair in the ledger but a single type in both performance engines (performance.py:41, performance_engine.py:174-181); "trainings" in the HR engine omits cluster_training_ssa_collection (performance_engine.py:159-173).

### `Milestone planned output vs verified achievement (Uganda Master priority cascade)`

- **Implementation:** /Users/omario/Developer/Edify Planning Tool/apps/hr/target_distribution.py:63-78 (PLANNED_OUTPUT_STATUSES, applied at :1217) and /Users/omario/Developer/Edify Planning Tool/apps/hr/milestone_progress.py:19 (QUALIFYING_STATES, applied at :104 and :136)
- **Discrepancy:** The two sets are not a partition: status 'completed' is in neither. PLANNED_OUTPUT_STATUSES stops at 'awaiting_ia_verification'/'rescheduled' and QUALIFYING_STATES = {'ia_verified','accountant_confirmed','closed'}. 'completed' is the legacy status the platform deliberately keeps alive (apps/core/activity_types.py:144-153, apps/activities/services.py:78 "legacy staged rows created before this canonical path") — and it is the status of 598 of the 600 activities in edify_pm right now. Every one of those rows contributes to neither the milestone's planned output nor its verified achievement: the work is invisible to the cascade's four-figure view rather than sitting in one of its two buckets. Everything else I checked in this engine agrees with its declaration — apps/hr/performance_engine.py filters on IA_VERIFIED_STATUSES at :150, :168, :179, :199, :273, :343, :361, :389 exactly as its docstring at :7-9 promises, and partner-supported schools are credited through a separate metric (:196-206) rather than as direct execution, as the mandate note at :13-15 requires.

### `country_schools_ready_for_action`

- **Implementation:** apps/command_center/dashboard_service.py:122-125
- **Discrepancy:** Computed as the arithmetic complement of needing-attention: `schools_qs.exclude(planning_readiness__in=["requires_cluster","data_cleanup_required"])`. That admits 9 of the 11 PlanningReadiness states as "ready for action", including CLOSED, COST_CATALOGUE_REQUIRED, FINANCE_PENDING, AWAITING_IA and AWAITING_EVIDENCE — none of which can be planned. The canonical answer already exists: PlanningReadiness.planning_ready_values() (apps/core/enums.py:87-93 = ready_for_support_planning + ready_for_baseline_ssa), which the schools directory uses at apps/frontend/views/school_views.py:439-441. Structural tell: needing_attention + ready_for_action always equals every school in scope.

### `country_operational_health_rate`

- **Implementation:** apps/command_center/dashboard_service.py:128 (composite), :49-53 (ready_pct), :79-87 and :106-117 (target_achievement)
- **Discrepancy:** The composite is (ready_pct + target_achievement)/2. target_achievement is completed-vs-scheduled activities inside the CURRENT CALENDAR MONTH filtered on `scheduled_date__date__range` — a time-bound component declared under NOT_TIME_BOUND/POINT_IN_TIME, and a calendar month rather than an FY month (the platform's FY runs Oct–Sep, apps/core/fy). The metric therefore moves on the 1st of each Gregorian month for reasons the spec says cannot exist. It also inherits the ready_pct complement defect above, since ready_pct (line 49-53) uses the same exclude()-based readiness.

### `partner_scheduled_activities`

- **Implementation:** apps/frontend/views/partner_views.py:271 ("is_pending": False hardcoded on every activity row), :374 (scheduled_rows), :460-465 (tile)
- **Discrepancy:** Activity rows are stamped `"is_pending": False` unconditionally, regardless of whether `planned_date`/`scheduled_date` exists, so `scheduled_rows = [row for row in all_rows if not row["is_pending"]]` counts dateless partner activities as Scheduled. The very same row renders with status_label "Awaiting schedule" (partner_views.py:239-247) two inches below the tile that just counted it as scheduled.

### `partner_activities_yet_to_schedule`

- **Implementation:** apps/frontend/views/partner_views.py:312 ("is_pending": True only on assignment rows), :375 (pending_rows), :466-471 (tile)
- **Discrepancy:** pending_rows can only ever contain PartnerAssignment-derived rows, because is_pending is True only in the assignment loop. An undated partner Activity — which the spec explicitly names as in scope — is never counted here (and is counted as Scheduled instead, see partner_scheduled_activities).

### `partner_high_risk_delays`

- **Implementation:** apps/frontend/views/partner_views.py:216-221 (local complete_statuses), :234-238 (activity overdue), :288-289 (assignment overdue), :376 (fold)
- **Discrepancy:** (a) The completeness test uses a view-local set {"completed","closed","ia_verified","payment_approved"} that omits `accountant_confirmed` — a real terminal status in COMPLETED_WORK_STATUSES (apps/core/activity_types.py:148-153) — and includes "payment_approved", which is not an ActivityStatus value at all (apps/core/enums.py:324-348). Accountant-confirmed, fully finished partner work past its date is therefore reported as a High-Risk Delay. The same view imports and uses COMPLETED_WORK_STATUSES correctly for the "overdue" status FILTER at :162-166, so clicking the filter and reading the tile give different sets. (b) Assignment rows at :288 are marked overdue purely on `scheduled_date < today` with no completeness test at all, and that date is the schedule-BY date, not a planned delivery date — so unscheduled handovers are counted here as well as in Yet-to-Schedule, and the metric mixes two date bases under a single PLANNED_DATE declaration.

### `bt_value_disbursed`

- **Implementation:** apps/business_transformation/services.py:1555-1565 (disbursed queryset), :1671 (valueDisbursed)
- **Discrepancy:** The period window is applied to `disbursement_date` (`disbursement_date__gte=fy_start.date(), __lt=fy_end.date()`), not to `submitted_at`. DateBasis.DISBURSEMENT_DATE exists in apps/core/metrics/spec.py:74 and is the correct member; SUBMISSION_DATE is used elsewhere in the same service for a genuinely different filter (`newLoans`, services.py:1668-1670 filters submitted_at). A loan submitted in Q1 and disbursed in Q2 falls in a different bucket than the spec promises, so bt_new_loans and bt_value_disbursed cannot be reconciled by a reader who trusts the declared basis.

### `bt_schools_financed`

- **Implementation:** apps/business_transformation/services.py:1560-1563 (schools=Count distinct over `disbursed`), :1676
- **Discrepancy:** Same mislabelled basis as bt_value_disbursed: the distinct count is taken over the disbursement-date-windowed set, not a submission-date one. Additionally the prose "Unique schools holding at least one disbursed MFI loan" reads as an all-time footprint while the number is period-bounded — a school financed in a prior FY silently leaves the count when the period control moves.

### `Core "Avg. Core Assessment Score"`

- **Implementation:** apps/core_schools/core_planning_services.py:1047-1061 (get_average_score) vs :1064-1090 (get_monthly_trend)
- **Discrepancy:** get_average_score takes the latest SsaRecord per school with NO verification_status filter, so pending/returned (unverified) assessments feed the headline score. The sibling method 17 lines below filters verification_status="confirmed" with the comment "Only verified assessments may drive the trend (methodology guardrail) — pending/returned records are not outcomes". The KPI and the trend line beneath it are therefore drawn from different populations. No live divergence today (0 of 1,411 core schools has an unverified latest record; both read 6.01) — it is a silent, data-dependent error waiting on the first pending upload.

### `Core "Visits Scheduled" / "Trainings Scheduled"`

- **Implementation:** apps/frontend/views/core_schools_views.py:170-193 (counts), :192 (total_target = total_core * 4)
- **Discrepancy:** Numerator excludes only status="cancelled", so `rejected` and `deferred` activities count as Scheduled — the platform's own NON_FUNDABLE_ACTIVITY_STATUSES (apps/core/activity_types.py:157-167) excludes all three, and the 2026-08-12 audit exists because that exact set disagreed across modules. Denominator hardcodes `total_core * 4` against apps/core_schools/services.py:57-64, which declares CORE_PACKAGE_SPEC the single source of truth for "every completion threshold — never hardcode"; it also counts core schools that have no CorePlan or slots for the FY, so the % complete is diluted by schools that were never planned.

### `/schools directory KPI strip (Total Schools, Client, Core, Unclustered, No SSA, Staff Required, Planning Ready, Duplicates)`

- **Implementation:** apps/frontend/views/school_views.py:455-518 (raw dicts), values at :428-447
- **Discrepancy:** Unregistered raw dicts, same anti-pattern as the Core Schools strip. Substantively, its "Planning Ready" tile uses the canonical PlanningReadiness.planning_ready_values() (school_views.py:439-441) while the registered country_schools_ready_for_action on the CD dashboard uses the complement of two blocked states — two different populations answering "ready" on two pages, which is precisely what the registry exists to prevent.

## Low (14)

### `fund_request_monthly_total`

- **Implementation:** /Users/omario/Developer/Edify Planning Tool/apps/frontend/views/budget_views.py:799 (`_band_workspace["total"]`) ← /Users/omario/Developer/Edify Planning Tool/apps/budget/services.py:1298
- **Discrepancy:** The arithmetic agrees: services.py:1298 returns selected_program_total + selected_admin_total, and because budget_views.py:791 forces every unknown table_kind into "standard", the four displayed components do sum to this total with nothing dropped. Two declaration breaks remain. (1) filter_behaviour=FILTERED is false: budget_views.py:779-787 forwards only period/fy/date/budget_scope to budget_workspace, so the band ignores the page's District, Staff, Request-type and Status filters (rendered at templates/partials/fund_requests/root.html:162-212) that _scoped_base_querysets applies at budget_views.py:139-151 to the KPI strip immediately above. Set a district and the two money bands on one page disagree with no indication why; PARTIAL is the honest declaration. (2) excluded_statuses=() is declared while the service excludes NON_FUNDABLE_ACTIVITY_STATUSES and requires a non-null scheduled_date (services.py:922-928).

### `fund_request_monthly_trainings_budget`

- **Implementation:** /Users/omario/Developer/Edify Planning Tool/apps/budget/services.py:1010-1017 and :1045-1046, consumed at /Users/omario/Developer/Edify Planning Tool/apps/frontend/views/budget_views.py:796
- **Discrepancy:** Numerator agrees: the inline training_types set (services.py:1010-1017) matches canonical TRAINING_TYPES (apps/core/activity_types.py:65-72) member for member, the window is planned_date-based (:978, :957), and non-fundable statuses are excluded (:928). Two lesser breaks. (1) filter_behaviour=FILTERED is not met — budget_views.py:779-787 forwards no district/staff/request-type/status filter, so this tile does not move when the reader filters the page. (2) The classification set is a local literal copy of a canonical tuple that exists precisely to stop copies drifting (activity_types.py module docstring, :1-24); a new training ActivityType added to the canonical tuple will silently fall into the "standard" bucket here and be reported as School Visits money.

### `fund_request_monthly_meetings_budget`

- **Implementation:** /Users/omario/Developer/Edify Planning Tool/apps/budget/services.py:1018 and :1043-1044, consumed at /Users/omario/Developer/Edify Planning Tool/apps/frontend/views/budget_views.py:797
- **Discrepancy:** Numerator agrees: meeting_types = {cluster_meeting, cluster_meeting_ssa_review} matches canonical CLUSTER_MEETING_TYPES (apps/core/activity_types.py:75-78) exactly, planned_date window, non-fundable statuses excluded. Same two lesser breaks as the trainings tile: filter_behaviour=FILTERED is not met (budget_views.py:779-787 forwards no page filters), and the type set is a local literal copy of the canonical tuple rather than a reference to it.

### `oversight_team_planned_budget`

- **Implementation:** /Users/omario/Developer/Edify Planning Tool/apps/planning/oversight_service.py:857 (fold), :504-521 (_cost_by_activity), :370-430 (_activities_in_scope)
- **Discrepancy:** Substantively agrees and is the best-behaved money metric of the set: it is a pure fold over the same items the table renders (:830-835), unscheduled partner assignments carry planned_cost=0 by explicit design (:678-684, :718), the scope arm matches (`responsible_staff_id | monitored_by_staff_id in team_ids`, :425-429), and the status allowlist LIVE_ACTIVITY_STATUSES (:40-60) excludes exactly cancelled/rejected/deferred/not_planned — equivalent to the canonical NON_FUNDABLE set (I diffed all 23 ActivityStatus members). One real gap: _cost_by_activity (:516-520) sums every cost line of an in-period activity with no line-level planned_date or fiscal_year restriction, while the activity itself is selected by fy/planned_month/quarter/planned_date (:414-423). A line re-dated out of the period, or a multi-month allocation, is therefore attributed to its parent activity's period rather than its own — which is not what date_basis=PLANNED_DATE declares. Currently masked: 0 rows in the DB where a line's planned_date differs from its activity's. Minor: excluded_statuses=() is declared while LIVE_ACTIVITY_STATUSES does exclude four statuses.

### `oversight_country_planned_budget`

- **Implementation:** /Users/omario/Developer/Edify Planning Tool/apps/planning/oversight_service.py:857, scope branch at :425-429, rendered at /Users/omario/Developer/Edify Planning Tool/apps/frontend/views/oversight_views.py:116-123
- **Discrepancy:** Same computation as the team figure with the scope narrowing skipped when scope.is_country (:425), which is exactly what "on the same basis as the team figure" and scope="Whole country" declare — so numerator, denominator, stage and scope all agree. It inherits the one gap noted on oversight_team_planned_budget: _cost_by_activity (:516-520) applies no line-level date or fiscal_year filter, so cost lines are periodised by their parent activity rather than by their own planned_date, which is not what date_basis=PLANNED_DATE says. Latent in current data.

### `ssa_* (all six) and impact_* (all four) — the `service` pointer itself`

- **Implementation:** apps/analytics/decision_engine.py:379 and :390 (the only definitions of those two symbols); the modules named in the registry expose build_dashboard instead
- **Discrepancy:** Neither declared dotted path resolves: ssa_performance_service.py and impact_engine.py define `build_dashboard`, and the named functions live on the decision_engine facade. A reader following the spec's one-service pointer finds nothing. A third pointer, apps.my_plan.services.get_my_plan_context, is likewise unresolvable. registry.check() (registry.py:~1780+) validates keys, labels and page placement but never imports or resolves `service`, so CI is green on all three.

### `ssa_completion_rate`

- **Implementation:** apps/analytics/ssa_performance_service.py:96 (School.objects.filter(deleted_at__isnull=True)), :300-302
- **Discrepancy:** The denominator is every non-deleted scoped school; there is no operational_status filter, so closed and suspended schools sit in it. The canonical helper exists — apps/schools/lifecycle_service.py:40-53 active_schools(), whose docstring names "coverage denominators" as its intended use — and School distinguishes deleted ("should never have existed") from closed ("was real and has ended") deliberately (apps/schools/models.py:150-167). No live impact today (all 16,988 rows are operational_status='active'), but the rate drops the first time a school is closed.

### `country_schools_needing_attention`

- **Implementation:** apps/command_center/dashboard_service.py:119-121
- **Discrepancy:** The numerator itself matches the (deliberately loose) definition: planning_readiness in [requires_cluster, data_cleanup_required]. The declared drill-down is dead — apps/frontend/views/school_views.py never reads a `readiness` query parameter (grep finds no GET handling for it; the view's filter set is region/district/type/ssa_status/owner), so clicking the tile lands on the unfiltered directory and the number cannot be traced through to its rows.

### `partner_oversight_yet_to_schedule`

- **Implementation:** apps/planning/partner_oversight_service.py:724 and :735 (fold), :486-497 (stage), :367-379 (_assignment_fy)
- **Discrepancy:** Numerator is correct (stage == awaiting_schedule). The declared PLANNED_DATE basis is unachievable for this population by construction: an unscheduled handover has no planned date, so _assignment_fy falls back to the schedule-BY date and then to created_at — a handover/record-created basis. The nearest honest members would be RECORD_CREATED or a due-date basis the enum does not yet have.

### `partner_oversight_needing_attention`

- **Implementation:** apps/planning/partner_risk_service.py:70-88 (detector list), apps/planning/partner_oversight_service.py:751 (at_risk fold), apps/frontend/views/oversight_views.py:974-980 (tile)
- **Discrepancy:** The fold counts any item with >=1 risk, and the detector list includes two conditions that are not live delivery problems: _schedule_approaching (partner_risk_service.py:115-130) fires when the deadline is up to 3 days AWAY — i.e. work that is on time — and _missing_rate (:175-192) flags a cost-catalogue gap owned by the Country Director, not partner delivery. "Partner Work Needing Attention" therefore includes handovers that are neither late nor stuck. Also note the spec's `service` names partner_risk_service.annotate while the displayed count is folded in partner_oversight_service.summarize:751.

### `bt_active_portfolio`

- **Implementation:** apps/business_transformation/services.py:1585-1615 (positioned/position), :1672
- **Discrepancy:** Numerator and finance stage are right (Sum of latest-snapshot outstanding_amount, restricted to status in [disbursed, active], matching "across active loans"). The declared NOTE is wrong: `positioned` is built from `loans` (services.py:1595), which `_selected_period_bounds` (:1452-1479) never touches — the period control narrows neither loans nor snapshots for this tile. The same applies to bt_amount_overdue and bt_defaulted_portfolio, which share the note's PARTIAL framing.

### `bt_repaid_amount`

- **Implementation:** apps/business_transformation/services.py:1616-1620, :1673
- **Discrepancy:** The window is applied to RepaymentSnapshot.as_of_date and the value summed is amount_paid_during_period — nothing to do with loan submission. SUBMISSION_DATE is the wrong member (the enum has no snapshot-as-of option; RECORD_CREATED would be nearer). Numerator itself matches the definition.

### `bt_use_verified`

- **Implementation:** apps/business_transformation/services.py:1576-1579 (due/verified), :1688-1692, :1785-1795 (tile)
- **Discrepancy:** Numerator and denominator agree: `due` is LoanVerificationRequirement with due_date <= today and `verified` is status=VERIFIED, which project_activity_state (services.py:1380-1393) writes only when the linked Activity reaches ia_verified/accountant_confirmed/closed AND a structured LoanUseResult exists — so "completed verification activity" is faithful, including the IA-verification gate. The declared date_basis is not: the population is defined by requirement.due_date, and no execution date is filtered anywhere. The DateBasis enum has no due-date member, so this is a spec-vocabulary gap rather than a query bug.

### `Core "Regions Covered"`

- **Implementation:** apps/frontend/views/core_schools_views.py:193-194, :250-256
- **Discrepancy:** Numerator is role-scoped (distinct regions of core_schools_qs) while the denominator is Region.objects.count() — every region in the deployment, unscoped and unfiltered. A PL whose portfolio sits in one region reads "1 / 12 · 8% coverage" for a portfolio that is 100% covered. Mixed scope inside one ratio, and no FilterBehaviour declaration exists to warn the reader because the tile is unregistered.
