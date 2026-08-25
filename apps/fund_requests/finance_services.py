import logging

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone
from apps.core.exceptions import BadRequest, Forbidden
from apps.activities.closure_services import (
    ActivityClosureService,
    ClosureEligibilityService,
)
from apps.activities.models import Activity
from apps.fund_requests.models import (
    MONEY_MOVED_ADVANCE_STATUSES,
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


def _assert_may_pay(actor) -> None:
    """Only a holder of `payment.act` may move partner money.

    Read from the permission matrix rather than a role tuple — the same
    contract `weekly_service._assert_may_disburse` enforces on the weekly
    channel. The 2026-08 audit's AUD-004 put `Permission.PAYMENT_ACT` into
    `ADMIN_EXCLUDED_PERMISSIONS` so the account that can approve a budget or
    verify an activity cannot also release the money for it. The partner
    channel handed that authority straight back three separate ways (FIN-03):
    `require_page_permission("disbursements")` alone on the payment screens
    (navigation maps that page to {Accountant, Admin} — reading a queue is not
    authority to pay out of it), the ("Accountant", "CountryDirector",
    "Admin") tuples in `partner_invoices` and `vendor_channel`, and no check
    at all inside `pay_partner`. Asserting here, at the money, is what stops
    the next screen re-opening the hole.

    `actor` is a principal, or the bare `user_id` these services still carry
    in places — resolved to its User the way the surrounding code does. An
    actor that does not resolve has no authority we can establish, and this is
    the last gate before the money moves, so it is refused.
    """
    from apps.core.permissions import has_permission
    from apps.core.rbac import Permission

    if isinstance(actor, str):
        from apps.accounts.models import User

        actor = User.objects.filter(id=actor).first()
    if not has_permission(actor, Permission.PAYMENT_ACT.value):
        raise Forbidden("Only a Program Accountant can pay partners.")


# The one definition of "this partner activity still needs paying".
#
# Four surfaces each carried their own version — the Disbursement Dashboard
# matched only `ia_confirmed`, the partner-payments page matched
# `none|ia_confirmed`, batch payments matched a third set, and the activities
logger = logging.getLogger(__name__)


# API a fourth. The same queue therefore showed different rows and different
# totals depending on which page the Accountant happened to open.
# "disbursed" = the 50% MOU advance is out and the balance awaits clearance
# once the partner finishes and IA verifies the work.
PARTNER_PAYABLE_STATUSES = ("none", "ia_confirmed", "disbursed")

# Statuses meaning money already left for this activity — never payable again.
PARTNER_PAID_STATUSES = ("disbursed", "paid")


def notify_partner_clearance_eligibility(activity):
    """MOU prompts after IA verifies a partner activity.

    The accountants are prompted that the balance is now clearable, and —
    once the partner's WHOLE slate of assigned work is verified — the partner
    is told they are eligible for clearance and should send their invoice for
    the remaining 50%. Both fire-and-forget: a notification failure must
    never roll back a verification.
    """
    if activity.delivery_type != "partner":
        return
    try:
        from apps.accounts.models import User
        from apps.notifications.services import WorkflowNotificationService

        cleared = PartnerPayment.objects.filter(
            activity=activity, payment_type=PartnerPayment.TYPE_CLEARANCE
        ).exists()
        if cleared:
            return
        has_advance = PartnerPayment.objects.filter(
            activity=activity, payment_type=PartnerPayment.TYPE_ADVANCE
        ).exists()

        acct_ids = list(
            User.objects.filter(active_role="Accountant", is_active=True).values_list(
                "id", flat=True
            )
        )
        if acct_ids:
            WorkflowNotificationService.trigger(
                event_type="partner_clearance_ready",
                category="finance",
                priority="high",
                title="Partner balance ready to clear",
                body=(
                    f"IA verified partner work (activity #{activity.id[:8]})."
                    + (
                        " The 50% MOU advance is out — the remaining balance "
                        "can now be cleared."
                        if has_advance
                        else " The partner payment can now be processed."
                    )
                ),
                context_type="Activity",
                context_id=activity.id,
                recipients=acct_ids,
            )

        partner_id = activity.assigned_partner_id
        if not partner_id:
            return
        from apps.partners.models import Partner as _Partner

        _p = _Partner.objects.filter(id=partner_id).select_related("user").first()
        _p_user_id = getattr(getattr(_p, "user", None), "id", None)
        # §12.5: EVERY verification tells the partner this activity is now
        # "Completed — Awaiting Payment". The slate-clear invoice prompt
        # below is a separate, second nudge — gating the only notice on the
        # whole slate left a partner with ten assignments hearing nothing
        # for the first nine verifications (2026-08-19 audit F8).
        if _p_user_id:
            WorkflowNotificationService.trigger(
                event_type="partner_activity_verified",
                category="finance",
                priority="normal",
                title="Work verified — awaiting payment",
                body=(
                    "IA verified your delivery "
                    f"(activity #{activity.id[:8]}). It now counts toward "
                    "your next invoice — track it on Completed & Payments."
                ),
                context_type="Activity",
                context_id=activity.id,
                recipients=[_p_user_id],
            )
        from apps.activities.models import Activity as _Activity

        still_outstanding = (
            _Activity.objects.filter(
                assigned_partner_id=partner_id,
                deleted_at__isnull=True,
                scheduled_date__isnull=False,
            )
            .exclude(
                status__in=[
                    "ia_verified",
                    "closed",
                    "accountant_confirmed",
                    "cancelled",
                    "rejected",
                    "deferred",
                ]
            )
            .exists()
        )
        if still_outstanding:
            return

        from apps.partners.models import Partner

        partner = Partner.objects.filter(id=partner_id).select_related("user").first()
        partner_user_id = getattr(getattr(partner, "user", None), "id", None)
        if partner_user_id:
            WorkflowNotificationService.trigger(
                event_type="partner_clearance_eligible",
                category="finance",
                priority="high",
                title="Eligible for clearance — send your invoice",
                body=(
                    "IA has verified all your assigned activities. You are "
                    "eligible for clearance of the remaining balance — please "
                    "send your invoice for the outstanding 50% to the "
                    "accountant."
                ),
                context_type="Partner",
                context_id=partner_id,
                recipients=[partner_user_id],
            )
    except Exception:  # noqa: BLE001
        logger.exception("partner MOU clearance notification failed")


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
                # Distinguish "money already out" from "not confirmed yet":
                # a repeat disbursement attempt used to surface as the
                # confirmation message below, inviting a retry through
                # another channel instead of stating the money moved.
                if activity.advance_requests.filter(
                    status__in=MONEY_MOVED_ADVANCE_STATUSES
                ).exists():
                    raise BadRequest(
                        "Cannot disburse — this activity's advances already "
                        "had money released. Disbursing again would pay the "
                        "same work twice."
                    )
                raise BadRequest(
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
    """Manages partner payments under the MOU: 50% of the planned activity
    cost as an advance up front, and the balance cleared only after the
    partner finishes the work and IA verifies it."""

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
        payment_type: str = PartnerPayment.TYPE_CLEARANCE,
        notify_partner: bool = True,
    ) -> PartnerPayment:
        # Authority first, before the row lock and before any write: the
        # screens gate three different ways and one of them (FIN-03) let a
        # role without `payment.act` through. See _assert_may_pay.
        _assert_may_pay(user_id)
        # Every guard below — including the one-payout-per-activity check —
        # must run against a LOCKED activity row, inside the same transaction
        # that writes the payment. Read unlocked (as they were), two accountants
        # clicking Pay at the same moment both saw payment_status != "paid",
        # both passed, and the second insert died on the unique constraint:
        # measured 1 success and 3 raw IntegrityErrors on a four-way race.
        # The money was never doubled — the constraint held — but the losing
        # accountant got a 500 on a payment screen, which is its own incident:
        # they cannot tell whether the money moved, and the natural response to
        # a failed payment page is to pay again.
        with transaction.atomic():
            locked = Activity.objects.select_for_update().filter(id=activity.id).first()
            if locked is None:
                raise BadRequest("Activity not found.")
            activity = locked
            return PartnerPaymentService._pay_partner_locked(
                activity=activity,
                partner_name=partner_name,
                amount=amount,
                method=method,
                reference=reference,
                user_id=user_id,
                notes=notes,
                netsuite_id=netsuite_id,
                payment_type=payment_type,
                notify_partner=notify_partner,
            )

    @staticmethod
    def _pay_partner_locked(
        activity: Activity,
        partner_name: str,
        amount: int,
        method: str,
        reference: str,
        user_id: str,
        notes: str = "",
        netsuite_id: str = "",
        payment_type: str = PartnerPayment.TYPE_CLEARANCE,
        notify_partner: bool = True,
    ) -> PartnerPayment:
        """The body of pay_partner, run with the activity row already locked
        and inside the caller's transaction."""
        if payment_type not in (
            PartnerPayment.TYPE_ADVANCE,
            PartnerPayment.TYPE_CLEARANCE,
        ):
            raise BadRequest(f"Unknown partner payment type '{payment_type}'.")

        is_advance = payment_type == PartnerPayment.TYPE_ADVANCE
        if is_advance:
            # The MOU advance is paid BEFORE the work happens, so the
            # execution blockers (IA verification, evidence) do not apply —
            # but dead work must never be advanced against, and the plan must
            # actually be costed.
            from apps.core.activity_types import NON_FUNDABLE_ACTIVITY_STATUSES

            if activity.status in NON_FUNDABLE_ACTIVITY_STATUSES:
                raise BadRequest(
                    "The MOU advance cannot be paid on cancelled, deferred or "
                    "rejected work."
                )
            if not activity.schedule_cost_lines.exists():
                raise BadRequest(
                    "The MOU advance needs the activity's costed budget lines "
                    "— schedule and cost the activity first."
                )
        else:
            # Clearance settles the balance only after verified execution.
            reasons = FinanceBlockedReasonService.get_blocked_reasons(activity)
            if reasons:
                raise BadRequest(f"Partner payment is blocked: {', '.join(reasons)}")

        # Amounts come from the plan, never the caller's keyboard — the same
        # contract weekly_service.disburse enforces. The MOU fixes the split:
        # the advance is exactly 50% of the planned activity cost, and the
        # clearance settles the remaining balance after verification.
        # Idempotency: one payout per activity and instalment, checked BEFORE
        # the amount arithmetic so a racing second payer is told the payment
        # is already recorded (not a balance message). Runs under the
        # caller's row lock; the DB unique constraint on
        # (activity, payment_type) stays as the last line of defence for any
        # writer that reaches the table without taking the lock.
        if (
            activity.payment_status == "paid"
            or PartnerPayment.objects.filter(
                activity=activity, payment_type=PartnerPayment.TYPE_CLEARANCE
            ).exists()
        ):
            raise BadRequest(
                "Partner payment already recorded for this activity — a further "
                "payout would double-count the money."
            )
        if (
            is_advance
            and PartnerPayment.objects.filter(
                activity=activity, payment_type=PartnerPayment.TYPE_ADVANCE
            ).exists()
        ):
            raise BadRequest(
                "The 50% MOU advance is already recorded for this activity — "
                "a second advance would double-count the money."
            )

        planned_total = (
            activity.schedule_cost_lines.aggregate(s=Sum("amount"))["s"] or 0
        )
        paid_so_far = (
            PartnerPayment.objects.filter(activity=activity).aggregate(
                s=Sum("amount_paid")
            )["s"]
            or 0
        )
        if is_advance:
            expected_advance = planned_total // 2
            if expected_advance <= 0:
                raise BadRequest("This activity has no planned budget to advance.")
            if amount != expected_advance:
                raise BadRequest(
                    "The MOU advance is exactly 50% of the planned activity "
                    f"cost — {expected_advance} UGX for this activity."
                )
        else:
            remaining = planned_total - paid_so_far
            if remaining <= 0:
                raise BadRequest(
                    "Nothing remains to clear on this activity — the planned "
                    "budget is already fully paid."
                )
            if amount <= 0 or amount > remaining:
                raise BadRequest(
                    "Partner clearance must be positive and within the "
                    f"remaining balance of {remaining} UGX (planned "
                    f"{planned_total}, already paid {paid_so_far})."
                )

        # Cross-channel guard: a partner activity whose staff advance already
        # moved money must not ALSO be partner-paid against the same cost
        # lines (the advance and partner channels had no mutual exclusion).
        if activity.advance_requests.filter(
            status__in=MONEY_MOVED_ADVANCE_STATUSES
        ).exists():
            raise BadRequest(
                "This activity already has money released through the advance "
                "channel — settle that accountability instead of issuing a "
                "partner payment for the same cost lines."
            )

        # NetSuite IDs are STAFF accountability proof — money a staff member
        # received and must account for. Partners are paid directly by the
        # accountant, so no NetSuite entry is asked here (owner, 2026-08-20);
        # the payment itself, with its reference, is the finance proof, and
        # the closure gate's check 7 exempts partner deliveries to match.
        netsuite_id = (netsuite_id or "").strip()

        with transaction.atomic():
            # A savepoint around the insert: if the unique constraint fires
            # anyway — a writer that reached the table without the row lock —
            # the accountant is told the payment already exists instead of
            # being shown a database error on a payment screen.
            try:
                with transaction.atomic():
                    pay = PartnerPayment.objects.create(
                        activity=activity,
                        partner_name=partner_name,
                        payment_type=payment_type,
                        amount_paid=amount,
                        payment_method=method,
                        payment_reference=reference,
                        paid_by=user_id,
                        notes=notes,
                    )
            except IntegrityError as exc:
                if "uniq_partner_payment_per_activity" in str(exc):
                    raise BadRequest(
                        "This instalment is already recorded for this activity "
                        "— a second payout would double-count the money."
                    ) from exc
                raise

            # 50% advance out → "disbursed" (money moved, accountability
            # open); clearance → "paid" (the terminal partner state).
            activity.payment_status = "disbursed" if is_advance else "paid"
            activity.save(update_fields=["payment_status", "updated_at"])

            FinanceAuditService.log_finance_event(
                activity=activity,
                event_type="partner_payment",
                actor_id=user_id,
                actor_role="Accountant",
                new_value=(
                    f"Paid partner {partner_name} {amount} UGX "
                    f"({pay.get_payment_type_display()}) via {method} "
                    f"(Ref: {reference})."
                ),
            )
            _chain_audit(
                "finance.partner_paid",
                activity,
                user_id,
                {
                    "partner": partner_name,
                    "amount": amount,
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

            # The partner hears about EVERY payment, whichever screen paid it
            # — the invoice wrapper notified but the direct finance screens
            # (including the 50% MOU advance) paid silently (audit F9).
            def _tell_partner(pay_id=pay.id, act=activity, amt=amount):
                if not notify_partner:
                    return
                try:
                    from apps.partners.models import Partner as _Partner
                    from apps.notifications.services import (
                        WorkflowNotificationService,
                    )

                    p = (
                        _Partner.objects.filter(id=act.assigned_partner_id)
                        .select_related("user")
                        .first()
                    )
                    p_user_id = getattr(getattr(p, "user", None), "id", None)
                    if p_user_id:
                        WorkflowNotificationService.trigger(
                            event_type="partner_payment_made",
                            category="finance",
                            priority="high",
                            title="Payment made to your organisation",
                            body=(
                                f"UGX {amt:,.0f} paid for activity "
                                f"#{act.id[:8]}. See Completed & Payments "
                                "for the reference."
                            ),
                            context_type="Activity",
                            context_id=act.id,
                            recipients=[p_user_id],
                        )
                except Exception:  # noqa: BLE001 — never break a payment
                    import logging

                    logging.getLogger(__name__).warning(
                        "partner payment notification failed", exc_info=True
                    )

            transaction.on_commit(_tell_partner)

            return pay


class ReimbursementService:
    """Fail-closed compatibility guard for the retired reimbursement ledger.

    Self-funded and over-spend reimbursement is owned by ``AdvanceRequest``:
    ``submit_reimbursement``/``approve_accountability`` → ``reimburse`` →
    ``confirm_reimbursement_receipt``. That canonical path locks one row,
    derives the variance, requires a NetSuite Code and employee receipt, and
    leaves closure to ``ActivityClosureService``.

    Historical ``ReimbursementClaim`` rows remain readable for audit, but old
    integrations must not create a second payable debt or close an Activity
    by assigning its status directly.
    """

    _RETIRED_MESSAGE = (
        "The legacy reimbursement-claim workflow is retired. Use the Activity's "
        "AdvanceRequest accountability workflow, which derives one reimbursement, "
        "requires NetSuite verification and receipt confirmation, and closes only "
        "through the canonical ActivityClosureService."
    )

    @staticmethod
    def claim_reimbursement(
        activity: Activity, actual_spend: int, staff_id: str, notes: str = ""
    ) -> ReimbursementClaim:
        raise BadRequest(ReimbursementService._RETIRED_MESSAGE)

    @staticmethod
    def disburse_reimbursement(
        claim: ReimbursementClaim, method: str, reference: str, user_id: str
    ) -> ReimbursementClaim:
        raise BadRequest(ReimbursementService._RETIRED_MESSAGE)


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
            raise BadRequest("No advance disbursement found for this activity.")

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
            raise BadRequest(
                "A valid NetSuite Expense ID is required (alphanumeric, 3-64 "
                "characters). Accountability cannot clear without it."
            )

        with transaction.atomic():
            # Lock the activity row + guard against re-clearing an already
            # cleared/closed record (double-click / replay immutability).
            locked = Activity.objects.select_for_update().filter(id=activity.id).first()
            if locked and locked.status == "closed":
                raise BadRequest(
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
