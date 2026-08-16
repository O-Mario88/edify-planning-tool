"""Business Transformation application services and authority boundaries."""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import Count, Max, OuterRef, Q, Subquery, Sum
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from apps.core.enums import SsaIntervention
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.fy import (
    get_fy_date_range,
    get_month_date_range,
    get_operational_fy,
    get_quarter_date_range,
)
from apps.core.metrics import MetricValue, render_metric, render_strip
from apps.core.permissions import has_permission
from apps.core.rbac import EdifyRole, Permission

from .models import (
    BusinessTransformationActivityLink,
    BusinessTransformationPolicy,
    CaseRecommendation,
    CaseStatus,
    CaseTrigger,
    DISBURSED_LOAN_STATUSES,
    FinanceReferral,
    FinancialPracticeAssessment,
    IAValidationStatus,
    LoanImpactStatus,
    LoanImpactAssessment,
    LoanPurpose,
    LoanStatus,
    LoanStatusDimension,
    LoanStatusHistory,
    LoanUseResult,
    LoanVerificationRequirement,
    MfiLoan,
    MfiMembership,
    MfiMembershipRole,
    MfiOrganization,
    OPEN_CASE_STATUSES,
    PortfolioDataException,
    PortfolioSubmission,
    RecommendationKind,
    ReferralStatus,
    RepaymentSnapshot,
    RepaymentStatus,
    SalesforceStatus,
    SchoolComplianceAssessment,
    ComplianceRequirement,
    TransformationCase,
    TriggerType,
    VerificationRequirementStatus,
)


UGANDA_WIDE_ROLES = {
    EdifyRole.BUSINESS_TRANSFORMATION_OFFICER.value,
    EdifyRole.COUNTRY_DIRECTOR.value,
    EdifyRole.IMPACT_ASSESSMENT.value,
    EdifyRole.ADMIN.value,
}
SUMMARY_ONLY_ROLES = {EdifyRole.REGIONAL_VICE_PRESIDENT.value}
MFI_ROLES = {
    EdifyRole.MFI_PARTNER_ADMIN.value,
    EdifyRole.MFI_LOAN_OFFICER.value,
}
SALESFORCE_ID_PATTERN = re.compile(r"^Loan-[0-9]+$")
SALESFORCE_RETURN_REASONS = {
    "school_unmatched": "School could not be matched",
    "duplicate_loan": "Duplicate loan",
    "amount_inconsistent": "Amount is inconsistent",
    "purpose_missing": "Loan purpose missing",
    "disbursement_date_missing": "Disbursement date missing",
    "invalid_mfi_reference": "Invalid MFI loan reference",
    "incorrect_status": "Incorrect status",
    "other": "Other reason",
}
CORE_LOAN_IDENTITY_FIELDS = {
    "external_loan_reference",
    "school_id",
    "mfi_id",
    "purpose_id",
    "approved_amount",
    "disbursed_amount",
    "disbursement_date",
}


def _actor_id(principal) -> str:
    return str(
        getattr(principal, "user_id", None)
        or getattr(principal, "id", None)
        or "system"
    )


def _require(principal, permission: Permission, message: str) -> None:
    if not has_permission(principal, permission.value):
        raise Forbidden(message)


def _record_status_change(
    loan: MfiLoan,
    dimension: str,
    previous_value: str,
    new_value: str,
    principal,
    *,
    reason: str = "",
) -> None:
    if previous_value == new_value:
        return
    LoanStatusHistory.objects.create(
        loan=loan,
        dimension=dimension,
        previous_value=previous_value or "",
        new_value=new_value,
        reason=reason,
        changed_by=_actor_id(principal),
        effective_at=timezone.now(),
    )


def _audit_loan_event(action: str, loan: MfiLoan, principal, payload: dict) -> None:
    from apps.audit.services import log as audit_log

    audit_log(
        action=action,
        subject_kind="MfiLoan",
        subject_id=str(loan.id),
        actor_id=_actor_id(principal),
        actor_role=getattr(principal, "active_role", None),
        payload=payload,
    )


def _decimal(value, *, field: str, required: bool = False) -> Decimal | None:
    if value in (None, ""):
        if required:
            raise BadRequest(f"{field} is required.")
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise BadRequest(f"{field} must be numeric.") from exc
    if parsed <= 0:
        raise BadRequest(f"{field} must be greater than zero.")
    return parsed


def _nonnegative_decimal(
    value, *, field: str, required: bool = False
) -> Decimal | None:
    if value in (None, ""):
        if required:
            raise BadRequest(f"{field} is required.")
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise BadRequest(f"{field} must be numeric.") from exc
    if parsed < 0:
        raise BadRequest(f"{field} cannot be negative.")
    return parsed


def _date(value, *, field: str, required: bool = False):
    if value in (None, ""):
        if required:
            raise BadRequest(f"{field} is required.")
        return None
    parsed = value.date() if hasattr(value, "date") else value
    parsed = parsed if hasattr(parsed, "year") else parse_date(str(parsed))
    if parsed is None:
        raise BadRequest(f"{field} must be a valid date.")
    return parsed


def _reporting_month(value, *, fallback):
    """Normalize an HTML month value to the first day of its reporting month."""

    if value in (None, ""):
        return fallback.replace(day=1)
    text = str(value).strip()
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}", text):
        text = f"{text}-01"
    return _date(text, field="Reporting month", required=True).replace(day=1)


def _datetime(value, *, field: str, required: bool = False):
    if value in (None, ""):
        if required:
            raise BadRequest(f"{field} is required.")
        return None
    if hasattr(value, "tzinfo"):
        parsed = value
    else:
        parsed = parse_datetime(str(value))
    if parsed is None:
        raise BadRequest(f"{field} must be a valid date and time.")
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _mfi_ids_for(principal, *, admin_only: bool = False) -> list[str]:
    qs = MfiMembership.objects.filter(user_id=_actor_id(principal), active=True)
    if admin_only:
        qs = qs.filter(role=MfiMembershipRole.ADMIN)
    return list(qs.values_list("mfi_id", flat=True))


def _assert_mfi_scope(principal, mfi_id: str, *, admin_only: bool = False) -> None:
    if str(mfi_id) not in set(_mfi_ids_for(principal, admin_only=admin_only)):
        raise NotFoundError("MFI record not found in your portfolio.")


def scoped_mfis(principal):
    qs = MfiOrganization.objects.filter(active=True).order_by("name")
    if getattr(principal, "active_role", "") in MFI_ROLES:
        return qs.filter(id__in=_mfi_ids_for(principal))
    return qs


def policy_for_fy(fy: str) -> BusinessTransformationPolicy:
    """Return the governed Uganda policy, creating a visible default once."""

    policy = BusinessTransformationPolicy.objects.filter(
        country_code="UG", fy=fy, active=True
    ).first()
    if policy:
        return policy
    policy, _ = BusinessTransformationPolicy.objects.get_or_create(
        country_code="UG",
        fy=fy,
        defaults={"active": True, "created_by": "system"},
    )
    return policy


def _open_case_for_school(school_id: str):
    return TransformationCase.objects.filter(
        school_id=school_id, status__in=OPEN_CASE_STATUSES
    ).first()


@transaction.atomic
def ensure_case_from_verified_ssa(ssa_record_id: str):
    """Converge one verified SSA onto one open case and recommendation set."""

    from apps.audit.services import log as audit_log
    from apps.ssa.models import SsaRecord

    record = (
        SsaRecord.objects.select_related("school")
        .prefetch_related("scores")
        .filter(id=ssa_record_id, verification_status="confirmed")
        .first()
    )
    if record is None:
        return None
    policy = policy_for_fy(record.fy)
    scores = {
        score.intervention: Decimal(str(score.score)) for score in record.scores.all()
    }
    weaknesses: list[tuple[str, Decimal, Decimal]] = []
    financial_score = scores.get(SsaIntervention.FINANCIAL_HEALTH)
    if (
        financial_score is not None
        and financial_score <= policy.financial_health_max_score
    ):
        weaknesses.append(
            (
                SsaIntervention.FINANCIAL_HEALTH,
                financial_score,
                policy.financial_health_max_score,
            )
        )
    government_score = scores.get(SsaIntervention.GOVERNMENT_REQUIREMENT)
    if (
        government_score is not None
        and government_score <= policy.government_requirements_max_score
    ):
        weaknesses.append(
            (
                SsaIntervention.GOVERNMENT_REQUIREMENT,
                government_score,
                policy.government_requirements_max_score,
            )
        )
    if not weaknesses:
        return None

    case = _open_case_for_school(record.school_id)
    if case is None:
        try:
            case = TransformationCase.objects.create(
                school_id=record.school_id,
                status=CaseStatus.RECOMMENDED,
                opened_fy=record.fy,
            )
        except IntegrityError:
            # Concurrent imports/verification events converge through the
            # partial unique constraint rather than creating parallel cases.
            case = _open_case_for_school(record.school_id)
            if case is None:  # pragma: no cover - defensive database anomaly
                raise

    trigger, _ = CaseTrigger.objects.get_or_create(
        trigger_type=TriggerType.VERIFIED_SSA,
        source_id=record.id,
        defaults={
            "case": case,
            "triggered_by": record.verified_by_user_id or record.uploaded_by,
            "source_snapshot": {
                "ssaId": record.id,
                "fy": record.fy,
                "verifiedAt": record.verified_at.isoformat()
                if record.verified_at
                else None,
                "scores": {code: str(value) for code, value in scores.items()},
            },
        },
    )
    created = 0
    for intervention, score, threshold in weaknesses:
        if intervention == SsaIntervention.FINANCIAL_HEALTH:
            recommendations = (
                RecommendationKind.FINANCIAL_HEALTH_TRAINING,
                RecommendationKind.LOAN_READINESS,
            )
        else:
            recommendations = (RecommendationKind.COMPLIANCE_SUPPORT,)
        for kind in recommendations:
            _recommendation, was_created = CaseRecommendation.objects.get_or_create(
                trigger=trigger,
                kind=kind,
                defaults={
                    "case": case,
                    "reason": (
                        f"Verified {SsaIntervention(intervention).label} score "
                        f"{score} is at or below the Uganda FY{record.fy} "
                        f"review threshold of {threshold}."
                    ),
                    "source_intervention": intervention,
                    "source_score": score,
                },
            )
            created += int(was_created)
    if created:
        audit_log(
            action="bt.ssa_recommendations_created",
            subject_kind="TransformationCase",
            subject_id=case.id,
            actor_id=record.verified_by_user_id or record.uploaded_by,
            actor_role=EdifyRole.IMPACT_ASSESSMENT.value,
            payload={
                "schoolId": record.school_id,
                "ssaId": record.id,
                "recommendationsCreated": created,
            },
        )
        _notify_bt_case(case)
    return case


def _notify_bt_case(case: TransformationCase) -> None:
    from apps.accounts.models import User
    from apps.notifications.services import WorkflowNotificationService

    recipients = User.objects.filter(
        is_active=True,
        active_role__in=[
            EdifyRole.BUSINESS_TRANSFORMATION_OFFICER.value,
            EdifyRole.COUNTRY_DIRECTOR.value,
        ],
    )
    WorkflowNotificationService.trigger(
        event_type="bt.case.recommended",
        category="business_transformation",
        priority="medium",
        title="Business Transformation review recommended",
        body=f"{case.school.name} has a verified financial or compliance weakness to triage.",
        context_type="TransformationCase",
        context_id=case.id,
        recipients=recipients,
    )


