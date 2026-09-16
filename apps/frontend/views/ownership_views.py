"""Reassigning school and district portfolio ownership (owner, 2026-09-15).

Admin and Impact Assessment only. Both actions show a preview of what they
would touch before anything is confirmed, and both leave school geography
alone — this moves who is responsible, not where a school is.
"""

from __future__ import annotations

from django.contrib import messages
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.html import escape

from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.fy import get_operational_fy
from apps.core.permissions import require_page_permission
from apps.schools import ownership_transfer as transfers
from apps.schools.models import School


def _eligible_owners(exclude_ids=()):
    """Active field officers and Programme Leads, who may hold a portfolio."""
    from apps.accounts.models import StaffProfile

    return (
        StaffProfile.objects.filter(
            deleted_at__isnull=True,
            user__is_active=True,
            user__status="active",
        )
        .filter(user__roles__overlap=list(transfers.PORTFOLIO_ROLES))
        .exclude(id__in=[i for i in exclude_ids if i])
        .select_related("user")
        .order_by("user__name")
    )


@require_page_permission("school_directory")
def school_owner_transfer_drawer(request, school_id):
    """Reassign one school's owner."""
    if not transfers.may_transfer_school(request.user):
        return HttpResponseForbidden(
            "Only an Admin or Impact Assessment can reassign school ownership."
        )
    school = get_object_or_404(
        School.objects.select_related("district"),
        deleted_at__isnull=True,
        school_id=school_id,
    )
    owner = transfers.current_owner(school)

    def drawer(error=None, posted=None, preview=None):
        return render(
            request,
            "partials/schools/owner_transfer_drawer.html",
            {
                "school": school,
                "current_owner": owner,
                "staff_options": _eligible_owners(
                    exclude_ids=[owner.id] if owner else []
                ),
                "preview": preview
                or transfers.preview_school_transfer(school).as_dict(),
                "validation_error": error,
                "posted": posted or {},
                "may_transfer_activities": transfers.may_transfer_open_activities(
                    request.user
                ),
                "today": get_operational_fy(),
                "drawer_size": "md",
            },
        )

    if request.method == "POST":
        posted = {
            "newOwnerId": request.POST.get("new_owner_id", "").strip(),
            "reason": request.POST.get("reason", "").strip(),
            "effectiveDate": request.POST.get("effective_date", "").strip(),
            "openActivityDecision": request.POST.get(
                "open_activity_decision", "keep"
            ).strip(),
        }
        if request.POST.get("confirm") != "yes":
            new_owner = transfers.resolve_staff(posted["newOwnerId"])
            return drawer(
                "Review what moves, then confirm the transfer.",
                posted,
                preview=transfers.preview_school_transfer(school, new_owner).as_dict(),
            )
        try:
            record = transfers.transfer_school_owner(school.id, posted, request.user)
        except (BadRequest, Forbidden, NotFoundError) as exc:
            return drawer(str(getattr(exc, "detail", exc)), posted)
        messages.success(
            request,
            f"{school.name} now belongs to {record.to_staff.user.name}."
            + (
                f" {len(record.transferred_activity_ids)} open activit"
                f"{'y' if len(record.transferred_activity_ids) == 1 else 'ies'} moved with it."
                if record.transferred_activity_ids
                else " Open activities kept their current owner."
            ),
        )
        target = f"/schools/{school.school_id}"
        if request.headers.get("HX-Request") == "true":
            response = HttpResponse(
                f'<script>window.location.href = "{escape(target)}";</script>'
            )
            response["HX-Trigger"] = "close-drawer"
            return response
        return redirect(target)
    return drawer()


@require_page_permission("ownership_transfers")
def ownership_transfers_view(request):
    """District portfolio transfers, the history, and targets to reconcile."""
    from apps.geography.models import District
    from apps.schools.models import DistrictPortfolioTransfer, SchoolOwnershipTransfer
    from apps.schools.ownership_models import TargetReconciliation

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        try:
            if action == "transfer_district":
                payload = {
                    "fromStaffId": request.POST.get("from_staff_id", "").strip(),
                    "newOwnerId": request.POST.get("new_owner_id", "").strip(),
                    "reason": request.POST.get("reason", "").strip(),
                    "effectiveDate": request.POST.get("effective_date", "").strip(),
                    "openActivityDecision": request.POST.get(
                        "open_activity_decision", "keep"
                    ).strip(),
                }
                if request.POST.get("confirm") != "yes":
                    raise BadRequest(
                        "Review the preview below, then tick the confirmation."
                    )
                batch = transfers.transfer_district_portfolio(
                    request.POST.get("district_id", "").strip(), payload, request.user
                )
                messages.success(
                    request,
                    f"{batch.school_count} school(s) in {batch.district.name} moved to "
                    f"{batch.to_staff.user.name}.",
                )
            elif action == "resolve_targets":
                transfers.resolve_target_reconciliation(
                    request.POST.get("transfer_id", "").strip(),
                    request.user,
                    note=request.POST.get("note", ""),
                )
                messages.success(request, "Target reconciliation recorded.")
            else:
                raise BadRequest("Choose an action.")
        except (BadRequest, Forbidden, NotFoundError) as exc:
            messages.error(request, str(getattr(exc, "detail", exc)))
        return redirect("/ownership-transfers/")

    preview = None
    preview_district = (request.GET.get("district") or "").strip()
    preview_from = (request.GET.get("from_staff") or "").strip()
    if preview_district and preview_from:
        district = District.objects.filter(id=preview_district).first()
        from_staff = transfers.resolve_staff(preview_from)
        if district and from_staff:
            preview = transfers.preview_district_transfer(
                district,
                from_staff,
                transfers.resolve_staff((request.GET.get("to_staff") or "").strip()),
            ).as_dict()

    context = {
        "districts": District.objects.select_related("region").order_by("name"),
        "staff_options": _eligible_owners(),
        "preview": preview,
        "preview_district": preview_district,
        "preview_from": preview_from,
        "batches": (
            DistrictPortfolioTransfer.objects.select_related(
                "district", "from_staff__user", "to_staff__user"
            ).order_by("-created_at")[:25]
        ),
        "transfers": (
            SchoolOwnershipTransfer.objects.select_related(
                "school", "from_staff__user", "to_staff__user"
            )
            .filter(batch__isnull=True)
            .order_by("-created_at")[:50]
        ),
        "reconciliations": (
            SchoolOwnershipTransfer.objects.select_related("school", "to_staff__user")
            .filter(target_reconciliation_status=TargetReconciliation.REQUIRED)
            .order_by("-created_at")[:50]
        ),
        "may_transfer_district": transfers.may_transfer_district(request.user),
    }
    return render(request, "pages/schools/ownership_transfers.html", context)
