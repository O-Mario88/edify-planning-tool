"""Tell a Programme Lead or a CCEO who holds too few schools to recruit more.

Owner, 2026-10-07: 280 and 560 are the visits a Programme Lead and a CCEO
plan in a year whatever they hold, "but those with less should be notified to
recruit more schools to meet the target".

Somebody is short when the schools they hold cannot take the visits of their
target at two a Core school and one each of the others
(``rules.Workload.short_of_target``, the figure the Planning Monitor and My
Plan show beside their visits). They get one notice for as long as that
holds, opening My Plan, which says how many schools are still needed; the
notice says no number, so it is never out of date. It is closed the day they
hold enough, and a person who falls short again later is told again.

Run once a day with the day's plan notices (apps.realtime.jobs). Read only
but for the notices: nothing here assigns a school to anybody.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Count

from apps.planning.country_oversight import rules

RECRUIT_SCHOOLS_EVENT = "planning_recruit_schools"
CONTEXT_TYPE = "visit_target"
TITLE = "Recruit more schools to meet your visit target"


@dataclass(frozen=True)
class Portfolio:
    """One Programme Lead or CCEO, and the schools they hold."""

    person: rules.Person
    core: int = 0
    client: int = 0

    @property
    def workload(self) -> rules.Workload:
        return rules.workload(self.person.target, self.core, self.client)

    @property
    def schools_to_recruit(self) -> int:
        return self.workload.short_of_target


def portfolios() -> list[Portfolio]:
    """Every Programme Lead and CCEO with the Core and the Client, Core
    Trained and Core Graduate schools they hold, as the Planning Monitor's
    rows count them: operating schools, filed by ``account_owner_id`` in
    either of the holder's id spaces. Two queries beside the roster's."""
    from apps.planning.planning_monitor import CORE_TYPES, MONITORED_TYPES
    from apps.schools.lifecycle_service import active_schools

    people = [person for team in rules.roster() for person in team.people]
    owner_of = {str(i): person.key for person in people for i in person.ids}
    held: dict[str, list[int]] = {person.key: [0, 0] for person in people}
    for owner_id, school_type, n in (
        active_schools()
        .filter(school_type__in=MONITORED_TYPES, account_owner_id__in=list(owner_of))
        .values_list("account_owner_id", "school_type")
        .annotate(n=Count("id"))
        .order_by()
    ):
        held[owner_of[str(owner_id)]][0 if school_type in CORE_TYPES else 1] += n
    return [
        Portfolio(person=person, core=held[person.key][0], client=held[person.key][1])
        for person in people
    ]


def _body(portfolio: Portfolio) -> str:
    return (
        f"You plan {portfolio.person.target:,} visits a year, and the schools you "
        "hold take fewer than that. Recruit more schools to meet your target. "
        "My Plan shows how many you still need."
    )


def sweep() -> int:
    """Open a notice for everybody who is short and has none; close the
    notice of everybody who is not short any more. Returns how many were
    opened."""
    from apps.notifications.models import Notification
    from apps.notifications.services import (
        WorkflowNotificationService,
        resolve_condition,
    )

    everyone = portfolios()
    # Told already, and still true: an archived notice counts, so somebody
    # who cleared theirs is not told again every morning.
    told = set(
        Notification.objects.filter(
            source_event_type=RECRUIT_SCHOOLS_EVENT,
            context_type=CONTEXT_TYPE,
            resolved_at__isnull=True,
        ).values_list("context_id", flat=True)
    )
    short = {p.person.key for p in everyone if p.schools_to_recruit}
    opened = 0
    for portfolio in everyone:
        key = portfolio.person.key
        if key in short and key not in told:
            sent = WorkflowNotificationService.trigger(
                event_type=RECRUIT_SCHOOLS_EVENT,
                category="planning",
                priority="normal",
                title=TITLE,
                body=_body(portfolio),
                context_type=CONTEXT_TYPE,
                context_id=key,
                recipients=[portfolio.person.user_id or key],
            )
            opened += 1 if sent else 0
    # Holds enough now, or is no longer a Lead or a CCEO.
    for key in told - short:
        resolve_condition(RECRUIT_SCHOOLS_EVENT, CONTEXT_TYPE, key)
    return opened


__all__ = [
    "CONTEXT_TYPE",
    "RECRUIT_SCHOOLS_EVENT",
    "TITLE",
    "Portfolio",
    "portfolios",
    "sweep",
]
