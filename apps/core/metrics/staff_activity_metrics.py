"""Metric definitions for the Staff Activity Log's summary strip.

Owner, 2026-09-29 (replaces Who's Online). The strip is rendered through
``apps.frontend.views.staff_activity_views._kpi_items``, which only accepts a
label the reconciled registry knows. Every figure is computed by
``apps.staff_activity.services.activity_log`` over the rows the page's table
lists, for the period and filters the reader chose, so a tile never counts
someone the table does not show. Active time is a management and adoption
signal, never a performance score.
"""

from __future__ import annotations

_SOURCE = "apps.frontend.views.staff_activity_views:_kpi_items"
_LOCATION = "apps/frontend/views/staff_activity_views.py"
_ROLES = ("Program Lead", "CountryDirector", "Admin")
_SCOPE = (
    "The CCEOs and Programme Leads in the reader's scope — a Programme Lead's "
    "supervised officers, or the country's for the Country Director and the Admin — "
    "narrowed by the page's role, Programme Lead, status and search filters"
)


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
    category: str = "scale",
    unit: str = "count",
    denominator: str | None = None,
) -> dict:
    return {
        "key": f"staff_activity_{_slug(label)}",
        "label": label,
        "source_label": label,
        "source": _SOURCE,
        "definition": definition,
        "question": question,
        "category": category,
        "unit": unit,
        "service": "apps.staff_activity.services.activity_log",
        "source_models": models,
        "numerator": numerator,
        "denominator": denominator,
        "date_basis": "record_created",
        "period": "point_in_time",
        "scope": _SCOPE,
        "owner_page": "staff_activity",
        "filter_behaviour": "filtered",
        "drilldown": None,
        "no_drilldown_reason": "The table below the strip lists the staff it counts, one row each.",
        "notes": "Staff Activity Log, added 2026-09-29; follows the page's Day/Week/Month/Quarter/FY period.",
        "roles": _ROLES,
        "source_location": f"{_LOCATION}:{line}",
    }


_USERS = ("apps.accounts.models.User",)
_TIME = ("apps.accounts.models.PresenceTime",)
_LOGINS = ("apps.accounts.models.LoginEvent",)
_AUDIT = ("apps.audit.models.AuditLog",)

STAFF_ACTIVITY_METRIC_ROWS: tuple[dict, ...] = (
    _row(
        "Staff Expected",
        line=124,
        definition=(
            "Staff with at least one expected working day in the period so far: "
            "a weekday that is not a public holiday and not approved leave."
        ),
        question="How many people were expected to use the platform?",
        numerator="people whose expected working days in the elapsed period > 0",
        models=_USERS
        + ("apps.accounts.models.Leave", "apps.accounts.models.PublicHoliday"),
    ),
    _row(
        "Staff Active",
        line=128,
        definition="Staff who signed in or had active time in the period.",
        question="How many people used the platform?",
        numerator="people with a sign-in or active seconds in the period",
        denominator="Staff Expected",
        models=_LOGINS + _TIME,
        category="progress",
    ),
    _row(
        "No Login",
        line=130,
        definition=(
            "Staff with an expected working day in the period who neither signed "
            "in nor had active time. Leave and holidays are not counted."
        ),
        question="Who may need a check-in because they have not used the platform?",
        numerator="expected people with no sign-in and no active time",
        models=_LOGINS + _TIME + ("apps.accounts.models.Leave",),
        category="risk",
    ),
    _row(
        "Total Active Time",
        line=136,
        definition=(
            "Active platform time in the period: the server credits the gap between "
            "two activity beats only when it is within the idle threshold, once per "
            "person whatever the number of tabs or devices."
        ),
        question="How much active time did the staff spend on the platform?",
        numerator="sum of PresenceTime seconds in the period (plus the pending beat)",
        models=_TIME,
        unit="status",
    ),
    _row(
        "Median Active Time",
        line=140,
        definition="The median active time of the staff who were active in the period.",
        question="What is a typical person's active time?",
        numerator="median of active seconds over active staff",
        models=_TIME,
        unit="status",
    ),
    _row(
        "Meaningful Actions",
        line=142,
        definition=(
            "Successful governed workflow actions in the period, read from the audit "
            "chain through apps.staff_activity.registry — never page views."
        ),
        question="How much operational work did the staff complete on the platform?",
        numerator="successful AuditLog rows whose action is a registered meaningful action",
        models=_AUDIT,
        category="outcome",
    ),
    _row(
        "Open Follow-ups",
        line=148,
        definition="Manager follow-ups about the listed staff that are not yet resolved.",
        question="How many staff follow-ups are still open?",
        numerator="StaffUsageFollowUp rows in an open status",
        models=("apps.staff_activity.models.StaffUsageFollowUp",),
        category="pending_action",
    ),
)
