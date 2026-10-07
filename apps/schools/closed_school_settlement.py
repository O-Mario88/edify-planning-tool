"""Schools that closed before closing took them out of what still held them.

Since 2026-10-07 closing a school releases its invitations to cluster
sessions not yet held, withdraws it from projects it has no work in and
closes its open data-quality issues (``lifecycle_service.close_school``;
owner: "make sure that if a school is closed they go to the closed school
list and total number updated"). A school closed before that kept all three,
so it was still listed as invited, still counted under an officer's training
ceiling and still held a place in a project.

``find`` says which closed schools still hold something; ``settle`` puts each
through the same door a closure now uses. Schools migration 0024 runs it once
on deploy, and ``python manage.py settle_closed_schools`` reports it (or, with
``--apply``, repairs any drift) afterwards. Both are safe to run again: a
settled school holds nothing, so it is not found.
"""

from __future__ import annotations

from dataclasses import dataclass

#: A session that has not been held: its invitations are still a plan
#: (``apps.activities.cluster_attendance._NOT_YET_HELD``).
NOT_YET_HELD = (
    "planned",
    "scheduled",
    "rescheduled",
    "partner_scheduled",
    "assigned_to_partner",
    "awaiting_owner_approval",
)
CLOSED = ("temporarily_closed", "permanently_closed")


@dataclass(frozen=True)
class Unsettled:
    school_pk: str
    school_code: str
    name: str
    invitations: int
    enrolments: int
    issues: int

    def line(self) -> str:
        return (
            f"{self.school_code or self.school_pk} {self.name}: "
            f"{self.invitations} invitation(s) to sessions not yet held, "
            f"{self.enrolments} project enrolment(s), "
            f"{self.issues} open data-quality issue(s)"
        )


def find(School, Attendance, Enrolment, Issue) -> list[Unsettled]:
    """Closed schools that still hold an invitation, an enrolment or an open
    issue. Takes the model classes, so a migration can pass historical ones;
    three grouped reads whatever the number of schools.
    """
    from django.db.models import Count

    closed = School.objects.filter(
        deleted_at__isnull=True, operational_status__in=CLOSED
    )
    rows = {
        pk: (code or "", name or "")
        for pk, code, name in closed.values_list("id", "school_id", "name")
    }
    if not rows:
        return []

    def tally(queryset) -> dict:
        return dict(
            queryset.values("school_id")
            .annotate(n=Count("pk"))
            .order_by()
            .values_list("school_id", "n")
        )

    invitations = tally(
        Attendance.objects.filter(
            school_id__in=list(rows),
            invited=True,
            attended=False,
            activity__deleted_at__isnull=True,
            activity__status__in=NOT_YET_HELD,
        )
    )
    enrolments = tally(Enrolment.objects.filter(school_id__in=list(rows)))
    issues = tally(Issue.objects.filter(school_id__in=list(rows), status="open"))
    found = [
        Unsettled(
            school_pk=pk,
            school_code=code,
            name=name,
            invitations=invitations.get(pk, 0),
            enrolments=enrolments.get(pk, 0),
            issues=issues.get(pk, 0),
        )
        for pk, (code, name) in rows.items()
        if invitations.get(pk) or enrolments.get(pk) or issues.get(pk)
    ]
    return sorted(found, key=lambda row: (row.name, row.school_pk))


def find_live() -> list[Unsettled]:
    from apps.activities.models import ClusterActivityAttendance
    from apps.projects.models import ProjectSchoolAssignment
    from apps.schools.models import DataQualityIssue, School

    return find(
        School, ClusterActivityAttendance, ProjectSchoolAssignment, DataQualityIssue
    )


def settle(school_pk: str) -> dict:
    """Put one closed school through what a closure now does. Live code.

    Invitations are released from the day the school closed, so a session it
    attended, or one held before it closed, is left as it was. An enrolment
    its project delivered work under stays: it is that work's record.
    """
    from django.db import transaction
    from django.utils import timezone

    from apps.schools.lifecycle_service import _leave_what_it_was_in
    from apps.schools.models import School

    with transaction.atomic():
        school = School.objects.select_for_update(of=("self",)).get(pk=school_pk)
        if not school.is_closed:
            return {"invitations": 0, "projects": 0, "issues": 0}
        since = school.closure_effective_date or (
            timezone.localtime(school.closed_at).date()
            if school.closed_at
            else timezone.localdate()
        )
        return _leave_what_it_was_in(school, None, since)
