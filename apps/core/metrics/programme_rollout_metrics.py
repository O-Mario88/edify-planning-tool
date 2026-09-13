"""Metric definitions for Programme Rollout — trainings, school self-assessments and spiritual transformation across a Programme Lead's team.

Program Lead alignment (owner, 2026-09-13). Rows are appended to the reconciled
registry in reconciled_registry.py; follow the row shape in cce_leadership_metrics.py.

Each tab of /programme-rollout renders its own panel of tiles through
``apps.frontend.views.programme_rollout_views._metric``, which only accepts a
label registered here. The tile shows the short source label; the canonical
label carries the page name so it stays unique platform-wide. The two
spiritual averages and the weak-schools tile name their interventions by the
platform's one abbreviation table (apps.core.interventions).
"""

from __future__ import annotations

from apps.core.enums import SsaIntervention
from apps.core.interventions import intervention_abbr

_SOURCE = "apps.frontend.views.programme_rollout_views:_metric"
_LOCATION = "apps/frontend/views/programme_rollout_views.py"
_SERVICE = "apps.analytics.programme_rollout_service"
_ROLES = ("Program Lead", "Admin")
_SCOPE = (
    "The Programme Lead's team (apps.hr.team_roster.team_members) and the "
    "lead's own portfolio; Admin reads one chosen lead's team"
)
_ACTIVITY = ("apps.activities.models.Activity",)
_ATTENDANCE = ("apps.activities.models.ClusterActivityAttendance",)
_OBSERVATION = ("apps.cce_leadership.models.RegionalEngagement",)
_SSA = ("apps.ssa.models.SsaRecord",)
_SCORE = ("apps.ssa.models.SsaScore",)
_CATALOGUE = ("apps.activity_catalogue.models.ActivityCatalogueItem",)

CB = intervention_abbr(SsaIntervention.CHRISTLIKE_BEHAVIOUR.value)
WOG = intervention_abbr(SsaIntervention.EXPOSURE_TO_WORD_OF_GOD.value)


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
    service: str,
    category: str = "progress",
    unit: str = "count",
    period: str = "financial_year",
    date_basis: str = "activity_planned_date",
    filter_behaviour: str = "filtered",
) -> dict:
    return {
        "key": f"programme_rollout_{_slug(label)}",
        "label": f"{label} — Programme Rollout",
        "source_label": label,
        "source": _SOURCE,
        "definition": definition,
        "question": question,
        "category": category,
        "unit": unit,
        "service": f"{_SERVICE}.{service}",
        "source_models": models,
        "numerator": numerator,
        "denominator": None,
        "date_basis": date_basis,
        "period": period,
        "scope": _SCOPE,
        "owner_page": "programme_rollout",
        "filter_behaviour": filter_behaviour,
        "drilldown": None,
        "no_drilldown_reason": (
            "The tables on the same tab break the figure down, and a tile that "
            "counts schools opens the schools it counts."
        ),
        "notes": "Programme Rollout, Program Lead alignment 2026-09-13.",
        "roles": _ROLES,
        "source_location": f"{_LOCATION}:{line}",
    }


