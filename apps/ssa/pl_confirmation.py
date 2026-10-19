"""The Programme Lead confirms staff SSA (owner, 2026-10-16).

"I am a PL so mine should show already only those of CCEOs should awaits
approval ... when PL approves they will reflect. Any SSA entered and approved
by PL should reflect immediately not show 0,0."

Until now every SSA waited for an Impact Assessment officer other than its
collector (IA review, 2026-09-13), and nobody confirmed the scores keyed on
visits, so every confirmed-only reader (the profile's figures, analytics, the
Programme Lead's coverage, Core Schools) read nothing. The rule now follows
the one for the work itself (2026-10-15, ``apps.pl_review``):

- SSA a Programme Lead keys is confirmed as it is keyed, the lead its
  verifier.
- A CCEO's SSA keyed on a visit is confirmed when the lead approves the visit
  (``confirm_visit_ssa``, called by ``pl_review.services._approve``), or as
  it is keyed when the visit is already approved.
- A lead confirms a supervised CCEO's other SSA in the SSA queue
  (``apps.ssa.services._assert_may_decide``); Impact Assessment still may.
- Partner SSA stays with Impact Assessment, whoever approves the visit.

And the Core package (owner, same day: "Core package only track visits and
trainings. Once assessment is done and entered, it should be recorded and
reflect everywhere"): its assessment is the school's confirmed SSA for the
package's year (``sync_core_assessment``, ``core_assessment_cells``), never a
slot no drawer could schedule.
"""

from __future__ import annotations

from apps.core.enums import VerificationStatus
from apps.core.rbac import EdifyRole

#: How a record was confirmed under this rule (the audit row's ``basis``).
BASIS_PL_OWN = "pl_own"
BASIS_PL_APPROVAL = "pl_approval"

LEAD_ROLE = EdifyRole.COUNTRY_PROGRAM_LEAD.value


def _is_partner(activity) -> bool:
    return activity is not None and activity.delivery_type == "partner"


def _approved_by_lead(activity) -> str | None:
    """The lead who approved ``activity``, when a lead approved it."""
    from apps.activities.completion_columns import APPROVED_STATUSES
    from apps.pl_review.services import lead_verifies

    if activity is None or activity.status not in APPROVED_STATUSES:
        return None
    if not activity.pl_reviewed_by or not lead_verifies(activity):
        return None
    return activity.pl_reviewed_by


def confirmer(principal, *, partner: bool, activity) -> tuple[str, str] | None:
    """``(verifier user id, basis)`` when SSA ``principal`` keys is confirmed
    as it is keyed, else None (it waits)."""
    from apps.pl_review.services import lead_clears_own_work

    if partner or _is_partner(activity):
        return None
    if lead_clears_own_work(principal):
        return principal.user_id, BASIS_PL_OWN
    lead = _approved_by_lead(activity)
    if lead:
        return lead, BASIS_PL_APPROVAL
    return None


def confirm_visit_ssa(activity, reviewer_id: str) -> list:
    """Confirm the pending staff SSA keyed on ``activity``, which
    ``reviewer_id`` has just approved. Inside the approval's transaction."""
    from apps.ssa.models import SsaRecord
    from apps.ssa.services import confirm_record

    if _is_partner(activity):
        return []
    records = (
        SsaRecord.objects.filter(
            source_activity_id=activity.id,
            deleted_at__isnull=True,
            verification_status=VerificationStatus.PENDING.value,
        )
        .exclude(collector_type="partner")
        .select_related("school")
    )
    return [
        confirm_record(
            record, reviewer_id, basis=BASIS_PL_APPROVAL, actor_role=LEAD_ROLE
        )
        for record in records
    ]


