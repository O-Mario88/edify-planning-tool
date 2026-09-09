"""Invalidate cached analytics only after a delivery/target transaction commits."""

from uuid import uuid4
from django.core.cache import cache
from django.db import transaction

KEY = "analytics:allocation-contract-revision:v1"


def revision():
    return cache.get(KEY, "0")


def changed(sender=None, **kwargs):
    connection = transaction.get_connection(kwargs.get("using") or "default")
    if any(
        getattr(callback, "_allocation_revision", False)
        for _, callback, _ in connection.run_on_commit
    ):
        return

    def invalidate():
        cache.set(KEY, uuid4().hex, timeout=None)

    invalidate._allocation_revision = True
    transaction.on_commit(invalidate, using=connection.alias)


def register():
    from django.db.models.signals import post_save, post_delete
    from apps.activities.models import Activity
    from apps.accounts.models import StaffProfile, StaffSupervisorAssignment
    from apps.hr.models import (
        PriorityMilestone,
        StrategicPriority,
        MilestoneAllocation,
        MilestonePeriodTarget,
        MilestoneActivityRule,
        MilestoneProgressCredit,
    )

    for model in (
        Activity,
        PriorityMilestone,
        StrategicPriority,
        StaffProfile,
        StaffSupervisorAssignment,
        MilestoneAllocation,
        MilestonePeriodTarget,
        MilestoneActivityRule,
        MilestoneProgressCredit,
    ):
        for signal in (post_save, post_delete):
            signal.connect(
                changed,
                sender=model,
                weak=False,
                dispatch_uid=f"accountability-revision-{model._meta.label}-{id(signal)}",
            )
