"""Metric definitions for Impact Assessment programme learning (training, lending, EdTech, visits).

IA review (owner, 2026-09-13). Two pages render tiles through
``render_precomputed_metric_for_source``, which only accepts a label the
reconciled registry knows:

  - Programme Learning (``apps.frontend.views.ia_learning_views._metric``):
    each programme tab's outputs strip, labelled "delivery, not impact" — so
    every one of these is SCALE or PROGRESS, never OUTCOME (the outcome is the
    table below the tiles, with its sample sizes and evidence grade) — and the
    Findings tab's review counts;
  - Lending Evidence (``apps.frontend.views.ia_lending_views._metric``): what
    waits for verification, preparation or correction.

Rows are appended to the reconciled registry in reconciled_registry.py; the
row shape follows cce_leadership_metrics.py. Source lines are read from the
view files, so they stay exact as the views change.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]

_LEARNING = "apps/frontend/views/ia_learning_views.py"
_LENDING = "apps/frontend/views/ia_lending_views.py"

_ACTIVITY = ("apps.activities.models.Activity",)
_SSA_PAIRS = ("apps.ssa.models.SsaRecord", "apps.ssa.models.SsaScore")
_OBSERVATION = ("apps.cce_leadership.models.RegionalEngagement",)
_LOANS = (
    "apps.business_transformation.models.MfiLoan",
    "apps.business_transformation.models.LoanDisbursement",
)
_ALLOCATION = ("apps.business_transformation.models.LoanPurposeAllocation",)
_CONCLUSION = ("apps.business_transformation.models.LoanImpactAssessment",)
_LENDING_EVIDENCE = (
    "apps.business_transformation.models.LoanPurposeAllocation",
    "apps.business_transformation.models.EnrolmentSnapshot",
    "apps.business_transformation.models.PurposeSpecificAssetOutput",
    "apps.business_transformation.models.TeacherDegreeUpgradeBeneficiary",
)
_DEPLOYMENT = (
    "apps.impact.models.EdTechDeployment",
    "apps.impact.models.EdTechCheck",
)
_FINDING = ("apps.impact.models.ImpactFinding",)

_ROLES = ("ImpactAssessment", "CountryDirector", "Admin")

_COUNTRY_SCOPE = (
    "Schools in the reader's analytics scope: the country for Impact Assessment "
    "and the Country Director, the deployment for Admin "
    "(apps.analytics.programme_effectiveness.scoped_countries)"
)
_LOAN_SCOPE = (
    "Loans at schools in the reader's impact reach: the country for Impact "
    "Assessment, the Country Director and Business Transformation "
    "(apps.business_transformation.lending_impact.scoped_impact_loans)"
)
_FINDING_SCOPE = (
    "Findings of the reader's country; Admin reads every country "
    "(apps.impact.findings.visible_findings)"
)


def _slug(text: str) -> str:
    out = "".join(ch if ch.isalnum() else "_" for ch in text.lower())
    while "__" in out:
        out = out.replace("__", "_")
    return out.strip("_")


@lru_cache(maxsize=4)
def _source_lines(path: str) -> tuple[str, ...]:
    try:
        return tuple((_ROOT / path).read_text(encoding="utf-8").splitlines())
    except OSError:
        return ()


def _line(path: str, label: str) -> int:
    needle = f'"{label}"'
    for number, text in enumerate(_source_lines(path), start=1):
        if needle in text:
            return number
    return 1


def _row(
    label: str,
    *,
    path: str,
    service: str,
    definition: str,
    question: str,
    numerator: str,
    models: tuple[str, ...],
    owner_page: str,
    scope: str,
    category: str = "scale",
    unit: str = "count",
    denominator: str | None = None,
    period: str = "point_in_time",
    date_basis: str = "not_time_bound",
    filter_behaviour: str = "fixed_context",
) -> dict:
    source = (
        "apps.frontend.views.ia_learning_views:_metric"
        if path == _LEARNING
        else "apps.frontend.views.ia_lending_views:_metric"
    )
    return {
        "key": f"ia_learning_{_slug(label)}",
        "label": label,
        "source_label": label,
        "source": source,
        "definition": definition,
        "question": question,
        "category": category,
        "unit": unit,
        "service": service,
        "source_models": models,
        "numerator": numerator,
        "denominator": denominator,
        "date_basis": date_basis,
        "period": period,
        "scope": scope,
        "owner_page": owner_page,
        "filter_behaviour": filter_behaviour,
        "drilldown": None,
        "no_drilldown_reason": "The table below the tile lists what it counts.",
        "notes": "IA programme learning and lending evidence, added 2026-09-13.",
        "roles": _ROLES,
        "source_location": f"{path}:{_line(path, label)}",
    }


def _tab(label, **kw):
    kw.setdefault("scope", _COUNTRY_SCOPE)
    kw.setdefault("filter_behaviour", "filtered")
    return _row(label, path=_LEARNING, owner_page="ia_learning", **kw)


def _lending(label, **kw):
    return _row(
        label,
        path=_LENDING,
        owner_page="ia_lending_evidence",
        scope=_LOAN_SCOPE,
        category="pending_action",
        **kw,
    )


IA_LEARNING_METRIC_ROWS: tuple[dict, ...] = (
    # ── Training tab (delivery, not impact) ───────────────────────────────
    _tab(
        "Verified Trainings in the Compared Years",
        service="apps.analytics.programme_effectiveness.training_tab",
        definition=(
            "IA-verified training activities dated in the two financial years "
            "compared, or inside a measured school's SSA window, for the chosen "
            "training, delivery mode and deliverer."
        ),
        question="How much verified training is the outcome table judging?",
        numerator="distinct IA-verified training activities",
        models=_ACTIVITY,
        period="financial_year",
        date_basis="activity_execution_date",
    ),
    _tab(
        "Schools Reached by Verified Trainings",
        service="apps.analytics.programme_effectiveness.training_tab",
        definition=(
            "Schools in scope attended by those IA-verified trainings, directly or "
            "through a cluster attendance list."
        ),
        question="How many schools did the training reach, measured or not?",
        numerator="distinct schools attributed to the trainings",
        models=_ACTIVITY,
        period="financial_year",
        date_basis="activity_execution_date",
    ),
    _tab(
        "Training Observations Shared With IA",
        service="apps.analytics.programme_effectiveness.training_tab",
        definition=(
            "Regional Lead training observations on those trainings that were "
            "shared and are in the reader's country — evidence of delivery "
            "quality, never of outcome."
        ),
        question="How much of the training has an independent quality observation?",
        numerator="shared training observations on the selected trainings",
        models=_OBSERVATION,
        category="quality",
        scope=(
            "Shared observations on the reader's country "
            "(apps.cce_leadership.services.feedback_visible_to)"
        ),
    ),
    # ── Lending tab ───────────────────────────────────────────────────────
    _tab(
        "Schools With Disbursed School Loans",
        service="apps.analytics.programme_effectiveness.lending_tab",
        definition=(
            "Schools in scope with at least one confirmed loan disbursement that "
            "has not been reversed."
        ),
        question="How many schools has lending reached?",
        numerator="distinct schools with a non-reversed disbursement",
        models=_LOANS,
        scope=_LOAN_SCOPE,
        filter_behaviour="fixed_context",
    ),
    _tab(
        "Loan Purpose Use Verified by IA",
        service="apps.analytics.programme_effectiveness.lending_tab",
        definition="Loan purpose allocations whose reported use Impact Assessment verified.",
        question="How much reported loan use has been checked?",
        numerator="purpose allocations with status verified",
        models=_ALLOCATION,
        category="progress",
        scope=_LOAN_SCOPE,
        filter_behaviour="fixed_context",
    ),
    _tab(
        "Loan Impact Conclusions Verified",
        service="apps.analytics.programme_effectiveness.lending_tab",
        definition=(
            "Loan impact conclusions prepared by one person and verified by "
            "another, for the chosen loan purpose."
        ),
        question="How many financed schools have a checked impact conclusion?",
        numerator="loan impact assessments with IA status verified",
        models=_CONCLUSION,
        category="progress",
        scope=_LOAN_SCOPE,
    ),
    # ── EdTech tab ────────────────────────────────────────────────────────
    _tab(
        "Verified EdTech Trainings",
        service="apps.analytics.programme_effectiveness.edtech_tab",
        definition=(
            "IA-verified activities of the EdTech catalogue category or the EdTech "
            "Pilot project, in the two financial years compared or inside a "
            "measured school's window."
        ),
        question="How much verified EdTech delivery is there?",
        numerator="distinct IA-verified EdTech activities",
        models=_ACTIVITY,
        period="financial_year",
        date_basis="activity_execution_date",
        filter_behaviour="fixed_context",
    ),
    _tab(
        "Confirmed EdTech Deployments in Scope",
        service="apps.analytics.programme_effectiveness.edtech_tab",
        definition="EdTech deployments at schools in scope confirmed by a second reader.",
        question="How far has technology been deployed?",
        numerator="confirmed EdTech deployments",
        models=_DEPLOYMENT,
        filter_behaviour="fixed_context",
    ),
    _tab(
        "EdTech Units Working at Last Check",
        service="apps.analytics.programme_effectiveness.edtech_tab",
        definition=(
            "Of the units in confirmed deployments that have a confirmed check, the "
            "share working at the latest check."
        ),
        question="Is the technology schools received still working?",
        numerator="units functional at each deployment's latest confirmed check",
        denominator="units in confirmed deployments with a confirmed check",
        models=_DEPLOYMENT,
        category="quality",
        unit="percent",
        filter_behaviour="fixed_context",
    ),
    _tab(
        "EdTech Loans Disbursed to Schools",
        service="apps.analytics.programme_effectiveness.edtech_tab",
        definition="Schools in scope with a non-reversed disbursement on an EdTech loan purpose.",
        question="How much of EdTech rollout is financed by loans?",
        numerator="distinct schools with an EdTech-purpose disbursement",
        models=_LOANS,
        scope=_LOAN_SCOPE,
        filter_behaviour="fixed_context",
    ),
    # ── Visits tab ────────────────────────────────────────────────────────
    _tab(
        "Verified Visits in SSA Windows",
        service="apps.analytics.programme_effectiveness.visits_tab",
        definition=(
            "IA-verified visit activities dated between a measured school's two "
            "confirmed SSA readings."
        ),
        question="How many verified visits does the visit comparison rest on?",
        numerator="distinct IA-verified visits inside SSA windows",
        models=_ACTIVITY + _SSA_PAIRS,
        period="financial_year",
        date_basis="activity_execution_date",
        filter_behaviour="fixed_context",
    ),
    _tab(
        "Schools With a Verified Visit in Window",
        service="apps.analytics.programme_effectiveness.visits_tab",
        definition="Measured schools with at least one IA-verified visit inside their SSA window.",
        question="How many measured schools were visited?",
        numerator="distinct measured schools with a verified visit in window",
        models=_ACTIVITY + _SSA_PAIRS,
        period="financial_year",
        date_basis="activity_execution_date",
        filter_behaviour="fixed_context",
    ),
    # ── Findings tab ──────────────────────────────────────────────────────
    _tab(
        "Impact Findings Awaiting Review",
        service="apps.impact.findings.counts",
        definition="Findings submitted for review by someone other than their author.",
        question="Which conclusions wait for a second reader?",
        numerator="findings in review",
        models=_FINDING,
        category="pending_action",
        scope=_FINDING_SCOPE,
        filter_behaviour="fixed_context",
    ),
    _tab(
        "Impact Findings Approved This Year",
        service="apps.impact.findings.counts",
        definition="Findings approved by a reviewer during the chosen financial year.",
        question="How many reviewed conclusions can reports cite?",
        numerator="findings approved in the financial year",
        models=_FINDING,
        category="quality",
        scope=_FINDING_SCOPE,
        period="financial_year",
        date_basis="approval_date",
    ),
    _tab(
        "Impact Findings Returned to Authors",
        service="apps.impact.findings.counts",
        definition="Findings a reviewer returned for the author to change.",
        question="Which conclusions need their author's correction?",
        numerator="returned findings",
        models=_FINDING,
        category="pending_action",
        scope=_FINDING_SCOPE,
        filter_behaviour="fixed_context",
    ),
    # ── Lending Evidence ──────────────────────────────────────────────────
    _lending(
        "Lending Evidence Awaiting IA Verification",
        service="apps.frontend.views.ia_lending_views.queue_counts",
        definition=(
            "Reported loan use, enrolment snapshots, purpose outputs and teacher "
            "completions Impact Assessment has not verified."
        ),
        question="What lending evidence waits for verification?",
        numerator="reported evidence records across the four queues",
        models=_LENDING_EVIDENCE,
    ),
    _lending(
        "Loan Impact Conclusions to Prepare",
        service="apps.frontend.views.ia_lending_views.queue_counts",
        definition="Loan impact assessments that are due and not yet prepared.",
        question="Which due conclusions has nobody prepared?",
        numerator="due, pending assessments with no preparer",
        models=_CONCLUSION,
    ),
    _lending(
        "Loan Impact Conclusions Awaiting Verification",
        service="apps.frontend.views.ia_lending_views.queue_counts",
        definition="Prepared loan impact conclusions waiting for someone other than the preparer.",
        question="Which prepared conclusions wait for verification?",
        numerator="prepared, pending assessments",
        models=_CONCLUSION,
    ),
    _lending(
        "Loan Impact Conclusions Returned",
        service="apps.frontend.views.ia_lending_views.queue_counts",
        definition="Loan impact conclusions a verifier returned to their preparer.",
        question="Which conclusions need their preparer's correction?",
        numerator="returned assessments",
        models=_CONCLUSION,
    ),
)
