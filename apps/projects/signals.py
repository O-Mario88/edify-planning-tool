"""Event bridges that keep Special Project impact measurable (PROJ-01).

Two things can make a project school measurable, and neither of them happens
in the projects app. A delivery is verified, which opens the measurement
window and fixes the date the follow-up is due from. An assessment is
confirmed, which may be the assessment that judges the work. Until this
module existed, neither reached `refresh_follow_up`, so no school ever left
"not yet measurable".

Registration only, like the Business Transformation bridge: the enqueue rides
the caller's transaction, so the source write and its projection commit or
roll back together.
"""

from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.activities.models import Activity
from apps.outbox.services import enqueue
from apps.ssa.models import SsaRecord

#: The states `_first_verified_delivery` counts as the project having reached
#: the school. Kept in step with it deliberately — a bridge that fired on a
#: state the reader ignores would enqueue work that changes nothing.
VERIFIED_DELIVERY_STATUSES = frozenset(
    {"ia_verified", "accountant_confirmed", "closed"}
)


def enqueue_impact_refresh(school_id: str, version: str) -> None:
    if not school_id:
        return
    enqueue(
        "projects.impact.refresh",
        {"schoolId": str(school_id)},
        idempotency_key=f"projects.impact:{school_id}:{version}",
    )


@receiver(post_save, sender=SsaRecord, dispatch_uid="projects_ssa_impact_bridge")
def _ssa_confirmation_bridge(sender, instance, **kwargs):
    """A confirmed assessment may be the one that judges a project's work."""
    if instance.verification_status != "confirmed":
        return
    version = (
        instance.verified_at.isoformat() if instance.verified_at else str(instance.id)
    )
    enqueue_impact_refresh(instance.school_id, f"ssa:{version}")


@receiver(post_save, sender=Activity, dispatch_uid="projects_activity_impact_bridge")
def _verified_delivery_bridge(sender, instance, **kwargs):
    """A verified delivery opens the window and sets the follow-up due date."""
    if not instance.project_id:
        return
    if instance.status not in VERIFIED_DELIVERY_STATUSES:
        return
    version = (
        instance.ia_confirmed_at.isoformat()
        if instance.ia_confirmed_at
        else str(instance.updated_at or instance.id)
    )
    enqueue_impact_refresh(instance.school_id, f"activity:{instance.id}:{version}")