PROGRAMME_ROLLOUT_METRIC_ROWS: tuple[dict, ...] = (
    # ── Trainings ────────────────────────────────────────────────────────────
    _row(
        "Trainings Delivered",
        line=77,
        definition=(
            "The team's trainings this financial year that are verified, "
            "confirmed or closed (COMPLETED_WORK_STATUSES), out of every training "
            "planned that was not cancelled, rejected, deferred or still a request."
        ),
        question="Is the team delivering the trainings it planned?",
        numerator="team training activities in COMPLETED_WORK_STATUSES for the FY",
        models=_ACTIVITY,
        service="trainings_rollout",
        category="progress",
    ),
    _row(
        "Portfolio Schools Trained",
        line=83,
        definition=(
            "Portfolio schools with a verified training this financial year, at "
            "the school or by confirmed attendance at a verified cluster training "
            "(apps.activities.cluster_attendance.trained_school_ids)."
        ),
        question="How much of the team's portfolio has been trained this year?",
        numerator="portfolio schools in trained_school_ids for the FY",
        models=_ACTIVITY + _ATTENDANCE,
        service="trainings_rollout",
        category="outcome",
    ),
    _row(
        "Teachers and Leaders Trained",
        line=92,
        definition=(
            "Teachers and school leaders recorded as attending the team's "
            "delivered trainings this financial year."
        ),
        question="How many people have the team's trainings reached?",
        numerator="sum of teachers_attended and leaders_attended on delivered team trainings",
        models=_ACTIVITY,
        service="trainings_rollout",
        category="scale",
        date_basis="activity_execution_date",
    ),
    _row(
        "Trainings Due in 30 Days",
        line=97,
        definition=(
            "Team trainings planned or scheduled for today and the next 30 days, "
            "whatever the financial year selected."
        ),
        question="What trainings does the team have coming up?",
        numerator="team training activities in a live status dated within 30 days",
        models=_ACTIVITY,
        service="trainings_rollout",
        category="readiness",
        period="rolling_30_days",
        filter_behaviour="fixed_context",
    ),
    _row(
        "Open Training Recommendations",
        line=102,
        definition=(
            "Regional Lead observations shared with the Programme Lead this "
            "financial year that recommend strengthening or replacing a training "
            "and that the lead has not yet answered."
        ),
        question="Which training quality concerns still wait on the Programme Lead?",
        numerator="shared observations with recommendation strengthen or replace and no acknowledgement",
        models=_OBSERVATION,
        service="trainings_rollout",
        category="risk",
        date_basis="record_created",
    ),
    # ── School self-assessments ──────────────────────────────────────────────
    _row(
        "Schools With a Confirmed SSA",
        line=119,
        definition=(
            "Portfolio schools with a confirmed SSA record for the financial "
            "year (schools_with_confirmed_ssa)."
        ),
        question="How far has this year's self-assessment reached the portfolio?",
        numerator="portfolio schools with a confirmed, undeleted SsaRecord whose fy is the FY",
        models=_SSA,
        service="ssa_rollout",
        category="progress",
        date_basis="ssa_assessment_date",
    ),
    _row(
        "SSAs Awaiting IA Verification",
        line=127,
        definition=(
            "Portfolio schools without a confirmed SSA whose record for the year "
            "is uploaded but unconfirmed, or whose SSA collection was held and "
            "is still being completed or verified."
        ),
        question="How much SSA work is waiting on Impact Assessment?",
        numerator="portfolio schools in the awaiting state of ssa_states",
        models=_SSA + _ACTIVITY,
        service="ssa_rollout",
        category="pending_action",
        date_basis="ssa_assessment_date",
    ),
    _row(
        "SSA Collections Scheduled",
        line=133,
        definition=(
            "Portfolio schools with no SSA record to wait on whose collection is "
            "planned or scheduled this year, or handed to a partner and not yet "
            "scheduled."
        ),
        question="How many schools have an SSA collection on the way?",
        numerator="portfolio schools in the scheduled state of ssa_states",
        models=_ACTIVITY + ("apps.partners.models.PartnerAssignment",),
        service="ssa_rollout",
        category="readiness",
    ),
    _row(
        "Schools With No SSA Planned",
        line=139,
        definition=(
            "Portfolio schools with no SSA record, collection or partner hand-over "
            "for the financial year."
        ),
        question="Which schools has nobody planned an SSA for?",
        numerator="portfolio schools in the not_planned state of ssa_states",
        models=_SSA + _ACTIVITY,
        service="ssa_rollout",
        category="risk",
        date_basis="not_time_bound",
    ),
    # ── Spiritual transformation ─────────────────────────────────────────────
    _row(
        f"Team {CB} Average",
        line=161,
        definition=(
            "The portfolio's average Christlike Behaviour score on the latest "
            "confirmed SSA cycle up to the financial year, with the change from "
            "the previous cycle (PLAnalyticsService.ssa_interventions)."
        ),
        question="Is Christlike Behaviour improving across the team's schools?",
        numerator="mean of confirmed Christlike Behaviour scores in the latest cycle",
        models=_SSA + _SCORE,
        service="spiritual_rollout",
        category="outcome",
        unit="score",
        date_basis="ssa_assessment_date",
    ),
    _row(
        f"Team {WOG} Average",
        line=161,
        definition=(
            "The portfolio's average Exposure to the Word of God score on the "
            "latest confirmed SSA cycle up to the financial year, with the change "
            "from the previous cycle (PLAnalyticsService.ssa_interventions)."
        ),
        question="Is exposure to the Word of God improving across the team's schools?",
        numerator="mean of confirmed Exposure to the Word of God scores in the latest cycle",
        models=_SSA + _SCORE,
        service="spiritual_rollout",
        category="outcome",
        unit="score",
        date_basis="ssa_assessment_date",
    ),
    _row(
        f"Schools Weak in {CB} or {WOG} Without a Plan",
        line=171,
        definition=(
            "Portfolio schools where Christlike Behaviour or Exposure to the Word "
            "of God is among the three weakest interventions on the latest "
            "confirmed SSA, and no activity this year at the school or its cluster "
            "targets that intervention."
        ),
        question="Which spiritually weakest schools have no response planned?",
        numerator="weak schools with at least one spiritual intervention unanswered",
        models=_SCORE + _ACTIVITY,
        service="spiritual_rollout",
        category="risk",
    ),
    _row(
        "Spiritual Programmes Delivered",
        line=177,
        definition=(
            "Delivered Christian Transformation courses, CC-SEL sessions and camps "
            "planned by the team this financial year, by officers and partners."
        ),
        question="Are the spiritual transformation programmes being delivered?",
        numerator="team activities on a spiritual catalogue item in COMPLETED_WORK_STATUSES",
        models=_ACTIVITY + _CATALOGUE,
        service="spiritual_rollout",
        category="progress",
    ),
    _row(
        "Biblical Integration Rating",
        line=183,
        definition=(
            "The average Biblical integration rating, from 1 to 4, on the Regional "
            "Lead's observations of the team's trainings shared with the "
            "Programme Lead this financial year."
        ),
        question="Are the team's trainings integrating the Bible well?",
        numerator="mean rating_biblical_integration on shared observations",
        models=_OBSERVATION,
        service="spiritual_rollout",
        category="quality",
        unit="score",
        date_basis="record_created",
    ),
)
