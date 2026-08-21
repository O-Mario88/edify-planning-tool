"""Purpose-use, impact evidence and complete-geography lending projections."""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models import Count, OuterRef, Q, Subquery, Sum
from django.utils import timezone

from apps.audit.services import log as audit_log
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.permissions import has_permission
from apps.core.rbac import EdifyRole, Permission
from apps.core.scoping import resolve_user_scope
from apps.geography.models import District
from apps.schools.lifecycle_models import OPERATING_STATUSES

from .lending_ledger import MFI_ROLES, _actor_id, _assert_loan_scope, _date, _money
from .models import (
    EnrolmentSnapshot,
    EnrolmentSnapshotKind,
    ImpactEvidenceStatus,
    IAValidationStatus,
    LoanDisbursement,
    LoanImpactAssessment,
    LoanImpactStatus,
    LoanPurpose,
    LoanPurposeAllocation,
    LoanPurposeProposal,
    LoanPurposeProposalStatus,
    LoanVerificationRequirement,
    MfiLoan,
    MfiMembership,
    PurposeSpecificAssetOutput,
    PurposeAllocationStatus,
    TeacherDegreeUpgradeBeneficiary,
    TeacherProgrammeStatus,
    VerificationRequirementStatus,
)

ZERO = Decimal("0.00")
COUNTRY_ROLES = {
    EdifyRole.BUSINESS_TRANSFORMATION_OFFICER.value,
    EdifyRole.COUNTRY_DIRECTOR.value,
    EdifyRole.IMPACT_ASSESSMENT.value,
    EdifyRole.REGIONAL_VICE_PRESIDENT.value,
}


def _require(principal, permission: Permission, message: str) -> None:
    if not has_permission(principal, permission.value):
        raise Forbidden(message)


def _notify_purpose_stage(
    proposal: LoanPurposeProposal,
    *,
    event_type: str,
    title: str,
    roles: list[str] | None = None,
    recipient_ids: list[str] | None = None,
) -> None:
    from apps.accounts.models import User
    from apps.notifications.services import WorkflowNotificationService

    recipients = User.objects.filter(is_active=True)
    filters = Q()
    if roles:
        filters |= Q(active_role__in=roles)
    if recipient_ids:
        filters |= Q(id__in=recipient_ids)
    recipients = recipients.filter(filters) if filters else recipients.none()
    WorkflowNotificationService.trigger(
        event_type=event_type,
        category="business_transformation",
        priority="high",
        title=title,
        body=f"{proposal.proposed_label} · {proposal.proposed_code}",
        context_type="LoanPurposeProposal",
        context_id=proposal.id,
        recipients=recipients,
    )


def _audit(action: str, subject, principal, payload: dict) -> None:
    audit_log(
        action=action,
        subject_kind=type(subject).__name__,
        subject_id=str(subject.id),
        actor_id=_actor_id(principal),
        actor_role=getattr(principal, "active_role", None),
        payload=payload,
        required=True,
    )


def scoped_impact_loans(principal):
    """Loan identities for impact work without financial fields."""

    role = getattr(principal, "active_role", "")
    qs = MfiLoan.objects.select_related("school", "purpose")
    if role in MFI_ROLES:
        return qs.filter(
            mfi_id__in=MfiMembership.objects.filter(
                user_id=_actor_id(principal), active=True
            ).values("mfi_id")
        )
    if role in COUNTRY_ROLES:
        return qs
    if role in {EdifyRole.CCEO.value, EdifyRole.COUNTRY_PROGRAM_LEAD.value}:
        scope = resolve_user_scope(principal)
        return qs.filter(school_id__in=scope.school_ids)
    return qs.none()


@transaction.atomic
def set_purpose_allocation_plan(
    loan_id: str, allocations: list[dict], principal
) -> list[LoanPurposeAllocation]:
    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_LOAN_WRITE,
        "Only an authorized lending-partner operator may plan loan purposes.",
    )
    loan = MfiLoan.objects.select_for_update().filter(id=loan_id).first()
    if loan is None:
        raise NotFoundError("School loan not found.")
    _assert_loan_scope(principal, loan)
    if loan.disbursements.exists():
        raise Forbidden("Purpose allocations are locked after the first disbursement.")
    if loan.approved_amount is None or not allocations:
        raise BadRequest("An approved loan and at least one allocation are required.")
    if LoanPurposeAllocation.objects.filter(loan=loan).exists():
        raise Forbidden("Submit an amendment instead of rewriting the purpose plan.")
    parsed = []
    total = ZERO
    seen = set()
    for raw in allocations:
        purpose = LoanPurpose.objects.filter(
            id=raw.get("purposeId"), active=True
        ).first()
        if purpose is None or purpose.id in seen:
            raise BadRequest("Every purpose must be active and appear only once.")
        seen.add(purpose.id)
        amount = _money(raw.get("plannedAmount"), field="Planned purpose amount")
        intended_output = str(raw.get("intendedOutput") or "").strip()
        if not intended_output:
            raise BadRequest("Each purpose requires an intended output.")
        total += amount
        parsed.append((purpose, amount, intended_output))
    if total != loan.approved_amount:
        raise BadRequest(
            "Purpose allocations must exactly equal the approved loan amount."
        )
    rows = [
        LoanPurposeAllocation.objects.create(
            loan=loan,
            purpose=purpose,
            planned_amount=amount,
            intended_output=output,
            recorded_by=_actor_id(principal),
        )
        for purpose, amount, output in parsed
    ]
    _audit(
        "bt.loan.purpose_plan_created",
        loan,
        principal,
        {"allocationCount": len(rows), "plannedAmount": str(total)},
    )
    return rows


