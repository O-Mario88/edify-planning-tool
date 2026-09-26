"""Verify & Confirm, and Return, for Partner work on Partner Monitoring.

Owner, 2026-09-26: "Staff (PL and CCEO, IA) action buttons should have Verify
and Confirm, Return in case they have not uploaded the evidence or uploaded
the wrong file as evidence and like I said before, they should return with a
reason."

Partner work left the staff My Plan for Partner Monitoring, so this is where
the people who answer for it decide it. Who may is unchanged and lives in one
place, ``RolePermissionService.can_confirm_partner_activity``: Impact
Assessment, or the staff member named as the activity's monitor (a CCEO, a
Programme Lead or a Project Coordinator). The page itself stays free of
inline forms (apps/planning/test_partner_monitoring.py); each decision is a
drawer, and each drawer's POST is checked again by its service:
``ia_confirm`` for Verify & Confirm, ``return_partner_work`` for Return.
"""

from __future__ import annotations

from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from apps.activities.models import Activity
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.permissions import RolePermissionService, require_page_permission

#: The two reasons the owner named, then the reasons every other return offers
#: (apps.activities.return_notes), so a Partner reads one vocabulary whoever
#: sent the work back.
PARTNER_RETURN_REASONS = (
    "Evidence not uploaded",
    "Wrong file uploaded as evidence",
)


def _return_reasons() -> tuple[str, ...]:
    from apps.activities.return_notes import COMMON_REASONS

    return PARTNER_RETURN_REASONS + tuple(
        r for r in COMMON_REASONS if r not in PARTNER_RETURN_REASONS
    )


def _reviewable(request, activity_id: str):
    """(activity, refusal) — the Partner activity this reader may decide."""
    activity = (
        Activity.objects.filter(
            id=(activity_id or "").strip(),
            deleted_at__isnull=True,
            delivery_type="partner",
        )
        .select_related("school", "cluster")
        .first()
    )
    if activity is None:
        return None, "This Partner activity no longer exists."
    if not RolePermissionService.can_confirm_partner_activity(request.user, activity):
        return None, (
            "Only Impact Assessment or this activity's monitoring staff member "
            "may verify or return this Partner work."
        )
    if activity.status != "awaiting_ia_verification":
        return None, "This work is not waiting for verification."
    return activity, ""


def _partner_name(activity) -> str:
    from apps.partners.models import Partner

    partner = Partner.objects.filter(id=activity.assigned_partner_id).first()
    return partner.name if partner else "the Partner"


def _refusal(request, template: str, message: str) -> HttpResponse:
    return render(
        request, template, {"refusal": message, "drawer_size": "sm"}, status=403
    )


def _decided(message: str) -> HttpResponse:
    response = HttpResponse(f'<p class="pill pill-success" role="status">{message}</p>')
    # The row, the Partner's pages and the To-Do read the decision on their
    # next render; refresh this page so the row moves now.
    response["HX-Trigger"] = "close-drawer"
    response["HX-Refresh"] = "true"
    return response


@require_page_permission("partner_oversight")
def partner_verify_drawer_view(request):
    """What the Partner submitted, and the Salesforce ID that confirms it."""
    from apps.evidence.models import EvidenceRecord
    from apps.evidence.requirements import checklist

    template = "partials/oversight/partner_verify_drawer.html"
    activity, refusal = _reviewable(request, request.GET.get("activity_id"))
    if activity is None:
        return _refusal(request, template, refusal)
    evidence = list(
        EvidenceRecord.objects.filter(
            activity_id=activity.id, quarantined=False
        ).order_by("-created_at")
    )
    return render(
        request,
        template,
        {
            "a": activity,
            "partner_name": _partner_name(activity),
            "evidence": evidence,
            "evidence_checklist": checklist(activity),
            "drawer_size": "md",
        },
    )


@require_POST
@require_page_permission("partner_oversight")
def partner_verify_submit_view(request):
    from apps.activities.services import ia_confirm
    from apps.core.htmx_errors import error_fragment

    activity, refusal = _reviewable(request, request.POST.get("activity_id"))
    if activity is None:
        return error_fragment(Forbidden(refusal), status=403)
    salesforce_id = (
        request.POST.get("salesforce_id") or activity.salesforce_activity_id or ""
    ).strip()
    if not salesforce_id:
        return error_fragment(
            BadRequest("Enter the Salesforce Activity ID to confirm this work."),
            status=400,
        )
    try:
        ia_confirm(
            activity.id,
            {
                "salesforceId": salesforce_id,
                "verificationNote": (
                    request.POST.get("verification_note") or ""
                ).strip(),
            },
            request.user,
        )
    except Exception as exc:  # noqa: BLE001 — the service's refusal, as it said it
        return error_fragment(exc, status=400)
    return _decided("Verified and confirmed.")


@require_page_permission("partner_oversight")
def partner_return_drawer_view(request):
    """Send the submission back, with the reason the Partner will read."""
    template = "partials/oversight/partner_return_drawer.html"
    activity, refusal = _reviewable(request, request.GET.get("activity_id"))
    if activity is None:
        return _refusal(request, template, refusal)
    return render(
        request,
        template,
        {
            "a": activity,
            "partner_name": _partner_name(activity),
            "reasons": _return_reasons(),
            "drawer_size": "md",
        },
    )


@require_POST
@require_page_permission("partner_oversight")
def partner_return_submit_view(request):
    from apps.activities.services import return_partner_work
    from apps.core.htmx_errors import error_fragment

    activity, refusal = _reviewable(request, request.POST.get("activity_id"))
    if activity is None:
        return error_fragment(Forbidden(refusal), status=403)
    allowed = set(_return_reasons())
    try:
        return_partner_work(
            activity.id,
            {
                "reasons": [r for r in request.POST.getlist("reasons") if r in allowed],
                "comment": request.POST.get("comment", ""),
            },
            request.user,
        )
    except Exception as exc:  # noqa: BLE001 — the service's refusal, as it said it
        return error_fragment(exc, status=400)
    return _decided("Returned to the Partner.")
