"""A partner's schools, split among its team members.

Owner, 2026-10-09: "Partner can assign schools assigend to them to the rest of
their team members so that the the system can track who supported which
schools."

The schools are the ones the organisation holds: handed to it and not taken
back (``PartnerAssignment.RELEASED_STATUSES``). The team is its active roster
(``PartnerMember``). ``PartnerSchoolMember`` says which member looks after
which school. Work at the school that is not finished and names nobody yet
takes the member's name, and the scheduling drawer offers the member first,
so the record of who went (``Activity.delivery_contact_name``) follows the
split without anyone retyping it.

The organisation makes the split itself; the Admin may make it for it.
"""

from __future__ import annotations

from django.db import transaction

from apps.core.activity_types import (
    COMPLETED_WORK_STATUSES,
    NOT_IN_PLAN_ACTIVITY_STATUSES,
)
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError

from .models import Partner, PartnerAssignment, PartnerMember, PartnerSchoolMember


def may_split_schools(principal, partner) -> bool:
    """The organisation's own login, or the Admin."""
    from apps.core.navigation import get_user_role_slug
    from apps.core.scoping import resolve_user_scope

    if getattr(principal, "is_superuser", False):
        return True
    if get_user_role_slug(principal) == "ADMIN":
        return True
    return partner.id in (resolve_user_scope(principal).partner_ids or [])


def held_schools(partner) -> list:
    """Every school the organisation holds, by name, once each."""
    from apps.schools.models import School

    ids = (
        PartnerAssignment.objects.filter(partner=partner, school__isnull=False)
        .exclude(status__in=PartnerAssignment.RELEASED_STATUSES)
        .values_list("school_id", flat=True)
        .distinct()
    )
    return list(
        School.objects.filter(id__in=list(ids))
        .select_related("district")
        .order_by("name")
    )


def members_by_school(partner) -> dict[str, PartnerMember]:
    """{school id: the team member who looks after it}."""
    return {
        row.school_id: row.member
        for row in PartnerSchoolMember.objects.filter(
            partner=partner, member__active=True
        ).select_related("member")
    }


def school_counts(partner) -> dict[str, int]:
    """{member id: how many of the organisation's held schools they have}."""
    held = {school.id for school in held_schools(partner)}
    counts: dict[str, int] = {}
    for school_id, member in members_by_school(partner).items():
        if school_id in held:
            counts[member.id] = counts.get(member.id, 0) + 1
    return counts


def member_for(partner, school_id) -> str:
    """The name of the member who looks after this school, or ''."""
    if not school_id:
        return ""
    row = (
        PartnerSchoolMember.objects.filter(
            partner=partner, school_id=school_id, member__active=True
        )
        .select_related("member")
        .first()
    )
    return row.member.name if row else ""


def _name_open_work(partner, school_ids, name: str) -> int:
    """Put the member's name on this organisation's unfinished work at these
    schools that names nobody yet. A name already chosen is left alone."""
    from apps.activities.models import Activity

    if not school_ids:
        return 0
    return (
        Activity.objects.filter(
            deleted_at__isnull=True,
            assigned_partner_id=partner.id,
            school_id__in=list(school_ids),
            delivery_contact_name="",
        )
        .exclude(status__in=COMPLETED_WORK_STATUSES)
        .exclude(status__in=NOT_IN_PLAN_ACTIVITY_STATUSES)
        .update(delivery_contact_name=name)
    )


@transaction.atomic
def set_member_schools(partner_id: str, member_id: str, school_ids, principal) -> dict:
    """Make ``school_ids`` the schools this team member looks after.

    A school ticked that another member had moves to this one; a school this
    member had and is no longer ticked goes back to nobody. Only schools the
    organisation holds can be given.
    """
    from apps.audit.services import log as audit_log

    partner = Partner.objects.filter(id=partner_id, deleted_at__isnull=True).first()
    if partner is None:
        raise NotFoundError("Partner organisation not found.")
    if not may_split_schools(principal, partner):
        raise Forbidden(
            "Only the organisation itself or an Admin assigns its schools to "
            "its team members."
        )
    member = PartnerMember.objects.filter(
        id=member_id, partner=partner, active=True
    ).first()
    if member is None:
        raise NotFoundError("This person is not on the organisation's team.")

    wanted = {str(i).strip() for i in (school_ids or []) if str(i).strip()}
    held = {school.id for school in held_schools(partner)}
    strangers = wanted - held
    if strangers:
        raise BadRequest(
            f"{len(strangers)} of the schools chosen "
            f"{'is' if len(strangers) == 1 else 'are'} not assigned to "
            f"{partner.name}. Reload the list and choose again."
        )

    actor = getattr(principal, "user_id", None) or str(getattr(principal, "id", ""))
    current = {
        row.school_id: row
        for row in PartnerSchoolMember.objects.select_for_update().filter(
            partner=partner
        )
    }
    before = sorted(sid for sid, row in current.items() if row.member_id == member.id)
    given, moved, cleared = [], [], []
    for school_id in sorted(wanted):
        row = current.get(school_id)
        if row is None:
            PartnerSchoolMember.objects.create(
                partner=partner,
                school_id=school_id,
                member=member,
                assigned_by_user_id=actor,
            )
            given.append(school_id)
        elif row.member_id != member.id:
            row.member = member
            row.assigned_by_user_id = actor
            row.save(update_fields=["member", "assigned_by_user_id", "updated_at"])
            moved.append(school_id)
    for school_id in before:
        if school_id not in wanted:
            current[school_id].delete()
            cleared.append(school_id)

    named = _name_open_work(partner, given + moved, member.name)
    if given or moved or cleared:
        audit_log(
            action="partner.school_team_member_set",
            subject_kind="partner",
            subject_id=partner.id,
            actor_id=getattr(principal, "id", None)
            or getattr(principal, "user_id", None),
            actor_role=getattr(principal, "active_role", None),
            payload={
                "memberId": member.id,
                "memberName": member.name,
                "given": given,
                "movedFromAnother": moved,
                "cleared": cleared,
                "activitiesNamed": named,
            },
        )
    return {
        "member": member.name,
        "schools": len(wanted),
        "given": len(given),
        "moved": len(moved),
        "cleared": len(cleared),
    }
