"""Partner invoice flow — period invoices through the PL to the accountant.

One invoice sums ALL of the partner's planned activity costs for a chosen
week, month or quarter, grouped by category (School Visits, Training
Facilitation Fee). The system fetches the period total; the amount the
partner enters must EQUAL it — that equality is the link between invoice and
plan. The payable is derived (50% on the advance invoice; the balance, only
for IA-cleared work, on the clearance invoice).

Routing: partner submits → the supervising Program Lead confirms the invoice
against the plan (or returns it) → the accountant downloads and pays. The
money still runs per activity through PartnerPaymentService.pay_partner, so
every instalment guard (exact 50%, balance clamp, IA blockers, idempotency,
NetSuite proof) keeps holding.
"""

from __future__ import annotations

import calendar
import os
import uuid
from datetime import date, timedelta

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core.exceptions import BadRequest, Forbidden

INVOICE_NAMESPACE = "partner-invoices"

_CLEARED_STATUSES = ("ia_verified", "closed", "accountant_confirmed")
_FINANCE_ROLES = ("Accountant", "CountryDirector", "Admin")


# ── scoping helpers ──────────────────────────────────────────────────────────
def _partner_ids_for(principal) -> list[str]:
    from apps.core.scoping import resolve_partner_ids

    ids = resolve_partner_ids(principal)
    if not ids:
        raise Forbidden("Only a partner account can submit partner invoices.")
    return ids


def _planned_total(activity) -> int:
    return activity.schedule_cost_lines.aggregate(s=Sum("amount"))["s"] or 0


def _paid_by_type(activity) -> dict[str, int]:
    from .finance_models import PartnerPayment

    totals: dict[str, int] = {}
    for p in PartnerPayment.objects.filter(activity=activity):
        totals[p.payment_type] = totals.get(p.payment_type, 0) + p.amount_paid
    return totals


def _category_of(activity) -> str:
    from apps.core.activity_types import TRAINING_TYPES

    if activity.activity_type in TRAINING_TYPES or "training" in activity.activity_type:
        return "Training Facilitation Fee"
    if activity.school_id:
        return "School Visits"
    return "Other Field Work"


# ── periods ──────────────────────────────────────────────────────────────────
def period_bounds(kind: str, anchor: date) -> tuple[date, date]:
    if kind == "week":
        start = anchor - timedelta(days=anchor.weekday())
        return start, start + timedelta(days=6)
    if kind == "month":
        start = anchor.replace(day=1)
        return start, anchor.replace(
            day=calendar.monthrange(anchor.year, anchor.month)[1]
        )
    if kind == "quarter":
        from apps.core.fy import get_operational_fy, get_quarter_date_range
        from apps.core.fy import get_quarter_for_date

        fy = get_operational_fy(anchor)
        quarter = get_quarter_for_date(anchor)
        return get_quarter_date_range(fy, quarter)
    raise BadRequest("Choose a week, month or quarter for the invoice.")


def period_label(kind: str, start: date, end: date) -> str:
    if kind == "week":
        return f"Week of {start:%d %b} – {end:%d %b %Y}"
    if kind == "month":
        return f"{start:%B %Y}"
    return f"{start:%d %b} – {end:%d %b %Y}"