def scoped_cases(principal):
    role = getattr(principal, "active_role", "")
    qs = TransformationCase.objects.select_related(
        "school", "school__region", "school__district"
    ).prefetch_related("recommendations")
    if role in UGANDA_WIDE_ROLES:
        return qs
    if role in SUMMARY_ONLY_ROLES or role in MFI_ROLES:
        return qs.none()
    from apps.core.scoping import resolve_user_scope

    scope = resolve_user_scope(principal)
    return qs.filter(school_id__in=scope.school_ids)


def scoped_loans(principal):
    """Universal Uganda loan register.

    Every authenticated platform role receives the register. MFI roles remain
    bounded to their governed organization; other platform roles read the
    Uganda-wide transparency view. Mutation is permission-gated separately.
    """

    qs = MfiLoan.objects.select_related(
        "mfi", "school", "school__region", "school__district", "purpose", "case"
    )
    if getattr(principal, "active_role", "") in MFI_ROLES:
        return qs.filter(mfi_id__in=_mfi_ids_for(principal))
    return qs


def scoped_referrals(principal):
    role = getattr(principal, "active_role", "")
    qs = FinanceReferral.objects.select_related(
        "case__school",
        "case__school__region",
        "case__school__district",
        "mfi",
        "purpose",
    )
    if role in UGANDA_WIDE_ROLES:
        return qs
    if role in SUMMARY_ONLY_ROLES:
        return qs.none()
    if role in MFI_ROLES:
        return qs.filter(mfi_id__in=_mfi_ids_for(principal))
    return qs.filter(case__in=scoped_cases(principal))


@transaction.atomic
def triage_case(case_id: str, data: dict, principal):
    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_CASE_MANAGE,
        "Only an authorized Business Transformation or country owner may triage a case.",
    )
    case = scoped_cases(principal).select_for_update().filter(id=case_id).first()
    if case is None:
        raise NotFoundError("Business Transformation case not found.")
    decision = (data.get("decision") or "").strip()
    allowed = {
        "accept": CaseStatus.ACTIVE,
        "financial_support_first": CaseStatus.ACTIVE,
        "refer_to_mfi": CaseStatus.ACTIVE,
        "defer": CaseStatus.DEFERRED,
        "close_not_eligible": CaseStatus.CLOSED,
        "further_assessment": CaseStatus.TRIAGE,
    }
    if decision not in allowed:
        raise BadRequest("Choose a valid triage decision.")
    reason = (data.get("reason") or "").strip()
    if decision in {"defer", "close_not_eligible", "further_assessment"} and not reason:
        raise BadRequest("A reason is required for this decision.")
    case.status = allowed[decision]
    case.triage_decision = decision
    case.triage_reason = reason
    case.triaged_by = _actor_id(principal)
    case.triaged_at = timezone.now()
    case.deferred_until = _date(data.get("deferredUntil"), field="Deferred until")
    if case.status == CaseStatus.CLOSED:
        case.closed_at = timezone.now()
        case.closure_reason = reason
    case.save()
    return serialize_case(case)


@transaction.atomic
def onboard_mfi(data: dict, principal):
    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_MFI_MANAGE,
        "Only an authorized Business Transformation or country owner may onboard an MFI.",
    )
    code = (data.get("code") or "").strip().upper()
    name = (data.get("name") or "").strip()
    if not code or not name:
        raise BadRequest("MFI code and name are required.")
    if MfiOrganization.objects.filter(Q(code=code) | Q(name__iexact=name)).exists():
        raise BadRequest("An MFI with that code or name already exists.")
    mfi = MfiOrganization.objects.create(
        code=code,
        name=name,
        contact_name=(data.get("contactName") or "").strip(),
        contact_email=(data.get("contactEmail") or "").strip(),
        contact_phone=(data.get("contactPhone") or "").strip(),
        data_sharing_agreement_active=bool(data.get("dataSharingAgreementActive")),
        onboarded_by=_actor_id(principal),
        onboarded_at=timezone.now(),
    )
    return serialize_mfi(mfi)


@transaction.atomic
def onboard_mfi_member(data: dict, principal):
    """MFI Admin governs its own loan-officer membership; Edify does not."""

    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_MFI_MEMBER_MANAGE,
        "Only an MFI Partner Administrator may onboard loan officers.",
    )
    from apps.accounts.models import User

    mfi_id = (data.get("mfiId") or "").strip()
    _assert_mfi_scope(principal, mfi_id, admin_only=True)
    user = User.objects.filter(id=data.get("userId"), is_active=True).first()
    if user is None:
        raise BadRequest("Select an active user account for the loan officer.")
    membership, _ = MfiMembership.objects.update_or_create(
        mfi_id=mfi_id,
        user=user,
        defaults={
            "role": MfiMembershipRole.LOAN_OFFICER,
            "officer_reference": (data.get("officerReference") or "").strip(),
            "active": True,
        },
    )
    from apps.audit.services import log as audit_log

    audit_log(
        action="bt.mfi.loan_officer_onboarded",
        subject_kind="MfiMembership",
        subject_id=str(membership.id),
        actor_id=_actor_id(principal),
        actor_role=getattr(principal, "active_role", None),
        payload={"mfi_id": mfi_id, "user_id": str(user.id)},
    )
    return {
        "id": membership.id,
        "mfiId": membership.mfi_id,
        "userId": membership.user_id,
        "role": membership.role,
        "active": membership.active,
    }


@transaction.atomic
def create_referral(data: dict, principal):
    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_REFERRAL_MANAGE,
        "Only an authorized Business Transformation or country owner may refer a school.",
    )
    case = scoped_cases(principal).filter(id=data.get("caseId")).first()
    if case is None:
        raise NotFoundError("Business Transformation case not found.")
    mfi = MfiOrganization.objects.filter(id=data.get("mfiId"), active=True).first()
    purpose = LoanPurpose.objects.filter(id=data.get("purposeId"), active=True).first()
    if mfi is None or purpose is None:
        raise BadRequest("Select an active MFI and governed loan purpose.")
    intended_use = (data.get("intendedUse") or "").strip()
    if not intended_use:
        raise BadRequest("Intended loan use is required.")
    consent_at = _datetime(
        data.get("consentRecordedAt"), field="Consent recorded at", required=True
    )
    referral = FinanceReferral.objects.create(
        case=case,
        mfi=mfi,
        purpose=purpose,
        requested_amount=_decimal(
            data.get("requestedAmount"), field="Requested amount"
        ),
        currency="UGX",
        intended_use=intended_use,
        consent_recorded_at=consent_at,
        status=ReferralStatus.SENT,
        referred_by=_actor_id(principal),
        referred_at=timezone.now(),
    )
    return serialize_referral(referral)


@transaction.atomic
def record_referral_decision(referral_id: str, data: dict, principal):
    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_LOAN_WRITE,
        "Only an authorized MFI Admin or MFI Loan Officer may record "
        "referral decisions.",
    )
    referral = (
        FinanceReferral.objects.select_for_update()
        .select_related("mfi", "case__school", "purpose")
        .filter(id=referral_id)
        .first()
    )
    if referral is None:
        raise NotFoundError("Referral not found.")
    _assert_mfi_scope(principal, referral.mfi_id)
    status = (data.get("status") or "").strip()
    allowed = {
        ReferralStatus.UNDER_ASSESSMENT,
        ReferralStatus.MORE_INFORMATION,
        ReferralStatus.APPROVED,
        ReferralStatus.DECLINED,
        ReferralStatus.WITHDRAWN,
        ReferralStatus.EXPIRED,
    }
    if status not in allowed:
        raise BadRequest("Choose a valid MFI referral decision.")
    referral.status = status
    referral.mfi_decided_by = _actor_id(principal)
    referral.mfi_decided_at = timezone.now()
    referral.decision_reason = (data.get("reason") or "").strip()
    referral.save()
    return serialize_referral(referral)


def _ensure_verification_requirement(loan: MfiLoan):
    policy = policy_for_fy(get_operational_fy(loan.disbursement_date))
    due_date = loan.disbursement_date + timedelta(
        days=policy.loan_use_verification_days
    )
    requirement, _ = LoanVerificationRequirement.objects.get_or_create(
        loan=loan,
        defaults={"due_date": due_date},
    )
    return requirement


