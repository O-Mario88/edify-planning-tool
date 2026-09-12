"""Whose people records a viewer may read: one rule for every HR surface.

The HR role is the Regional Human Resource Director (owner, 2026-09-12). They
work with the Regional Vice President and the Country Directors of a region,
so their reach is the countries of that region: the geography an
administrator assigns names the countries (as for the Regional Programme
Lead, ``apps.core.scoping._regional_reach``). With no geography assigned the
director keeps the country on their own People record, as HR always has.
That fallback is deliberately narrow: widening an unassigned HR account to
every country would silently hand a country HR officer the whole platform.

Every other role keeps the rule the HR surfaces applied before this module
existed, in nine private copies that had started to disagree: Admin reads the
whole organisation, a Programme Lead reads their own team, and any other role
reads the country on their own People record.

A page asks ``people_reach(user)`` once and narrows with the helpers below; it
never re-derives the rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.db.models import Q

HR_DIRECTOR_ROLE = "HumanResources"
_PROGRAMME_LEAD_ROLES = frozenset({"Program Lead", "ProgramLead"})

# How a reach bounds a query.
ALL = "all"  # no boundary
COUNTRIES = "countries"  # People records whose country is listed
TEAM = "team"  # the viewer and the people they supervise
NONE = "none"  # nothing


@dataclass(frozen=True)
class PeopleReach:
    kind: str
    countries: tuple[str, ...] = ()
    # False only for a Regional HR Director with no geography assigned, whose
    # reach falls back to the country on their own People record.
    assigned: bool = True
    viewer_staff_id: str | None = None
    # Every country the platform knows, for filter options.
    known_countries: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_everything(self) -> bool:
        return self.kind == ALL

    def label(self) -> str:
        if self.kind == ALL:
            return "All countries"
        if self.kind == TEAM:
            return "Your team"
        if self.kind == NONE:
            return "No countries"
        if len(self.countries) == 1:
            return self.countries[0]
        return f"{len(self.countries)} countries"

    def filter_options(self) -> tuple[str, ...]:
        """The countries a page may offer in a country filter."""
        if self.kind == ALL:
            return self.known_countries
        return self.countries

    def allows_country(self, country: str | None) -> bool:
        if self.kind == ALL:
            return True
        if self.kind == COUNTRIES:
            return bool(country) and country in self.countries
        return False


def _known_countries() -> tuple[str, ...]:
    from apps.accounts.models import StaffProfile
    from apps.geography.models import Region

    names = set(Region.objects.values_list("country", flat=True))
    names |= set(
        StaffProfile.objects.exclude(country__isnull=True)
        .exclude(country="")
        .values_list("country", flat=True)
    )
    return tuple(sorted(n for n in names if n))


def _director_countries(principal) -> tuple[str, ...]:
    """The countries a Regional HR Director's assigned geography names."""
    from apps.accounts.models import StaffGeographyAssignment
    from apps.geography.models import District, Region

    staff_id = getattr(principal, "staff_profile_id", None)
    if not staff_id:
        return ()
    rows = StaffGeographyAssignment.objects.filter(staff_id=staff_id)
    region_ids = set(
        rows.exclude(region_id__isnull=True).values_list("region_id", flat=True)
    )
    district_ids = set(
        rows.exclude(district_id__isnull=True).values_list("district_id", flat=True)
    )
    if district_ids:
        region_ids |= set(
            District.objects.filter(id__in=district_ids).values_list(
                "region_id", flat=True
            )
        )
    if not region_ids:
        return ()
    return tuple(
        sorted(
            set(
                Region.objects.filter(id__in=region_ids).values_list(
                    "country", flat=True
                )
            )
            - {""}
        )
    )


def people_reach(principal) -> PeopleReach:
    """The reach of this viewer, memoised per request."""
    from apps.core.request_cache import memoize

    return memoize(
        (
            "people_reach",
            getattr(principal, "pk", None),
            getattr(principal, "active_role", ""),
        ),
        lambda: _people_reach_uncached(principal),
    )


def _people_reach_uncached(principal) -> PeopleReach:
    role = getattr(principal, "active_role", "") or ""
    if role == "Admin" or getattr(principal, "is_superuser", False):
        return PeopleReach(ALL, known_countries=_known_countries())

    viewer = getattr(principal, "staff_profile", None)
    country = (getattr(viewer, "country", "") or "").strip() if viewer else ""

    if role == HR_DIRECTOR_ROLE:
        countries = _director_countries(principal)
        if countries:
            return PeopleReach(COUNTRIES, countries=countries)
        if country:
            return PeopleReach(COUNTRIES, countries=(country,), assigned=False)
        return PeopleReach(NONE, assigned=False)

    if role in _PROGRAMME_LEAD_ROLES and viewer:
        return PeopleReach(TEAM, viewer_staff_id=viewer.id)
    if country:
        return PeopleReach(COUNTRIES, countries=(country,))
    return PeopleReach(NONE)


# ── Narrowing querysets ──────────────────────────────────────────────────────
def scope_profiles(profiles, reach: PeopleReach):
    """Narrow a StaffProfile queryset to the reach."""
    if reach.kind == ALL:
        return profiles
    if reach.kind == COUNTRIES:
        return profiles.filter(country__in=reach.countries)
    if reach.kind == TEAM:
        return profiles.filter(
            Q(id=reach.viewer_staff_id)
            | Q(supervisor_links__supervisor_id=reach.viewer_staff_id)
        ).distinct()
    return profiles.none()


def scope_by_staff(queryset, reach: PeopleReach, staff_field: str = "staff"):
    """Narrow any queryset that points at a StaffProfile through ``staff_field``."""
    if reach.kind == ALL:
        return queryset
    if reach.kind == COUNTRIES:
        return queryset.filter(**{f"{staff_field}__country__in": reach.countries})
    if reach.kind == TEAM:
        return queryset.filter(
            Q(**{f"{staff_field}_id": reach.viewer_staff_id})
            | Q(
                **{
                    f"{staff_field}__supervisor_links__supervisor_id": reach.viewer_staff_id
                }
            )
        ).distinct()
    return queryset.none()


def scope_users(users, reach: PeopleReach):
    """Narrow a User queryset through each user's People record."""
    if reach.kind == ALL:
        return users
    if reach.kind == COUNTRIES:
        return users.filter(staff_profile__country__in=reach.countries)
    if reach.kind == TEAM:
        return users.filter(
            Q(staff_profile__id=reach.viewer_staff_id)
            | Q(staff_profile__supervisor_links__supervisor_id=reach.viewer_staff_id)
        ).distinct()
    return users.none()


def scope_by_country(queryset, reach: PeopleReach, country_field: str = "country"):
    """Narrow a queryset whose rows carry their own country (a vacancy, a case)."""
    if reach.kind == ALL:
        return queryset
    if reach.kind == COUNTRIES:
        return queryset.filter(**{f"{country_field}__in": reach.countries})
    return queryset.none()


def user_in_reach(principal, target_user) -> bool:
    """Whether ``target_user``'s People record falls inside the viewer's reach."""
    reach = people_reach(principal)
    if reach.kind == ALL:
        return True
    profile = getattr(target_user, "staff_profile", None)
    if profile is None:
        return False
    if reach.kind == COUNTRIES:
        return (profile.country or "") in reach.countries
    if reach.kind == TEAM:
        if profile.id == reach.viewer_staff_id:
            return True
        return profile.supervisor_links.filter(
            supervisor_id=reach.viewer_staff_id
        ).exists()
    return False
