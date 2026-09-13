"""Close the recommendation loop when a plan's work is verified or dropped.

A recommendation marked planned by `apps.ssa.plan_alignment.stamp` was never
closed: `mark_planned` and `mark_delivered` existed with no caller, so every
recorded need stayed "Generated" through its plan and its verified delivery,
and the priority-schools queue kept offering work already done (2026-09-13).
"""

from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.activities.models import Activity
from apps.ssa.plan_alignment import DELIVERED_STATUSES, RELEASED_STATUSES

_SETTLING = frozenset(DELIVERED_STATUSES) | frozenset(RELEASED_STATUSES)


@receiver(post_save, sender=Activity, dispatch_uid="ssa_recommendation_settlement")
def _settle_recommendations(sender, instance, **kwargs):
    # Most saves are neither verification nor cancellation; they cost nothing.
    if instance.status not in _SETTLING:
        return
    from apps.ssa.plan_alignment import settle_recommendations

    settle_recommendations(instance)
