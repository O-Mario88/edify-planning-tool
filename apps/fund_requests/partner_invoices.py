"""Partner invoice flow — period invoices through the PL to the accountant.

The platform writes the invoice (owner, 2026-10-08: scheduled and completed
visits "should be able to compute the cost into an invoice to Edify which goes
to the program lead for that region (The PL own schools, schools of CCEOs
under him)"). For a chosen week, month or quarter it lists the partner's
activities with their costs, grouped by category (School Visits, Training
Facilitation Fee), and totals them; the payable is derived (50% on the advance
invoice for scheduled work; the balance, only for work completed with its
evidence and cleared by IA, on the clearance invoice). The partner types no
total and need attach nothing.

Work that is already completed with its evidence is payable in full (owner,
2026-10-08: "if the activity is completed and evidence uploaded, payable
become full amount"). It is not offered at 50% any more, and its invoice no
longer waits for an advance to have been paid first: it pays the whole cost,
or what is left of it where the 50% did go out. "Completed" here is what the
balance has always required and what the accountant's payment step enforces
(finance_services.FinanceBlockedReasonService): verified by IA, with evidence
on file.

One invoice is raised for each Programme Lead whose schools the period's work
is at (apps.fund_requests.invoice_routing), so a Lead confirms their own
schools and nobody else's.

Routing: partner sends → the Programme Lead it is addressed to confirms it
against the plan (or returns it) → the accountant pays. The money still runs
per activity through PartnerPaymentService.pay_partner, so every instalment
guard (exact 50%, balance clamp, IA blockers, idempotency) keeps holding.
"""

from __future__ import annotations

import calendar
import os
import uuid
from datetime import date, timedelta

from django.db import transaction
from django.db.models import Q
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
    """What the partner is paid for: all of partner-delivered work; the
    facilitation fee of a partner-facilitated training."""
    from apps.activities.facilitation import partner_planned_total

    return partner_planned_total(activity)


def _paid_by_type(activity) -> dict[str, int]:
    from .finance_models import PartnerPayment

    totals: dict[str, int] = {}
    for p in PartnerPayment.objects.filter(activity=activity):
        totals[p.payment_type] = totals.get(p.payment_type, 0) + p.amount_paid
    return totals


def _category_of(activity) -> str:
    from apps.activities.facilitation import is_facilitated, is_meeting
    from apps.core.activity_types import TRAINING_TYPES

    if activity.activity_type in TRAINING_TYPES or "training" in activity.activity_type:
        return "Training Facilitation Fee"
    if (
        is_meeting(activity.activity_type)
        and is_facilitated(activity)
        and activity.delivery_type != "partner"
    ):
        # A cluster meeting the partner organised and facilitated (owner,
        # 2026-10-02): the fee is what it invoices.
        return "Meeting Facilitation Fee"
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
            Q(activity__assigned_partner_id__in=partner_ids)
            | Q(activity__facilitating_partner_id__in=partner_ids),
            instalment=instalment,
        ).values_list("activity_id", flat=True)
    )

    # The partner's own delivered work, and the staff-run group trainings it
    # facilitates, whose fee it invoices here (owner, 2026-09-26).
    activities = (
        Activity.objects.filter(
            Q(assigned_partner_id__in=partner_ids, delivery_type="partner")
            | Q(facilitating_partner_id__in=partner_ids, delivery_type="staff"),
            deleted_at__isnull=True,
            scheduled_date__date__range=(start, end),
        )
        .exclude(status__in=NON_FUNDABLE_ACTIVITY_STATUSES)
        .select_related("school", "school__district", "cluster", "cluster__district")
        .order_by("scheduled_date")
    )

    activities = list(activities)
    done = _completed_with_evidence(activities)
    # A 50% that is on an invoice and not yet paid: the rest is invoiced once
    # that invoice is settled, or the two would ask for 150% between them.
    advance_in_flight = set(
        PartnerInvoiceItem.objects.filter(
            activity_id__in=[a.id for a in activities],
            instalment="advance",
            payment__isnull=True,
        ).values_list("activity_id", flat=True)
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
            # Completed with its evidence: invoiced in full, not at 50%.
            if activity.id in done:
                continue
            payable = planned // 2
        else:
            # Payable in full once the work is completed with its evidence
            # (and verified): the whole cost, less a 50% already paid.
            if activity.id not in done:
                continue
            if activity.id in advance_in_flight:
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
                **_line_facts(activity),
            }
        )

    # One invoice for each Programme Lead whose schools the work is at.
    from .invoice_routing import split_by_lead

    by_lead = [
        {
            "lead": lead,
            "items": rows,
            "system_total": sum(i["planned"] for i in rows),
            "payable": sum(i["payable"] for i in rows),
        }
        for lead, rows in split_by_lead(items)
    ]

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
        "by_lead": by_lead,
        "system_total": sum(i["planned"] for i in items),
        "payable": sum(i["payable"] for i in items),
    }


