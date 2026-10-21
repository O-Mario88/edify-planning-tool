"""Targets: the Uganda Master Priority Plan figures leads already set.

Owner, 2026-10-20: "Targets are already set by PL and Project coordinator
and people have already populated." Nothing here is typed: the country
reads the milestone (its Core or Client figure for a Core or client row), a
region its lead's approved team allocation (else its officers' approved
allocations added up), a CCEO their approved allocation, and each month the
approved phasing of those allocations (`MilestonePeriodTarget`).

A percentage milestone is a coverage rate: its target is that share of the
scope's eligible schools. A coverage row the plan has no milestone for (the
workbook's "of the Core schools") takes the eligible schools themselves. With
neither, the target is "Not set" — never 0.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from apps.core.fy import get_fy_date_range

from .measures import Measure

RATE_MEASUREMENTS = frozenset({"percentage", "ratio"})
COUNTRY_ID = "Uganda"


@dataclass(frozen=True)
class Scope:
    """Whose target: the country, a lead's region, or one officer."""

    kind: str
    lead: str = ""
    staff: frozenset[str] = frozenset()

    @classmethod
    def country(cls) -> Scope:
        return cls("country")

    @classmethod
    def region(cls, lead_staff_id: str, staff_ids) -> Scope:
        return cls("region", str(lead_staff_id), frozenset(map(str, staff_ids)))

    @classmethod
    def officer(cls, staff_id: str) -> Scope:
        return cls("officer", str(staff_id), frozenset({str(staff_id)}))


@dataclass
class Target:
    annual: float | None
    source: str
    #: Month of the FY (1 = October) -> the approved phasing, or None when
    #: nothing is phased.
    months: dict[int, float] | None = None
    #: The coverage rate (a percentage) a target was worked out from.
    rate: float | None = None
    milestone: object = field(default=None, repr=False)

    def month(self, month_of_fy: int) -> float | None:
        if self.months is None:
            return None
        return self.months.get(month_of_fy, 0)

    def over(self, months) -> float | None:
        """The phased target of these FY months; None when nothing is phased
        or no month is asked for (a week, which no plan phases)."""
        if self.months is None or not months:
            return None
        return sum(self.months.get(m, 0) for m in months)

    def through(self, month_of_fy: int) -> float | None:
        """The phased target from October to the end of this month."""
        if self.months is None:
            return None
        return sum(v for m, v in self.months.items() if m <= month_of_fy)


NOT_SET = "Not set"
ELIGIBLE = "Eligible schools"


def _num(value) -> float | None:
    return None if value is None else float(value)


