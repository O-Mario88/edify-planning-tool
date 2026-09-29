"""ExecutionStageClassifier — the canonical activity states, read as oversight stages.

No second state machine: every stage below is a set of the platform's own
ActivityStatus values (apps.core.enums), and the transitions are the ones the
activity, PL-review, IA and closure services already make.

The spine, as the platform runs it (2026-09-28):

* **Staff work by a CCEO** — scheduled → started (``start_completion``) →
  evidence → submitted to the Programme Lead (``submitted_to_pl``) → the Lead
  approves, which verifies it (``pl_review.confirm`` sets ``ia_verified``), or
  returns it (``returned_by_pl``) → closure.
* **A Lead's own work, and other staff** — submitted straight to IA
  (``awaiting_ia_verification``) → IA verifies or returns → closure.
* **Partner work** — assigned → Partner-scheduled → started → evidence →
  straight to IA (no PL stage: the Partner branch goes direct) → IA verifies
  (payment follows) or returns it to the Partner (``returned_by_ia``).
* **Closure** — ``closed`` only through the governed closure (evidence,
  Salesforce ID, verification, and — where money moved — accounts cleared and
  a NetSuite ID), apps.activities.closure_services.

Four completion levels are kept apart (spec §1): execution completed (the
implementer submitted), manager review (the Lead approved, staff CCEO work
only), programme completion (verified), fully closed.

**Overdue** (spec §9.7) is read against the approved scheduled date — no
hour-level SLA is invented — and always carries its stage, so work waiting on a
reviewer reads "PL review overdue — waiting on the PL", never "staff behind":

    execution  not started            → the implementer, the Partner, the
                                        Accountant (funds not disbursed) or the
                                        school (not operating)
    evidence   started, not submitted → the implementer or the Partner
    correction returned, not resubmitted → the implementer or the Partner
    pl_review  waiting on the Lead    → the Programme Lead
    ia_review  waiting on IA          → Impact Assessment

Verified work that is not yet closed is not "overdue" (closure has no approved
deadline); it is open finance/closure work, owned by whoever the governed
closure checklist names.
"""

from __future__ import annotations

from datetime import date
from typing import NamedTuple

#: The definitions below, by date. Recorded on every locked period snapshot
#: (apps.planning.execution_snapshot_models) so a closed period's figures are
#: always read with the rules that produced them.
STAGE_POLICY = "2026-09-29.1"

#: Not a plan at all: nobody committed to this work.
NOT_A_PLAN = frozenset({"not_planned", "awaiting_owner_approval", "rejected"})
#: Taken off the plan.
OFF_PLAN = frozenset({"cancelled", "deferred"})
#: Planned, not yet started.
WAITING_START = frozenset(
    {"planned", "scheduled", "rescheduled", "assigned_to_partner", "partner_scheduled"}
)
#: Started in the field, not yet submitted. ``completed`` is the legacy staged
#: state that still has to be submitted (apps.activities.services).
IN_FIELD = frozenset(
    {
        "in_progress",
        "completion_started",
        "evidence_uploaded",
        "evidence_accepted",
        "salesforce_id_required",
        "completed",
    }
)
#: Sent back for correction.
RETURNED = frozenset({"returned", "returned_by_pl", "returned_by_ia"})
AT_PL = frozenset({"submitted_to_pl"})
AT_IA = frozenset({"awaiting_ia_verification"})
#: Programme completion: verified — by the Lead for a CCEO's staff work, by IA
#: for Partner and a Lead's own work (the platform's workflow).
VERIFIED = frozenset({"ia_verified", "accountant_confirmed", "closed"})
CLOSED = frozenset({"closed"})
#: Every state a live plan can be in.
LIVE = WAITING_START | IN_FIELD | RETURNED | AT_PL | AT_IA | VERIFIED
#: What the page reads: live plans and cancelled ones (to count them).
READ_STATES = LIVE | OFF_PLAN

#: The stages, in the order a record moves through them.
STAGES = (
    ("scheduled", "Scheduled — not started"),
    ("in_field", "Started — evidence not submitted"),
    ("returned", "Returned for correction"),
    ("pl_review", "Waiting on PL review"),
    ("ia_review", "Waiting on IA verification"),
    ("verified", "Verified — closure open"),
    ("closed", "Fully closed"),
    ("cancelled", "Cancelled"),
)
STAGE_LABELS = dict(STAGES)

#: Stage-specific overdue labels (spec §9.7).
OVERDUE_LABELS = {
    "execution": "Execution overdue",
    "evidence": "Evidence overdue",
    "correction": "Correction overdue",
    "pl_review": "PL review overdue",
    "ia_review": "IA review overdue",
}

#: Who holds the next action (spec §10).
OWNERS = (
    ("staff", "Staff"),
    ("pl", "PL Review"),
    ("ia", "IA"),
    ("partner", "Partner"),
    ("finance", "Finance"),
    ("external", "External / School"),
)
OWNER_LABELS = dict(OWNERS)

