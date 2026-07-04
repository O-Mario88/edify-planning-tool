from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from apps.activities.models import Activity
from apps.fund_requests.models import (
    Disbursement,
    PartnerPayment,
    ReimbursementClaim,
    AccountabilityRecord,
    Receipt,
    NetSuiteExpenseRecord,
    VarianceReview,
    FinanceAuditLog
)
from apps.notifications.models import Notification

class FinanceBlockedReasonService:
    """Evaluates if an activity's finance steps are blocked and provides clean reasons."""
    @staticmethod
    def get_blocked_reasons(activity: Activity, has_evidence: bool | None = None, has_budget_lines: bool | None = None) -> list[str]:
        reasons = []
        
        # Rule 1: No IA verification -> no final clearance
        if activity.status not in ["ia_verified", "closed", "accountant_confirmed"]:
            reasons.append("IA Verification Missing")

        # Rule 2: No evidence -> no clearance
        if has_evidence is None:
            from apps.evidence.models import EvidenceRecord
            has_evidence = EvidenceRecord.objects.filter(activity_id=activity.id, quarantined=False).exists()
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
    def disburse_advance(activity: Activity, amount: int, method: str, reference: str, user_id: str, notes: str = "") -> Disbursement:
        with transaction.atomic():
            # Create Disbursement
            disb = Disbursement.objects.create(
                activity=activity,
                amount_disbursed=amount,
                disbursed_by=user_id,
                payment_method=method,
                payment_reference=reference,
                notes=notes
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
                status="pending"
            )
            
            # Log Audit
            FinanceAuditService.log_finance_event(
                activity=activity,
                event_type="advance_disbursement",
                actor_id=user_id,
                actor_role="Accountant",
                new_value=f"Disbursed advance of {amount} UGX via {method} (Ref: {reference})"
            )
            
            # Send Notification
            if activity.responsible_staff_id:
                Notification.objects.create(
                    recipient_id=activity.responsible_staff_id,
                    title="Advance Funds Disbursed",
                    body=f"Advance of {amount // 100} UGX disbursed for Activity #{activity.id[:8]}. Please submit accountability after execution.",
                    priority="normal"
                )
                
            return disb


class PartnerPaymentService:
    """Manages partner payments after verified execution."""
    @staticmethod
    def pay_partner(activity: Activity, partner_name: str, amount: int, method: str, reference: str, user_id: str, notes: str = "") -> PartnerPayment:
        # Enforce blockers
        reasons = FinanceBlockedReasonService.get_blocked_reasons(activity)
        if reasons:
            raise ValueError(f"Partner payment is blocked: {', '.join(reasons)}")

        with transaction.atomic():
            pay = PartnerPayment.objects.create(
                activity=activity,
                partner_name=partner_name,
                amount_paid=amount,
                payment_method=method,
                payment_reference=reference,
                paid_by=user_id,
                notes=notes
            )
            
            activity.payment_status = "paid"
            activity.status = "closed"
            activity.save(update_fields=["payment_status", "status", "updated_at"])
            
            FinanceAuditService.log_finance_event(
                activity=activity,
                event_type="partner_payment",
                actor_id=user_id,
                actor_role="Accountant",
                new_value=f"Paid partner {partner_name} {amount} UGX via {method} (Ref: {reference})"
            )
            
            return pay


class ReimbursementService:
    """Manages staff self-funded activities and overspent budgets claims."""
    @staticmethod
    def claim_reimbursement(activity: Activity, actual_spend: int, staff_id: str, notes: str = "") -> ReimbursementClaim:
        approved_budget = activity.schedule_cost_lines.aggregate(s=Sum("amount"))["s"] or 0
        
        # Calculate disbursed amount
        disbursed = Disbursement.objects.filter(activity=activity).aggregate(s=Sum("amount_disbursed"))["s"] or 0
        
        reimbursement_amount = actual_spend - disbursed
        if reimbursement_amount <= 0:
            raise ValueError("Actual spend does not exceed advance amount. No reimbursement needed.")

        with transaction.atomic():
            claim = ReimbursementClaim.objects.create(
                activity=activity,
                staff_id=staff_id,
                approved_budget=approved_budget,
                amount_advanced=disbursed,
                actual_spend=actual_spend,
                reimbursement_amount=reimbursement_amount,
                status="pending",
                notes=notes
            )
            
            # Log event
            FinanceAuditService.log_finance_event(
                activity=activity,
                event_type="reimbursement_claimed",
                actor_id=staff_id,
                actor_role="CCEO",
                new_value=f"Claimed reimbursement of {reimbursement_amount} UGX (Spend: {actual_spend}, Advance: {disbursed})"
            )
            
            return claim

    @staticmethod
    def disburse_reimbursement(claim: ReimbursementClaim, method: str, reference: str, user_id: str) -> ReimbursementClaim:
        activity = claim.activity
        
        # Reimbursement can only be paid if IA Verified
        if activity.status not in ["ia_verified", "closed", "accountant_confirmed"]:
            raise ValueError("Reimbursement is blocked: IA Verification Missing")

        with transaction.atomic():
            claim.status = "paid"
            claim.payment_method = method;
            claim.payment_reference = reference;
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
                notes=f"Reimbursement payout for claim ID {claim.id}"
            )
            
            # Close the activity
            activity.status = "closed"
            activity.save(update_fields=["status", "updated_at"])
            
            FinanceAuditService.log_finance_event(
                activity=activity,
                event_type="reimbursement_disbursed",
                actor_id=user_id,
                actor_role="Accountant",
                new_value=f"Disbursed reimbursement claim of {claim.reimbursement_amount} UGX via {method} (Ref: {reference})"
            )
            
            return claim


