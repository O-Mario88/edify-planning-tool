from django.db import models
from django.utils import timezone
from apps.core.models import CuidField, TimeStampedModel
from apps.activities.models import Activity
from apps.fund_requests.models import FundRequest


class Disbursement(TimeStampedModel):
    id = CuidField()
    activity = models.ForeignKey(
        Activity, on_delete=models.CASCADE, related_name="disbursements"
    )
    fund_request = models.ForeignKey(
        FundRequest, on_delete=models.SET_NULL, null=True, blank=True
    )
    amount_disbursed = models.BigIntegerField()  # UGX Cents
    disbursed_at = models.DateTimeField(default=timezone.now)
    disbursed_by = models.CharField(max_length=30)
    payment_method = models.CharField(max_length=64)
    payment_reference = models.CharField(max_length=128)
    notes = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "disbursement"


class PartnerPayment(TimeStampedModel):
    id = CuidField()
    activity = models.ForeignKey(
        Activity, on_delete=models.CASCADE, related_name="partner_payments"
    )
    partner_name = models.CharField(max_length=255)
    amount_paid = models.BigIntegerField()  # UGX Cents
    payment_method = models.CharField(max_length=64)
    payment_reference = models.CharField(max_length=128)
    payment_date = models.DateTimeField(default=timezone.now)
    paid_by = models.CharField(max_length=30)
    notes = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "partner_payment"


class ReimbursementClaim(TimeStampedModel):
    id = CuidField()
    activity = models.ForeignKey(
        Activity, on_delete=models.CASCADE, related_name="reimbursement_claims"
    )
    staff_id = models.CharField(max_length=30)
    approved_budget = models.BigIntegerField()  # UGX Cents
    amount_advanced = models.BigIntegerField(default=0)  # UGX Cents
    actual_spend = models.BigIntegerField()  # UGX Cents
    reimbursement_amount = models.BigIntegerField()  # UGX Cents
    status = models.CharField(
        max_length=32, default="pending"
    )  # pending, approved, paid, returned
    payment_method = models.CharField(max_length=64, null=True, blank=True)
    payment_reference = models.CharField(max_length=128, null=True, blank=True)
    payment_date = models.DateTimeField(null=True, blank=True)
    paid_by = models.CharField(max_length=30, null=True, blank=True)
    notes = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "reimbursement_claim"


class AccountabilityRecord(TimeStampedModel):
    id = CuidField()
    activity = models.ForeignKey(
        Activity, on_delete=models.CASCADE, related_name="accountability_records"
    )
    staff_id = models.CharField(max_length=30)
    amount_disbursed = models.BigIntegerField()  # UGX Cents
    actual_spend = models.BigIntegerField()  # UGX Cents
    variance = models.BigIntegerField()  # UGX Cents
    variance_reason = models.TextField(null=True, blank=True)
    netsuite_expense_id = models.CharField(max_length=128, null=True, blank=True)
    status = models.CharField(
        max_length=32, default="pending"
    )  # pending, variance_review, cleared, returned
    submitted_at = models.DateTimeField(default=timezone.now)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.CharField(max_length=30, null=True, blank=True)
    notes = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "accountability_record"


class Receipt(TimeStampedModel):
    id = CuidField()
    accountability_record = models.ForeignKey(
        AccountabilityRecord,
        on_delete=models.CASCADE,
        related_name="receipts",
        null=True,
        blank=True,
    )
    reimbursement_claim = models.ForeignKey(
        ReimbursementClaim,
        on_delete=models.CASCADE,
        related_name="receipts",
        null=True,
        blank=True,
    )
    original_name = models.CharField(max_length=255)
    uri = models.CharField(max_length=512)
    file_size = models.BigIntegerField()
    mime_type = models.CharField(max_length=128, null=True, blank=True)
    uploaded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "finance_receipt"


class NetSuiteExpenseRecord(TimeStampedModel):
    id = CuidField()
    activity = models.ForeignKey(
        Activity, on_delete=models.CASCADE, related_name="netsuite_expenses"
    )
    netsuite_expense_id = models.CharField(max_length=128, unique=True)
    expense_date = models.DateField()
    amount_entered = models.BigIntegerField()  # UGX Cents
    entered_by = models.CharField(max_length=30)
    notes = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "netsuite_expense_record"


class FinanceReturn(TimeStampedModel):
    id = CuidField()
    activity = models.ForeignKey(
        Activity, on_delete=models.CASCADE, related_name="finance_returns"
    )
    returned_to = models.CharField(max_length=30)
    returned_by = models.CharField(max_length=30)
    reason = models.TextField()
    returned_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(
        max_length=32, default="pending"
    )  # pending, fixed, resolved

    class Meta:
        db_table = "finance_return"


class VarianceReview(TimeStampedModel):
    id = CuidField()
    activity = models.ForeignKey(
        Activity, on_delete=models.CASCADE, related_name="variance_reviews"
    )
    budgeted_amount = models.BigIntegerField()  # UGX Cents
    disbursed_amount = models.BigIntegerField()  # UGX Cents
    actual_spend = models.BigIntegerField()  # UGX Cents
    variance = models.BigIntegerField()  # UGX Cents
    reason = models.TextField()
    status = models.CharField(
        max_length=32, default="pending"
    )  # pending, approved, refund_required, resolved
    reviewed_by = models.CharField(max_length=30, null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "variance_review"


class FinanceAuditLog(TimeStampedModel):
    id = CuidField()
    activity = models.ForeignKey(
        Activity,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="finance_audit_logs",
    )
    event_type = models.CharField(
        max_length=64
    )  # e.g., disbursement, partner_paid, reimbursement, accountability_cleared
    actor_id = models.CharField(max_length=30)
    actor_role = models.CharField(max_length=64)
    old_value = models.TextField(null=True, blank=True)
    new_value = models.TextField(null=True, blank=True)
    timestamp = models.DateTimeField(default=timezone.now)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        db_table = "finance_audit_log"
