"""Fund-request models — the Budget → Fund Request approval chain."""

from __future__ import annotations

from django.db import models

from apps.core.models import CuidField, TimeStampedModel


class FundRequestPeriod(models.TextChoices):
    WEEKLY = "weekly", "Weekly"
    MONTHLY = "monthly", "Monthly"
    QUARTERLY = "quarterly", "Quarterly"
    ANNUAL = "annual", "Annual"


class FundRequestStatus(models.TextChoices):
    SUBMITTED = "submitted", "Submitted"
    APPROVED = "approved", "Approved"
    RETURNED = "returned", "Returned"
    REJECTED = "rejected", "Rejected"
    DISBURSED = "disbursed", "Disbursed"
    DRAFT = "draft", "Draft"
    SUBMITTED_TO_PL = "submitted_to_pl", "Submitted to PL"
    APPROVED_BY_PL = "approved_by_pl", "Approved by PL"
    SUBMITTED_TO_CD = "submitted_to_cd", "Submitted to CD"
    APPROVED_BY_CD = "approved_by_cd", "Approved by CD"
    SUBMITTED_TO_RVP = "submitted_to_rvp", "Submitted to RVP"
    APPROVED_BY_RVP = "approved_by_rvp", "Approved by RVP"
    SENT_TO_ACCOUNTANT = "sent_to_accountant", "Sent to Accountant"
    HELD = "held", "Held"
    CLOSED = "closed", "Closed"
    RETURNED_BY_PL = "returned_by_pl", "Returned by PL"
    RETURNED_BY_CD = "returned_by_cd", "Returned by CD"
    RETURNED_BY_RVP = "returned_by_rvp", "Returned by RVP"
    RETURNED_BY_ACCOUNTANT = "returned_by_accountant", "Returned by Accountant"


class FundRequest(TimeStampedModel):
    """A submitted snapshot of a period's scheduled+costed work, routed for
    approval (PL → CD → RVP → Accountant)."""

    id = CuidField()
    fy = models.CharField(max_length=16)
    period = models.CharField(max_length=16, choices=FundRequestPeriod.choices)
    period_key = models.CharField(max_length=32)  # "2026" | "2026-Q3" | "2026-M2"
    scope = models.CharField(max_length=16)  # own | team | country
    submitted_by_user_id = models.CharField(max_length=30)
    submitted_by_role = models.CharField(max_length=64)
    total_amount = models.BigIntegerField()  # UGX, integer (plain shillings, not cents)
    activity_count = models.IntegerField()
    status = models.CharField(
        max_length=32,
        choices=FundRequestStatus.choices,
        default=FundRequestStatus.SUBMITTED,
    )
    reviewed_by_user_id = models.CharField(max_length=30, null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=512, null=True, blank=True)
    disbursed_amount = models.BigIntegerField(null=True, blank=True)  # UGX
    disbursed_at = models.DateTimeField(null=True, blank=True)
    disbursed_by_user_id = models.CharField(max_length=30, null=True, blank=True)
    disburse_method = models.CharField(max_length=64, null=True, blank=True)
    disburse_reference = models.CharField(max_length=128, null=True, blank=True)
    # Accountant hold (pause without rejecting) + requester receipt confirmation.
    held_reason = models.CharField(max_length=256, null=True, blank=True)
    held_at = models.DateTimeField(null=True, blank=True)
    receipt_confirmed_at = models.DateTimeField(null=True, blank=True)
    accounted_amount = models.BigIntegerField(null=True, blank=True)  # UGX
    returned_amount = models.BigIntegerField(null=True, blank=True)  # UGX
    accountability_status = models.CharField(max_length=32, null=True, blank=True)
    accountability_netsuite_id = models.CharField(max_length=128, null=True, blank=True)
    accountability_submitted_at = models.DateTimeField(null=True, blank=True)
    accountability_reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "fund_request"
        constraints = [
            models.UniqueConstraint(
                fields=["submitted_by_user_id", "period", "period_key", "scope"],
                name="uniq_request_period_owner",
            ),
            # ── INT-01: money floors, enforced by Postgres ────────────────
            # This table carried SEVEN unique constraints and ZERO checks, so
            # a negative disbursement was a legal row. Every service that
            # writes these fields bounds them (services.disburse,
            # disbursement_dashboard_service.disburse), but one unbounded
            # write reaches them —`services.py` sets accounted_amount and
            # returned_amount straight from the request payload — and a
            # management command, a shell or a repair script reaches all of
            # them. The floor belongs where nothing can route around it.
            #
            # >= 0, not > 0, on every one of these: total_amount is the sum
            # of ActivityScheduleCostLine amounts, and apps/budget/costing.py
            # prices a line at 0 when its rate is missing or its quantity is
            # zero, so a legitimately-zero total is reachable. Only a
            # NEGATIVE figure is arithmetically impossible here.
            models.CheckConstraint(
                condition=models.Q(total_amount__gte=0),
                name="fund_request_total_amount_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(disbursed_amount__isnull=True)
                | models.Q(disbursed_amount__gte=0),
                name="fund_request_disbursed_amount_non_negative",
            ),
            # accounted_amount == disbursed - returned + reimbursed, so a
            # full return legitimately accounts for 0 spent. Never negative.
            models.CheckConstraint(
                condition=models.Q(accounted_amount__isnull=True)
                | models.Q(accounted_amount__gte=0),
                name="fund_request_accounted_amount_non_negative",
            ),
            # Returning nothing is the normal case, so 0 must stay legal.
            models.CheckConstraint(
                condition=models.Q(returned_amount__isnull=True)
                | models.Q(returned_amount__gte=0),
                name="fund_request_returned_amount_non_negative",
            ),
        ]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["fy", "period"]),
            models.Index(fields=["submitted_by_user_id"]),
        ]