# ── the invoice basis ────────────────────────────────────────────────────────
def invoice_basis(principal, kind: str, anchor: date, instalment: str) -> dict:
    """Everything the drawer (and submit) needs: the eligible activities in
    the period for this instalment, grouped totals, the system total and the
    derived payable."""
    from apps.activities.models import Activity
    from apps.core.activity_types import NON_FUNDABLE_ACTIVITY_STATUSES

    from .finance_models import PartnerInvoiceItem

    if instalment not in ("advance", "clearance"):
        raise BadRequest("Choose the 50% advance or the clearance invoice.")
    partner_ids = _partner_ids_for(principal)
    start, end = period_bounds(kind, anchor)

    already_invoiced = set(
        PartnerInvoiceItem.objects.filter(
            instalment=instalment,
            activity__assigned_partner_id__in=partner_ids,
        ).values_list("activity_id", flat=True)
    )

    activities = (
        Activity.objects.filter(
            assigned_partner_id__in=partner_ids,
            delivery_type="partner",
            deleted_at__isnull=True,
            scheduled_date__date__range=(start, end),
        )
        .exclude(status__in=NON_FUNDABLE_ACTIVITY_STATUSES)
        .select_related("school")
        .order_by("scheduled_date")
    )

    items = []
    for activity in activities:
        if activity.id in already_invoiced:
            continue
        planned = _planned_total(activity)
        if planned <= 0:
            continue
        paid = _paid_by_type(activity)
        if instalment == "advance":
            if paid.get("advance") or paid.get("clearance"):
                continue
            payable = planned // 2
        else:
            # The balance opens only after IA has cleared the work and the
            # advance actually moved.
            if activity.status not in _CLEARED_STATUSES:
                continue
            if not paid.get("advance"):
                continue
            if paid.get("clearance"):
                continue
            payable = planned - sum(paid.values())
        if payable <= 0:
            continue
        items.append(
            {
                "activity": activity,
                "planned": planned,
                "payable": payable,
                "category": _category_of(activity),
            }
        )

    groups: dict[str, dict] = {}
    for item in items:
        g = groups.setdefault(
            item["category"], {"planned": 0, "payable": 0, "count": 0}
        )
        g["planned"] += item["planned"]
        g["payable"] += item["payable"]
        g["count"] += 1

    return {
        "kind": kind,
        "start": start,
        "end": end,
        "label": period_label(kind, start, end),
        "instalment": instalment,
        "items": items,
        "groups": groups,
        "system_total": sum(i["planned"] for i in items),
        "payable": sum(i["payable"] for i in items),
    }


# ── submit ───────────────────────────────────────────────────────────────────
def submit_invoice(
    principal, kind: str, anchor: date, instalment: str, entered_total, file_obj
) -> dict:
    from apps.evidence.services import _scan_upload
    from apps.evidence.validation import assert_safe_upload
    from apps.core.private_storage import (
        best_effort_delete,
        materialized_file,
        save_file,
    )

    from .finance_models import PartnerInvoice, PartnerInvoiceItem

    basis = invoice_basis(principal, kind, anchor, instalment)
    if not basis["items"]:
        raise BadRequest(
            "Nothing is invoiceable for that period — the advance may already "
            "be invoiced, or the balance opens only after IA has cleared the "
            "work."
        )
    try:
        entered = int(entered_total)
    except (TypeError, ValueError):
        raise BadRequest("Enter the period's total cost as a whole number.")
    if entered != basis["system_total"]:
        raise BadRequest(
            "The amount entered must equal the period's total planned cost "
            f"of {basis['system_total']:,} UGX — that is how the system links "
            "your invoice to the plan."
        )

    if not file_obj:
        raise BadRequest("Attach the invoice document.")
    original_name = getattr(file_obj, "name", "invoice")
    mime_type = getattr(file_obj, "content_type", "") or ""
    head = file_obj.read(512)
    file_obj.seek(0, os.SEEK_END)
    size = file_obj.tell()
    file_obj.seek(0)
    ext = assert_safe_upload(
        original_name=original_name, mime_type=mime_type, head=head, size=size
    )
    stored_name = f"{uuid.uuid4().hex}{ext}"
    save_file(INVOICE_NAMESPACE, stored_name, file_obj)
    try:
        with materialized_file(INVOICE_NAMESPACE, stored_name) as local_file:
            scan_status, threat = _scan_upload(local_file)
    except Exception:
        best_effort_delete(INVOICE_NAMESPACE, stored_name)
        raise
    if scan_status == "infected":
        best_effort_delete(INVOICE_NAMESPACE, stored_name)
        raise BadRequest(
            "This file was flagged by the malware scanner and has been "
            f"rejected ({threat}). Contact IT if you believe this is an error."
        )

    partner_id = basis["items"][0]["activity"].assigned_partner_id
    try:
        with transaction.atomic():
            invoice = PartnerInvoice.objects.create(
                partner_id=partner_id,
                invoice_type=instalment,
                period_kind=kind,
                period_start=basis["start"],
                period_end=basis["end"],
                system_total=basis["system_total"],
                entered_total=entered,
                payable_amount=basis["payable"],
                stored_name=stored_name,
                original_name=original_name,
                mime_type=mime_type,
                file_size=size,
                submitted_by=principal.user_id,
            )
            PartnerInvoiceItem.objects.bulk_create(
                [
                    PartnerInvoiceItem(
                        invoice=invoice,
                        activity=item["activity"],
                        instalment=instalment,
                        planned_amount=item["planned"],
                        payable_amount=item["payable"],
                        category=item["category"],
                    )
                    for item in basis["items"]
                ]
            )
    except Exception:
        best_effort_delete(INVOICE_NAMESPACE, stored_name)
        raise

    _notify_pls_of_invoice(invoice)
    return {
        "id": invoice.id,
        "invoiceType": invoice.invoice_type,
        "payable": invoice.payable_amount,
        "label": basis["label"],
    }


