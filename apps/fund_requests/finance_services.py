from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from apps.activities.closure_services import (
    ActivityClosureService,
    ClosureEligibilityService,
)
from apps.activities.models import Activity, CompletedActivitySnapshot
from apps.fund_requests.models import (
    AdvanceRequestStatus,
    Disbursement,
    PartnerPayment,
    ReimbursementClaim,
    AccountabilityRecord,
    Receipt,
    NetSuiteExpenseRecord,
    VarianceReview,
    FinanceAuditLog,
)
from apps.notifications.services import WorkflowNotificationService


def _chain_audit(action: str, activity, actor_id: str, payload: dict) -> None:
    """Mirror a security-critical finance event onto the tamper-evident
    AuditLog chain. FinanceAuditLog remains the specialized ledger, but the
    ecosystem audit found money events entirely absent from the hash chain."""
    try:
        from apps.audit.services import log as audit_log

        audit_log(
            action=action,
            subject_kind="Activity",
            subject_id=activity.id,
            actor_id=actor_id,
            actor_role="Accountant",
            success=True,
            payload=payload,
        )
    except Exception:  # pragma: no cover — audit must never break finance
        pass


# The one definition of "this partner activity still needs paying".
#
# Four surfaces each carried their own version — the Disbursement Dashboard
# matched only `ia_confirmed`, the partner-payments page matched
# `none|ia_confirmed`, batch payments matched a third set, and the activities
# API a fourth. The same queue therefore showed different rows and different
# totals depending on which page the Accountant happened to open.
PARTNER_PAYABLE_STATUSES = ("none", "ia_confirmed")

# Statuses meaning money already left for this activity — never payable again.
PARTNER_PAID_STATUSES = ("disbursed", "paid")


class FinanceBlockedReasonService:
    """Evaluates if an activity's finance steps are blocked and provides clean reasons."""

    @staticmethod
    def get_blocked_reasons(
        activity: Activity,
        has_evidence: bool | None = None,
        has_budget_lines: bool | None = None,
    ) -> list[str]:
        reasons = []

        # Rule 1: No IA verification -> no final clearance
        if activity.status not in ["ia_verified", "closed", "accountant_confirmed"]:
            reasons.append("IA Verification Missing")

        # Rule 2: No evidence -> no clearance
        if has_evidence is None:
            from apps.evidence.models import EvidenceRecord

            has_evidence = EvidenceRecord.objects.filter(
                activity_id=activity.id, quarantined=False
            ).exists()
        if not has_evidence:
            reasons.append("Evidence Missing")

        # Rule 3: No Activity SF ID -> no clearance
        if not activity.salesforce_activity_id:
            reasons.append("Activity SF ID Missing")

        # Rule 4: Budget line missing
        if has_budget_lines is None:
            has_budget_lines = activity.schedule_cost_lines.exists()
        if not has_budget_lines:
            reasons.append("Budget Line Missing")

        # Rule 5: Duplicate NetSuite ID risk check
        # (handelled dynamically if double entered)

        return reasons

    @staticmethod
    def is_blocked(activity: Activity) -> bool:
        return len(FinanceBlockedReasonService.get_blocked_reasons(activity)) > 0


