"""What a member of staff has planned: one definition for every page.

Owner, 2026-10-02: "There is a discrepancy in the actual numbers seen by PL
Planning against target and planning oversight and the ones seen on CCEO my
plan. CCEO sees less and PL sees more. ... make sure those pages are picking
the actual planned activities by staff."

Three pages answered that question three ways:

* **My Plan** counted what was still AHEAD: its "planned this week / month /
  quarter / year" tiles dropped every activity once its date had passed, the
  delivered ones too, so a person's year shrank by the day while their
  Programme Lead went on reading all of it. Its visits tile counted by a list
  of activity types of its own.
* **Team Plan** (Planning Oversight) lists every live activity of the person.
* **The Planning Monitor** counts the rulebook's visits: Follow up, In-school
  Training and SSA Support, planned and dated.

They now read this module:

``own_plan_q``
    The activities that are a person's own plan — theirs to deliver, by staff,
    in a live state. My Plan's tiles and the Team Plan tab count these, so the
    two agree row for row. A date that has passed does not take an activity
    off somebody's plan; nor does delivering it.

``visit_tallies``
    Of those, the visits that count toward the 560 a CCEO and the 280 a
    Programme Lead plan in a year (``country_oversight.rules``). The Planning
    Monitor's "Visits planned" and My Plan's visits tile are this one count.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Count, Q

#: The two states only a Partner's work carries.
PARTNER_ONLY_STATUSES = ("assigned_to_partner", "partner_scheduled")

#: School types whose visits are the Core package's (two staff visits a year).
CORE_TYPES = ("core",)


def live_statuses() -> tuple[str, ...]:
    """The states in which staff work is on somebody's plan: every state
    Planning Oversight lists (``oversight_service.LIVE_ACTIVITY_STATUSES``),
    less the Partner's two."""
    from apps.planning.oversight_service import LIVE_ACTIVITY_STATUSES

    return tuple(s for s in LIVE_ACTIVITY_STATUSES if s not in PARTNER_ONLY_STATUSES)


def own_plan_q(staff_ids) -> Q:
    """A person's own plan: what they deliver themselves, in a live state.

    ``staff_ids`` are the person's ids in BOTH spaces — the StaffProfile id
    and the User id (``apps.core.scoping.owner_ids``):
    ``Activity.responsible_staff_id`` holds either. Partner-delivered work is
    the Partner's plan and is followed on Partner Monitoring (owner,
    2026-09-26). Deletion and the fiscal year are the caller's.
    """
    return (
        Q(responsible_staff_id__in=list(staff_ids))
        & ~Q(delivery_type="partner")
        & Q(status__in=live_statuses())
    )


def not_yet_delivered_q() -> Q:
    """Work on a plan that has not been carried out or sent back."""
    from apps.activities.services import RETURNED_STATUSES
    from apps.core.activity_types import COMPLETED_WORK_STATUSES

    return ~Q(status__in=COMPLETED_WORK_STATUSES) & ~Q(status__in=RETURNED_STATUSES)


def past_due_q(today) -> Q:
    """Planned for a day that has passed and not yet delivered."""
    return not_yet_delivered_q() & (
        Q(planned_date__lt=today)
        | Q(planned_date__isnull=True, scheduled_date__date__lt=today)
    )


@dataclass
class VisitTally:
    """One person's counted visits in a year."""

    core: int = 0
    client: int = 0
    delivered: int = 0

    @property
    def total(self) -> int:
        return self.core + self.client


def counted_visits(queryset):
    """The visits in ``queryset`` that count toward a person's target: a
    Follow up or an In-school Training at a school, delivered
    by staff, planned and dated, not deleted (the planning rulebook)."""
    from apps.planning.country_oversight import rules

    return queryset.filter(
        rules.planned_q(),
        rules.counted_visit_q(),
        rules.staff_delivery_q(),
        deleted_at__isnull=True,
    )


def delivered_statuses() -> frozenset:
    from apps.planning.school_planning_badges import (
        AWAITING_VERIFICATION_STATUSES,
        VERIFIED_STATUSES,
    )

    return frozenset(AWAITING_VERIFICATION_STATUSES) | frozenset(VERIFIED_STATUSES)