class FundRequestItem(TimeStampedModel):
    """Links a cost line to a fund request."""

    id = CuidField()
    fund_request = models.ForeignKey(
        FundRequest, on_delete=models.CASCADE, related_name="items"
    )
    activity_id = models.CharField(max_length=30)
    activity_schedule_cost_line_id = models.CharField(max_length=30)
    amount = models.BigIntegerField()  # UGX, integer (plain shillings, not cents)
    period = models.CharField(max_length=16, choices=FundRequestPeriod.choices)
    period_key = models.CharField(max_length=32)
    added_after_generation = models.BooleanField(default=False)

    class Meta:
        db_table = "fund_request_item"
        constraints = [
            models.UniqueConstraint(
                fields=["fund_request", "activity_schedule_cost_line_id"],
                name="uniq_request_costline",
            ),
            # INT-01. A request item mirrors one cost line, and
            # apps/budget/costing.py emits amount=0 for a line whose rate is
            # missing, so 0 is a real priced line, not a bug. Negative is.
            models.CheckConstraint(
                condition=models.Q(amount__gte=0),
                name="fund_request_item_amount_non_negative",
            ),
        ]
        indexes = [models.Index(fields=["activity_id"])]


class AdvanceRequestStatus(models.TextChoices):
    """The weekly-advance lifecycle. A scheduled activity drafts an advance that
    the RESPONSIBLE user must confirm before the Accountant may disburse."""

    DRAFT_FROM_SCHEDULE = "draft_from_schedule", "Draft (from schedule)"
    PENDING_RESPONSIBLE_CONFIRMATION = (
        "pending_responsible_confirmation",
        "Pending responsible confirmation",
    )
    CONFIRMED_FOR_ADVANCE = "confirmed_for_advance", "Confirmed for advance"
    SELF_FUNDED_PENDING_REIMBURSEMENT = (
        "self_funded_pending_reimbursement",
        "Self-funded (pending reimbursement)",
    )
    NOT_REQUESTED = "not_requested", "Not requested"
    SUBMITTED_TO_ACCOUNTANT = "submitted_to_accountant", "Submitted to accountant"
    DISBURSED = "disbursed", "Disbursed"
    # Accountability routes through the owner's Program Lead BEFORE the
    # Accountant (2026-08-13 mandate: "all fund accountability is approved by
    # the PL, then goes to the accountant"). The PL confirms the money is
    # accounted for; IA separately confirms the work was done; the Accountant
    # settles last.
    ACCOUNTABILITY_PL_PENDING = (
        "accountability_pl_pending",
        "Accountability awaiting PL approval",
    )
    ACCOUNTABILITY_PENDING = "accountability_pending", "Accountability pending"
    ACCOUNTED = "accounted", "Accounted"
    # A self-funded reimbursement claim awaiting the PL's approval before it
    # reaches the Accountant's reimbursement queue.
    REIMBURSEMENT_PL_PENDING = (
        "reimbursement_pl_pending",
        "Reimbursement awaiting PL approval",
    )
    REIMBURSEMENT_SUBMITTED = "reimbursement_submitted", "Reimbursement submitted"
    # Accountant has disbursed the reimbursement but the employee has not yet
    # confirmed receipt — money is not "reimbursed" (financially cleared)
    # until that confirmation lands (2026-07-15 finance-unification mandate:
    # "reimbursement_disbursed -> reimbursement_receipt_pending ->
    # financially_cleared"). See advance_service.reimburse /
    # confirm_reimbursement_receipt.
    REIMBURSEMENT_DISBURSED = (
        "reimbursement_disbursed",
        "Reimbursement disbursed (awaiting receipt confirmation)",
    )
    REIMBURSED = "reimbursed", "Reimbursed"
    RETURNED = "returned", "Returned"
    CANCELLED = "cancelled", "Cancelled"


