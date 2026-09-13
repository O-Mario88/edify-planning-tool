"""Metric definitions for the CCE Regional Lead's registers (owner, 2026-09-13).

The engagement log, the training feedback register and the monthly reports
render their tiles through ``apps.frontend.views.cce_leadership_views._metric``,
which only accepts a label the reconciled registry knows. Their definitions
live here and are appended to the reconciled rows in reconciled_registry.py.
"""

from __future__ import annotations

_SOURCE = "apps.frontend.views.cce_leadership_views:_metric"
_LOCATION = "apps/frontend/views/cce_leadership_views.py"
_ENGAGEMENT = ("apps.cce_leadership.models.RegionalEngagement",)
_REPORT = ("apps.cce_leadership.models.RegionalCceReport",)


def _slug(text: str) -> str:
    out = "".join(ch if ch.isalnum() else "_" for ch in text.lower())
    while "__" in out:
        out = out.replace("__", "_")
    return out.strip("_")


def _row(
    label: str,
    *,
    line: int,
    definition: str,
    question: str,
    numerator: str,
    models: tuple[str, ...],
    owner_page: str,
    roles: tuple[str, ...],
    scope: str,
    category: str = "progress",
    unit: str = "count",
    period: str = "point_in_time",
    date_basis: str = "not_time_bound",
) -> dict:
    return {
        "key": f"cce_leadership_{_slug(label)}",
        "label": label,
        "source_label": label,
        "source": _SOURCE,
        "definition": definition,
        "question": question,
        "category": category,
        "unit": unit,
        "service": "apps.frontend.views.cce_leadership_views._metric",
        "source_models": models,
        "numerator": numerator,
        "denominator": None,
        "date_basis": date_basis,
        "period": period,
        "scope": scope,
        "owner_page": owner_page,
        "filter_behaviour": "fixed_context",
        "drilldown": None,
        "no_drilldown_reason": "The register below the tile lists the records it counts.",
        "notes": "CCE Regional Lead registers, added 2026-09-13.",
        "roles": roles,
        "source_location": f"{_LOCATION}:{line}",
    }


_LEAD = ("RegionalProgramLead", "Admin")
_LOG_SCOPE = "The Regional Lead's own engagements; Admin reads every lead's"
_FEEDBACK_ROLES = ("Program Lead", "CountryDirector", "RegionalProgramLead", "Admin")
_FEEDBACK_SCOPE = (
    "Observations shared with the Programme Lead, on the Country Director's "
    "country, or recorded by the Regional Lead (apps.cce_leadership.services)"
)
_REPORT_ROLES = ("RegionalProgramLead", "RegionalVicePresident", "Admin")
_REPORT_SCOPE = (
    "The Regional Lead's own reports; for the RVP, submitted reports on the "
    "countries they oversee"
)