def visit_tallies(ids_by_person: dict, fy: str, *, within: Q | None = None) -> dict:
    """Each person's counted visits in ``fy``, in one query.

    ``ids_by_person`` maps a key of the caller's choosing to that person's
    ids in both spaces. Counted by who planned the visit — the responsible
    officer — wherever the school is: a CCEO's visit at a colleague's school
    is one of the CCEO's 560. Core or client by the school's type.

    ``within`` narrows the year to a part of it (My Plan's month or quarter).
    """
    from apps.activities.models import Activity

    key_of = {
        str(staff_id): key
        for key, staff_ids in ids_by_person.items()
        for staff_id in staff_ids
        if staff_id
    }
    tallies = {key: VisitTally() for key in ids_by_person}
    if not key_of:
        return tallies
    rows = counted_visits(
        Activity.objects.filter(responsible_staff_id__in=list(key_of), fy=str(fy))
    )
    if within is not None:
        rows = rows.filter(within)
    delivered = delivered_statuses()
    for row in (
        rows.values("responsible_staff_id", "school__school_type", "status")
        .annotate(n=Count("id"))
        .order_by()
    ):
        key = key_of.get(str(row["responsible_staff_id"]))
        if key is None:
            continue
        tally = tallies[key]
        if row["school__school_type"] in CORE_TYPES:
            tally.core += row["n"]
        else:
            tally.client += row["n"]
        if row["status"] in delivered:
            tally.delivered += row["n"]
    return tallies


def visit_tally(staff_ids, fy: str, *, within: Q | None = None) -> VisitTally:
    """One person's counted visits (``visit_tallies``)."""
    return visit_tallies({"me": staff_ids}, fy, within=within)["me"]


def visits_target(principal) -> int:
    """The visits this person plans in a year by the role they hold: 280 for
    a Programme Lead, 560 for a CCEO, none for anyone else."""
    from apps.planning.country_oversight import rules

    role = rules.planning_role(
        getattr(principal, "roles", None), getattr(principal, "active_role", None)
    )
    return rules.target_for(role)


def ceiling_notice(principal, fy: str) -> str:
    """What to tell somebody whose counted visits in ``fy`` have passed the
    visits their role plans in a year; "" while they are within it.

    The ceiling warns and never refuses (owner, 2026-10-03: "platform should
    not refuse just warn and let it through"): the visit that took them past
    it is saved like any other, and this is said beside the confirmation.
    """
    from apps.core.scoping import owner_ids
    from apps.planning.country_oversight import rules

    cap = visits_target(principal)
    if not cap:
        return ""
    planned = visit_tally(owner_ids(principal), str(fy)).total
    over = rules.over_ceiling(planned, cap)
    if not over:
        return ""
    return (
        f"You have now planned {planned:,} visits for FY{fy}: {over:,} past the "
        f"{cap:,} your role plans in a year. Visits past it are the Partner's "
        "share, so hand those schools to a Partner."
    )


def own_workload(principal, fy: str) -> dict | None:
    """A Programme Lead's or CCEO's own year, shared out (``rules.workload``):
    the staff visits their schools take — two at each Core school, then one
    at each other school until the ceiling is reached — what they have
    planned against it, and how many of their schools are the Partner's.
    None for anybody whose role plans no visits. Two queries.
    """
    from apps.core.scoping import owner_ids
    from apps.planning.country_oversight import rules
    from apps.schools.lifecycle_service import active_schools
    from apps.schools.models import School

    cap = visits_target(principal)
    if not cap:
        return None
    ids = owner_ids(principal)
    held: dict[str, int] = {}
    for school_type, n in (
        active_schools(School.objects.filter(account_owner_id__in=ids))
        .values_list("school_type")
        .annotate(n=Count("id"))
        .order_by()
    ):
        held[school_type or ""] = n
    share = rules.workload(
        cap,
        held.get("core", 0),
        sum(held.get(t, 0) for t in rules.CLIENT_RULE_TYPES),
    )
    tally = visit_tally(ids, str(fy))
    return {
        "fy": str(fy),
        "ceiling": cap,
        "planned": tally.total,
        "over": rules.over_ceiling(tally.total, cap),
        "core_planned": tally.core,
        "core_target": share.staff_core_visits,
        "client_planned": tally.client,
        "client_target": share.staff_client_visits,
        "partner_schools": share.partner_client_visits,
        "partner_core_visits": share.partner_core_visits,
        "partner_target": share.partner_visits,
        "core_only": share.core_only,
        "core_over": share.core_over,
    }


__all__ = [
    "CORE_TYPES",
    "PARTNER_ONLY_STATUSES",
    "VisitTally",
    "ceiling_notice",
    "own_workload",
    "counted_visits",
    "delivered_statuses",
    "live_statuses",
    "not_yet_delivered_q",
    "own_plan_q",
    "past_due_q",
    "visit_tallies",
    "visit_tally",
    "visits_target",
]