# The funding choice the responsible user makes for a scheduled activity.
ADVANCE_TYPES = (
    ("advance", "Request Advance"),
    ("self_funded", "Use Own Funds (claim reimbursement later)"),
    ("not_requested", "Do Not Request Funds Yet"),
)

# Advance statuses meaning money has actually left the account (or is in a
# post-disbursement leg). The AdvanceRequest rows are the one shared ledger
# every disbursement channel (advance, weekly, period) converges on — each
# channel must refuse to release money for a budget line whose advance is
# already in one of these states, or the same line gets paid twice.
MONEY_MOVED_ADVANCE_STATUSES = (
    AdvanceRequestStatus.DISBURSED,
    AdvanceRequestStatus.ACCOUNTABILITY_PL_PENDING,
    AdvanceRequestStatus.ACCOUNTABILITY_PENDING,
    AdvanceRequestStatus.ACCOUNTED,
    # A self-funded claim's money is the EMPLOYEE's, already spent — the
    # in-flight claim is equally a financial record that must never be
    # silently deleted or re-priced away.
    AdvanceRequestStatus.REIMBURSEMENT_PL_PENDING,
    AdvanceRequestStatus.REIMBURSEMENT_SUBMITTED,
    AdvanceRequestStatus.REIMBURSEMENT_DISBURSED,
    AdvanceRequestStatus.REIMBURSED,
)


