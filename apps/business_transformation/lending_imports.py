"""Secure staged CSV imports for certified lending-partner repayments."""

from __future__ import annotations

import csv
import hashlib
import io
import tempfile
from decimal import Decimal

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.audit.services import log as audit_log
from apps.core.exceptions import BadRequest, ConflictError, Forbidden, NotFoundError
from apps.core.permissions import has_permission
from apps.core.rbac import Permission

from .lending_ledger import _actor_id, _assert_mfi_scope, _date, _money
from .models import (
    LoanRepaymentInstallment,
    MfiLoan,
    MfiOrganization,
    PortfolioDataException,
    PortfolioImportRow,
    PortfolioImportRowStatus,
    PortfolioSubmission,
    PortfolioSubmissionStatus,
)

MAX_IMPORT_BYTES = 10 * 1024 * 1024
MAX_IMPORT_ROWS = 10_000
REQUIRED_COLUMNS = {
    "loan_reference",
    "payment_reference",
    "payment_date",
    "installment_number",
    "total_amount",
    "principal_amount",
    "interest_amount",
    "fee_amount",
    "penalty_amount",
    "evidence_reference",
}
COMPONENT_COLUMNS = {
    "principal": "principal_amount",
    "interest": "interest_amount",
    "fee": "fee_amount",
    "penalty": "penalty_amount",
}


def _require(principal, permission: Permission, message: str) -> None:
    if not has_permission(principal, permission.value):
        raise Forbidden(message)


def _audit(
    action: str, submission: PortfolioSubmission, principal, payload: dict
) -> None:
    audit_log(
        action=action,
        subject_kind="PortfolioSubmission",
        subject_id=str(submission.id),
        actor_id=_actor_id(principal),
        actor_role=getattr(principal, "active_role", None),
        payload=payload,
        required=True,
    )


def _whole_number(value, *, field: str) -> int:
    try:
        parsed = int(str(value or "").strip())
    except (TypeError, ValueError) as exc:
        raise BadRequest(f"{field} must be a whole number.") from exc
    if parsed <= 0:
        raise BadRequest(f"{field} must be greater than zero.")
    return parsed


