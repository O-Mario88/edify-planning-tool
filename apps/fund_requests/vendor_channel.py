"""Vendor-direct mission costs — the accountant's channel decisions.

School-visit transport is always paid to the transport company (rule, not
data). Accommodation moves to the vendor channel per line when Finance books
the hotel directly; the owner's weekly draft regenerates without it and the
owner sees a booking status instead of an amount.
"""

from __future__ import annotations

from django.db import transaction

from apps.core.exceptions import BadRequest, Forbidden


def _assert_may_decide(principal) -> None:
    if getattr(principal, "active_role", "") not in (
        "Accountant",
        "CountryDirector",
        "Admin",
    ):
        raise Forbidden("Only Finance can change how a mission cost is paid.")


def set_accommodation_vendor_paid(line_id: str, vendor_paid: bool, principal) -> dict:
    """Mark one accommodation line hotel-booked (or hand it back to the
    owner's advance). Refused once the carrying weekly request has left the
    owner's hands — the approved figure must not silently change."""
    from apps.activities.models import ActivityScheduleCostLine
    from apps.fund_requests.models import WeeklyFundRequest
    from apps.fund_requests.weekly_service import (
        REBUILDABLE_WEEKLY_STATUSES,
        generate_weekly_fund_request,
    )

    _assert_may_decide(principal)
    with transaction.atomic():
        line = (
            ActivityScheduleCostLine.objects.select_for_update()
            .select_related("activity")
            .filter(id=line_id)
            .first()
        )
        if line is None:
            raise BadRequest("Budget line not found.")
        if line.line_item_type != "accommodation":
            raise BadRequest("Only accommodation can move to the vendor channel.")

        frozen = (
            WeeklyFundRequest.objects.select_for_update()
            .filter(
                lines__activity_budget_line=line,
            )
            .exclude(status__in=REBUILDABLE_WEEKLY_STATUSES)
            .exists()
        )
        if frozen:
            raise BadRequest(
                "This week's request is already submitted or approved — "
                "return it before changing how accommodation is paid."
            )

        line.vendor_paid = bool(vendor_paid)
        line.save(update_fields=["vendor_paid", "updated_at"])

    owner = line.responsible_user
    week = line.week_start_date
    if owner and week:
        generate_weekly_fund_request(owner, week.isoformat())

    from apps.audit.services import log as audit_log

    audit_log(
        action="mission_cost.accommodation_channel",
        subject_kind="ActivityScheduleCostLine",
        subject_id=line.id,
        actor_id=principal.user_id,
        actor_role=getattr(principal, "active_role", None),
        payload={
            "vendor_paid": bool(vendor_paid),
            "activity_id": line.activity_id,
            "amount": line.amount,
        },
    )

    return {"id": line.id, "vendorPaid": line.vendor_paid}


def ensure_transport_obligation(batch):
    """§9.1 — one vendor obligation per mission day. Created/refreshed from
    the batch's pooled transport component while pending; immutable once
    paid (a re-priced day never silently rewrites a settled invoice)."""
    from .finance_models import TransportPayment

    transport_amount = sum(
        int(v) for k, v in (batch.rate_snapshot or {}).items() if "transport" in k
    )
    if not transport_amount:
        TransportPayment.objects.filter(batch=batch, status="pending").delete()
        return None
    payment, created = TransportPayment.objects.get_or_create(
        batch=batch,
        defaults={
            "provider_name": "Approved transport provider",
            "amount": transport_amount,
        },
    )
    if (
        not created
        and payment.status == "pending"
        and payment.amount != transport_amount
    ):
        payment.amount = transport_amount
        payment.save(update_fields=["amount", "updated_at"])
    return payment


def pay_transport_provider(payment_id: str, data: dict, principal) -> dict:
    """Accountant settles the transport company for one mission day.

    Never combined with the staff allowance transfer; requires the provider,
    a payment reference and the NetSuite expense id, and refuses double
    payment under a row lock."""
    from django.utils import timezone

    from .finance_models import TransportPayment
    from .finance_services import _assert_may_pay

    # Deciding how a mission cost is PAID is a Finance-wide call
    # (_assert_may_decide above); actually paying the provider is not. This
    # moves money, so it needs `payment.act` — which the 2026-08 audit's
    # AUD-004 withholds from Admin, and which CountryDirector has never held
    # (FIN-03). Strictly tighter than _assert_may_decide, never wider.
    _assert_may_pay(principal)
    with transaction.atomic():
        payment = (
            TransportPayment.objects.select_for_update()
            .select_related("batch")
            .filter(id=payment_id)
            .first()
        )
        if payment is None:
            raise BadRequest("Transport payment not found.")
        if payment.status == "paid":
            raise BadRequest(
                "This mission day's transport is already paid — a second "
                "payout would double-pay the provider."
            )
        provider = (data.get("provider_name") or "").strip()
        reference = (data.get("payment_reference") or "").strip()
        netsuite = (data.get("netsuite_expense_id") or "").strip()
        if not provider:
            raise BadRequest("Name the transport provider being paid.")
        if not reference:
            raise BadRequest("A payment reference is required.")
        # No NetSuite ID asked: those are STAFF accountability proof (owner,
        # 2026-08-20). The accountant pays the provider directly — the
        # reference is the proof. The field is kept when a value is offered.
        payment.provider_name = provider
        payment.payment_method = (data.get("payment_method") or "").strip()
        payment.payment_reference = reference
        payment.netsuite_expense_id = netsuite
        payment.status = "paid"
        payment.paid_by = principal.user_id
        payment.paid_at = timezone.now()
        payment.notes = (data.get("notes") or "").strip()
        payment.save()

    from apps.audit.services import log as audit_log

    audit_log(
        action="transport_payment.paid",
        subject_kind="TransportPayment",
        subject_id=payment.id,
        actor_id=principal.user_id,
        actor_role=getattr(principal, "active_role", None),
        payload={
            "amount": payment.amount,
            "provider": payment.provider_name,
            "batch_id": payment.batch_id,
            "reference": reference,
        },
    )
    return {"id": payment.id, "status": payment.status, "amount": payment.amount}