@transaction.atomic
def report_purpose_use(
    allocation_id: str, data: dict, principal
) -> LoanPurposeAllocation:
    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_LOAN_WRITE,
        "Only an authorized lending-partner operator may report loan use.",
    )
    allocation = (
        LoanPurposeAllocation.objects.select_for_update()
        .select_related("loan")
        .filter(id=allocation_id)
        .first()
    )
    if allocation is None:
        raise NotFoundError("Purpose allocation not found.")
    _assert_loan_scope(principal, allocation.loan)
    amount = _money(data.get("reportedAmount"), field="Reported use", allow_zero=True)
    if amount > allocation.planned_amount:
        raise BadRequest("Reported use cannot exceed the planned allocation.")
    allocation.reported_amount = amount
    allocation.status = PurposeAllocationStatus.REPORTED
    allocation.save(update_fields=["reported_amount", "status", "updated_at"])
    _audit(
        "bt.loan.purpose_use_reported",
        allocation,
        principal,
        {"reportedAmount": str(amount)},
    )
    return allocation


@transaction.atomic
def verify_purpose_use(
    allocation_id: str, data: dict, principal
) -> LoanPurposeAllocation:
    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_IA_VALIDATE,
        "Only Impact & Analytics may verify purpose use.",
    )
    allocation = (
        LoanPurposeAllocation.objects.select_for_update()
        .filter(id=allocation_id)
        .first()
    )
    if allocation is None:
        raise NotFoundError("Purpose allocation not found.")
    if allocation.reported_amount is None:
        raise BadRequest("Partner-reported use is required before verification.")
    amount = _money(data.get("verifiedAmount"), field="Verified use", allow_zero=True)
    if amount > allocation.reported_amount:
        raise BadRequest("Verified use cannot exceed partner-reported use.")
    allocation.verified_amount = amount
    allocation.status = PurposeAllocationStatus.VERIFIED
    allocation.verified_by = _actor_id(principal)
    allocation.verified_at = timezone.now()
    allocation.verification_note = str(data.get("note") or "").strip()
    allocation.save(
        update_fields=[
            "verified_amount",
            "status",
            "verified_by",
            "verified_at",
            "verification_note",
            "updated_at",
        ]
    )
    _audit(
        "bt.loan.purpose_use_verified",
        allocation,
        principal,
        {
            "reportedAmount": str(allocation.reported_amount),
            "verifiedAmount": str(amount),
        },
    )
    return allocation


@transaction.atomic
def capture_enrolment_snapshot(
    loan_id: str, data: dict, principal
) -> EnrolmentSnapshot:
    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_LOAN_WRITE,
        "Only an authorized lending-partner operator may report impact evidence.",
    )
    loan = MfiLoan.objects.select_for_update().filter(id=loan_id).first()
    if loan is None:
        raise NotFoundError("School loan not found.")
    _assert_loan_scope(principal, loan)
    kind = str(data.get("kind") or "").strip()
    if kind not in EnrolmentSnapshotKind.values:
        raise BadRequest("Snapshot kind must be baseline or follow_up.")
    try:
        learner_count = int(data.get("learnerCount"))
    except (TypeError, ValueError) as exc:
        raise BadRequest("Learner count must be a non-negative integer.") from exc
    if learner_count < 0:
        raise BadRequest("Learner count cannot be negative.")
    as_of_date = _date(data.get("asOfDate"), field="Snapshot date")
    first_disbursement = loan.disbursements.order_by("value_date").first()
    if kind == EnrolmentSnapshotKind.BASELINE and first_disbursement:
        if as_of_date > first_disbursement.value_date:
            raise BadRequest("Baseline must be dated on or before first disbursement.")
    if kind == EnrolmentSnapshotKind.FOLLOW_UP:
        if first_disbursement is None or as_of_date <= first_disbursement.value_date:
            raise BadRequest("Follow-up must be after a confirmed disbursement.")
    snapshot = EnrolmentSnapshot.objects.create(
        loan=loan,
        kind=kind,
        as_of_date=as_of_date,
        learner_count=learner_count,
        cohort_definition=str(data.get("cohortDefinition") or "").strip(),
        evidence_reference=str(data.get("evidenceReference") or "").strip(),
        reported_by=_actor_id(principal),
    )
    if not snapshot.cohort_definition or not snapshot.evidence_reference:
        raise BadRequest("Cohort definition and evidence reference are required.")
    _audit(
        "bt.loan.enrolment_reported",
        snapshot,
        principal,
        {
            "kind": kind,
            "asOfDate": as_of_date.isoformat(),
            "learnerCount": learner_count,
        },
    )
    return snapshot


