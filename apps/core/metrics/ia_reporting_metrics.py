"""Metric definitions for Impact Assessment reports and their release.

IA review (owner, 2026-09-13). Three surfaces render these tiles through
``apps.impact.reports._metric``, which only accepts a label the reconciled
registry knows:

  - Impact Reports (/ia/impact-reports/) and the IA dashboard's Reports view:
    what waits for review or correction, what was released this year, the
    recommendations still waiting for the Country Director, and the donor
    versions waiting for an RVP;
  - the Country Director dashboard's "Impact findings" section (operations
    view): the latest release, reports only the CD can acknowledge, and the
    recommendations awaiting a response or overdue.

None of them is an OUTCOME: they count reports and decisions, not change in
schools — the outcomes are inside the reports, with their evidence grades.

Rows are appended to the reconciled registry in reconciled_registry.py; the
row shape follows cce_leadership_metrics.py. Source lines are read from
apps/impact/reports.py, so they stay exact as the service changes.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_PATH = "apps/impact/reports.py"
_SOURCE = "apps.impact.reports:_metric"

_REPORT = ("apps.impact.models.ImpactReport",)
_RECOMMENDATION = (
    "apps.impact.models.ImpactReportRecommendation",
    "apps.impact.models.ImpactReport",
)
_RELEASE = (
    "apps.impact.models.ImpactReportRelease",
    "apps.impact.models.ImpactReport",
)

_REGISTER_ROLES = (
    "ImpactAssessment",
    "CountryDirector",
    "RegionalVicePresident",
    "Admin",
)
_CD_ROLES = ("CountryDirector",)

_REPORT_SCOPE = (
    "Reports of the reader's country for Impact Assessment and the Country "
    "Director; reviewed and released reports of the RVP's region; every country "
    "for Admin (apps.impact.reports.visible_reports)"
)
_CD_SCOPE = (
    "Reports of the Country Director's country (apps.impact.reports.visible_reports)"
)


def _slug(text: str) -> str:
    out = "".join(ch if ch.isalnum() else "_" for ch in text.lower())
    while "__" in out:
        out = out.replace("__", "_")
    return out.strip("_")


@lru_cache(maxsize=1)
def _source_lines() -> tuple[str, ...]:
    try:
        return tuple((_ROOT / _PATH).read_text(encoding="utf-8").splitlines())
    except OSError:
        return ()


def _line(label: str) -> int:
    needle = f'"{label}"'
    for number, text in enumerate(_source_lines(), start=1):
        if needle in text:
            return number
    return 1


def _row(
    label: str,
    *,
    service: str,
    definition: str,
    question: str,
    numerator: str,
    models: tuple[str, ...],
    owner_page: str,
    roles: tuple[str, ...],
    scope: str,
    category: str = "pending_action",
    unit: str = "count",
    period: str = "point_in_time",
    date_basis: str = "not_time_bound",
    drilldown: str | None = None,
) -> dict:
    return {
        "key": f"ia_reporting_{_slug(label)}",
        "label": label,
        "source_label": label,
        "source": _SOURCE,
        "definition": definition,
        "question": question,
        "category": category,
        "unit": unit,
        "service": service,
        "source_models": models,
        "numerator": numerator,
        "denominator": None,
        "date_basis": date_basis,
        "period": period,
        "scope": scope,
        "owner_page": owner_page,
        "filter_behaviour": "fixed_context",
        "drilldown": drilldown,
        "no_drilldown_reason": None
        if drilldown
        else "The table beside the tile lists what it counts.",
        "notes": "IA reporting and accountability, added 2026-09-13.",
        "roles": roles,
        "source_location": f"{_PATH}:{_line(label)}",
    }


IA_REPORTING_METRIC_ROWS: tuple[dict, ...] = (
    # ── Impact Reports register and the IA dashboard's Reports view ─────────
    _row(
        "Impact Reports Awaiting Review",
        service="apps.impact.reports.counts",
        definition=(
            "Impact reports submitted for review — their evidence frozen — that "
            "nobody has approved or returned yet."
        ),
        question="Which reports wait for a second reader before anyone may act on them?",
        numerator="reports with status submitted",
        models=_REPORT,
        owner_page="impact_reports",
        roles=_REGISTER_ROLES,
        scope=_REPORT_SCOPE,
        drilldown="/ia/impact-reports/?status=submitted",
    ),
    _row(
        "Impact Reports Returned for Correction",
        service="apps.impact.reports.counts",
        definition=(
            "Impact reports a reviewer returned with a note; the author corrects "
            "one as a new version."
        ),
        question="Which reports need their author's correction?",
        numerator="reports with status returned",
        models=_REPORT,
        owner_page="impact_reports",
        roles=_REGISTER_ROLES,
        scope=_REPORT_SCOPE,
        drilldown="/ia/impact-reports/?status=returned",
    ),
    _row(
        "Impact Reports Released This Year",
        service="apps.impact.reports.counts",
        definition=(
            "Impact reports of the operational financial year released to "
            "country leadership and not since superseded by a correction."
        ),
        question="How much reviewed evidence has reached country leadership this year?",
        numerator="reports with status released for the financial year",
        models=_REPORT,
        owner_page="impact_reports",
        roles=_REGISTER_ROLES,
        scope=_REPORT_SCOPE,
        category="progress",
        period="financial_year",
        date_basis="approval_date",
        drilldown="/ia/impact-reports/?status=released",
    ),
    _row(
        "Report Recommendations Awaiting a Response",
        service="apps.impact.reports.counts",
        definition=(
            "Recommendations of released impact reports the Country Director has "
            "not yet accepted, rejected or deferred; the helper names how many "
            "open recommendations are past their due date."
        ),
        question="Which evidence-based recommendations has leadership not yet answered?",
        numerator="recommendations with status proposed on released reports",
        models=_RECOMMENDATION,
        owner_page="impact_reports",
        roles=_REGISTER_ROLES,
        scope=_REPORT_SCOPE,
    ),
    _row(
        "Donor Versions Awaiting RVP Approval",
        service="apps.impact.reports.counts",
        definition=(
            "Donor versions — aggregates only, small cells suppressed — requested "
            "by the reviewer or the Country Director and not yet approved or "
            "declined by an RVP."
        ),
        question="Which donor versions wait for the second key?",
        numerator="donor releases with status awaiting approval",
        models=_RELEASE,
        owner_page="impact_reports",
        roles=_REGISTER_ROLES,
        scope=_REPORT_SCOPE,
    ),
    # ── Country Director dashboard: Impact findings ─────────────────────────
    _row(
        "Latest Released Impact Report",
        service="apps.impact.reports.cd_impact_findings",
        definition=(
            "The period of the impact report most recently released to the "
            "country's leadership, with its measured enrolments over all "
            "enrolments from the frozen evidence."
        ),
        question="What is the latest reviewed evidence on the country's impact?",
        numerator="the latest leadership release's report period",
        models=_RELEASE,
        owner_page="dashboard",
        roles=_CD_ROLES,
        scope=_CD_SCOPE,
        category="progress",
        unit="status",
        date_basis="approval_date",
    ),
    _row(
        "Impact Reports Awaiting Your Acknowledgement",
        service="apps.impact.reports.cd_impact_findings",
        definition=(
            "Submitted impact reports the Country Director reviews because the "
            "country has no second Impact Assessment officer."
        ),
        question="Which reports can only I acknowledge?",
        numerator="submitted reports whose author is the country's only IA officer",
        models=_REPORT,
        owner_page="dashboard",
        roles=_CD_ROLES,
        scope=_CD_SCOPE,
    ),
    _row(
        "Recommendations Awaiting Your Response",
        service="apps.impact.reports.cd_impact_findings",
        definition=(
            "Recommendations of the country's released impact reports that the "
            "Country Director has not yet answered."
        ),
        question="Which recommendations wait for my decision?",
        numerator="recommendations with status proposed on released reports",
        models=_RECOMMENDATION,
        owner_page="dashboard",
        roles=_CD_ROLES,
        scope=_CD_SCOPE,
    ),
    _row(
        "Report Recommendations Overdue",
        service="apps.impact.reports.cd_impact_findings",
        definition=(
            "Recommendations of released impact reports that are proposed, "
            "accepted or in progress and past their due date."
        ),
        question="Which agreed follow-ups have slipped?",
        numerator="open recommendations with a due date before today",
        models=_RECOMMENDATION,
        owner_page="dashboard",
        roles=_CD_ROLES,
        scope=_CD_SCOPE,
        category="risk",
    ),
)