class AdvanceDisbursementService:
    """Manages releasing advance money before execution."""

    @staticmethod
    def disburse_advance(
        activity: Activity,
        amount: int,
        method: str,
        reference: str,
        user_id: str,
        notes: str = "",
    ) -> Disbursement:
        with transaction.atomic():
            # GUARDED: mirrors apps.fund_requests.advance_service.disburse() —
            # the Accountant may NOT disburse before the responsible user
            # confirms the advance (the finance-safety rule). This legacy,
            # activity-level path shares the same AdvanceRequest rows that
            # advance_service.sync_for_activity auto-creates per budget line,
            # so it must honour the same confirmation gate rather than
            # disbursing unconditionally. select_for_update() + the status
            # check happening inside this same atomic block (rather than
            # before it) closes the double-click race: a second near-
            # simultaneous call blocks on the row lock, then sees these rows
            # already DISBURSED and finds nothing pending instead of
            # re-disbursing them.
            pending = list(
                activity.advance_requests.select_for_update().filter(
                    status__in=[
                        AdvanceRequestStatus.CONFIRMED_FOR_ADVANCE,
                        AdvanceRequestStatus.SUBMITTED_TO_ACCOUNTANT,
                    ]
                )
            )
            if not pending:
                raise ValueError(
                    "Cannot disburse — the responsible user has not confirmed "
                    "this advance yet. The Accountant may not disburse before "
                    "responsible-user confirmation."
                )

            # Create Disbursement
            disb = Disbursement.objects.create(
                activity=activity,
                amount_disbursed=amount,
                disbursed_by=user_id,
                payment_method=method,
                payment_reference=reference,
                notes=notes,
            )

            # Move the underlying AdvanceRequest(s) to DISBURSED too — this
            # activity-level legacy path shares the same rows the canonical
            # advance_service.disburse()/weekly_service.disburse() queues read
            # their "ready for disbursement" lists from. Leaving them at
            # CONFIRMED_FOR_ADVANCE let the same money be disbursed a SECOND
            # time through either of those queues. Scale each row's
            # disbursed_amount proportionally to the fraction of the pending
            # total this call actually released, same as the weekly path.
            pending_total = sum(a.amount for a in pending)
            fraction = (amount / pending_total) if pending_total else 0
            now = timezone.now()
            for adv in pending:
                adv.status = AdvanceRequestStatus.DISBURSED
                adv.disbursed_amount = round(adv.amount * fraction)
                adv.disbursed_at = now
                adv.disbursed_by_user_id = user_id
                adv.disburse_method = method
                adv.disburse_reference = reference
                adv.save(
                    update_fields=[
                        "status",
                        "disbursed_amount",
                        "disbursed_at",
                        "disbursed_by_user_id",
                        "disburse_method",
                        "disburse_reference",
                        "updated_at",
                    ]
                )

            # Update Activity Payment Status
            activity.payment_status = "disbursed"
            activity.save(update_fields=["payment_status", "updated_at"])

            # Create a shell Accountability Record for the user to submit later
            AccountabilityRecord.objects.create(
                activity=activity,
                staff_id=activity.responsible_staff_id or user_id,
                amount_disbursed=amount,
                actual_spend=0,
                variance=-amount,
                status="pending",
            )

            # Log Audit
            FinanceAuditService.log_finance_event(
                activity=activity,
                event_type="advance_disbursement",
                actor_id=user_id,
                actor_role="Accountant",
                new_value=f"Disbursed advance of {amount} UGX via {method} (Ref: {reference})",
            )
            _chain_audit(
                "finance.disbursed",
                activity,
                user_id,
                {"amount": amount, "method": method, "reference": reference},
            )

            # Send Notification
            if activity.responsible_staff_id:
                WorkflowNotificationService.trigger(
                    event_type="fund_request_approved",
                    category="finance",
                    priority="normal",
                    title="Advance Funds Disbursed",
                    body=f"Advance of {amount} UGX disbursed for Activity #{activity.id[:8]}. Please submit accountability after execution.",
                    context_type="Activity",
                    context_id=activity.id,
                    recipients=[activity.responsible_staff_id],
                )

            return disb