@transaction.atomic
def stage_repayment_csv(
    *,
    mfi_id: str,
    reporting_month,
    filename: str,
    content: bytes,
    principal,
) -> PortfolioSubmission:
    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_REPAYMENT_WRITE,
        "Only an authorized lending-partner operator may stage repayment data.",
    )
    _assert_mfi_scope(principal, mfi_id)
    mfi = MfiOrganization.objects.filter(id=mfi_id, active=True).first()
    if mfi is None:
        raise NotFoundError("Lending partner not found.")
    if not filename.lower().endswith(".csv"):
        raise BadRequest("Repayment imports must be CSV files.")
    if not content or len(content) > MAX_IMPORT_BYTES:
        raise BadRequest("Import file is empty or exceeds the 10 MB limit.")
    from apps.evidence.services import _scan_upload

    with tempfile.NamedTemporaryFile(suffix=".csv") as staged_file:
        staged_file.write(content)
        staged_file.flush()
        scan_status, threat = _scan_upload(staged_file.name)
    if scan_status == "infected":
        raise BadRequest(f"Import file was quarantined by malware scanning: {threat}.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise BadRequest("Import file must use UTF-8 encoding.") from exc
    digest = hashlib.sha256(content).hexdigest()
    month = _date(reporting_month, field="Reporting month").replace(day=1)
    existing = PortfolioSubmission.objects.filter(
        mfi=mfi, reporting_month=month, file_sha256=digest
    ).first()
    if existing:
        return existing
    reader = csv.DictReader(io.StringIO(text))
    columns = {str(value or "").strip() for value in (reader.fieldnames or [])}
    missing_columns = sorted(REQUIRED_COLUMNS - columns)
    if missing_columns:
        raise BadRequest("Missing required columns: " + ", ".join(missing_columns))
    rows = list(reader)
    if not rows or len(rows) > MAX_IMPORT_ROWS:
        raise BadRequest("Import must contain between 1 and 10,000 data rows.")
    submission = PortfolioSubmission.objects.create(
        mfi=mfi,
        reporting_month=month,
        source_type="spreadsheet",
        source_file_name=filename[:255],
        file_sha256=digest,
        total_rows=len(rows),
        submitted_by=_actor_id(principal),
    )
    valid_rows = 0
    for row_number, raw in enumerate(rows, start=2):
        raw_data = {str(key): str(value or "").strip() for key, value in raw.items()}
        errors = []
        normalized = {}
        loan = MfiLoan.objects.filter(
            mfi=mfi,
            external_loan_reference=raw_data.get("loan_reference", ""),
        ).first()
        if loan is None:
            errors.append("loan_not_found")
        try:
            payment_date = _date(raw_data.get("payment_date"), field="Payment date")
            if payment_date > timezone.localdate():
                raise BadRequest("Payment date cannot be in the future.")
            installment_number = _whole_number(
                raw_data.get("installment_number"), field="Installment number"
            )
            total = _money(raw_data.get("total_amount"), field="Total amount")
            components = {
                component: _money(
                    raw_data.get(column, "0"),
                    field=column,
                    allow_zero=True,
                )
                for component, column in COMPONENT_COLUMNS.items()
            }
            if sum(components.values(), Decimal("0.00")) != total:
                raise BadRequest("Repayment components must equal total amount.")
            if not raw_data.get("payment_reference"):
                raise BadRequest("Payment reference is required.")
            if not raw_data.get("evidence_reference"):
                raise BadRequest("Evidence reference is required.")
            installment = None
            if loan:
                latest_version = LoanRepaymentInstallment.objects.filter(
                    loan=loan
                ).aggregate(version=Max("schedule_version"))["version"]
                installment = LoanRepaymentInstallment.objects.filter(
                    loan=loan,
                    schedule_version=latest_version,
                    installment_number=installment_number,
                ).first()
                if installment is None:
                    raise BadRequest(
                        "Installment was not found on the current schedule."
                    )
            normalized = {
                "loanId": loan.id if loan else None,
                "installmentId": installment.id if installment else None,
                "paymentReference": raw_data["payment_reference"],
                "paymentDate": payment_date.isoformat(),
                "totalAmount": str(total),
                "components": {
                    component: str(amount) for component, amount in components.items()
                },
                "evidenceReference": raw_data["evidence_reference"],
            }
        except BadRequest as exc:
            errors.append(str(exc))
        status = (
            PortfolioImportRowStatus.INVALID
            if errors
            else PortfolioImportRowStatus.VALID
        )
        staged = PortfolioImportRow.objects.create(
            submission=submission,
            row_number=row_number,
            raw_data=raw_data,
            normalized_data=normalized,
            status=status,
            error_codes=errors,
            idempotency_key=f"portfolio-import:{digest}:{row_number}",
            loan=loan,
        )
        if errors:
            PortfolioDataException.objects.create(
                submission=submission,
                row_number=row_number,
                code="row_validation_failed",
                message="; ".join(errors),
                context={"importRowId": staged.id},
            )
        else:
            valid_rows += 1
    submission.valid_rows = valid_rows
    submission.exception_rows = len(rows) - valid_rows
    submission.status = (
        PortfolioSubmissionStatus.NEEDS_CORRECTION
        if submission.exception_rows
        else PortfolioSubmissionStatus.STAGED
    )
    submission.save(
        update_fields=[
            "valid_rows",
            "exception_rows",
            "status",
            "updated_at",
        ]
    )
    _audit(
        "bt.portfolio_import.staged",
        submission,
        principal,
        {
            "sha256": digest,
            "rows": len(rows),
            "validRows": valid_rows,
            "exceptionRows": submission.exception_rows,
        },
    )
    return submission


@transaction.atomic
def apply_repayment_import(submission_id: str, principal) -> PortfolioSubmission:
    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_REPAYMENT_WRITE,
        "Only an authorized lending-partner operator may apply repayment data.",
    )
    submission = PortfolioSubmission.objects.filter(id=submission_id).first()
    if submission is None:
        raise NotFoundError("Portfolio submission not found.")
    _assert_mfi_scope(principal, submission.mfi_id)
    if submission.status == PortfolioSubmissionStatus.CERTIFIED:
        raise Forbidden("A certified portfolio return is immutable.")
    from .lending_ledger import post_repayment_transaction

    for row in submission.rows.filter(status=PortfolioImportRowStatus.VALID):
        normalized = row.normalized_data
        allocations = [
            {
                "installmentId": normalized["installmentId"],
                "component": component,
                "amount": amount,
            }
            for component, amount in normalized["components"].items()
            if Decimal(amount) > 0
        ]
        try:
            posting = post_repayment_transaction(
                {
                    "loanId": normalized["loanId"],
                    "externalReference": normalized["paymentReference"],
                    "idempotencyKey": row.idempotency_key,
                    "amount": normalized["totalAmount"],
                    "receivedOn": normalized["paymentDate"],
                    "valueDate": normalized["paymentDate"],
                    "evidenceReference": normalized["evidenceReference"],
                    "allocations": allocations,
                },
                principal,
            )
        except (BadRequest, ConflictError, Forbidden, NotFoundError) as exc:
            row.status = PortfolioImportRowStatus.INVALID
            row.error_codes = [str(exc)]
            row.save(update_fields=["status", "error_codes", "updated_at"])
            PortfolioDataException.objects.get_or_create(
                submission=submission,
                row_number=row.row_number,
                code="posting_failed",
                defaults={
                    "message": str(exc),
                    "context": {"importRowId": row.id},
                },
            )
            continue
        row.status = PortfolioImportRowStatus.APPLIED
        row.repayment_transaction = posting
        row.save(update_fields=["status", "repayment_transaction", "updated_at"])
    invalid = submission.rows.filter(status=PortfolioImportRowStatus.INVALID).count()
    applied = submission.rows.filter(status=PortfolioImportRowStatus.APPLIED).count()
    submission.valid_rows = applied
    submission.exception_rows = invalid
    submission.status = (
        PortfolioSubmissionStatus.NEEDS_CORRECTION
        if invalid
        else PortfolioSubmissionStatus.IMPORTED
    )
    submission.save(
        update_fields=[
            "valid_rows",
            "exception_rows",
            "status",
            "updated_at",
        ]
    )
    _audit(
        "bt.portfolio_import.applied",
        submission,
        principal,
        {"appliedRows": applied, "exceptionRows": invalid},
    )
    return submission


