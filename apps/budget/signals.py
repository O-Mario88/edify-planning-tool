"""Financial-ledger projections into the immutable/current activity cost view."""

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.fund_requests.models import AdvanceRequest


@receiver(post_save, sender=AdvanceRequest, dispatch_uid="budget.sync_activity_cost_actuals")
def sync_activity_cost_actuals(sender, instance, **kwargs):
    from .costing_service import sync_snapshot_actuals

    sync_snapshot_actuals(instance.activity_id)


__all__ = []