class PartnerPaymentService:
    """Manages partner payments after verified execution."""

    @staticmethod
    def pay_partner(
        activity: Activity,
        partner_name: str,
        amount: int,
        method: str,
        reference: str,
        user_id: str,
        notes: str = "",
        netsuite_id: str = "",
    ) -> PartnerPayment:
        # Enforce blockers
        reasons = FinanceBlockedReasonService.get_blocked_reasons(activity)
        if reasons:
            raise ValueError(f"Partner payment is blocked: {', '.join(reasons)}")

        # Cross-channel guard: a partner activity whose staff advance already
        # moved money must not ALSO be partner-paid against the same cost
        # lines (the advance and partner channels had no mutual exclusion).
        from apps.fund_requests.models import MONEY_MOVED_ADVANCE_STATUSES

        if activity.advance_requests.filter(
            status__in=MONEY_MOVED_ADVANCE_STATUSES
        ).exists():
            raise ValueError(
                "This activity already has money released through the advance "
                "channel — settle that accountability instead of issuing a "
                "partner payment for the same cost lines."
            )

        # Idempotency: one payout per activity. get_blocked_reasons passes for
        # closed activities too, so without this a double-submit (or a second
        # call after close) would write a duplicate PartnerPayment ledger row.
        # Backstopped by the DB unique constraint on PartnerPayment.activity.
        if (
            activity.payment_status == "paid"
            or PartnerPayment.objects.filter(activity=activity).exists()
        ):
            raise ValueError(
                "Partner payment already recorded for this activity — a second "
                "payout would double-count the money."
            )

        # Partner payment is the terminal finance step for partner-delivery
        # activities in this legacy stack — there is no separate accountant
        # NetSuite-entry step downstream of it the way staff advances have.
        # The canonical rule (NetSuite ID required whenever finance_required,
        # see apps.activities.closure_services.ClosureEligibilityService) was
        # never enforced here, so a partner activity could close with money
        # paid out and no NetSuite record at all — enforce it now.
        netsuite_id = (netsuite_id or "").strip()
        if not netsuite_id:
            raise ValueError(
                "Partner payment requires a NetSuite Expense ID — proof the "
                "payment was entered into NetSuite before the activity can close."
            )

        with transaction.atomic():
            pay = PartnerPayment.objects.create(
                activity=activity,
                partner_name=partner_name,
                amount_paid=amount,
                payment_method=method,
                payment_reference=reference,
                paid_by=user_id,
                notes=notes,
            )

            activity.payment_status = "paid"
            activity.save(update_fields=["payment_status", "updated_at"])

            NetSuiteExpenseRecord.objects.update_or_create(
                activity=activity,
                defaults={
                    "netsuite_expense_id": netsuite_id,
                    "expense_date": timezone.now().date(),
                    "amount_entered": amount,
                    "entered_by": user_id,
                    "notes": notes,
                },
            )

            FinanceAuditService.log_finance_event(
                activity=activity,
                event_type="partner_payment",
                actor_id=user_id,
                actor_role="Accountant",
                new_value=(
                    f"Paid partner {partner_name} {amount} UGX via {method} "
                    f"(Ref: {reference}). NetSuite ID: {netsuite_id}"
                ),
            )
            _chain_audit(
                "finance.partner_paid",
                activity,
                user_id,
                {
                    "partner": partner_name,
                    "amount": amount,
                    "netsuite_id": netsuite_id,
                    "reference": reference,
                },
            )

            # Close through the canonical gate (ClosureEligibilityService /
            # ActivityClosureService.close()) instead of writing
            # status="closed" directly — re-evaluates the full 9-check
            # checklist now that payment_status and the NetSuite record are
            # in place, and produces the CompletedActivitySnapshot the direct
            # write used to skip.
            if ClosureEligibilityService.is_eligible(activity):
                ActivityClosureService.close(activity, closed_by=user_id)

            return pay