@transaction.atomic
def certify_portfolio_submission(submission_id: str, principal) -> PortfolioSubmission:
    _require(
        principal,
        Permission.BUSINESS_TRANSFORMATION_PORTFOLIO_CERTIFY,
        "Only a Lending Partner Administrator may certify the monthly return.",
    )
    submission = (
        PortfolioSubmission.objects.select_for_update().filter(id=submission_id).first()
    )
    if submission is None:
        raise NotFoundError("Portfolio submission not found.")
    from .services import _assert_mfi_scope as assert_mfi_admin_scope

    assert_mfi_admin_scope(principal, submission.mfi_id, admin_only=True)
    if submission.status == PortfolioSubmissionStatus.CERTIFIED:
        return submission
    if (
        submission.status != PortfolioSubmissionStatus.IMPORTED
        or submission.exception_rows
        or submission.exceptions.filter(status="open").exists()
        or submission.rows.exclude(status=PortfolioImportRowStatus.APPLIED).exists()
    ):
        raise BadRequest("Resolve every row-level exception before certification.")
    submission.status = PortfolioSubmissionStatus.CERTIFIED
    submission.certified_by = _actor_id(principal)
    submission.certified_at = timezone.now()
    submission.save(
        update_fields=["status", "certified_by", "certified_at", "updated_at"]
    )
    _audit(
        "bt.portfolio_import.certified",
        submission,
        principal,
        {"reportingMonth": submission.reporting_month.isoformat()},
    )
    return submission


__all__ = [
    "apply_repayment_import",
    "certify_portfolio_submission",
    "stage_repayment_csv",
]