#: Schools where due work cannot happen (the school's lifecycle, not the plan).
NOT_OPERATING = frozenset({"temporarily_closed", "permanently_closed"})

#: Overdue age groups (spec §11.4).
AGE_GROUPS = (
    ("age_1_2", "1–2 days", 1, 2),
    ("age_3_7", "3–7 days", 3, 7),
    ("age_8_14", "8–14 days", 8, 14),
    ("age_15", "> 14 days", 15, 10**9),
)


class Stage(NamedTuple):
    """One activity's position in the spine, for the page."""

    stage: str
    started: bool
    executed: bool
    pl_applicable: bool
    pl_reviewed: bool
    verified: bool
    closed: bool
    returned: bool
    cancelled: bool
    overdue: str  # an OVERDUE_LABELS key, or ""
    owner: str  # an OWNERS key for open past-due work, or ""
    finance_open: bool  # verified, past due, not closed
    timing: str  # on_time | late | unknown | not_started | upcoming | cancelled
    age: int  # days past the scheduled date (0 when not past it)


def age_group(age: int) -> str:
    for key, _label, low, high in AGE_GROUPS:
        if low <= age <= high:
            return key
    return ""


def classify(
    *,
    status: str,
    partner: bool,
    due: date | None,
    start: date | None,
    pl_reviewed_at,
    reviewer_path: str,
    school_operating: bool,
    funds_pending: bool,
    closure_owner: str,
    today: date,
) -> Stage:
    """Classify one activity.

    ``reviewer_path`` is "pl" when a CCEO's staff work goes to their Lead,
    "ia" otherwise. ``start`` is the day execution started (or was delivered).
    ``closure_owner`` names who holds a verified record's closure (from the
    governed closure checklist and the Partner payment): "finance", "staff",
    "ia" or "".
    """
    past_due = due is not None and due < today
    age = (today - due).days if past_due else 0
    field_owner = "partner" if partner else "staff"

    if status in OFF_PLAN:
        return Stage(
            "cancelled",
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            True,
            "",
            "",
            False,
            "cancelled",
            0,
        )

    pl_applicable = (not partner) and reviewer_path == "pl"
    if status in WAITING_START:
        overdue = owner = ""
        if past_due:
            overdue = "execution"
            if not school_operating:
                owner = "external"
            elif funds_pending and not partner:
                owner = "finance"
            else:
                owner = field_owner
        timing = "not_started" if past_due else "upcoming"
        return Stage(
            "scheduled",
            False,
            False,
            pl_applicable,
            False,
            False,
            False,
            False,
            False,
            overdue,
            owner,
            False,
            timing,
            age,
        )

    timing = (
        "unknown"
        if start is None or due is None
        else ("on_time" if start <= due else "late")
    )
    if status in IN_FIELD:
        return Stage(
            "in_field",
            True,
            False,
            pl_applicable,
            False,
            False,
            False,
            False,
            False,
            "evidence" if past_due else "",
            field_owner if past_due else "",
            False,
            timing,
            age,
        )
    if status in RETURNED:
        return Stage(
            "returned",
            True,
            False,
            pl_applicable,
            False,
            False,
            False,
            True,
            False,
            "correction" if past_due else "",
            field_owner if past_due else "",
            False,
            timing,
            age,
        )
    if status in AT_PL:
        return Stage(
            "pl_review",
            True,
            True,
            True,
            False,
            False,
            False,
            False,
            False,
            "pl_review" if past_due else "",
            "pl" if past_due else "",
            False,
            timing,
            age,
        )
    # Past the Lead, the PL stage applied only if the Lead reviewed the work: a
    # CCEO's work that went straight to IA never had one to complete.
    reviewed = pl_applicable and pl_reviewed_at is not None
    if status in AT_IA:
        return Stage(
            "ia_review",
            True,
            True,
            reviewed,
            reviewed,
            False,
            False,
            False,
            False,
            "ia_review" if past_due else "",
            "ia" if past_due else "",
            False,
            timing,
            age,
        )
    pl_applicable = reviewed
    if status in CLOSED:
        return Stage(
            "closed",
            True,
            True,
            pl_applicable,
            reviewed,
            True,
            True,
            False,
            False,
            "",
            "",
            False,
            timing,
            age,
        )
    # Verified, closure open.
    owner = (closure_owner or "staff") if past_due else ""
    return Stage(
        "verified",
        True,
        True,
        pl_applicable,
        reviewed,
        True,
        False,
        False,
        False,
        "",
        owner,
        past_due,
        timing,
        age,
    )


class ExecutionStageClassifier:
    """The classifier, as one importable surface."""

    classify = staticmethod(classify)
    stages = STAGES
    overdue_labels = OVERDUE_LABELS
    owners = OWNERS