@transaction.atomic
def verify_enrolment_snapshot(
    snapshot_id: str, data: dict, principal
) -> EnrolmentSnapshot:
    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_IA_VALIDATE,
        "Only Impact & Analytics may verify impact evidence.",
    )
    snapshot = (
        EnrolmentSnapshot.objects.select_for_update().filter(id=snapshot_id).first()
    )
    if snapshot is None:
        raise NotFoundError("Enrolment snapshot not found.")
    decision = str(data.get("decision") or "verified").strip()
    if decision not in {ImpactEvidenceStatus.VERIFIED, ImpactEvidenceStatus.RETURNED}:
        raise BadRequest("Decision must be verified or returned.")
    snapshot.status = decision
    snapshot.verified_by = _actor_id(principal)
    snapshot.verified_at = timezone.now()
    snapshot.save(update_fields=["status", "verified_by", "verified_at", "updated_at"])
    _audit(
        "bt.loan.enrolment_verified"
        if decision == "verified"
        else "bt.loan.enrolment_returned",
        snapshot,
        principal,
        {"decision": decision, "note": str(data.get("note") or "").strip()},
    )
    return snapshot


def _positive_int(value, *, field: str, allow_zero: bool = False) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise BadRequest(f"{field} must be a whole number.") from exc
    if parsed < 0 or (parsed == 0 and not allow_zero):
        comparator = "zero or greater" if allow_zero else "greater than zero"
        raise BadRequest(f"{field} must be {comparator}.")
    return parsed


@transaction.atomic
def create_asset_output(
    allocation_id: str, data: dict, principal
) -> PurposeSpecificAssetOutput:
    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_LOAN_WRITE,
        "Only an authorized lending-partner operator may plan purpose outputs.",
    )
    allocation = (
        LoanPurposeAllocation.objects.select_for_update()
        .select_related("loan", "purpose")
        .filter(id=allocation_id)
        .first()
    )
    if allocation is None:
        raise NotFoundError("Purpose allocation not found.")
    _assert_loan_scope(principal, allocation.loan)
    if allocation.loan.disbursements.exists():
        raise Forbidden("Planned outputs are locked after the first disbursement.")
    asset_type = str(data.get("assetType") or "").strip().lower()
    allowed_types = {"classroom", "land", "computer", "computer_lab", "other"}
    if asset_type not in allowed_types:
        raise BadRequest("Choose a governed purpose output type.")
    output = PurposeSpecificAssetOutput.objects.create(
        allocation=allocation,
        asset_type=asset_type,
        unit=str(
            data.get("unit") or allocation.purpose.unit_of_measure or "count"
        ).strip(),
        planned_quantity=_positive_int(
            data.get("plannedQuantity"), field="Planned quantity"
        ),
        unit_cost=(
            _money(data.get("unitCost"), field="Unit cost", allow_zero=True)
            if data.get("unitCost") not in (None, "")
            else None
        ),
        learner_capacity=(
            _positive_int(
                data.get("learnerCapacity"),
                field="Learner capacity",
                allow_zero=True,
            )
            if data.get("learnerCapacity") not in (None, "")
            else None
        ),
        area=(
            _money(data.get("area"), field="Area", allow_zero=True)
            if data.get("area") not in (None, "")
            else None
        ),
        area_unit=str(data.get("areaUnit") or "").strip(),
        reported_by=_actor_id(principal),
    )
    if output.area is not None and not output.area_unit:
        raise BadRequest("An area unit is required when land area is supplied.")
    _audit(
        "bt.loan.purpose_output_planned",
        output,
        principal,
        {
            "assetType": output.asset_type,
            "plannedQuantity": output.planned_quantity,
        },
    )
    return output


@transaction.atomic
def report_asset_output(
    output_id: str, data: dict, principal
) -> PurposeSpecificAssetOutput:
    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_LOAN_WRITE,
        "Only an authorized lending-partner operator may report purpose outputs.",
    )
    output = (
        PurposeSpecificAssetOutput.objects.select_for_update()
        .select_related("allocation__loan")
        .filter(id=output_id)
        .first()
    )
    if output is None:
        raise NotFoundError("Purpose output not found.")
    _assert_loan_scope(principal, output.allocation.loan)
    reported = _positive_int(
        data.get("reportedQuantity"), field="Reported quantity", allow_zero=True
    )
    operational = _positive_int(
        data.get("reportedOperationalQuantity", 0),
        field="Reported operational quantity",
        allow_zero=True,
    )
    if reported > output.planned_quantity or operational > reported:
        raise BadRequest(
            "Reported quantity cannot exceed plan and operational quantity cannot "
            "exceed reported quantity."
        )
    output.reported_quantity = reported
    output.reported_operational_quantity = operational
    output.reported_completion_state = str(data.get("completionState") or "").strip()
    output.evidence_reference = str(data.get("evidenceReference") or "").strip()
    output.status = ImpactEvidenceStatus.REPORTED
    output.save(
        update_fields=[
            "reported_quantity",
            "reported_operational_quantity",
            "reported_completion_state",
            "evidence_reference",
            "status",
            "updated_at",
        ]
    )
    _audit(
        "bt.loan.purpose_output_reported",
        output,
        principal,
        {"reportedQuantity": reported, "operationalQuantity": operational},
    )
    return output


