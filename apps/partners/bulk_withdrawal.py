"""Withdraw many schools from a partner at once (owner, 2026-09-29).

"Allow the staff to bulk withdraw schools from project or partner assignment.
They can go to the project profile or partner monitoring and check all the
schools they want to withdraw and be able to withdraw."

A bulk withdrawal is the single withdrawal repeated, never a second rule:
each ticked assignment goes through ``withdrawal_service.withdraw`` (or
``request_withdrawal`` where the reader may only ask their Program Lead), in
its own transaction, with the one reason, explanation and disposition the
reader gave. One school the service refuses does not undo the others; the
reader is told, school by school, what happened.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from apps.core.exceptions import BadRequest, ConflictError, Forbidden, NotFoundError

#: A page's worth of ticks. More than this is a mistake, not a decision.
MAX_BULK_WITHDRAWALS = 100

WITHDRAWN = "withdrawn"
REQUESTED = "requested"
SKIPPED = "skipped"


@dataclass
class BulkOutcome:
    assignment_id: str
    school: str
    outcome: str
    message: str = ""


def clean_ids(raw_ids) -> list[str]:
    """The ticked ids, once each, in the order ticked."""
    ids = [str(i).strip() for i in (raw_ids or ()) if str(i).strip()]
    ids = list(dict.fromkeys(ids))
    if not ids:
        raise BadRequest("Tick the schools to withdraw first.")
    if len(ids) > MAX_BULK_WITHDRAWALS:
        raise BadRequest(f"Withdraw at most {MAX_BULK_WITHDRAWALS} schools at a time.")
    return ids


def withdraw_many(principal, plan, data: dict) -> list[BulkOutcome]:
    """Run each planned withdrawal.

    ``plan`` is a list of ``(assignment_id, school_name, mode)`` where mode is
    ``"withdraw"``, ``"request"`` or a refusal message already known to the
    caller (out of scope, a project's coordinator's decision, settled work).
    """
    from apps.partners import withdrawal_service

    outcomes: list[BulkOutcome] = []
    for assignment_id, school, mode in plan:
        if mode not in ("withdraw", "request"):
            outcomes.append(BulkOutcome(assignment_id, school, SKIPPED, mode))
            continue
        try:
            with transaction.atomic():
                if mode == "request":
                    withdrawal_service.request_withdrawal(
                        assignment_id, data, principal
                    )
                    outcomes.append(BulkOutcome(assignment_id, school, REQUESTED))
                else:
                    result = withdrawal_service.withdraw(assignment_id, data, principal)
                    outcomes.append(
                        BulkOutcome(
                            assignment_id,
                            school,
                            WITHDRAWN,
                            f"{result.get_kind_display()} — "
                            f"{result.get_state_display()}.",
                        )
                    )
        except (BadRequest, ConflictError, Forbidden, NotFoundError) as exc:
            outcomes.append(BulkOutcome(assignment_id, school, SKIPPED, str(exc)))
    return outcomes


def summary(outcomes: list[BulkOutcome]) -> str:
    """One sentence for the page: what moved, what was asked, what did not."""
    withdrawn = sum(1 for o in outcomes if o.outcome == WITHDRAWN)
    requested = sum(1 for o in outcomes if o.outcome == REQUESTED)
    skipped = sum(1 for o in outcomes if o.outcome == SKIPPED)
    parts = []
    if withdrawn:
        parts.append(f"Withdrew {withdrawn} school{'s' if withdrawn != 1 else ''}")
    if requested:
        parts.append(
            f"sent {requested} to your Program Lead for a decision"
            if parts
            else f"Sent {requested} to your Program Lead for a decision"
        )
    if skipped:
        parts.append(f"{skipped} not withdrawn")
    return (", ".join(parts) or "Nothing was withdrawn") + "."