def _completed_with_evidence(activities) -> set[str]:
    """The ids of the activities that are completed with their evidence: IA
    has verified them and at least one evidence file is on record. One query
    for the whole period."""
    from apps.evidence.models import EvidenceRecord

    cleared = [a.id for a in activities if a.status in _CLEARED_STATUSES]
    if not cleared:
        return set()
    return set(
        EvidenceRecord.objects.filter(activity_id__in=cleared, quarantined=False)
        .values_list("activity_id", flat=True)
        .distinct()
    )


def _line_facts(activity) -> dict:
    """What an invoice says of one activity besides its money: the day, the
    place, the work and who delivered it."""
    from apps.core.clock import local_day

    place = activity.school or activity.cluster
    return {
        "date": local_day(activity.scheduled_date) if activity.scheduled_date else None,
        "place": getattr(place, "name", "") or "",
        "district": getattr(getattr(place, "district", None), "name", "") or "",
        "work": activity.activity_name_snapshot or activity.get_activity_type_display(),
        "delivered_by": activity.delivery_contact_name or "",
    }


# ── submit ───────────────────────────────────────────────────────────────────
def submit_invoice(
    principal,
    kind: str,
    anchor: date,
    instalment: str,
    entered_total=None,
    file_obj=None,
) -> dict:
    """Raise the period's invoice: one for each Programme Lead whose schools
    the work is at. The totals are the plan's. ``entered_total`` is optional
    and, when given, must be the plan's total; ``file_obj`` is the partner's
    own document, when it issues one."""
    from apps.activities.facilitation import paid_partner_id

    from .finance_models import PartnerInvoice, PartnerInvoiceItem

    basis = invoice_basis(principal, kind, anchor, instalment)
    if not basis["items"]:
        raise BadRequest(
            "Nothing is invoiceable for that period — the advance may already "
            "be invoiced, or the work is not yet completed with its evidence "
            "and verified by IA."
        )
    if entered_total not in (None, ""):
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

    document = _store_document(file_obj) if file_obj else None
    partner_id = paid_partner_id(basis["items"][0]["activity"])
    invoices = []
    try:
        with transaction.atomic():
            for group in basis["by_lead"]:
                lead = group["lead"]
                invoice = PartnerInvoice.objects.create(
                    partner_id=partner_id,
                    invoice_type=instalment,
                    period_kind=kind,
                    period_start=basis["start"],
                    period_end=basis["end"],
                    system_total=group["system_total"],
                    # Kept equal: the platform wrote the total from the plan.
                    entered_total=group["system_total"],
                    payable_amount=group["payable"],
                    submitted_by=principal.user_id,
                    program_lead_staff_id=lead.staff_id if lead else None,
                    **(document or {}),
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
                        for item in group["items"]
                    ]
                )
                invoice.lead_name = lead.name if lead else ""
                invoices.append(invoice)
    except Exception:
        if document:
            from apps.core.private_storage import best_effort_delete

            best_effort_delete(INVOICE_NAMESPACE, document["stored_name"])
        raise

    for invoice in invoices:
        _notify_pls_of_invoice(invoice)
    return {
        # The first, for a caller that raised one invoice and reads one.
        "id": invoices[0].id,
        "invoices": [
            {"id": i.id, "lead": i.lead_name, "payable": i.payable_amount}
            for i in invoices
        ],
        "invoiceType": instalment,
        "payable": basis["payable"],
        "label": basis["label"],
    }


def _store_document(file_obj) -> dict:
    """Check, scan and keep the partner's own invoice document; the fields
    the invoice records of it."""
    from apps.core.private_storage import (
        best_effort_delete,
        materialized_file,
        save_file,
    )
    from apps.evidence.services import _scan_upload
    from apps.evidence.validation import assert_safe_upload

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
    return {
        "stored_name": stored_name,
        "original_name": original_name,
        "mime_type": mime_type,
        "file_size": size,
    }


# ── the PL stage ─────────────────────────────────────────────────────────────
def _supervising_pl_user_ids(invoice) -> set[str]:
    """The Programme Lead(s) who confirm this invoice.

    One, for an invoice addressed to its Lead. An invoice raised before
    2026-10-08 names none and may cover two teams: every Lead of its schools
    reads it, by the same rule that now addresses a new one — which also
    finds the Lead of a school they hold themselves, where the old rule
    (the supervisor of the officer on the activity) found nobody.
    """
    from apps.accounts.models import StaffProfile

    if invoice.program_lead_staff_id:
        return set(
            StaffProfile.objects.filter(id=invoice.program_lead_staff_id).values_list(
                "user_id", flat=True
            )
        )
    from .invoice_routing import LeadResolver

    activities = [item.activity for item in invoice.items.select_related("activity")]
    resolver = LeadResolver(activities)
    leads = {resolver.lead_of(activity) for activity in activities}
    return {lead.user_id for lead in leads if lead is not None}


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
        invoice.reference = invoice_reference(invoice)
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
    from .finance_services import PartnerPaymentService, _assert_may_pay

    # `payment.act`, not `_FINANCE_ROLES`. That tuple also admits
    # CountryDirector and Admin, which is right for READING the invoice queue
    # (below) but hands the money-moving half back to roles the 2026-08 audit's
    # AUD-004 deliberately excluded — Admin holds no `payment.act` at all
    # (FIN-03). pay_partner re-asserts it per instalment.
    _assert_may_pay(principal)

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
    if not invoice.stored_name:
        raise BadRequest(
            "This invoice was written by the platform and has no attached "
            "document. Open the invoice to read or print it."
        )
    return invoice, open_file(INVOICE_NAMESPACE, invoice.stored_name)


