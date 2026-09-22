"""Core Trained, Core Graduate and Champion schools, in one list.

Owner, 2026-09-21:

  "Create a page for a combined list of core trained, core graduate and
  Champion School and [they] can receive all the activities (visit,
  trainings) client schools should receive but cannot be assigned to
  partner."

They had no operational home. ``core_trained`` sat in the School Directory
under the client rule, ``champion`` and ``core_graduate`` sat on no visit rule
at all — which reads as an unlimited entitlement rather than a chosen one —
and nothing anywhere said the three belong together or that partner delivery
is closed to them.

This module is the list, and nothing else: the two rules it describes live
where they are enforced, so no surface can hold a different opinion of them.

* The **entitlement** is ``apps.planning.visit_gate``: all three are on the
  client rule, so they take the same visits and the same trainings a client
  school takes, from the same drawers.
* The **partner refusal** is the visit gate's ``can_assign_partner`` and
  ``apps.partners.services.create_assignment`` — the drawer greys the control
  and the one creation door refuses it, so a bulk path cannot walk around it.

Every number here is read live from the Activity ledger and the visit gate.
There is no stored "programme school" flag to go stale: a school is on this
page because of its ``school_type``, and it leaves the page the day that
changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apps.planning.visit_gate import PROGRAMME_SCHOOL_TYPES

__all__ = [
    "PROGRAMME_SCHOOL_TYPES",
    "ProgrammeSchoolRow",
    "ProgrammeSchools",
    "programme_schools",
    "type_options",
]


def type_options() -> list[tuple[str, str]]:
    """The three types, with their labels, in lifecycle order."""
    from apps.core.enums import SchoolType

    labels = dict(SchoolType.choices)
    return [(value, labels.get(value, value)) for value in PROGRAMME_SCHOOL_TYPES]


@dataclass
class ProgrammeSchoolRow:
    """One school, with what it has taken of its year and what it may still."""

    id: str
    school_id: str
    name: str
    school_type: str
    school_type_label: str
    district: str
    owner: str
    ssa_average: float | None
    ssa_tone: str
    visits_used: int
    visits_allowed: int
    visit_status_label: str
    visit_status_tone: str
    next_visit_date: object | None
    training_label: str
    training_planned: bool
    can_schedule: bool
    schedule_reason: str
    partner_reason: str

    @property
    def visits_left(self) -> int:
        return max(0, self.visits_allowed - self.visits_used)


@dataclass
class ProgrammeSchools:
    """The page's rows and the figures above them."""

    rows: list[ProgrammeSchoolRow] = field(default_factory=list)
    total: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    visits_planned: int = 0
    trainings_planned: int = 0

    @property
    def visit_gap(self) -> int:
        """Schools with no visit planned for the year — the work outstanding."""
        return max(0, self.total - self.visits_planned)


def _scoped(principal):
    from apps.core.scoping import resolve_user_scope, scoped_school_queryset
    from apps.schools.lifecycle_models import OPERATING_STATUSES
    from apps.schools.models import School

    base = School.objects.filter(
        deleted_at__isnull=True,
        school_type__in=PROGRAMME_SCHOOL_TYPES,
        operational_status__in=OPERATING_STATUSES,
    )
    scoped = scoped_school_queryset(resolve_user_scope(principal), base=base)
    return base if scoped is None else scoped


