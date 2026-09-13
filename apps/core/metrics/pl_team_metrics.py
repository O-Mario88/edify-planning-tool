"""Metric definitions for My Team — the Programme Lead's roster of the officers they line-manage.

Program Lead alignment (owner, 2026-09-13). My Team renders its tiles through
``apps.frontend.views.staff_views._team_metric``, which only accepts a label
the reconciled registry knows. Every figure comes from
``apps.hr.team_roster.build_team_roster`` — the same roster the page's table
lists — so a tile never counts something the rows below it do not show. The
rows are appended to the reconciled registry in reconciled_registry.py; the
row shape follows cce_leadership_metrics.py.

These replace the three ``frontend_views_staff_views_*`` tiles the old page
rendered (Total CCEOs, With Overdue, All Caught Up).
"""

from __future__ import annotations

_SOURCE = "apps.frontend.views.staff_views:_team_metric"
_LOCATION = "apps/frontend/views/staff_views.py"
_ROLES = ("Program Lead", "Admin")
_SCOPE = (
    "The officers the viewer line-manages: direct supervisees holding the CCEO "
    "role, plus an absent Programme Lead's officers while the viewer covers "
    "(apps.hr.team_roster.team_members)"
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
    category: str = "scale",
    unit: str = "count",
    denominator: str | None = None,
    period: str = "point_in_time",
    date_basis: str = "not_time_bound",
) -> dict:
    return {
        "key": f"pl_team_{_slug(label)}",
        "label": label,
        "source_label": label,
        "source": _SOURCE,
        "definition": definition,
        "question": question,
        "category": category,
        "unit": unit,
        "service": "apps.hr.team_roster.build_team_roster",
        "source_models": models,
        "numerator": numerator,
        "denominator": denominator,
        "date_basis": date_basis,
        "period": period,
        "scope": _SCOPE,
        "owner_page": "my_team",
        "filter_behaviour": "filtered",
        "drilldown": None,
        "no_drilldown_reason": "The roster and the action list below the tile list the officers and items it counts.",
        "notes": "Programme Lead team home (My Team), added 2026-09-13.",
        "roles": _ROLES,
        "source_location": f"{_LOCATION}:{line}",
    }


_PROFILES = ("apps.accounts.models.StaffProfile",)

PL_TEAM_METRIC_ROWS: tuple[dict, ...] = (
    _row(
        "Officers on My Team",
        line=988,
        definition=(
            "Officers the Programme Lead line-manages: active CCEOs linked to them "
            "as supervisor, and an absent lead's officers while they cover."
        ),
        question="How many officers does the lead supervise?",
        numerator="team_members(principal)",
        models=_PROFILES
        + (
            "apps.accounts.models.StaffSupervisorAssignment",
            "apps.accounts.models.TemporaryCoverageAssignment",
        ),
    ),
    _row(
        "Officers On Pace for FY Targets",
        line=993,
        definition=(
            "Officers whose weighted achievement for the financial year so far is "
            "On Track, Complete or Exceeded against Team Targets' pace bands "
            "(within 5 points of the expected pace)."
        ),
        question="How many officers are keeping pace with their agreed targets?",
        numerator="officers whose FY Team Targets status is On Track, Complete or Exceeded",
        models=(
            "apps.targets.models.TargetAchievementLedger",
            "apps.targets.models.MonthlyPersonalTarget",
            "apps.accounts.models.StaffTargetProfile",
        ),
        category="progress",
        period="financial_year",
        date_basis="activity_planned_date",
    ),
    _row(
        "Officers at Target Risk This Month",
        line=999,
        definition=(
            "Officers whose weighted achievement this month is High Risk or "
            "Critical against Team Targets' pace bands — the band Team "
            "Oversight's High-Risk Staff tile counts."
        ),
        question="Which officers need a catch-up conversation this month?",
        numerator="officers whose monthly Team Targets status is High Risk or Critical",
        models=(
            "apps.targets.models.TargetAchievementLedger",
            "apps.targets.models.MonthlyPersonalTarget",
        ),
        category="risk",
        period="month",
        date_basis="activity_planned_date",
    ),
    _row(
        "Team Handoffs Waiting on You",
        line=1005,
        definition=(
            "Items the officers handed to the lead that are still undecided: "
            "completions submitted for confirmation, development requests at "
            "the supervisor stage, pending leave requests, open escalations the "
            "lead may decide, and extra work submitted for the lead to verify."
        ),
        question="How much of the team's work is waiting on the lead?",
        numerator="sum of the five waiting counts across the roster",
        models=(
            "apps.activities.models.Activity",
            "apps.professional_development.models.ProfessionalDevelopmentRequest",
            "apps.accounts.models.Leave",
            "apps.flags.models.LeadershipEscalation",
            "apps.hr.models.ExtraAssignment",
        ),
        category="pending_action",
    ),
    _row(
        "Team Exceptions Needing Your Action",
        line=1011,
        definition=(
            "Manager-owned exceptions for the team: leave decisions older than "
            "three days, overdue performance reviews, officers with no "
            "agreement for the year, approved leave in the next fortnight with "
            "nobody covering, plus the handoffs waiting on the lead, one item "
            "per officer and kind."
        ),
        question="What must the lead act on now as a line manager?",
        numerator="items in the Needs your action list",
        models=(
            "apps.accounts.models.Leave",
            "apps.hr.models.PerformanceReview",
            "apps.accounts.models.TemporaryCoverageAssignment",
        ),
        category="pending_action",
    ),
    _row(
        "Team Portfolio SSA Coverage This FY",
        line=1017,
        definition=(
            "The share of the officers' portfolio schools with an IA-confirmed "
            "school self-assessment recorded for the financial year."
        ),
        question="How much of the team's portfolio has been assessed this year?",
        numerator="portfolio schools with a confirmed SsaRecord for the FY",
        denominator="the officers' active portfolio schools",
        models=(
            "apps.ssa.models.SsaRecord",
            "apps.accounts.models.StaffSchoolAssignment",
        ),
        category="progress",
        unit="percent",
        period="financial_year",
        date_basis="ssa_assessment_date",
    ),
)
