"""Metric definitions for Team Guidance — priority guidance a Programme Lead issues to their officers.

Program Lead alignment (owner, 2026-09-13). /priorities/guidance renders its
tiles through ``apps.frontend.views.team_guidance_views._metric``, which only
accepts a label the reconciled registry knows. Rows are appended to the
reconciled registry in reconciled_registry.py; the row shape follows
cce_leadership_metrics.py. The counts come from
apps.cce_leadership.guidance.guidance_counts, over the guidance of the year
the register shows.
"""

from __future__ import annotations

_SOURCE = "apps.frontend.views.team_guidance_views:_metric"
_LOCATION = "apps/frontend/views/team_guidance_views.py"
_GUIDANCE = (
    "apps.cce_leadership.models.TeamGuidance",
    "apps.cce_leadership.models.TeamGuidanceReceipt",
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
    category: str = "progress",
    unit: str = "count",
    period: str = "point_in_time",
    date_basis: str = "not_time_bound",
) -> dict:
    return {
        "key": f"team_guidance_{_slug(label)}",
        "label": label,
        "source_label": label,
        "source": _SOURCE,
        "definition": definition,
        "question": question,
        "category": category,
        "unit": unit,
        "service": "apps.frontend.views.team_guidance_views._metric",
        "source_models": _GUIDANCE,
        "numerator": numerator,
        "denominator": None,
        "date_basis": date_basis,
        "period": period,
        "scope": _SCOPE,
        "owner_page": "team_guidance",
        "filter_behaviour": "fixed_context",
        "drilldown": None,
        "no_drilldown_reason": "The register below the tile lists the guidance it counts.",
        "notes": "Programme Lead Team Guidance, added 2026-09-13.",
        "roles": _ROLES,
        "source_location": f"{_LOCATION}:{line}",
    }


_ROLES = ("Program Lead", "Admin")
_SCOPE = (
    "For a Programme Lead, the guidance they wrote for the financial year the "
    "register shows; Admin reads every lead's "
    "(apps.cce_leadership.guidance.guidance_visible_to)"
)

TEAM_GUIDANCE_METRIC_ROWS: tuple[dict, ...] = (
    _row(
        "Team Guidance Issued",
        line=287,
        definition=(
            "Guidance the Programme Lead issued to officers on their team for the "
            "financial year, excluding withdrawn guidance."
        ),
        question="How much guidance on the priorities has reached the team this year?",
        numerator="TeamGuidance rows with issued_at set and withdrawn_at empty",
    ),
    _row(
        "Guidance Awaiting Officer Acknowledgement",
        line=292,
        definition=(
            "Receipts on issued, not withdrawn guidance that the officer has not "
            "acknowledged yet: one per officer per piece of guidance."
        ),
        question="Which officers have not answered the guidance they received?",
        numerator=(
            "TeamGuidanceReceipt rows with acknowledged_at empty on guidance with "
            "issued_at set and withdrawn_at empty"
        ),
        category="pending_action",
    ),
    _row(
        "Guidance Reviews Due",
        line=298,
        definition=(
            "Issued, not withdrawn guidance whose review date has arrived; the "
            "lead reads the responses and sets the next review or closes it."
        ),
        question="Which guidance should the lead review now?",
        numerator=(
            "TeamGuidance rows with issued_at set, withdrawn_at empty and "
            "review_on on or before today"
        ),
        category="risk",
    ),
    _row(
        "Guidance Drafts Not Issued",
        line=304,
        definition="Guidance the Programme Lead drafted and has not issued or withdrawn.",
        question="Which guidance has not reached the officers yet?",
        numerator="TeamGuidance rows with issued_at and withdrawn_at empty",
        category="pending_action",
    ),
)
