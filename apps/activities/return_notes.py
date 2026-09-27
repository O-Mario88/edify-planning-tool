"""Why a completion was sent back, said the same way everywhere.

Owner, 2026-09-24: "PL and IA verification workflow should have two buttons,
Verified and Return. Return is if the PL or IA does not confirm the activity in
Salesforce — for training and school visit. For example if I have uploaded the
training attendance form and training ID but when the approver checks and finds
the participants are not entered. The reason for returning should be clearly
stated. The staff can resubmit after fixing the issue."

Three return paths existed and each kept its reason somewhere different: the
Programme Lead's in ``Activity.pl_review_note``, Impact Assessment's partner
path in the same field, and Impact Assessment's staff workspace only in its own
``ReturnedReason`` / ``VerificationComment`` tables. The officer's My Plan read
none of them — it read ``last_reason``, which is the reschedule and cancel
note — so the person who had to fix the work was told "Correction required"
and nothing more.

One rule now: every return writes its reason to ``Activity.pl_review_note``
(the field predates the IA paths; its name is historical, its meaning is "the
reviewer's note on this completion"), and every surface reads it through
``note_for``. The reason is required on every path, in the service, so no
control can return work silently.
"""

from __future__ import annotations

#: ``Activity.pl_review_note`` is a 512-character column. A reason is cut to
#: fit with a marker rather than failing the return: the decision matters more
#: than the last words of a long instruction, and the reviewer's full comment
#: is also kept in the verification record.
NOTE_MAX = 512

#: The reasons an approver most often returns a school visit or a training
#: for, offered on both the Programme Lead's and Impact Assessment's Return.
#: "Participants not entered in Salesforce" is the owner's own example, and
#: so is a Salesforce ID with no participants behind it (2026-09-26).
COMMON_REASONS = (
    "Salesforce ID entered, but no participants in Salesforce",
    "Participants not entered in Salesforce",
    "Activity ID missing or wrong in Salesforce",
    "Attendance form missing or unreadable",
    "Participant numbers do not match the attendance form",
    "Evidence missing or unclear",
    "Wrong school, cluster or activity date",
)

#: Who sent the work back, by the status the return wrote.
RETURNED_BY = {
    "returned_by_pl": "Programme Lead",
    "returned_by_ia": "Impact Assessment",
    "returned": "Impact Assessment",
}


def fit(note: str) -> str:
    """The note, cut to the column with a visible marker if it is too long."""
    note = (note or "").strip()
    if len(note) <= NOTE_MAX:
        return note
    return note[: NOTE_MAX - 1].rstrip() + "…"


def compose(reasons, comment: str) -> str:
    """Categories and the written explanation, as one sentence for the officer."""
    picked = [str(r).strip() for r in (reasons or []) if str(r).strip()]
    comment = (comment or "").strip()
    head = "; ".join(picked)
    if head and comment:
        return fit(f"{head} — {comment}")
    return fit(head or comment)


def note_for(activity) -> str:
    """What the reviewer said when they returned this activity, or ""."""
    return (getattr(activity, "pl_review_note", "") or "").strip()


def returned_by(activity) -> str:
    """ "Programme Lead" or "Impact Assessment" for a returned activity."""
    return RETURNED_BY.get(getattr(activity, "status", "") or "", "")
