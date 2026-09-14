"""Metric definitions for Impact Assessment's collection worklist.

IA review (owner, 2026-09-13). The Collection view renders its tiles through
``apps.analytics.ia_collection.collection_tiles``, which only accepts a label
the reconciled registry knows. Rows are appended to the reconciled registry in
reconciled_registry.py; the row shape follows cce_leadership_metrics.py.
"""

from __future__ import annotations

_SOURCE = "apps.analytics.ia_collection:collection_tiles"
_LOCATION = "apps/analytics/ia_collection.py"
_SERVICE = "apps.analytics.ia_collection.collection_worklist"
_SCHOOLS = ("apps.schools.models.School", "apps.ssa.models.SsaRecord")
_ROLES = ("ImpactAssessment", "CountryDirector", "Admin")
_SCOPE = (
    "Operationally active schools in the reader's country (the deployment for "
    "Admin), after the Collection view's district, owner, school type and "
    "project filters (apps.analytics.ia_collection.collection_schools)"
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
    category: str,
    filter_behaviour: str = "fixed_context",
) -> dict:
    return {
        "key": f"ia_collection_{_slug(label)}",
        "label": label,
        "source_label": label,
        "source": _SOURCE,
        "definition": definition,
        "question": question,
        "category": category,
        "unit": "count",
        "service": _SERVICE,
        "source_models": models,
        "numerator": numerator,
        "denominator": None,
        "date_basis": "not_time_bound",
        "period": "point_in_time",
        "scope": _SCOPE,
        "owner_page": "ia_dashboard",
        "filter_behaviour": filter_behaviour,
        "drilldown": None,
        "no_drilldown_reason": "The collection worklist below the tile lists the schools it counts.",
        "notes": "IA collection worklist, added 2026-09-13.",
        "roles": _ROLES,
        "source_location": f"{_LOCATION}:{line}",
    }


IA_COLLECTION_METRIC_ROWS: tuple[dict, ...] = (
    _row(
        "Schools Never Assessed",
        line=586,
        definition=(
            "Operationally active schools in scope with no confirmed SSA on record, "
            "no pending or returned record, and no SSA collection visit open: the "
            "true missing baselines."
        ),
        question="Which schools have never had a confirmed assessment?",
        numerator="schools whose collection_state is never_assessed",
        models=_SCHOOLS,
        category="risk",
    ),
    _row(
        "SSA Follow-up Due",
        line=592,
        definition=(
            "Operationally active schools in scope with a confirmed SSA from an "
            "earlier financial year and none confirmed, pending or planned in the "
            "current one."
        ),
        question="Which assessed schools are due this year's follow-up SSA?",
        numerator="schools whose collection_state is follow_up_due",
        models=_SCHOOLS,
        category="risk",
    ),
    _row(
        "SSA Awaiting Verification",
        line=598,
        definition=(
            "Schools whose latest SSA is pending: scores keyed by staff, Impact "
            "Assessment, a file import or a partner, waiting for a verifier other "
            "than their collector. They count nowhere until confirmed."
        ),
        question="How many schools' latest scores still wait for a verifier?",
        numerator="schools whose collection_state is pending_verification or partner_pending",
        models=_SCHOOLS,
        category="readiness",
    ),
    _row(
        "Unmatched SSA Import Rows",
        line=604,
        definition=(
            "Imported SSA rows still pending or on hold because no school matched "
            "their School ID, placed in the country of the person who uploaded "
            "the batch (or of the suggested school)."
        ),
        question="How many imported assessments belong to no school yet?",
        numerator="UnmatchedSSARecord rows with status pending or hold in the reader's country",
        models=("apps.schools.models.UnmatchedSSARecord",),
        category="compliance",
    ),
)
