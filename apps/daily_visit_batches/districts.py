"""Resolve a visit's district type — primary or secondary — for the person
travelling, which decides whether the day is transport and lunch or the full
per diem with a night's accommodation.

The rule (school visit costing spec, 2026-09-26) turns on the person's role:

* Field staff — a CCEO or a Program Lead — have exactly one primary district
  on their profile. A visit there is primary; a visit anywhere else, Kampala
  included, is secondary.
* Everyone else is head office — the Country Director, Impact Assessment,
  the Accountant, HR and so on — and works from the Kampala, Wakiso and
  Mukono zone. A visit to one of those three districts is primary; a visit
  to any other district is secondary.

``resolve_district_type`` is the rule on plain values, shared with the pure
calculator in apps.budget.school_visit_costing; ``district_type_for_staff``
applies it to a staff member and a District row.
"""

from __future__ import annotations

from django.db.models import Q

from apps.core.rbac import EdifyRole

# The head-office zone, matched on the district's name, case-insensitively.
HQ_PRIMARY_DISTRICTS: tuple[str, ...] = ("Kampala", "Wakiso", "Mukono")
_HQ_ZONE = frozenset(name.casefold() for name in HQ_PRIMARY_DISTRICTS)

# The roles that hold one primary district of their own.
FIELD_ROLES: frozenset[str] = frozenset(
    {EdifyRole.CCEO.value, EdifyRole.COUNTRY_PROGRAM_LEAD.value}
)
# Aliases the spec and the field use for the same two roles.
_FIELD_ROLE_ALIASES = frozenset({"pl", "cceo", "program lead", "programme lead"})

PRIMARY = "primary"
SECONDARY = "secondary"


def _norm(value) -> str:
    return str(value or "").strip().casefold()


def is_field_role(role) -> bool:
    """Whether ``role`` is one of the two field roles that hold a primary
    district of their own; anything else, or no role at all, is head office."""
    if role is None:
        return False
    text = str(getattr(role, "value", role))
    return text in FIELD_ROLES or _norm(text) in _FIELD_ROLE_ALIASES


def hq_district_type(district_name) -> str:
    """The district type of a visit by head-office staff: primary inside the
    Kampala, Wakiso and Mukono zone, secondary anywhere else."""
    return PRIMARY if _norm(district_name) in _HQ_ZONE else SECONDARY


def resolve_district_type(role, primary_district, target_district) -> str:
    """The rule on plain values: the person's role, the primary district on
    their profile (a name or an id; None when none is configured) and the
    district visited, compared the same way.

    Raises ``ValueError`` for a field role with no primary district: the
    spec requires exactly one, and guessing would price the day wrong.
    """
    if not _norm(target_district):
        raise ValueError("target_district is required")
    if is_field_role(role):
        if not _norm(primary_district):
            raise ValueError(
                f"a {role} must have exactly one primary district configured "
                f"before a visit can be priced"
            )
        return (
            PRIMARY if _norm(primary_district) == _norm(target_district) else SECONDARY
        )
    return hq_district_type(target_district)


def district_type_for_staff(responsible_id, district):
    """The district type of a visit to ``district`` by the staff member
    ``responsible_id`` (a User id or a StaffProfile id).

    Field staff are read against the primary district on their profile;
    head-office staff against the Kampala, Wakiso and Mukono zone, whatever
    their profile says. The district's own legacy classification answers only
    when there is nobody to resolve for, or a field profile has no primary
    district yet — the spec requires one, and until it is set the day prices
    as it always did rather than refusing to price at all.
    """
    if district is None:
        return PRIMARY
    from apps.accounts.models import StaffProfile

    profile = (
        StaffProfile.objects.filter(Q(user_id=responsible_id) | Q(id=responsible_id))
        .select_related("user")
        .first()
        if responsible_id
        else None
    )
    if profile is None:
        return district.district_type
    user = profile.user
    roles = list(getattr(user, "roles", None) or [])
    role = getattr(user, "active_role", None) or (roles[0] if roles else None)
    if is_field_role(role):
        home = profile.primary_district_id
        if home:
            return PRIMARY if str(home) == str(district.pk) else SECONDARY
        return district.district_type
    return hq_district_type(district.name)


__all__ = [
    "HQ_PRIMARY_DISTRICTS",
    "FIELD_ROLES",
    "PRIMARY",
    "SECONDARY",
    "is_field_role",
    "hq_district_type",
    "resolve_district_type",
    "district_type_for_staff",
]
