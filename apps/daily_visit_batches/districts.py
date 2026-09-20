"""Resolve travel rates against the responsible staff member's home district."""

from django.db.models import Q


def district_type_for_staff(responsible_id, district):
    """Use the user configuration first; retain legacy classification if unset.

    A district can be primary for one officer and secondary for another.
    Responsible IDs may refer to either User or StaffProfile.
    """
    if district is None:
        return "primary"
    from apps.accounts.models import StaffProfile

    home = (
        StaffProfile.objects.filter(Q(user_id=responsible_id) | Q(id=responsible_id))
        .values_list("primary_district_id", flat=True)
        .first()
    ) if responsible_id else None
    if home:
        return "primary" if str(home) == str(district.pk) else "secondary"
    return district.district_type