@transaction.atomic
def verify_asset_output(
    output_id: str, data: dict, principal
) -> PurposeSpecificAssetOutput:
    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_IA_VALIDATE,
        "Only Impact & Analytics may verify purpose outputs.",
    )
    output = (
        PurposeSpecificAssetOutput.objects.select_for_update()
        .filter(id=output_id)
        .first()
    )
    if output is None:
        raise NotFoundError("Purpose output not found.")
    if output.reported_quantity is None or not output.evidence_reference:
        raise BadRequest(
            "Reported output and evidence are required before verification."
        )
    verified = _positive_int(
        data.get("verifiedQuantity"), field="Verified quantity", allow_zero=True
    )
    operational = _positive_int(
        data.get("verifiedOperationalQuantity", 0),
        field="Verified operational quantity",
        allow_zero=True,
    )
    if verified > output.reported_quantity or operational > verified:
        raise BadRequest(
            "Verified quantity cannot exceed reported quantity and operational "
            "quantity cannot exceed verified quantity."
        )
    output.verified_quantity = verified
    output.verified_operational_quantity = operational
    output.verified_completion_state = str(data.get("completionState") or "").strip()
    output.status = ImpactEvidenceStatus.VERIFIED
    output.verified_by = _actor_id(principal)
    output.verified_at = timezone.now()
    output.save(
        update_fields=[
            "verified_quantity",
            "verified_operational_quantity",
            "verified_completion_state",
            "status",
            "verified_by",
            "verified_at",
            "updated_at",
        ]
    )
    _audit(
        "bt.loan.purpose_output_verified",
        output,
        principal,
        {"verifiedQuantity": verified, "operationalQuantity": operational},
    )
    return output


@transaction.atomic
def record_teacher_beneficiary(
    loan_id: str, data: dict, principal
) -> TeacherDegreeUpgradeBeneficiary:
    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_LOAN_WRITE,
        "Only an authorized lending-partner operator may record a beneficiary.",
    )
    loan = MfiLoan.objects.select_for_update().filter(id=loan_id).first()
    if loan is None:
        raise NotFoundError("School loan not found.")
    _assert_loan_scope(principal, loan)
    reference = str(data.get("beneficiaryReference") or "").strip()
    institution = str(data.get("institution") or "").strip()
    programme = str(data.get("programme") or "").strip()
    if not reference or not institution or not programme:
        raise BadRequest(
            "Beneficiary reference, institution and programme are required."
        )
    programme_status = str(
        data.get("programmeStatus") or TeacherProgrammeStatus.PLANNED
    ).strip()
    if programme_status not in {
        TeacherProgrammeStatus.PLANNED,
        TeacherProgrammeStatus.ENROLLED,
        TeacherProgrammeStatus.STUDYING,
    }:
        raise BadRequest("A new beneficiary must be planned, enrolled or studying.")
    beneficiary = TeacherDegreeUpgradeBeneficiary.objects.create(
        loan=loan,
        anonymized_reference=reference,
        qualification_before=str(data.get("qualificationBefore") or "").strip(),
        institution=institution,
        programme=programme,
        started_on=_date(data.get("startedOn"), field="Programme start date"),
        expected_completion_on=(
            _date(data.get("expectedCompletionOn"), field="Expected completion date")
            if data.get("expectedCompletionOn")
            else None
        ),
        funding_amount=(
            _money(data.get("fundingAmount"), field="Funding amount", allow_zero=True)
            if data.get("fundingAmount") not in (None, "")
            else None
        ),
        programme_status=programme_status,
        evidence_reference=str(data.get("evidenceReference") or "").strip(),
        reported_by=_actor_id(principal),
    )
    _audit(
        "bt.loan.teacher_beneficiary_recorded",
        beneficiary,
        principal,
        {"programmeStatus": programme_status},
    )
    return beneficiary


@transaction.atomic
def report_teacher_progress(
    beneficiary_id: str, data: dict, principal
) -> TeacherDegreeUpgradeBeneficiary:
    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_LOAN_WRITE,
        "Only an authorized lending-partner operator may report teacher progress.",
    )
    beneficiary = (
        TeacherDegreeUpgradeBeneficiary.objects.select_for_update()
        .select_related("loan")
        .filter(id=beneficiary_id)
        .first()
    )
    if beneficiary is None:
        raise NotFoundError("Teacher beneficiary not found.")
    _assert_loan_scope(principal, beneficiary.loan)
    status = str(data.get("programmeStatus") or "").strip()
    allowed = {
        TeacherProgrammeStatus.ENROLLED,
        TeacherProgrammeStatus.STUDYING,
        TeacherProgrammeStatus.DEFERRED,
        TeacherProgrammeStatus.WITHDRAWN,
        TeacherProgrammeStatus.COMPLETED,
        TeacherProgrammeStatus.VERIFICATION_PENDING,
    }
    if status not in allowed:
        raise BadRequest("Choose a valid reportable programme status.")
    completed_on = (
        _date(data.get("completedOn"), field="Completion date")
        if data.get("completedOn")
        else None
    )
    evidence = str(data.get("evidenceReference") or "").strip()
    if status in {
        TeacherProgrammeStatus.COMPLETED,
        TeacherProgrammeStatus.VERIFICATION_PENDING,
    } and (completed_on is None or not evidence):
        raise BadRequest("Reported completion requires a completion date and evidence.")
    beneficiary.programme_status = status
    beneficiary.completed_on = completed_on
    beneficiary.evidence_reference = evidence
    beneficiary.status = ImpactEvidenceStatus.REPORTED
    beneficiary.save(
        update_fields=[
            "programme_status",
            "completed_on",
            "evidence_reference",
            "status",
            "updated_at",
        ]
    )
    _audit(
        "bt.loan.teacher_progress_reported",
        beneficiary,
        principal,
        {"programmeStatus": status},
    )
    return beneficiary


