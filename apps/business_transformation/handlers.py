"""Durable outbox handlers for Business Transformation projections."""

from apps.outbox.services import register

from .services import ensure_case_from_verified_ssa, project_activity_state


@register(
    "bt.ssa.confirmed",
    idempotency_note=(
        "Case triggers are unique by verified SSA id and recommendations are "
        "unique by trigger and kind, so replay converges on the same records."
    ),
)
def handle_ssa_confirmed(payload: dict) -> None:
    ensure_case_from_verified_ssa(payload["ssaRecordId"])


@register(
    "bt.activity.state_changed",
    idempotency_note=(
        "The projector derives the current requirement/result state from the "
        "canonical Activity row and updates the same one-to-one records."
    ),
)
def handle_activity_state_changed(payload: dict) -> None:
    project_activity_state(payload["activityId"])
