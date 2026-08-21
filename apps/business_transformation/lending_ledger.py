"""Authoritative lending-facility, disbursement and repayment ledger services.

All value-bearing writes are idempotent, transactionally locked, append-only,
and fail closed when the tamper-evident audit event cannot be persisted.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import F, Max, OuterRef, Q, Subquery, Sum
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.audit.services import log as audit_log
from apps.core.exceptions import BadRequest, ConflictError, Forbidden, NotFoundError
from apps.core.permissions import has_permission
from apps.core.rbac import EdifyRole, Permission

from .models import (
    FacilityCapitalSource,
    FacilityAllocationStatus,
    FacilityMovementKind,
    FundingFacility,
    FundingFacilityAllocation,
    FundingFacilityStatus,
    FundingFacilityTranche,
    FundingFacilityTrancheReversal,
    FundingFacilityMovement,
    FundingFacilityMovementReversal,
    EnrolmentSnapshot,
    EnrolmentSnapshotKind,
    LoanDisbursement,
    LoanDisbursementReversal,
    LoanImpactAssessment,
    LoanImpactStatus,
    LoanPurposeAllocation,
    LoanRepaymentInstallment,
    LoanStatus,
    MfiLoan,
    MfiMembership,
    MfiMembershipRole,
    MfiOrganization,
    RepaymentAllocation,
    RepaymentComponent,
    RepaymentTransaction,
    RepaymentTransactionKind,
)

MONEY_QUANTUM = Decimal("0.01")
ZERO = Decimal("0.00")
MFI_ROLES = {
    EdifyRole.MFI_PARTNER_ADMIN.value,
    EdifyRole.MFI_LOAN_OFFICER.value,
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


def _money(value, *, field: str, allow_zero: bool = False) -> Decimal:
    if value in (None, ""):
        raise BadRequest(f"{field} is required.")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise BadRequest(f"{field} must be a valid monetary amount.") from exc
    if not parsed.is_finite() or parsed != parsed.quantize(MONEY_QUANTUM):
        raise BadRequest(f"{field} must have no more than two decimal places.")
    if parsed < 0 or (parsed == 0 and not allow_zero):
        comparator = "zero or greater" if allow_zero else "greater than zero"
        raise BadRequest(f"{field} must be {comparator}.")
    return parsed


def _date(value, *, field: str) -> date:
    parsed = value if isinstance(value, date) else parse_date(str(value or ""))
    if parsed is None:
        raise BadRequest(f"{field} must be a valid date.")
    return parsed


def _text(data: dict, key: str, label: str) -> str:
    value = str(data.get(key) or "").strip()
    if not value:
        raise BadRequest(f"{label} is required.")
    return value


def _assert_mfi_scope(principal, mfi_id: str) -> None:
    if getattr(principal, "active_role", "") not in MFI_ROLES:
        return
    if not MfiMembership.objects.filter(
        user_id=_actor_id(principal), mfi_id=mfi_id, active=True
    ).exists():
        raise Forbidden("This record is outside your lending-partner scope.")


def _assert_loan_scope(principal, loan: MfiLoan) -> None:
    _assert_mfi_scope(principal, loan.mfi_id)
    if getattr(principal, "active_role", "") != EdifyRole.MFI_LOAN_OFFICER.value:
        return
    actor_id = _actor_id(principal)
    references = (
        MfiMembership.objects.filter(
            user_id=actor_id,
            mfi_id=loan.mfi_id,
            role=MfiMembershipRole.LOAN_OFFICER,
            active=True,
        )
        .exclude(officer_reference="")
        .values_list("officer_reference", flat=True)
    )
    if loan.registered_by != actor_id and loan.assigned_officer_reference not in set(
        references
    ):
        raise NotFoundError("Loan record not found in your assigned portfolio.")


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


def _same_money(left, right) -> bool:
    return Decimal(left) == Decimal(right)


@transaction.atomic
def create_funding_facility(data: dict, principal) -> FundingFacility:
    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_FACILITY_MANAGE,
        "Only Business Transformation or the Country Director may create a facility.",
    )
    mfi_id = _text(data, "mfiId", "Lending partner")
    mfi = MfiOrganization.objects.filter(id=mfi_id, active=True).first()
    if mfi is None:
        raise NotFoundError("Lending partner not found.")
    starts_on = _date(data.get("startsOn"), field="Start date")
    ends_on = (
        _date(data.get("endsOn"), field="End date") if data.get("endsOn") else None
    )
    if ends_on and ends_on < starts_on:
        raise BadRequest("End date cannot be before start date.")
    country_code = str(data.get("countryCode") or mfi.country_code).strip().upper()
    currency = str(data.get("currency") or "UGX").strip().upper()
    if len(country_code) != 2 or len(currency) != 3:
        raise BadRequest("Country and currency must use ISO codes.")
    facility = FundingFacility.objects.create(
        mfi=mfi,
        external_reference=_text(data, "externalReference", "Facility reference"),
        name=_text(data, "name", "Facility name"),
        country_code=country_code,
        currency=currency,
        funding_source=str(data.get("fundingSource") or "").strip(),
        facility_type=str(data.get("facilityType") or "").strip(),
        approved_amount=(
            _money(data.get("approvedAmount"), field="Approved amount")
            if data.get("approvedAmount") not in (None, "")
            else None
        ),
        commitment_amount=_money(data.get("commitmentAmount"), field="Commitment"),
        revolving=bool(data.get("revolving", False)),
        starts_on=starts_on,
        ends_on=ends_on,
        agreement_reference=str(data.get("agreementReference") or "").strip(),
        permitted_purpose_codes=list(data.get("permittedPurposeCodes") or []),
        geographic_restrictions=dict(data.get("geographicRestrictions") or {}),
        school_eligibility_restrictions=dict(
            data.get("schoolEligibilityRestrictions") or {}
        ),
        interest_structure=dict(data.get("interestStructure") or {}),
        reporting_conditions=dict(data.get("reportingConditions") or {}),
        created_by=_actor_id(principal),
    )
    if (
        facility.approved_amount is not None
        and facility.commitment_amount > facility.approved_amount
    ):
        raise BadRequest("Commitment cannot exceed the approved facility amount.")
    _audit(
        "bt.facility.created",
        facility,
        principal,
        {
            "mfiId": facility.mfi_id,
            "currency": facility.currency,
            "commitmentAmount": str(facility.commitment_amount),
            "revolving": facility.revolving,
        },
    )
    return facility


@transaction.atomic
def approve_funding_facility(facility_id: str, principal) -> FundingFacility:
    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_FACILITY_APPROVE,
        "Only the Country Director may approve a funding facility.",
    )
    facility = (
        FundingFacility.objects.select_for_update().filter(id=facility_id).first()
    )
    if facility is None:
        raise NotFoundError("Funding facility not found.")
    actor = _actor_id(principal)
    if facility.created_by == actor:
        raise Forbidden("The facility creator cannot approve the same facility.")
    if facility.status != FundingFacilityStatus.DRAFT:
        raise ConflictError("Only a draft facility can be approved.")
    now = timezone.now()
    facility.status = FundingFacilityStatus.APPROVED
    facility.approved_by = actor
    facility.approved_at = now
    facility.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
    _audit(
        "bt.facility.approved",
        facility,
        principal,
        {"previousStatus": FundingFacilityStatus.DRAFT, "status": facility.status},
    )
    return facility


@transaction.atomic
def confirm_facility_tranche(data: dict, principal) -> FundingFacilityTranche:
    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_FACILITY_TRANSFER,
        "Only the Accountant may confirm a facility cash receipt.",
    )
    facility_id = _text(data, "facilityId", "Funding facility")
    facility = (
        FundingFacility.objects.select_for_update().filter(id=facility_id).first()
    )
    if facility is None:
        raise NotFoundError("Funding facility not found.")
    if facility.status not in {
        FundingFacilityStatus.APPROVED,
        FundingFacilityStatus.ACTIVE,
    }:
        raise ConflictError("Cash can be confirmed only for an approved facility.")
    key = _text(data, "idempotencyKey", "Idempotency key")
    amount = _money(data.get("amount"), field="Receipt amount")
    external_reference = _text(data, "externalReference", "Transfer reference")
    existing = FundingFacilityTranche.objects.filter(idempotency_key=key).first()
    if existing:
        if (
            existing.facility_id != facility.id
            or existing.external_reference != external_reference
            or not _same_money(existing.amount, amount)
        ):
            raise ConflictError("Idempotency key was already used for another receipt.")
        return existing
    confirmed_receipts = (
        FundingFacilityTranche.objects.filter(
            facility=facility, reversal__isnull=True
        ).aggregate(total=Sum("amount"))["total"]
        or ZERO
    )
    if confirmed_receipts + amount > facility.commitment_amount:
        raise BadRequest("Confirmed receipts cannot exceed the facility commitment.")
    now = timezone.now()
    tranche = FundingFacilityTranche.objects.create(
        facility=facility,
        external_reference=external_reference,
        tranche_number=(
            int(data["trancheNumber"])
            if data.get("trancheNumber") not in (None, "")
            else None
        ),
        idempotency_key=key,
        amount=amount,
        received_on=_date(data.get("receivedOn"), field="Receipt date"),
        value_date=_date(data.get("valueDate"), field="Value date"),
        evidence_reference=_text(data, "evidenceReference", "Transfer evidence"),
        payment_reference=str(data.get("paymentReference") or external_reference),
        source_account=str(data.get("sourceAccount") or "").strip(),
        currency=facility.currency,
        exchange_rate=Decimal(str(data.get("exchangeRate") or "1")),
        reconciliation_status="confirmed",
        confirmed_by=_actor_id(principal),
        confirmed_at=now,
    )
    if facility.status == FundingFacilityStatus.APPROVED:
        facility.status = FundingFacilityStatus.ACTIVE
        facility.save(update_fields=["status", "updated_at"])
    _audit(
        "bt.facility.tranche_confirmed",
        tranche,
        principal,
        {
            "facilityId": facility.id,
            "amount": str(amount),
            "currency": facility.currency,
            "valueDate": tranche.value_date.isoformat(),
        },
    )
    from apps.integrations.services import enqueue_facility_tranche_netsuite_sync

    enqueue_facility_tranche_netsuite_sync(tranche.id)
    return tranche


@transaction.atomic
def reverse_facility_tranche(
    tranche_id: str, data: dict, principal
) -> FundingFacilityTrancheReversal:
    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_FACILITY_TRANSFER,
        "Only the Accountant may reverse a facility cash receipt.",
    )
    tranche = (
        FundingFacilityTranche.objects.select_related("facility")
        .select_for_update()
        .filter(id=tranche_id)
        .first()
    )
    if tranche is None:
        raise NotFoundError("Facility receipt not found.")
    key = _text(data, "idempotencyKey", "Idempotency key")
    existing = FundingFacilityTrancheReversal.objects.filter(
        idempotency_key=key
    ).first()
    if existing:
        if existing.tranche_id != tranche.id:
            raise ConflictError(
                "Idempotency key was already used for another reversal."
            )
        return existing
    if FundingFacilityTrancheReversal.objects.filter(tranche=tranche).exists():
        raise ConflictError("This facility receipt has already been reversed.")
    position = facility_position(tranche.facility)
    if position["originalCapitalRemaining"] < tranche.amount:
        raise ConflictError(
            "The receipt cannot be reversed while its funds are allocated or disbursed."
        )
    reversal = FundingFacilityTrancheReversal.objects.create(
        tranche=tranche,
        idempotency_key=key,
        reason=_text(data, "reason", "Reversal reason"),
        reversed_by=_actor_id(principal),
        reversed_at=timezone.now(),
    )
    _audit(
        "bt.facility.tranche_reversed",
        reversal,
        principal,
        {"trancheId": tranche.id, "amount": str(tranche.amount)},
    )
    return reversal


@transaction.atomic
def post_facility_movement(data: dict, principal) -> FundingFacilityMovement:
    """Post an evidenced facility deduction or capital return, by capital pool."""

    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_FACILITY_TRANSFER,
        "Only the Accountant may post a facility deduction or capital return.",
    )
    facility = (
        FundingFacility.objects.select_for_update()
        .filter(id=_text(data, "facilityId", "Funding facility"))
        .first()
    )
    if facility is None:
        raise NotFoundError("Funding facility not found.")
    kind = str(data.get("kind") or "").strip()
    source = str(data.get("capitalSource") or "").strip()
    if kind not in FacilityMovementKind.values:
        raise BadRequest(
            "Movement kind must be an authorized deduction or capital return."
        )
    if source not in FacilityCapitalSource.values:
        raise BadRequest("Capital source must be original or recovered.")
    if source == FacilityCapitalSource.RECOVERED and not facility.revolving:
        raise BadRequest("A non-revolving facility has no recoverable relending pool.")
    amount = _money(data.get("amount"), field="Movement amount")
    key = _text(data, "idempotencyKey", "Idempotency key")
    reference = _text(data, "externalReference", "Movement reference")
    existing = FundingFacilityMovement.objects.filter(idempotency_key=key).first()
    if existing:
        if (
            existing.facility_id != facility.id
            or existing.kind != kind
            or existing.capital_source != source
            or not _same_money(existing.amount, amount)
        ):
            raise ConflictError(
                "Idempotency key was already used for another movement."
            )
        return existing
    position = facility_position(facility)
    source_available = (
        position["originalCapitalRemaining"]
        if source == FacilityCapitalSource.ORIGINAL
        else position["recoveredPrincipalAvailableForRelending"]
    )
    if amount > source_available:
        raise ConflictError(f"Movement exceeds available {source} capital.")
    movement = FundingFacilityMovement.objects.create(
        facility=facility,
        kind=kind,
        capital_source=source,
        amount=amount,
        external_reference=reference,
        idempotency_key=key,
        value_date=_date(data.get("valueDate"), field="Value date"),
        evidence_reference=_text(data, "evidenceReference", "Movement evidence"),
        posted_by=_actor_id(principal),
        posted_at=timezone.now(),
    )
    _audit(
        "bt.facility.movement_posted",
        movement,
        principal,
        {
            "facilityId": facility.id,
            "kind": kind,
            "capitalSource": source,
            "amount": str(amount),
        },
    )
    return movement


@transaction.atomic
def reverse_facility_movement(
    movement_id: str, data: dict, principal
) -> FundingFacilityMovementReversal:
    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_FACILITY_TRANSFER,
        "Only the Accountant may reverse a facility movement.",
    )
    movement = (
        FundingFacilityMovement.objects.select_for_update()
        .filter(id=movement_id)
        .first()
    )
    if movement is None:
        raise NotFoundError("Facility movement not found.")
    key = _text(data, "idempotencyKey", "Idempotency key")
    existing = FundingFacilityMovementReversal.objects.filter(
        idempotency_key=key
    ).first()
    if existing:
        if existing.movement_id != movement.id:
            raise ConflictError(
                "Idempotency key was already used for another reversal."
            )
        return existing
    if FundingFacilityMovementReversal.objects.filter(movement=movement).exists():
        raise ConflictError("This facility movement has already been reversed.")
    reversal = FundingFacilityMovementReversal.objects.create(
        movement=movement,
        idempotency_key=key,
        reason=_text(data, "reason", "Reversal reason"),
        reversed_by=_actor_id(principal),
        reversed_at=timezone.now(),
    )
    _audit(
        "bt.facility.movement_reversed",
        reversal,
        principal,
        {"movementId": movement.id, "amount": str(movement.amount)},
    )
    return reversal


def _net_disbursed_for_loan(loan: MfiLoan, *, as_of: date | None = None) -> Decimal:
    filters = Q(loan=loan, reversal__isnull=True)
    if as_of:
        filters &= Q(value_date__lte=as_of)
    return (
        LoanDisbursement.objects.filter(filters).aggregate(total=Sum("amount"))["total"]
        or ZERO
    )


def _net_principal_repaid(loan: MfiLoan, *, as_of: date | None = None) -> Decimal:
    allocations = RepaymentAllocation.objects.filter(
        transaction__loan=loan,
        component=RepaymentComponent.PRINCIPAL,
    )
    if as_of:
        allocations = allocations.filter(transaction__value_date__lte=as_of)
    paid = (
        allocations.filter(
            transaction__kind=RepaymentTransactionKind.PAYMENT
        ).aggregate(total=Sum("amount"))["total"]
        or ZERO
    )
    reversed_amount = (
        allocations.filter(
            transaction__kind=RepaymentTransactionKind.REVERSAL
        ).aggregate(total=Sum("amount"))["total"]
        or ZERO
    )
    return paid - reversed_amount


def facility_position(facility: FundingFacility) -> dict[str, Decimal]:
    receipts = (
        FundingFacilityTranche.objects.filter(
            facility=facility, reversal__isnull=True
        ).aggregate(total=Sum("amount"))["total"]
        or ZERO
    )
    disbursements = LoanDisbursement.objects.filter(
        allocation__facility=facility, reversal__isnull=True
    )
    original_disbursed = (
        disbursements.filter(capital_source=FacilityCapitalSource.ORIGINAL).aggregate(
            total=Sum("amount")
        )["total"]
        or ZERO
    )
    recovered_disbursed = (
        disbursements.filter(capital_source=FacilityCapitalSource.RECOVERED).aggregate(
            total=Sum("amount")
        )["total"]
        or ZERO
    )
    disbursed = original_disbursed + recovered_disbursed
    recycled = ZERO
    if facility.revolving:
        allocations = RepaymentAllocation.objects.filter(
            transaction__loan__facility=facility,
            component=RepaymentComponent.PRINCIPAL,
        )
        paid = (
            allocations.filter(
                transaction__kind=RepaymentTransactionKind.PAYMENT
            ).aggregate(total=Sum("amount"))["total"]
            or ZERO
        )
        reversed_amount = (
            allocations.filter(
                transaction__kind=RepaymentTransactionKind.REVERSAL
            ).aggregate(total=Sum("amount"))["total"]
            or ZERO
        )
        recycled = paid - reversed_amount
    reserved_by_source = {
        FacilityCapitalSource.ORIGINAL: ZERO,
        FacilityCapitalSource.RECOVERED: ZERO,
    }
    active_allocations = FundingFacilityAllocation.objects.filter(
        facility=facility,
        status__in=[
            FacilityAllocationStatus.RESERVED,
            FacilityAllocationStatus.CONSUMED,
        ],
    ).prefetch_related("disbursements__reversal")
    for allocation in active_allocations:
        allocation_disbursed = sum(
            (
                posting.amount
                for posting in allocation.disbursements.all()
                if not hasattr(posting, "reversal")
            ),
            ZERO,
        )
        reserved_by_source[allocation.capital_source] += max(
            ZERO, allocation.amount - allocation_disbursed
        )
    movements = FundingFacilityMovement.objects.filter(
        facility=facility, reversal__isnull=True
    )

    def movement_total(kind, source):
        return (
            movements.filter(kind=kind, capital_source=source).aggregate(
                total=Sum("amount")
            )["total"]
            or ZERO
        )

    original_deductions = movement_total(
        FacilityMovementKind.AUTHORIZED_DEDUCTION, FacilityCapitalSource.ORIGINAL
    )
    recovered_deductions = movement_total(
        FacilityMovementKind.AUTHORIZED_DEDUCTION, FacilityCapitalSource.RECOVERED
    )
    original_returns = movement_total(
        FacilityMovementKind.CAPITAL_RETURN, FacilityCapitalSource.ORIGINAL
    )
    recovered_returns = movement_total(
        FacilityMovementKind.CAPITAL_RETURN, FacilityCapitalSource.RECOVERED
    )
    original_remaining = (
        receipts
        - original_disbursed
        - reserved_by_source[FacilityCapitalSource.ORIGINAL]
        - original_deductions
        - original_returns
    )
    recovered_available = (
        recycled
        - recovered_disbursed
        - reserved_by_source[FacilityCapitalSource.RECOVERED]
        - recovered_deductions
        - recovered_returns
    )
    reserved = sum(reserved_by_source.values(), ZERO)
    available = original_remaining + recovered_available
    return {
        "approved": facility.approved_amount or facility.commitment_amount,
        "commitment": facility.commitment_amount,
        "confirmedReceipts": receipts,
        "recycledPrincipal": recycled,
        "principalRecovered": recycled,
        "originalDisbursements": original_disbursed,
        "recoveredCapitalDisbursements": recovered_disbursed,
        "amountRelended": recovered_disbursed,
        "confirmedDisbursements": disbursed,
        "originalCapitalReserved": reserved_by_source[FacilityCapitalSource.ORIGINAL],
        "recoveredCapitalReserved": reserved_by_source[FacilityCapitalSource.RECOVERED],
        "reservedAllocations": reserved,
        "authorizedDeductions": original_deductions + recovered_deductions,
        "capitalReturned": original_returns + recovered_returns,
        "originalCapitalRemaining": original_remaining,
        "recoveredPrincipalAvailableForRelending": recovered_available,
        "available": available,
        "reconciliationDifference": ZERO,
    }


def scoped_facilities(principal):
    """Facility-only projection; never joins or serializes school-loan detail."""

    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_FACILITY_VIEW,
        "You do not have access to lending facilities.",
    )
    qs = FundingFacility.objects.select_related("mfi")
    if getattr(principal, "active_role", "") in MFI_ROLES:
        return qs.filter(
            mfi_id__in=MfiMembership.objects.filter(
                user_id=_actor_id(principal), active=True
            ).values("mfi_id")
        )
    return qs


def serialize_facility(facility: FundingFacility) -> dict:
    position = facility_position(facility)
    return {
        "id": facility.id,
        "mfiId": facility.mfi_id,
        "mfiName": facility.mfi.name,
        "externalReference": facility.external_reference,
        "name": facility.name,
        "countryCode": facility.country_code,
        "currency": facility.currency,
        "fundingSource": facility.funding_source,
        "facilityType": facility.facility_type,
        "approvedAmount": str(facility.approved_amount or facility.commitment_amount),
        "commitmentAmount": str(facility.commitment_amount),
        "revolving": facility.revolving,
        "startsOn": facility.starts_on.isoformat(),
        "endsOn": facility.ends_on.isoformat() if facility.ends_on else None,
        "status": facility.status,
        "position": {key: str(value) for key, value in position.items()},
    }


@transaction.atomic
def reserve_facility_for_loan(data: dict, principal) -> FundingFacilityAllocation:
    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_ALLOCATION_MANAGE,
        "Only Business Transformation or the Country Director may reserve facility funds.",
    )
    facility = (
        FundingFacility.objects.select_for_update()
        .filter(id=_text(data, "facilityId", "Funding facility"))
        .first()
    )
    loan = (
        MfiLoan.objects.select_for_update()
        .filter(id=_text(data, "loanId", "School loan"))
        .first()
    )
    if facility is None or loan is None:
        raise NotFoundError("Funding facility or school loan not found.")
    if facility.status != FundingFacilityStatus.ACTIVE:
        raise ConflictError("Funds can be reserved only from an active facility.")
    if facility.mfi_id != loan.mfi_id or facility.currency != loan.currency:
        raise BadRequest("Facility, lending partner and loan currency must match.")
    if loan.status != LoanStatus.PROCESSING:
        raise ConflictError("Funds can be reserved only for a processing loan.")
    amount = _money(data.get("amount"), field="Allocation amount")
    capital_source = str(
        data.get("capitalSource") or FacilityCapitalSource.ORIGINAL
    ).strip()
    if capital_source not in FacilityCapitalSource.values:
        raise BadRequest("Capital source must be original or recovered.")
    if capital_source == FacilityCapitalSource.RECOVERED and not facility.revolving:
        raise BadRequest(
            "Recovered principal can be re-lent only from a revolving facility."
        )
    if loan.approved_amount is None or amount > loan.approved_amount:
        raise BadRequest("Allocation cannot exceed the approved loan amount.")
    key = _text(data, "idempotencyKey", "Idempotency key")
    existing = FundingFacilityAllocation.objects.filter(idempotency_key=key).first()
    if existing:
        if (
            existing.facility_id != facility.id
            or existing.loan_id != loan.id
            or not _same_money(existing.amount, amount)
            or existing.capital_source != capital_source
        ):
            raise ConflictError(
                "Idempotency key was already used for another allocation."
            )
        return existing
    if FundingFacilityAllocation.objects.filter(loan=loan).exists():
        raise ConflictError("This loan already has a facility allocation.")
    position = facility_position(facility)
    source_available = (
        position["originalCapitalRemaining"]
        if capital_source == FacilityCapitalSource.ORIGINAL
        else position["recoveredPrincipalAvailableForRelending"]
    )
    if source_available < amount:
        raise ConflictError(
            f"The facility does not have enough {capital_source} capital available."
        )
    allocation = FundingFacilityAllocation.objects.create(
        facility=facility,
        loan=loan,
        amount=amount,
        capital_source=capital_source,
        idempotency_key=key,
        reserved_by=_actor_id(principal),
        reserved_at=timezone.now(),
    )
    loan.facility = facility
    loan.save(update_fields=["facility", "updated_at"])
    _audit(
        "bt.facility.allocated",
        allocation,
        principal,
        {
            "facilityId": facility.id,
            "loanId": loan.id,
            "amount": str(amount),
            "capitalSource": capital_source,
        },
    )
    return allocation


@transaction.atomic
def release_facility_allocation(
    allocation_id: str, data: dict, principal
) -> FundingFacilityAllocation:
    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_ALLOCATION_MANAGE,
        "Only Business Transformation or the Country Director may release funds.",
    )
    allocation = (
        FundingFacilityAllocation.objects.select_for_update()
        .select_related("loan")
        .filter(id=allocation_id)
        .first()
    )
    if allocation is None:
        raise NotFoundError("Facility allocation not found.")
    if allocation.status == FacilityAllocationStatus.RELEASED:
        return allocation
    allocation.status = FacilityAllocationStatus.RELEASED
    allocation.released_by = _actor_id(principal)
    allocation.released_at = timezone.now()
    allocation.release_reason = _text(data, "reason", "Release reason")
    allocation.save(
        update_fields=[
            "status",
            "released_by",
            "released_at",
            "release_reason",
            "updated_at",
        ]
    )
    _audit(
        "bt.facility.allocation_released",
        allocation,
        principal,
        {"loanId": allocation.loan_id, "reason": allocation.release_reason},
    )
    return allocation


@transaction.atomic
def post_loan_disbursement(data: dict, principal) -> LoanDisbursement:
    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_DISBURSEMENT_WRITE,
        "Only an authorized lending-partner operator may post a disbursement.",
    )
    loan = (
        MfiLoan.objects.select_for_update()
        .filter(id=_text(data, "loanId", "School loan"))
        .first()
    )
    if loan is None:
        raise NotFoundError("School loan not found.")
    _assert_loan_scope(principal, loan)
    allocation = (
        FundingFacilityAllocation.objects.select_for_update()
        .select_related("facility")
        .filter(loan=loan)
        .first()
    )
    if allocation is None or allocation.status == FacilityAllocationStatus.RELEASED:
        raise ConflictError("The loan has no active facility allocation.")
    amount = _money(data.get("amount"), field="Disbursement amount")
    key = _text(data, "idempotencyKey", "Idempotency key")
    existing = LoanDisbursement.objects.filter(idempotency_key=key).first()
    if existing:
        if (
            existing.loan_id != loan.id
            or not _same_money(existing.amount, amount)
            or existing.capital_source != allocation.capital_source
        ):
            raise ConflictError(
                "Idempotency key was already used for another disbursement."
            )
        return existing
    net_before = _net_disbursed_for_loan(loan)
    if net_before == ZERO:
        planned_purpose = (
            LoanPurposeAllocation.objects.filter(loan=loan).aggregate(
                total=Sum("planned_amount")
            )["total"]
            or ZERO
        )
        if loan.approved_amount is None or planned_purpose != loan.approved_amount:
            raise ConflictError(
                "A reconciled purpose allocation plan is required before disbursement."
            )
        if not EnrolmentSnapshot.objects.filter(
            loan=loan,
            kind=EnrolmentSnapshotKind.BASELINE,
            as_of_date__lte=_date(data.get("valueDate"), field="Value date"),
        ).exists():
            raise ConflictError(
                "An enrolment baseline dated on or before disbursement is required."
            )
    if net_before + amount > allocation.amount:
        raise ConflictError("Disbursement would exceed the reserved facility amount.")
    sequence = int(data.get("sequence") or 0)
    if sequence <= 0:
        raise BadRequest("Disbursement sequence must be greater than zero.")
    now = timezone.now()
    posting = LoanDisbursement.objects.create(
        loan=loan,
        allocation=allocation,
        sequence=sequence,
        external_reference=_text(data, "externalReference", "Disbursement reference"),
        idempotency_key=key,
        amount=amount,
        capital_source=allocation.capital_source,
        disbursed_on=_date(data.get("disbursedOn"), field="Disbursement date"),
        value_date=_date(data.get("valueDate"), field="Value date"),
        bank_reference=_text(data, "bankReference", "Bank reference"),
        confirmed_by=_actor_id(principal),
        confirmed_at=now,
    )
    net_after = net_before + amount
    first_confirmation = loan.disbursement_confirmed_at
    loan.disbursed_amount = net_after
    loan.disbursement_date = loan.disbursement_date or posting.disbursed_on
    loan.disbursement_confirmed_at = first_confirmation or now
    if loan.status == LoanStatus.PROCESSING:
        loan.status = LoanStatus.DISBURSED
    loan.save(
        update_fields=[
            "disbursed_amount",
            "disbursement_date",
            "disbursement_confirmed_at",
            "status",
            "updated_at",
        ]
    )
    from . import services as bt_services

    bt_services._record_status_change(
        loan,
        "lifecycle",
        LoanStatus.PROCESSING if net_before == ZERO else loan.status,
        loan.status,
        principal,
        reason="Confirmed facility-backed disbursement posted",
    )
    bt_services._ensure_verification_requirement(loan)
    case = loan.case
    if case.status in {"recommended", "triage", "active"}:
        case.status = "monitoring"
        case.save(update_fields=["status", "updated_at"])
    if net_before == ZERO:
        bt_services._notify_disbursement(loan)
        due_date = posting.disbursed_on + timedelta(days=loan.purpose.follow_up_days)
        LoanImpactAssessment.objects.get_or_create(
            loan=loan,
            due_date=due_date,
            defaults={
                "classification": (
                    LoanImpactStatus.DUE
                    if due_date <= timezone.localdate()
                    else LoanImpactStatus.NOT_DUE
                )
            },
        )
        loan.impact_status = (
            LoanImpactStatus.DUE
            if due_date <= timezone.localdate()
            else LoanImpactStatus.NOT_DUE
        )
        loan.save(update_fields=["impact_status", "updated_at"])
    if net_after == allocation.amount:
        allocation.status = FacilityAllocationStatus.CONSUMED
        allocation.save(update_fields=["status", "updated_at"])
    _audit(
        "bt.loan.disbursement_posted",
        posting,
        principal,
        {
            "loanId": loan.id,
            "facilityId": allocation.facility_id,
            "amount": str(amount),
            "netDisbursed": str(net_after),
        },
    )
    return posting


@transaction.atomic
def reverse_loan_disbursement(
    disbursement_id: str, data: dict, principal
) -> LoanDisbursementReversal:
    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_DISBURSEMENT_WRITE,
        "Only an authorized lending-partner operator may reverse a disbursement.",
    )
    posting = (
        LoanDisbursement.objects.select_related("loan", "allocation")
        .select_for_update()
        .filter(id=disbursement_id)
        .first()
    )
    if posting is None:
        raise NotFoundError("Disbursement not found.")
    _assert_loan_scope(principal, posting.loan)
    if RepaymentTransaction.objects.filter(
        loan=posting.loan, kind=RepaymentTransactionKind.PAYMENT
    ).exists():
        raise ConflictError("A disbursement cannot be reversed after repayments exist.")
    key = _text(data, "idempotencyKey", "Idempotency key")
    existing = LoanDisbursementReversal.objects.filter(idempotency_key=key).first()
    if existing:
        if existing.disbursement_id != posting.id:
            raise ConflictError(
                "Idempotency key was already used for another reversal."
            )
        return existing
    if LoanDisbursementReversal.objects.filter(disbursement=posting).exists():
        raise ConflictError("This disbursement has already been reversed.")
    reversal = LoanDisbursementReversal.objects.create(
        disbursement=posting,
        idempotency_key=key,
        reason=_text(data, "reason", "Reversal reason"),
        reversed_by=_actor_id(principal),
        reversed_at=timezone.now(),
    )
    loan = MfiLoan.objects.select_for_update().get(id=posting.loan_id)
    net_after = _net_disbursed_for_loan(loan)
    remaining_postings = LoanDisbursement.objects.filter(
        loan=loan, reversal__isnull=True
    ).order_by("disbursed_on", "confirmed_at")
    earliest_remaining = remaining_postings.first()
    loan.disbursed_amount = net_after or None
    if net_after == ZERO:
        loan.disbursement_date = None
        loan.disbursement_confirmed_at = None
        loan.status = LoanStatus.PROCESSING
    elif earliest_remaining:
        loan.disbursement_date = earliest_remaining.disbursed_on
        loan.disbursement_confirmed_at = earliest_remaining.confirmed_at
    loan.save(
        update_fields=[
            "disbursed_amount",
            "disbursement_date",
            "disbursement_confirmed_at",
            "status",
            "updated_at",
        ]
    )
    allocation = FundingFacilityAllocation.objects.select_for_update().get(
        id=posting.allocation_id
    )
    allocation.status = FacilityAllocationStatus.RESERVED
    allocation.save(update_fields=["status", "updated_at"])
    _audit(
        "bt.loan.disbursement_reversed",
        reversal,
        principal,
        {"disbursementId": posting.id, "amount": str(posting.amount)},
    )
    return reversal


@transaction.atomic
def create_repayment_schedule(
    loan_id: str, installments: list[dict], principal, *, version: int = 1
) -> list[LoanRepaymentInstallment]:
    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_LOAN_WRITE,
        "Only an authorized lending-partner operator may create a repayment schedule.",
    )
    loan = MfiLoan.objects.select_for_update().filter(id=loan_id).first()
    if loan is None:
        raise NotFoundError("School loan not found.")
    _assert_loan_scope(principal, loan)
    if version <= 0 or not installments:
        raise BadRequest("A positive schedule version and installments are required.")
    existing = list(
        LoanRepaymentInstallment.objects.filter(
            loan=loan, schedule_version=version
        ).order_by("installment_number")
    )
    if existing:
        return existing
    net_disbursed = _net_disbursed_for_loan(loan)
    if net_disbursed <= ZERO:
        raise ConflictError("A repayment schedule requires a confirmed disbursement.")
    rows = []
    principal_total = ZERO
    seen_numbers = set()
    for raw in installments:
        number = int(raw.get("installmentNumber") or 0)
        if number <= 0 or number in seen_numbers:
            raise BadRequest("Installment numbers must be unique positive integers.")
        seen_numbers.add(number)
        principal_due = _money(
            raw.get("principalDue", 0), field="Principal due", allow_zero=True
        )
        interest_due = _money(
            raw.get("interestDue", 0), field="Interest due", allow_zero=True
        )
        fee_due = _money(raw.get("feeDue", 0), field="Fee due", allow_zero=True)
        if principal_due + interest_due + fee_due <= ZERO:
            raise BadRequest("Each installment must contain an amount due.")
        principal_total += principal_due
        rows.append(
            LoanRepaymentInstallment(
                loan=loan,
                schedule_version=version,
                installment_number=number,
                due_date=_date(raw.get("dueDate"), field="Installment due date"),
                principal_due=principal_due,
                interest_due=interest_due,
                fee_due=fee_due,
                created_by=_actor_id(principal),
            )
        )
    if principal_total != net_disbursed:
        raise BadRequest(
            "Scheduled principal must equal confirmed net disbursed principal."
        )
    # bulk_create bypasses model save by design, so create each immutable row
    # through its guarded save while retaining one surrounding transaction.
    created = []
    for row in rows:
        row.save(force_insert=True)
        created.append(row)
    _audit(
        "bt.loan.repayment_schedule_created",
        loan,
        principal,
        {
            "version": version,
            "installmentCount": len(created),
            "principal": str(principal_total),
        },
    )
    return created


def _component_due(installment: LoanRepaymentInstallment, component: str) -> Decimal:
    return {
        RepaymentComponent.PRINCIPAL: installment.principal_due,
        RepaymentComponent.INTEREST: installment.interest_due,
        RepaymentComponent.FEE: installment.fee_due,
        RepaymentComponent.PENALTY: Decimal("Infinity"),
    }[component]


def _net_allocated(
    installment: LoanRepaymentInstallment, component: str, *, as_of: date | None = None
) -> Decimal:
    qs = RepaymentAllocation.objects.filter(
        installment=installment, component=component
    )
    if as_of:
        qs = qs.filter(transaction__value_date__lte=as_of)
    paid = (
        qs.filter(transaction__kind=RepaymentTransactionKind.PAYMENT).aggregate(
            total=Sum("amount")
        )["total"]
        or ZERO
    )
    reversed_amount = (
        qs.filter(transaction__kind=RepaymentTransactionKind.REVERSAL).aggregate(
            total=Sum("amount")
        )["total"]
        or ZERO
    )
    return paid - reversed_amount


@transaction.atomic
def post_repayment_transaction(data: dict, principal) -> RepaymentTransaction:
    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_REPAYMENT_WRITE,
        "Only an authorized lending-partner operator may post a repayment.",
    )
    loan = (
        MfiLoan.objects.select_for_update()
        .filter(id=_text(data, "loanId", "School loan"))
        .first()
    )
    if loan is None:
        raise NotFoundError("School loan not found.")
    _assert_loan_scope(principal, loan)
    if _net_disbursed_for_loan(loan) <= ZERO:
        raise ConflictError("Repayment can be posted only after disbursement.")
    key = _text(data, "idempotencyKey", "Idempotency key")
    amount = _money(data.get("amount"), field="Repayment amount")
    existing = RepaymentTransaction.objects.filter(idempotency_key=key).first()
    if existing:
        if existing.loan_id != loan.id or not _same_money(existing.amount, amount):
            raise ConflictError(
                "Idempotency key was already used for another repayment."
            )
        return existing
    external_reference = _text(data, "externalReference", "Repayment reference")
    if RepaymentTransaction.objects.filter(
        loan=loan, external_reference=external_reference
    ).exists():
        raise ConflictError("That repayment reference already exists for this loan.")
    raw_allocations = data.get("allocations") or []
    if not isinstance(raw_allocations, list) or not raw_allocations:
        raise BadRequest("At least one repayment allocation is required.")
    parsed_allocations = []
    allocated_total = ZERO
    seen = set()
    for raw in raw_allocations:
        installment = (
            LoanRepaymentInstallment.objects.select_for_update()
            .filter(id=raw.get("installmentId"), loan=loan)
            .first()
        )
        if installment is None:
            raise BadRequest("Every allocation must reference this loan's schedule.")
        component = str(raw.get("component") or "").strip()
        if component not in RepaymentComponent.values:
            raise BadRequest("Unknown repayment component.")
        identity = (installment.id, component)
        if identity in seen:
            raise BadRequest("A component may appear only once per transaction.")
        seen.add(identity)
        allocation_amount = _money(raw.get("amount"), field="Allocation amount")
        due = _component_due(installment, component)
        if component != RepaymentComponent.PENALTY:
            already_allocated = _net_allocated(installment, component)
            if already_allocated + allocation_amount > due:
                raise BadRequest("Allocation would exceed the scheduled component due.")
        allocated_total += allocation_amount
        parsed_allocations.append((installment, component, allocation_amount))
    if allocated_total != amount:
        raise BadRequest(
            "Repayment allocations must exactly equal the transaction amount."
        )
    principal_in_payment = sum(
        (
            allocation_amount
            for _, component, allocation_amount in parsed_allocations
            if component == RepaymentComponent.PRINCIPAL
        ),
        ZERO,
    )
    if _net_principal_repaid(loan) + principal_in_payment > _net_disbursed_for_loan(
        loan
    ):
        raise BadRequest("Principal repayment cannot exceed net disbursed principal.")
    received_on = _date(data.get("receivedOn"), field="Receipt date")
    value_date = _date(data.get("valueDate"), field="Value date")
    if received_on > timezone.localdate() or value_date > timezone.localdate():
        raise BadRequest("Repayment dates cannot be in the future.")
    first_disbursement = (
        LoanDisbursement.objects.filter(loan=loan, reversal__isnull=True)
        .order_by("value_date")
        .first()
    )
    if first_disbursement and value_date < first_disbursement.value_date:
        raise BadRequest("Repayment value date cannot precede loan disbursement.")
    posting = RepaymentTransaction.objects.create(
        loan=loan,
        kind=RepaymentTransactionKind.PAYMENT,
        external_reference=external_reference,
        idempotency_key=key,
        amount=amount,
        received_on=received_on,
        value_date=value_date,
        evidence_reference=_text(data, "evidenceReference", "Repayment evidence"),
        posted_by=_actor_id(principal),
        posted_at=timezone.now(),
    )
    for installment, component, allocation_amount in parsed_allocations:
        RepaymentAllocation.objects.create(
            transaction=posting,
            installment=installment,
            component=component,
            amount=allocation_amount,
        )
    loan.last_repayment_data_date = max(
        value_date, loan.last_repayment_data_date or value_date
    )
    if _net_principal_repaid(loan) == _net_disbursed_for_loan(loan):
        loan.status = LoanStatus.REPAID
    elif loan.status == LoanStatus.DISBURSED:
        loan.status = LoanStatus.ACTIVE
    loan.save(update_fields=["last_repayment_data_date", "status", "updated_at"])
    _audit(
        "bt.loan.repayment_posted",
        posting,
        principal,
        {
            "loanId": loan.id,
            "amount": str(amount),
            "principal": str(principal_in_payment),
            "allocationCount": len(parsed_allocations),
        },
    )
    return posting


@transaction.atomic
def reverse_repayment_transaction(
    transaction_id: str, data: dict, principal
) -> RepaymentTransaction:
    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_REPAYMENT_REVERSE,
        "Only a Lending Partner Admin may reverse a repayment.",
    )
    original = (
        RepaymentTransaction.objects.select_for_update()
        .prefetch_related("allocations")
        .filter(id=transaction_id, kind=RepaymentTransactionKind.PAYMENT)
        .first()
    )
    if original is None:
        raise NotFoundError("Repayment transaction not found.")
    _assert_loan_scope(principal, original.loan)
    key = _text(data, "idempotencyKey", "Idempotency key")
    existing = RepaymentTransaction.objects.filter(idempotency_key=key).first()
    if existing:
        if existing.reversal_of_id != original.id:
            raise ConflictError(
                "Idempotency key was already used for another reversal."
            )
        return existing
    if RepaymentTransaction.objects.filter(reversal_of=original).exists():
        raise ConflictError("This repayment has already been reversed.")
    reason = _text(data, "reason", "Reversal reason")
    now = timezone.now()
    reversal = RepaymentTransaction.objects.create(
        loan=original.loan,
        kind=RepaymentTransactionKind.REVERSAL,
        reversal_of=original,
        external_reference=_text(data, "externalReference", "Reversal reference"),
        idempotency_key=key,
        amount=original.amount,
        received_on=timezone.localdate(),
        value_date=timezone.localdate(),
        evidence_reference=_text(data, "evidenceReference", "Reversal evidence"),
        posted_by=_actor_id(principal),
        posted_at=now,
        reason=reason,
    )
    for allocation in original.allocations.all():
        RepaymentAllocation.objects.create(
            transaction=reversal,
            installment=allocation.installment,
            component=allocation.component,
            amount=allocation.amount,
        )
    loan = MfiLoan.objects.select_for_update().get(id=original.loan_id)
    if loan.status == LoanStatus.REPAID:
        loan.status = LoanStatus.ACTIVE
        loan.save(update_fields=["status", "updated_at"])
    _audit(
        "bt.loan.repayment_reversed",
        reversal,
        principal,
        {"originalTransactionId": original.id, "amount": str(original.amount)},
    )
    return reversal


def loan_position(loan: MfiLoan, *, as_of: date | None = None) -> dict:
    as_of = as_of or timezone.localdate()
    disbursed = _net_disbursed_for_loan(loan, as_of=as_of)
    principal_repaid = _net_principal_repaid(loan, as_of=as_of)
    outstanding = max(ZERO, disbursed - principal_repaid)
    latest_version = LoanRepaymentInstallment.objects.filter(loan=loan).aggregate(
        version=Max("schedule_version")
    )["version"]
    overdue = ZERO
    earliest_unpaid_due = None
    if latest_version:
        installments = LoanRepaymentInstallment.objects.filter(
            loan=loan, schedule_version=latest_version, due_date__lte=as_of
        ).order_by("due_date", "installment_number")
        for installment in installments:
            remaining = ZERO
            for component in (
                RepaymentComponent.PRINCIPAL,
                RepaymentComponent.INTEREST,
                RepaymentComponent.FEE,
            ):
                remaining += max(
                    ZERO,
                    _component_due(installment, component)
                    - _net_allocated(installment, component, as_of=as_of),
                )
            if remaining > ZERO:
                overdue += remaining
                earliest_unpaid_due = earliest_unpaid_due or installment.due_date
    days_past_due = (
        max(0, (as_of - earliest_unpaid_due).days) if earliest_unpaid_due else 0
    )
    return {
        "asOf": as_of,
        "netDisbursedPrincipal": disbursed,
        "principalRepaid": principal_repaid,
        "outstandingPrincipal": outstanding,
        "amountOverdue": overdue,
        "daysPastDue": days_past_due,
        "scheduleVersion": latest_version,
    }


def reconcile_facility(facility: FundingFacility) -> dict:
    """Return a deterministic control report for one facility.

    ``difference`` is the independently restated source side less every use and
    remaining balance.  A non-zero value or any issue is a release blocker.
    """

    position = facility_position(facility)
    source_total = position["confirmedReceipts"] + position["recycledPrincipal"]
    use_total = (
        position["confirmedDisbursements"]
        + position["reservedAllocations"]
        + position["authorizedDeductions"]
        + position["capitalReturned"]
        + position["available"]
    )
    difference = source_total - use_total
    issues = []
    if position["confirmedReceipts"] > position["commitment"]:
        issues.append("receipts_exceed_commitment")
    if position["available"] < ZERO:
        issues.append("negative_available_balance")
    if position["originalCapitalRemaining"] < ZERO:
        issues.append("negative_original_capital_balance")
    if position["recoveredPrincipalAvailableForRelending"] < ZERO:
        issues.append("negative_recovered_capital_balance")
    mismatched_allocations = FundingFacilityAllocation.objects.filter(
        facility=facility
    ).exclude(loan__mfi_id=facility.mfi_id)
    if mismatched_allocations.exists():
        issues.append("allocation_lending_partner_mismatch")
    if (
        FundingFacilityAllocation.objects.filter(facility=facility)
        .exclude(loan__currency=facility.currency)
        .exists()
    ):
        issues.append("allocation_currency_mismatch")
    if difference != ZERO:
        issues.append("facility_identity_difference")
    return {
        **position,
        "sourceTotal": source_total,
        "useAndBalanceTotal": use_total,
        "difference": difference,
        "issues": issues,
        "reconciled": not issues,
    }


def reconcile_loan(loan: MfiLoan, *, as_of: date | None = None) -> dict:
    """Restate one loan from postings and expose every broken invariant."""

    # Callers often hold the registration instance while financial postings are
    # created in a separate service call. Reconciliation must compare against
    # the persisted projection, never a potentially stale Python object.
    loan = MfiLoan.objects.select_related("facility").get(pk=loan.pk)
    position = loan_position(loan, as_of=as_of)
    approved = loan.approved_amount or ZERO
    planned_purpose = (
        LoanPurposeAllocation.objects.filter(loan=loan).aggregate(
            total=Sum("planned_amount")
        )["total"]
        or ZERO
    )
    reported_purpose = (
        LoanPurposeAllocation.objects.filter(loan=loan).aggregate(
            total=Sum("reported_amount")
        )["total"]
        or ZERO
    )
    latest_version = position["scheduleVersion"]
    scheduled_principal = ZERO
    if latest_version:
        scheduled_principal = (
            LoanRepaymentInstallment.objects.filter(
                loan=loan, schedule_version=latest_version
            ).aggregate(total=Sum("principal_due"))["total"]
            or ZERO
        )
    allocation = FundingFacilityAllocation.objects.filter(loan=loan).first()
    issues = []
    if position["netDisbursedPrincipal"] > approved:
        issues.append("disbursed_exceeds_approved")
    if allocation is None and position["netDisbursedPrincipal"]:
        issues.append("disbursement_without_facility_allocation")
    if allocation and position["netDisbursedPrincipal"] > allocation.amount:
        issues.append("disbursed_exceeds_allocation")
    if allocation and (
        allocation.facility_id != loan.facility_id
        or allocation.facility.mfi_id != loan.mfi_id
        or allocation.facility.currency != loan.currency
    ):
        issues.append("facility_allocation_mismatch")
    if planned_purpose and planned_purpose != approved:
        issues.append("planned_purpose_does_not_equal_approved")
    if reported_purpose and reported_purpose != position["netDisbursedPrincipal"]:
        issues.append("reported_purpose_does_not_equal_disbursed")
    if latest_version and scheduled_principal != position["netDisbursedPrincipal"]:
        issues.append("schedule_principal_does_not_equal_disbursed")
    projected_disbursed = loan.disbursed_amount or ZERO
    if projected_disbursed != position["netDisbursedPrincipal"]:
        issues.append("loan_disbursed_projection_drift")
    if loan.status == LoanStatus.REPAID and position["outstandingPrincipal"] != ZERO:
        issues.append("repaid_loan_has_outstanding_principal")
    if loan.status == LoanStatus.CANCELED and position["netDisbursedPrincipal"] != ZERO:
        issues.append("canceled_loan_has_disbursement")
    return {
        "loanId": loan.id,
        "requested": loan.requested_amount,
        "approved": loan.approved_amount,
        "facilityAllocation": allocation.amount if allocation else None,
        "plannedPurpose": planned_purpose,
        "reportedPurpose": reported_purpose,
        "scheduledPrincipal": scheduled_principal,
        **position,
        "issues": issues,
        "reconciled": not issues,
    }


def portfolio_ratios(
    loans, *, period_start: date, period_end: date, as_of=None
) -> dict:
    """Compute portfolio ratios in a fixed query budget, independent of loan count."""

    as_of = as_of or period_end
    loan_ids = (
        list(loans.values_list("id", flat=True))
        if hasattr(loans, "values_list")
        else [loan.id for loan in loans]
    )
    if not loan_ids:
        return {
            "totalOutstandingPrincipal": ZERO,
            "par30Principal": ZERO,
            "par90Principal": ZERO,
            "par30Pct": None,
            "par90Pct": None,
            "amountDue": ZERO,
            "amountCollected": ZERO,
            "collectionRatePct": None,
            "installmentsDue": 0,
            "installmentsPaidOnTime": 0,
            "onTimeRatePct": None,
        }

    disbursed_by_loan = {
        row["loan_id"]: row["total"] or ZERO
        for row in LoanDisbursement.objects.filter(
            loan_id__in=loan_ids,
            value_date__lte=as_of,
            reversal__isnull=True,
        )
        .values("loan_id")
        .annotate(total=Sum("amount"))
    }
    principal_rows = (
        RepaymentAllocation.objects.filter(
            transaction__loan_id__in=loan_ids,
            transaction__value_date__lte=as_of,
            component=RepaymentComponent.PRINCIPAL,
        )
        .values("transaction__loan_id")
        .annotate(
            paid=Sum(
                "amount",
                filter=Q(transaction__kind=RepaymentTransactionKind.PAYMENT),
            ),
            reversed=Sum(
                "amount",
                filter=Q(transaction__kind=RepaymentTransactionKind.REVERSAL),
            ),
        )
    )
    principal_repaid_by_loan = {
        row["transaction__loan_id"]: (row["paid"] or ZERO) - (row["reversed"] or ZERO)
        for row in principal_rows
    }
    outstanding_by_loan = {
        loan_id: max(
            ZERO,
            disbursed_by_loan.get(loan_id, ZERO)
            - principal_repaid_by_loan.get(loan_id, ZERO),
        )
        for loan_id in loan_ids
    }
    total_outstanding = sum(outstanding_by_loan.values(), ZERO)

    latest_version = (
        LoanRepaymentInstallment.objects.filter(loan_id=OuterRef("loan_id"))
        .values("loan_id")
        .annotate(version=Max("schedule_version"))
        .values("version")[:1]
    )
    installments = list(
        LoanRepaymentInstallment.objects.filter(
            loan_id__in=loan_ids,
            schedule_version=Subquery(latest_version),
            due_date__lte=max(as_of, period_end),
        ).only(
            "id",
            "loan_id",
            "due_date",
            "principal_due",
            "interest_due",
            "fee_due",
        )
    )
    installment_ids = [installment.id for installment in installments]
    allocation_rows = (
        RepaymentAllocation.objects.filter(
            installment_id__in=installment_ids,
            transaction__value_date__lte=as_of,
        )
        .values("installment_id")
        .annotate(
            paid=Sum(
                "amount",
                filter=Q(transaction__kind=RepaymentTransactionKind.PAYMENT),
            ),
            reversed=Sum(
                "amount",
                filter=Q(transaction__kind=RepaymentTransactionKind.REVERSAL),
            ),
        )
    )
    allocated_by_installment = {
        row["installment_id"]: (row["paid"] or ZERO) - (row["reversed"] or ZERO)
        for row in allocation_rows
    }
    earliest_unpaid = {}
    for installment in installments:
        if installment.due_date > as_of:
            continue
        scheduled = (
            installment.principal_due + installment.interest_due + installment.fee_due
        )
        if allocated_by_installment.get(installment.id, ZERO) < scheduled:
            current = earliest_unpaid.get(installment.loan_id)
            if current is None or installment.due_date < current:
                earliest_unpaid[installment.loan_id] = installment.due_date
    par30_principal = sum(
        (
            outstanding_by_loan[loan_id]
            for loan_id, due_date in earliest_unpaid.items()
            if (as_of - due_date).days > 30
        ),
        ZERO,
    )
    par90_principal = sum(
        (
            outstanding_by_loan[loan_id]
            for loan_id, due_date in earliest_unpaid.items()
            if (as_of - due_date).days > 90
        ),
        ZERO,
    )
    due_installments = [
        installment
        for installment in installments
        if period_start <= installment.due_date <= period_end
    ]
    due_total = sum(
        (
            installment.principal_due + installment.interest_due + installment.fee_due
            for installment in due_installments
        ),
        ZERO,
    )
    allocations = RepaymentAllocation.objects.filter(
        transaction__loan_id__in=loan_ids,
        transaction__value_date__gte=period_start,
        transaction__value_date__lte=period_end,
    )
    collected = (
        allocations.filter(
            transaction__kind=RepaymentTransactionKind.PAYMENT
        ).aggregate(total=Sum("amount"))["total"]
        or ZERO
    )
    reversed_amount = (
        allocations.filter(
            transaction__kind=RepaymentTransactionKind.REVERSAL
        ).aggregate(total=Sum("amount"))["total"]
        or ZERO
    )
    net_collected = collected - reversed_amount
    on_time_rows = (
        RepaymentAllocation.objects.filter(
            installment_id__in=[item.id for item in due_installments],
            transaction__value_date__lte=F("installment__due_date"),
        )
        .values("installment_id")
        .annotate(
            paid=Sum(
                "amount",
                filter=Q(transaction__kind=RepaymentTransactionKind.PAYMENT),
            ),
            reversed=Sum(
                "amount",
                filter=Q(transaction__kind=RepaymentTransactionKind.REVERSAL),
            ),
        )
    )
    paid_on_time = {
        row["installment_id"]: (row["paid"] or ZERO) - (row["reversed"] or ZERO)
        for row in on_time_rows
    }
    on_time = sum(
        1
        for installment in due_installments
        if paid_on_time.get(installment.id, ZERO)
        >= installment.principal_due + installment.interest_due + installment.fee_due
    )
    return {
        "totalOutstandingPrincipal": total_outstanding,
        "par30Principal": par30_principal,
        "par90Principal": par90_principal,
        "par30Pct": (
            (par30_principal / total_outstanding * 100).quantize(MONEY_QUANTUM)
            if total_outstanding
            else None
        ),
        "par90Pct": (
            (par90_principal / total_outstanding * 100).quantize(MONEY_QUANTUM)
            if total_outstanding
            else None
        ),
        "amountDue": due_total,
        "amountCollected": net_collected,
        "collectionRatePct": (
            (net_collected / due_total * 100).quantize(MONEY_QUANTUM)
            if due_total
            else None
        ),
        "installmentsDue": len(due_installments),
        "installmentsPaidOnTime": on_time,
        "onTimeRatePct": (
            (Decimal(on_time) / len(due_installments) * 100).quantize(MONEY_QUANTUM)
            if due_installments
            else None
        ),
    }


__all__ = [
    "approve_funding_facility",
    "confirm_facility_tranche",
    "create_funding_facility",
    "create_repayment_schedule",
    "facility_position",
    "loan_position",
    "portfolio_ratios",
    "post_facility_movement",
    "post_loan_disbursement",
    "post_repayment_transaction",
    "release_facility_allocation",
    "reconcile_facility",
    "reconcile_loan",
    "reserve_facility_for_loan",
    "reverse_facility_tranche",
    "reverse_facility_movement",
    "reverse_loan_disbursement",
    "reverse_repayment_transaction",
    "scoped_facilities",
    "serialize_facility",
]