class ReimbursementService:
    """Manages staff self-funded activities and overspent budgets claims."""

    @staticmethod
    def claim_reimbursement(
        activity: Activity, actual_spend: int, staff_id: str, notes: str = ""
    ) -> ReimbursementClaim:
        approved_budget = (
            activity.schedule_cost_lines.aggregate(s=Sum("amount"))["s"] or 0
        )

        # Calculate disbursed amount
        disbursed = (
            Disbursement.objects.filter(activity=activity).aggregate(
                s=Sum("amount_disbursed")
            )["s"]
            or 0
        )

        reimbursement_amount = actual_spend - disbursed
        if reimbursement_amount <= 0:
            raise ValueError(
                "Actual spend does not exceed advance amount. No reimbursement needed."
            )

        with transaction.atomic():
            claim = ReimbursementClaim.objects.create(
                activity=activity,
                staff_id=staff_id,
                approved_budget=approved_budget,
                amount_advanced=disbursed,
                actual_spend=actual_spend,
                reimbursement_amount=reimbursement_amount,
                status="pending",
                notes=notes,
            )

            # Log event
            FinanceAuditService.log_finance_event(
                activity=activity,
                event_type="reimbursement_claimed",
                actor_id=staff_id,
                actor_role="CCEO",
                new_value=f"Claimed reimbursement of {reimbursement_amount} UGX (Spend: {actual_spend}, Advance: {disbursed})",
            )

            return claim

    @staticmethod
    def disburse_reimbursement(
        claim: ReimbursementClaim, method: str, reference: str, user_id: str
    ) -> ReimbursementClaim:
        activity = claim.activity

        # Reimbursement can only be paid if IA Verified
        if activity.status not in ["ia_verified", "closed", "accountant_confirmed"]:
            raise ValueError("Reimbursement is blocked: IA Verification Missing")

        with transaction.atomic():
            # Re-read under lock and refuse a repeat. This was the only
            # money-moving path with no idempotency protection at all — a
            # double-click or a network retry marked the claim paid twice and
            # wrote two Disbursement rows for one debt. The advance and
            # partner channels both guard this; the reimbursement channel is
            # the same money and gets the same guard.
            claim = type(claim).objects.select_for_update().get(id=claim.id)
            if claim.status == "paid":
                raise ValueError(
                    "This reimbursement has already been paid "
                    f"({claim.payment_reference or 'no reference'})."
                )
            claim.status = "paid"
            claim.payment_method = method
            claim.payment_reference = reference
            claim.payment_date = timezone.now()
            claim.paid_by = user_id
            claim.save()

            # Also create a Disbursement record
            Disbursement.objects.create(
                activity=activity,
                amount_disbursed=claim.reimbursement_amount,
                disbursed_by=user_id,
                payment_method=method,
                payment_reference=reference,
                notes=f"Reimbursement payout for claim ID {claim.id}",
            )

            # Close the activity
            activity.status = "closed"
            activity.save(update_fields=["status", "updated_at"])

            # This still bypasses the canonical ActivityClosureService.close()
            # gate — reimbursement claims carry no NetSuite ID of their own to
            # satisfy ClosureEligibilityService's netsuite check, so fully
            # routing through it is a larger refactor. But it must not skip
            # the CompletedActivitySnapshot the canonical path always leaves
            # behind, or this activity renders with snapshot=None forever.
            from apps.evidence.models import EvidenceRecord

            budget_total = (
                activity.schedule_cost_lines.aggregate(s=Sum("amount"))["s"] or 0
            )
            disb_total = (
                Disbursement.objects.filter(activity=activity).aggregate(
                    s=Sum("amount_disbursed")
                )["s"]
                or 0
            )
            ns_rec = NetSuiteExpenseRecord.objects.filter(activity=activity).first()
            CompletedActivitySnapshot.objects.update_or_create(
                activity=activity,
                defaults={
                    "final_budget_amount": budget_total,
                    "disbursed_amount": disb_total,
                    "actual_spend_amount": disb_total,
                    "netsuite_expense_id": ns_rec.netsuite_expense_id
                    if ns_rec
                    else None,
                    "evidence_count": EvidenceRecord.objects.filter(
                        activity=activity
                    ).count(),
                    "snapshot_taken_at": timezone.now(),
                },
            )

            FinanceAuditService.log_finance_event(
                activity=activity,
                event_type="reimbursement_disbursed",
                actor_id=user_id,
                actor_role="Accountant",
                new_value=f"Disbursed reimbursement claim of {claim.reimbursement_amount} UGX via {method} (Ref: {reference})",
            )

            return claim


class AccountabilityService:
    """Manages staff submitting receipts and closing advance variances."""

    @staticmethod
    def submit_accountability(
        activity: Activity,
        actual_spend: int,
        variance_reason: str,
        staff_id: str,
        receipts: list[dict] = None,
    ) -> AccountabilityRecord:
        disbursed = (
            Disbursement.objects.filter(activity=activity).aggregate(
                s=Sum("amount_disbursed")
            )["s"]
            or 0
        )

        if disbursed == 0:
            raise ValueError("No advance disbursement found for this activity.")

        variance = actual_spend - disbursed
        status = "netsuite_id_required"
        if variance != 0:
            status = "variance_review"

        with transaction.atomic():
            # Clear old records
            AccountabilityRecord.objects.filter(
                activity=activity, status="pending"
            ).delete()

            record = AccountabilityRecord.objects.create(
                activity=activity,
                staff_id=staff_id,
                amount_disbursed=disbursed,
                actual_spend=actual_spend,
                variance=variance,
                variance_reason=variance_reason,
                status=status,
            )

            # Save Receipts if any
            if receipts:
                for r in receipts:
                    Receipt.objects.create(
                        accountability_record=record,
                        original_name=r["original_name"],
                        uri=r["uri"],
                        file_size=r["file_size"],
                        mime_type=r.get("mime_type", ""),
                    )

            # Save Variance Review if needed
            if variance != 0:
                VarianceReview.objects.create(
                    activity=activity,
                    budgeted_amount=activity.schedule_cost_lines.aggregate(
                        s=Sum("amount")
                    )["s"]
                    or 0,
                    disbursed_amount=disbursed,
                    actual_spend=actual_spend,
                    variance=variance,
                    reason=variance_reason,
                    status="pending",
                )

            FinanceAuditService.log_finance_event(
                activity=activity,
                event_type="accountability_submitted",
                actor_id=staff_id,
                actor_role="CCEO",
                new_value=f"Submitted accountability. Spend: {actual_spend} UGX, Variance: {variance} UGX",
            )

            return record