class TargetBook:
    """The year's master milestones and approved allocations, read once."""

    def __init__(self, fy: str):
        self.fy = str(fy)
        self.milestones: list = []
        self.by_code: dict[str, object] = {}
        self._codes: dict[str, str] = {}
        #: Country targets IA or Admin set (`country_targets`), by report row.
        self.country: dict[str, dict] = {}
        self._team: dict[tuple[str, str], object] = {}
        self._staff: dict[tuple[str, str], object] = {}
        #: Every approved team / employee allocation of a milestone.
        self._teams_of: dict[str, list] = defaultdict(list)
        self._staff_of: dict[str, list] = defaultdict(list)
        self._months: dict[str, dict[int, float]] = defaultdict(dict)

    @classmethod
    def load(cls, fy: str) -> TargetBook:
        from apps.hr.models import MilestoneAllocation, MilestonePeriodTarget
        from apps.hr.target_distribution import uganda_master_priorities

        from . import country_targets

        book = cls(fy)
        book.country = country_targets.load(book.fy)
        for priority in uganda_master_priorities(book.fy, country_id=COUNTRY_ID):
            for milestone in priority.milestones.all():
                book.milestones.append(milestone)
                book.by_code.setdefault(milestone.code, milestone)
        ids = [m.id for m in book.milestones]
        book._codes = {str(m.id): m.code for m in book.milestones}
        for allocation in MilestoneAllocation.objects.filter(
            milestone_id__in=ids, status="approved"
        ):
            code = book._code(allocation.milestone_id)
            if allocation.allocated_to_type == "team" and allocation.team_id:
                book._team[(code, str(allocation.team_id))] = allocation
                book._teams_of[code].append(allocation)
            elif allocation.employee_id:
                book._staff[(code, str(allocation.employee_id))] = allocation
                book._staff_of[code].append(allocation)
        fy_start = get_fy_date_range(book.fy)[0].date()
        for allocation_id, start, value in MilestonePeriodTarget.objects.filter(
            allocation__milestone_id__in=ids,
            allocation__status="approved",
            period_type="month",
        ).values_list("allocation_id", "period_start", "planned_value"):
            month = (start.year - fy_start.year) * 12 + start.month - fy_start.month + 1
            if 1 <= month <= 12:
                book._months[str(allocation_id)][month] = float(value)
        return book

    def _code(self, milestone_id) -> str:
        return self._codes.get(str(milestone_id), "")

    # ── Reading ─────────────────────────────────────────────────────────────
    def target(
        self, measure: Measure, scope: Scope, *, eligible: int | None = None
    ) -> Target:
        milestone = self.by_code.get(measure.milestone) if measure.milestone else None
        # IA or Admin set the country's figure; the plan is the fallback.
        if scope.kind == "country" and measure.key in self.country:
            set_ = self.country[measure.key]
            return Target(
                annual=set_["annual"],
                source=set_["source"],
                months=set_["months"],
                milestone=milestone,
            )
        if milestone is not None:
            if milestone.measurement_type in RATE_MEASUREMENTS:
                return self._rate(milestone, measure, scope, eligible)
            found = self._count(milestone, measure, scope)
            if found is not None:
                return found
        # Only a row the plan has no milestone for takes its eligible schools:
        # a 60% or 90% milestone missing for the year is not 100% of them.
        if measure.basis and not measure.milestone and eligible is not None:
            return Target(annual=float(eligible), source=ELIGIBLE)
        return Target(annual=None, source=NOT_SET, milestone=milestone)

    def for_code(
        self,
        code: str,
        scope: Scope,
        *,
        slice: str = "",
        basis: str = "",
        eligible=None,
        key: str = "_",
    ) -> Target:
        """The target of any plan milestone by its code, for a row that is
        not itself a Weekly Report measure (the Strategic Milestones rows)."""
        from dataclasses import replace

        from .measures import Measure

        probe = replace(Measure(key, "", ""), milestone=code, slice=slice, basis=basis)
        return self.target(probe, scope, eligible=eligible)

    def holders(self, code: str) -> list[str]:
        """The staff holding an approved allocation of a milestone."""
        return sorted({str(a.employee_id) for a in self._staff_of.get(code, [])})

    def _allocations(self, code: str, scope: Scope) -> list:
        if scope.kind == "officer":
            found = self._staff.get((code, scope.lead))
            return [found] if found else []
        if scope.kind == "region":
            team = self._team.get((code, scope.lead))
            if team is not None:
                return [team]
            return [a for s in sorted(scope.staff) if (a := self._staff.get((code, s)))]
        return []

    @staticmethod
    def _slice(holder, measure: Measure) -> float | None:
        """The row's figure of a milestone or allocation: its Core or Client
        part for a sliced row, else the whole."""
        # A milestone holds `target_value`, an allocation `allocated_target`;
        # a figure of 0 is a target of 0, not a missing one.
        whole = _num(
            holder.target_value
            if hasattr(holder, "target_value")
            else getattr(holder, "allocated_target", None)
        )
        if measure.slice == "core":
            return _num(holder.core_target)
        if measure.slice == "client":
            return _num(holder.client_target)
        return whole

    def _count(self, milestone, measure: Measure, scope: Scope) -> Target | None:
        if scope.kind == "country":
            annual = self._slice(milestone, measure)
            if annual is None:
                return None
            # The country's months are its teams' approved phasing (else its
            # officers'), which is how the milestone was spread.
            spread = self._teams_of.get(milestone.code) or self._staff_of.get(
                milestone.code, []
            )
            return Target(
                annual=annual,
                source="Country milestone",
                months=self._phasing(spread, measure) if spread else None,
                milestone=milestone,
            )
        allocations = self._allocations(milestone.code, scope)
        if not allocations:
            return None
        values = [self._slice(a, measure) for a in allocations]
        if all(v is None for v in values):
            return None
        months = self._phasing(allocations, measure)
        source = (
            "Team allocation"
            if allocations[0].allocated_to_type == "team"
            else "Allocation"
        )
        return Target(
            annual=sum(v or 0 for v in values),
            source=source,
            months=months,
            milestone=milestone,
        )

    def _phasing(self, allocations, measure: Measure) -> dict[int, float] | None:
        months: dict[int, float] = defaultdict(float)
        phased = False
        for allocation in allocations:
            rows = self._months.get(str(allocation.id))
            if not rows:
                continue
            phased = True
            share = 1.0
            whole = _num(allocation.allocated_target)
            part = self._slice(allocation, measure)
            if measure.slice and whole and part is not None:
                share = part / whole
            for month, value in rows.items():
                months[month] += value * share
        return dict(months) if phased else None

    def _rate(self, milestone, measure: Measure, scope: Scope, eligible) -> Target:
        rate = _num(milestone.target_value)
        source = "Country milestone"
        allocations = self._allocations(milestone.code, scope)
        if allocations and allocations[0].allocated_target is not None:
            rate = _num(allocations[0].allocated_target)
            source = (
                "Team allocation"
                if allocations[0].allocated_to_type == "team"
                else "Allocation"
            )
        if rate is None or eligible is None:
            return Target(annual=None, source=NOT_SET, rate=rate, milestone=milestone)
        return Target(
            annual=float(round(rate / 100.0 * eligible)),
            source=f"{rate:g}% of eligible schools ({source.lower()})",
            rate=rate,
            milestone=milestone,
        )
