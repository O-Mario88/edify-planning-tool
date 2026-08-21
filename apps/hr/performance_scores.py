"""The one place a performance score is computed (§13–§15).

Every surface — My Targets, Team Targets, Country Program Leads Performance,
Country Performance, Performance Management, the exports — reads from here.
That is the whole point: a platform where two pages compute the same score
independently is a platform where two pages eventually disagree, and the person
whose rating is on the screen has no way to tell which one is right.

The chain this implements:

    allocation → verified achievement → milestone score
                                             ↓
                             weighted staff overall score
                                             ↓
                    PL team average · CD country average

Three rules that decide most of the edge cases:

  * Verified only. Nothing here reads planned work, and there is no argument
    to any of these functions that lets a caller supply an achievement figure.
  * Each person counted once. A CD's country average is built from individual
    staff scores, never by averaging PL team averages — that would count every
    CCEO twice, once in their PL's average and again in the country's.
  * Absence is stated, never scored. Someone with no approved agreement is
    excluded from the average and reported as needing configuration, because
    averaging them in at 0% would quietly punish a setup gap.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from apps.hr.models import MilestoneAllocation
from apps.hr.target_distribution import classify_achievement

#: Reported instead of a score when a person cannot be scored at all. It is a
#: setup state, not a performance state, and it never enters an average.
CONFIGURATION_REQUIRED = "Performance Configuration Required"


@dataclass
class MilestoneScore:
    """One allocation's contribution to a person's overall score."""

    allocation_id: str
    milestone: str
    priority: str
    target: Decimal
    achieved: Decimal
    weight: int
    classification: dict

    @property
    def is_scoring(self) -> bool:
        return bool(self.classification.get("is_scoring")) and self.weight > 0

    @property
    def pct(self) -> float | None:
        return self.classification.get("pct")

    @property
    def variance(self) -> Decimal:
        """§12.3 — achieved minus target, in the target's own unit."""
        return self.achieved - self.target

    def as_dict(self) -> dict:
        return {
            "allocationId": self.allocation_id,
            "milestone": self.milestone,
            "priority": self.priority,
            "target": self.target,
            "achieved": self.achieved,
            "variance": self.variance,
            "weight": self.weight,
            "pct": self.pct,
            "classification": self.classification,
            "isScoring": self.is_scoring,
        }


@dataclass
class StaffScore:
    """A person's automatic overall performance for a financial year."""

    staff_id: str
    name: str
    rows: list[MilestoneScore] = field(default_factory=list)
    pct: float | None = None
    classification: dict = field(default_factory=dict)
    eligible: bool = False
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "staffId": self.staff_id,
            "name": self.name,
            "pct": self.pct,
            "classification": self.classification,
            "eligible": self.eligible,
            "reason": self.reason,
            "rows": [row.as_dict() for row in self.rows],
        }


def _achieved(allocation) -> Decimal:
    """Verified achievement for one allocation.

    Counts never accumulate a rate: a 90% coverage commitment is 90% in every
    period, so its year figure is the best period reading, not their sum.
    """
    periods = list(allocation.period_targets.all())
    months = [p for p in periods if p.period_type == "month"]
    source = months or periods
    if allocation.milestone.measurement_type in {"count", "currency"}:
        return sum((p.actual_value for p in source), Decimal("0"))
    return max((p.actual_value for p in source), default=Decimal("0"))


def milestone_scores(staff_id: str, fy: str) -> list[MilestoneScore]:
    """Every approved allocation this person holds, scored."""
    allocations = (
        MilestoneAllocation.objects.filter(
            employee_id=staff_id, status="approved", milestone__priority__fy=fy
        )
        .select_related("milestone__priority", "milestone__metric_definition")
        .prefetch_related("period_targets")
        .order_by("milestone__priority__sequence", "milestone__source_order")
    )
    rows = []
    for allocation in allocations:
        milestone = allocation.milestone
        target = allocation.allocated_target or Decimal("0")
        achieved = _achieved(allocation)
        pct = (
            round(float(achieved / target * 100), 2) if target and target != 0 else None
        )
        rows.append(
            MilestoneScore(
                allocation_id=allocation.id,
                milestone=milestone.title,
                priority=milestone.priority.title,
                target=target,
                achieved=achieved,
                weight=int(allocation.weight or milestone.weight or 0),
                classification=classify_achievement(
                    pct,
                    cap_at_100=milestone.cap_at_100,
                    target=target,
                    scoreable=milestone.definition_status != "non_scoreable",
                ),
            )
        )
    return rows


