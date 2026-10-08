"""Whose calendar a reader may open besides their own.

Owner, 2026-10-07: "can we have leads have access to calendar page for their
cceo, cd to have calendar for every one organized by tabs with theirs first".

The Calendar is personal (owner rule, 2026-08-20; `calendar_scope`) and it
still opens on the reader's own. Two readers get more tabs beside it:

* a Programme Lead: one tab for each CCEO on their team
  (`apps.hr.team_roster.team_members`, the officers of a Lead they cover
  included). An Acting Programme Lead (apps.acting) reads the team of the
  Lead who appointed them, and that Lead's own calendar first;
* the Country Director: every Programme Lead's team, the Lead first and then
  their CCEOs, and last the CCEOs who report to no Lead
  (`apps.planning.monitor_roster.monitor_roster`, the people the Planning
  Monitor follows).

Somebody else's calendar is read, never run. Nothing here grants a tick box:
those go to work the reader holds (`group_actions.tickable_ids`). A leave
request that is not approved yet stays with the person who made it.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from apps.core.rbac import EdifyRole

from .calendar_scope import plan_of

#: What the first tab is called, whoever reads it.
OWN_LABEL = "My calendar"


@dataclass(frozen=True)
class Person:
    """Somebody whose calendar the reader may open.

    ``key`` is their StaffProfile id, which is what ``?person=`` carries.
    ``ids`` are the two ids their work is written under
    (`apps.core.scoping.owner_ids`).
    """

    key: str
    name: str
    ids: frozenset = field(default_factory=frozenset)


@dataclass
class Team:
    """People who share a strip of tabs. A Programme Lead reads one team, and
    it has no name; the Country Director reads one for each Lead."""

    key: str
    name: str
    people: list = field(default_factory=list)


def teams_for(user) -> list[Team]:
    """The calendars this reader may open besides their own, by team.

    Empty for everybody but a Programme Lead and the Country Director, and for
    a Lead with nobody on their team: their Calendar is the personal page it
    always was.
    """
    role = getattr(user, "active_role", "") or ""
    if role == EdifyRole.COUNTRY_PROGRAM_LEAD.value:
        return _lead_team(user)
    if role == EdifyRole.COUNTRY_DIRECTOR.value:
        return _country_teams(user)
    return []


def _lead_team(user) -> list[Team]:
    from apps.hr.team_roster import team_members

    people = [
        Person(
            key=str(profile.id),
            name=profile.user.name or profile.user.email or str(profile.id),
            ids=frozenset(str(i) for i in (profile.id, profile.user_id) if i),
        )
        for profile in team_members(user)
    ]
    # An acting appointment is for the whole team, the Lead included: the
    # Lead is nobody's officer, so they are not on `team_members`, and their
    # calendar is read from the seat the appointment delegates.
    from apps.core.acting import SCOPE_PL_TEAM, seat

    acting = seat(user, SCOPE_PL_TEAM)
    if acting is not None:
        people.insert(
            0,
            Person(
                key=str(acting.seat_staff_id),
                name=acting.seat_name,
                ids=frozenset((str(acting.seat_staff_id), str(acting.seat_user_id))),
            ),
        )
    return [Team(key="", name="", people=people)] if people else []


def _country_teams(user) -> list[Team]:
    from django.conf import settings

    from apps.core.scoping import owner_ids
    from apps.planning.monitor_roster import NO_LEAD_KEY, monitor_roster

    # A deployment that keeps the Country Director to aggregates
    # (ALLOW_CD_OPERATIONAL_PLANNING off) refuses them every activity record;
    # a calendar of one officer's activities is those records.
    if not getattr(settings, "ALLOW_CD_OPERATIONAL_PLANNING", False):
        return []
    own = {str(i) for i in owner_ids(user)}
    teams = []
    for team in monitor_roster(user):
        people = [
            Person(key=str(person.key), name=person.name, ids=frozenset(person.ids))
            for person in team.people
            # The reader's own calendar is the first tab, not one of these.
            if not (set(person.ids) & own)
        ]
        if people:
            name = team.name if team.key == NO_LEAD_KEY else f"{team.name}'s team"
            teams.append(Team(key=str(team.key), name=name, people=people))
    return teams


def find(teams, key: str) -> tuple[Team | None, Person | None]:
    """The person ``?person=`` names and the team they are filed under, or
    nothing: a key that is not on the reader's own strip opens nobody's
    calendar but their own."""
    key = (key or "").strip()
    if key:
        for team in teams:
            for person in team.people:
                if person.key == key:
                    return team, person
    return None, None


def plan_counts(activities, holders: dict[str, frozenset]) -> dict[str, int]:
    """How many of ``activities`` are on each holder's plan, in one query.

    ``holders`` maps a tab to the ids its person's work is written under. The
    rule is `calendar_scope.plan_of`, so a tab's count is the number of
    activities its calendar draws.
    """
    counts = dict.fromkeys(holders, 0)
    tabs_of: dict[str, set[str]] = defaultdict(set)
    for tab, ids in holders.items():
        for holder_id in ids:
            tabs_of[str(holder_id)].add(tab)
    if not tabs_of:
        return counts
    rows = (
        plan_of(activities, list(tabs_of))
        .order_by()
        .values_list("responsible_staff_id", "monitored_by_staff_id", "delivery_type")
    )
    for responsible, monitor, delivery in rows:
        tabs = set(tabs_of.get(str(responsible or ""), ()))
        if delivery == "partner":
            tabs |= tabs_of.get(str(monitor or ""), set())
        for tab in tabs:
            counts[tab] += 1
    return counts


__all__ = ["OWN_LABEL", "Person", "Team", "find", "plan_counts", "teams_for"]
