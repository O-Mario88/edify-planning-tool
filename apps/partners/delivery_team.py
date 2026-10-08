"""Who, on a partner's team, delivers each piece of its work.

Owner, 2026-10-08: the partner's "calendar should show activities of the day
and who is executing them from among the onboarded partner team member".

An activity has always carried the name of the person expected at the school
(``Activity.delivery_contact_name``), typed freely when the partner dated the
work and never changed afterwards. The organisation's team has its own record
since 2026-09-07, the roster (``PartnerMember``). The two were not joined: a
name could be typed that is on no roster, a training an officer runs with the
organisation as facilitator had nobody named at all, and when the person
changed there was no way to say so.

Here the name is chosen from the team — the active roster, and the person
signed in, who is often the one who goes — and can be changed for as long as
the work is not finished.
"""

from __future__ import annotations

from django.db import transaction

from apps.core.activity_types import (
    COMPLETED_WORK_STATUSES,
    NOT_IN_PLAN_ACTIVITY_STATUSES,
)
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError


def team_names(partner, login=None) -> list[str]:
    """The people who may be named on this organisation's work: its active
    roster in roster order, then the person signed in when they are not on
    it."""
    names = [m.name.strip() for m in partner.members.filter(active=True) if m.name]
    own = (getattr(login, "name", "") or "").strip()
    if own and own.casefold() not in {n.casefold() for n in names}:
        names.append(own)
    return names


def on_team(partner, name: str, login=None) -> str:
    """``name`` as the team spells it, or a refusal that says where the team
    is kept."""
    wanted = (name or "").strip()
    if len(wanted) < 2:
        raise BadRequest("Choose the team member who will deliver this work.")
    for member in team_names(partner, login):
        if member.casefold() == wanted.casefold():
            return member
    raise BadRequest(
        f"{wanted} is not on your organisation's team. Add them under Staff "
        "and volunteers on your organisation's profile, then choose them here."
    )


def partner_of(activity, partner_ids) -> str | None:
    """The one of these organisations that delivers or facilitates the
    activity, or None when it is none of theirs."""
    ids = {i for i in partner_ids if i}
    if activity.assigned_partner_id in ids:
        return activity.assigned_partner_id
    if activity.facilitating_partner_id in ids:
        return activity.facilitating_partner_id
    return None


def may_rename(activity) -> bool:
    """Finished work keeps the name it was delivered under, and called-off
    work has nobody to name."""
    return (
        activity.status not in COMPLETED_WORK_STATUSES
        and activity.status not in NOT_IN_PLAN_ACTIVITY_STATUSES
    )


@transaction.atomic
def name_member(activity_id: str, name: str, principal) -> dict:
    """Name the team member who delivers an activity of the signed-in
    partner's: a visit or training handed to it, or an officer's training it
    facilitates."""
    from apps.activities.models import Activity
    from apps.audit.services import log as audit_log
    from apps.core.scoping import resolve_partner_ids
    from apps.partners.models import Partner

    partner_ids = resolve_partner_ids(principal)
    if not partner_ids:
        raise Forbidden("Only a partner account names its own team's work.")
    activity = (
        Activity.objects.select_for_update()
        .filter(id=activity_id, deleted_at__isnull=True)
        .first()
    )
    if activity is None:
        raise NotFoundError("Activity not found.")
    partner_id = partner_of(activity, partner_ids)
    if partner_id is None:
        raise Forbidden("This activity belongs to another organisation.")
    if not may_rename(activity):
        raise BadRequest(
            "This work is finished or was called off; who delivered it is "
            "part of its record now."
        )
    partner = Partner.objects.get(id=partner_id)
    chosen = on_team(partner, name, principal)
    previous = activity.delivery_contact_name or ""
    if chosen != previous:
        activity.delivery_contact_name = chosen
        activity.save(update_fields=["delivery_contact_name", "updated_at"])
        audit_log(
            action="partner.delivery_member_named",
            subject_kind="activity",
            subject_id=activity.id,
            actor_id=getattr(principal, "id", None)
            or getattr(principal, "user_id", None),
            actor_role=getattr(principal, "active_role", None),
            payload={"partnerId": partner_id, "previous": previous, "new": chosen},
        )
    return {"id": activity.id, "deliveredBy": chosen, "previous": previous}