@transaction.atomic
def verify_teacher_completion(
    beneficiary_id: str, data: dict, principal
) -> TeacherDegreeUpgradeBeneficiary:
    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_IA_VALIDATE,
        "Only Impact & Analytics may verify teacher completion.",
    )
    beneficiary = (
        TeacherDegreeUpgradeBeneficiary.objects.select_for_update()
        .filter(id=beneficiary_id)
        .first()
    )
    if beneficiary is None:
        raise NotFoundError("Teacher beneficiary not found.")
    if beneficiary.completed_on is None or not beneficiary.evidence_reference:
        raise BadRequest("Completion date and evidence are required for verification.")
    beneficiary.programme_status = TeacherProgrammeStatus.VERIFIED_COMPLETED
    beneficiary.status = ImpactEvidenceStatus.VERIFIED
    beneficiary.verified_by = _actor_id(principal)
    beneficiary.verified_at = timezone.now()
    beneficiary.save(
        update_fields=[
            "programme_status",
            "status",
            "verified_by",
            "verified_at",
            "updated_at",
        ]
    )
    _audit(
        "bt.loan.teacher_completion_verified",
        beneficiary,
        principal,
        {"note": str(data.get("note") or "").strip()},
    )
    return beneficiary


@transaction.atomic
def request_loan_purpose(data: dict, principal) -> LoanPurposeProposal:
    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_PURPOSE_REQUEST,
        "Only a lending-partner operator may request a new purpose.",
    )
    code = str(data.get("code") or "").strip().upper()
    label = str(data.get("name") or "").strip()
    required = {
        "code": code,
        "name": label,
        "description": str(data.get("description") or "").strip(),
        "business reason": str(data.get("businessReason") or "").strip(),
        "expected outputs": str(data.get("expectedOutputs") or "").strip(),
        "unit": str(data.get("unit") or "").strip(),
        "expected impact": str(data.get("expectedImpact") or "").strip(),
        "example loan": str(data.get("exampleLoanReference") or "").strip(),
    }
    missing = [label for label, value in required.items() if not value]
    evidence = data.get("requiredEvidence") or []
    if missing or not isinstance(evidence, list) or not evidence:
        raise BadRequest(
            "A new purpose request requires its full measurement and evidence profile."
        )
    if (
        LoanPurpose.objects.filter(code=code).exists()
        or LoanPurposeProposal.objects.filter(
            proposed_code=code,
            status__in=[
                LoanPurposeProposalStatus.REQUESTED,
                LoanPurposeProposalStatus.BT_REVIEWED,
                LoanPurposeProposalStatus.IA_DEFINED,
                LoanPurposeProposalStatus.APPROVED,
            ],
        ).exists()
    ):
        raise BadRequest("That purpose code already exists or is under review.")
    proposal = LoanPurposeProposal.objects.create(
        proposed_code=code,
        proposed_label=label,
        proposed_is_edtech=bool(data.get("isEdtech", False)),
        rationale=required["business reason"],
        description=required["description"],
        expected_outputs=required["expected outputs"],
        unit_of_measure=required["unit"],
        required_evidence=evidence,
        expected_impact=required["expected impact"],
        example_loan_reference=required["example loan"],
        requested_by=_actor_id(principal),
    )
    _audit("bt.loan.purpose_requested", proposal, principal, {"code": code})
    _notify_purpose_stage(
        proposal,
        event_type="bt.loan.purpose_requested",
        title="New loan purpose requires BT review",
        roles=[EdifyRole.BUSINESS_TRANSFORMATION_OFFICER.value],
    )
    return proposal


@transaction.atomic
def review_loan_purpose(proposal_id: str, data: dict, principal) -> LoanPurposeProposal:
    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_PURPOSE_REVIEW,
        "Only Business Transformation may review a proposed purpose.",
    )
    proposal = (
        LoanPurposeProposal.objects.select_for_update().filter(id=proposal_id).first()
    )
    if proposal is None:
        raise NotFoundError("Purpose proposal not found.")
    if proposal.status != LoanPurposeProposalStatus.REQUESTED:
        raise BadRequest("Only a requested purpose can receive BT review.")
    note = str(data.get("note") or "").strip()
    if not note:
        raise BadRequest("BT review notes are required.")
    proposal.status = LoanPurposeProposalStatus.BT_REVIEWED
    proposal.bt_reviewed_by = _actor_id(principal)
    proposal.bt_reviewed_at = timezone.now()
    proposal.review_note = note
    proposal.save(
        update_fields=[
            "status",
            "bt_reviewed_by",
            "bt_reviewed_at",
            "review_note",
            "updated_at",
        ]
    )
    _audit("bt.loan.purpose_bt_reviewed", proposal, principal, {"note": note})
    from apps.notifications.services import resolve_condition

    resolve_condition("bt.loan.purpose_requested", "LoanPurposeProposal", proposal.id)
    _notify_purpose_stage(
        proposal,
        event_type="bt.loan.purpose_bt_reviewed",
        title="Loan purpose needs measurement definition",
        roles=[EdifyRole.IMPACT_ASSESSMENT.value],
    )
    return proposal


