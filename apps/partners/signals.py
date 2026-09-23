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
                # A project handover is answerable as one (owner, 2026-09-15).
                "project_id": instance.project_id,
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


@receiver(
    post_save,
    sender=PartnerAssignment,
    dispatch_uid="partner_assignment_multiple_partner_exception",
)
def on_partner_assignment_support_changed(sender, instance, created, **kwargs):
    """Keep the school's multiple-Partner exception in step with its live rows.

    Any write that can change how many Partners hold a school's support — a
    new handover, a return, a withdrawal, a resolution — lands here. Deferred
    to commit so the exception describes committed rows, and so a rolled-back
    handover never opens one.
    """
    update_fields = kwargs.get("update_fields")
    if not instance.school_id or not (
        created or update_fields is None or "status" in update_fields
    ):
        return
    from django.db import transaction

    from apps.partners.support_responsibility import (
        sync_multiple_partner_exception,
        visibility_enabled,
    )

    if not visibility_enabled():
        return

    def _sync(school_id=instance.school_id):
        try:
            sync_multiple_partner_exception(school_id)
        except Exception:  # pragma: no cover — bookkeeping never breaks the flow
            logger.warning("multiple-partner exception sync failed", exc_info=True)

    transaction.on_commit(_sync)