# ── the PL stage ─────────────────────────────────────────────────────────────
def _supervising_pl_user_ids(invoice) -> set[str]:
    from apps.accounts.models import StaffProfile, StaffSupervisorAssignment

    # Partner-scheduled activities carry responsible_staff_id=None — the
    # school's CCEO sits on monitored_by_staff_id (the §5 handoff contract).
    # Resolving through responsible alone left real partner invoices in NO
    # Program Lead's queue (2026-08-19 audit finding).
    staff_ids = {
        item.activity.responsible_staff_id or item.activity.monitored_by_staff_id
        for item in invoice.items.select_related("activity")
        if item.activity.responsible_staff_id or item.activity.monitored_by_staff_id
    }
    if not staff_ids:
        return set()
    profile_ids = set(staff_ids) | set(
        StaffProfile.objects.filter(user_id__in=staff_ids).values_list("id", flat=True)
    )
    return set(
        StaffSupervisorAssignment.objects.filter(
            supervisee_id__in=profile_ids
        ).values_list("supervisor__user_id", flat=True)
    )


def _pl_may_act(invoice, principal) -> bool:
    role = getattr(principal, "active_role", "")
    if role in _FINANCE_ROLES:
        return True
    if role != "Program Lead":
        return False
    return principal.user_id in _supervising_pl_user_ids(invoice)


def pl_invoice_queue(principal):
    """Invoices awaiting this PL's confirmation (country roles see all)."""
    from .finance_models import PartnerInvoice
    from apps.partners.models import Partner

    invoices = list(
        PartnerInvoice.objects.filter(status="submitted_to_pl")
        .prefetch_related("items__activity")
        .order_by("created_at")
    )
    role = getattr(principal, "active_role", "")
    if role == "Program Lead":
        invoices = [
            i for i in invoices if principal.user_id in _supervising_pl_user_ids(i)
        ]
    elif role not in _FINANCE_ROLES:
        return []
    names = dict(
        Partner.objects.filter(id__in={i.partner_id for i in invoices}).values_list(
            "id", "name"
        )
    )
    for invoice in invoices:
        invoice.partner_name = names.get(invoice.partner_id, invoice.partner_id)
        groups: dict[str, int] = {}
        for item in invoice.items.all():
            groups[item.category] = groups.get(item.category, 0) + item.planned_amount
        invoice.group_summary = groups
    return invoices


def confirm_invoice(invoice_id: str, principal) -> dict:
    """The PL confirms the invoice against the plan → to the accountant."""
    from .finance_models import PartnerInvoice

    with transaction.atomic():
        invoice = (
            PartnerInvoice.objects.select_for_update().filter(id=invoice_id).first()
        )
        if invoice is None:
            raise BadRequest("Invoice not found.")
        if invoice.status != "submitted_to_pl":
            raise BadRequest("This invoice is not awaiting PL confirmation.")
        if not _pl_may_act(invoice, principal):
            raise Forbidden("This invoice belongs to another Program Lead's team.")
        invoice.status = "confirmed_by_pl"
        invoice.pl_confirmed_by = principal.user_id
        invoice.pl_confirmed_at = timezone.now()
        invoice.save(
            update_fields=[
                "status",
                "pl_confirmed_by",
                "pl_confirmed_at",
                "updated_at",
            ]
        )
    _notify_accountants_of_invoice(invoice)
    return {"id": invoice.id, "status": invoice.status}


