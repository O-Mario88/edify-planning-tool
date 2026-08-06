"""Canonical geography administration transitions."""

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import BadRequest, NotFoundError

from .models import SecondaryDistrictGroup, SecondaryDistrictGroupStatus


def approve_secondary_district_group(group_id: str, principal):
    """Approve a same-day secondary-district route group once, under lock."""
    with transaction.atomic():
        group = (
            SecondaryDistrictGroup.objects.select_for_update()
            .prefetch_related("members")
            .filter(id=group_id)
            .first()
        )
        if not group:
            raise NotFoundError("Secondary district group not found.")
        if group.status == SecondaryDistrictGroupStatus.APPROVED:
            raise BadRequest("This secondary district group is already approved.")
        if not group.members.exists():
            raise BadRequest("Add at least one secondary district before approval.")
        group.status = SecondaryDistrictGroupStatus.APPROVED
        group.approved_by = principal.user_id
        group.approved_at = timezone.now()
        group.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])

        from apps.audit.services import log as audit_log

        audit_log(
            action="geography.secondary_group_approved",
            subject_kind="SecondaryDistrictGroup",
            subject_id=group.id,
            actor_id=principal.id,
            actor_role=getattr(principal, "active_role", None),
            payload={"name": group.name, "memberCount": group.members.count()},
        )
    return group
