"""PlanningRequirementService — the eligible portfolio and what it owes.

Three questions, answered once for every surface of the page:

* **Which schools count?** The reader's own school lens (``scoped_school_queryset``
  keeps a country role inside its country), then only schools operating on the
  reporting date: active, or reopened by then. Closed schools, duplicate
  records and schools created after the date are outside the denominator. For a
  past fiscal year the family and the owner are read as they were on the
  reporting date, from the ownership-transfer and change-log history.

* **Who holds each school?** ``School.account_owner_id`` — the canonical account
  owner, which transfers move together with ``StaffSchoolAssignment`` — read in
  both id spaces. A CCEO's school sits under the Programme Lead they report to;
  a Programme Lead's own school is their *personal* delivery and never mixes
  with the team they supervise. Nobody's school is still counted, under its
  own heading, because a school nobody holds is exactly what a country lens
  exists to surface.

* **How is the owner's capacity spent?** Core staff slots first and in full,
  whatever the ceiling says; a ceiling below them is a visible deficit. The
  capacity left over takes Client slots; the balance of the Client slots is
  the Partner's. The split is made per school, deterministically, so any
  filtered subset of a portfolio sums to the same figures the whole of it does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import NamedTuple

from django.db.models import Q

from apps.planning.country_oversight import policy

NO_OWNER_KEY = "__unassigned__"
NO_LEAD_KEY = "__no_lead__"
NO_LEAD_LABEL = "No Programme Lead"
NO_OWNER_LABEL = "No account owner"


@dataclass
class OwnerInfo:
    """The person holding a portfolio, and where they sit in the hierarchy."""

    key: str
    name: str
    role: str = ""
    user_id: str | None = None
    lead_key: str = NO_LEAD_KEY
    lead_name: str = NO_LEAD_LABEL
    # Every Programme Lead the person reports to directly. More than one is a
    # data-quality exception; the first by name is the line used.
    lead_keys: tuple[str, ...] = ()
    active: bool = True
    ids: set = field(default_factory=set)

    @property
    def is_lead_personal(self) -> bool:
        return self.role == policy.PROGRAM_LEAD_ROLE

    @property
    def ceiling(self) -> int:
        return policy.ceiling_for(self.role) if self.active else 0

    @property
    def kind(self) -> str:
        if self.key == NO_OWNER_KEY:
            return "unassigned"
        if self.is_lead_personal:
            return "pl_personal"
        if self.role == policy.CCEO_ROLE:
            return "cceo"
        return "other"


@dataclass
class LeadInfo:
    key: str
    name: str
    user_id: str | None = None
    region_names: tuple[str, ...] = ()


def reporting_date(fy: str, today: date | None = None) -> date:
    """The day the portfolio is read on: today, or the last day of a past year."""
    from datetime import timedelta

    from apps.core.fy import get_fy_date_range

    today = today or date.today()
    _, fy_end = get_fy_date_range(str(fy))
    last_day = fy_end.date() - timedelta(days=1)
    return min(today, last_day)


def operating_on_q(as_of: date) -> Q:
    """Schools operating on ``as_of``, from their lifecycle fields.

    A reopened school enters from its reopening; a closed school leaves from
    the date its closure took effect, not from when somebody recorded it.
    """
    from apps.schools.lifecycle_models import CLOSED_STATUSES

    closed = tuple(str(status) for status in CLOSED_STATUSES)
    still_open_then = Q(closure_effective_date__gt=as_of) | Q(
        closure_effective_date__isnull=True, closed_at__date__gt=as_of
    )
    return (
        Q(operational_status="active")
        | Q(operational_status="reopened", reopened_at__isnull=True)
        | Q(operational_status="reopened", reopened_at__date__lte=as_of)
        # Reopened after the reporting date: it was operating then only if its
        # closure had not yet taken effect.
        | (
            Q(operational_status="reopened", reopened_at__date__gt=as_of)
            & still_open_then
        )
        | (Q(operational_status__in=closed) & still_open_then)
    )


def eligible_school_queryset(scope, as_of: date, base=None):
    """The schools this reader's lens may count, operating on ``as_of``.

    Duplicates of another record never count. Unplaced schools the country
    lens reaches through their owner are included, as they are everywhere else.
    """
    from apps.core.scoping import scoped_school_queryset

    queryset = scoped_school_queryset(scope, base)
    if queryset is None:
        return None
    return (
        queryset.exclude(duplicate_status__in=policy.EXCLUDED_DUPLICATE_STATUSES)
        .filter(created_at__date__lte=as_of)
        .filter(operating_on_q(as_of))
    )


def historical_adjustments(school_ids, as_of: date) -> tuple[dict, dict]:
    """(owner_as_of, type_as_of) for schools whose owner or type changed later.

    Only read for a date in the past: the earliest change after ``as_of``
    names what the school was on that day (its ``from`` side).
    """
    from apps.schools.models import SchoolChangeLog
    from apps.schools.ownership_models import SchoolOwnershipTransfer

    if as_of >= date.today():
        return {}, {}
    owners: dict[str, str] = {}
    for school_id, from_staff_id in (
        SchoolOwnershipTransfer.objects.filter(
            school_id__in=school_ids, effective_date__gt=as_of
        )
        .order_by("school_id", "effective_date", "created_at")
        .values_list("school_id", "from_staff_id")
    ):
        owners.setdefault(school_id, from_staff_id or "")
    types: dict[str, str] = {}
    for school_id, old_value in (
        SchoolChangeLog.objects.filter(
            school_id__in=school_ids,
            field_name="school_type",
            changed_at__date__gt=as_of,
        )
        .order_by("school_id", "changed_at")
        .values_list("school_id", "old_value")
    ):
        types.setdefault(school_id, old_value or "")
    try:
        from apps.core_schools.models import CoreSchoolOnboarding
        from apps.schools.models import School

        onboarded = CoreSchoolOnboarding.objects.filter(onboarded_at__date__gt=as_of)
        codes = dict(onboarded.values_list("school_id", "previous_school_type"))
        if codes:
            for pk, code in School.objects.filter(
                id__in=school_ids, school_id__in=list(codes)
            ).values_list("id", "school_id"):
                types.setdefault(pk, codes.get(code) or "")
    except Exception:  # noqa: BLE001 - history is best-effort context
        pass
    return owners, types


# ── Owners ───────────────────────────────────────────────────────────────────
def owner_directory(owner_ids) -> dict[str, OwnerInfo]:
    """Every raw owner id → the person, in either id space, in three queries.

    The line to a Programme Lead is the DIRECT one only: Impact Assessment and
    the RVP supervise the same people as overlapping oversight, and filing a
    CCEO's schools under a reviewer would be a scope change dressed as a join.
    """
    from apps.accounts.models import StaffProfile, StaffSupervisorAssignment

    ids = {str(i) for i in owner_ids if i}
    directory: dict[str, OwnerInfo] = {}
    if not ids:
        return directory
    # Soft-deleted profiles included on purpose: a school still held by
    # somebody who has left is a finding (their capacity is zero), not a row
    # to drop from the country.
    profiles = list(
        StaffProfile.all_objects.filter(Q(id__in=ids) | Q(user_id__in=ids))
        .select_related("user")
        .order_by("pk")
    )
    leads: dict[str, list[tuple[str, str]]] = {}
    for link in (
        StaffSupervisorAssignment.objects.filter(
            supervisee_id__in=[p.id for p in profiles],
            supervisor__user__active_role=policy.PROGRAM_LEAD_ROLE,
        )
        .exclude(supervisor_id=None)
        .select_related("supervisor__user")
        .order_by("supervisor__user__name", "supervisor_id")
    ):
        if link.supervisor_id == link.supervisee_id:
            continue
        name = link.supervisor.user.name or link.supervisor.user.email or ""
        pair = (link.supervisor_id, name)
        if pair not in leads.setdefault(link.supervisee_id, []):
            leads[link.supervisee_id].append(pair)

    for profile in profiles:
        user = profile.user
        role = getattr(user, "active_role", "") or ""
        active = (
            getattr(profile, "deleted_at", None) is None
            and getattr(user, "status", "active") == "active"
            and getattr(user, "deleted_at", None) is None
        )
        info = OwnerInfo(
            key=profile.id,
            name=(
                getattr(user, "name", "") or getattr(user, "email", "") or profile.id
            ),
            role=role,
            user_id=profile.user_id,
            active=active,
            ids={profile.id, *([profile.user_id] if profile.user_id else [])},
        )
        if role == policy.PROGRAM_LEAD_ROLE:
            info.lead_key, info.lead_name = profile.id, info.name
            info.lead_keys = (profile.id,)
        else:
            own_leads = leads.get(profile.id, [])
            info.lead_keys = tuple(key for key, _ in own_leads)
            if own_leads and active:
                info.lead_key, info.lead_name = own_leads[0]
        directory[profile.id] = info
        if profile.user_id:
            directory.setdefault(str(profile.user_id), info)
    return directory


def system_leads() -> list[LeadInfo]:
    """Every Programme Lead by role — a Lead with no schools still gets a row."""
    from apps.planning.oversight_service import system_program_leads

    return [
        LeadInfo(key=lead["id"], name=lead["name"], user_id=lead.get("user_id"))
        for lead in system_program_leads()
    ]


def lead_rosters(lead_keys) -> dict[str, list[OwnerInfo]]:
    """Each Programme Lead's direct reports, so a CCEO holding no school still
    reads as a row of zeroes under their Lead rather than vanishing."""
    from apps.planning.oversight_service import program_lead_rosters

    rosters: dict[str, list[OwnerInfo]] = {}
    for lead_key, members in program_lead_rosters(lead_keys).items():
        people = []
        for member in members[1:]:
            people.append(
                OwnerInfo(
                    key=member["id"],
                    name=member["name"],
                    role=policy.CCEO_ROLE,
                    lead_key=lead_key,
                    ids=set(member["ids"]),
                )
            )
        rosters[lead_key] = people
    return rosters


# ── Capacity allocation ──────────────────────────────────────────────────────
class Allocation(NamedTuple):
    """One school's share of its owner's requirement, decided per school.

    ``staff`` and ``partner`` are the visit slots each channel is expected to
    deliver; ``deficit`` is how many of the school's Core staff slots sit
    beyond the owner's ceiling (still required, still staff).

    Immutable, and there are only a handful of distinct ones, so every school
    with the same share holds the same object — which is also what keeps a
    cached dataset's 50,000 allocations to a few bytes each.
    """

    staff: int = 0
    partner: int = 0
    deficit: int = 0


_ALLOCATIONS: dict[tuple, Allocation] = {}


def _allocation(staff: int = 0, partner: int = 0, deficit: int = 0) -> Allocation:
    key = (staff, partner, deficit)
    found = _ALLOCATIONS.get(key)
    if found is None:
        found = _ALLOCATIONS.setdefault(key, Allocation(*key))
    return found


def allocate(owner: OwnerInfo | None, schools) -> dict[str, Allocation]:
    """Split an owner's portfolio between staff capacity and Partners.

    ``schools`` are that owner's SchoolFacts with ``annual_position`` read (see
    coverage). Client schools a member of staff already holds are staff's
    first, then open ones, and those a Partner holds come last, so the split
    follows the plan where there is one. Core schools a member of staff has
    planned keep their capacity ahead of the ones nobody has, which is where a
    deficit lands. Ties break on the school's code, so the split is stable.
    """
    ceiling = owner.ceiling if owner is not None else 0
    core = [s for s in schools if s.family == policy.CORE_FAMILY]
    client = [s for s in schools if s.family == policy.CLIENT_FAMILY]
    per_core = policy.requirement_for(policy.CORE_FAMILY)
    per_client = policy.requirement_for(policy.CLIENT_FAMILY)

    allocations: dict[str, Allocation] = {}
    core_staff_required = per_core.staff_visit_slots * len(core)
    over = max(0, core_staff_required - ceiling)
    ranked_core = sorted(core, key=lambda s: (-s.annual_staff_claims, s.code or s.id))
    # The deficit lands on the least-planned schools, slot by slot from the end.
    deficits: dict[str, int] = {}
    for school in reversed(ranked_core):
        if not over:
            break
        take = min(over, per_core.staff_visit_slots)
        deficits[school.id] = take
        over -= take
    for school in ranked_core:
        allocations[school.id] = _allocation(
            per_core.staff_visit_slots,
            per_core.partner_visit_slots,
            deficits.get(school.id, 0),
        )

    capacity_left = max(0, ceiling - core_staff_required)
    staff_client = min(
        len(client), capacity_left // max(1, per_client.flexible_visit_slots)
    )
    order = {"staff": 0, "open": 1, "partner": 2}
    ranked_client = sorted(
        client, key=lambda s: (order.get(s.annual_holder, 1), s.code or s.id)
    )
    for index, school in enumerate(ranked_client):
        if index < staff_client:
            allocations[school.id] = _allocation(staff=per_client.flexible_visit_slots)
        else:
            allocations[school.id] = _allocation(
                partner=per_client.flexible_visit_slots
            )
    return allocations


class PlanningRequirementService:
    """The requirement half of the page, as one importable surface."""

    reporting_date = staticmethod(reporting_date)
    eligible_school_queryset = staticmethod(eligible_school_queryset)
    owner_directory = staticmethod(owner_directory)
    system_leads = staticmethod(system_leads)
    lead_rosters = staticmethod(lead_rosters)
    allocate = staticmethod(allocate)
    family_of = staticmethod(policy.family_of)
    requirement_for = staticmethod(policy.requirement_for)