def return_invoice(invoice_id: str, reason: str, principal) -> dict:
    """The PL returns the invoice; its items free up for re-invoicing."""
    from .finance_models import PartnerInvoice

    reason = (reason or "").strip()
    if not reason:
        raise BadRequest("A return reason is required.")
    with transaction.atomic():
        invoice = (
            PartnerInvoice.objects.select_for_update().filter(id=invoice_id).first()
        )
        if invoice is None:
            raise BadRequest("Invoice not found.")
        if invoice.status != "submitted_to_pl":
            raise BadRequest("This invoice is not awaiting PL confirmation.")
        if not _pl_may_act(invoice, principal):
            raise Forbidden("This invoice belongs to another Program Lead's team.")
        invoice.status = "returned_by_pl"
        invoice.pl_note = reason
        invoice.save(update_fields=["status", "pl_note", "updated_at"])
        # Free the instalment for a corrected re-submission.
        invoice.items.all().delete()
    _notify_partner(
        invoice,
        "partner_invoice_returned",
        "Your invoice was returned",
        f"Your {invoice.get_invoice_type_display()} for "
        f"{period_label(invoice.period_kind, invoice.period_start, invoice.period_end)} "
        f"was returned by the Program Lead: {reason}. Correct and resubmit.",
    )
    return {"id": invoice.id, "status": invoice.status}


# ── the accountant stage ─────────────────────────────────────────────────────
def pay_invoice(invoice_id: str, data: dict, principal) -> dict:
    """Accountant pays a PL-confirmed invoice. Per-activity instalments run
    through pay_partner (all guards hold); all-or-nothing."""
    from apps.partners.models import Partner

    from .finance_models import PartnerInvoice
    from .finance_services import PartnerPaymentService

    if getattr(principal, "active_role", "") not in _FINANCE_ROLES:
        raise Forbidden("Only Finance can pay partner invoices.")

    invoice = (
        PartnerInvoice.objects.prefetch_related("items__activity")
        .filter(id=invoice_id)
        .first()
    )
    if invoice is None:
        raise BadRequest("Invoice not found.")
    if invoice.status == "paid":
        raise BadRequest("This invoice is already paid.")
    if invoice.status != "confirmed_by_pl":
        raise BadRequest(
            "The Program Lead must confirm this invoice before it is paid."
        )

    partner = Partner.objects.filter(id=invoice.partner_id).first()
    partner_name = getattr(partner, "name", None) or invoice.partner_id
    reference = (data.get("payment_reference") or "").strip()
    method = (data.get("payment_method") or "").strip() or "Bank Transfer"
    if not reference:
        raise BadRequest("Enter the payment reference for this transfer.")

    # No NetSuite ID here: those exist for STAFF accountability (money a
    # staff member received and must account for). The accountant pays the
    # partner directly — the reference is the proof (owner, 2026-08-20).
    with transaction.atomic():
        total_paid = 0
        for index, item in enumerate(invoice.items.select_related("activity"), 1):
            payment = PartnerPaymentService.pay_partner(
                item.activity,
                partner_name,
                item.payable_amount,
                method,
                reference,
                principal.user_id,
                notes=f"Invoice {invoice.id} · item {index}",
                # One "invoice paid" notice covers the whole invoice below —
                # per-activity pings on a 10-item invoice would be noise.
                notify_partner=False,
                payment_type=item.instalment,
            )
            item.payment = payment
            item.save(update_fields=["payment", "updated_at"])
            total_paid += payment.amount_paid
        invoice.status = "paid"
        invoice.save(update_fields=["status", "updated_at"])

    _notify_partner(
        invoice,
        "partner_invoice_paid",
        "Your invoice has been paid",
        f"UGX {total_paid:,} was paid against your invoice for "
        f"{period_label(invoice.period_kind, invoice.period_start, invoice.period_end)}. "
        "Check your account.",
    )
    return {"id": invoice.id, "status": invoice.status, "paid": total_paid}