@transaction.atomic
def define_loan_purpose_measurement(
    proposal_id: str, data: dict, principal
) -> LoanPurposeProposal:
    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_PURPOSE_DEFINE,
        "Only Impact & Analytics may define purpose measurement.",
    )
    proposal = (
        LoanPurposeProposal.objects.select_for_update().filter(id=proposal_id).first()
    )
    if proposal is None:
        raise NotFoundError("Purpose proposal not found.")
    if proposal.status != LoanPurposeProposalStatus.BT_REVIEWED:
        raise BadRequest("BT review is required before IA measurement definition.")
    evidence = data.get("requiredEvidence") or proposal.required_evidence
    indicators = data.get("impactIndicators") or []
    method = str(data.get("verificationMethod") or "").strip()
    if not evidence or not indicators or not method:
        raise BadRequest(
            "Evidence, impact indicators and verification method are required."
        )
    proposal.required_evidence = evidence
    proposal.expected_impact = str(
        data.get("expectedImpact") or proposal.expected_impact
    ).strip()
    proposal.verification_method = method
    proposal.impact_indicators = indicators
    proposal.ia_defined_by = _actor_id(principal)
    proposal.ia_defined_at = timezone.now()
    proposal.status = LoanPurposeProposalStatus.IA_DEFINED
    proposal.save(
        update_fields=[
            "required_evidence",
            "expected_impact",
            "verification_method",
            "impact_indicators",
            "ia_defined_by",
            "ia_defined_at",
            "status",
            "updated_at",
        ]
    )
    _audit(
        "bt.loan.purpose_measurement_defined",
        proposal,
        principal,
        {"verificationMethod": method, "impactIndicators": indicators},
    )
    from apps.notifications.services import resolve_condition

    resolve_condition("bt.loan.purpose_bt_reviewed", "LoanPurposeProposal", proposal.id)
    _notify_purpose_stage(
        proposal,
        event_type="bt.loan.purpose_measurement_defined",
        title="Loan purpose is ready for country approval",
        roles=[EdifyRole.COUNTRY_DIRECTOR.value],
    )
    return proposal


@transaction.atomic
def approve_loan_purpose(proposal_id: str, data: dict, principal) -> LoanPurpose:
    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_PURPOSE_APPROVE,
        "Only the Country Director may approve a governed purpose.",
    )
    proposal = (
        LoanPurposeProposal.objects.select_for_update().filter(id=proposal_id).first()
    )
    if proposal is None:
        raise NotFoundError("Purpose proposal not found.")
    if proposal.status != LoanPurposeProposalStatus.IA_DEFINED:
        raise BadRequest("IA measurement definition is required before approval.")
    countries = data.get("applicableCountries") or []
    if not countries:
        raise BadRequest("Country applicability is required.")
    purpose = LoanPurpose.objects.create(
        code=proposal.proposed_code,
        label=proposal.proposed_label,
        description=proposal.description,
        applicable_countries=countries,
        unit_of_measure=proposal.unit_of_measure,
        required_evidence=proposal.required_evidence,
        verification_method=proposal.verification_method,
        impact_indicators=proposal.impact_indicators,
        measurement_profile_complete=True,
        is_edtech=proposal.proposed_is_edtech,
        active=True,
    )
    proposal.status = LoanPurposeProposalStatus.APPROVED
    proposal.cd_approved_by = _actor_id(principal)
    proposal.cd_approved_at = timezone.now()
    proposal.reviewed_by = _actor_id(principal)
    proposal.reviewed_at = proposal.cd_approved_at
    proposal.resulting_purpose = purpose
    proposal.save(
        update_fields=[
            "status",
            "cd_approved_by",
            "cd_approved_at",
            "reviewed_by",
            "reviewed_at",
            "resulting_purpose",
            "updated_at",
        ]
    )
    _audit(
        "bt.loan.purpose_published",
        purpose,
        principal,
        {"proposalId": proposal.id, "countries": countries},
    )
    from apps.notifications.services import resolve_condition

    resolve_condition(
        "bt.loan.purpose_measurement_defined", "LoanPurposeProposal", proposal.id
    )
    _notify_purpose_stage(
        proposal,
        event_type="bt.loan.purpose_approved",
        title="Requested loan purpose approved",
        recipient_ids=[proposal.requested_by],
    )
    return purpose