@transaction.atomic
def register_or_update_loan(data: dict, principal):
    """Create or update a governed Uganda loan for an authorized owner."""

    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_LOAN_WRITE,
        "Only an authorized MFI Admin or MFI Loan Officer may enter or "
        "update loan facts.",
    )
    external_ref = (data.get("externalLoanReference") or "").strip()
    if not external_ref:
        raise BadRequest("External loan reference is required.")
    referral = (
        FinanceReferral.objects.select_related("case__school", "mfi", "purpose")
        .filter(id=data.get("referralId"))
        .first()
    )
    if referral is None:
        raise BadRequest(
            "A valid Edify referral is required. "
            "Historical portfolio loans must use the governed import workflow."
        )
    if not referral.purpose.active:
        raise BadRequest(
            "The selected referral uses a retired loan purpose. Create a new "
            "referral with an active governed purpose."
        )
    case = referral.case
    purpose = referral.purpose
    mfi_id = str(referral.mfi_id)
    supplied_relations = {
        "caseId": str(case.id),
        "mfiId": str(mfi_id),
        "purposeId": str(purpose.id),
    }
    for field, governed_value in supplied_relations.items():
        supplied_value = data.get(field)
        if supplied_value not in (None, "") and str(supplied_value) != governed_value:
            raise BadRequest(f"{field} does not match the selected referral.")
    _assert_mfi_scope(principal, mfi_id)
    status = (data.get("status") or LoanStatus.PROCESSING).strip()
    if status not in LoanStatus.values:
        raise BadRequest("Unknown loan status.")
    disbursement_date = _date(data.get("disbursementDate"), field="Disbursement date")
    disbursed_amount = _decimal(data.get("disbursedAmount"), field="Disbursed amount")
    if status in DISBURSED_LOAN_STATUSES and (
        disbursement_date is None or disbursed_amount is None
    ):
        raise BadRequest(
            "A disbursed loan requires its confirmed disbursement date and amount."
        )
    loan = (
        MfiLoan.objects.select_for_update()
        .filter(mfi_id=mfi_id, external_loan_reference=external_ref)
        .first()
    )
    was_disbursed = bool(loan and loan.status in DISBURSED_LOAN_STATUSES)
    previous_status = loan.status if loan else ""
    status_reason = (data.get("statusReason") or "").strip()
    if (
        previous_status == LoanStatus.DEFAULTED
        and status == LoanStatus.ACTIVE
        and not status_reason
    ):
        raise BadRequest(
            "Moving a defaulted loan back to Active requires a restructuring "
            "or recovery reason."
        )
    if loan and loan.certified_at:
        raise Forbidden(
            "This loan is certified. Submit an amendment instead of rewriting it."
        )
    if loan and loan.core_identity_locked:
        proposed_identity = {
            "external_loan_reference": external_ref,
            "school_id": str(case.school_id),
            "mfi_id": str(mfi_id),
            "purpose_id": str(purpose.id),
            "approved_amount": _decimal(
                data.get("approvedAmount"), field="Approved amount"
            ),
            "disbursed_amount": disbursed_amount,
            "disbursement_date": disbursement_date,
        }
        changed = [
            field
            for field, proposed in proposed_identity.items()
            if str(getattr(loan, field) or "") != str(proposed or "")
        ]
        if changed:
            raise Forbidden(
                "Salesforce-confirmed loan identity is locked. Submit an audited "
                "amendment request to change: " + ", ".join(changed) + "."
            )
    term_months = None
    if data.get("termMonths") not in (None, ""):
        try:
            term_months = int(data["termMonths"])
        except (TypeError, ValueError) as exc:
            raise BadRequest("Term months must be a whole number.") from exc
        if term_months <= 0:
            raise BadRequest("Term months must be greater than zero.")
    values = {
        "school": case.school,
        "case": case,
        "referral": referral,
        "purpose": purpose,
        "assigned_officer_reference": (
            data.get("assignedOfficerReference") or ""
        ).strip(),
        "requested_amount": _decimal(
            data.get("requestedAmount"), field="Requested amount"
        ),
        "approved_amount": _decimal(
            data.get("approvedAmount"), field="Approved amount"
        ),
        "disbursed_amount": disbursed_amount,
        "currency": "UGX",
        "processing_date": _date(
            data.get("processingDate"), field="Processing date"
        ),
        "approved_at": _datetime(data.get("approvedAt"), field="Approved at"),
        "disbursement_date": disbursement_date,
        "disbursement_confirmed_at": (
            timezone.now() if status in DISBURSED_LOAN_STATUSES else None
        ),
        "term_months": term_months,
        "repayment_frequency": (data.get("repaymentFrequency") or "").strip(),
        "installment_amount": _decimal(
            data.get("installmentAmount"), field="Installment amount"
        ),
        "maturity_date": _date(data.get("maturityDate"), field="Maturity date"),
        "status": status,
        "default_classified_at": _date(
            data.get("defaultClassifiedAt"), field="Default classification date"
        ),
    }
    if status == LoanStatus.DEFAULTED and values["default_classified_at"] is None:
        raise BadRequest("A defaulted loan requires its classification date.")
    if status == LoanStatus.CANCELED and disbursement_date is not None:
        raise BadRequest("A canceled loan cannot have a disbursement date.")
    if loan is None:
        loan = MfiLoan.objects.create(
            mfi_id=mfi_id,
            external_loan_reference=external_ref,
            registered_by=_actor_id(principal),
            submitted_by=_actor_id(principal),
            submitted_at=timezone.now(),
            **values,
        )
        _record_status_change(
            loan,
            LoanStatusDimension.LIFECYCLE,
            "",
            status,
            principal,
            reason="MFI submitted loan record",
        )
        _record_status_change(
            loan,
            LoanStatusDimension.SALESFORCE,
            "",
            SalesforceStatus.PENDING,
            principal,
            reason="Salesforce confirmation required",
        )
    else:
        for field, value in values.items():
            setattr(loan, field, value)
        if loan.salesforce_status == SalesforceStatus.RETURNED:
            _record_status_change(
                loan,
                LoanStatusDimension.SALESFORCE,
                SalesforceStatus.RETURNED,
                SalesforceStatus.PENDING,
                principal,
                reason="MFI corrected and resubmitted the returned loan",
            )
            loan.salesforce_status = SalesforceStatus.PENDING
            loan.submitted_by = _actor_id(principal)
            loan.submitted_at = timezone.now()
        loan.save()
        _record_status_change(
            loan,
            LoanStatusDimension.LIFECYCLE,
            previous_status,
            status,
            principal,
            reason=status_reason,
        )
    if status in DISBURSED_LOAN_STATUSES:
        _ensure_verification_requirement(loan)
        if case.status in {
            CaseStatus.RECOMMENDED,
            CaseStatus.TRIAGE,
            CaseStatus.ACTIVE,
        }:
            case.status = CaseStatus.MONITORING
            case.save(update_fields=["status", "updated_at"])
        if not was_disbursed:
            _notify_disbursement(loan)
    _audit_loan_event(
        "bt.loan.submitted" if not previous_status else "bt.loan.updated",
        loan,
        principal,
        {"lifecycle_status": status, "mfi_id": str(loan.mfi_id)},
    )
    return serialize_loan(loan)


@transaction.atomic
def confirm_salesforce_loan(loan_id: str, data: dict, principal):
    """Record BT's confirmation that an MFI loan exists in Salesforce."""

    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_SALESFORCE_CONFIRM,
        "Only a Business Transformation Officer may confirm Salesforce loan IDs.",
    )
    loan = MfiLoan.objects.select_for_update().filter(id=loan_id).first()
    if loan is None:
        raise NotFoundError("Loan not found.")
    if loan.salesforce_status == SalesforceStatus.RETURNED:
        raise BadRequest("The MFI must correct and resubmit this returned loan first.")
    if not loan.mfi.active or not loan.submitted_at:
        raise BadRequest("The loan must be submitted by an active authorized MFI.")
    if not all(
        [
            loan.school_id,
            loan.mfi_id,
            loan.purpose_id,
            loan.external_loan_reference,
        ]
    ):
        raise BadRequest("Required loan identity information is incomplete.")
    if loan.status in DISBURSED_LOAN_STATUSES and (
        loan.disbursed_amount is None or loan.disbursement_date is None
    ):
        raise BadRequest("Disbursed loan information is incomplete.")
    salesforce_id = (data.get("salesforceLoanId") or "").strip()
    if not SALESFORCE_ID_PATTERN.fullmatch(salesforce_id):
        raise BadRequest(
            "Salesforce Loan ID must use the format Loan-<number>, for example "
            "Loan-19650."
        )
    if (
        MfiLoan.objects.filter(salesforce_loan_id=salesforce_id)
        .exclude(id=loan.id)
        .exists()
    ):
        raise BadRequest("That Salesforce Loan ID is already linked to another loan.")
    previous_status = loan.salesforce_status
    loan.salesforce_loan_id = salesforce_id
    loan.salesforce_status = SalesforceStatus.CONFIRMED
    # BT supplies one fact only: the Salesforce Loan ID. The platform captures
    # the date, actor and timestamp automatically so the confirmation cannot
    # quietly become a second loan-editing surface.
    loan.salesforce_entry_date = timezone.localdate()
    loan.salesforce_confirmation_note = ""
    loan.salesforce_confirmed_by = _actor_id(principal)
    loan.salesforce_confirmed_at = timezone.now()
    try:
        with transaction.atomic():
            loan.save(
                update_fields=[
                    "salesforce_loan_id",
                    "salesforce_status",
                    "salesforce_entry_date",
                    "salesforce_confirmation_note",
                    "salesforce_confirmed_by",
                    "salesforce_confirmed_at",
                    "updated_at",
                ]
            )
    except IntegrityError as exc:
        raise BadRequest(
            "That Salesforce Loan ID is already linked to another loan."
        ) from exc
    _record_status_change(
        loan,
        LoanStatusDimension.SALESFORCE,
        previous_status,
        SalesforceStatus.CONFIRMED,
        principal,
        reason="Salesforce entry confirmed",
    )
    _audit_loan_event(
        "bt.loan.salesforce_confirmed",
        loan,
        principal,
        {
            "salesforce_loan_id": salesforce_id,
            "salesforce_entry_date": loan.salesforce_entry_date.isoformat(),
        },
    )
    _notify_salesforce_confirmation(loan)
    return serialize_loan(loan)


@transaction.atomic
def return_salesforce_loan(loan_id: str, data: dict, principal):
    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_CASE_MANAGE,
        "Only an authorized country programme owner may return a loan to its MFI.",
    )
    loan = (
        MfiLoan.objects.select_for_update()
        .select_related("mfi", "school")
        .filter(id=loan_id)
        .first()
    )
    if loan is None:
        raise NotFoundError("Loan not found.")
    reason = (data.get("returnReason") or "").strip()
    if reason not in SALESFORCE_RETURN_REASONS:
        raise BadRequest("Choose a valid return reason.")
    note = (data.get("returnNote") or "").strip()
    if reason == "other" and not note:
        raise BadRequest("Explain the other return reason.")
    previous_status = loan.salesforce_status
    loan.salesforce_status = SalesforceStatus.RETURNED
    loan.salesforce_return_reason = reason
    loan.salesforce_return_note = note
    loan.salesforce_returned_by = _actor_id(principal)
    loan.salesforce_returned_at = timezone.now()
    loan.save(
        update_fields=[
            "salesforce_status",
            "salesforce_return_reason",
            "salesforce_return_note",
            "salesforce_returned_by",
            "salesforce_returned_at",
            "updated_at",
        ]
    )
    explanation = SALESFORCE_RETURN_REASONS[reason]
    _record_status_change(
        loan,
        LoanStatusDimension.SALESFORCE,
        previous_status,
        SalesforceStatus.RETURNED,
        principal,
        reason=f"{explanation}: {note}" if note else explanation,
    )
    _audit_loan_event(
        "bt.loan.returned_to_mfi",
        loan,
        principal,
        {"reason": reason, "note": note},
    )
    _notify_mfi_return(loan, explanation, note)
    return serialize_loan(loan)


@transaction.atomic
def validate_loan_by_ia(loan_id: str, data: dict, principal):
    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_IA_VALIDATE,
        "Only Impact Assessment may validate a submitted loan record.",
    )
    loan = MfiLoan.objects.select_for_update().filter(id=loan_id).first()
    if loan is None:
        raise NotFoundError("Loan not found.")
    if loan.salesforce_status != SalesforceStatus.CONFIRMED:
        raise BadRequest("Salesforce confirmation is required before IA validation.")
    decision = (data.get("decision") or "").strip()
    if decision not in {IAValidationStatus.VERIFIED, IAValidationStatus.RETURNED}:
        raise BadRequest("Choose Verify or Return.")
    reason = (data.get("reason") or "").strip()
    if decision == IAValidationStatus.RETURNED and not reason:
        raise BadRequest("A return reason is required.")
    previous_status = loan.ia_validation_status
    loan.ia_validation_status = decision
    loan.ia_validated_by = _actor_id(principal)
    loan.ia_validated_at = timezone.now()
    loan.ia_return_reason = reason if decision == IAValidationStatus.RETURNED else ""
    loan.save(
        update_fields=[
            "ia_validation_status",
            "ia_validated_by",
            "ia_validated_at",
            "ia_return_reason",
            "updated_at",
        ]
    )
    _record_status_change(
        loan,
        LoanStatusDimension.IA_VALIDATION,
        previous_status,
        decision,
        principal,
        reason=reason or "IA verified the programme record",
    )
    _audit_loan_event(
        "bt.loan.ia_verified"
        if decision == IAValidationStatus.VERIFIED
        else "bt.loan.ia_returned",
        loan,
        principal,
        {"decision": decision, "reason": reason},
    )
    if decision == IAValidationStatus.RETURNED:
        _notify_ia_return(loan, reason)
    return serialize_loan(loan)


def _notify_salesforce_confirmation(loan: MfiLoan) -> None:
    from apps.accounts.models import User
    from apps.notifications.services import WorkflowNotificationService

    recipients = User.objects.filter(
        Q(id__in=loan.mfi.memberships.filter(active=True).values("user_id"))
        | Q(active_role=EdifyRole.IMPACT_ASSESSMENT.value),
        is_active=True,
    )
    WorkflowNotificationService.trigger(
        event_type="bt.loan.salesforce_confirmed",
        category="business_transformation",
        priority="medium",
        title="Salesforce confirmation complete",
        body=f"{loan.school.name} · {loan.salesforce_loan_id} is ready for IA validation.",
        context_type="MfiLoan",
        context_id=loan.id,
        recipients=recipients,
    )


