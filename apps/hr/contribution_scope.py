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
        return queryset.filter(
            Q(responsible_staff_id__in=ids)
            | Q(delivery_type="partner", monitored_by_staff_id__in=ids)
        ).distinct()
    if country:
        from apps.accounts.models import StaffProfile

        profiles = StaffProfile.objects.filter(country=country)
        ids = {str(x) for x in profiles.values_list("id", flat=True)} | {
            str(x) for x in profiles.values_list("user_id", flat=True) if x
        }
        # An explicit school country takes precedence over the staff country.
        return queryset.filter(
            Q(school__region__country=country)
            | Q(school__isnull=True, cluster__district__region__country=country)
            | Q(school__isnull=True, cluster__isnull=True)
            & (Q(responsible_staff_id__in=ids) | Q(monitored_by_staff_id__in=ids))
        ).distinct()
    return queryset
