"""The District Type of a planned activity, as every table and export shows
it: Primary District, Secondary District or Mixed.

Owner, 2026-10-12: "all plans (Trainings, school visits and field events) in
the primary district is marked as Primary district and all that are in
secondary district it is marked as secondary district. Only those that are
crossing from primary to secondary on the same day can be mixed", then: "Add
District and district type column to the export and also to My Plan ...
literally on all the tables and in all exports".

An activity that shares a costed day (a Daily Visit Batch) carries the day's
mark, worked out from every live member of that day exactly as the day is
priced (`pricing.day_district_mark`): the visit in the primary district on a
day that also goes to a secondary one reads Mixed, because that is the rate
its transport was bought at. An activity on no shared day carries its own
district's type for the person responsible.

One function, read in bulk: a table asks once for all its rows.
"""

from __future__ import annotations

from collections.abc import Iterable

from apps.core.activity_types import NON_FUNDABLE_ACTIVITY_STATUSES

from .districts import district_type_for_staff
from .pricing import DAY_MARK_LABELS, MIXED_DAY, PRIMARY_DAY, day_district_mark

#: The column's heading, the same words everywhere.
DISTRICT_TYPE_HEADER = "District Type"
NO_MARK = "—"
_CHUNK = 5000


def _chunks(values: list):
    for start in range(0, len(values), _CHUNK):
        yield values[start : start + _CHUNK]


def district_type_marks(activity_ids: Iterable) -> dict[str, str]:
    """``{activity id: "primary" | "secondary" | "mixed"}`` for the ids given.

    An id that names no activity is left out. Seven queries at most, whatever
    the number of ids (chunked for the country exports)."""
    from apps.accounts.models import StaffProfile
    from apps.activities.models import Activity
    from apps.geography.models import District

    from .models import DailyVisitBatch

    ids = [i for i in dict.fromkeys(activity_ids) if i]
    if not ids:
        return {}

    fields = (
        "id",
        "responsible_staff_id",
        "planned_date",
        "daily_visit_batch_id",
        "school__district_id",
        "cluster__district_id",
        "event_district_id",
    )
    rows = []
    for chunk in _chunks(ids):
        rows.extend(Activity.objects.filter(id__in=chunk).values_list(*fields))

    # The person a day belongs to is a user; a plan names a staff profile.
    staff_ids = {row[1] for row in rows if row[1]}
    user_of = (
        dict(StaffProfile.objects.filter(id__in=staff_ids).values_list("id", "user_id"))
        if staff_ids
        else {}
    )

    # An in-school training priced inside its visit sits on no day of its
    # own; it is on its person's day all the same.
    batch_ids = {row[3] for row in rows if row[3]}
    loose = {
        (str(user_of.get(row[1], row[1])), row[2])
        for row in rows
        if not row[3] and row[1] and row[2]
    }
    day_of: dict[tuple, str] = {}
    if loose:
        for batch_id, user_id, day in DailyVisitBatch.objects.filter(
            responsible_user__in={user for user, _ in loose},
            visit_date__in={day for _, day in loose},
        ).values_list("id", "responsible_user", "visit_date"):
            if (str(user_id), day) in loose:
                day_of[(str(user_id), day)] = batch_id
                batch_ids.add(batch_id)

    owner_of = (
        dict(
            DailyVisitBatch.objects.filter(id__in=batch_ids).values_list(
                "id", "responsible_user"
            )
        )
        if batch_ids
        else {}
    )
    members: dict[str, list] = {}
    if batch_ids:
        for batch_id, school_d, cluster_d, event_d in (
            Activity.objects.filter(
                daily_visit_batch_id__in=batch_ids, deleted_at__isnull=True
            )
            .exclude(status__in=NON_FUNDABLE_ACTIVITY_STATUSES)
            .values_list(
                "daily_visit_batch_id",
                "school__district_id",
                "cluster__district_id",
                "event_district_id",
            )
        ):
            members.setdefault(batch_id, []).append(school_d or cluster_d or event_d)

    district_ids = {row[4] or row[5] or row[6] for row in rows} | {
        d for ds in members.values() for d in ds
    }
    district_ids.discard(None)
    districts = (
        {d.id: d for d in District.objects.filter(id__in=district_ids)}
        if district_ids
        else {}
    )

    types: dict[tuple, str] = {}

    def type_for(person, district_id) -> str:
        """Primary or secondary for this person in this district; work with
        no district on record is at home, as the day prices it."""
        key = (person, district_id)
        if key not in types:
            district = districts.get(district_id)
            types[key] = (
                district_type_for_staff(person, district) if district else None
            ) or PRIMARY_DAY
        return types[key]

    day_marks: dict[str, str] = {}

    def day_mark(batch_id) -> str:
        if batch_id not in day_marks:
            owner = owner_of.get(batch_id)
            day_marks[batch_id] = day_district_mark(
                type_for(owner, d) for d in members.get(batch_id, ())
            )
        return day_marks[batch_id]

    marks: dict[str, str] = {}
    for activity_id, staff_id, day, batch_id, school_d, cluster_d, event_d in rows:
        own = type_for(staff_id, school_d or cluster_d or event_d)
        if not batch_id and staff_id:
            # (Some plans name the user directly, not their staff profile.)
            batch_id = day_of.get((str(user_of.get(staff_id, staff_id)), day))
        if batch_id and members.get(batch_id):
            # The day's mark, with this activity's own district counted in:
            # a pair training is not a member of the day it is on.
            of_day = day_mark(batch_id)
            marks[activity_id] = (
                of_day if of_day == MIXED_DAY else day_district_mark([of_day, own])
            )
        else:
            marks[activity_id] = own
    return marks


def district_type_labels(activity_ids: Iterable) -> dict[str, str]:
    """``{activity id: "Primary District" | "Secondary District" | "Mixed"}``."""
    return {
        activity_id: DAY_MARK_LABELS[mark]
        for activity_id, mark in district_type_marks(activity_ids).items()
    }


def label_of(labels: dict, activity_id) -> str:
    """The cell for one row; a row that names no activity shows a dash."""
    return labels.get(activity_id) or NO_MARK


__all__ = [
    "DISTRICT_TYPE_HEADER",
    "NO_MARK",
    "district_type_marks",
    "district_type_labels",
    "label_of",
]