def _notify_mfi_return(loan: MfiLoan, reason: str, note: str) -> None:
    from apps.accounts.models import User
    from apps.notifications.services import WorkflowNotificationService

    recipients = User.objects.filter(
        id__in=loan.mfi.memberships.filter(active=True).values("user_id"),
        is_active=True,
    )
    WorkflowNotificationService.trigger(
        event_type="bt.loan.returned_to_mfi",
        category="business_transformation",
        priority="high",
        title="Loan record returned for correction",
        body=f"{loan.school.name} · {reason}{': ' + note if note else ''}",
        context_type="MfiLoan",
        context_id=loan.id,
        recipients=recipients,
    )


def _notify_ia_return(loan: MfiLoan, reason: str) -> None:
    from apps.accounts.models import User
    from apps.notifications.services import WorkflowNotificationService

    recipients = User.objects.filter(
        Q(id__in=loan.mfi.memberships.filter(active=True).values("user_id"))
        | Q(active_role=EdifyRole.BUSINESS_TRANSFORMATION_OFFICER.value),
        is_active=True,
    )
    WorkflowNotificationService.trigger(
        event_type="bt.loan.ia_returned",
        category="business_transformation",
        priority="high",
        title="IA returned a loan record",
        body=f"{loan.school.name} · {reason}",
        context_type="MfiLoan",
        context_id=loan.id,
        recipients=recipients,
    )


def _notify_disbursement(loan: MfiLoan) -> None:
    from apps.accounts.models import User
    from apps.notifications.services import WorkflowNotificationService

    recipients = User.objects.filter(
        is_active=True,
        active_role__in=[
            EdifyRole.BUSINESS_TRANSFORMATION_OFFICER.value,
            EdifyRole.COUNTRY_DIRECTOR.value,
        ],
    )
    WorkflowNotificationService.trigger(
        event_type="bt.loan.disbursed",
        category="business_transformation",
        priority="high",
        title="MFI disbursement confirmed",
        body=(
            f"{loan.mfi.name} confirmed a {loan.purpose.label} loan for "
            f"{loan.school.name}; loan-use verification is now required."
        ),
        context_type="MfiLoan",
        context_id=loan.id,
        recipients=recipients,
    )


def _repayment_status(days: int, supplied: str = "") -> str:
    if supplied == RepaymentStatus.RESTRUCTURED:
        return supplied
    if days > 90:
        return RepaymentStatus.OVERDUE_90_PLUS
    if days > 30:
        return RepaymentStatus.OVERDUE_31_90
    if days > 0:
        return RepaymentStatus.OVERDUE_1_30
    return RepaymentStatus.CURRENT


@transaction.atomic
def add_repayment_snapshot(loan_id: str, data: dict, principal):
    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_REPAYMENT_WRITE,
        "Only an authorized MFI Admin or MFI Loan Officer may update "
        "repayment data.",
    )
    loan = MfiLoan.objects.select_for_update().filter(id=loan_id).first()
    if loan is None:
        raise NotFoundError("Loan not found.")
    _assert_mfi_scope(principal, loan.mfi_id)
    if loan.status not in DISBURSED_LOAN_STATUSES:
        raise BadRequest("Repayment data can be added only after disbursement.")
    as_of = _date(data.get("asOfDate"), field="As-of date", required=True)
    if as_of > timezone.localdate():
        raise BadRequest("As-of date cannot be in the future.")
    try:
        days = int(data.get("daysInArrears") or 0)
    except (TypeError, ValueError) as exc:
        raise BadRequest("Days in arrears must be a whole number.") from exc
    if days < 0:
        raise BadRequest("Days in arrears cannot be negative.")
    supplied_status = (data.get("status") or "").strip()
    status = _repayment_status(days, supplied_status)
    outstanding = _nonnegative_decimal(
        data.get("outstandingAmount"), field="Outstanding amount", required=True
    )
    lifecycle_status = (data.get("loanStatus") or loan.status).strip()
    if lifecycle_status not in LoanStatus.values:
        raise BadRequest("Unknown loan lifecycle status.")
    if lifecycle_status == LoanStatus.REPAID and outstanding != 0:
        raise BadRequest("A repaid loan must have a zero outstanding balance.")
    if lifecycle_status == LoanStatus.DEFAULTED and not data.get(
        "defaultClassifiedAt"
    ) and not loan.default_classified_at:
        raise BadRequest("A defaulted loan requires its classification date.")
    previous_lifecycle = loan.status
    status_reason = (data.get("statusReason") or "").strip()
    if (
        previous_lifecycle == LoanStatus.DEFAULTED
        and lifecycle_status == LoanStatus.ACTIVE
        and not status_reason
    ):
        raise BadRequest(
            "Moving a defaulted loan back to Active requires a restructuring "
            "or recovery reason."
        )
    snapshot, created = RepaymentSnapshot.objects.get_or_create(
        loan=loan,
        as_of_date=as_of,
        defaults={
            "reporting_month": _reporting_month(
                data.get("reportingMonth"), fallback=as_of
            ),
            "amount_due_during_period": _nonnegative_decimal(
                data.get("amountDueDuringPeriod", data.get("amountCurrentlyDue", 0)),
                field="Amount due during period",
                required=True,
            ),
            "amount_paid_during_period": _nonnegative_decimal(
                data.get("amountPaidDuringPeriod", 0),
                field="Amount paid during period",
                required=True,
            ),
            "principal_repaid": _nonnegative_decimal(
                data.get("principalRepaid", 0), field="Principal repaid", required=True
            ),
            "outstanding_amount": outstanding,
            "amount_currently_due": _nonnegative_decimal(
                data.get("amountCurrentlyDue", 0),
                field="Amount currently due",
                required=True,
            ),
            "amount_overdue": _nonnegative_decimal(
                data.get("amountOverdue", 0), field="Amount overdue", required=True
            ),
            "days_in_arrears": days,
            "next_payment_date": _date(
                data.get("nextPaymentDate"), field="Next payment date"
            ),
            "last_payment_date": _date(
                data.get("lastPaymentDate"), field="Last payment date"
            ),
            "status": status,
            "restructuring_status": (data.get("restructuringStatus") or "").strip(),
            "submitted_by": _actor_id(principal),
        },
    )
    if not created:
        raise BadRequest("A repayment snapshot already exists for that date.")
    loan.last_repayment_data_date = as_of
    loan.status = lifecycle_status
    if lifecycle_status == LoanStatus.DEFAULTED and not loan.default_classified_at:
        loan.default_classified_at = _date(
            data.get("defaultClassifiedAt"),
            field="Default classification date",
            required=True,
        )
    loan.save(
        update_fields=[
            "last_repayment_data_date",
            "status",
            "default_classified_at",
            "updated_at",
        ]
    )
    _record_status_change(
        loan,
        LoanStatusDimension.REPAYMENT,
        "",
        status,
        principal,
        reason=f"Repayment snapshot as at {as_of.isoformat()}",
    )
    _record_status_change(
        loan,
        LoanStatusDimension.LIFECYCLE,
        previous_lifecycle,
        lifecycle_status,
        principal,
        reason=status_reason,
    )
    return serialize_snapshot(snapshot)


@transaction.atomic
def link_verification_activity(requirement_id: str, activity_id: str, principal):
    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_SCHOOL_SUPPORT_MANAGE,
        "Only the responsible CCEO or Program Lead may link verification work.",
    )
    if getattr(principal, "active_role", "") not in {
        EdifyRole.CCEO.value,
        EdifyRole.COUNTRY_PROGRAM_LEAD.value,
    }:
        raise Forbidden(
            "Only the responsible CCEO or Program Lead may link verification work."
        )
    from apps.activities.models import Activity
    from apps.core.scoping import assert_may_plan_school

    requirement = (
        LoanVerificationRequirement.objects.select_for_update()
        .select_related("loan__case", "loan__school")
        .filter(id=requirement_id)
        .first()
    )
    activity = (
        Activity.objects.select_related("catalogue_item").filter(id=activity_id).first()
    )
    if requirement is None or activity is None:
        raise NotFoundError("Verification requirement or activity not found.")
    assert_may_plan_school(principal, requirement.loan.school)
    if activity.school_id != requirement.loan.school_id:
        raise BadRequest("Verification activity must belong to the financed school.")
    if (
        activity.catalogue_item is None
        or activity.catalogue_item.stable_code != "BT_UG_LOAN_USE_VERIFICATION"
    ):
        raise BadRequest(
            "Select the governed Uganda Loan-Use Verification Visit activity."
        )
    BusinessTransformationActivityLink.objects.get_or_create(
        activity=activity,
        defaults={
            "case": requirement.loan.case,
            "loan": requirement.loan,
            "purpose": RecommendationKind.LOAN_USE_VERIFICATION,
        },
    )
    requirement.activity = activity
    requirement.assigned_by = _actor_id(principal)
    requirement.status = VerificationRequirementStatus.SCHEDULED
    requirement.save()
    return serialize_requirement(requirement)


@transaction.atomic
def record_loan_use_result(requirement_id: str, data: dict, principal):
    from .models import LoanUseFinding

    requirement = (
        LoanVerificationRequirement.objects.select_for_update()
        .filter(id=requirement_id)
        .first()
    )
    if requirement is None or requirement.activity_id is None:
        raise NotFoundError("Scheduled loan-use verification not found.")
    actor_ids = {
        _actor_id(principal),
        str(getattr(principal, "staff_profile_id", "") or ""),
    }
    if requirement.activity.responsible_staff_id not in actor_ids:
        raise Forbidden("Only the assigned field officer may record this finding.")
    finding = (data.get("finding") or "").strip()
    if finding not in LoanUseFinding.values:
        raise BadRequest("Choose a valid loan-use finding.")
    result, _ = LoanUseResult.objects.update_or_create(
        requirement=requirement,
        defaults={
            "finding": finding,
            "notes": (data.get("notes") or "").strip(),
            "edtech_asset_operational": data.get("edtechAssetOperational"),
            "recorded_by": _actor_id(principal),
            "verification_status": "provisional",
            "ia_verified_at": None,
        },
    )
    requirement.status = VerificationRequirementStatus.AWAITING_VERIFICATION
    requirement.save(update_fields=["status", "updated_at"])
    return serialize_loan_use_result(result)


@transaction.atomic
def project_activity_state(activity_id: str):
    """Project Activity authority into BT state; safe to replay."""

    from apps.activities.models import Activity

    activity = Activity.objects.filter(id=activity_id).first()
    if activity is None:
        return None
    requirement = (
        LoanVerificationRequirement.objects.select_for_update()
        .filter(activity_id=activity_id)
        .first()
    )
    if requirement is None:
        return None
    result = LoanUseResult.objects.filter(requirement=requirement).first()
    if activity.status in {"ia_verified", "accountant_confirmed", "closed"}:
        if result is None:
            # Structured finding is required; IA verification of the generic
            # activity cannot manufacture a loan-use conclusion.
            requirement.status = VerificationRequirementStatus.AWAITING_VERIFICATION
            requirement.save(update_fields=["status", "updated_at"])
            return requirement
        result.verification_status = "confirmed"
        result.ia_verified_at = activity.ia_confirmed_at or timezone.now()
        result.save(
            update_fields=["verification_status", "ia_verified_at", "updated_at"]
        )
        requirement.status = VerificationRequirementStatus.VERIFIED
        requirement.verified_at = result.ia_verified_at
    elif activity.status in {"returned", "returned_by_ia", "returned_by_pl"}:
        if result:
            result.verification_status = "provisional"
            result.ia_verified_at = None
            result.save(
                update_fields=["verification_status", "ia_verified_at", "updated_at"]
            )
        requirement.status = VerificationRequirementStatus.AWAITING_VERIFICATION
        requirement.verified_at = None
    else:
        return requirement
    requirement.save(update_fields=["status", "verified_at", "updated_at"])
    return requirement


