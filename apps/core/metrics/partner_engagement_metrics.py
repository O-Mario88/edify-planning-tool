"""Metric definitions for Partner engagements — capacity-building work with training organisations.

Program Lead alignment (owner, 2026-09-13). The partner engagement register on
Partner Oversight renders its tiles through
``apps.frontend.views.partner_engagement_views._metric``, which only accepts a
label the reconciled registry knows. Rows are appended to the reconciled
registry in reconciled_registry.py; the row shape follows
cce_leadership_metrics.py. The counts come from
apps.partners.engagement_services (engagement_counts,
open_observation_follow_ups) — the same functions the To-Do queue and the
Programme Lead dashboard's engagement_summary read.
"""

from __future__ import annotations

_SOURCE = "apps.frontend.views.partner_engagement_views:_metric"
_LOCATION = "apps/frontend/views/partner_engagement_views.py"
_ENGAGEMENT = ("apps.partners.models.PartnerEngagement",)
_OBSERVATION = (
    "apps.cce_leadership.models.RegionalEngagement",
    "apps.partners.models.PartnerEngagement",
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
    roles: tuple[str, ...],
    scope: str,
    models: tuple[str, ...] = _ENGAGEMENT,
    category: str = "progress",
    unit: str = "count",
    period: str = "point_in_time",
    date_basis: str = "not_time_bound",
    filter_behaviour: str = "filtered",
) -> dict:
    return {
        "key": f"partner_engagement_{_slug(label)}",
        "label": label,
        "source_label": label,
        "source": _SOURCE,
        "definition": definition,
        "question": question,
        "category": category,
        "unit": unit,
        "service": "apps.frontend.views.partner_engagement_views._metric",
        "source_models": models,
        "numerator": numerator,
        "denominator": None,
        "date_basis": date_basis,
        "period": period,
        "scope": scope,
        "owner_page": "partner_oversight",
        "filter_behaviour": filter_behaviour,
        "drilldown": None,
        "no_drilldown_reason": "The register below the tile lists the records it counts.",
        "notes": "Partner engagement log, added 2026-09-13.",
        "roles": roles,
        "source_location": f"{_LOCATION}:{line}",
    }


_ROLES = ("Program Lead", "CountryDirector", "Admin")
_SCOPE = (
    "For a Programme Lead, the engagements they recorded; for the Country "
    "Director, every engagement in their country; Admin reads all "
    "(apps.partners.engagement_services.engagements_visible_to). Narrowed to "
    "the partner tab in view."
)

PARTNER_ENGAGEMENT_METRIC_ROWS: tuple[dict, ...] = (
    _row(
        "Partner Engagements This FY",
        line=198,
        definition=(
            "Engagements with training partners — review meetings, framework "
            "orientations, quality follow-ups, joint planning and capacity-building "
            "sessions — held in the selected financial year."
        ),
        question="How much partnership work did we do with training partners this year?",
        numerator="partner engagements with fy equal to the selected FY",
        roles=_ROLES,
        scope=_SCOPE,
        category="scale",
        period="financial_year",
        date_basis="record_created",
    ),
    _row(
        "Partners Engaged This FY",
        line=203,
        definition=(
            "Distinct training partners with at least one engagement held in the "
            "selected financial year."
        ),
        question="Which training partners have we actually worked with this year?",
        numerator="distinct partners among partner engagements in the selected FY",
        roles=_ROLES,
        scope=_SCOPE,
        category="progress",
        period="financial_year",
        date_basis="record_created",
    ),
    _row(
        "Partner Follow-Ups Due",
        line=208,
        definition=(
            "Engagements whose follow-up date has arrived and whose follow-up the "
            "author has not closed, whatever year the improvements were agreed in."
        ),
        question="Which agreed partner improvements should be checked now?",
        numerator="partner engagements with follow_up_due on or before today and follow_up_done_at empty",
        roles=_ROLES,
        scope=_SCOPE,
        category="pending_action",
    ),
    _row(
        "Regional Lead Observations Awaiting Partner Follow-Up",
        line=217,
        definition=(
            "Regional Lead observations shared with the Programme Lead of a "
            "partner-delivered training that recommend strengthening or replacing "
            "it, with no engagement with that partner recorded on or after the day "
            "it was observed (apps.partners.engagement_services."
            "open_observation_follow_ups)."
        ),
        question="Which Regional Lead observations still need work with the partner?",
        numerator=(
            "shared training observations with recommendation strengthen or replace "
            "on partner-delivered trainings and no later partner engagement"
        ),
        roles=("Program Lead", "Admin"),
        scope=(
            "Observations shared with the Programme Lead "
            "(apps.cce_leadership.services.feedback_visible_to)"
        ),
        models=_OBSERVATION,
        category="risk",
        filter_behaviour="fixed_context",
    ),
)