def sync_core_assessment(school, fy: str) -> None:
    """The school's Core package for ``fy`` reads its assessment done exactly
    while a confirmed SSA of that year is on file."""
    from apps.core_schools.models import CorePlan
    from apps.ssa.models import SsaRecord

    done = int(
        SsaRecord.objects.filter(
            school_id=school.pk,
            fy=fy,
            deleted_at__isnull=True,
            verification_status=VerificationStatus.CONFIRMED.value,
        ).exists()
    )
    CorePlan.objects.filter(school_id=school.school_id, fy=fy).exclude(
        assessment_completed=done
    ).update(assessment_completed=done)


#: The Core row's Assessment cell for each state of the year's SSA, in the
#: shape the package's slot cells use.
_CELLS = {
    VerificationStatus.CONFIRMED.value: (
        "Complete",
        "bg-emerald-50 text-emerald-700 border-emerald-200",
        "✔",
    ),
    VerificationStatus.PENDING.value: (
        "Awaiting Approval",
        "bg-amber-50 text-amber-700 border-amber-200",
        "Pend",
    ),
    VerificationStatus.RETURNED.value: (
        "Returned",
        "bg-rose-100 text-rose-800 border-rose-300",
        "Ret",
    ),
}
_MISSING = ("Missing", "bg-rose-50 text-rose-700 border-rose-200", "Miss")
#: Of two records in one year (a returned one re-keyed), the one that says most.
_RANK = {
    VerificationStatus.CONFIRMED.value: 0,
    VerificationStatus.PENDING.value: 1,
    VerificationStatus.RETURNED.value: 2,
}


def core_assessment_cells(school_pks, fy: str) -> dict:
    """``{school pk: cell}``: each school's SSA for ``fy`` as the Core row's
    Assessment cell. One query for the page."""
    from apps.ssa.models import SsaRecord

    school_pks = list(school_pks)
    best: dict = {}
    for school_pk, status in SsaRecord.objects.filter(
        school_id__in=school_pks,
        fy=fy,
        deleted_at__isnull=True,
        verification_status__in=list(_RANK),
    ).values_list("school_id", "verification_status"):
        held = best.get(school_pk)
        if held is None or _RANK[status] < _RANK[held]:
            best[school_pk] = status
    cells = {}
    for school_pk in school_pks:
        status, pill_class, label = _CELLS.get(best.get(school_pk), _MISSING)
        cells[school_pk] = {"status": status, "pill_class": pill_class, "label": label}
    return cells


def confirm_left_pending(*, apply: bool = False) -> list[dict]:
    """Records the old rule left pending that this one confirms: a lead's
    own, and a CCEO's keyed on a visit the lead has approved. Returns one row
    per record; writes only with ``apply``. Run by the deploy (ssa 0011) and
    ``manage.py confirm_pl_ssa``."""
    from apps.accounts.models import User
    from apps.core.exceptions import BadRequest
    from apps.ssa.models import SsaRecord
    from apps.ssa.services import confirm_record

    pending = (
        SsaRecord.objects.filter(
            deleted_at__isnull=True,
            verification_status=VerificationStatus.PENDING.value,
        )
        .exclude(collector_type="partner")
        .select_related("school", "source_activity")
        .order_by("date_of_ssa", "id")
    )
    leads = set(
        User.objects.filter(roles__contains=[LEAD_ROLE]).values_list("id", flat=True)
    )
    rows = []
    for record in pending:
        activity = record.source_activity
        if _is_partner(activity):
            continue
        if record.collected_by_user_id in leads:
            verifier, basis = record.collected_by_user_id, BASIS_PL_OWN
        else:
            verifier, basis = _approved_by_lead(activity), BASIS_PL_APPROVAL
        if not verifier:
            continue
        row = {
            "id": record.id,
            "school": record.school.school_id,
            "fy": record.fy,
            "basis": basis,
            "verifier": verifier,
        }
        if apply:
            try:
                confirm_record(record, verifier, basis=basis, actor_role=LEAD_ROLE)
            except BadRequest as exc:
                row["skipped"] = str(getattr(exc, "detail", exc))
        rows.append(row)
    return rows
