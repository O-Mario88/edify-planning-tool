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

from django.db.models import Q

#: The visits a Programme Lead plans in a year (owner, 2026-09-29).
PL_VISITS_TARGET = 280
#: The visits a CCEO plans in a year (owner, 2026-09-28).
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


def _person(profile, role: str) -> Person:
    user = profile.user
    return Person(
        key=str(profile.id),
        name=(getattr(user, "name", "") or getattr(user, "email", "") or profile.id),
        role=role,
        ids=frozenset(str(i) for i in (profile.id, profile.user_id) if i),
    )


def _live_profiles():
    from apps.accounts.models import StaffProfile

    return StaffProfile.objects.filter(
        deleted_at__isnull=True, user__is_active=True
    ).select_related("user")


def monitor_roster(principal, *, lead_ids_hint=()) -> list[Team]:
    """The teams this reader follows, each Lead first and then their CCEOs.

    ``lead_ids_hint`` — the Programme Leads a school-scoped reader (the
    Regional Programme Lead) reaches through the schools in their scope.
    """
    from apps.accounts.models import StaffSupervisorAssignment
    from apps.core.rbac import EdifyRole
    from apps.planning.oversight_service import resolve_oversight_scope

    pl_role = EdifyRole.COUNTRY_PROGRAM_LEAD.value
    cceo_role = EdifyRole.CCEO.value
    scope = resolve_oversight_scope(principal)

    if scope.is_country:
        leads = list(_live_profiles().filter(user__active_role=pl_role))
    elif scope.kind == "pl":
        own = {str(i) for i in scope.own_ids}
        leads = list(
            _live_profiles().filter(
                Q(id__in=own) | Q(user_id__in=own), user__active_role=pl_role
            )
        )
    else:
        hint = {str(i) for i in lead_ids_hint if i}
        leads = list(
            _live_profiles().filter(
                Q(id__in=hint) | Q(user_id__in=hint), user__active_role=pl_role
            )
        )
    leads.sort(key=lambda p: ((p.user.name or p.user.email or "").casefold(), p.id))

    members: dict[str, list] = {}
    placed: set[str] = set()
    for link in (
        StaffSupervisorAssignment.objects.filter(
            supervisor_id__in=[lead.id for lead in leads],
            supervisee__deleted_at__isnull=True,
            supervisee__user__is_active=True,
            supervisee__user__active_role=cceo_role,
        )
        .select_related("supervisee__user")
        .order_by("supervisee__user__name", "supervisee_id")
    ):
        # One team per person: a CCEO linked to two Leads is followed under
        # the first, so the country total counts them once.
        if link.supervisee_id in placed:
            continue
        placed.add(link.supervisee_id)
        members.setdefault(link.supervisor_id, []).append(link.supervisee)

    teams = [
        Team(
            key=str(lead.id),
            name=_person(lead, ROLE_PL).name,
            people=[
                _person(lead, ROLE_PL),
                *(_person(p, ROLE_CCEO) for p in members.get(lead.id, [])),
            ],
        )
        for lead in leads
    ]

    if scope.is_country:
        # Every CCEO reports somewhere: one with no Programme Lead link is
        # still planning against 560 and is still followed.
        lead_linked = set(
            StaffSupervisorAssignment.objects.filter(
                supervisor__user__active_role=pl_role
            ).values_list("supervisee_id", flat=True)
        )
        loose = [
            _person(p, ROLE_CCEO)
            for p in _live_profiles()
            .filter(user__active_role=cceo_role)
            .exclude(id__in=placed | lead_linked)
            .order_by("user__name", "id")
        ]
        if loose:
            teams.append(Team(key=NO_LEAD_KEY, name=NO_LEAD_LABEL, people=loose))
    return teams


def roles_of(staff_ids) -> dict[str, str]:
    """ROLE_PL or ROLE_CCEO for each StaffProfile id that is one of them."""
    from apps.accounts.models import StaffProfile
    from apps.core.rbac import EdifyRole

    roles = {
        EdifyRole.COUNTRY_PROGRAM_LEAD.value: ROLE_PL,
        EdifyRole.CCEO.value: ROLE_CCEO,
    }
    ids = {str(i) for i in staff_ids if i}
    if not ids:
        return {}
    return {
        str(staff_id): roles[role]
        for staff_id, role in StaffProfile.objects.filter(id__in=ids).values_list(
            "id", "user__active_role"
        )
        if role in roles
    }


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