class AdvanceRequest(TimeStampedModel):
    """A weekly advance request, auto-created from an activity's budget line when
    the activity is scheduled. The responsible user (the scheduler/owner) confirms
    how they want it funded; the Accountant can only disburse after that
    confirmation. Self-funded advances skip disbursement and open a reimbursement
    path after completion + approval."""

    id = CuidField()
    activity = models.ForeignKey(
        "activities.Activity", on_delete=models.CASCADE, related_name="advance_requests"
    )
    budget_line = models.ForeignKey(
        "activities.ActivityScheduleCostLine",
        on_delete=models.CASCADE,
        related_name="advance_requests",
    )
    responsible_user_id = models.CharField(
        max_length=30, null=True, blank=True
    )  # the scheduler/owner (null for pure-partner activities until confirmed)
    # Period (mirrors the activity for fund-request bucket grouping).
    fy = models.CharField(max_length=16)
    quarter = models.CharField(max_length=8)
    month = models.IntegerField(null=True, blank=True)
    week = models.IntegerField(null=True, blank=True)
    planned_date = models.DateTimeField(null=True, blank=True)
    amount = models.BigIntegerField()  # UGX, integer (the budget-line amount)
    status = models.CharField(
        max_length=40,
        choices=AdvanceRequestStatus.choices,
        default=AdvanceRequestStatus.PENDING_RESPONSIBLE_CONFIRMATION,
    )
    advance_type = models.CharField(
        max_length=16, choices=ADVANCE_TYPES, default="advance"
    )
    # Disbursement (advance path).
    disbursed_amount = models.BigIntegerField(null=True, blank=True)
    disbursed_at = models.DateTimeField(null=True, blank=True)
    disbursed_by_user_id = models.CharField(max_length=30, null=True, blank=True)
    disburse_method = models.CharField(max_length=64, null=True, blank=True)
    disburse_reference = models.CharField(max_length=128, null=True, blank=True)
    # Accountability (advance path, after disbursement).
    accounted_amount = models.BigIntegerField(null=True, blank=True)
    returned_amount = models.BigIntegerField(null=True, blank=True)
    accountability_netsuite_id = models.CharField(max_length=128, null=True, blank=True)
    accountability_submitted_at = models.DateTimeField(null=True, blank=True)
    # The Program Lead's confirmation that the money is accounted for —
    # required before the Accountant may settle (clear or reimburse).
    accountability_pl_approved_at = models.DateTimeField(null=True, blank=True)
    accountability_pl_approved_by = models.CharField(
        max_length=30, null=True, blank=True
    )
    accountability_reviewed_at = models.DateTimeField(null=True, blank=True)
    # Confirmation / review audit.
    confirmed_at = models.DateTimeField(null=True, blank=True)
    last_note = models.CharField(max_length=512, null=True, blank=True)
    # Reimbursement payout (self-funded activities, OR the over-spend portion
    # of an advance-funded activity) — kept on separate fields from
    # disbursed_amount/disburse_reference (the ORIGINAL advance) per the
    # 2026-07-15 finance-unification mandate's identifier-separation rule:
    # "Disbursement Reference" and "Reimbursement Reference" must never share
    # a field, since an advance-funded overspend needs BOTH amounts recorded.
    reimbursed_amount = models.BigIntegerField(null=True, blank=True)
    reimbursed_at = models.DateTimeField(null=True, blank=True)
    reimbursed_by_user_id = models.CharField(max_length=30, null=True, blank=True)
    reimburse_method = models.CharField(max_length=64, null=True, blank=True)
    reimburse_reference = models.CharField(max_length=128, null=True, blank=True)
    # The employee's confirmation that a disbursed reimbursement actually
    # arrived — required before the advance reaches its terminal REIMBURSED
    # (financially-cleared) status. Without this, "disbursed" and "received"
    # were being conflated.
    reimbursement_receipt_confirmed_at = models.DateTimeField(null=True, blank=True)
    reimbursement_receipt_confirmed_amount = models.BigIntegerField(
        null=True, blank=True
    )
    # Accountant verification of an employee-declared under-spend return.
    # Required before approve_accountability may clear an accountability
    # whose returned_amount > 0 — previously the employee's self-declared
    # returned_amount was trusted with no accountant verification step at
    # all (mandate §11: "Accountant verifies the return").
    return_verified_at = models.DateTimeField(null=True, blank=True)
    return_verified_by_user_id = models.CharField(max_length=30, null=True, blank=True)
    return_reference = models.CharField(max_length=128, null=True, blank=True)

    class Meta:
        db_table = "advance_request"
        ordering = ["-created_at"]
        constraints = [
            # One advance per budget line (idempotent auto-creation).
            models.UniqueConstraint(
                fields=["budget_line"], name="uniq_advance_per_budget_line"
            ),
            # ── INT-01: money floors on the shared advance ledger ─────────
            # These rows are the one ledger every disbursement channel
            # converges on (see MONEY_MOVED_ADVANCE_STATUSES above), so a
            # negative figure here is a negative figure in every budget
            # rollup, every dashboard and every reconciliation identity.
            #
            # Mirrors the budget line, which prices at 0 for a missing rate
            # or a zero quantity (apps/budget/costing.py) — so >= 0.
            models.CheckConstraint(
                condition=models.Q(amount__gte=0),
                name="advance_request_amount_non_negative",
            ),
            # >= 0 and NOT > 0, deliberately: the weekly channel splits a
            # partial disbursement across the week's advances by largest
            # remainder (weekly_service.disburse) and the legacy activity
            # channel scales by a rounded fraction (finance_services), and
            # both legitimately allot 0 to a line. A `> 0` floor here would
            # reject a correct split at the database.
            models.CheckConstraint(
                condition=models.Q(disbursed_amount__isnull=True)
                | models.Q(disbursed_amount__gte=0),
                name="advance_request_disbursed_amount_non_negative",
            ),
            # 0 is legitimate: an employee who spent nothing and returned the
            # whole advance satisfies accounted == disbursed - returned.
            models.CheckConstraint(
                condition=models.Q(accounted_amount__isnull=True)
                | models.Q(accounted_amount__gte=0),
                name="advance_request_accounted_amount_non_negative",
            ),
            # Returning nothing is the ordinary outcome — 0 stays legal.
            models.CheckConstraint(
                condition=models.Q(returned_amount__isnull=True)
                | models.Q(returned_amount__gte=0),
                name="advance_request_returned_amount_non_negative",
            ),
            # The one money field here where 0 IS meaningless, hence > 0.
            # advance_service.reimburse() refuses to pay unless due_amount is
            # strictly positive and the payout equals it exactly, so a
            # reimbursement of 0 records a payment that never happened while
            # moving the advance into REIMBURSEMENT_DISBURSED — a state whose
            # only exit is the employee's receipt confirmation. Null stays
            # legal: most advances are never reimbursed at all.
            models.CheckConstraint(
                condition=models.Q(reimbursed_amount__isnull=True)
                | models.Q(reimbursed_amount__gt=0),
                name="advance_request_reimbursed_amount_positive",
            ),
            # ── INTG-07: one NetSuite Code clears one advance ─────────────
            # approve_accountability() gates finance clearance on this field
            # merely being non-empty, so without uniqueness a single NetSuite
            # expense reference satisfied the gate on unlimited advances —
            # the rule FinanceBlockedReasonService names as "Rule 5:
            # Duplicate NetSuite ID risk check" and never implemented.
            # NetSuiteExpenseRecord.netsuite_expense_id is already globally
            # unique; this is the same law on the field the clearance gate
            # actually reads.
            #
            # PARTIAL, on the Activity.uniq_activity_salesforce_id pattern:
            # the great majority of advances legitimately carry no code (not
            # yet accounted, self-funded, cancelled), and both NULL and ""
            # occur in the wild, so both are excluded. There is no soft
            # delete on this table — a superseded advance is hard-deleted by
            # advance_service.sync_for_activity — so a tombstone exclusion
            # has nothing to exclude here and the identifier is freed by the
            # delete itself.
            models.UniqueConstraint(
                fields=["accountability_netsuite_id"],
                condition=models.Q(accountability_netsuite_id__isnull=False)
                & ~models.Q(accountability_netsuite_id=""),
                name="uniq_advance_accountability_netsuite_id",
            ),
        ]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["responsible_user_id"]),
            models.Index(fields=["fy", "month"]),
        ]


