"""HR service — staff roster (PII-gated) + leave management."""

from __future__ import annotations

from django.utils import timezone

from apps.accounts.models import Leave, StaffProfile
from apps.core.rbac import EdifyRole
from apps.core.scoping import resolve_user_scope


def roster(principal) -> dict:
    """Staff directory. Conforms to BeRoster contract."""
    from apps.schools.models import School
    from apps.geography.models import District

    scope = resolve_user_scope(principal)
    qs = StaffProfile.objects.filter(deleted_at__isnull=True).select_related("user")
    if (
        principal.active_role == EdifyRole.COUNTRY_PROGRAM_LEAD.value
        and scope.supervised_staff_ids
    ):
        qs = qs.filter(id__in=scope.supervised_staff_ids)
    strip_email = principal.active_role not in (
        EdifyRole.ADMIN.value,
        EdifyRole.HUMAN_RESOURCES.value,
        EdifyRole.COUNTRY_DIRECTOR.value,
        EdifyRole.COUNTRY_PROGRAM_LEAD.value,
    )
    staff = []
    total_count = qs.count()
    active_count = 0
    pending_count = 0

    district_ids = [sp.primary_district_id for sp in qs if sp.primary_district_id]
    district_map = {d.id: d.name for d in District.objects.filter(id__in=district_ids)}

    for sp in qs:
        email = None if strip_email else sp.user.email
        schools_count = School.objects.filter(
            account_owner_id=sp.id, deleted_at__isnull=True
        ).count()
        supervisees_count = sp.supervisee_links.count()
        primary_district_name = (
            district_map.get(sp.primary_district_id) if sp.primary_district_id else None
        )

        if sp.onboarding_state == "active":
            active_count += 1
        elif sp.onboarding_state == "pending":
            pending_count += 1

        role_label = sp.user.roles[0] if sp.user.roles else (sp.title or "")

        staff.append(
            {
                "staffProfileId": sp.id,
                "name": sp.user.name,
                "email": email or "",
                "role": role_label,
                "onboardingState": sp.onboarding_state,
                "active": sp.onboarding_state == "active",
                "primaryDistrict": primary_district_name,
                "schools": schools_count,
                "supervisees": supervisees_count,
            }
        )

    return {
        "counts": {
            "total": total_count,
            "active": active_count,
            "pending": pending_count,
        },
        "staff": staff,
    }


def list_leave(principal, query: dict) -> list[dict]:
    qs = Leave.objects.all().order_by("-created_at")
    if query.get("status"):
        qs = qs.filter(status=query["status"])
    return [_serialize_leave(leave) for leave in qs]


def approved_leave_calendar(query: dict) -> list[dict]:
    qs = Leave.objects.filter(status="approved")
    return [_serialize_leave(leave) for leave in qs]


def request_leave(data: dict, principal) -> dict:
    if not principal.staff_profile_id:
        from apps.core.exceptions import BadRequest

        raise BadRequest("No staff profile linked to your account.")
    days = int(data.get("days", 1))
    leave = Leave.objects.create(
        staff_id=principal.staff_profile_id,
        type=data.get("type", "annual"),
        start_date=data.get("startDate"),
        end_date=data.get("endDate"),
        days=days,
        reason=data.get("reason"),
    )
    return _serialize_leave(leave)


def review_leave(leave_id: str, decision: str, principal) -> dict:
    from apps.core.exceptions import BadRequest, NotFoundError
    from apps.hr.leave_services import LeaveApprovalService

    leave = Leave.objects.filter(id=leave_id).first()
    if not leave:
        raise NotFoundError("Leave request not found.")
    if decision not in ("approved", "rejected"):
        raise BadRequest("decision must be approved or rejected.")
    # Hierarchy + self-approval authorization check — mirrors the main UI
    # path (LeaveApprovalService.approve_request/reject_request) so this
    # parallel /api/hr/leave endpoint enforces the same rule instead of
    # letting any LEAVE_PLANNER_VIEW holder (e.g. HR staff) self-approve or
    # approve/reject leave outside their supervisory hierarchy.
    if not LeaveApprovalService.is_authorized_approver(principal, leave):
        action = "approve" if decision == "approved" else "reject"
        raise BadRequest(f"You are not authorized to {action} this leave request.")
    leave.status = decision
    leave.reviewed_by_user_id = principal.user_id
    leave.reviewed_at = timezone.now()
    leave.save(
        update_fields=["status", "reviewed_by_user_id", "reviewed_at", "updated_at"]
    )
    return _serialize_leave(leave)


def _serialize_leave(leave: Leave) -> dict:
    return {
        "id": leave.id,
        "staffId": leave.staff_id,
        "type": leave.type,
        "startDate": leave.start_date,
        "endDate": leave.end_date,
        "days": leave.days,
        "status": leave.status,
        "reason": leave.reason,
        "reviewedByUserId": leave.reviewed_by_user_id,
        "reviewedAt": leave.reviewed_at.isoformat() if leave.reviewed_at else None,
    }
