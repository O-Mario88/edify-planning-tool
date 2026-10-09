"""A Group Training delivered online costs nothing.

Owner, 2026-10-09: "add schedule for online training on the cluster training
schedule. so that users can schedule for their online trainings. online
training fetches no cost it is free."

The planner says so in the Group Training drawer (Delivery: In person /
Online). The record is still a Group Training for its cluster and schools:
the same training, participants, attendance and ceiling count. Only its
delivery differs, kept in ``Activity.programme_delivery_mode``, and with it
the price: nobody travels, no room is hired and no meal is served, so it
carries no cost line at all, the partner facilitation fee included.

``ONLINE_TRAINING`` is the one definition every "priced work" reader uses to
leave it out, beside the in-school Training whose visit carries its cost
(``apps.activities.pair_costing``): fund requests, the costing repair and the
missing-cost health checks. Without it a free training reads as work nobody
has priced.
"""

from __future__ import annotations

from django.db.models import Q

from apps.budget.costing import CLUSTER_TRAINING_TYPES

ONLINE = "online"

#: A Group Training delivered online.
ONLINE_TRAINING = Q(
    activity_type__in=CLUSTER_TRAINING_TYPES, programme_delivery_mode=ONLINE
)

#: What a page writes beside the UGX 0 of an online training.
ONLINE_FREE_NOTE = "(online training: no cost)"


def is_online_training(activity) -> bool:
    return (
        activity.activity_type in CLUSTER_TRAINING_TYPES
        and activity.programme_delivery_mode == ONLINE
    )


def asked_for_online(activity_type: str, data: dict) -> bool:
    """Did the planner schedule this Group Training as an online one?"""
    return (
        activity_type in CLUSTER_TRAINING_TYPES
        and str(data.get("programmeDeliveryMode") or "").strip() == ONLINE
    )