def invoice_file(invoice_id: str, principal):
    """The stored invoice document — PL (in scope) and Finance roles."""
    from apps.core.private_storage import open_file

    from .finance_models import PartnerInvoice

    invoice = PartnerInvoice.objects.filter(id=invoice_id).first()
    if invoice is None:
        raise BadRequest("Invoice not found.")
    if not _pl_may_act(invoice, principal):
        raise Forbidden("You are not authorized to download this invoice.")
    return invoice, open_file(INVOICE_NAMESPACE, invoice.stored_name)


# ── notifications ────────────────────────────────────────────────────────────
def _notify_pls_of_invoice(invoice) -> None:
    try:
        from apps.notifications.services import WorkflowNotificationService

        ids = list(_supervising_pl_user_ids(invoice))
        if not ids:
            return
        WorkflowNotificationService.trigger(
            event_type="partner_invoice_submitted",
            category="finance",
            priority="high",
            title="Partner invoice awaiting your confirmation",
            body=(
                f"A partner submitted a {invoice.get_invoice_type_display()} "
                f"for {period_label(invoice.period_kind, invoice.period_start, invoice.period_end)} "
                f"(payable UGX {invoice.payable_amount:,}). Confirm it against "
                "the plan on Fund Approvals."
            ),
            context_type="PartnerInvoice",
            context_id=invoice.id,
            recipients=ids,
        )
    except Exception:  # noqa: BLE001 — notification never blocks the invoice
        pass


def _notify_accountants_of_invoice(invoice) -> None:
    try:
        from apps.accounts.models import User
        from apps.notifications.services import WorkflowNotificationService

        ids = list(
            User.objects.filter(active_role="Accountant", is_active=True).values_list(
                "id", flat=True
            )
        )
        if not ids:
            return
        WorkflowNotificationService.trigger(
            event_type="partner_invoice_confirmed",
            category="finance",
            priority="high",
            title="PL-confirmed partner invoice — ready to pay",
            body=(
                f"A {invoice.get_invoice_type_display()} for UGX "
                f"{invoice.payable_amount:,} was confirmed by the Program "
                "Lead. Download it from Partner Payments and disburse."
            ),
            context_type="PartnerInvoice",
            context_id=invoice.id,
            recipients=ids,
        )
    except Exception:  # noqa: BLE001
        pass


def _notify_partner(invoice, event_type: str, title: str, body: str) -> None:
    try:
        from apps.partners.models import Partner
        from apps.notifications.services import WorkflowNotificationService

        partner = (
            Partner.objects.filter(id=invoice.partner_id).select_related("user").first()
        )
        user_id = getattr(getattr(partner, "user", None), "id", None)
        if not user_id:
            return
        WorkflowNotificationService.trigger(
            event_type=event_type,
            category="finance",
            priority="high",
            title=title,
            body=body,
            context_type="PartnerInvoice",
            context_id=invoice.id,
            recipients=[user_id],
        )
    except Exception:  # noqa: BLE001
        pass


def partner_payment_tracker(principal) -> list[dict]:
    """The partner's payment position, per period invoice — for My Plan."""
    from .finance_models import PartnerInvoice

    try:
        partner_ids = _partner_ids_for(principal)
    except Forbidden:
        return []
    rows = []
    labels = {
        "submitted_to_pl": ("With your Program Lead", "info"),
        "confirmed_by_pl": ("PL-confirmed — with the accountant", "info"),
        "returned_by_pl": ("Returned — correct and resubmit", "danger"),
        "paid": ("Paid", "success"),
    }
    for invoice in PartnerInvoice.objects.filter(partner_id__in=partner_ids).order_by(
        "-created_at"
    )[:12]:
        stage, tone = labels.get(invoice.status, (invoice.status, "info"))
        if invoice.status == "returned_by_pl" and invoice.pl_note:
            stage = f"Returned — {invoice.pl_note}"
        rows.append(
            {
                "invoice": invoice,
                "label": period_label(
                    invoice.period_kind, invoice.period_start, invoice.period_end
                ),
                "stage": stage,
                "tone": tone,
            }
        )
    return rows
