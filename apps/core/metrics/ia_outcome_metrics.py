"""Metric definitions for Impact Assessment's school progress surfaces (IA review, owner, 2026-09-13).

Three sources render tiles through ``render_precomputed_metric_for_source``,
which only accepts a label the reconciled registry knows:

  - the Outcomes view (``apps.analytics.ia_workflow._metric``): school change
    across the portfolio and the special-project cohorts;
  - School Evidence (``apps.frontend.views.ia_school_evidence_views._metric``);
  - Most Significant Change (``apps.frontend.views.ia_stories_views._metric``).

A tile with nothing measured reads "Not measured", never 0 (the renderer
records it as no data). Rows are appended to the reconciled registry in
reconciled_registry.py; the row shape follows cce_leadership_metrics.py.
Source lines are read from the source file, so they stay exact as the views
change.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]

_WORKFLOW = "apps/analytics/ia_workflow.py"
_EVIDENCE = "apps/frontend/views/ia_school_evidence_views.py"
_STORIES = "apps/frontend/views/ia_stories_views.py"

_SSA = ("apps.ssa.models.SsaRecord", "apps.ssa.models.SsaScore")
_ENROLMENT = ("apps.projects.models.ProjectSchoolAssignment",) + _SSA
_EVIDENCE_MODELS = (
    "apps.impact.models.LearningAssessmentResult",
    "apps.impact.models.DiscipleshipIndicatorRecord",
    "apps.impact.models.EdTechDeployment",
    "apps.impact.models.EdTechCheck",
)
_STORY = ("apps.targets.models.MostSignificantChangeStory",)
_OUTCOME_ROLES = ("ImpactAssessment", "CountryDirector", "Admin")
_STORY_ROLES = ("ImpactAssessment", "Admin")

_COUNTRY_SCOPE = (
    "Schools in the reader's analytics scope: the country for Impact Assessment "
    "and the Country Director, the deployment for Admin "
    "(apps.core.scoping.scoped_school_queryset)"
)


def _slug(text: str) -> str:
    out = "".join(ch if ch.isalnum() else "_" for ch in text.lower())
    while "__" in out:
        out = out.replace("__", "_")
    return out.strip("_")


@lru_cache(maxsize=8)
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
    source: str,
    service: str,
    definition: str,
    question: str,
    numerator: str,
    models: tuple[str, ...],
    category: str,
    owner_page: str,
    roles: tuple[str, ...],
    scope: str = _COUNTRY_SCOPE,
    unit: str = "count",
    denominator: str | None = None,
    period: str = "point_in_time",
    date_basis: str = "not_time_bound",
    filter_behaviour: str = "fixed_context",
    drilldown: str | None = None,
) -> dict:
    return {
        "key": f"ia_outcome_{_slug(label)}",
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
        "drilldown": drilldown,
        "no_drilldown_reason": None
        if drilldown
        else "The table below the tile lists the records it counts.",
        "notes": "IA school progress and new measures, added 2026-09-13.",
        "roles": roles,
        "source_location": f"{path}:{_line(path, label)}",
    }


def _portfolio(label, **kw):
    return _row(
        label,
        path=_WORKFLOW,
        source="apps.analytics.ia_workflow:_metric",
        service="apps.analytics.ia_workflow.portfolio_change",
        owner_page="ia_dashboard",
        roles=_OUTCOME_ROLES,
        models=_SSA,
        period="financial_year",
        date_basis="ssa_assessment_date",
        filter_behaviour="filtered",
        **kw,
    )


def _cohort(label, **kw):
    kw.setdefault("models", _ENROLMENT)
    return _row(
        label,
        path=_WORKFLOW,
        source="apps.analytics.ia_workflow:_metric",
        service="apps.analytics.ia_workflow.outcome_workspace",
        owner_page="ia_dashboard",
        roles=_OUTCOME_ROLES,
        filter_behaviour="filtered",
        **kw,
    )


def _evidence(label, **kw):
    return _row(
        label,
        path=_EVIDENCE,
        source="apps.frontend.views.ia_school_evidence_views:_metric",
        service="apps.impact.evidence_services.counts",
        owner_page="ia_school_evidence",
        roles=_OUTCOME_ROLES,
        models=_EVIDENCE_MODELS,
        **kw,
    )


def _story(label, **kw):
    return _row(
        label,
        path=_STORIES,
        source="apps.frontend.views.ia_stories_views:_metric",
        service="apps.targets.mscs_review.visible_stories",
        owner_page="ia_stories",
        roles=_STORY_ROLES,
        models=_STORY,
        scope=(
            "Stories whose school is in the reader's country, or with no school "
            "whose author is (apps.targets.mscs_review.visible_stories)"
        ),
        **kw,
    )


IA_OUTCOME_METRIC_ROWS: tuple[dict, ...] = (
    # ── Outcomes view: school change across the portfolio ─────────────────
    _portfolio(
        "Schools With Paired Confirmed SSAs",
        definition=(
            "Schools in scope with a confirmed SSA in the chosen financial year and "
            "the year before whose readings are far enough apart to compare "
            "(apps.ssa.change_rules.MIN_INTERVAL_DAYS), shown against every school "
            "in scope."
        ),
        question="How much of the portfolio can school change be measured for?",
        numerator="schools with at least one comparable confirmed SSA domain pair",
        denominator="operational schools in the reader's scope",
        category="quality",
        unit="status",
    ),
    _portfolio(
        "Schools Improved (Share of Measured)",
        definition=(
            "Of the schools with comparable confirmed SSAs, the share whose mean "
            "change across comparable domains classifies as improved under the "
            "published IA measurement rules (apps.ssa.change_rules)."
        ),
        question="In how many measured schools did the SSA move the expected way?",
        numerator="schools whose SSA change classifies as improved",
        denominator="schools with comparable confirmed SSAs in both years",
        category="outcome",
        unit="percent",
    ),
    _portfolio(
        "Schools Declined (Share of Measured)",
        definition=(
            "Of the schools with comparable confirmed SSAs, the share whose mean "
            "change across comparable domains classifies as declined under the "
            "published IA measurement rules — the same rule Declining Schools uses."
        ),
        question="In how many measured schools did the SSA fall?",
        numerator="schools whose SSA change classifies as declined",
        denominator="schools with comparable confirmed SSAs in both years",
        category="risk",
        unit="percent",
    ),
    _portfolio(
        "Median Days Between Paired SSAs",
        definition=(
            "The median number of days between the two confirmed readings compared "
            "for each measured school."
        ),
        question="Over what span is the school change measured?",
        numerator="median days between paired confirmed SSA dates",
        category="quality",
        unit="days",
    ),
    # ── Outcomes and Reports views: special-project cohorts ───────────────
    _cohort(
        "Project Enrolments Measured",
        definition=(
            "Special-project enrolments with a confirmed baseline and a confirmed "
            "later follow-up, against every enrolment in scope; unique schools are "
            "named beside it because a school may be in several projects."
        ),
        question="How many project enrolments have measurable evidence?",
        numerator="enrolments with a valid confirmed baseline and follow-up",
        denominator="project enrolments in scope",
        category="quality",
        unit="status",
    ),
    _cohort(
        "Project Enrolments Improved",
        definition=(
            "Of the measured project enrolments, the share whose stored "
            "classification is improved."
        ),
        question="Did enrolled schools move the way the project intends?",
        numerator="measured enrolments classified improved",
        denominator="measured project enrolments",
        category="outcome",
        unit="percent",
    ),
    _cohort(
        "Project Enrolments Declined",
        definition=(
            "Of the measured project enrolments, the share whose stored "
            "classification is declined."
        ),
        question="Which project cohorts lost ground?",
        numerator="measured enrolments classified declined",
        denominator="measured project enrolments",
        category="risk",
        unit="percent",
    ),
    _cohort(
        "Project Enrolments Missing a Baseline",
        definition=(
            "Project enrolments without a valid confirmed baseline: either no "
            "confirmed SSA exists yet or it has not been captured."
        ),
        question="Which enrolments cannot be measured until a baseline exists?",
        numerator="enrolments whose baseline is missing, unconfirmed or invalid",
        category="pending_action",
        drilldown="/ia/dashboard/?view=collection",
    ),
    _cohort(
        "Project Follow-ups Overdue",
        definition=(
            "Project enrolments with a baseline but no follow-up whose follow-up "
            "window has passed."
        ),
        question="Which follow-up assessments are late?",
        numerator="enrolments past their follow-up due date without a follow-up",
        category="risk",
        drilldown="/ia/dashboard/?view=collection",
    ),
    # ── School Evidence ───────────────────────────────────────────────────
    _evidence(
        "School Evidence Awaiting Verification",
        definition=(
            "Learning results, discipleship records, EdTech deployments and checks "
            "in scope that wait for someone other than the recorder to confirm them."
        ),
        question="What school evidence is waiting for a second reader?",
        numerator="pending school evidence records",
        category="pending_action",
    ),
    _evidence(
        "Schools With Confirmed Learning Results",
        definition="Schools in scope with at least one confirmed class-level learning result.",
        question="For how many schools is student learning evidenced?",
        numerator="distinct schools with a confirmed learning result",
        category="quality",
    ),
    _evidence(
        "Schools With Confirmed Discipleship Records",
        definition="Schools in scope with at least one confirmed discipleship practice record.",
        question="For how many schools is discipleship practice evidenced?",
        numerator="distinct schools with a confirmed discipleship record",
        category="quality",
    ),
    _evidence(
        "Schools With Confirmed EdTech Deployments",
        definition="Schools in scope with at least one confirmed EdTech deployment.",
        question="How far has educational technology reached?",
        numerator="distinct schools with a confirmed EdTech deployment",
        category="scale",
    ),
    _evidence(
        "School Evidence Returned for Correction",
        definition="School evidence records a verifier returned to their recorder.",
        question="What evidence is waiting for its recorder to correct it?",
        numerator="returned school evidence records",
        category="pending_action",
    ),
    # ── Most Significant Change ───────────────────────────────────────────
    _story(
        "Change Stories Awaiting Review",
        definition="Submitted Most Significant Change stories not yet reviewed.",
        question="Which change stories wait for review?",
        numerator="submitted stories",
        category="pending_action",
    ),
    _story(
        "Change Stories Approved This Year",
        definition=(
            "Stories dated in the financial year that a reviewer other than the "
            "author approved as evidence of change."
        ),
        question="How much reviewed qualitative evidence of change is there?",
        numerator="approved stories dated in the financial year",
        category="quality",
        period="financial_year",
        date_basis="approval_date",
        filter_behaviour="filtered",
    ),
    _story(
        "Change Stories Returned or Rejected This Year",
        definition="Stories dated in the financial year that a reviewer returned or rejected.",
        question="How many stories did not stand as evidence?",
        numerator="returned or rejected stories dated in the financial year",
        category="quality",
        period="financial_year",
        date_basis="approval_date",
        filter_behaviour="filtered",
    ),
)