def filter_loans(qs, filters: dict):
    if filters.get("status"):
        qs = qs.filter(status=filters["status"])
    if filters.get("mfi"):
        qs = qs.filter(mfi_id=filters["mfi"])
    if filters.get("region"):
        qs = qs.filter(school__region_id=filters["region"])
    if filters.get("district"):
        qs = qs.filter(school__district_id=filters["district"])
    if filters.get("school"):
        qs = qs.filter(school_id=filters["school"])
    if filters.get("purpose"):
        qs = qs.filter(purpose_id=filters["purpose"])
    if filters.get("edtech") == "yes":
        qs = qs.filter(purpose__is_edtech=True)
    elif filters.get("edtech") == "no":
        qs = qs.filter(purpose__is_edtech=False)
    if filters.get("salesforce_status"):
        qs = qs.filter(salesforce_status=filters["salesforce_status"])
    if filters.get("ia_status"):
        qs = qs.filter(ia_validation_status=filters["ia_status"])
    if filters.get("impact_status"):
        qs = qs.filter(impact_status=filters["impact_status"])
    if filters.get("repayment_health"):
        latest_health = (
            RepaymentSnapshot.objects.filter(loan_id=OuterRef("pk"))
            .order_by("-as_of_date", "-created_at")
            .values("status")[:1]
        )
        qs = qs.annotate(_filter_repayment_health=Subquery(latest_health)).filter(
            _filter_repayment_health=filters["repayment_health"]
        )
    if filters.get("q"):
        term = filters["q"]
        qs = qs.filter(
            Q(school__name__icontains=term)
            | Q(school__school_id__icontains=term)
            | Q(external_loan_reference__icontains=term)
            | Q(salesforce_loan_id__icontains=term)
        )
    return qs


def _selected_period_bounds(fy: str, filters: dict):
    period_type = filters.get("period_type") or "fy"
    if period_type == "quarter" and filters.get("quarter") in {
        "Q1",
        "Q2",
        "Q3",
        "Q4",
    }:
        return get_quarter_date_range(fy, filters["quarter"])
    if period_type == "month":
        try:
            month = int(filters.get("month") or 0)
        except (TypeError, ValueError):
            month = 0
        if 1 <= month <= 12:
            return get_month_date_range(fy, month)
    if period_type == "custom":
        start = parse_date(filters.get("custom_from") or "")
        end = parse_date(filters.get("custom_to") or "")
        if start and end and start <= end:
            tz = timezone.get_current_timezone()
            return (
                timezone.make_aware(datetime.combine(start, time.min), tz),
                timezone.make_aware(
                    datetime.combine(end + timedelta(days=1), time.min), tz
                ),
            )
    return get_fy_date_range(fy)


def lending_partner_dashboard(principal, filters: dict) -> list[dict]:
    """One-query lending-partner rollup for the governed loan register."""

    latest_repayment = RepaymentSnapshot.objects.filter(loan_id=OuterRef("pk")).order_by(
        "-as_of_date", "-created_at"
    )
    rows = list(
        filter_loans(scoped_loans(principal), filters)
        .annotate(
            latest_repayment_health=Subquery(latest_repayment.values("status")[:1])
        )
        .values("mfi_id", "mfi__name")
        .annotate(
            loan_count=Count("id"),
            disbursed_loans=Count(
                "id", filter=Q(status__in=DISBURSED_LOAN_STATUSES)
            ),
            disbursed_value=Sum(
                "disbursed_amount", filter=Q(status__in=DISBURSED_LOAN_STATUSES)
            ),
            schools_impacted=Count(
                "school_id",
                distinct=True,
                filter=Q(status__in=DISBURSED_LOAN_STATUSES),
            ),
            salesforce_confirmed=Count(
                "id", filter=Q(salesforce_status=SalesforceStatus.CONFIRMED)
            ),
            at_risk=Count(
                "id",
                filter=Q(
                    latest_repayment_health__in=[
                        RepaymentStatus.OVERDUE_31_90,
                        RepaymentStatus.OVERDUE_90_PLUS,
                    ]
                ) | Q(status=LoanStatus.DEFAULTED),
            ),
            latest_repayment_update=Max("last_repayment_data_date"),
        )
        .order_by("mfi__name")
    )
    for row in rows:
        row["disbursed_value"] = row["disbursed_value"] or Decimal("0")
        row["salesforce_pending"] = (
            row["loan_count"] - row["salesforce_confirmed"]
        )
        row["salesforce_coverage_pct"] = (
            round(row["salesforce_confirmed"] / row["loan_count"] * 100, 1)
            if row["loan_count"]
            else None
        )
    return rows


def loan_export_rows(principal, filters: dict):
    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_EXPORT,
        "Your active role cannot export the Uganda loan register.",
    )
    return filter_loans(scoped_loans(principal), filters).order_by(
        "mfi__name", "school__name", "external_loan_reference"
    )


def portfolio_metrics(principal, *, fy: str | None = None, filters=None) -> dict:
    from apps.schools.models import School

    fy = fy or get_operational_fy()
    filters = filters or {}
    loans = filter_loans(scoped_loans(principal), filters)
    salesforce = loans.aggregate(
        records=Count("id"),
        confirmed=Count("id", filter=Q(salesforce_status=SalesforceStatus.CONFIRMED)),
    )
    fy_start, fy_end = _selected_period_bounds(fy, filters)
    disbursed = loans.filter(
        disbursement_confirmed_at__isnull=False,
        disbursement_date__gte=fy_start.date(),
        disbursement_date__lt=fy_end.date(),
    )
    headline = disbursed.aggregate(
        count=Count("id"),
        value=Sum("disbursed_amount"),
        schools=Count("school_id", distinct=True),
        edtech=Count("id", filter=Q(purpose__is_edtech=True)),
    )
    impacted_schools = School.objects.filter(
        id__in=disbursed.order_by().values("school_id")
    )
    impact = impacted_schools.aggregate(
        students=Sum("enrollment", filter=Q(enrollment__gt=0)),
        schools_with_enrollment=Count("id", filter=Q(enrollment__gt=0)),
        schools_missing_enrollment=Count(
            "id", filter=Q(enrollment__isnull=True) | Q(enrollment__lte=0)
        ),
    )
    due = LoanVerificationRequirement.objects.filter(
        loan__in=loans, due_date__lte=timezone.localdate()
    )
    verified = due.filter(status=VerificationRequirementStatus.VERIFIED).count()
    latest_status = (
        RepaymentSnapshot.objects.filter(loan_id=OuterRef("pk"))
        .order_by("-as_of_date", "-created_at")
        .values("status")[:1]
    )
    latest_outstanding = (
        RepaymentSnapshot.objects.filter(loan_id=OuterRef("pk"))
        .order_by("-as_of_date", "-created_at")
        .values("outstanding_amount")[:1]
    )
    latest_overdue = (
        RepaymentSnapshot.objects.filter(loan_id=OuterRef("pk"))
        .order_by("-as_of_date", "-created_at")
        .values("amount_overdue")[:1]
    )
    positioned = loans.annotate(
        latest_repayment_status=Subquery(latest_status),
        latest_outstanding_amount=Subquery(latest_outstanding),
        latest_overdue_amount=Subquery(latest_overdue),
    )
    par30 = positioned.filter(
        latest_repayment_status__in=[
            RepaymentStatus.OVERDUE_31_90,
            RepaymentStatus.OVERDUE_90_PLUS,
        ]
    ).count()
    position = positioned.aggregate(
        active_portfolio=Sum(
            "latest_outstanding_amount",
            filter=Q(status__in=[LoanStatus.DISBURSED, LoanStatus.ACTIVE]),
        ),
        amount_overdue=Sum("latest_overdue_amount"),
        defaulted_portfolio=Sum(
            "latest_outstanding_amount", filter=Q(status=LoanStatus.DEFAULTED)
        ),
    )
    period_repaid = RepaymentSnapshot.objects.filter(
        loan__in=loans,
        as_of_date__gte=fy_start.date(),
        as_of_date__lt=fy_end.date(),
    ).aggregate(value=Sum("amount_paid_during_period"))["value"] or Decimal("0")
    positive_impact = loans.filter(
        impact_status__in=[
            LoanImpactStatus.STRONG_POSITIVE,
            LoanImpactStatus.POSITIVE,
        ]
    ).count()
    assessed_impact = loans.exclude(
        impact_status__in=[
            LoanImpactStatus.NOT_DUE,
            LoanImpactStatus.BASELINE_REQUIRED,
            LoanImpactStatus.DUE,
            LoanImpactStatus.UNDER_REVIEW,
        ]
    ).count()
    total = headline["count"] or 0
    edtech = headline["edtech"] or 0
    role = getattr(principal, "active_role", "")
    if role in SUMMARY_ONLY_ROLES:
        active_cases = TransformationCase.objects.filter(
            status__in=[
                CaseStatus.RECOMMENDED,
                CaseStatus.TRIAGE,
                CaseStatus.ACTIVE,
                CaseStatus.MONITORING,
            ]
        ).count()
    else:
        active_cases = (
            scoped_cases(principal)
            .filter(
                status__in=[
                    CaseStatus.RECOMMENDED,
                    CaseStatus.TRIAGE,
                    CaseStatus.ACTIVE,
                    CaseStatus.MONITORING,
                ]
            )
            .count()
        )
    schools_impacted = headline["schools"] or 0
    schools_with_enrollment = impact["schools_with_enrollment"] or 0
    students_reached = impact["students"] or 0
    loan_records = salesforce["records"] or 0
    salesforce_confirmed = salesforce["confirmed"] or 0
    return {
        "fy": fy,
        "loansDisbursed": total,
        "newLoans": loans.filter(
            submitted_at__gte=fy_start, submitted_at__lt=fy_end
        ).count(),
        "valueDisbursed": headline["value"] or Decimal("0"),
        "activePortfolioValue": position["active_portfolio"] or Decimal("0"),
        "repaidAmount": period_repaid,
        "amountOverdue": position["amount_overdue"] or Decimal("0"),
        "defaultedPortfolio": position["defaulted_portfolio"] or Decimal("0"),
        "schoolsFinanced": schools_impacted,
        "schoolsImpacted": schools_impacted,
        "studentsReached": students_reached,
        "schoolsWithEnrollment": schools_with_enrollment,
        "schoolsMissingEnrollment": impact["schools_missing_enrollment"] or 0,
        "enrollmentCoveragePct": (
            round(schools_with_enrollment / schools_impacted * 100, 1)
            if schools_impacted
            else None
        ),
        "edtechLoans": edtech,
        "edtechPct": round(edtech / total * 100, 1) if total else None,
        "verificationDue": due.count(),
        "verificationVerified": verified,
        "verificationPct": round(verified / due.count() * 100, 1)
        if due.exists()
        else None,
        "portfolioAtRisk30Count": par30,
        "positiveImpactCount": positive_impact,
        "impactAssessedCount": assessed_impact,
        "positiveImpactPct": (
            round(positive_impact / assessed_impact * 100, 1)
            if assessed_impact
            else None
        ),
        "loanRecords": loan_records,
        "salesforceConfirmed": salesforce_confirmed,
        "salesforcePending": loan_records - salesforce_confirmed,
        "salesforceCoveragePct": (
            round(salesforce_confirmed / loan_records * 100, 1)
            if loan_records
            else None
        ),
        "activeCases": active_cases,
    }


