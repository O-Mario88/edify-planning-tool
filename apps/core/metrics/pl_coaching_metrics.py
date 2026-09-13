"""Metric definitions for Coaching — a Programme Lead's coaching log and an officer's acknowledgements.

Program Lead alignment (owner, 2026-09-13). /team/coaching and /my-coaching
render their tiles through ``apps.frontend.views.coaching_views._metric``, which
only accepts a label the reconciled registry knows. Rows are appended to the
reconciled registry in reconciled_registry.py; the row shape follows
cce_leadership_metrics.py. The counts come from
apps.cce_leadership.coaching (coaching_counts, monthly_one_to_ones), the same
functions the To-Do queue and the Programme Lead dashboard read.
"""

from __future__ import annotations

_SOURCE = "apps.frontend.views.coaching_views:_metric"
_LOCATION = "apps/frontend/views/coaching_views.py"
_COACHING = ("apps.cce_leadership.models.CceoCoaching",)


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
    owner_page: str,
    roles: tuple[str, ...],
    scope: str,
    category: str = "progress",
    unit: str = "count",
    period: str = "point_in_time",
    date_basis: str = "not_time_bound",
    denominator: str | None = None,
) -> dict:
    return {
        "key": f"pl_coaching_{_slug(label)}",
        "label": label,
        "source_label": label,
        "source": _SOURCE,
        "definition": definition,
        "question": question,
        "category": category,
        "unit": unit,
        "service": "apps.frontend.views.coaching_views._metric",
        "source_models": _COACHING,
        "numerator": numerator,
        "denominator": denominator,
        "date_basis": date_basis,
        "period": period,
        "scope": scope,
        "owner_page": owner_page,
        "filter_behaviour": "fixed_context",
        "drilldown": None,
        "no_drilldown_reason": "The register below the tile lists the records it counts.",
        "notes": "Programme Lead coaching, added 2026-09-13.",
        "roles": roles,
        "source_location": f"{_LOCATION}:{line}",
    }


_TEAM_ROLES = ("Program Lead", "CountryDirector", "RegionalProgramLead", "Admin")
_TEAM_SCOPE = (
    "For a Programme Lead, the coaching they wrote for the officers on their team "
    "(apps.hr.team_roster.team_members); for the Country Director, shared coaching "
    "in their country; for the Regional Lead, shared coaching in their region's "
    "countries; Admin reads all (apps.cce_leadership.coaching.coaching_visible_to)"
)
_OFFICER_ROLES = ("CCEO", "Admin")
_OFFICER_SCOPE = (
    "Coaching the officer's Programme Lead shared with them; Admin reads every "
    "shared record"
)

PL_COACHING_METRIC_ROWS: tuple[dict, ...] = (
    _row(
        "One-to-Ones Held This Month",
        line=315,
        definition=(
            "Officers whose monthly one-to-one is recorded for the current calendar "
            "month, against the officers on the Programme Lead's team. An officer "
            "without one is due from the tenth of the month "
            "(apps.cce_leadership.coaching.monthly_one_to_ones)."
        ),
        question="Has every officer had this month's one-to-one?",
        numerator="team members with a one_to_one coaching record held this month",
        denominator="officers on the Programme Lead's team",
        owner_page="team_coaching",
        roles=_TEAM_ROLES,
        scope=_TEAM_SCOPE,
        unit="status",
        period="month",
        date_basis="record_created",
    ),
    _row(
        "Coaching Notes Not Yet Shared",
        line=339,
        definition="Coaching records the Programme Lead wrote and has not shared with the officer.",
        question="Which coaching notes has the officer not received yet?",
        numerator="coaching records with shared_at empty",
        owner_page="team_coaching",
        roles=_TEAM_ROLES,
        scope=_TEAM_SCOPE,
        category="pending_action",
    ),
    _row(
        "Coaching Awaiting Officer Acknowledgement",
        line=345,
        definition="Coaching shared with an officer that the officer has not acknowledged.",
        question="Which officers have not answered their coaching?",
        numerator="coaching records with shared_at set and acknowledged_at empty",
        owner_page="team_coaching",
        roles=_TEAM_ROLES,
        scope=_TEAM_SCOPE,
        category="pending_action",
    ),
    _row(
        "Coaching Follow-Ups Due",
        line=351,
        definition=(
            "Coaching records whose follow-up date has arrived and whose follow-up "
            "the Programme Lead has not closed."
        ),
        question="Which agreed actions should the lead check on now?",
        numerator="coaching records with follow_up_due on or before today and follow_up_done_at empty",
        owner_page="team_coaching",
        roles=_TEAM_ROLES,
        scope=_TEAM_SCOPE,
        category="risk",
    ),
    _row(
        "Coaching Awaiting My Acknowledgement",
        line=1086,
        definition="Coaching shared with the officer that they have not acknowledged yet.",
        question="Which coaching do I still need to answer?",
        numerator="shared coaching records addressed to the officer with acknowledged_at empty",
        owner_page="my_coaching",
        roles=_OFFICER_ROLES,
        scope=_OFFICER_SCOPE,
        category="pending_action",
    ),
    _row(
        "Coaching I Have Acknowledged",
        line=1092,
        definition="Coaching the officer acknowledged with a response.",
        question="How much of my coaching have I answered?",
        numerator="shared coaching records addressed to the officer with acknowledged_at set",
        owner_page="my_coaching",
        roles=_OFFICER_ROLES,
        scope=_OFFICER_SCOPE,
    ),
    _row(
        "Agreed Coaching Actions Open",
        line=1098,
        definition=(
            "Shared coaching with a follow-up date whose follow-up the Programme "
            "Lead has not closed yet."
        ),
        question="Which agreed actions will my lead still follow up?",
        numerator="shared coaching records with follow_up_due set and follow_up_done_at empty",
        owner_page="my_coaching",
        roles=_OFFICER_ROLES,
        scope=_OFFICER_SCOPE,
    ),
)