def staff_overall(staff_profile, fy: str) -> StaffScore:
    """§13.2 — Σ(milestone score × weight) ÷ Σ(applicable weights).

    Weights are the ones carried on the approved allocations. Where a scoring
    row has no weight it cannot be included, and the whole score is withheld
    rather than silently reweighting the rest — inventing an equal split would
    change someone's rating without anyone deciding to.
    """
    user = getattr(staff_profile, "user", None)
    score = StaffScore(
        staff_id=str(staff_profile.id),
        name=getattr(user, "name", None) or getattr(user, "email", "") or "Staff",
    )
    score.rows = milestone_scores(str(staff_profile.id), fy)
    if not score.rows:
        score.reason = CONFIGURATION_REQUIRED
        score.classification = classify_achievement(None)
        return score

    scoring = [row for row in score.rows if row.is_scoring]
    unweighted = [
        row
        for row in score.rows
        if row.classification.get("is_scoring") and row.weight <= 0
    ]
    if unweighted:
        score.reason = (
            f"{len(unweighted)} scoreable milestone(s) carry no weight, so a "
            f"weighted score cannot be computed."
        )
        score.classification = classify_achievement(None)
        return score
    if not scoring:
        score.reason = (
            "No scoreable allocation — every milestone here is non-scoreable, "
            "not applicable, or awaiting configuration."
        )
        score.classification = classify_achievement(None)
        return score

    total_weight = sum(row.weight for row in scoring)
    weighted = sum((row.pct or 0) * row.weight for row in scoring)
    score.pct = round(weighted / total_weight, 2)
    score.classification = classify_achievement(score.pct)
    score.eligible = True
    return score


def _eligible_scores(profiles, fy: str) -> tuple[list[StaffScore], list[StaffScore]]:
    """Score a roster, splitting who counts from who cannot yet be scored."""
    eligible, excluded = [], []
    for profile in profiles:
        score = staff_overall(profile, fy)
        (eligible if score.eligible else excluded).append(score)
    return eligible, excluded


def _average(scores: list[StaffScore]) -> float | None:
    if not scores:
        return None
    return round(sum(s.pct or 0 for s in scores) / len(scores), 2)


def direct_reports(pl_profile):
    """The CCEOs this Program Lead actually supervises, right now."""
    from apps.accounts.models import StaffProfile, StaffSupervisorAssignment

    supervisee_ids = StaffSupervisorAssignment.objects.filter(
        supervisor_id=pl_profile.id
    ).values_list("supervisee_id", flat=True)
    return list(
        StaffProfile.objects.filter(
            id__in=list(supervisee_ids),
            user__is_active=True,
            user__deleted_at__isnull=True,
            onboarding_state="active",
        )
        .exclude(id=pl_profile.id)
        .select_related("user")
    )


def pl_performance(pl_profile, fy: str) -> dict:
    """§14 — the Program Lead's own score and their team's, kept apart.

    The headline on Country Program Leads Performance is the TEAM average, but
    a PL now holds a self-allocation too, and letting the team number stand in
    for their own delivery would hide the part of the target they personally
    committed to.
    """
    personal = staff_overall(pl_profile, fy)
    reports = direct_reports(pl_profile)
    eligible, excluded = _eligible_scores(reports, fy)
    team_pct = _average(eligible)
    return {
        "staffId": str(pl_profile.id),
        "name": personal.name,
        "personal": personal.as_dict(),
        "team": {
            "pct": team_pct,
            "classification": classify_achievement(team_pct),
            "counted": len(eligible),
            "excluded": [
                {"name": s.name, "reason": s.reason or CONFIGURATION_REQUIRED}
                for s in excluded
            ],
            "members": [s.as_dict() for s in eligible],
        },
        "directReports": len(reports),
    }


def country_performance(country: str, fy: str) -> dict:
    """§15 — the average of eligible individual staff, each counted once.

    Deliberately NOT an average of PL team averages: every CCEO sits inside
    their PL's average, so averaging those would weight a CCEO by how large
    their team is and count them twice over.
    """
    from apps.accounts.models import StaffProfile

    from apps.hr.review_authority import REVIEWER_ROLE_FOR

    staff = list(
        StaffProfile.objects.filter(
            country=country,
            user__is_active=True,
            user__deleted_at__isnull=True,
            onboarding_state="active",
            user__active_role__in=list(REVIEWER_ROLE_FOR),
        ).select_related("user")
    )
    eligible, excluded = _eligible_scores(staff, fy)
    pct = _average(eligible)
    return {
        "country": country,
        "fy": fy,
        "pct": pct,
        "classification": classify_achievement(pct),
        "counted": len(eligible),
        "population": len(staff),
        "excluded": [
            {"name": s.name, "reason": s.reason or CONFIGURATION_REQUIRED}
            for s in excluded
        ],
        "members": [s.as_dict() for s in eligible],
    }
