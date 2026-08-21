"""Durable handler: a confirmed assessment produces recorded recommendations.

Generation used to be something a page did while rendering. That made it
invisible when it did not happen and unrepeatable when it failed. Riding the
existing `bt.ssa.confirmed` outbox event means a confirmation that lands during
an outage is retried rather than lost, and an SSA import of any size costs one
enqueue rather than a recommendation pass per row.
"""

from __future__ import annotations

import logging

from apps.outbox.services import register

logger = logging.getLogger("edify.ssa.recommendations")


@register(
    "ssa.recommendations.generate",
    idempotency_note=(
        "Recommendations are unique per need by condition_key with a partial "
        "unique constraint on the live states, so a replay refreshes the "
        "existing rows and creates nothing."
    ),
)
def handle_generate_recommendations(payload: dict) -> None:
    """Retire the superseded picture, then record the current one."""
    from apps.core.fy import get_operational_fy
    from apps.ssa.models import SsaRecord
    from apps.ssa.recommendation_service import generate_for_school, supersede_stale

    record = (
        SsaRecord.objects.select_related("school")
        .filter(id=payload["ssaRecordId"])
        .first()
    )
    if record is None or record.school is None:
        # The assessment or its school was removed after the event was raised.
        # Nothing to recommend against; converge quietly rather than retrying
        # to a dead letter over a record that no longer exists.
        return
    if record.verification_status != "confirmed":
        # Confirmation was withdrawn between enqueue and delivery. An
        # unconfirmed assessment must never drive a recommendation.
        return

    fy = record.fy or get_operational_fy()
    school = record.school

    # Order matters. Retiring first means a need answered by the OLD picture
    # closes before the new picture raises its own version of it, so the
    # successor links back through `supersedes` instead of colliding with a
    # live row it should have replaced.
    supersede_stale(school, fy=fy)
    result = generate_for_school(school, fy=fy)
    if result.get("skipped"):
        logger.info(
            "No recommendations for school %s: %s", school.id, result["skipped"]
        )
