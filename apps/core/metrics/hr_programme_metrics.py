"""Metric definitions for the Regional HR Director's programme registers.

The HR register pages render their tiles through
``apps.frontend.views.hr_views._metric``, which only accepts a label the
reconciled registry knows. The registers rebuilt on 2026-09-13 count things
the old ones did not (cases awaiting triage, disciplinary matters, vacancies by
real status), so their definitions live here and are appended to the
reconciled rows in ``reconciled_registry.py``. One row per label: a label is
shared by every HR register that renders it.
"""

from __future__ import annotations

_SOURCE = "apps.frontend.views.hr_views:_metric"
_HR_ROLES = ("HumanResources", "Admin")


def _slug(text: str) -> str:
    out = "".join(ch if ch.isalnum() else "_" for ch in text.lower())
    while "__" in out:
        out = out.replace("__", "_")
    return out.strip("_")


def _row(
    label: str,
    *,
    definition: str,
    question: str,
    numerator: str,
    models: tuple[str, ...],
    owner_page: str,
    location: str,
    category: str = "scale",
    unit: str = "count",
    drilldown: str | None = None,
) -> dict:
    return {
        "key": f"hr_programme_{_slug(label)}",
        "label": label,
        "source_label": label,
        "source": _SOURCE,
        "definition": definition,
        "question": question,
        "category": category,
        "unit": unit,
        "service": "apps.frontend.views.hr_views._metric",
        "source_models": models,
        "numerator": numerator,
        "date_basis": "not_time_bound",
        "period": "point_in_time",
        "scope": "The countries the Regional HR Director oversees (apps.hr.reach)",
        "owner_page": owner_page,
        "filter_behaviour": "partial",
        "drilldown": drilldown,
        "no_drilldown_reason": None
        if drilldown
        else "The register below the tile lists the records it counts.",
        "notes": "HR programme register rebuilt 2026-09-13.",
        "roles": _HR_ROLES,
        "source_location": location,
    }


_ER = ("apps.hr.models.EmployeeRelationsCase",)
_VACANCY = ("apps.hr.models.Vacancy",)
_APPLICATION = ("apps.hr.models.Application",)
_ONBOARDING = ("apps.hr.models.OnboardingPlan",)
_OFFBOARDING = ("apps.hr.models.OffboardingPlan",)

HR_PROGRAMME_METRIC_ROWS: tuple[dict, ...] = (
    _row(
        "Awaiting triage",
        definition=(
            "Open employee-relations cases that are submitted or in restricted "
            "triage, in the countries the director oversees."
        ),
        question="How many cases still need a first assessment?",
        numerator="cases with status submitted or triage",
        models=_ER,
        owner_page="employee_relations",
        location="apps/frontend/views/hr_views.py:employee_relations_view",
        category="risk",
    ),
    _row(
        "Under investigation",
        definition=(
            "Open employee-relations cases between investigation and appeal: "
            "investigation, findings recorded, action decided or under appeal."
        ),
        question="How many cases are being investigated or decided?",
        numerator="cases with status investigation, findings, action or appeal",
        models=_ER,
        owner_page="employee_relations",
        location="apps/frontend/views/hr_views.py:employee_relations_view",
        category="pending_action",
    ),
    _row(
        "Disciplinary matters",
        definition="Open employee-relations cases of the disciplinary type.",
        question="How many disciplinary matters are open?",
        numerator="open cases with case_type disciplinary",
        models=_ER,
        owner_page="employee_relations",
        location="apps/frontend/views/hr_views.py:employee_relations_view",
        category="risk",
    ),
    _row(
        "Replacements",
        definition=(
            "Open or pending vacancies raised to replace someone who left, rather "
            "than a new role."
        ),
        question="How many posts are waiting to replace leavers?",
        numerator="vacancies pending, approved or open with replacement_or_new_role replacement",
        models=_VACANCY,
        owner_page="recruitment",
        location="apps/frontend/views/hr_views.py:recruitment_view",
        category="capacity",
    ),
    _row(
        "Offers",
        definition="Applications at the offer stage or with an accepted offer.",
        question="How many candidates hold an offer?",
        numerator="applications with stage offer or accepted",
        models=_APPLICATION,
        owner_page="candidate_pipeline",
        location="apps/frontend/views/hr_views.py:candidate_pipeline_view",
        category="progress",
    ),
    _row(
        "Awaiting supervisor",
        definition=(
            "Onboarding plans waiting for the supervisor to confirm the new "
            "employee is ready."
        ),
        question="How many new hires are waiting on their supervisor?",
        numerator="onboarding plans with status supervisor_review",
        models=_ONBOARDING,
        owner_page="onboarding",
        location="apps/frontend/views/hr_views.py:onboarding_view",
        category="pending_action",
    ),
    _row(
        "Ready for activation",
        definition="Onboarding plans confirmed ready, which HR can close to activate.",
        question="How many new hires can HR activate now?",
        numerator="onboarding plans with status ready_for_activation",
        models=_ONBOARDING,
        owner_page="onboarding",
        location="apps/frontend/views/hr_views.py:onboarding_view",
        category="readiness",
    ),
    _row(
        "Voluntary exits",
        definition="Offboardings whose reason is a resignation or a retirement.",
        question="How many people chose to leave?",
        numerator="offboarding plans with exit_reason resignation or retirement",
        models=_OFFBOARDING,
        owner_page="offboarding",
        location="apps/frontend/views/hr_views.py:offboarding_view",
        category="risk",
    ),
)