def _portfolio_kpi_items(metrics: dict, fy: str) -> list[dict]:
    """Project governed portfolio metrics into the shared KPI-strip contract.

    Every tile binds a registry metric (apps.core.metrics) so the label,
    unit, formatting, and definition live in one place; icon, variant, and
    helper are presentation and ride along afterwards, the same way My
    Plan's strip attaches them.
    """

    measured = MetricValue.measured
    tiles = [
        (
            render_metric("bt_new_loans", measured(metrics["newLoans"])),
            f"Submitted in selected FY {fy} period",
            "currency",
            "primary",
        ),
        (
            render_metric(
                "bt_value_disbursed", measured(float(metrics["valueDisbursed"]))
            ),
            "MFI-confirmed UGX",
            "currency",
            "info",
        ),
        (
            render_metric("bt_schools_financed", measured(metrics["schoolsImpacted"])),
            "Unique financed schools",
            "school",
            "success",
        ),
        (
            render_metric(
                "bt_active_portfolio",
                measured(float(metrics["activePortfolioValue"])),
            ),
            "Latest MFI-reported outstanding",
            "chart",
            "info",
        ),
        (
            render_metric("bt_repaid_amount", measured(float(metrics["repaidAmount"]))),
            "Paid in selected period",
            "currency",
            "success",
        ),
        (
            render_metric(
                "bt_amount_overdue", measured(float(metrics["amountOverdue"]))
            ),
            "Latest portfolio position",
            "warning",
            "danger" if metrics["amountOverdue"] else "neutral",
        ),
        (
            render_metric(
                "bt_defaulted_portfolio",
                measured(float(metrics["defaultedPortfolio"])),
            ),
            "Outstanding on defaulted loans",
            "warning",
            "danger" if metrics["defaultedPortfolio"] else "neutral",
        ),
        (
            render_metric(
                "bt_edtech_share",
                MetricValue.ratio(metrics["edtechLoans"], metrics["loansDisbursed"]),
            ),
            f"{metrics['edtechLoans']} disbursements",
            "chart",
            "info" if metrics["edtechPct"] is not None else "neutral",
        ),
        (
            render_metric(
                "bt_use_verified",
                MetricValue.ratio(
                    metrics["verificationVerified"], metrics["verificationDue"]
                ),
            ),
            f"{metrics['verificationVerified']} of {metrics['verificationDue']} due",
            "shield",
            "success" if metrics["verificationPct"] is not None else "neutral",
        ),
        (
            render_metric(
                "bt_salesforce_backlog", measured(metrics["salesforcePending"])
            ),
            f"{metrics['salesforceConfirmed']} confirmed",
            "warning",
            "warning" if metrics["salesforcePending"] else "success",
        ),
        (
            render_metric(
                "bt_positive_impact",
                MetricValue.ratio(
                    metrics["positiveImpactCount"], metrics["impactAssessedCount"]
                ),
            ),
            f"{metrics['positiveImpactCount']} of "
            f"{metrics['impactAssessedCount']} assessed",
            "chart",
            "success" if metrics["positiveImpactPct"] is not None else "neutral",
        ),
    ]
    items = render_strip([tile for tile, _helper, _icon, _variant in tiles])
    for item, (_tile, helper, icon, variant) in zip(items, tiles):
        item["helper"] = helper
        item["icon"] = icon
        item["variant"] = variant
    return items


def workspace_context(principal, filters: dict) -> dict:
    fy = filters.get("fy") or get_operational_fy()
    filters = {**filters, "fy": fy}
    cases = scoped_cases(principal)
    if filters.get("case_status"):
        cases = cases.filter(status=filters["case_status"])
    if filters.get("region"):
        cases = cases.filter(school__region_id=filters["region"])
    if filters.get("district"):
        cases = cases.filter(school__district_id=filters["district"])
    if filters.get("q"):
        cases = cases.filter(
            Q(school__name__icontains=filters["q"])
            | Q(school__school_id__icontains=filters["q"])
        )
    loans = filter_loans(scoped_loans(principal), filters)
    referrals = scoped_referrals(principal)
    if filters.get("mfi"):
        referrals = referrals.filter(mfi_id=filters["mfi"])
    if filters.get("region"):
        referrals = referrals.filter(case__school__region_id=filters["region"])
    if filters.get("district"):
        referrals = referrals.filter(case__school__district_id=filters["district"])
    if filters.get("q"):
        referrals = referrals.filter(
            Q(case__school__name__icontains=filters["q"])
            | Q(case__school__school_id__icontains=filters["q"])
        )
    summary_only = getattr(principal, "active_role", "") in SUMMARY_ONLY_ROLES
    if summary_only:
        # Regional oversight is aggregate-only. The metrics above execute from
        # the governed ledger, but no school, reference, or loan row is exposed.
        loans = loans.none()
        referrals = referrals.none()
    from apps.geography.models import District, Region

    metrics = portfolio_metrics(principal, fy=fy, filters=filters)

    return {
        "fy": fy,
        "filters": filters,
        "metrics": metrics,
        "kpi_strip_items": _portfolio_kpi_items(metrics, fy),
        "active_cases_label": (
            f"{metrics['activeCases']} active "
            f"case{'' if metrics['activeCases'] == 1 else 's'}"
        ),
        "cases": cases[:50],
        "loans": loans[:100],
        "referrals": referrals[:100],
        "mfis": scoped_mfis(principal),
        "regions": Region.objects.order_by("name"),
        "districts": District.objects.select_related("region").order_by("name"),
        "case_statuses": CaseStatus.choices,
        "loan_statuses": LoanStatus.choices,
        "summary_only": summary_only,
        "mfi_user": getattr(principal, "active_role", "") in MFI_ROLES,
        "can_manage_cases": has_permission(
            principal, Permission.BUSINESS_TRANSFORMATION_CASE_MANAGE.value
        ),
        "can_manage_mfis": has_permission(
            principal, Permission.BUSINESS_TRANSFORMATION_MFI_MANAGE.value
        ),
        "can_write_loans": has_permission(
            principal, Permission.BUSINESS_TRANSFORMATION_LOAN_WRITE.value
        ),
    }


_PORTFOLIO_PAGE_SIZES = (10, 20, 50)
_DELIVERED_ACTIVITY_STATUSES = {
    "completed",
    "ia_verified",
    "accountant_confirmed",
    "closed",
}
_OPEN_SUPPORT_STATUSES = {
    "planned",
    "scheduled",
    "assigned_to_partner",
    "partner_scheduled",
    "in_progress",
    "completion_started",
    "evidence_uploaded",
    "evidence_accepted",
    "salesforce_id_required",
    "submitted_to_pl",
    "awaiting_ia_verification",
}


def _portfolio_performance(scores: list[tuple]) -> dict:
    """Build transparent baseline/latest movement from confirmed SSA scores."""

    by_school: dict[str, dict] = {}
    for school_id, score, assessed_at in scores:
        item = by_school.setdefault(
            str(school_id),
            {
                "baseline_score": score,
                "baseline_date": assessed_at,
                "latest_score": score,
                "latest_date": assessed_at,
            },
        )
        item["latest_score"] = score
        item["latest_date"] = assessed_at

    for item in by_school.values():
        baseline = item["baseline_score"]
        latest = item["latest_score"]
        movement = round(float(latest) - float(baseline), 1)
        item["movement"] = movement
        if item["baseline_date"] == item["latest_date"]:
            item.update(label="Baseline only", tone="neutral")
        elif movement >= 1:
            item.update(label="Improving", tone="success")
        elif movement <= -1:
            item.update(label="Declining", tone="danger")
        else:
            item.update(label="Stable", tone="info")
    return by_school


def _intervention_school_queryset(principal, intervention: str):
    """Schools with a governed signal, assignment or delivery for an intervention."""

    from apps.core.scoping import resolve_user_scope
    from apps.schools.models import School

    schools = School.objects.select_related("region", "district").filter(
        Q(
            partner_assignments__focus_intervention=intervention,
            partner_assignments__status__in=[
                "assigned",
                "pending_scheduling",
                "scheduled",
            ],
        )
        | Q(
            activities__focus_intervention=intervention,
            activities__deleted_at__isnull=True,
        )
        | Q(
            business_transformation_cases__recommendations__source_intervention=intervention,
            business_transformation_cases__deleted_at__isnull=True,
        )
    )

    role = getattr(principal, "active_role", "")
    scope = resolve_user_scope(principal)
    if role in SUMMARY_ONLY_ROLES or not scope.can_view_school_level_detail:
        return schools.none()
    if role not in UGANDA_WIDE_ROLES:
        schools = schools.filter(id__in=scope.school_ids)
    return schools.distinct()


