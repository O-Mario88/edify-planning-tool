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
    amount_disbursed = (
        models.BigIntegerField()
    )  # UGX (plain shillings, not cents -- see apps/budget/models.py CostSetting)
    disbursed_at = models.DateTimeField(default=timezone.now)
    disbursed_by = models.CharField(max_length=30)
    payment_method = models.CharField(max_length=64)
    payment_reference = models.CharField(max_length=128)
    notes = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "disbursement"


class PartnerPayment(TimeStampedModel):
    # The partner MOU pays in two instalments: 50% of the planned activity
    # cost up front, and the balance cleared once the partner finishes the
    # work and IA verifies it. Historical single payments predate the MOU
    # split and are clearances (they were terminal).
    TYPE_ADVANCE = "advance"
    TYPE_CLEARANCE = "clearance"
    PAYMENT_TYPE_CHOICES = [
        (TYPE_ADVANCE, "50% MOU Advance"),
        (TYPE_CLEARANCE, "Clearance"),
    ]

    id = CuidField()
    activity = models.ForeignKey(
        Activity, on_delete=models.CASCADE, related_name="partner_payments"
    )
    partner_name = models.CharField(max_length=255)
    payment_type = models.CharField(
        max_length=16, choices=PAYMENT_TYPE_CHOICES, default=TYPE_CLEARANCE
    )
    amount_paid = (
        models.BigIntegerField()
    )  # UGX (plain shillings, not cents -- see apps/budget/models.py CostSetting)
    payment_method = models.CharField(max_length=64)
    payment_reference = models.CharField(max_length=128)
    payment_date = models.DateTimeField(default=timezone.now)
    paid_by = models.CharField(max_length=30)
    notes = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "partner_payment"
        constraints = [
            # One payout per activity AND instalment — the concurrency
            # backstop for the pay_partner idempotency guard. A duplicate row
            # here is a double-counted partner payment.
            models.UniqueConstraint(
                fields=["activity", "payment_type"],
                name="uniq_partner_payment_per_activity_type",
            ),
        ]


class ReimbursementClaim(TimeStampedModel):
    id = CuidField()
    activity = models.ForeignKey(
        Activity, on_delete=models.CASCADE, related_name="reimbursement_claims"
    )
    staff_id = models.CharField(max_length=30)
    approved_budget = (
        models.BigIntegerField()
    )  # UGX (plain shillings, not cents -- see apps/budget/models.py CostSetting)
    amount_advanced = models.BigIntegerField(
        default=0
    )  # UGX (plain shillings, not cents -- see apps/budget/models.py CostSetting)
    actual_spend = (
        models.BigIntegerField()
    )  # UGX (plain shillings, not cents -- see apps/budget/models.py CostSetting)
    reimbursement_amount = (
        models.BigIntegerField()
    )  # UGX (plain shillings, not cents -- see apps/budget/models.py CostSetting)
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
    amount_disbursed = (
        models.BigIntegerField()
    )  # UGX (plain shillings, not cents -- see apps/budget/models.py CostSetting)
    actual_spend = (
        models.BigIntegerField()
    )  # UGX (plain shillings, not cents -- see apps/budget/models.py CostSetting)
    variance = (
        models.BigIntegerField()
    )  # UGX (plain shillings, not cents -- see apps/budget/models.py CostSetting)
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
    amount_entered = (
        models.BigIntegerField()
    )  # UGX (plain shillings, not cents -- see apps/budget/models.py CostSetting)
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
    budgeted_amount = (
        models.BigIntegerField()
    )  # UGX (plain shillings, not cents -- see apps/budget/models.py CostSetting)
    disbursed_amount = (
        models.BigIntegerField()
    )  # UGX (plain shillings, not cents -- see apps/budget/models.py CostSetting)
    actual_spend = (
        models.BigIntegerField()
    )  # UGX (plain shillings, not cents -- see apps/budget/models.py CostSetting)
    variance = (
        models.BigIntegerField()
    )  # UGX (plain shillings, not cents -- see apps/budget/models.py CostSetting)
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


