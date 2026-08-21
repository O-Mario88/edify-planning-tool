"""The one inventory of every metric the platform is allowed to display.

Add a metric by adding one ``MetricSpec`` here and computing it in the one
service the spec names -- never by writing a fresh ``{"label": ..., "value":
...}`` dict in whichever view happens to need the number. That is how the
platform arrived at 281 KPI tiles built in 25 different key shapes, 21 labels
computed independently in more than one module, and one service reading two of
another's values by their *display labels*.

``check()`` is called by the guard tests. It is deliberately strict about the
things that were actually wrong rather than about style.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from apps.core.metrics.spec import (
    Category,
    DateBasis,
    FilterBehaviour,
    FinanceStage,
    MetricSpec,
    Period,
    Unit,
)
from apps.core.metrics.reconciled_registry import RECONCILED_METRICS


# ── Labels that describe nothing ─────────────────────────────────────────────
# Section 10 of the KPI mandate. "Budget" was in use for requested, approved and
# disbursed money; "Pending" for three unrelated queues. A label that needs the
# reader to guess which one it means is a defect, not a shorthand.
AMBIGUOUS_LABELS = frozenset(
    {
        "actual",
        "amount",
        "budget",
        "coverage",
        "count",
        "overall",
        "pending",
        "performance",
        "progress",
        "rate",
        "score",
        "status",
        "summary",
        "total",
    }
)


METRIC_REGISTRY: tuple[MetricSpec, ...] = (
    # ── My Plan: the personal scheduled-work family ──────────────────────────
    # Owned by My Plan. `projects/my_plan_service.py` and
    # `command_center/dashboard_service.py` each built their own copies of
    # these four labels against a *different* date basis -- see the module
    # docstring of apps/core/metrics/__init__.py for the divergence.
    MetricSpec(
        key="my_plan_activities_planned_week",
        label="My Activities Planned This Week",
        definition=(
            "Activities owned by the signed-in user whose planned date falls in "
            "the current week. Legacy rows with no planned date fall back to "
            "their scheduled timestamp so imported records stay visible."
        ),
        question="What am I committed to delivering this week?",
        category=Category.SCALE,
        unit=Unit.COUNT,
        service="apps.my_plan.services.get_my_plan_context",
        source_models=("activities.Activity",),
        numerator="Activities owned by the user, planned within the current week",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.WEEK,
        scope="Signed-in user's own activities (apps.core.scoping.owner_ids)",
        owner_page="my_plan",
        filter_behaviour=FilterBehaviour.FIXED_CONTEXT,
        drilldown="my_plan",
        refresh_events=("activity_scheduled", "activity_rescheduled"),
        notes="Fixed context: the tile always means *this* week, never the filtered period.",
    ),
    MetricSpec(
        key="my_plan_activities_planned_month",
        label="My Activities Planned This Month",
        definition=(
            "Activities owned by the signed-in user whose planned date falls in "
            "the current calendar month, with the same legacy fallback."
        ),
        question="How loaded is my month?",
        category=Category.SCALE,
        unit=Unit.COUNT,
        service="apps.my_plan.services.get_my_plan_context",
        source_models=("activities.Activity",),
        numerator="Activities owned by the user, planned within the current month",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.MONTH,
        scope="Signed-in user's own activities",
        owner_page="my_plan",
        filter_behaviour=FilterBehaviour.FIXED_CONTEXT,
        drilldown="my_plan",
        refresh_events=("activity_scheduled", "activity_rescheduled"),
    ),
    MetricSpec(
        key="my_plan_activities_planned_quarter",
        label="My Activities Planned This Quarter",
        definition=(
            "Activities owned by the signed-in user stamped with the current "
            "financial quarter. Note the basis differs from the week and month "
            "tiles: this reads the stored `quarter` field rather than a date "
            "range, so a row with a mis-stamped quarter is counted by its stamp."
        ),
        question="How loaded is my quarter?",
        category=Category.SCALE,
        unit=Unit.COUNT,
        service="apps.my_plan.services.get_my_plan_context",
        source_models=("activities.Activity",),
        numerator="Activities owned by the user stamped with the current quarter",
        # Declared honestly: this genuinely is not a planned-date filter.
        date_basis=DateBasis.NOT_TIME_BOUND,
        period=Period.QUARTER,
        scope="Signed-in user's own activities",
        owner_page="my_plan",
        filter_behaviour=FilterBehaviour.FIXED_CONTEXT,
        drilldown="my_plan",
        refresh_events=("activity_scheduled", "activity_rescheduled"),
        notes=(
            "Basis divergence from the week/month tiles is recorded here rather "
            "than hidden; reconciling it needs a data-repair pass over `quarter`."
        ),
    ),
    MetricSpec(
        key="my_plan_activities_planned_fy",
        label="My Activities Planned This Financial Year",
        definition=(
            "Every activity owned by the signed-in user within the selected "
            "financial year. The FY narrowing comes from the page's FY scope, "
            "not from a date filter on the tile."
        ),
        question="What is my whole-year commitment?",
        category=Category.SCALE,
        unit=Unit.COUNT,
        service="apps.my_plan.services.get_my_plan_context",
        source_models=("activities.Activity",),
        numerator="All in-scope activities owned by the user for the FY",
        date_basis=DateBasis.NOT_TIME_BOUND,
        period=Period.FINANCIAL_YEAR,
        scope="Signed-in user's own activities, FY-scoped by the page",
        owner_page="my_plan",
        filter_behaviour=FilterBehaviour.FIXED_CONTEXT,
        drilldown="my_plan",
        refresh_events=("activity_scheduled",),
    ),
    # These three narrow to the *selected* period (`qs_period`), unlike the
    # four tiles above, which always describe the current week/month/quarter/FY
    # regardless of the filter. Same strip, two filter behaviours -- declared
    # here so the difference is visible rather than surprising.
    MetricSpec(
        key="my_plan_visits_scheduled_period",
        label="School Visits Scheduled This Period",
        definition=(
            "Activities of a school-visit type owned by the user within the "
            "selected period."
        ),
        question="How much of my selected period is school contact?",
        category=Category.SCALE,
        unit=Unit.COUNT,
        service="apps.my_plan.services.get_my_plan_context",
        source_models=("activities.Activity",),
        numerator="Visit-type activities owned by the user in the period",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.MONTH,
        scope="Signed-in user's own activities, narrowed to the selected period",
        owner_page="my_plan",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="my_plan",
        refresh_events=("activity_scheduled",),
    ),
    MetricSpec(
        key="my_plan_trainings_scheduled_period",
        label="Trainings Scheduled This Period",
        definition=(
            "Activities of a training type owned by the user within the "
            "selected period."
        ),
        question="How much of my selected period is training delivery?",
        category=Category.SCALE,
        unit=Unit.COUNT,
        service="apps.my_plan.services.get_my_plan_context",
        source_models=("activities.Activity",),
        numerator="Training-type activities owned by the user in the period",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.MONTH,
        scope="Signed-in user's own activities, narrowed to the selected period",
        owner_page="my_plan",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="my_plan",
        refresh_events=("activity_scheduled",),
    ),
    MetricSpec(
        key="my_plan_cluster_meetings_scheduled_period",
        label="Cluster Meetings Scheduled This Period",
        definition=(
            "Cluster meeting and cluster SSA review activities owned by the "
            "user within the selected period."
        ),
        question="How much of my selected period is cluster convening?",
        category=Category.SCALE,
        unit=Unit.COUNT,
        service="apps.my_plan.services.get_my_plan_context",
        source_models=("activities.Activity",),
        numerator="Cluster meeting activities owned by the user in the period",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.MONTH,
        scope="Signed-in user's own activities, narrowed to the selected period",
        owner_page="my_plan",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="my_plan",
        refresh_events=("activity_scheduled",),
    ),
    MetricSpec(
        key="my_plan_completion_readiness_pct",
        label="My Completed Share of Planned Work",
        definition=(
            "Share of the user's activities in the selected period that have "
            "reached a completed work status. Uses "
            "apps.core.activity_types.COMPLETED_WORK_STATUSES, which includes "
            "the legacy 'completed' value; target *credit* deliberately uses a "
            "stricter set (targets.my_targets.IA_VERIFIED_STATUSES)."
        ),
        question="Am I on track to finish what I planned for this period?",
        category=Category.PROGRESS,
        unit=Unit.PERCENT,
        service="apps.my_plan.services.get_my_plan_context",
        source_models=("activities.Activity",),
        numerator="Activities in COMPLETED_WORK_STATUSES within the period",
        denominator="All the user's activities planned within the same period",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.MONTH,
        scope="Signed-in user's own activities",
        included_statuses=(
            "ia_verified",
            "closed",
            "accountant_confirmed",
            "completed",
        ),
        owner_page="my_plan",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="my_plan",
        refresh_events=("activity_closed", "activity_ia_verified"),
        notes=(
            "Renamed from 'Completion Readiness', which named neither the "
            "numerator nor the period. An empty period is NO_DATA, not 0% -- "
            "the previous implementations both returned 0."
        ),
    ),
    # ── Upload Center ────────────────────────────────────────────────────────
    MetricSpec(
        key="uploads_awaiting_review",
        label="Awaiting Review",
        definition=(
            "Records in the Upload Center whose next action is a review: a "
            "staged import batch, or a document submitted and not yet approved."
        ),
        question="What is waiting on somebody to look at it?",
        category=Category.PENDING_ACTION,
        unit=Unit.COUNT,
        service="apps.documents.upload_center.UploadCenterService",
        source_models=(
            "documents.DocumentAsset",
            "schools.SchoolImportBatch",
            "schools.SSAImportBatch",
        ),
        numerator="Authorised rows whose next action is a review step",
        date_basis=DateBasis.RECORD_CREATED,
        period=Period.ALL_TIME,
        scope="Only the categories the viewer's role can see",
        owner_page="uploads",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="uploads",
        notes=(
            "Counted across adapters, so one number covers imports and "
            "documents rather than a tile per source."
        ),
    ),
    MetricSpec(
        key="uploads_documents_published",
        label="Published",
        definition="Documents in the library that are published or effective.",
        question="How much of the library is live?",
        category=Category.SCALE,
        unit=Unit.COUNT,
        service="apps.documents.upload_center.UploadCenterService",
        source_models=("documents.DocumentAsset",),
        numerator="DocumentAsset rows in a readable status",
        date_basis=DateBasis.RECORD_CREATED,
        period=Period.ALL_TIME,
        scope="Documents the viewer administers or is an audience for",
        owner_page="uploads",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="uploads",
    ),
    # ── Policy compliance ────────────────────────────────────────────────────
    MetricSpec(
        key="policy_acknowledgements_accepted",
        label="Accepted",
        definition=(
            "People who have agreed to the current version of a mandatory "
            "document, within the viewer's scope."
        ),
        question="Who has accepted the policies required of them?",
        category=Category.PROGRESS,
        unit=Unit.COUNT,
        service="apps.documents.compliance.PolicyComplianceService",
        source_models=("documents.DocumentAcknowledgement",),
        numerator="Acknowledgements in the agreed state",
        date_basis=DateBasis.RECORD_CREATED,
        period=Period.ALL_TIME,
        scope="HR: their remit · CD: their country · PL: supervised staff",
        owner_page="policy_compliance",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="policy_compliance",
        notes=(
            "Keyed on the version, so agreeing to v1 does not count as " "accepting v2."
        ),
    ),
    # ── Fund requests: the monthly summary band ─────────────────────────────
    # Five planned-money figures for the month the page has open. All PLANNED:
    # sums of ActivityScheduleCostLine for the selected month, before any
    # approval or disbursement -- naming the stage is what stops this band
    # disagreeing with a disbursement figure under the same word "budget".
    MetricSpec(
        key="fund_request_monthly_visits_budget",
        label="School Visits",
        definition=(
            "Planned school-visit spend for the selected month: the sum of schedule cost lines on visit activities planned in that month."
        ),
        question="How much of this month's plan is school visits?",
        category=Category.FINANCE,
        unit=Unit.MONEY_UGX,
        finance_stage=FinanceStage.PLANNED,
        service="apps.frontend.views.budget_views._build_fund_requests_context",
        source_models=("activities.ActivityScheduleCostLine",),
        numerator="Cost-line amounts on visit-type activities planned in the month",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.MONTH,
        scope=(
            "Role-dependent: CCEO own plan · PL supervised team · "
            "CD/Admin their monthly admin plan (switchable to country)"
        ),
        owner_page="fund_requests",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="fund_requests",
    ),
    MetricSpec(
        key="fund_request_monthly_trainings_budget",
        label="Cluster Trainings",
        definition=("Planned cluster-training spend for the selected month."),
        question="How much of this month's plan is trainings?",
        category=Category.FINANCE,
        unit=Unit.MONEY_UGX,
        finance_stage=FinanceStage.PLANNED,
        service="apps.frontend.views.budget_views._build_fund_requests_context",
        source_models=("activities.ActivityScheduleCostLine",),
        numerator="Cost-line amounts on training-type activities planned in the month",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.MONTH,
        scope=(
            "Role-dependent: CCEO own plan · PL supervised team · "
            "CD/Admin their monthly admin plan (switchable to country)"
        ),
        owner_page="fund_requests",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="fund_requests",
    ),
    MetricSpec(
        key="fund_request_monthly_meetings_budget",
        label="Cluster Meetings",
        definition=("Planned cluster-meeting spend for the selected month."),
        question="How much of this month's plan is cluster meetings?",
        category=Category.FINANCE,
        unit=Unit.MONEY_UGX,
        finance_stage=FinanceStage.PLANNED,
        service="apps.frontend.views.budget_views._build_fund_requests_context",
        source_models=("activities.ActivityScheduleCostLine",),
        numerator="Cost-line amounts on cluster-meeting activities planned in the month",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.MONTH,
        scope=(
            "Role-dependent: CCEO own plan · PL supervised team · "
            "CD/Admin their monthly admin plan (switchable to country)"
        ),
        owner_page="fund_requests",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="fund_requests",
    ),
    MetricSpec(
        key="fund_request_monthly_admin_budget",
        label="Admin Budget (for CD)",
        definition=(
            "Planned administrative spend for the selected month -- the CD's monthly admin plan lines, not field-activity costs."
        ),
        question="How much administrative money does this month's plan carry?",
        category=Category.FINANCE,
        unit=Unit.MONEY_UGX,
        finance_stage=FinanceStage.PLANNED,
        service="apps.frontend.views.budget_views._build_fund_requests_context",
        source_models=("activities.ActivityScheduleCostLine",),
        numerator="Admin budget lines for the month",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.MONTH,
        scope=(
            "Role-dependent: CCEO own plan · PL supervised team · "
            "CD/Admin their monthly admin plan (switchable to country)"
        ),
        owner_page="fund_requests",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="fund_requests",
    ),
    MetricSpec(
        key="fund_request_monthly_total",
        label="Total Monthly Request",
        definition=(
            "Everything the selected month's plan asks for: visits, trainings, meetings and admin together."
        ),
        question="What will this month's plan request in total?",
        category=Category.FINANCE,
        unit=Unit.MONEY_UGX,
        finance_stage=FinanceStage.PLANNED,
        service="apps.frontend.views.budget_views._build_fund_requests_context",
        source_models=("activities.ActivityScheduleCostLine",),
        numerator="Sum of the four monthly components",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.MONTH,
        scope=(
            "Role-dependent: CCEO own plan · PL supervised team · "
            "CD/Admin their monthly admin plan (switchable to country)"
        ),
        owner_page="fund_requests",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="fund_requests",
    ),
    MetricSpec(
        key="policy_acknowledgements_overdue",
        label="Overdue",
        definition=(
            "Pending acknowledgements whose due date has passed, within the "
            "viewer's scope."
        ),
        question="Who has run out of time to respond?",
        category=Category.RISK,
        unit=Unit.COUNT,
        service="apps.documents.compliance.PolicyComplianceService",
        source_models=("documents.DocumentAcknowledgement",),
        numerator="Pending acknowledgements with due_date in the past",
        date_basis=DateBasis.RECORD_CREATED,
        period=Period.ALL_TIME,
        scope="HR: their remit · CD: their country · PL: supervised staff",
        owner_page="policy_compliance",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="policy_compliance",
    ),
    # ── Work Plan (2026-07-30) ───────────────────────────────────────────────
    MetricSpec(
        key="work_plan_activities_planned",
        label="Activities Planned",
        definition=(
            "Live planned activities in the caller's authorized scope whose "
            "date falls in the selected Work Plan period. Cancelled, rejected "
            "and deferred work is excluded."
        ),
        question="How much work has been planned for this period?",
        category=Category.SCALE,
        unit=Unit.COUNT,
        service="apps.frontend.views.work_plan_page.build_work_plan_context",
        source_models=("activities.Activity",),
        numerator="Live activities dated within the selected period",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.MONTH,
        scope="Role-scoped Work Plan audience (own / supervised / country)",
        owner_page="work_plan",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="work_plan",
        refresh_events=("activity_scheduled", "activity_rescheduled"),
    ),
    MetricSpec(
        key="work_plan_activities_this_month",
        label="Activities This Month",
        definition=(
            "Live planned activities in scope dated in the current calendar "
            "month, regardless of which period the page is filtered to."
        ),
        question="What is actually landing this month?",
        category=Category.PROGRESS,
        unit=Unit.COUNT,
        service="apps.frontend.views.work_plan_page.build_work_plan_context",
        source_models=("activities.Activity",),
        numerator="Live activities dated in the current calendar month",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.MONTH,
        scope="Role-scoped Work Plan audience",
        owner_page="work_plan",
        filter_behaviour=FilterBehaviour.FIXED_CONTEXT,
        drilldown="work_plan",
        notes="Fixed context: always *this* month, never the filtered period.",
    ),
    MetricSpec(
        key="work_plan_plan_derived_budget",
        label="Plan-Derived Budget",
        definition=(
            "Sum of the canonical ActivityScheduleCostLine amounts belonging "
            "to the period's activities. Every shilling traces to a dated "
            "plan and a Cost Catalogue rate; nothing here is typed by hand."
        ),
        question="What will the planned work cost?",
        category=Category.FINANCE,
        unit=Unit.MONEY_UGX,
        finance_stage=FinanceStage.PLANNED,
        service="apps.frontend.views.work_plan_page.build_work_plan_context",
        source_models=("activities.ActivityScheduleCostLine",),
        numerator="Cost lines dated within the selected period",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.MONTH,
        scope="Role-scoped Work Plan audience",
        owner_page="work_plan",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="work_plan",
        refresh_events=("activity_scheduled", "activity_rescheduled"),
    ),
    MetricSpec(
        key="work_plan_pending_approval",
        label="Pending Approval",
        definition=(
            "Activities in the period whose weekly fund request is submitted "
            "and awaiting a PL or CD decision."
        ),
        question="What is waiting on an approver before money can move?",
        category=Category.PENDING_ACTION,
        unit=Unit.COUNT,
        service="apps.frontend.views.work_plan_page.build_work_plan_context",
        source_models=("fund_requests.WeeklyFundRequest",),
        numerator="Period activities carried by a submitted weekly request",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.MONTH,
        scope="Role-scoped Work Plan audience",
        owner_page="work_plan",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="work_plan",
    ),
    MetricSpec(
        key="work_plan_cost_setup_required",
        label="Cost Setup Required",
        definition=(
            "Activities in the period with no applicable Cost Catalogue rate. "
            "They may sit in draft planning but cannot enter a submitted fund "
            "request until the Country Director sets the missing rate."
        ),
        question="What cannot be funded until the CD configures a rate?",
        category=Category.QUALITY,
        unit=Unit.COUNT,
        service="apps.frontend.views.work_plan_page.build_work_plan_context",
        source_models=("activities.Activity",),
        numerator="Period activities flagged cost_missing",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.MONTH,
        scope="Role-scoped Work Plan audience",
        owner_page="work_plan",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="work_plan",
    ),
    MetricSpec(
        key="work_plan_activities_at_risk",
        label="Activities At Risk",
        definition=(
            "Activities whose planned date has passed while they are still "
            "scheduled or in progress — planned work that has not been "
            "completed or rescheduled."
        ),
        question="What has slipped its date without being dealt with?",
        category=Category.RISK,
        unit=Unit.COUNT,
        service="apps.frontend.views.work_plan_page.build_work_plan_context",
        source_models=("activities.Activity",),
        numerator="Period activities past their date, still open",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.MONTH,
        scope="Role-scoped Work Plan audience",
        owner_page="work_plan",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="work_plan",
    ),
    # ── Impact Assessment (2026-07-31) ───────────────────────────────────────
    # The six questions the IA verification command centre exists to answer.
    # Each one drills into the queue that resolves it; none of them restates
    # another, which is why the dashboard's previous "verified this week" and
    # "data quality" tiles are gone -- neither told IA what to do next.
    MetricSpec(
        key="ia_awaiting_verification",
        label="Awaiting IA Verification",
        definition=(
            "Activities submitted to Impact Assessment and still sitting in "
            "the queue. Work that has not yet been submitted is not counted: "
            "it is the field's to finish, not IA's to verify."
        ),
        question="What must I verify now?",
        category=Category.PENDING_ACTION,
        unit=Unit.COUNT,
        service="apps.frontend.views.ia_views.ia_dashboard_view",
        source_models=("activities.Activity",),
        numerator="Activities in status awaiting_ia_verification",
        date_basis=DateBasis.RECORD_CREATED,
        period=Period.ALL_TIME,
        scope="Country-wide: IA verifies for the whole deployment",
        owner_page="ia_verification",
        filter_behaviour=FilterBehaviour.FIXED_CONTEXT,
        drilldown="ia_verification",
        refresh_events=("activity_submitted_to_ia", "activity_verified"),
    ),
    MetricSpec(
        key="ia_evidence_ready_for_review",
        label="Evidence Ready for Review",
        definition=(
            "Uploaded evidence records that have cleared quarantine and are "
            "waiting on an IA decision. Quarantined files are excluded — they "
            "are a storage-safety state, not a review backlog."
        ),
        question="Which submissions have all required evidence?",
        category=Category.READINESS,
        unit=Unit.COUNT,
        service="apps.frontend.views.ia_views.ia_dashboard_view",
        source_models=("evidence.EvidenceRecord",),
        numerator="Evidence records with status uploaded, not quarantined",
        date_basis=DateBasis.RECORD_CREATED,
        period=Period.ALL_TIME,
        scope="Country-wide",
        owner_page="ia_verification",
        filter_behaviour=FilterBehaviour.FIXED_CONTEXT,
        drilldown="ia_verification",
    ),
    MetricSpec(
        key="ia_salesforce_verification_pending",
        label="Salesforce Verification Pending",
        definition=(
            "Reviewable activities carrying no Salesforce Activity ID. Without "
            "one the record cannot be reconciled downstream, so it is not yet "
            "eligible to clear even when its evidence is complete."
        ),
        question="Which Salesforce IDs require confirmation?",
        category=Category.COMPLIANCE,
        unit=Unit.COUNT,
        service="apps.frontend.views.ia_views.ia_dashboard_view",
        source_models=("activities.Activity",),
        numerator="Reviewable activities with a null or empty Salesforce ID",
        date_basis=DateBasis.RECORD_CREATED,
        period=Period.ALL_TIME,
        scope="Country-wide",
        owner_page="ia_verification",
        filter_behaviour=FilterBehaviour.FIXED_CONTEXT,
        drilldown="ia_verification",
    ),
    MetricSpec(
        key="ia_returned_for_correction",
        label="Returned for Correction",
        definition=(
            "Activities IA sent back and which the field has not yet "
            "resubmitted. This is IA's outstanding correction load, not a "
            "count of how many returns were issued."
        ),
        question="Which records have been returned and are still open?",
        category=Category.PROGRESS,
        unit=Unit.COUNT,
        service="apps.frontend.views.ia_views.ia_dashboard_view",
        source_models=("activities.Activity",),
        numerator="Activities in status returned_by_ia",
        date_basis=DateBasis.RECORD_CREATED,
        period=Period.ALL_TIME,
        scope="Country-wide",
        owner_page="ia_returned",
        filter_behaviour=FilterBehaviour.FIXED_CONTEXT,
        drilldown="ia_returned",
    ),
    MetricSpec(
        key="ia_unmatched_ssa_records",
        label="Unmatched SSA Records",
        definition=(
            "Imported SSA rows that could not be resolved to a school and are "
            "still pending or on hold. Until they are matched their scores "
            "belong to no school and enter no analytic."
        ),
        question="Which SSA records are unmatched or invalid?",
        category=Category.QUALITY,
        unit=Unit.COUNT,
        service="apps.frontend.views.ia_views.ia_dashboard_view",
        source_models=("schools.UnmatchedSSARecord",),
        numerator="Unmatched SSA rows in status pending or hold",
        date_basis=DateBasis.RECORD_CREATED,
        period=Period.ALL_TIME,
        scope="Country-wide",
        owner_page="ssa_unmatched",
        filter_behaviour=FilterBehaviour.FIXED_CONTEXT,
        drilldown="ssa_unmatched",
    ),
    MetricSpec(
        key="ia_verification_overdue",
        label="Verification Overdue",
        definition=(
            "Activities that have been waiting on IA for longer than the "
            "24-hour verification SLA, measured from the moment they entered "
            "the queue. A count, not a percentage: the SLA rate says how the "
            "week went, this says what is late right now."
        ),
        question="Which verification queues are aging beyond SLA?",
        category=Category.RISK,
        unit=Unit.COUNT,
        service="apps.frontend.views.ia_views.ia_dashboard_view",
        source_models=("activities.Activity",),
        numerator="Queued activities submitted to IA more than 24 hours ago",
        date_basis=DateBasis.RECORD_CREATED,
        period=Period.ALL_TIME,
        scope="Country-wide",
        owner_page="ia_verification",
        filter_behaviour=FilterBehaviour.FIXED_CONTEXT,
        drilldown="ia_verification",
        refresh_events=("activity_submitted_to_ia", "activity_verified"),
    ),
    # ── SSA performance ─────────────────────────────────────────────────────
    MetricSpec(
        key="ssa_schools_assessed",
        label="Total Schools Assessed",
        definition="Schools with a confirmed SSA in the selected financial quarter.",
        question="How much of the scoped school portfolio has a confirmed assessment?",
        category=Category.SCALE,
        unit=Unit.COUNT,
        service="apps.analytics.ssa_performance_service.ssa_performance_dashboard",
        source_models=("schools.School", "ssa.SsaRecord"),
        numerator="Distinct scoped schools with a confirmed SSA record",
        date_basis=DateBasis.SSA_ASSESSMENT_DATE,
        period=Period.QUARTER,
        scope="Role-scoped schools and selected FY quarter",
        owner_page="ssa_performance",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="ssa_performance",
    ),
    MetricSpec(
        key="ssa_completion_rate",
        label="SSA Completion Rate",
        definition="Share of scoped schools with a confirmed SSA in the selected quarter.",
        question="Is assessment coverage complete enough for reliable decisions?",
        category=Category.PROGRESS,
        unit=Unit.PERCENT,
        service="apps.analytics.ssa_performance_service.ssa_performance_dashboard",
        source_models=("schools.School", "ssa.SsaRecord"),
        numerator="Scoped schools with a confirmed SSA record",
        denominator="All active scoped schools",
        date_basis=DateBasis.SSA_ASSESSMENT_DATE,
        period=Period.QUARTER,
        scope="Role-scoped schools and selected FY quarter",
        owner_page="ssa_performance",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="ssa_performance",
    ),
    MetricSpec(
        key="ssa_districts_reporting",
        label="Districts Reporting SSA",
        definition="Districts containing at least one confirmed SSA in the selected quarter.",
        question="Which parts of the operating scope are contributing assessment evidence?",
        category=Category.CAPACITY,
        unit=Unit.COUNT,
        service="apps.analytics.ssa_performance_service.ssa_performance_dashboard",
        source_models=("schools.District", "ssa.SsaRecord"),
        numerator="Scoped districts with one or more confirmed SSA records",
        date_basis=DateBasis.SSA_ASSESSMENT_DATE,
        period=Period.QUARTER,
        scope="Role-scoped districts and selected FY quarter",
        owner_page="ssa_performance",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="ssa_performance",
    ),
    MetricSpec(
        key="ssa_average_score",
        label="Average SSA Score",
        definition="Mean confirmed SSA score across assessed schools in the selected quarter.",
        question="What is the current average school-improvement outcome?",
        category=Category.OUTCOME,
        unit=Unit.SCORE,
        service="apps.analytics.ssa_performance_service.ssa_performance_dashboard",
        source_models=("ssa.SsaRecord",),
        numerator="Sum of confirmed school average scores divided by assessed schools",
        date_basis=DateBasis.SSA_ASSESSMENT_DATE,
        period=Period.QUARTER,
        scope="Assessed role-scoped schools",
        owner_page="ssa_performance",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="ssa_performance",
    ),
    MetricSpec(
        key="ssa_high_risk_schools",
        label="High-Risk Schools",
        definition="Assessed schools whose confirmed average is below the governed risk threshold.",
        question="Which schools require the most urgent intervention?",
        category=Category.RISK,
        unit=Unit.COUNT,
        service="apps.analytics.ssa_performance_service.ssa_performance_dashboard",
        source_models=("schools.School", "ssa.SsaRecord"),
        numerator="Assessed schools below the SSA high-risk threshold",
        date_basis=DateBasis.SSA_ASSESSMENT_DATE,
        period=Period.QUARTER,
        scope="Assessed role-scoped schools",
        owner_page="ssa_performance",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="ssa_performance",
    ),
    MetricSpec(
        key="ssa_districts_below_target",
        label="Districts Below SSA Target",
        definition="Districts whose confirmed average SSA score is below the governed target.",
        question="Where is district-level support falling short of the target?",
        category=Category.READINESS,
        unit=Unit.COUNT,
        service="apps.analytics.ssa_performance_service.ssa_performance_dashboard",
        source_models=("schools.District", "ssa.SsaRecord"),
        numerator="Reporting districts below the SSA average target",
        date_basis=DateBasis.SSA_ASSESSMENT_DATE,
        period=Period.QUARTER,
        scope="Role-scoped reporting districts",
        owner_page="ssa_performance",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="ssa_performance",
    ),
    # ── Impact analytics ────────────────────────────────────────────────────
    MetricSpec(
        key="impact_schools_analysed",
        label="Schools Analysed for Impact",
        definition="Schools with confirmed SSA observations in both comparison cycles.",
        question="How large is the valid before-and-after evidence base?",
        category=Category.SCALE,
        unit=Unit.COUNT,
        service="apps.analytics.impact_engine.impact_analytics_dashboard",
        source_models=("schools.School", "ssa.SsaRecord"),
        numerator="Scoped schools paired across both SSA cycles",
        date_basis=DateBasis.SSA_ASSESSMENT_DATE,
        period=Period.FINANCIAL_YEAR,
        scope="Role-scoped schools with paired SSA cycles",
        owner_page="impact_analytics",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="impact_analytics",
    ),
    MetricSpec(
        key="impact_median_school_delta",
        label="Median School SSA Delta",
        definition="Median change in school SSA score between the selected and prior FY cycles.",
        question="Did the typical assessed school improve?",
        category=Category.OUTCOME,
        unit=Unit.SCORE,
        service="apps.analytics.impact_engine.impact_analytics_dashboard",
        source_models=("ssa.SsaRecord",),
        numerator="Median of paired school-level SSA score differences",
        date_basis=DateBasis.SSA_ASSESSMENT_DATE,
        period=Period.FINANCIAL_YEAR,
        scope="Role-scoped schools with paired SSA cycles",
        owner_page="impact_analytics",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="impact_analytics",
    ),
    MetricSpec(
        key="impact_schools_improved_rate",
        label="Schools Improved Rate",
        definition="Share of paired schools whose mean SSA score improved beyond the governed threshold.",
        question="How widespread is meaningful school improvement?",
        category=Category.PROGRESS,
        unit=Unit.PERCENT,
        service="apps.analytics.impact_engine.impact_analytics_dashboard",
        source_models=("schools.School", "ssa.SsaRecord"),
        numerator="Paired schools improving by more than the governed threshold",
        denominator="All role-scoped schools with paired SSA cycles",
        date_basis=DateBasis.SSA_ASSESSMENT_DATE,
        period=Period.FINANCIAL_YEAR,
        scope="Role-scoped schools with paired SSA cycles",
        owner_page="impact_analytics",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="impact_analytics",
    ),
    MetricSpec(
        key="impact_accepted_spend",
        label="Accepted Activity Spend",
        definition="Accepted activity cost associated with the impact-analysis window.",
        question="How much accepted spend sits behind the measured outcomes?",
        category=Category.FINANCE,
        unit=Unit.MONEY_UGX,
        service="apps.analytics.impact_engine.impact_analytics_dashboard",
        source_models=("activities.Activity",),
        numerator="Sum of accepted activity costs in the impact window",
        date_basis=DateBasis.EXECUTION_DATE,
        period=Period.FINANCIAL_YEAR,
        scope="Role-scoped impact-analysis activities",
        owner_page="impact_analytics",
        filter_behaviour=FilterBehaviour.FILTERED,
        finance_stage=FinanceStage.ACCOUNTED,
        drilldown="impact_analytics",
    ),
    # ── Partner operations ──────────────────────────────────────────────────
    MetricSpec(
        key="partner_total_partners",
        label="Partners in Current View",
        definition="Active partner records remaining after the current directory filters.",
        question="How many partners am I currently reviewing?",
        category=Category.SCALE,
        unit=Unit.COUNT,
        service="apps.frontend.views.partner_views.partners_list_view",
        source_models=("partners.Partner",),
        numerator="Partner records matching the current filters",
        date_basis=DateBasis.NOT_TIME_BOUND,
        period=Period.POINT_IN_TIME,
        scope="Role-scoped partner directory filters",
        owner_page="partners",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="partners",
    ),
    MetricSpec(
        key="partner_assigned_schools",
        label="Schools Assigned to Partners",
        definition="Distinct schools linked to a partner assignment or partner-led activity.",
        question="How much of the school portfolio has partner coverage?",
        category=Category.CAPACITY,
        unit=Unit.COUNT,
        service="apps.frontend.views.partner_views.partners_list_view",
        source_models=(
            "schools.School",
            "partners.PartnerAssignment",
            "activities.Activity",
        ),
        numerator="Distinct schools linked to the filtered partner workload",
        date_basis=DateBasis.NOT_TIME_BOUND,
        period=Period.POINT_IN_TIME,
        scope="Filtered partner workload",
        owner_page="partners",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="partners",
    ),
    MetricSpec(
        key="partner_scheduled_activities",
        label="Partner Activities Scheduled",
        definition="Partner assignments or activities carrying a scheduled delivery date.",
        question="How much partner work is ready to execute?",
        category=Category.READINESS,
        unit=Unit.COUNT,
        service="apps.frontend.views.partner_views.partners_list_view",
        source_models=("partners.PartnerAssignment", "activities.Activity"),
        numerator="Filtered partner work with a scheduled date",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.FINANCIAL_YEAR,
        scope="Filtered partner workload",
        owner_page="partners",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="partners",
    ),
    MetricSpec(
        key="partner_activities_yet_to_schedule",
        label="Partner Activities Yet to Schedule",
        definition="Partner assignments or activities that still have no delivery date.",
        question="What partner work still needs a date?",
        category=Category.PENDING_ACTION,
        unit=Unit.COUNT,
        service="apps.frontend.views.partner_views.partners_list_view",
        source_models=("partners.PartnerAssignment", "activities.Activity"),
        numerator="Filtered partner work without a scheduled date",
        date_basis=DateBasis.NOT_TIME_BOUND,
        period=Period.FINANCIAL_YEAR,
        scope="Filtered partner workload",
        owner_page="partners",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="partners",
    ),
    MetricSpec(
        key="partner_scheduled_activity_cost",
        label="Partner Scheduled Activity Cost",
        definition="Planned cost of the scheduled partner workload in the current filters.",
        question="What planned cost is attached to scheduled partner delivery?",
        category=Category.FINANCE,
        unit=Unit.MONEY_UGX,
        service="apps.frontend.views.partner_views.partners_list_view",
        source_models=("partners.PartnerAssignment", "activities.Activity"),
        numerator="Sum of planned costs for scheduled filtered partner work",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.FINANCIAL_YEAR,
        scope="Filtered partner workload",
        owner_page="partners",
        filter_behaviour=FilterBehaviour.FILTERED,
        finance_stage=FinanceStage.PLANNED,
        drilldown="partners",
    ),
    MetricSpec(
        key="partner_high_risk_delays",
        label="High-Risk Partner Delays",
        definition="Partner work whose scheduled date has passed without completion.",
        question="Which partner commitments require intervention now?",
        category=Category.RISK,
        unit=Unit.COUNT,
        service="apps.frontend.views.partner_views.partners_list_view",
        source_models=("partners.PartnerAssignment", "activities.Activity"),
        numerator="Filtered scheduled partner work overdue and incomplete",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.POINT_IN_TIME,
        scope="Filtered partner workload",
        owner_page="partners",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="partners",
    ),
    # ── Country and platform operations dashboards ──────────────────────────
    MetricSpec(
        key="country_schools_needing_attention",
        label="Schools Needing Attention",
        definition="Schools currently classified by dashboard signals as needing intervention.",
        question="Where should country leadership focus first?",
        category=Category.RISK,
        unit=Unit.COUNT,
        service="apps.command_center.dashboard_service.DashboardMetricsService",
        source_models=("schools.School",),
        numerator="Scoped schools classified as needing attention",
        date_basis=DateBasis.NOT_TIME_BOUND,
        period=Period.POINT_IN_TIME,
        scope="Country dashboard school scope",
        owner_page="dashboard",
        filter_behaviour=FilterBehaviour.FIXED_CONTEXT,
        drilldown="/schools?readiness=attention",
    ),
    MetricSpec(
        key="country_schools_ready_for_action",
        label="Schools Ready for Action",
        definition="Schools whose current data and planning state allow the next intervention action.",
        question="Which schools can move into planning now?",
        category=Category.READINESS,
        unit=Unit.COUNT,
        service="apps.command_center.dashboard_service.DashboardMetricsService",
        source_models=("schools.School",),
        numerator="Scoped schools classified as ready for action",
        date_basis=DateBasis.NOT_TIME_BOUND,
        period=Period.POINT_IN_TIME,
        scope="Country dashboard school scope",
        owner_page="dashboard",
        filter_behaviour=FilterBehaviour.FIXED_CONTEXT,
        drilldown="planning",
    ),
    MetricSpec(
        key="country_operational_health_rate",
        label="Country Operational Health Rate",
        definition="Composite governed score of current country operating health.",
        question="Is the country programme operating within its expected health envelope?",
        category=Category.QUALITY,
        unit=Unit.PERCENT,
        service="apps.command_center.dashboard_service.DashboardMetricsService",
        source_models=("schools.School", "activities.Activity"),
        numerator="Composite operational-health points achieved",
        denominator="Maximum composite operational-health points",
        date_basis=DateBasis.NOT_TIME_BOUND,
        period=Period.POINT_IN_TIME,
        scope="Country dashboard operational scope",
        owner_page="dashboard",
        filter_behaviour=FilterBehaviour.FIXED_CONTEXT,
        drilldown="system_health",
    ),
    MetricSpec(
        key="admin_critical_incidents",
        label="Critical Incidents",
        definition="Open platform incidents carrying critical severity.",
        question="Which platform failures require immediate response?",
        category=Category.RISK,
        unit=Unit.COUNT,
        service="apps.admin_ops.services.AdminOpsDashboardService.summary",
        source_models=("admin_ops.SystemIncident",),
        numerator="Open incidents with critical severity",
        date_basis=DateBasis.RECORD_CREATED,
        period=Period.POINT_IN_TIME,
        scope="Platform operations",
        owner_page="admin_dashboard",
        filter_behaviour=FilterBehaviour.FIXED_CONTEXT,
        drilldown="/admin-ops/incidents",
    ),
    MetricSpec(
        key="admin_open_support_tickets",
        label="Open Platform Support Tickets",
        definition="Support tickets that have not reached a closed state.",
        question="What user-reported work remains unresolved?",
        category=Category.PENDING_ACTION,
        unit=Unit.COUNT,
        service="apps.admin_ops.services.AdminOpsDashboardService.summary",
        source_models=("admin_ops.SupportTicket",),
        numerator="Support tickets in an open state",
        date_basis=DateBasis.RECORD_CREATED,
        period=Period.POINT_IN_TIME,
        scope="Platform operations",
        owner_page="admin_dashboard",
        filter_behaviour=FilterBehaviour.FIXED_CONTEXT,
        drilldown="/admin-ops/support",
    ),
    MetricSpec(
        key="admin_overdue_work",
        label="Overdue Admin Work",
        definition="Open administrative work items whose due date has passed.",
        question="Which admin commitments have breached their due date?",
        category=Category.COMPLIANCE,
        unit=Unit.COUNT,
        service="apps.admin_ops.services.AdminOpsDashboardService.summary",
        source_models=("admin_ops.AdminOperationsWorkItem",),
        numerator="Open admin work items past due",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.POINT_IN_TIME,
        scope="Platform operations",
        owner_page="admin_dashboard",
        filter_behaviour=FilterBehaviour.FIXED_CONTEXT,
        drilldown="/admin-ops/my-plan",
    ),
    MetricSpec(
        key="admin_background_job_incidents",
        label="Background Job Incidents",
        definition="Open incidents raised for failed or overdue scheduled jobs.",
        question="Which background processes need operator attention?",
        category=Category.QUALITY,
        unit=Unit.COUNT,
        service="apps.admin_ops.services.AdminOpsDashboardService.summary",
        source_models=("admin_ops.SystemIncident",),
        numerator="Open incidents classified as background-job failures",
        date_basis=DateBasis.RECORD_CREATED,
        period=Period.POINT_IN_TIME,
        scope="Platform operations",
        owner_page="admin_dashboard",
        filter_behaviour=FilterBehaviour.FIXED_CONTEXT,
        drilldown="/admin-ops/incidents",
    ),
    MetricSpec(
        key="admin_unhealthy_routes",
        label="Slow or Unhealthy Routes",
        definition="Open route-performance incidents representing an SLO breach.",
        question="Which user journeys are currently outside performance objectives?",
        category=Category.OUTCOME,
        unit=Unit.COUNT,
        service="apps.admin_ops.services.AdminOpsDashboardService.summary",
        source_models=("admin_ops.SystemIncident",),
        numerator="Open route incidents classified as performance or SLO breaches",
        date_basis=DateBasis.RECORD_CREATED,
        period=Period.POINT_IN_TIME,
        scope="Platform operations",
        owner_page="admin_dashboard",
        filter_behaviour=FilterBehaviour.FIXED_CONTEXT,
        drilldown="/admin-ops/incidents",
    ),
    MetricSpec(
        key="admin_security_alerts",
        label="Open Security Alerts",
        definition="Open incidents classified as security alerts.",
        question="Which security conditions remain unresolved?",
        category=Category.READINESS,
        unit=Unit.COUNT,
        service="apps.admin_ops.services.AdminOpsDashboardService.summary",
        source_models=("admin_ops.SystemIncident",),
        numerator="Open incidents classified as security alerts",
        date_basis=DateBasis.RECORD_CREATED,
        period=Period.POINT_IN_TIME,
        scope="Platform operations",
        owner_page="admin_dashboard",
        filter_behaviour=FilterBehaviour.FIXED_CONTEXT,
        drilldown="/admin-ops/incidents",
    ),
    MetricSpec(
        key="admin_maintenance_due",
        label="Platform Maintenance Due",
        definition="Governed maintenance templates at or beyond their next due date.",
        question="What preventative platform maintenance is due now?",
        category=Category.CAPACITY,
        unit=Unit.COUNT,
        service="apps.admin_ops.services.AdminOpsDashboardService.summary",
        source_models=("admin_ops.MaintenanceTemplate",),
        numerator="Maintenance templates at or past their due date",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.POINT_IN_TIME,
        scope="Platform operations",
        owner_page="admin_dashboard",
        filter_behaviour=FilterBehaviour.FIXED_CONTEXT,
        drilldown="/admin-ops/maintenance",
    ),
    # ── Planning oversight: the supervision lenses ───────────────────────────
    # Team and country are separate entries rather than one metric with two
    # labels, because they are different numbers over different scopes. One
    # spec with a scope that changes per caller is how "planned activities"
    # came to mean three things.
    MetricSpec(
        key="oversight_team_activities_planned",
        label="Team Activities Planned",
        definition=(
            "Every activity planned in the period by the Program Lead or any "
            "CCEO they supervise, plus every partner handover their team owns "
            "that no partner has scheduled yet."
        ),
        question="What has my team committed to this period?",
        category=Category.SCALE,
        unit=Unit.COUNT,
        service="apps.planning.oversight_service.summarize",
        source_models=("activities.Activity", "partners.PartnerAssignment"),
        numerator="Planned activities plus unscheduled partner handovers in scope",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.FINANCIAL_YEAR,
        scope="The Program Lead's own work and their supervisees'",
        owner_page="team_planning_oversight",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="/team-planning-oversight/",
        refresh_events=("activity_scheduled", "partner_assignment_created"),
    ),
    MetricSpec(
        key="oversight_country_activities_planned",
        label="Country Planned Activities",
        definition=(
            "Every activity planned in the period anywhere in the country, "
            "plus every partner handover no partner has scheduled yet."
        ),
        question="What has the country committed to this period?",
        category=Category.SCALE,
        unit=Unit.COUNT,
        service="apps.planning.oversight_service.summarize",
        source_models=("activities.Activity", "partners.PartnerAssignment"),
        numerator="Planned activities plus unscheduled partner handovers, country-wide",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.FINANCIAL_YEAR,
        scope="Whole country",
        owner_page="country_planning_oversight",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="/country-planning-oversight/",
        refresh_events=("activity_scheduled", "partner_assignment_created"),
    ),
    MetricSpec(
        key="oversight_partner_awaiting_schedule",
        label="Partner Awaiting Schedule",
        definition=(
            "Handovers a partner has accepted and not yet put a date on. These "
            "carry no cost, and contribute UGX 0 to the planned budget until "
            "the partner schedules."
        ),
        question="How much work is sitting with partners, undated?",
        category=Category.PENDING_ACTION,
        unit=Unit.COUNT,
        service="apps.planning.oversight_service.summarize",
        source_models=("partners.PartnerAssignment",),
        numerator="Partner assignments in an unscheduled status",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.FINANCIAL_YEAR,
        scope="The reader's oversight scope — team for a PL, country for a CD",
        owner_page="team_planning_oversight",
        secondary_pages=("country_planning_oversight",),
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="/partner-oversight/",
        refresh_events=("partner_assignment_scheduled",),
    ),
    MetricSpec(
        key="oversight_team_work_needing_attention",
        label="Team Work Needing Attention",
        definition=(
            "Planned work on which at least one risk condition currently holds "
            "— an overdue activity, an unscheduled handover past its date, "
            "outstanding evidence, a missing Salesforce id, an IA return."
        ),
        question="Where must I intervene in my team's plan?",
        category=Category.RISK,
        unit=Unit.COUNT,
        service="apps.planning.risk_service.annotate",
        source_models=("activities.Activity", "partners.PartnerAssignment"),
        numerator="Items with one or more live risk conditions",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.FINANCIAL_YEAR,
        scope="The Program Lead's own work and their supervisees'",
        owner_page="team_planning_oversight",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="/team-planning-oversight/?tab=attention",
        refresh_events=("activity_rescheduled", "evidence_uploaded"),
    ),
    MetricSpec(
        key="oversight_country_activities_at_risk",
        label="Country Activities At Risk",
        definition=(
            "The same risk conditions as the team lens, measured across the "
            "whole country rather than one team."
        ),
        question="Which teams are carrying the country's planning risk?",
        category=Category.RISK,
        unit=Unit.COUNT,
        service="apps.planning.risk_service.annotate",
        source_models=("activities.Activity", "partners.PartnerAssignment"),
        numerator="Items with one or more live risk conditions, country-wide",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.FINANCIAL_YEAR,
        scope="Whole country",
        owner_page="country_planning_oversight",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="/country-planning-oversight/",
        refresh_events=("activity_rescheduled", "evidence_uploaded"),
    ),
    MetricSpec(
        key="oversight_team_planned_budget",
        label="Planned Team Budget",
        definition=(
            "The sum of the cost lines on the team's scheduled activities. "
            "Unscheduled partner handovers contribute nothing, because no cost "
            "exists for work with no date."
        ),
        question="What has my team's plan committed financially?",
        category=Category.FINANCE,
        unit=Unit.MONEY_UGX,
        finance_stage=FinanceStage.PLANNED,
        service="apps.planning.oversight_service.summarize",
        source_models=("activities.ActivityScheduleCostLine",),
        numerator="Sum of cost lines on scheduled activities in scope",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.FINANCIAL_YEAR,
        scope="The Program Lead's own work and their supervisees'",
        owner_page="team_planning_oversight",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="/team-planning-oversight/",
        refresh_events=("activity_scheduled", "activity_costed"),
    ),
    MetricSpec(
        key="oversight_country_planned_budget",
        label="Planned Country Budget",
        definition=(
            "The sum of the cost lines on every scheduled activity in the "
            "country, on the same basis as the team figure."
        ),
        question="What has the country's plan committed financially?",
        category=Category.FINANCE,
        unit=Unit.MONEY_UGX,
        finance_stage=FinanceStage.PLANNED,
        service="apps.planning.oversight_service.summarize",
        source_models=("activities.ActivityScheduleCostLine",),
        numerator="Sum of cost lines on scheduled activities, country-wide",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.FINANCIAL_YEAR,
        scope="Whole country",
        owner_page="country_planning_oversight",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="/country-planning-oversight/",
        refresh_events=("activity_scheduled", "activity_costed"),
    ),
    MetricSpec(
        key="oversight_execution_progress",
        label="Plan Execution Progress",
        definition=(
            "Completed work as a share of work whose planned date has passed. "
            "Measured against what is due rather than against the whole plan, "
            "so a plan that is entirely in the future reads as 'nothing due "
            "yet' rather than as 0% delivered."
        ),
        question="Is the plan being delivered on time?",
        category=Category.PROGRESS,
        unit=Unit.PERCENT,
        denominator="Activities whose planned date has passed",
        service="apps.planning.oversight_service.summarize",
        source_models=("activities.Activity",),
        numerator="Activities in a completed status",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.FINANCIAL_YEAR,
        scope="The reader's oversight scope — team for a PL, country for a CD",
        owner_page="team_planning_oversight",
        secondary_pages=("country_planning_oversight",),
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="/team-planning-oversight/?tab=completed",
        refresh_events=("activity_completed", "activity_verified"),
    ),
    # ── Partner oversight ────────────────────────────────────────────────────
    MetricSpec(
        key="oversight_awaiting_verification",
        label="Awaiting Verification",
        definition=(
            "Completions that entered the Impact Assessment queue and are "
            "still unverified. Measured from submitted_to_ia_at, the field the "
            "activity model keeps apart from updated_at for exactly this."
        ),
        question="What has been delivered but not yet earns credit?",
        category=Category.PENDING_ACTION,
        unit=Unit.COUNT,
        service="apps.planning.oversight_service.summarize",
        source_models=("activities.Activity",),
        numerator="Activities submitted to IA with verification still pending",
        date_basis=DateBasis.SUBMISSION_DATE,
        period=Period.FINANCIAL_YEAR,
        scope="The reader's oversight scope — team for a PL, country for a CD",
        owner_page="team_planning_oversight",
        secondary_pages=("country_planning_oversight",),
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="/ia/verification-queue",
        refresh_events=("activity_submitted_for_review", "activity_verified"),
        notes=(
            "The actor is a queue, not a person: no officer is assigned a "
            "particular verification, so the oversight pages nudge the whole "
            "queue rather than opening a TeamAction against an individual."
        ),
    ),
    MetricSpec(
        key="partner_oversight_active_partners",
        label="Active Partners",
        definition=(
            "Distinct partners holding at least one assignment in the period, "
            "at any stage from handover to payment."
        ),
        question="How many partners am I relying on this period?",
        category=Category.SCALE,
        unit=Unit.COUNT,
        service="apps.planning.partner_oversight_service.summarize",
        source_models=("partners.PartnerAssignment",),
        numerator="Distinct partners on assignments in scope",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.FINANCIAL_YEAR,
        scope="The reader's oversight scope — team for a PL, country for a CD",
        owner_page="partner_oversight",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="/partner-oversight/",
        refresh_events=("partner_assignment_created",),
    ),
    MetricSpec(
        key="partner_oversight_yet_to_schedule",
        label="Handovers Yet To Schedule",
        definition=(
            "Assignments a partner holds and has not put a date on. No cost "
            "exists for these — not zero, absent — because pricing happens at "
            "scheduling."
        ),
        question="Which partners are holding work without committing to it?",
        category=Category.PENDING_ACTION,
        unit=Unit.COUNT,
        service="apps.planning.partner_oversight_service.summarize",
        source_models=("partners.PartnerAssignment",),
        numerator="Assignments in an unscheduled status",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.FINANCIAL_YEAR,
        scope="The reader's oversight scope — team for a PL, country for a CD",
        owner_page="partner_oversight",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="/partner-oversight/",
        refresh_events=("partner_assignment_scheduled",),
    ),
    MetricSpec(
        key="partner_oversight_scheduled",
        label="Partner Work Scheduled",
        definition=(
            "Assignments a partner has put a date on, at any point from "
            "scheduled through delivery, verification and payment."
        ),
        question="How much partner work is actually under way?",
        category=Category.PROGRESS,
        unit=Unit.COUNT,
        service="apps.planning.partner_oversight_service.summarize",
        source_models=("partners.PartnerAssignment", "activities.Activity"),
        numerator="Assignments linked to a scheduled activity",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.FINANCIAL_YEAR,
        scope="The reader's oversight scope — team for a PL, country for a CD",
        owner_page="partner_oversight",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="/partner-oversight/",
        refresh_events=("partner_assignment_scheduled",),
    ),
    MetricSpec(
        key="partner_oversight_needing_attention",
        label="Partner Work Needing Attention",
        definition=(
            "Handovers on which at least one partner risk condition holds — "
            "nobody has scheduled, delivery is past its date with no evidence, "
            "the managing CCEO has not reviewed, the payment is overdue."
        ),
        question="Where is partner delivery stuck, and with whom?",
        category=Category.RISK,
        unit=Unit.COUNT,
        service="apps.planning.partner_risk_service.annotate",
        source_models=("partners.PartnerAssignment", "activities.Activity"),
        numerator="Handovers with one or more live partner risk conditions",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.FINANCIAL_YEAR,
        scope="The reader's oversight scope — team for a PL, country for a CD",
        owner_page="partner_oversight",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="/partner-oversight/",
        refresh_events=("partner_assignment_scheduled", "evidence_uploaded"),
    ),
    MetricSpec(
        key="partner_oversight_scheduled_budget",
        label="Scheduled Partner Budget",
        definition=(
            "The sum of the cost lines on partner activities the partner has "
            "scheduled. Handovers with no date are excluded entirely, because "
            "no rate has been applied to them."
        ),
        question="What has partner delivery committed financially?",
        category=Category.FINANCE,
        unit=Unit.MONEY_UGX,
        finance_stage=FinanceStage.PLANNED,
        service="apps.planning.partner_oversight_service.summarize",
        source_models=("activities.ActivityScheduleCostLine",),
        numerator="Sum of cost lines on scheduled partner activities",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.FINANCIAL_YEAR,
        scope="The reader's oversight scope — team for a PL, country for a CD",
        owner_page="partner_oversight",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="/partner-oversight/",
        refresh_events=("partner_assignment_scheduled", "activity_costed"),
    ),
    MetricSpec(
        key="partner_oversight_payment_pending",
        label="Partner Payments Pending",
        definition=(
            "Partner work Impact Assessment has verified that the accountant "
            "has not yet paid."
        ),
        question="What do we owe partners for work already verified?",
        category=Category.PENDING_ACTION,
        unit=Unit.COUNT,
        service="apps.planning.partner_oversight_service.summarize",
        source_models=("activities.Activity",),
        numerator="Verified partner activities with no completed payment",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.FINANCIAL_YEAR,
        scope="The reader's oversight scope — team for a PL, country for a CD",
        owner_page="partner_oversight",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="/accounts/partner-payments",
        refresh_events=("activity_verified", "partner_paid"),
    ),
    # ── Business Transformation: the Uganda MFI portfolio scorecard ──────────
    # Owned by the BT workspace; the Loan Register repeats the strip because
    # its reader is making the same portfolio judgement over the filtered
    # register rather than a different one. The workspace renders no more than
    # six decision-grade tiles; the remaining governed measures live in the
    # register and drill-down views.
    # `services.portfolio_metrics` over the caller's scoped loans.
    MetricSpec(
        key="bt_new_loans",
        label="New Loans",
        definition=(
            "MFI loans submitted within the selected financial-year period "
            "for schools in the caller's Business Transformation scope."
        ),
        question="How much new lending is the programme originating?",
        category=Category.SCALE,
        unit=Unit.COUNT,
        service="apps.business_transformation.services.workspace_context",
        source_models=("business_transformation.MfiLoan",),
        numerator="Loans with a submission date inside the selected FY period",
        date_basis=DateBasis.SUBMISSION_DATE,
        period=Period.FINANCIAL_YEAR,
        scope="The caller's scoped Business Transformation loan portfolio",
        owner_page="business_transformation",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="/loans",
        secondary_pages=("loans",),
    ),
    MetricSpec(
        key="bt_value_disbursed",
        label="Value Disbursed",
        definition=(
            "Net principal confirmed through append-only disbursement and "
            "reversal postings in the selected period, in the facility currency."
        ),
        question="How much financing actually reached schools?",
        category=Category.FINANCE,
        unit=Unit.MONEY_UGX,
        finance_stage=FinanceStage.DISBURSED,
        service="apps.business_transformation.services.workspace_context",
        source_models=(
            "business_transformation.LoanDisbursement",
            "business_transformation.LoanDisbursementReversal",
        ),
        numerator="Confirmed disbursement postings less reversal postings",
        date_basis=DateBasis.SUBMISSION_DATE,
        period=Period.FINANCIAL_YEAR,
        scope="The caller's scoped Business Transformation loan portfolio",
        owner_page="business_transformation",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="/loans",
        secondary_pages=("loans",),
    ),
    MetricSpec(
        key="bt_schools_financed",
        label="Schools Financed",
        definition="Unique schools holding at least one disbursed MFI loan.",
        question="How broad is the financed footprint?",
        category=Category.SCALE,
        unit=Unit.COUNT,
        service="apps.business_transformation.services.workspace_context",
        source_models=("business_transformation.MfiLoan", "schools.School"),
        numerator="Distinct schools across disbursed loans in scope",
        date_basis=DateBasis.SUBMISSION_DATE,
        period=Period.FINANCIAL_YEAR,
        scope="The caller's scoped Business Transformation loan portfolio",
        owner_page="business_transformation",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="/loans",
        secondary_pages=("loans",),
    ),
    MetricSpec(
        key="bt_active_portfolio",
        label="Active Portfolio",
        definition=(
            "Net confirmed principal disbursed less principal repayment "
            "allocations and their reversals at the reporting date."
        ),
        question="How much financed money is still at work?",
        category=Category.FINANCE,
        unit=Unit.MONEY_UGX,
        finance_stage=FinanceStage.OUTSTANDING,
        service="apps.business_transformation.services.workspace_context",
        source_models=(
            "business_transformation.LoanDisbursement",
            "business_transformation.RepaymentAllocation",
        ),
        numerator="Net confirmed principal less net principal collected",
        date_basis=DateBasis.SUBMISSION_DATE,
        period=Period.POINT_IN_TIME,
        scope="The caller's scoped Business Transformation loan portfolio",
        owner_page="business_transformation",
        filter_behaviour=FilterBehaviour.PARTIAL,
        drilldown="/loans",
        secondary_pages=("loans",),
        notes="A ledger position: the period filter narrows loans, not postings.",
    ),
    MetricSpec(
        key="bt_repaid_amount",
        label="Repaid Amount",
        definition=(
            "Principal the schools repaid to their MFIs within the selected "
            "period, in UGX."
        ),
        question="Is the portfolio actually being serviced?",
        category=Category.PROGRESS,
        unit=Unit.MONEY_UGX,
        finance_stage=FinanceStage.RETURNED,
        service="apps.business_transformation.services.workspace_context",
        source_models=(
            "business_transformation.RepaymentTransaction",
            "business_transformation.RepaymentAllocation",
        ),
        numerator="Net principal allocations posted inside the selected period",
        date_basis=DateBasis.SUBMISSION_DATE,
        period=Period.FINANCIAL_YEAR,
        scope="The caller's scoped Business Transformation loan portfolio",
        owner_page="business_transformation",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="/loans",
        secondary_pages=("loans",),
        notes=(
            "School→MFI repayments; RETURNED is the closest pipeline stage — "
            "this money leaves the portfolio rather than Edify's books."
        ),
    ),
    MetricSpec(
        key="bt_amount_overdue",
        label="Amount Overdue",
        definition=(
            "Scheduled principal, interest and fees due by the reporting date "
            "that remain unallocated after repayment reversals."
        ),
        question="How much repayment is late right now?",
        category=Category.RISK,
        unit=Unit.MONEY_UGX,
        finance_stage=FinanceStage.OUTSTANDING,
        service="apps.business_transformation.services.workspace_context",
        source_models=(
            "business_transformation.LoanRepaymentInstallment",
            "business_transformation.RepaymentAllocation",
        ),
        numerator="Due scheduled components less net repayment allocations",
        date_basis=DateBasis.SUBMISSION_DATE,
        period=Period.POINT_IN_TIME,
        scope="The caller's scoped Business Transformation loan portfolio",
        owner_page="business_transformation",
        filter_behaviour=FilterBehaviour.PARTIAL,
        drilldown="/loans",
        secondary_pages=("loans",),
    ),
    MetricSpec(
        key="bt_defaulted_portfolio",
        label="Defaulted Portfolio",
        definition=(
            "Outstanding principal on loans the MFI has classified as "
            "defaulted, in UGX."
        ),
        question="How much of the portfolio has been lost to default?",
        category=Category.RISK,
        unit=Unit.MONEY_UGX,
        finance_stage=FinanceStage.OUTSTANDING,
        service="apps.business_transformation.services.workspace_context",
        source_models=(
            "business_transformation.LoanDisbursement",
            "business_transformation.RepaymentAllocation",
        ),
        numerator="Ledger-derived outstanding principal on defaulted loans",
        date_basis=DateBasis.SUBMISSION_DATE,
        period=Period.POINT_IN_TIME,
        scope="The caller's scoped Business Transformation loan portfolio",
        owner_page="business_transformation",
        filter_behaviour=FilterBehaviour.PARTIAL,
        drilldown="/loans",
        secondary_pages=("loans",),
    ),
    MetricSpec(
        key="bt_par30",
        label="Portfolio at Risk 30",
        definition=(
            "Outstanding principal on loans more than 30 days past due as a "
            "share of total outstanding principal."
        ),
        question="How much outstanding principal is materially delinquent?",
        category=Category.RISK,
        unit=Unit.PERCENT,
        denominator="Total outstanding principal in the scoped portfolio",
        service="apps.business_transformation.services.workspace_context",
        source_models=(
            "business_transformation.LoanRepaymentInstallment",
            "business_transformation.RepaymentAllocation",
        ),
        numerator="Outstanding principal on loans more than 30 days past due",
        date_basis=DateBasis.EXECUTION_DATE,
        period=Period.POINT_IN_TIME,
        scope="The caller's scoped Business Transformation loan portfolio",
        owner_page="business_transformation",
        filter_behaviour=FilterBehaviour.PARTIAL,
        drilldown="/loans",
        secondary_pages=("loans",),
    ),
    MetricSpec(
        key="bt_collection_rate",
        label="Collection Rate",
        definition=(
            "Net repayment value collected during the selected period as a "
            "share of scheduled principal, interest and fees due in that period."
        ),
        question="Are scheduled repayments being collected?",
        category=Category.PROGRESS,
        unit=Unit.PERCENT,
        denominator="Scheduled principal, interest and fees due in the period",
        service="apps.business_transformation.services.workspace_context",
        source_models=(
            "business_transformation.LoanRepaymentInstallment",
            "business_transformation.RepaymentTransaction",
            "business_transformation.RepaymentAllocation",
        ),
        numerator="Repayment allocations less reversal allocations in the period",
        date_basis=DateBasis.EXECUTION_DATE,
        period=Period.FINANCIAL_YEAR,
        scope="The caller's scoped Business Transformation loan portfolio",
        owner_page="business_transformation",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="/loans",
        secondary_pages=("loans",),
    ),
    MetricSpec(
        key="bt_edtech_share",
        label="EdTech Share",
        definition=(
            "Share of disbursed loans whose governed purpose is an EdTech " "purpose."
        ),
        question="Is the lending advancing the EdTech objective?",
        category=Category.QUALITY,
        unit=Unit.PERCENT,
        denominator="All disbursed loans in the selected period",
        service="apps.business_transformation.services.workspace_context",
        source_models=("business_transformation.MfiLoan",),
        numerator="Disbursed loans with an EdTech purpose",
        date_basis=DateBasis.SUBMISSION_DATE,
        period=Period.FINANCIAL_YEAR,
        scope="The caller's scoped Business Transformation loan portfolio",
        owner_page="business_transformation",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="/loans",
        secondary_pages=("loans",),
    ),
    MetricSpec(
        key="bt_use_verified",
        label="Loan Use Verified",
        definition=(
            "Share of due loan-use verifications that a governed verification "
            "visit has completed."
        ),
        question="Are we actually checking that loans bought what they promised?",
        category=Category.PROGRESS,
        unit=Unit.PERCENT,
        denominator="Loan-use verifications currently due",
        service="apps.business_transformation.services.workspace_context",
        source_models=("business_transformation.LoanVerificationRequirement",),
        numerator="Due verifications with a completed verification activity",
        date_basis=DateBasis.EXECUTION_DATE,
        period=Period.POINT_IN_TIME,
        scope="The caller's scoped Business Transformation loan portfolio",
        owner_page="business_transformation",
        filter_behaviour=FilterBehaviour.PARTIAL,
        drilldown="/loans",
        secondary_pages=("loans",),
    ),
    MetricSpec(
        key="bt_salesforce_backlog",
        label="Salesforce Backlog",
        definition=(
            "Loan records whose Salesforce reference has not yet been " "confirmed."
        ),
        question="Which loan records still need their Salesforce proof?",
        category=Category.PENDING_ACTION,
        unit=Unit.COUNT,
        service="apps.business_transformation.services.workspace_context",
        source_models=("business_transformation.MfiLoan",),
        numerator="Loan records minus Salesforce-confirmed records",
        date_basis=DateBasis.SUBMISSION_DATE,
        period=Period.POINT_IN_TIME,
        scope="The caller's scoped Business Transformation loan portfolio",
        owner_page="business_transformation",
        filter_behaviour=FilterBehaviour.PARTIAL,
        drilldown="/loans",
        secondary_pages=("loans",),
    ),
    MetricSpec(
        key="bt_positive_impact",
        label="Positive Impact",
        definition=(
            "Share of impact-assessed loans whose assessment concluded a "
            "positive school-level outcome."
        ),
        question="Is the financing changing school outcomes for the better?",
        category=Category.QUALITY,
        unit=Unit.PERCENT,
        denominator="Loans with a completed impact assessment",
        service="apps.business_transformation.services.workspace_context",
        source_models=("business_transformation.LoanImpactAssessment",),
        numerator="Completed assessments with a positive conclusion",
        date_basis=DateBasis.SUBMISSION_DATE,
        period=Period.POINT_IN_TIME,
        scope="The caller's scoped Business Transformation loan portfolio",
        owner_page="business_transformation",
        filter_behaviour=FilterBehaviour.PARTIAL,
        drilldown="/loans",
        secondary_pages=("loans",),
    ),
    *RECONCILED_METRICS,
)


# ── Accessors ────────────────────────────────────────────────────────────────
_BY_KEY: dict[str, MetricSpec] = {m.key: m for m in METRIC_REGISTRY}


def get_metric(key: str) -> MetricSpec:
    try:
        return _BY_KEY[key]
    except KeyError:
        raise KeyError(
            f"unregistered metric {key!r} -- add a MetricSpec to "
            f"apps/core/metrics/registry.py before displaying it"
        ) from None


def all_metrics() -> tuple[MetricSpec, ...]:
    return METRIC_REGISTRY


def metrics_for_page(page: str) -> tuple[MetricSpec, ...]:
    return tuple(m for m in METRIC_REGISTRY if page in m.approved_pages())


def check() -> None:
    """Fail loudly on the defects this registry exists to prevent."""
    duplicate_keys = [
        k for k, n in Counter(m.key for m in METRIC_REGISTRY).items() if n > 1
    ]
    if duplicate_keys:
        raise ValueError(f"duplicate metric keys: {sorted(duplicate_keys)}")

    # Two metrics with one label are indistinguishable to a reader, which is
    # precisely how a page ends up showing "the same thing" twice.
    by_label: dict[str, list[str]] = defaultdict(list)
    for m in METRIC_REGISTRY:
        by_label[m.label.casefold()].append(m.key)
    clashes = {label: keys for label, keys in by_label.items() if len(keys) > 1}
    if clashes:
        raise ValueError(f"metrics sharing a label: {clashes}")

    vague = [
        m.key for m in METRIC_REGISTRY if m.label.strip().casefold() in AMBIGUOUS_LABELS
    ]
    if vague:
        raise ValueError(
            f"labels that do not say what they count: {sorted(vague)} -- "
            f"name the state, period and scope"
        )

    # One metric, one owning page (section 4). A metric listing itself as a
    # secondary appearance of its own owner is a copy-paste, not a decision.
    for m in METRIC_REGISTRY:
        if m.owner_page in m.secondary_pages:
            raise ValueError(f"{m.key}: owner_page repeated in secondary_pages")