def _intervention_school_portfolio_context(
    principal,
    filters: dict,
    *,
    intervention: str,
    portfolio_kind: str,
) -> dict:
    """Shared list contract for the two school-level transformation portfolios."""

    from django.core.paginator import Paginator

    from apps.activities.models import Activity
    from apps.core.scoping import may_plan_school, resolve_user_scope
    from apps.geography.models import District, Region
    from apps.partners.models import Partner, PartnerAssignment
    from apps.ssa.models import SsaScore

    fy = filters.get("fy") or get_operational_fy()
    scope = resolve_user_scope(principal)
    active_role = getattr(principal, "active_role", "")
    schools = _intervention_school_queryset(principal, intervention)

    q = filters.get("q")
    if q:
        schools = schools.filter(
            Q(name__icontains=q)
            | Q(school_id__icontains=q)
            | Q(district__name__icontains=q)
            | Q(region__name__icontains=q)
            | Q(account_owner_name_raw__icontains=q)
        )
    if filters.get("region"):
        schools = schools.filter(region_id=filters["region"])
    if filters.get("district"):
        schools = schools.filter(district_id=filters["district"])
    if filters.get("partner"):
        schools = schools.filter(
            partner_assignments__partner_id=filters["partner"],
            partner_assignments__focus_intervention=intervention,
        )

    support_status = filters.get("support_status")
    if support_status == "assigned":
        schools = schools.filter(
            partner_assignments__focus_intervention=intervention,
            partner_assignments__status__in=[
                "assigned",
                "pending_scheduling",
                "scheduled",
            ],
        )
    elif support_status == "delivered":
        schools = schools.filter(
            activities__focus_intervention=intervention,
            activities__status__in=_DELIVERED_ACTIVITY_STATUSES,
        )
    elif support_status == "follow_up_due":
        schools = schools.filter(
            activities__focus_intervention=intervention,
            activities__status__in=_OPEN_SUPPORT_STATUSES,
            activities__planned_date__lt=timezone.localdate(),
        )

    schools = schools.distinct().order_by("name", "school_id")
    portfolio_school_ids = list(schools.values_list("id", flat=True))

    score_rows = list(
        SsaScore.objects.filter(
            ssa_record__school_id__in=portfolio_school_ids,
            ssa_record__verification_status="confirmed",
            ssa_record__fy=fy,
            intervention=intervention,
        )
        .order_by("ssa_record__school_id", "ssa_record__date_of_ssa")
        .values_list("ssa_record__school_id", "score", "ssa_record__date_of_ssa")
    )
    performance_by_school = _portfolio_performance(score_rows)

    try:
        per_page = int(filters.get("per_page") or 20)
    except (TypeError, ValueError):
        per_page = 20
    if per_page not in _PORTFOLIO_PAGE_SIZES:
        per_page = 20
    page_obj = Paginator(schools, per_page).get_page(filters.get("page") or 1)
    page_schools = list(page_obj.object_list)
    page_school_ids = [school.id for school in page_schools]

    assignments = (
        PartnerAssignment.objects.filter(
            school_id__in=page_school_ids,
            focus_intervention=intervention,
        )
        .exclude(status="returned_to_staff")
        .select_related("partner")
        .order_by("school_id", "-created_at")
    )
    assignment_by_school = {}
    for assignment in assignments:
        assignment_by_school.setdefault(str(assignment.school_id), assignment)

    activities = list(
        Activity.objects.filter(
            school_id__in=page_school_ids,
            focus_intervention=intervention,
            fy=fy,
        )
        .exclude(status__in=["cancelled", "rejected"])
        .select_related("catalogue_item")
        .order_by("school_id", "-planned_date", "-created_at")
    )
    activities_by_school: dict[str, list] = {}
    for activity in activities:
        activities_by_school.setdefault(str(activity.school_id), []).append(activity)

    cases = list(
        TransformationCase.objects.filter(school_id__in=page_school_ids)
        .order_by("school_id", "-created_at")
    )
    case_by_school = {}
    for case in cases:
        case_by_school.setdefault(str(case.school_id), case)

    practice_by_school = {}
    compliance_by_school: dict[str, list] = {}
    if portfolio_kind == "financial_health":
        for assessment in FinancialPracticeAssessment.objects.filter(
            case__school_id__in=page_school_ids
        ).order_by("case__school_id", "-assessed_on", "-created_at"):
            practice_by_school.setdefault(str(assessment.case.school_id), assessment)
    else:
        for assessment in SchoolComplianceAssessment.objects.filter(
            case__school_id__in=page_school_ids
        ).select_related("requirement").order_by("case__school_id", "requirement__label"):
            compliance_by_school.setdefault(str(assessment.case.school_id), []).append(
                assessment
            )

    rows = []
    today = timezone.localdate()
    for school in page_schools:
        school_key = str(school.id)
        school_activities = activities_by_school.get(school_key, [])
        delivered = [
            activity
            for activity in school_activities
            if activity.status in _DELIVERED_ACTIVITY_STATUSES
        ]
        verified = [
            activity
            for activity in school_activities
            if activity.status == "ia_verified"
            or activity.ia_verification_status == "confirmed"
        ]
        open_support = [
            activity
            for activity in school_activities
            if activity.status in _OPEN_SUPPORT_STATUSES
        ]
        overdue_support = [
            activity
            for activity in open_support
            if activity.planned_date and activity.planned_date < today
        ]
        next_support = min(
            (activity for activity in open_support if activity.planned_date),
            key=lambda activity: activity.planned_date,
            default=None,
        )
        performance = performance_by_school.get(
            school_key,
            {
                "baseline_score": None,
                "latest_score": None,
                "movement": None,
                "label": "Not assessed",
                "tone": "warning",
                "latest_date": None,
            },
        )
        assignment = assignment_by_school.get(school_key)
        case = case_by_school.get(school_key)
        row = {
            "id": school.id,
            "school_id": school.school_id,
            "name": school.name,
            "district_name": school.district.name if school.district else "—",
            "region_name": school.region.name if school.region else "—",
            "owner_name": school.account_owner_name_raw or "Unassigned",
            "school_type": school.get_school_type_display(),
            "enrollment": school.enrollment,
            "partner_name": assignment.partner.name if assignment else "Not assigned",
            "partner_status": assignment.get_status_display()
            if assignment and hasattr(assignment, "get_status_display")
            else (assignment.status.replace("_", " ").title() if assignment else "—"),
            "support_delivered": len(delivered),
            "support_verified": len(verified),
            "last_support_date": delivered[0].planned_date if delivered else None,
            "next_support_date": next_support.planned_date if next_support else None,
            "follow_up_overdue": bool(overdue_support),
            "performance": performance,
            "case": case,
            "can_manage": has_permission(
                principal,
                Permission.BUSINESS_TRANSFORMATION_SCHOOL_SUPPORT_MANAGE.value,
            ),
            # BT manages the transformation case/portfolio but never plans the
            # visit or training. The planning control belongs only to the CCEO
            # or PL who owns the school in the normal operational scope.
            "can_plan": active_role
            in {
                EdifyRole.CCEO.value,
                EdifyRole.COUNTRY_PROGRAM_LEAD.value,
            }
            and may_plan_school(scope, school.id),
        }

        if portfolio_kind == "financial_health":
            practice = practice_by_school.get(school_key)
            practices = practice.practices if practice else {}
            adopted = sum(value is True for value in practices.values())
            row.update(
                practice_adopted=adopted,
                practice_total=len(practices),
                practice_verified=bool(
                    practice
                    and practice.verification_status == IAValidationStatus.VERIFIED
                ),
                practice_assessed_on=practice.assessed_on if practice else None,
            )
        else:
            compliance = compliance_by_school.get(school_key, [])
            verified_compliance = [
                item for item in compliance if item.ia_status == IAValidationStatus.VERIFIED
            ]
            row.update(
                compliance_total=len(compliance),
                compliant=sum(item.status == "compliant" for item in verified_compliance),
                action_required=sum(
                    item.status in {"action_required", "expired"}
                    for item in verified_compliance
                ),
                awaiting_verification=sum(
                    item.ia_status == IAValidationStatus.PENDING for item in compliance
                ),
                unknown=sum(
                    item.status in {"not_assessed", "unknown"} for item in compliance
                ),
                nearest_expiry=min(
                    (item.expiry_date for item in verified_compliance if item.expiry_date),
                    default=None,
                ),
            )
        rows.append(row)

    activity_portfolio = Activity.objects.filter(
        school_id__in=portfolio_school_ids,
        focus_intervention=intervention,
        fy=fy,
    )
    active_assignment_portfolio = PartnerAssignment.objects.filter(
        school_id__in=portfolio_school_ids,
        focus_intervention=intervention,
    ).exclude(status="returned_to_staff")
    improving_count = sum(
        item["label"] == "Improving" for item in performance_by_school.values()
    )
    declining_count = sum(
        item["label"] == "Declining" for item in performance_by_school.values()
    )

    metrics = {
        "portfolio": len(portfolio_school_ids),
        "partnerAssigned": active_assignment_portfolio.values("school_id").distinct().count(),
        "supportDelivered": activity_portfolio.filter(
            status__in=_DELIVERED_ACTIVITY_STATUSES
        ).count(),
        "schoolsSupported": activity_portfolio.filter(
            status__in=_DELIVERED_ACTIVITY_STATUSES
        ).values("school_id").distinct().count(),
        "improving": improving_count,
        "declining": declining_count,
    }
    if portfolio_kind == "financial_health":
        practice_portfolio = FinancialPracticeAssessment.objects.filter(
            case__school_id__in=portfolio_school_ids
        )
        metrics.update(
            practiceAssessed=practice_portfolio.values("case__school_id").distinct().count(),
            practiceVerified=practice_portfolio.filter(
                verification_status=IAValidationStatus.VERIFIED
            ).values("case__school_id").distinct().count(),
        )
    else:
        compliance_portfolio = SchoolComplianceAssessment.objects.filter(
            case__school_id__in=portfolio_school_ids
        )
        metrics.update(
            compliant=compliance_portfolio.filter(
                status="compliant", ia_status=IAValidationStatus.VERIFIED
            ).values("case__school_id").distinct().count(),
            actionRequired=compliance_portfolio.filter(
                status__in=["action_required", "expired"],
                ia_status=IAValidationStatus.VERIFIED,
            ).values("case__school_id").distinct().count(),
            awaitingVerification=compliance_portfolio.filter(
                ia_status=IAValidationStatus.PENDING
            ).count(),
        )

    relevant_partner_ids = PartnerAssignment.objects.filter(
        school_id__in=portfolio_school_ids,
        focus_intervention=intervention,
    ).values("partner_id")
    return {
        "fy": fy,
        "filters": filters,
        "portfolio_kind": portfolio_kind,
        "intervention": intervention,
        "rows": rows,
        "metrics": metrics,
        "page_obj": page_obj,
        "pages_list": list(
            page_obj.paginator.get_elided_page_range(
                page_obj.number, on_each_side=1, on_ends=1
            )
        ),
        "per_page": per_page,
        "page_size_options": _PORTFOLIO_PAGE_SIZES,
        "regions": Region.objects.filter(
            id__in=schools.values("region_id")
        ).distinct().order_by("name"),
        "districts": District.objects.filter(
            id__in=schools.values("district_id")
        ).distinct().order_by("name"),
        "partners": Partner.objects.filter(id__in=relevant_partner_ids)
        .distinct()
        .order_by("name"),
        "requirements": ComplianceRequirement.objects.filter(
            country_code="UG", active=True
        ).order_by("label")
        if portfolio_kind == "government_requirements"
        else (),
        "can_manage_support": has_permission(
            principal,
            Permission.BUSINESS_TRANSFORMATION_SCHOOL_SUPPORT_MANAGE.value,
        ),
    }


def financial_health_context(principal, filters: dict) -> dict:
    """School-centred BAFF portfolio using the canonical directory pattern."""

    return _intervention_school_portfolio_context(
        principal,
        filters,
        intervention=SsaIntervention.FINANCIAL_HEALTH,
        portfolio_kind="financial_health",
    )


def government_requirements_context(principal, filters: dict) -> dict:
    """School-centred Uganda Government Requirements support portfolio."""

    return _intervention_school_portfolio_context(
        principal,
        filters,
        intervention=SsaIntervention.GOVERNMENT_REQUIREMENT,
        portfolio_kind="government_requirements",
    )


def impact_reports_context(principal, filters: dict) -> dict:
    fy = filters.get("fy") or get_operational_fy()
    loans = filter_loans(scoped_loans(principal), {**filters, "fy": fy})
    assessments = LoanImpactAssessment.objects.filter(loan__in=loans).select_related(
        "loan__school", "loan__mfi", "loan__purpose"
    )
    metrics = portfolio_metrics(principal, fy=fy, filters=filters)
    return {
        "fy": fy,
        "filters": filters,
        "metrics": metrics,
        "impact_assessments": assessments.order_by("due_date")[:200],
        "impact_statuses": LoanImpactStatus.choices,
        "cohorts": list(
            loans.filter(disbursement_date__isnull=False)
            .values("disbursement_date__year", "purpose__label")
            .annotate(loans=Count("id"), schools=Count("school_id", distinct=True))
            .order_by("-disbursement_date__year", "purpose__label")[:50]
        ),
    }