_STAGES = {
    "submitted_to_pl": ("With the Programme Lead", "info"),
    "confirmed_by_pl": ("Confirmed · with the accountant", "info"),
    "returned_by_pl": ("Returned", "danger"),
    "paid": ("Paid", "success"),
}


def invoice_reference(invoice) -> str:
    """The number an invoice is quoted by: the month it was raised and the
    end of its id."""
    return f"INV-{invoice.created_at:%Y%m}-{invoice.id[-6:].upper()}"


def invoice_document(invoice_id: str, principal) -> dict:
    """The invoice as it is read and printed: who it is from and to, and each
    activity on it with its day, who delivered it, the evidence filed for it,
    its cost and what this instalment pays.

    Open to the organisation it belongs to, the Programme Lead it is
    addressed to, and Finance.
    """
    from django.db.models import Count

    from apps.accounts.models import StaffProfile
    from apps.core.scoping import resolve_partner_ids
    from apps.evidence.models import EvidenceRecord
    from apps.partners.models import Partner
    from apps.partners.profile_lists import stage_of

    from .finance_models import PartnerInvoice

    invoice = PartnerInvoice.objects.filter(id=invoice_id).first()
    if invoice is None:
        raise BadRequest("Invoice not found.")
    own = invoice.partner_id in set(resolve_partner_ids(principal) or [])
    if not own and not _pl_may_act(invoice, principal):
        raise Forbidden("This invoice is not yours to open.")

    items = list(
        invoice.items.select_related(
            "activity",
            "activity__school",
            "activity__school__district",
            "activity__cluster",
            "activity__cluster__district",
        ).order_by("activity__scheduled_date", "id")
    )
    evidence = dict(
        EvidenceRecord.objects.filter(
            activity_id__in=[item.activity_id for item in items], quarantined=False
        )
        .values("activity_id")
        .annotate(n=Count("id"))
        .values_list("activity_id", "n")
    )
    lines = []
    for item in items:
        activity = item.activity
        status, tone = stage_of(activity)
        lines.append(
            {
                "activity_id": activity.id,
                "school_id": activity.school_id or "",
                "category": item.category,
                "status": status,
                "tone": tone,
                "evidence": evidence.get(activity.id, 0),
                "planned": item.planned_amount,
                "payable": item.payable_amount,
                **_line_facts(activity),
            }
        )

    if invoice.program_lead_staff_id:
        lead_name = (
            StaffProfile.objects.filter(id=invoice.program_lead_staff_id)
            .values_list("user__name", flat=True)
            .first()
            or ""
        )
    else:
        from .invoice_routing import LeadResolver

        activities = [item.activity for item in items]
        resolver = LeadResolver(activities)
        lead_name = ", ".join(
            sorted(
                {
                    lead.name
                    for lead in (resolver.lead_of(a) for a in activities)
                    if lead is not None
                }
            )
        )

    partner = Partner.all_objects.filter(id=invoice.partner_id).first()
    role = getattr(principal, "active_role", "")
    if own:
        back = ("/my-plan", "My Plan")
        file_href = ""
    elif role == "Program Lead":
        back = ("/fund-approvals", "Fund Approvals")
        file_href = f"/fund-approvals/invoices/{invoice.id}/download"
    else:
        back = ("/accounts/partner-payments/", "Partner Payments")
        file_href = f"/accounts/partner-invoices/{invoice.id}/download"
    status_label, status_tone = _STAGES.get(invoice.status, (invoice.status, "info"))
    return {
        "invoice": invoice,
        "reference": invoice_reference(invoice),
        "partner": partner,
        "partner_name": getattr(partner, "name", "") or invoice.partner_id,
        "lead_name": lead_name,
        "period_label": period_label(
            invoice.period_kind, invoice.period_start, invoice.period_end
        ),
        "lines": lines,
        "status_label": status_label,
        "status_tone": status_tone,
        "has_file": bool(invoice.stored_name) and bool(file_href),
        "file_href": file_href,
        "back_href": back[0],
        "back_label": back[1],
    }


# ── notifications ────────────────────────────────────────────────────────────
def _notify_pls_of_invoice(invoice) -> None:
    try:
        from apps.notifications.services import WorkflowNotificationService

        ids = list(_supervising_pl_user_ids(invoice))
        if not ids:
            # No Lead holds these schools: the Country Director confirms it
            # in the Lead's place (they read every invoice, _FINANCE_ROLES).
            from apps.accounts.models import User

            ids = list(
                User.objects.filter(
                    active_role="CountryDirector", is_active=True
                ).values_list("id", flat=True)
            )
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
                "reference": invoice_reference(invoice),
                "label": period_label(
                    invoice.period_kind, invoice.period_start, invoice.period_end
                ),
                "stage": stage,
                "tone": tone,
            }
        )
    return rows