class AccountabilityService:
    """Manages staff submitting receipts and closing advance variances."""
    @staticmethod
    def submit_accountability(activity: Activity, actual_spend: int, variance_reason: str, staff_id: str, receipts: list[dict] = None) -> AccountabilityRecord:
        disbursed = Disbursement.objects.filter(activity=activity).aggregate(s=Sum("amount_disbursed"))["s"] or 0
        
        if disbursed == 0:
            raise ValueError("No advance disbursement found for this activity.")
            
        variance = actual_spend - disbursed
        status = "netsuite_id_required"
        if variance != 0:
            status = "variance_review"

        with transaction.atomic():
            # Clear old records
            AccountabilityRecord.objects.filter(activity=activity, status="pending").delete()
            
            record = AccountabilityRecord.objects.create(
                activity=activity,
                staff_id=staff_id,
                amount_disbursed=disbursed,
                actual_spend=actual_spend,
                variance=variance,
                variance_reason=variance_reason,
                status=status
            )
            
            # Save Receipts if any
            if receipts:
                for r in receipts:
                    Receipt.objects.create(
                        accountability_record=record,
                        original_name=r["original_name"],
                        uri=r["uri"],
                        file_size=r["file_size"],
                        mime_type=r.get("mime_type", "")
                    )
            
            # Save Variance Review if needed
            if variance != 0:
                VarianceReview.objects.create(
                    activity=activity,
                    budgeted_amount=activity.schedule_cost_lines.aggregate(s=Sum("amount"))["s"] or 0,
                    disbursed_amount=disbursed,
                    actual_spend=actual_spend,
                    variance=variance,
                    reason=variance_reason,
                    status="pending"
                )
                
            FinanceAuditService.log_finance_event(
                activity=activity,
                event_type="accountability_submitted",
                actor_id=staff_id,
                actor_role="CCEO",
                new_value=f"Submitted accountability. Spend: {actual_spend} UGX, Variance: {variance} UGX"
            )
            
            return record


class NetSuiteExpenseService:
    """Manages entering NetSuite ID and matching duplicates."""
    @staticmethod
    def enter_netsuite_id(activity: Activity, netsuite_id: str, amount: int, expense_date, user_id: str, notes: str = "") -> NetSuiteExpenseRecord:
        # Check if already entered for another activity (duplicate check)
        is_dup = NetSuiteExpenseRecord.objects.filter(netsuite_expense_id=netsuite_id).exclude(activity=activity).exists()
        
        with transaction.atomic():
            rec, _ = NetSuiteExpenseRecord.objects.update_or_create(
                activity=activity,
                defaults={
                    "netsuite_expense_id": netsuite_id,
                    "expense_date": expense_date,
                    "amount_entered": amount,
                    "entered_by": user_id,
                    "notes": f"[DUPLICATE RISK] {notes}" if is_dup else notes
                }
            )
            
            # Update AccountabilityRecords
            AccountabilityRecord.objects.filter(activity=activity).update(
                netsuite_expense_id=netsuite_id,
                status="cleared",
                reviewed_at=timezone.now(),
                reviewed_by=user_id
            )
            
            # If everything else is clean (IA verified, Salesforce ID, evidence exists), close the activity
            reasons = FinanceBlockedReasonService.get_blocked_reasons(activity)
            if not reasons:
                activity.status = "closed"
                activity.save(update_fields=["status", "updated_at"])
                
            FinanceAuditService.log_finance_event(
                activity=activity,
                event_type="netsuite_id_entered",
                actor_id=user_id,
                actor_role="Accountant",
                new_value=f"Entered NetSuite ID: {netsuite_id}. Duplicate Risk: {is_dup}"
            )
            
            return rec


class FinanceAuditService:
    """Helper to log all financial operations."""
    @staticmethod
    def log_finance_event(activity: Activity, event_type: str, actor_id: str, actor_role: str, new_value: str, old_value: str = ""):
        FinanceAuditLog.objects.create(
            activity=activity,
            event_type=event_type,
            actor_id=actor_id,
            actor_role=actor_role,
            old_value=old_value,
            new_value=new_value
        )