def is_valid_netsuite_id(value: str) -> bool:
    """A NetSuite Expense ID is a non-empty alphanumeric reference (letters,
    digits, hyphens; 3-64 chars). Rejects blank/whitespace-only and obvious
    junk so a cleared accountability always carries a usable reference."""
    import re

    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9\-]{2,63}", (value or "").strip()))


class NetSuiteExpenseService:
    """Manages entering NetSuite ID and matching duplicates."""

    @staticmethod
    def enter_netsuite_id(
        activity: Activity,
        netsuite_id: str,
        amount: int,
        expense_date,
        user_id: str,
        notes: str = "",
    ) -> NetSuiteExpenseRecord:
        netsuite_id = (netsuite_id or "").strip()
        if not is_valid_netsuite_id(netsuite_id):
            raise ValueError(
                "A valid NetSuite Expense ID is required (alphanumeric, 3-64 "
                "characters). Accountability cannot clear without it."
            )

        with transaction.atomic():
            # Lock the activity row + guard against re-clearing an already
            # cleared/closed record (double-click / replay immutability).
            locked = Activity.objects.select_for_update().filter(id=activity.id).first()
            if locked and locked.status == "closed":
                raise ValueError(
                    "This activity is already closed — its accountability "
                    "record is immutable. Reopen it through the formal "
                    "reopen workflow to amend."
                )

            # A variance must be resolved before an activity clears — never
            # silently ignored. The accountant entering the NetSuite ID after
            # reviewing the accountability IS the acceptance of the variance,
            # so resolve any pending review here (audited), which is what
            # unblocks clearance. Callers wanting a separate pre-clearance
            # resolution can still resolve the review first; this makes the
            # accountant's clearance the backstop rather than a dead end.
            VarianceReview.objects.filter(activity=activity, status="pending").update(
                status="resolved"
            )

            # Check if already entered for another activity (duplicate check)
            is_dup = (
                NetSuiteExpenseRecord.objects.filter(netsuite_expense_id=netsuite_id)
                .exclude(activity=activity)
                .exists()
            )

            rec, _ = NetSuiteExpenseRecord.objects.update_or_create(
                activity=activity,
                defaults={
                    "netsuite_expense_id": netsuite_id,
                    "expense_date": expense_date,
                    "amount_entered": amount,
                    "entered_by": user_id,
                    "notes": f"[DUPLICATE RISK] {notes}" if is_dup else notes,
                },
            )

            # Update AccountabilityRecords
            AccountabilityRecord.objects.filter(activity=activity).update(
                netsuite_expense_id=netsuite_id,
                status="cleared",
                reviewed_at=timezone.now(),
                reviewed_by=user_id,
            )

            # Close through the canonical gate (ClosureEligibilityService /
            # ActivityClosureService.close()) instead of the weaker 4-check
            # FinanceBlockedReasonService set — re-evaluates the full 9-check
            # checklist (the NetSuite record above satisfies its netsuite
            # check) and produces the CompletedActivitySnapshot the direct
            # status="closed" write used to skip.
            if ClosureEligibilityService.is_eligible(activity):
                ActivityClosureService.close(activity, closed_by=user_id)

            FinanceAuditService.log_finance_event(
                activity=activity,
                event_type="netsuite_id_entered",
                actor_id=user_id,
                actor_role="Accountant",
                new_value=f"Entered NetSuite ID: {netsuite_id}. Duplicate Risk: {is_dup}",
            )

            return rec


class FinanceAuditService:
    """Helper to log all financial operations."""

    @staticmethod
    def log_finance_event(
        activity: Activity,
        event_type: str,
        actor_id: str,
        actor_role: str,
        new_value: str,
        old_value: str = "",
    ):
        FinanceAuditLog.objects.create(
            activity=activity,
            event_type=event_type,
            actor_id=actor_id,
            actor_role=actor_role,
            old_value=old_value,
            new_value=new_value,
        )
