"""Metric definitions for the Impact Assessment measurement framework register.

IA review (owner, 2026-09-13). The Measurement Framework page
(/ia/framework/) renders its tiles through
``apps.frontend.views.ia_framework_views._metric``, which only accepts a label
the reconciled registry knows. Rows are appended to the reconciled registry in
reconciled_registry.py; the row shape follows cce_leadership_metrics.py.
"""

from __future__ import annotations

_SOURCE = "apps.frontend.views.ia_framework_views:_metric"
_LOCATION = "apps/frontend/views/ia_framework_views.py"
_SERVICE = "apps.impact.framework.framework_counts"
_MAPPING = ("apps.activity_catalogue.models.ActivityInterventionMapping",)
_ROLES = ("ImpactAssessment", "CountryDirector", "Admin")
_SCOPE = (
    "Deployment-wide framework definitions: every active school-outcome "
    "catalogue item, published measurement rule, indicator and loan purpose"
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
    denominator: str | None = None,
) -> dict:
    return {
        "key": f"ia_framework_{_slug(label)}",
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
        "denominator": denominator,
        "date_basis": "not_time_bound",
        "period": "point_in_time",
        "scope": _SCOPE,
        "owner_page": "ia_framework",
        "filter_behaviour": "fixed_context",
        "drilldown": None,
        "no_drilldown_reason": "The register below the tile lists the records it counts.",
        "notes": "IA measurement framework register, added 2026-09-13.",
        "roles": _ROLES,
        "source_location": f"{_LOCATION}:{line}",
    }


IA_FRAMEWORK_METRIC_ROWS: tuple[dict, ...] = (
    _row(
        "Activities Without a Measurement Rule",
        line=104,
        definition=(
            "Active catalogue activities with a school outcome (school-facing, "
            "cluster-delivered or training courses) that have no live primary "
            "measurement rule."
        ),
        question="Which programme steps can the framework not yet judge?",
        numerator="school-outcome catalogue items without an active primary mapping",
        models=("apps.activity_catalogue.models.ActivityCatalogueItem",) + _MAPPING,
        category="risk",
    ),
    _row(
        "Measurement Rules Published",
        line=110,
        definition=(
            "Live measurement rules published by a second reviewer (another IA "
            "officer, or the Country Director's acknowledgement where the country "
            "has one officer). Reference defaults nobody reviewed are not counted."
        ),
        question="How much of the framework has been independently reviewed?",
        numerator="active mappings with status published, excluding not-measured records",
        models=_MAPPING,
        category="compliance",
    ),
    _row(
        "Published Rules Without a Follow-up Window",
        line=115,
        definition=(
            "Published measurement rules with no earliest, expected or latest "
            "follow-up day: any later confirmed reading judges the work."
        ),
        question="Which published rules still let any later reading judge the work?",
        numerator="published active mappings with all three follow-up day fields empty",
        models=_MAPPING,
        category="risk",
    ),
    _row(
        "Indicators Approved",
        line=121,
        definition=(
            "Indicator definitions in their current approved version (earlier "
            "versions are superseded, not counted). Loan-purpose measurement "
            "profiles are counted under loan purposes."
        ),
        question="How many measures of success are defined and reviewed?",
        numerator="indicator definitions with status approved",
        models=("apps.impact.models.IndicatorDefinition",),
        category="readiness",
    ),
    _row(
        "Loan Purposes Without Measurement",
        line=126,
        definition=(
            "Active loan purposes whose measurement profile (impact indicators, "
            "evidence and verification method) is not complete."
        ),
        question="Which lending purposes have no defined outcome measure?",
        numerator="active loan purposes with measurement_profile_complete false",
        models=("apps.business_transformation.models.LoanPurpose",),
        category="risk",
    ),
)
