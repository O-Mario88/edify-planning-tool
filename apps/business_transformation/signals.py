"""Small event bridge from canonical SSA and Activity state changes."""

from __future__ import annotations

from django.db.models.signals import post_save
from django.db import transaction
from django.dispatch import receiver

from apps.activities.models import Activity
from apps.outbox.services import enqueue
from apps.ssa.models import SsaRecord


def _ssa_confirmed_event(record_id: str, verified_at=None) -> tuple[dict, str]:
    version = verified_at.isoformat() if verified_at else "confirmed"
    return (
        {"ssaRecordId": str(record_id)},
        f"bt.ssa.confirmed:{record_id}:{version}",
    )


def enqueue_ssa_confirmed(record_id: str, verified_at=None) -> None:
    payload, key = _ssa_confirmed_event(record_id, verified_at)
    enqueue("bt.ssa.confirmed", payload, idempotency_key=key)
    # A confirmed assessment is also what SSA recommendations are derived
    # from. Two independent projections off one confirmation, each with its
    # own idempotency key so a retry of one never re-runs the other.
    enqueue(
        "ssa.recommendations.generate",
        payload,
        idempotency_key=key.replace("bt.ssa.confirmed:", "ssa.recommendations:"),
    )


def enqueue_ssa_confirmed_batch(records) -> None:
    """One INSERT for a whole import's worth of confirmations.

    The per-record loop made SSA upload queries grow with the file; the
    upload's query bound (test_upload_query_count_does_not_grow_per_ssa_row)
    holds this path to O(1).
    """
    from apps.outbox.services import enqueue_many

    events = [_ssa_confirmed_event(record.id, record.verified_at) for record in records]
    enqueue_many("bt.ssa.confirmed", events)
    enqueue_many(
        "ssa.recommendations.generate",
        [
            (payload, key.replace("bt.ssa.confirmed:", "ssa.recommendations:"))
            for payload, key in events
        ],
    )


@receiver(post_save, sender=SsaRecord, dispatch_uid="bt_ssa_confirmation_bridge")
def _ssa_confirmation_bridge(sender, instance, **kwargs):
    if instance.verification_status != "confirmed":
        return
    # Enqueue inside the ambient business transaction: the SSA and its follow-
    # up event commit together or roll back together.
    enqueue_ssa_confirmed(instance.id, instance.verified_at)


@receiver(post_save, sender=Activity, dispatch_uid="bt_activity_state_bridge")
def _activity_state_bridge(sender, instance, **kwargs):
    _link_planned_loan_verification_activity(instance)
    if instance.status not in {
        "ia_verified",
        "accountant_confirmed",
        "closed",
        "returned",
        "returned_by_ia",
        "returned_by_pl",
    }:
        return
    version = (
        instance.ia_confirmed_at.isoformat()
        if instance.ia_confirmed_at
        else instance.updated_at.isoformat()
    )
    enqueue(
        "bt.activity.state_changed",
        {"activityId": str(instance.id)},
        idempotency_key=f"bt.activity.state:{instance.id}:{instance.status}:{version}",
    )


def _link_planned_loan_verification_activity(activity: Activity) -> None:
    """Attach a governed BT verification visit to the oldest due loan need."""

    if not activity.school_id or not activity.catalogue_item_id:
        return
    from apps.activity_catalogue.models import ActivityCatalogueItem

    if not ActivityCatalogueItem.objects.filter(
        id=activity.catalogue_item_id,
        stable_code="BT_UG_LOAN_USE_VERIFICATION",
    ).exists():
        return
    from .models import (
        BusinessTransformationActivityLink,
        LoanVerificationRequirement,
        RecommendationKind,
        VerificationRequirementStatus,
    )

    with transaction.atomic():
        requirement = (
            LoanVerificationRequirement.objects.select_for_update()
            .select_related("loan__case")
            .filter(
                loan__school_id=activity.school_id,
                activity__isnull=True,
                status__in=[
                    VerificationRequirementStatus.NEEDS_SCHEDULING,
                    VerificationRequirementStatus.OVERDUE,
                ],
            )
            .order_by("due_date", "created_at")
            .first()
        )
        if requirement is None:
            return
        BusinessTransformationActivityLink.objects.get_or_create(
            activity=activity,
            defaults={
                "case": requirement.loan.case,
                "loan": requirement.loan,
                "purpose": RecommendationKind.LOAN_USE_VERIFICATION,
            },
        )
        requirement.activity = activity
        requirement.status = VerificationRequirementStatus.SCHEDULED
        requirement.save(update_fields=["activity", "status", "updated_at"])
