"""A Partner's work is dated by the Partner (owner, 2026-10-05).

"The date on the partner assignment drawer should change from target date to
assigned date so that the staff cannot schedule for the partner. Block any
potential scheduling for the partner visit."

Staff hand a school over; the Partner chooses the day. A hand-over therefore
carries the day it was made and no other date, and every door that puts a
date on work an assigned Partner delivers asks ``assert_partner_dates_it``:
creating it already dated, dating a hand-over, dating or moving the Partner's
activity, and moving a staff visit that has a date onto a Partner.

The one exception is the other partner workflow (``ExecutorType``): a
Certified Partner Agency is booked by Edify onto a day, so that day is
staff's by design.
"""

from __future__ import annotations

from apps.core.exceptions import Forbidden


def acts_for_partner(principal) -> bool:
    """Is the person acting one of a Partner's own users?"""
    from apps.planning.country_oversight.rules import is_partner_principal

    return is_partner_principal(principal)


def is_agency_booking(activity) -> bool:
    """Work Edify booked a Certified Partner Agency onto, on a day staff chose."""
    from apps.core.enums import ExecutorType

    executor = getattr(activity, "executor_type", "") or ""
    return executor == ExecutorType.CERTIFIED_PARTNER_AGENCY


def refusal(partner_name: str = "") -> str:
    """Why staff cannot date this work, and what they do instead."""
    partner = partner_name or "The partner"
    return (
        f"{partner} chooses the date for this work. Assign the school to the "
        "partner and they schedule it; to take the work back, withdraw it "
        "from the partner."
    )


def partner_name_for(partner_id) -> str:
    if not partner_id:
        return ""
    from apps.partners.models import Partner

    return (
        Partner.all_objects.filter(id=partner_id).values_list("name", flat=True).first()
        or ""
    )


def assert_partner_dates_it(principal, partner_id=None) -> None:
    """Refuse a date staff put on work an assigned Partner delivers."""
    if acts_for_partner(principal):
        return
    raise Forbidden(refusal(partner_name_for(partner_id)))


def partner_has_dated(activity) -> bool:
    """Has the Partner put this work on a day of their own?

    An activity still ``assigned_to_partner`` waits for the Partner whatever
    date it carries: a Partner's own scheduling moves it to
    ``partner_scheduled``. A date staff put on it is marked as theirs.
    """
    from apps.planning.country_oversight.rules import DATED_BY_STAFF

    if activity is None:
        return False
    if (getattr(activity, "status", "") or "") == "assigned_to_partner":
        return False
    if (getattr(activity, "partner_date_set_by", "") or "") == DATED_BY_STAFF:
        return False
    return bool(
        getattr(activity, "planned_date", None)
        or getattr(activity, "scheduled_date", None)
    )