def purpose_output_summary(principal) -> dict:
    loans = scoped_impact_loans(principal)
    outputs = PurposeSpecificAssetOutput.objects.filter(
        allocation__loan__in=loans,
        status=ImpactEvidenceStatus.VERIFIED,
    )
    teachers = TeacherDegreeUpgradeBeneficiary.objects.filter(loan__in=loans)
    by_type = {
        row["asset_type"]: {
            "verified": row["verified"] or 0,
            "operational": row["operational"] or 0,
        }
        for row in outputs.values("asset_type").annotate(
            verified=Sum("verified_quantity"),
            operational=Sum("verified_operational_quantity"),
        )
    }
    return {
        "outputs": by_type,
        "learnerCapacityCreated": outputs.aggregate(total=Sum("learner_capacity"))[
            "total"
        ],
        "teachersFinanced": teachers.values("anonymized_reference").distinct().count(),
        "teachersEnrolled": teachers.filter(
            programme_status__in=[
                TeacherProgrammeStatus.ENROLLED,
                TeacherProgrammeStatus.STUDYING,
                TeacherProgrammeStatus.COMPLETED,
                TeacherProgrammeStatus.VERIFICATION_PENDING,
                TeacherProgrammeStatus.VERIFIED_COMPLETED,
            ]
        )
        .values("anonymized_reference")
        .distinct()
        .count(),
        "teachersStudying": teachers.filter(
            programme_status=TeacherProgrammeStatus.STUDYING
        )
        .values("anonymized_reference")
        .distinct()
        .count(),
        "teachersVerifiedCompleted": teachers.filter(
            programme_status=TeacherProgrammeStatus.VERIFIED_COMPLETED,
            status=ImpactEvidenceStatus.VERIFIED,
        )
        .values("anonymized_reference")
        .distinct()
        .count(),
        "teachersDeferred": teachers.filter(
            programme_status=TeacherProgrammeStatus.DEFERRED
        )
        .values("anonymized_reference")
        .distinct()
        .count(),
        "teachersWithdrawn": teachers.filter(
            programme_status=TeacherProgrammeStatus.WITHDRAWN
        )
        .values("anonymized_reference")
        .distinct()
        .count(),
    }


@transaction.atomic
def verify_loan_impact(
    assessment_id: str, data: dict, principal
) -> LoanImpactAssessment:
    """Publish an evidence-backed IA conclusion without claiming causation."""

    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_IA_VALIDATE,
        "Only Impact & Analytics may publish a loan impact assessment.",
    )
    assessment = (
        LoanImpactAssessment.objects.select_for_update()
        .select_related("loan")
        .filter(id=assessment_id)
        .first()
    )
    if assessment is None:
        raise NotFoundError("Loan impact assessment not found.")
    if assessment.due_date > timezone.localdate():
        raise BadRequest("Impact cannot be published before the assessment is due.")
    if not LoanVerificationRequirement.objects.filter(
        loan=assessment.loan,
        status=VerificationRequirementStatus.VERIFIED,
        result__verification_status="confirmed",
    ).exists():
        raise BadRequest("Verified loan use is required before impact publication.")
    baseline = (
        EnrolmentSnapshot.objects.filter(
            loan=assessment.loan,
            kind=EnrolmentSnapshotKind.BASELINE,
            status=ImpactEvidenceStatus.VERIFIED,
        )
        .order_by("-as_of_date")
        .first()
    )
    follow_up = (
        EnrolmentSnapshot.objects.filter(
            loan=assessment.loan,
            kind=EnrolmentSnapshotKind.FOLLOW_UP,
            status=ImpactEvidenceStatus.VERIFIED,
        )
        .order_by("-as_of_date")
        .first()
    )
    verified_outputs = PurposeSpecificAssetOutput.objects.filter(
        allocation__loan=assessment.loan,
        status=ImpactEvidenceStatus.VERIFIED,
    ).exists()
    verified_teacher = TeacherDegreeUpgradeBeneficiary.objects.filter(
        loan=assessment.loan,
        status=ImpactEvidenceStatus.VERIFIED,
    ).exists()
    if baseline is None or not (follow_up or verified_outputs or verified_teacher):
        raise BadRequest(
            "A verified baseline and at least one verified follow-up or purpose output "
            "are required."
        )
    classification = str(data.get("classification") or "").strip()
    allowed = {
        LoanImpactStatus.STRONG_POSITIVE,
        LoanImpactStatus.POSITIVE,
        LoanImpactStatus.EARLY_PROGRESS,
        LoanImpactStatus.MIXED,
        LoanImpactStatus.NO_CHANGE,
        LoanImpactStatus.NEGATIVE,
        LoanImpactStatus.INSUFFICIENT_EVIDENCE,
    }
    if classification not in allowed:
        raise BadRequest("Choose a governed impact classification.")
    narrative = str(data.get("narrative") or "").strip()
    limitations = str(data.get("limitations") or "").strip()
    evidence = data.get("evidenceReferences") or []
    if (
        not narrative
        or not limitations
        or not isinstance(evidence, list)
        or not evidence
    ):
        raise BadRequest(
            "Impact publication requires narrative, limitations and evidence references."
        )
    assessment.assessment_date = timezone.localdate()
    assessment.baseline_indicators = {
        "learnerCount": baseline.learner_count,
        "asOfDate": baseline.as_of_date.isoformat(),
    }
    assessment.follow_up_indicators = (
        {
            "learnerCount": follow_up.learner_count,
            "asOfDate": follow_up.as_of_date.isoformat(),
        }
        if follow_up
        else {}
    )
    assessment.classification = classification
    assessment.narrative = narrative
    assessment.limitations = limitations
    assessment.evidence_references = evidence
    assessment.prepared_by = "server-evidence-compiler"
    assessment.prepared_at = timezone.now()
    assessment.ia_status = IAValidationStatus.VERIFIED
    assessment.ia_verified_by = _actor_id(principal)
    assessment.ia_verified_at = timezone.now()
    assessment.ia_note = str(data.get("note") or "").strip()
    assessment.save()
    loan = assessment.loan
    previous = loan.impact_status
    loan.impact_status = classification
    loan.save(update_fields=["impact_status", "updated_at"])
    _audit(
        "bt.loan.impact_verified",
        assessment,
        principal,
        {
            "previousClassification": previous,
            "classification": classification,
            "causalClaim": "observed_after_financing",
        },
    )
    return assessment