CCE_LEADERSHIP_METRIC_ROWS: tuple[dict, ...] = (
    _row(
        "Coaching Conversations (30 Days)",
        line=194,
        definition="Programme Lead coaching conversations the lead recorded in the last 30 days.",
        question="Is the lead meeting the Programme Leads regularly?",
        numerator="engagements of kind pl_coaching held in the last 30 days",
        models=_ENGAGEMENT,
        owner_page="cce_engagements",
        roles=_LEAD,
        scope=_LOG_SCOPE,
        period="rolling_30_days",
        date_basis="record_created",
    ),
    _row(
        "Trainings Observed This Quarter",
        line=202,
        definition="Training observations recorded in the current financial-year quarter.",
        question="Are trainings being observed and critiqued?",
        numerator="engagements of kind training_observation held this quarter",
        models=_ENGAGEMENT,
        owner_page="cce_engagements",
        roles=_LEAD,
        scope=_LOG_SCOPE,
        category="quality",
        period="quarter",
        date_basis="record_created",
    ),
    _row(
        "Country Reviews This Quarter",
        line=207,
        definition="Quarterly reviews with a Country Director recorded this quarter.",
        question="Has every country had its quarterly review?",
        numerator="engagements of kind cd_quarterly_review held this quarter",
        models=_ENGAGEMENT,
        owner_page="cce_engagements",
        roles=_LEAD,
        scope=_LOG_SCOPE,
        period="quarter",
        date_basis="record_created",
    ),
    _row(
        "Engagements Overdue",
        line=212,
        definition=(
            "Rows of the role's meeting rhythm that are overdue or missed: "
            "coaching conversations older than a month, check-ins and meetings "
            "past their cadence, and annual budget input a country's budget went "
            "without (apps.cce_leadership.cadence)."
        ),
        question="What in the lead's rhythm has slipped?",
        numerator="cadence rows in state overdue or missed",
        models=_ENGAGEMENT + ("apps.monthly_work_plan.models.CountryAnnualBudget",),
        owner_page="cce_engagements",
        roles=_LEAD,
        scope=_LOG_SCOPE,
        category="risk",
    ),
    _row(
        "Feedback Awaiting Acknowledgement",
        line=707,
        definition="Shared training observations the Programme Lead has not yet acknowledged.",
        question="Which training feedback has not been answered?",
        numerator="observations with feedback_shared_at set and acknowledged_at empty",
        models=_ENGAGEMENT,
        owner_page="cce_training_feedback",
        roles=_FEEDBACK_ROLES,
        scope=_FEEDBACK_SCOPE,
        category="risk",
    ),
    _row(
        "Feedback Acknowledged",
        line=713,
        definition="Shared training observations the Programme Lead acknowledged with a response.",
        question="How much training feedback has been acted on?",
        numerator="observations with acknowledged_at set",
        models=_ENGAGEMENT,
        owner_page="cce_training_feedback",
        roles=_FEEDBACK_ROLES,
        scope=_FEEDBACK_SCOPE,
        category="quality",
    ),
    _row(
        "Average Observation Rating",
        line=719,
        definition=(
            "The mean of each observation's average rating across the five "
            "criteria (Biblical integration, SSA need, facilitation, participation, "
            "practical application), on a 1-4 scale."
        ),
        question="How good are the trainings being observed?",
        numerator="sum of observation average ratings",
        models=_ENGAGEMENT,
        owner_page="cce_training_feedback",
        roles=_FEEDBACK_ROLES,
        scope=_FEEDBACK_SCOPE,
        category="quality",
        unit="score",
    ),
    _row(
        "Report Drafts",
        line=875,
        definition="Monthly CCE reports started and not yet submitted.",
        question="Which monthly reports are still being written?",
        numerator="reports in status draft",
        models=_REPORT,
        owner_page="cce_reports",
        roles=_REPORT_ROLES,
        scope=_REPORT_SCOPE,
    ),
    _row(
        "Reports Awaiting Review",
        line=877,
        definition="Monthly CCE reports submitted and not yet acknowledged or returned.",
        question="Which reports wait for the RVP?",
        numerator="reports in status submitted",
        models=_REPORT,
        owner_page="cce_reports",
        roles=_REPORT_ROLES,
        scope=_REPORT_SCOPE,
        category="risk",
    ),
    _row(
        "Reports Returned",
        line=883,
        definition="Monthly CCE reports the RVP returned for revision.",
        question="Which reports need revising?",
        numerator="reports in status returned",
        models=_REPORT,
        owner_page="cce_reports",
        roles=_REPORT_ROLES,
        scope=_REPORT_SCOPE,
        category="risk",
    ),
    _row(
        "Reports Acknowledged",
        line=889,
        definition="Monthly CCE reports the RVP acknowledged.",
        question="Which monthly reports are closed?",
        numerator="reports in status acknowledged",
        models=_REPORT,
        owner_page="cce_reports",
        roles=_REPORT_ROLES,
        scope=_REPORT_SCOPE,
    ),
)