class WeeklyFundRequest(TimeStampedModel):
    """A weekly advance request aggregating all scheduled activities for that week."""

    id = CuidField()
    fy = models.CharField(max_length=16)
    week_start_date = models.DateField()
    week_end_date = models.DateField()
    responsible_user = models.CharField(max_length=30)  # responsible user id
    responsible_role = models.CharField(max_length=64, null=True, blank=True)
    total_amount = models.BigIntegerField(default=0)  # UGX
    status = models.CharField(max_length=40, default="pending_responsible_confirmation")

    # Disbursement (advance path)
    disbursed_amount = models.BigIntegerField(null=True, blank=True)
    disbursed_at = models.DateTimeField(null=True, blank=True)
    disbursed_by_user_id = models.CharField(max_length=30, null=True, blank=True)
    disburse_method = models.CharField(max_length=64, null=True, blank=True)
    disburse_reference = models.CharField(max_length=128, null=True, blank=True)
    # The owner's confirmation that the disbursed week's funds actually
    # arrived. Accountability on the week's advances opens only after this —
    # disbursed and received are different facts (the monthly FundRequest and
    # the reimbursement leg already record them separately).
    receipt_confirmed_at = models.DateTimeField(null=True, blank=True)

    # Accountability (advance path, after disbursement)
    accounted_amount = models.BigIntegerField(null=True, blank=True)
    returned_amount = models.BigIntegerField(null=True, blank=True)
    accountability_netsuite_id = models.CharField(max_length=128, null=True, blank=True)
    accountability_submitted_at = models.DateTimeField(null=True, blank=True)
    accountability_reviewed_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "weekly_fund_request"
        constraints = [
            models.UniqueConstraint(
                fields=["responsible_user", "week_start_date"],
                name="uniq_weekly_request_owner_week",
            ),
            # INT-01, same floors as the monthly FundRequest above: this is
            # the third channel money leaves through, and it was equally
            # unprotected. total_amount is the sum of the week's fundable
            # cost lines, any of which may legitimately price at 0.
            models.CheckConstraint(
                condition=models.Q(total_amount__gte=0),
                name="weekly_fund_request_total_amount_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(disbursed_amount__isnull=True)
                | models.Q(disbursed_amount__gte=0),
                name="weekly_fund_request_disbursed_amount_non_negative",
            ),
            # Both roll up the week's child advances by summation
            # (disbursement_dashboard_service), so they inherit those floors
            # and, like them, are legitimately 0.
            models.CheckConstraint(
                condition=models.Q(accounted_amount__isnull=True)
                | models.Q(accounted_amount__gte=0),
                name="weekly_fund_request_accounted_amount_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(returned_amount__isnull=True)
                | models.Q(returned_amount__gte=0),
                name="weekly_fund_request_returned_amount_non_negative",
            ),
            # NOT constrained, deliberately (INTG-07): this table's
            # accountability_netsuite_id is a comma-joined LIST of its child
            # advances' codes, truncated to 128 chars — see
            # disbursement_dashboard_service. It is a display roll-up, not an
            # identifier, and uniqueness on it would be meaningless. The
            # per-advance code carries the constraint instead.
        ]


