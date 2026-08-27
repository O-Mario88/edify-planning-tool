"""PDFundRequestService — the dedicated PD finance queue (§15–16).

A PD fund request is created only after Supervisor + HR approval, and only
for funded courses. It never touches ActivityBudgetLine, WeeklyFundRequest or
CountryMonthlyBudget — Professional Development funding is a wholly separate
ledger from school-activity budgets, by design (§15).

The Accountant who disburses or clears a PD request's accountability must
never be the requester (§31) — enforced the same way as the HR stage: exclude
self from the eligible-approver pool at the point of action, not just at
submission.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import BadRequest, Forbidden

from apps.professional_development.models import (
    PDFundRequestStatus,
    PDStatus,
    ProfessionalDevelopmentDisbursement,
    ProfessionalDevelopmentFundRequest,
    ProfessionalDevelopmentRequest,
)

FINANCE_ROLE = "Accountant"

# The Accountant's disbursement queue item, named so that disbursing (or
# returning) the request can close it — the resolution path the raw insert it
# replaces never had (INTG-03).
PD_FUND_PENDING_DISBURSEMENT = "pd_fund_request_pending_disbursement"


def _assert_finance_role(req: ProfessionalDevelopmentRequest, principal) -> None:
    role = getattr(principal, "active_role", "")
    if role not in (FINANCE_ROLE, "Admin"):
        raise Forbidden("Only an Accountant may act on PD finance items.")
    if req.staff_id == (principal.staff_profile_id or ""):
        raise Forbidden(
            "You cannot process your own Professional Development funding — "
            "ask another Accountant to handle this request."
        )


class PDFundRequestService:
    @staticmethod
    def can_review(req: ProfessionalDevelopmentRequest, principal) -> bool:
        if req.staff_id == (principal.staff_profile_id or ""):
            return False
        if getattr(principal, "active_role", "") not in (FINANCE_ROLE, "Admin"):
            return False
        return req.status in (
            PDStatus.APPROVED_PENDING_FUNDING,
            PDStatus.ACCOUNTABILITY_SUBMITTED,
        )

    @staticmethod
    def create(
        req: ProfessionalDevelopmentRequest,
    ) -> ProfessionalDevelopmentFundRequest:
        fr, _ = ProfessionalDevelopmentFundRequest.objects.get_or_create(
            request=req,
            defaults={
                "fy": req.fy,
                "staff_id": req.staff_id,
                "amount_cents": req.requested_amount_cents,
                "currency": req.currency,
                "payment_recipient": req.payment_recipient,
                "payment_details": req.payment_details,
            },
        )
        try:
            from apps.professional_development.approval_service import _pick_approver

            approver = _pick_approver(FINANCE_ROLE, req.owner_user_id)
            if approver:
                # Through `_notify`, not a raw insert (INTG-03). The raw insert
                # set no `source_event_type`, so the Accountant's disbursement
                # queue item could never be closed by disbursing it — it stayed
                # "Action Required" past the payment and the 48-hour escalation
                # job then promoted it to urgent.
                PDFundRequestService._notify(
                    approver.id,
                    "PD fund request awaiting disbursement",
                    f"{req.staff_name} — “{req.course_name}” "
                    f"({req.currency} {req.requested_amount_cents / 100:,.0f}).",
                    req,
                    event_type=PD_FUND_PENDING_DISBURSEMENT,
                )
        except Exception:  # noqa: BLE001 — notification is supportive, never blocking
            pass
        return fr

    @staticmethod
    @transaction.atomic
    def disburse(
        fund_request_id: str, principal, *, method: str, reference: str, notes: str = ""
    ) -> ProfessionalDevelopmentFundRequest:
        fr = ProfessionalDevelopmentFundRequest.objects.select_for_update().get(
            id=fund_request_id
        )
        req = ProfessionalDevelopmentRequest.objects.select_for_update().get(
            id=fr.request_id
        )
        _assert_finance_role(req, principal)
        if fr.status != PDFundRequestStatus.PENDING_DISBURSEMENT:
            raise BadRequest("This PD fund request is not pending disbursement.")
        ProfessionalDevelopmentDisbursement.objects.create(
            fund_request=fr,
            amount_cents=fr.amount_cents,
            disbursed_by=principal.user_id,
            payment_method=method,
            payment_reference=reference,
            notes=notes,
        )
        fr.status = PDFundRequestStatus.DISBURSED
        fr.save(update_fields=["status", "updated_at"])
        req.status = PDStatus.DISBURSED
        req.save(update_fields=["status", "updated_at"])
        from apps.professional_development.approval_service import _audit_decision

        _audit_decision("pd_disburse", req, principal)
        # Paying it is what ends "awaiting disbursement" (INTG-03).
        PDFundRequestService._close_pending_disbursement(req)
        PDFundRequestService._notify(
            req.owner_user_id,
            "PD funds disbursed",
            f"Funding for “{req.course_name}” has been disbursed — confirm receipt and "
            "your enrollment.",
            req,
        )
        return fr

    @staticmethod
    def hold(
        fund_request_id: str, principal, reason: str
    ) -> ProfessionalDevelopmentFundRequest:
        fr = ProfessionalDevelopmentFundRequest.objects.get(id=fund_request_id)
        req = ProfessionalDevelopmentRequest.objects.get(id=fr.request_id)
        _assert_finance_role(req, principal)
        fr.status = PDFundRequestStatus.HELD
        fr.hold_reason = (reason or "")[:512]
        fr.save()
        return fr

    @staticmethod
    def return_request(
        fund_request_id: str, principal, reason: str
    ) -> ProfessionalDevelopmentFundRequest:
        if not (reason or "").strip():
            raise BadRequest("A return reason is required.")
        fr = ProfessionalDevelopmentFundRequest.objects.get(id=fund_request_id)
        req = ProfessionalDevelopmentRequest.objects.get(id=fr.request_id)
        _assert_finance_role(req, principal)
        fr.status = PDFundRequestStatus.RETURNED
        fr.return_reason = reason[:512]
        fr.save()
        req.status = PDStatus.RETURNED_BY_HR  # back into the correction loop
        req.hr_note = f"Finance returned: {reason}"[:512]
        req.save(update_fields=["status", "hr_note", "updated_at"])
        # It has left the disbursement queue for the correction loop, so the
        # Accountant's queue item is satisfied too (INTG-03).
        PDFundRequestService._close_pending_disbursement(req)
        PDFundRequestService._notify(
            req.owner_user_id, "PD funding request returned", reason, req
        )
        return fr

    # ── Accountability clearance (§23) ───────────────────────────────────────
    @staticmethod
    @transaction.atomic
    def clear_accountability(req_id: str, principal) -> ProfessionalDevelopmentRequest:
        # select_for_update() outside an atomic block raises
        # TransactionManagementError in production. Django's TestCase wraps
        # every test in a transaction, which hid this completely — the
        # Accountant's clearance action 500'd for real users while the suite
        # stayed green.
        req = ProfessionalDevelopmentRequest.objects.select_for_update().get(id=req_id)
        _assert_finance_role(req, principal)
        if req.status != PDStatus.ACCOUNTABILITY_SUBMITTED:
            raise BadRequest("Accountability has not been submitted for this request.")
        if not (req.accountability_netsuite_id or "").strip():
            raise BadRequest(
                "No NetSuite Expense ID on record — accountability cannot be cleared."
            )
        # Straight to the same AWAITING_HR_SIGNOFF gate unfunded courses reach
        # from BambooHR confirmation — sign_off() then has one uniform check
        # instead of a funded/unfunded branch. `accountability_reviewed_at`
        # is the durable "cleared" signal for reporting/timeline coloring.
        req.status = PDStatus.AWAITING_HR_SIGNOFF
        req.accountability_reviewed_by = principal.user_id
        req.accountability_reviewed_at = timezone.now()
        req.save()
        from apps.professional_development.approval_service import _audit_decision

        _audit_decision("pd_accountability_cleared", req, principal)
        PDFundRequestService._notify(
            req.owner_user_id,
            "PD accountability cleared",
            f"Finance cleared your accountability for “{req.course_name}” — "
            "awaiting HR sign-off.",
            req,
        )
        return req

    @staticmethod
    def return_accountability(
        req_id: str, principal, reason: str
    ) -> ProfessionalDevelopmentRequest:
        if not (reason or "").strip():
            raise BadRequest("A return reason is required.")
        req = ProfessionalDevelopmentRequest.objects.get(id=req_id)
        _assert_finance_role(req, principal)
        req.status = PDStatus.BAMBOOHR_CONFIRMED  # back to "submit accountability"
        req.accountability_variance_note = reason[:512]
        req.accountability_reviewed_by = principal.user_id
        req.accountability_reviewed_at = timezone.now()
        req.save()
        PDFundRequestService._notify(
            req.owner_user_id, "PD accountability returned", reason, req
        )
        return req

    @staticmethod
    def _close_pending_disbursement(req) -> None:
        """Close the Accountant's queue item once the request leaves the queue.

        Best-effort: a notification must never block a money movement.
        """
        try:
            from apps.notifications.services import resolve_condition

            resolve_condition(PD_FUND_PENDING_DISBURSEMENT, "pd_request", req.id)
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _notify(
        recipient_user_id, title, body, req, event_type="pd_action_required"
    ) -> None:
        if not recipient_user_id:
            return
        try:
            # Through the canonical service: a raw insert had no dedupe key, no
            # audit row and no realtime publish, so a daily reminder stacked a
            # new row every day for the same unchanged condition.
            from apps.notifications.services import WorkflowNotificationService

            WorkflowNotificationService.trigger(
                event_type=event_type,
                category="professional_development",
                priority="high",
                title=title,
                body=body,
                context_type="pd_request",
                context_id=req.id,
                recipients=[recipient_user_id],
            )
        except Exception:  # noqa: BLE001
            pass
