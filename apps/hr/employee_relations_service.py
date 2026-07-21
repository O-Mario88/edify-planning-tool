"""Employee relations — the register that now knows whom a case is about.

The model had no subject-employee field at all, so a conduct case could not
record whom it concerned. That was not only a gap in the record: it made the
register impossible to scope, which is why it was the one HR surface with no
scope of any kind — every grievance, harassment, whistleblowing and
safeguarding case in every country, with `is_confidential` rendered as a label
that filtered nothing.

Three rules hold here:

  * **Access is by country, ownership or investigation** — never by role
    alone. A confidential case is visible only to the people working it.
  * **Reading is an event.** Opening the register writes an audit row. In this
    one domain, after-the-fact attribution of who looked is the point.
  * **An escalation creates a case.** It is never a status flip on someone's
    performance record — those carry different evidentiary standards.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import BadRequest, Forbidden
from apps.hr.models import EmployeeRelationsCase, ERCaseStatus

_HR_ROLES = {"HumanResources", "Admin"}


def _role(principal) -> str:
    return getattr(principal, "active_role", "") or ""


def _country(principal) -> str | None:
    return getattr(getattr(principal, "staff_profile", None), "country", None)


def _assert_hr(principal) -> None:
    if _role(principal) not in _HR_ROLES:
        raise Forbidden("Only HR may manage employee-relations cases.")


def visible_cases(principal):
    """Cases this person may see.

    Admin org-wide. Everyone else: their own country, and a confidential case
    only if they own it or are investigating it. Nobody else needs to know a
    confidential case exists — including that it exists at all, which is why
    this filters rows rather than redacting fields.
    """
    qs = EmployeeRelationsCase.objects.select_related(
        "case_owner", "subject_staff__user", "investigator"
    )
    if _role(principal) == "Admin":
        return qs
    country = _country(principal)
    if not country or _role(principal) not in _HR_ROLES:
        return qs.none()
    from django.db.models import Q

    uid = getattr(principal, "user_id", None)
    return qs.filter(country=country).filter(
        Q(is_confidential=False) | Q(case_owner_id=uid) | Q(investigator_id=uid)
    )


def record_access(principal, *, what: str, case_id: str | None = None) -> None:
    """Reading a restricted people register is itself worth attributing."""
    from apps.audit.services import log as audit_log

    audit_log(
        action="hr.er_accessed",
        subject_kind="employee_relations_case",
        subject_id=case_id,
        actor_id=getattr(principal, "user_id", None),
        actor_role=_role(principal),
        payload={"view": what},
    )


def get_case(case_id: str, principal) -> EmployeeRelationsCase:
    case = visible_cases(principal).filter(id=case_id).first()
    if not case:
        raise Forbidden("You do not have access to this case.")
    record_access(principal, what="case_detail", case_id=case.id)
    return case


def _audit(action: str, case, principal, payload=None) -> None:
    from apps.audit.services import log as audit_log

    audit_log(
        action=action,
        subject_kind="employee_relations_case",
        subject_id=case.id,
        actor_id=getattr(principal, "user_id", None),
        actor_role=_role(principal),
        # Never the narrative. The case type and status are enough to
        # reconstruct who did what; the description and findings are not.
        payload={
            "caseType": case.case_type,
            "status": case.status,
            "severity": case.severity,
            **(payload or {}),
        },
    )


@transaction.atomic
def open_case(data: dict, principal) -> EmployeeRelationsCase:
    _assert_hr(principal)
    description = (data.get("description") or "").strip()
    if not description:
        raise BadRequest("A description is required to open a case.")
    case_type = data.get("case_type")
    if not case_type:
        raise BadRequest("A case type is required.")

    subject = None
    subject_id = (data.get("subject_staff_id") or "").strip()
    if subject_id:
        from apps.accounts.models import StaffProfile

        subject = StaffProfile.objects.filter(id=subject_id).first()
        if not subject:
            raise BadRequest("That employee was not found.")

    country = (
        (data.get("country") or "").strip()
        or getattr(subject, "country", None)
        or _country(principal)
    )
    if not country:
        raise BadRequest("A country is required to scope this case.")
    if _role(principal) != "Admin" and country != _country(principal):
        raise Forbidden("You may only open cases in your own country.")

    case = EmployeeRelationsCase.objects.create(
        subject_staff=subject,
        country=country,
        case_type=case_type,
        severity=data.get("severity") or "medium",
        status=ERCaseStatus.SUBMITTED,
        case_owner_id=getattr(principal, "user_id", None),
        raised_by_id=getattr(principal, "user_id", None),
        description=description,
        is_confidential=data.get("is_confidential", True),
        opened_at=timezone.now(),
        retention_until=data.get("retention_until") or None,
    )
    _audit("hr.er_case_opened", case, principal, {"hasSubject": bool(subject)})
    return case


#: The case workflow. A transition not listed here is refused.
_CASE_FLOW = {
    ERCaseStatus.SUBMITTED: {ERCaseStatus.TRIAGE, ERCaseStatus.CLOSED},
    ERCaseStatus.TRIAGE: {ERCaseStatus.INVESTIGATION, ERCaseStatus.CLOSED},
    ERCaseStatus.INVESTIGATION: {ERCaseStatus.FINDINGS},
    ERCaseStatus.FINDINGS: {ERCaseStatus.ACTION},
    ERCaseStatus.ACTION: {ERCaseStatus.APPEAL, ERCaseStatus.RESOLVED},
    ERCaseStatus.APPEAL: {ERCaseStatus.RESOLVED},
    ERCaseStatus.RESOLVED: {ERCaseStatus.CLOSED},
}


@transaction.atomic
def advance_case(
    case_id: str, principal, *, to_status: str, note: str = "", investigator_id=None
) -> EmployeeRelationsCase:
    _assert_hr(principal)
    case = get_case(case_id, principal)
    if case.subject_staff and case.subject_staff.user_id == getattr(
        principal, "user_id", None
    ):
        raise Forbidden("You cannot act on a case concerning yourself.")

    allowed = _CASE_FLOW.get(case.status, set())
    if to_status not in allowed:
        raise BadRequest(
            f"A case at '{case.get_status_display()}' cannot move to that state."
        )

    if to_status == ERCaseStatus.INVESTIGATION:
        if not investigator_id:
            raise BadRequest("An investigator must be named.")
        case.investigator_id = investigator_id
    if to_status == ERCaseStatus.FINDINGS:
        if not (note or "").strip():
            raise BadRequest("Findings are required.")
        case.findings = note
    if to_status == ERCaseStatus.ACTION:
        if not (note or "").strip():
            raise BadRequest("The action taken must be recorded.")
        case.action_taken = note
    if to_status == ERCaseStatus.APPEAL:
        case.appeal_note = note
    if to_status == ERCaseStatus.CLOSED:
        case.closed_at = timezone.now()

    case.status = to_status
    case.save()
    _audit(f"hr.er_case_{to_status}", case, principal)
    return case


@transaction.atomic
def escalate_recovery_plan(plan_id: str, principal, *, reason: str):
    """Turn a performance concern into a conduct case — by CREATING one.

    "Escalate to conduct" used to be a status flip on the performance record
    itself, which meant a capacity or workload problem could become a
    disciplinary matter without anyone opening a case, naming an authoriser,
    or applying a different standard of evidence.
    """
    _assert_hr(principal)
    if not (reason or "").strip():
        raise BadRequest("A reason is required to escalate to a conduct case.")

    from apps.hr.models import (
        PerformanceImprovementPlan,
        RecoveryPlanType,
        RecoveryStatus,
    )

    plan = (
        PerformanceImprovementPlan.objects.select_for_update()
        .select_related("staff")
        .filter(id=plan_id)
        .first()
    )
    if not plan:
        raise BadRequest("Recovery plan not found.")
    if plan.plan_type != RecoveryPlanType.FORMAL:
        raise BadRequest(
            "Only a formal improvement plan may escalate to a conduct case."
        )
    if plan.escalated_case_id:
        raise BadRequest("This plan has already been escalated.")

    case = open_case(
        {
            "subject_staff_id": plan.staff_id,
            "country": plan.staff.country,
            "case_type": "conduct",
            "severity": "high",
            "description": (
                f"Escalated from a formal performance improvement plan. {reason}"
            ),
            "is_confidential": True,
        },
        principal,
    )
    plan.escalated_case = case
    plan.status = RecoveryStatus.ESCALATED
    plan.outcome_note = reason
    plan.save(update_fields=["escalated_case", "status", "outcome_note", "updated_at"])

    from apps.audit.services import log as audit_log

    audit_log(
        action="hr.recovery_escalated_to_conduct",
        subject_kind="recovery_plan",
        subject_id=plan.id,
        actor_id=getattr(principal, "user_id", None),
        actor_role=_role(principal),
        payload={"caseId": case.id, "staffId": plan.staff_id},
    )
    return case