def impact_summary(principal) -> dict:
    loans = scoped_impact_loans(principal)
    snapshots = EnrolmentSnapshot.objects.filter(loan__in=loans)
    verified = snapshots.filter(status=ImpactEvidenceStatus.VERIFIED)
    baseline_loans = verified.filter(kind=EnrolmentSnapshotKind.BASELINE).values(
        "loan_id"
    )
    follow_up = verified.filter(kind=EnrolmentSnapshotKind.FOLLOW_UP)
    return {
        "loansInScope": loans.count(),
        "verifiedBaselineLoans": baseline_loans.distinct().count(),
        "verifiedFollowUpLoans": follow_up.values("loan_id").distinct().count(),
        "verifiedLearnersObserved": follow_up.aggregate(total=Sum("learner_count"))[
            "total"
        ],
        "reportedEvidencePending": snapshots.filter(
            status=ImpactEvidenceStatus.REPORTED
        ).count(),
        "missingBaselineLoans": loans.exclude(id__in=baseline_loans).count(),
    }


def geographic_equity(principal) -> dict:
    """Complete district spine with zero and missing data kept distinct."""

    loans = scoped_impact_loans(principal)
    include_financial = has_permission(
        principal, Permission.BUSINESS_TRANSFORMATION_SENSITIVE_VIEW.value
    )
    confirmed_amounts = (
        LoanDisbursement.objects.filter(
            loan__in=loans,
            loan__school__district_id=OuterRef("pk"),
            reversal__isnull=True,
        )
        .values("loan__school__district_id")
        .annotate(total=Sum("amount"))
        .values("total")[:1]
    )
    districts = District.objects.select_related("region").annotate(
        eligible_schools=Count(
            "schools",
            filter=Q(schools__operational_status__in=OPERATING_STATUSES),
            distinct=True,
        ),
        loan_count=Count(
            "schools__mfi_loans",
            filter=Q(
                schools__mfi_loans__in=loans,
                schools__mfi_loans__disbursements__isnull=False,
                schools__mfi_loans__disbursements__reversal__isnull=True,
            ),
            distinct=True,
        ),
        schools_financed=Count(
            "schools",
            filter=Q(
                schools__mfi_loans__in=loans,
                schools__mfi_loans__disbursements__isnull=False,
                schools__mfi_loans__disbursements__reversal__isnull=True,
            ),
            distinct=True,
        ),
        verified_impact_schools=Count(
            "schools__mfi_loans",
            filter=Q(
                schools__mfi_loans__in=loans,
                schools__mfi_loans__enrolment_snapshots__kind=EnrolmentSnapshotKind.FOLLOW_UP,
                schools__mfi_loans__enrolment_snapshots__status=ImpactEvidenceStatus.VERIFIED,
            ),
            distinct=True,
        ),
        confirmed_disbursed_amount=Subquery(confirmed_amounts),
    )
    rows = []
    for district in districts:
        row = {
            "regionId": district.region_id,
            "region": district.region.name,
            "districtId": district.id,
            "district": district.name,
            "eligibleSchools": district.eligible_schools,
            "loanCount": district.loan_count,
            "schoolsFinanced": district.schools_financed,
            "verifiedImpactSchools": district.verified_impact_schools,
            "financingPenetrationPct": (
                round(district.schools_financed / district.eligible_schools * 100, 1)
                if district.eligible_schools
                else None
            ),
            "noLoanGap": bool(
                district.eligible_schools and district.schools_financed == 0
            ),
            "dataState": (
                "not_applicable"
                if district.eligible_schools == 0
                else "zero"
                if district.schools_financed == 0
                else "observed"
            ),
        }
        if include_financial:
            total = district.confirmed_disbursed_amount or ZERO
            row["confirmedDisbursedAmount"] = str(total)
            row["amountPerEligibleSchool"] = (
                str((total / district.eligible_schools).quantize(Decimal("0.01")))
                if district.eligible_schools
                else None
            )
        rows.append(row)
    return {
        "rows": rows,
        "loansMissingDistrict": loans.filter(school__district__isnull=True).count(),
        "financialFieldsIncluded": include_financial,
    }


__all__ = [
    "approve_loan_purpose",
    "capture_enrolment_snapshot",
    "create_asset_output",
    "define_loan_purpose_measurement",
    "geographic_equity",
    "impact_summary",
    "purpose_output_summary",
    "record_teacher_beneficiary",
    "report_asset_output",
    "report_purpose_use",
    "report_teacher_progress",
    "request_loan_purpose",
    "review_loan_purpose",
    "scoped_impact_loans",
    "set_purpose_allocation_plan",
    "verify_asset_output",
    "verify_enrolment_snapshot",
    "verify_loan_impact",
    "verify_purpose_use",
    "verify_teacher_completion",
]
