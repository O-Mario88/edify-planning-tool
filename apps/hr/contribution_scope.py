"""Delivery ownership and monitored partner accountability, shared by all rollups."""

from django.db.models import Q


def owner_ids(staff, include_team=False) -> frozenset[str]:
    """Every id a person's work may be filed under (StaffProfile and User),
    with their team's when asked. Read once a request (`request_cache`): a
    team's target page asks for it once per allocation."""
    from apps.core.request_cache import memoize

    staff_id = str(getattr(staff, "id", staff))
    return memoize(
        ("contribution_scope.owner_ids", staff_id, bool(include_team)),
        lambda: _owner_ids(staff_id, include_team),
    )


def _owner_ids(staff_id: str, include_team: bool) -> frozenset[str]:
    from apps.accounts.models import StaffProfile, StaffSupervisorAssignment

    ids = {staff_id}
    if include_team:
        ids.update(
            str(x)
            for x in StaffSupervisorAssignment.objects.filter(
                supervisor_id=staff_id
            ).values_list("supervisee_id", flat=True)
        )
    users = StaffProfile.objects.filter(id__in=ids).values_list("user_id", flat=True)
    return frozenset(ids | {str(x) for x in users if x})


def country_staff_ids(country: str) -> frozenset[str]:
    """Every id the country's staff file work under, read once a request: a
    country rollup asks for it once per allocation (1,318 identical queries
    of a Programme Lead's To-Do queue, 2026-10-24)."""
    from apps.core.request_cache import memoize

    def read() -> frozenset[str]:
        from apps.accounts.models import StaffProfile

        rows = StaffProfile.objects.filter(country=country).values_list("id", "user_id")
        return frozenset(str(v) for row in rows for v in row if v)

    return memoize(("contribution_scope.country_staff_ids", country), read)


def scope_activities(queryset, *, staff=None, include_team=False, country=None):
    if staff is not None:
        ids = owner_ids(staff, include_team)
        # AUD-005: a partner activity still names the school's owner as
        # responsible_staff_id (230 of 231 partner rows in dev). That name is
        # custody, not delivery — the credit goes to whoever MONITORED the
        # partner, and to nobody through the responsible column.
        return queryset.filter(
            (Q(responsible_staff_id__in=ids) & ~Q(delivery_type="partner"))
            | Q(delivery_type="partner", monitored_by_staff_id__in=ids)
        ).distinct()
    if country:
        from apps.core.scoping import school_in_country_q

        ids = country_staff_ids(country)
        # An explicit school country takes precedence over the staff country.
        # The school arm is the shared boundary rather than `region__country`
        # written out again, so work planned at a school the upload could not
        # place counts here as it does everywhere else — otherwise the country
        # rollups silently dropped every activity standing at one.
        return queryset.filter(
            school_in_country_q(country, "school__")
            | Q(school__isnull=True, cluster__district__region__country=country)
            | Q(school__isnull=True, cluster__isnull=True)
            & (Q(responsible_staff_id__in=ids) | Q(monitored_by_staff_id__in=ids))
        ).distinct()
    return queryset
