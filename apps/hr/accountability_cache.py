"""Invalidate cached analytics only after a delivery/target transaction commits.

The cache here is an optimisation over the database and nothing more, so
neither half may fail a request when it cannot be reached. That mattered less
while every process kept its own cache, which cannot go away on its own. A
shared cache is one more machine that restarts: rehearsed against a real
server on 2026-10-06, stopping it took every Analytics page down through
`revision`, and would have answered every activity save with an error after
the save had committed, through the write in `changed`.
"""

import logging
from uuid import uuid4

from django.core.cache import cache
from django.db import transaction

KEY = "analytics:allocation-contract-revision:v1"

logger = logging.getLogger(__name__)


def revision():
    """The token every cached analytics answer is filed under.

    Unreadable, it is a token nobody has filed anything under: the answer is
    then built from the database rather than read from a snapshot that may
    belong to a revision already replaced.
    """
    try:
        return cache.get(KEY, "0")
    except Exception:  # noqa: BLE001 - cache loss must degrade to computation
        logger.warning(
            "Analytics revision unreadable; building from the database",
            exc_info=True,
        )
        return f"unread-{uuid4().hex}"


def changed(sender=None, **kwargs):
    connection = transaction.get_connection(kwargs.get("using") or "default")
    if any(
        getattr(callback, "_allocation_revision", False)
        for _, callback, _ in connection.run_on_commit
    ):
        return

    def invalidate():
        # After the commit: the work is saved whatever happens here. A missed
        # revision leaves cached analytics as they were until they lapse
        # (five minutes at most), which is what every other process already
        # saw while each kept a cache of its own.
        try:
            cache.set(KEY, uuid4().hex, timeout=None)
        except Exception:  # noqa: BLE001 - committed work stays committed
            logger.warning("Analytics revision not advanced", exc_info=True)

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