def mfi_portal_context(principal, section: str, filters: dict) -> dict:
    if getattr(principal, "active_role", "") not in MFI_ROLES:
        raise Forbidden("The MFI partner portal is available only to MFI users.")
    allowed_sections = {"dashboard", "loans", "monthly-return", "data-issues", "reports"}
    if section not in allowed_sections:
        raise NotFoundError("MFI portal section not found.")
    fy = filters.get("fy") or get_operational_fy()
    mfi_ids = _mfi_ids_for(principal)
    submissions = PortfolioSubmission.objects.filter(mfi_id__in=mfi_ids).select_related(
        "mfi"
    )
    exceptions = PortfolioDataException.objects.filter(
        submission__mfi_id__in=mfi_ids, status="open"
    ).select_related("submission", "submission__mfi")
    return {
        **loan_register_context(principal, {**filters, "fy": fy}),
        "section": section,
        "portal_submissions": submissions.order_by("-reporting_month")[:24],
        "data_issues": exceptions.order_by("submission__reporting_month", "row_number")[:100],
        "open_issue_count": exceptions.count(),
    }


def loan_register_context(principal, filters: dict) -> dict:
    """Universal Uganda loan register with an explicit read/write projection."""

    from apps.geography.models import District, Region
    from apps.schools.models import School

    fy = filters.get("fy") or get_operational_fy()
    filters = {**filters, "fy": fy}
    latest_snapshot = RepaymentSnapshot.objects.filter(loan_id=OuterRef("pk")).order_by(
        "-as_of_date", "-created_at"
    )
    loans = filter_loans(scoped_loans(principal), filters).annotate(
        latest_repayment_health=Subquery(latest_snapshot.values("status")[:1]),
        latest_amount_paid=Subquery(
            latest_snapshot.values("amount_paid_during_period")[:1]
        ),
        latest_outstanding_amount=Subquery(
            latest_snapshot.values("outstanding_amount")[:1]
        ),
        latest_amount_overdue=Subquery(latest_snapshot.values("amount_overdue")[:1]),
    )
    metrics = portfolio_metrics(principal, fy=fy, filters=filters)
    can_write = has_permission(
        principal, Permission.BUSINESS_TRANSFORMATION_LOAN_WRITE.value
    )
    can_execute = has_permission(
        principal, Permission.BUSINESS_TRANSFORMATION_REPAYMENT_WRITE.value
    )
    can_confirm_salesforce = has_permission(
        principal, Permission.BUSINESS_TRANSFORMATION_SALESFORCE_CONFIRM.value
    )
    loan_rows = list(loans[:200])
    repayment_labels = dict(RepaymentStatus.choices)
    for loan in loan_rows:
        loan.latest_repayment_health_label = repayment_labels.get(
            loan.latest_repayment_health, "Unknown"
        )
    return {
        "fy": fy,
        "filters": filters,
        "metrics": metrics,
        "kpi_strip_items": _portfolio_kpi_items(metrics, fy),
        "loans": loan_rows,
        "lending_partners": lending_partner_dashboard(principal, filters),
        "salesforce_pending_loans": (
            loans.filter(salesforce_status=SalesforceStatus.PENDING)[:50]
            if can_confirm_salesforce
            else loans.none()
        ),
        "mfis": scoped_mfis(principal),
        "regions": Region.objects.order_by("name"),
        "districts": District.objects.select_related("region").order_by("name"),
        "schools": School.objects.filter(
            id__in=scoped_loans(principal).order_by().values("school_id")
        )
        .order_by("name")
        .only("id", "name", "school_id"),
        "referrals": scoped_referrals(principal)
        .filter(purpose__active=True)
        .exclude(status__in=[ReferralStatus.DECLINED, ReferralStatus.WITHDRAWN])
        .order_by("case__school__name", "mfi__name"),
        "loan_purposes": LoanPurpose.objects.filter(active=True).order_by("label"),
        "loan_statuses": LoanStatus.choices,
        "repayment_statuses": RepaymentStatus.choices,
        "salesforce_statuses": SalesforceStatus.choices,
        "ia_statuses": IAValidationStatus.choices,
        "impact_statuses": LoanImpactStatus.choices,
        "can_write_loans": can_write,
        "can_execute_loans": can_execute,
        "can_confirm_salesforce": can_confirm_salesforce,
        "can_validate_ia": has_permission(
            principal, Permission.BUSINESS_TRANSFORMATION_IA_VALIDATE.value
        ),
        "can_export_loans": has_permission(
            principal, Permission.BUSINESS_TRANSFORMATION_EXPORT.value
        ),
        "access_label": (
            "Full access · MFI scope"
            if getattr(principal, "active_role", "") in MFI_ROLES
            and can_write
            and can_execute
            else "Salesforce confirmation"
            if can_confirm_salesforce
            else "Full access"
            if can_write and can_execute
            else "Read only"
        ),
    }


def school_profile_context(principal, school) -> dict:
    """Read-only School 360 projection with role-appropriate field visibility."""

    from apps.ssa.models import SsaScore

    sensitive = has_permission(
        principal, Permission.BUSINESS_TRANSFORMATION_SENSITIVE_VIEW.value
    )
    latest_repayment_status = (
        RepaymentSnapshot.objects.filter(loan_id=OuterRef("pk"))
        .order_by("-as_of_date", "-created_at")
        .values("status")[:1]
    )
    latest_outstanding = (
        RepaymentSnapshot.objects.filter(loan_id=OuterRef("pk"))
        .order_by("-as_of_date", "-created_at")
        .values("outstanding_amount")[:1]
    )
    loans = list(
        scoped_loans(principal)
        .filter(school=school)
        .annotate(
            latest_repayment_status=Subquery(latest_repayment_status),
            latest_outstanding_amount=Subquery(latest_outstanding),
        )
        .prefetch_related("verification_requirements")[:20]
    )
    loan_rows = []
    for loan in loans:
        requirement = next(iter(loan.verification_requirements.all()), None)
        row = {
            "id": loan.id,
            "mfi": loan.mfi.name,
            "purpose": loan.purpose.label,
            "is_edtech": loan.purpose.is_edtech,
            "status": loan.get_status_display(),
            "salesforce_status": loan.get_salesforce_status_display(),
            "salesforce_status_code": loan.salesforce_status,
            "impact_status": loan.get_impact_status_display(),
            "impact_status_code": loan.impact_status,
            "repayment_status": loan.latest_repayment_status or "No update",
            "verification_status": requirement.get_status_display()
            if requirement
            else "Not due",
            "verification_status_code": requirement.status if requirement else "",
            "verification_requirement_id": requirement.id if requirement else None,
            "verification_due": requirement.due_date if requirement else None,
        }
        if sensitive:
            row.update(
                {
                    "external_reference": loan.external_loan_reference,
                    "disbursed_amount": loan.disbursed_amount,
                    "currency": loan.currency,
                    "outstanding_amount": loan.latest_outstanding_amount,
                    "term_months": loan.term_months,
                }
            )
        loan_rows.append(row)

    cases = list(scoped_cases(principal).filter(school=school)[:5])
    score_rows = list(
        SsaScore.objects.filter(
            ssa_record__school=school,
            ssa_record__deleted_at__isnull=True,
            ssa_record__verification_status="confirmed",
            intervention__in=[
                SsaIntervention.FINANCIAL_HEALTH,
                SsaIntervention.GOVERNMENT_REQUIREMENT,
            ],
        )
        .select_related("ssa_record")
        .order_by("-ssa_record__date_of_ssa")[:12]
    )
    financial_practices = list(
        FinancialPracticeAssessment.objects.filter(case__school=school)
        .order_by("-assessed_on")[:5]
    )
    compliance_assessments = list(
        SchoolComplianceAssessment.objects.filter(case__school=school)
        .select_related("requirement")
        .order_by("requirement__label")[:20]
    )
    return {
        "visible": bool(
            cases
            or loans
            or score_rows
            or financial_practices
            or compliance_assessments
        ),
        "sensitive": sensitive,
        "can_manage": has_permission(
            principal, Permission.BUSINESS_TRANSFORMATION_CASE_MANAGE.value
        ),
        "cases": cases,
        "loans": loan_rows,
        "ssa_scores": score_rows,
        "financial_practices": financial_practices,
        "compliance_assessments": compliance_assessments,
        "active_case": next(
            (case for case in cases if case.status in OPEN_CASE_STATUSES), None
        ),
    }


def serialize_case(case: TransformationCase) -> dict:
    return {
        "id": case.id,
        "schoolId": case.school.school_id,
        "schoolName": case.school.name,
        "status": case.status,
        "openedFy": case.opened_fy,
        "triageDecision": case.triage_decision,
        "recommendations": [
            {
                "id": rec.id,
                "kind": rec.kind,
                "label": rec.get_kind_display(),
                "status": rec.status,
                "reason": rec.reason,
            }
            for rec in case.recommendations.all()
        ],
    }


def serialize_mfi(mfi: MfiOrganization) -> dict:
    return {"id": mfi.id, "code": mfi.code, "name": mfi.name, "active": mfi.active}


def serialize_referral(referral: FinanceReferral) -> dict:
    return {
        "id": referral.id,
        "caseId": referral.case_id,
        "schoolId": referral.case.school.school_id,
        "schoolName": referral.case.school.name,
        "mfiId": referral.mfi_id,
        "mfiName": referral.mfi.name,
        "purposeId": referral.purpose_id,
        "purpose": referral.purpose.label,
        "requestedAmount": str(referral.requested_amount)
        if referral.requested_amount is not None
        else None,
        "currency": referral.currency,
        "status": referral.status,
    }


def serialize_loan(loan: MfiLoan) -> dict:
    return {
        "id": loan.id,
        "mfiId": loan.mfi_id,
        "schoolId": loan.school.school_id,
        "caseId": loan.case_id,
        "externalLoanReference": loan.external_loan_reference,
        "salesforceLoanId": loan.salesforce_loan_id,
        "salesforceStatus": loan.salesforce_status,
        "salesforceEntryDate": (
            loan.salesforce_entry_date.isoformat()
            if loan.salesforce_entry_date
            else None
        ),
        "salesforceConfirmedBy": loan.salesforce_confirmed_by,
        "salesforceConfirmedAt": (
            loan.salesforce_confirmed_at.isoformat()
            if loan.salesforce_confirmed_at
            else None
        ),
        "purpose": loan.purpose.label,
        "isEdtech": loan.purpose.is_edtech,
        "approvedAmount": str(loan.approved_amount)
        if loan.approved_amount is not None
        else None,
        "disbursedAmount": str(loan.disbursed_amount)
        if loan.disbursed_amount is not None
        else None,
        "currency": loan.currency,
        "disbursementDate": loan.disbursement_date.isoformat()
        if loan.disbursement_date
        else None,
        "status": loan.status,
        "iaValidationStatus": loan.ia_validation_status,
        "impactStatus": loan.impact_status,
        "submittedAt": loan.submitted_at.isoformat() if loan.submitted_at else None,
    }


def serialize_snapshot(snapshot: RepaymentSnapshot) -> dict:
    return {
        "id": snapshot.id,
        "loanId": snapshot.loan_id,
        "asOfDate": snapshot.as_of_date.isoformat(),
        "outstandingAmount": str(snapshot.outstanding_amount),
        "amountOverdue": str(snapshot.amount_overdue),
        "daysInArrears": snapshot.days_in_arrears,
        "status": snapshot.status,
    }


def serialize_requirement(requirement: LoanVerificationRequirement) -> dict:
    return {
        "id": requirement.id,
        "loanId": requirement.loan_id,
        "activityId": requirement.activity_id,
        "dueDate": requirement.due_date.isoformat(),
        "status": requirement.status,
    }


def serialize_loan_use_result(result: LoanUseResult) -> dict:
    return {
        "id": result.id,
        "requirementId": result.requirement_id,
        "finding": result.finding,
        "verificationStatus": result.verification_status,
    }
