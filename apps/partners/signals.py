"""Partner assignment ecosystem signals.

Partner assignment is a workflow handoff (staff → partner planning queue)
that previously emitted nothing: no audit entry and no notification, at any
of its seven creation sites. A post_save receiver covers every site — present
and future — without each view having to remember the bookkeeping.
"""

from __future__ import annotations

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.partners.models import PartnerAssignment

logger = logging.getLogger(__name__)


@receiver(
    post_save, sender=PartnerAssignment, dispatch_uid="partner_assignment_created"
)
def on_partner_assignment_created(sender, instance, created, **kwargs):
    if not created:
        return
    try:
        from apps.audit.services import log as audit_log

        audit_log(
            action="partner.assigned",
            subject_kind="PartnerAssignment",
            subject_id=instance.id,
            actor_id=instance.assigning_staff_id or "system",
            actor_role="",
            success=True,
            payload={
                "partner_id": instance.partner_id,
                "school_id": instance.school_id,
                "cluster_id": instance.cluster_id,
            },
        )
    except Exception:  # pragma: no cover — bookkeeping must never break the flow
        logger.warning("partner.assigned audit failed", exc_info=True)

    try:
        from apps.notifications.services import WorkflowNotificationService
        from apps.partners.models import Partner

        partner_user_id = (
            Partner.objects.filter(id=instance.partner_id)
            .values_list("user_id", flat=True)
            .first()
        )
        if partner_user_id:
            WorkflowNotificationService.trigger(
                event_type="partner_scheduled_activity",
                category="partner",
                priority="normal",
                title="New assignment from Edify staff",
                body="A school or activity slot was assigned to your organisation — it is now in your planning queue.",
                context_type="partner_assignment",
                context_id=instance.id,
                recipients=[partner_user_id],
            )
    except Exception:  # pragma: no cover
        logger.warning("partner.assigned notification failed", exc_info=True)