class TransportPayment(TimeStampedModel):
    """§9.1 — the transport company's payment obligation for one mission day.

    Transport is never part of the staff advance: one vendor payment per
    day-batch, never combined with the CCEO's allowance transfer. The CCEO
    sees only arrangement/confirmation status — no amount.
    """

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("paid", "Paid"),
        ("failed", "Failed"),
    ]

    id = CuidField()
    batch = models.OneToOneField(
        "daily_visit_batches.DailyVisitBatch",
        on_delete=models.CASCADE,
        related_name="transport_payment",
    )
    provider_name = models.CharField(max_length=255)
    amount = models.BigIntegerField()  # UGX — the day's transport component
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="pending")
    payment_method = models.CharField(max_length=64, blank=True, default="")
    payment_reference = models.CharField(max_length=128, blank=True, default="")
    netsuite_expense_id = models.CharField(max_length=128, blank=True, default="")
    paid_by = models.CharField(max_length=30, null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")

    class Meta:
        db_table = "transport_payment"


class PartnerInvoice(TimeStampedModel):
    """A partner's PERIOD invoice — one invoice sums all their planned
    activity costs for a week, month or quarter, grouped by category
    (School Visits, Training facilitation). The entered amount must equal
    the system-fetched period total — that equality links the invoice to
    the plan. Routing: the partner submits to their Program Lead, the PL
    confirms the invoice against the plan, and only then does the
    accountant download and pay the instalment (50% first; the balance
    once IA has cleared the work).
    """

    TYPE_ADVANCE = "advance"
    TYPE_CLEARANCE = "clearance"
    TYPE_CHOICES = [
        (TYPE_ADVANCE, "50% Advance Invoice"),
        (TYPE_CLEARANCE, "Clearance Invoice"),
    ]
    STATUS_CHOICES = [
        ("submitted_to_pl", "With Program Lead"),
        ("confirmed_by_pl", "PL-confirmed — awaiting payment"),
        ("returned_by_pl", "Returned by Program Lead"),
        ("paid", "Paid"),
    ]
    PERIOD_CHOICES = [
        ("week", "Week"),
        ("month", "Month"),
        ("quarter", "Quarter"),
    ]

    id = CuidField()
    partner_id = models.CharField(max_length=30, db_index=True)
    invoice_type = models.CharField(max_length=16, choices=TYPE_CHOICES)
    period_kind = models.CharField(max_length=12, choices=PERIOD_CHOICES)
    period_start = models.DateField()
    period_end = models.DateField()
    # The system-fetched planned total for the invoiced work.
    system_total = models.BigIntegerField()
    entered_total = models.BigIntegerField()  # must equal system_total
    payable_amount = models.BigIntegerField()  # 50% or the balance
    stored_name = models.CharField(max_length=255)
    original_name = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=128, blank=True, default="")
    file_size = models.BigIntegerField(default=0)
    status = models.CharField(
        max_length=24, choices=STATUS_CHOICES, default="submitted_to_pl"
    )
    submitted_by = models.CharField(max_length=30)
    pl_confirmed_by = models.CharField(max_length=30, null=True, blank=True)
    pl_confirmed_at = models.DateTimeField(null=True, blank=True)
    pl_note = models.CharField(max_length=512, blank=True, default="")

    class Meta:
        db_table = "partner_invoice"


class PartnerInvoiceItem(TimeStampedModel):
    """One activity's share of a period invoice. The per-activity instalment
    uniqueness lives here: an activity's advance (or clearance) can appear on
    exactly one invoice, whatever period that invoice covers."""

    id = CuidField()
    invoice = models.ForeignKey(
        PartnerInvoice, on_delete=models.CASCADE, related_name="items"
    )
    activity = models.ForeignKey(
        Activity, on_delete=models.CASCADE, related_name="partner_invoice_items"
    )
    instalment = models.CharField(max_length=16, choices=PartnerInvoice.TYPE_CHOICES)
    planned_amount = models.BigIntegerField()
    payable_amount = models.BigIntegerField()
    category = models.CharField(max_length=64)
    payment = models.OneToOneField(
        PartnerPayment,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invoice_item",
    )

    class Meta:
        db_table = "partner_invoice_item"
        constraints = [
            models.UniqueConstraint(
                fields=["activity", "instalment"],
                name="uniq_partner_invoice_item_activity_instalment",
            ),
        ]
