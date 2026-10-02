"""The people the Planning and Execution Monitors follow.

Owner, 2026-09-29: "PL plans for maximum of 280 and CCEO 560 ... fetch the
right data based on what people have planned." The monitors used to find
their people through the schools they own, so a CCEO who planned all year but
held no school on the directory never appeared, and a Programme Lead's own
plan was read against a CCEO's 560. The roster is now the reporting line
itself:

* the **country** (Country Director, Impact Assessment, the RVP, Admin):
  every Programme Lead, each with the CCEOs they supervise, and then every
  CCEO who reports to no Programme Lead;
* a **Programme Lead**: themselves and the CCEOs they supervise (owner,
  2026-09-29: "give PLs access ... so they can follow up with their team
  members");
* a **Regional Programme Lead**: the Programme Leads whose people hold the
  schools in their region, and their teams.

Each person carries both of their id spaces, because
``Activity.responsible_staff_id`` holds a StaffProfile id or a User id
depending on the path that wrote it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: The visits a Programme Lead plans in a year (owner, 2026-09-29) and a CCEO
#: (owner, 2026-09-28): the planning rulebook's figures, under the names the
#: monitors have always used.
PL_VISITS_TARGET = 280
CCEO_VISITS_TARGET = 560

ROLE_PL = "PL"
ROLE_CCEO = "CCEO"

VISITS_TARGET_BY_ROLE = {ROLE_PL: PL_VISITS_TARGET, ROLE_CCEO: CCEO_VISITS_TARGET}

NO_LEAD_KEY = "__no_lead__"
NO_LEAD_LABEL = "No Programme Lead"


@dataclass
class Person:
    key: str  # the StaffProfile id
    name: str
    role: str  # ROLE_PL | ROLE_CCEO
    ids: frozenset = field(default_factory=frozenset)

    @property
    def visits_target(self) -> int:
        return VISITS_TARGET_BY_ROLE.get(self.role, 0)


@dataclass
class Team:
    key: str
    name: str
    people: list = field(default_factory=list)


def _role_code(role: str) -> str:
    from apps.planning.country_oversight import rules

    return {rules.PROGRAM_LEAD_ROLE: ROLE_PL, rules.CCEO_ROLE: ROLE_CCEO}.get(role, "")


def monitor_roster(principal, *, lead_ids_hint=()) -> list[Team]:
    """The teams this reader follows, each Lead first and then their CCEOs.

    The people are the planning rulebook's (apps.planning.country_oversight.
    rules.roster): a Lead or a CCEO by the role they HOLD, whichever role the
    account is switched to today, so the monitor and Country Planning
    Oversight follow the same people under the same Leads.

    ``lead_ids_hint`` — the Programme Leads a school-scoped reader (the
    Regional Programme Lead) reaches through the schools in their scope.
    """
    from apps.core.scoping import resolve_user_scope
    from apps.planning.country_oversight import rules
    from apps.planning.oversight_service import resolve_oversight_scope

    scope = resolve_oversight_scope(principal)
    country = getattr(resolve_user_scope(principal), "country", "") or ""
    if scope.is_country:
        wanted = None
    elif scope.kind == "pl":
        wanted = {str(i) for i in scope.own_ids}
    else:
        wanted = {str(i) for i in lead_ids_hint if i}

    teams = []
    for team in rules.roster(country if scope.is_country else ""):
        if team.is_no_lead:
            # Every CCEO reports somewhere: one with no Programme Lead is
            # still planning against 560 and is still followed — by the
            # country, which is the only reader they sit under.
            if wanted is not None:
                continue
        elif wanted is not None and not (set(team.people[0].ids) & wanted):
            continue
        teams.append(
            Team(
                key=NO_LEAD_KEY if team.is_no_lead else team.key,
                name=NO_LEAD_LABEL if team.is_no_lead else team.name,
                people=[
                    Person(
                        key=person.key,
                        name=person.name,
                        role=_role_code(person.role),
                        ids=frozenset(person.ids),
                    )
                    for person in team.people
                ],
            )
        )
    return teams


def roles_of(staff_ids) -> dict[str, str]:
    """ROLE_PL or ROLE_CCEO for each StaffProfile id that holds one of them."""
    from apps.accounts.models import StaffProfile
    from apps.planning.country_oversight import rules

    ids = {str(i) for i in staff_ids if i}
    if not ids:
        return {}
    found = {}
    for staff_id, roles, in_use in StaffProfile.objects.filter(id__in=ids).values_list(
        "id", "user__roles", "user__active_role"
    ):
        code = _role_code(rules.planning_role(roles, in_use) or "")
        if code:
            found[str(staff_id)] = code
    return found


__all__ = [
    "CCEO_VISITS_TARGET",
    "NO_LEAD_KEY",
    "NO_LEAD_LABEL",
    "PL_VISITS_TARGET",
    "Person",
    "ROLE_CCEO",
    "ROLE_PL",
    "Team",
    "monitor_roster",
    "roles_of",
]