class WeeklyFundRequestLine(TimeStampedModel):
    """An itemized line in a WeeklyFundRequest, linked to the original ActivityScheduleCostLine."""

    id = CuidField()
    weekly_fund_request = models.ForeignKey(
        WeeklyFundRequest, on_delete=models.CASCADE, related_name="lines"
    )
    activity_budget_line = models.ForeignKey(
        "activities.ActivityScheduleCostLine",
        on_delete=models.CASCADE,
        related_name="weekly_request_lines",
    )
    line_item_type = models.CharField(max_length=64)
    description = models.CharField(max_length=255)
    quantity = models.IntegerField(default=1)
    unit_cost = models.BigIntegerField()
    total_cost = models.BigIntegerField()
    currency = models.CharField(max_length=8, default="UGX")

    class Meta:
        db_table = "weekly_fund_request_line"
        constraints = [
            models.UniqueConstraint(
                fields=["weekly_fund_request", "activity_budget_line"],
                name="uniq_weekly_line_budget_line",
            ),
        ]


from .finance_models import (  # noqa: E402 — circular import, must load after FundRequest is defined
    Disbursement,
    PartnerPayment,
    ReimbursementClaim,
    AccountabilityRecord,
    Receipt,
    NetSuiteExpenseRecord,
    FinanceReturn,
    VarianceReview,
    FinanceAuditLog,
)

__all__ = [
    "FundRequestPeriod",
    "FundRequestStatus",
    "FundRequest",
    "FundRequestItem",
    "AdvanceRequestStatus",
    "AdvanceRequest",
    "WeeklyFundRequest",
    "WeeklyFundRequestLine",
    "Disbursement",
    "PartnerPayment",
    "ReimbursementClaim",
    "AccountabilityRecord",
    "Receipt",
    "NetSuiteExpenseRecord",
    "FinanceReturn",
    "VarianceReview",
    "FinanceAuditLog",
]