def programme_schools(
    principal,
    *,
    query: str = "",
    school_type: str = "",
    district: str = "",
    fy: str | None = None,
    limit: int = 500,
) -> ProgrammeSchools:
    """The scoped list, with each school's live entitlement position.

    ``limit`` bounds the rows the page renders; the counts above them are
    aggregated over the whole matching set, so paging through the list never
    changes the figures it is filtered by.
    """
    from apps.core.enums import ssa_score_band
    from apps.core.fy import get_operational_fy
    from apps.core.scoping import direct_portfolio_schools, resolve_user_scope
    from apps.planning.visit_gate import visit_gates
    from apps.schools.school_status import cluster_training_coverage, visit_statuses

    fy = str(fy or get_operational_fy())
    qs = _scoped(principal).select_related("district")
    if school_type in PROGRAMME_SCHOOL_TYPES:
        qs = qs.filter(school_type=school_type)
    if district:
        qs = qs.filter(district_id=district)
    query = (query or "").strip()
    if query:
        from django.db.models import Q

        qs = qs.filter(Q(name__icontains=query) | Q(school_id__icontains=query))

    result = ProgrammeSchools()
    # Counted over the whole filtered set, in the database — a total that
    # shrinks as somebody pages is not a total.
    from django.db.models import Count

    result.by_type = {
        row["school_type"]: row["n"]
        for row in qs.values("school_type").annotate(n=Count("id"))
    }
    result.total = sum(result.by_type.values())
    if not result.total:
        return result

    schools = list(qs.order_by("name")[:limit])
    gates = visit_gates(schools, fy)
    statuses = visit_statuses([school.id for school in schools], fy=fy)
    coverage = cluster_training_coverage(schools, fy=fy)

    scope = resolve_user_scope(principal)
    writable = direct_portfolio_schools(scope)
    writable_ids = (
        set(
            writable.filter(id__in=[s.id for s in schools]).values_list("id", flat=True)
        )
        if writable is not None
        else set()
    )

    owners = _owner_names(schools)
    averages = _ssa_averages(schools)
    for school in schools:
        gate = gates[school.id]
        status = statuses[school.id]
        training = coverage[school.id]
        average = averages.get(school.id)
        _band, _hex, tone = ssa_score_band(average)
        may_schedule = school.id in writable_ids and gate.staff_can_schedule
        result.rows.append(
            ProgrammeSchoolRow(
                id=school.id,
                school_id=school.school_id,
                name=school.name,
                school_type=school.school_type,
                school_type_label=school.get_school_type_display(),
                district=school.district.name if school.district_id else "",
                owner=owners.get(school.account_owner_id, ""),
                ssa_average=average,
                ssa_tone=tone,
                visits_used=gate.total_visits,
                visits_allowed=gate.staff_cap,
                visit_status_label=status.label,
                visit_status_tone=status.tone,
                next_visit_date=status.next_date,
                training_label=training.label,
                training_planned=training.planned,
                can_schedule=may_schedule,
                schedule_reason=(
                    ""
                    if may_schedule
                    else (
                        gate.staff_locked_reason
                        or gate.staff_reason
                        or f"{school.name} is not in your own portfolio. "
                        "Its owner plans its visits."
                    )
                ),
                partner_reason=gate.assign_reason,
            )
        )

    result.visits_planned = sum(1 for row in result.rows if row.next_visit_date)
    result.trainings_planned = sum(1 for row in result.rows if row.training_planned)
    return result


def _ssa_averages(schools) -> dict[str, float]:
    """The confirmed SSA average per school, from the canonical batched read.

    A school with no confirmed assessment is simply absent, so the page can
    say "Not assessed" rather than print a zero that reads as a score.
    """
    from apps.ssa.presentation import build_ssa_score_summary
    from apps.ssa.services import latest_applicable_records

    records = latest_applicable_records(schools, with_scores=True)
    averages = {}
    for school_id, record in records.items():
        summary = build_ssa_score_summary(
            [
                {"intervention": score.intervention, "score": score.score}
                for score in record.scores.all()
            ]
        )
        if summary["has_scores"]:
            averages[school_id] = summary["average_score"]
    return averages


def _owner_names(schools) -> dict[str, str]:
    """Owner ids resolve in both id spaces, so ask for both (apps.core.scoping)."""
    from apps.accounts.models import StaffProfile

    ids = {school.account_owner_id for school in schools if school.account_owner_id}
    if not ids:
        return {}
    names = {}
    for profile in StaffProfile.objects.filter(id__in=ids).select_related("user"):
        names[profile.id] = profile.user.name if profile.user_id else ""
    missing = ids - set(names)
    if missing:
        from apps.accounts.models import User

        for user in User.objects.filter(id__in=missing):
            names[user.id] = user.name
    return names
