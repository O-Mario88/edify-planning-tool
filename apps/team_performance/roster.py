"""Who the report lists: the officers, under the regions their leads run.

The workbook lists every CCEO under a region, with the region's Programme
Lead first when they hold schools of their own. A region here is a lead's
team (`StaffSupervisorAssignment`), named after the region most of its schools
are in. Owner, 2026-10-20: leads read all four regions; a CCEO reads the page
narrowed to their own row.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from apps.core.rbac import EdifyRole

#: The workbook's order; any other region follows, then officers with no lead.
REGION_ORDER = ("Eastern", "Northern", "Central", "Western")
NO_LEAD = "No Programme Lead"
CCEO = EdifyRole.CCEO.value
LEAD = EdifyRole.COUNTRY_PROGRAM_LEAD.value


@dataclass
class Officer:
    staff_id: str
    name: str
    role: str
    lead: str = ""


@dataclass
class Region:
    key: str
    label: str
    lead_name: str
    officers: list[Officer] = field(default_factory=list)

    @property
    def staff_ids(self) -> set[str]:
        return {o.staff_id for o in self.officers}


@dataclass
class Roster:
    regions: list[Region]
    #: True when the reader sees only their own row.
    own: bool = False

    @property
    def officers(self) -> list[Officer]:
        return [o for r in self.regions for o in r.officers]

    def officer(self, staff_id: str) -> Officer | None:
        return next((o for o in self.officers if o.staff_id == str(staff_id)), None)

    def region(self, key: str) -> Region | None:
        return next((r for r in self.regions if r.key == str(key)), None)

    def region_of(self, staff_id: str) -> Region | None:
        return next((r for r in self.regions if str(staff_id) in r.staff_ids), None)


def own_staff_id(user) -> str | None:
    """The reader's staff id when the page is narrowed to them (a CCEO)."""
    if getattr(user, "active_role", "") != CCEO:
        return None
    profile = getattr(user, "staff_profile", None)
    return str(profile.id) if profile else ""


def build(user, ledger) -> Roster:
    from django.db.models import Q

    from apps.accounts.models import StaffSupervisorAssignment, User

    own = own_staff_id(user)
    people = (
        User.objects.filter(status="active", deleted_at__isnull=True)
        .filter(roles__overlap=[CCEO, LEAD])
        .select_related("staff_profile")
        .order_by("name")
    )
    holders = ledger.holders()
    officers: dict[str, Officer] = {}
    leads: dict[str, str] = {}
    for person in people:
        profile = getattr(person, "staff_profile", None)
        if profile is None:
            continue
        staff_id = str(profile.id)
        roles = person.roles or []
        if LEAD in roles:
            leads[staff_id] = person.name or person.email
        # A lead is listed when they hold schools of their own.
        if CCEO in roles or staff_id in holders:
            officers[staff_id] = Officer(
                staff_id, person.name or person.email, CCEO if CCEO in roles else LEAD
            )
    # The direct line is the supervisor who is a Programme Lead; IA and RVP
    # rows are oversight beside it (`StaffSupervisorAssignment`). The first
    # one assigned holds a CCEO with two.
    for supervisee, supervisor in (
        StaffSupervisorAssignment.objects.filter(supervisee_id__in=list(officers))
        .filter(
            Q(supervisor__user__active_role=LEAD)
            | Q(supervisor__user__roles__contains=[LEAD])
        )
        .order_by("created_at", "id")
        .values_list("supervisee_id", "supervisor_id")
    ):
        officer = officers[str(supervisee)]
        if (
            officer.role == CCEO
            and not officer.lead
            and str(supervisor) != officer.staff_id
        ):
            officer.lead = str(supervisor)
    for staff_id, officer in officers.items():
        if officer.role == LEAD and staff_id in leads:
            officer.lead = staff_id

    teams: dict[str, list[Officer]] = defaultdict(list)
    for officer in officers.values():
        teams[officer.lead].append(officer)
    regions = []
    for lead, members in teams.items():
        # The lead first, then their officers by name, as the workbook lists them.
        members.sort(key=lambda o: (o.staff_id != lead, o.name.lower()))
        if own is not None:
            members = [o for o in members if o.staff_id == own]
            if not members:
                continue
        lead_name = leads.get(lead) or (_name_of(lead) if lead else "")
        tally = ledger.regions_of({o.staff_id for o in teams[lead]})
        place = max(tally, key=tally.get) if tally else ""
        label = place or lead_name or NO_LEAD
        if not lead:
            label = NO_LEAD
        regions.append(
            Region(
                key=lead or "none", label=label, lead_name=lead_name, officers=members
            )
        )
    regions.sort(key=_region_order)
    _distinguish(regions)
    return Roster(regions=regions, own=own is not None)


def _name_of(staff_id: str) -> str:
    from apps.accounts.models import StaffProfile

    profile = StaffProfile.objects.filter(id=staff_id).select_related("user").first()
    return (profile.user.name or profile.user.email) if profile else ""


def _region_order(region: Region):
    if region.label == NO_LEAD:
        return (2, 0, "")
    if region.label in REGION_ORDER:
        return (0, REGION_ORDER.index(region.label), region.lead_name)
    return (1, 0, region.label)


def _distinguish(regions: list[Region]) -> None:
    """Two leads whose teams sit in the same region are told apart by name."""
    seen = defaultdict(int)
    for region in regions:
        seen[region.label] += 1
    for region in regions:
        if seen[region.label] > 1 and region.lead_name:
            region.label = f"{region.label} ({region.lead_name})"
