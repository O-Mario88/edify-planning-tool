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


#: What a reader sees (owner, 2026-10-21): a CCEO their own portfolio, a
#: Programme Lead their own and their team's, IA, CD and Admin (and RVP and
#: RPL) everyone, grouped by Programme Lead.
OWN, TEAM, ALL = "own", "team", "all"


@dataclass
class Roster:
    regions: list[Region]
    #: How far the reader sees: OWN, TEAM or ALL.
    reach: str = ALL
    #: A Programme Lead reader's staff id: their team's key.
    lead: str = ""

    @property
    def own(self) -> bool:
        """The reader sees only their own row (a CCEO)."""
        return self.reach == OWN

    @property
    def narrowed(self) -> bool:
        """The reader sees part of the country, not all of it."""
        return self.reach != ALL

    @property
    def home_label(self) -> str:
        return {OWN: "Your portfolio", TEAM: "Your team"}.get(
            self.reach, "National Total"
        )

    @property
    def officers(self) -> list[Officer]:
        return [o for r in self.regions for o in r.officers]

    def officer(self, staff_id: str) -> Officer | None:
        return next((o for o in self.officers if o.staff_id == str(staff_id)), None)

    def region(self, key: str) -> Region | None:
        return next((r for r in self.regions if r.key == str(key)), None)

    def region_of(self, staff_id: str) -> Region | None:
        return next((r for r in self.regions if str(staff_id) in r.staff_ids), None)


def reach_of(user) -> str:
    role = getattr(user, "active_role", "")
    return {CCEO: OWN, LEAD: TEAM}.get(role, ALL)


def visible_staff(user) -> set[str] | None:
    """The officers whose schools a reader sees: a CCEO themselves; a
    Programme Lead themselves and the CCEOs whose direct line is to them;
    None — everyone — for anyone else who may open the report."""
    reach = reach_of(user)
    if reach == ALL:
        return None
    profile = getattr(user, "staff_profile", None)
    if profile is None:
        return {""}
    me = str(profile.id)
    if reach == OWN:
        return {me}
    from apps.accounts.models import StaffSupervisorAssignment

    supervised = StaffSupervisorAssignment.objects.filter(supervisor_id=me).values_list(
        "supervisee_id", flat=True
    )
    lines = direct_leads([str(s) for s in supervised])
    return {me} | {staff for staff, lead in lines.items() if lead == me}


def direct_leads(staff_ids) -> dict[str, str]:
    """Each officer's Programme Lead: the supervisor who is a Programme Lead
    (IA and RVP rows are oversight beside the direct line,
    `StaffSupervisorAssignment`); the first one assigned holds a CCEO with
    two."""
    from django.db.models import Q

    from apps.accounts.models import StaffSupervisorAssignment

    out: dict[str, str] = {}
    for supervisee, supervisor in (
        StaffSupervisorAssignment.objects.filter(supervisee_id__in=list(staff_ids))
        .filter(
            Q(supervisor__user__active_role=LEAD)
            | Q(supervisor__user__roles__contains=[LEAD])
        )
        .order_by("created_at", "id")
        .values_list("supervisee_id", "supervisor_id")
    ):
        if str(supervisee) != str(supervisor):
            out.setdefault(str(supervisee), str(supervisor))
    return out


def build(user, ledger) -> Roster:
    from apps.accounts.models import User

    reach = reach_of(user)
    visible = visible_staff(user)
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
    for staff_id, lead in direct_leads(officers).items():
        if officers[staff_id].role == CCEO:
            officers[staff_id].lead = lead
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
        if visible is not None:
            members = [o for o in members if o.staff_id in visible]
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
    lead_key = ""
    if reach == TEAM and visible:
        lead_key = str(getattr(getattr(user, "staff_profile", None), "id", ""))
    return Roster(regions=regions, reach=reach, lead=lead_key)


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
