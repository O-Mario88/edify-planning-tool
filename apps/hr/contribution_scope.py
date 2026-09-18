"""Delivery ownership and monitored partner accountability, shared by all rollups."""

from django.db.models import Q


def owner_ids(staff, include_team=False):
    from apps.accounts.models import StaffProfile, StaffSupervisorAssignment

    staff_id = getattr(staff, "id", staff)
    ids = {str(staff_id)}
    if include_team:
        ids.update(
            str(x)
            for x in StaffSupervisorAssignment.objects.filter(
                supervisor_id=staff_id
            ).values_list("supervisee_id", flat=True)
        )
    users = StaffProfile.objects.filter(id__in=ids).values_list("user_id", flat=True)
    return ids | {str(x) for x in users if x}


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
        from apps.accounts.models import StaffProfile
        from apps.core.scoping import school_in_country_q

        profiles = StaffProfile.objects.filter(country=country)
        ids = {str(x) for x in profiles.values_list("id", flat=True)} | {
            str(x) for x in profiles.values_list("user_id", flat=True) if x
        }
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
