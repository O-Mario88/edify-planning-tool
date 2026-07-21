"""HR service — staff roster (PII-gated) + leave management."""

from __future__ import annotations


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


def _leave_country_scope(principal, qs):
    """Confine a leave listing to the caller's own country.

    This returned every leave record in the deployment — `reason` included,
    which is free text where an employee explains a medical or family
    circumstance. HR is a country function, not a global one.
    """
    if getattr(principal, "active_role", "") == "Admin":
        return qs
    sp = getattr(principal, "staff_profile", None)
    country = getattr(sp, "country", None)
    if not country:
        return qs.none()
    return qs.filter(staff__country=country)


def list_leave(principal, query: dict) -> list[dict]:
    qs = Leave.objects.all().order_by("-created_at")
    if query.get("status"):
        qs = qs.filter(status=query["status"])
    qs = _leave_country_scope(principal, qs)
    # No `reason` in a list response — it is detail, and detail belongs on the
    # authorized single-record path.
    return [_serialize_leave(leave, include_reason=False) for leave in qs]


def approved_leave_calendar(principal, query: dict) -> list[dict]:
    qs = _leave_country_scope(principal, Leave.objects.filter(status="approved"))
    return [_serialize_leave(leave, include_reason=False) for leave in qs]


def request_leave(data: dict, principal, attachment_file=None) -> dict:
    from apps.core.exceptions import BadRequest
    from apps.hr.leave_services import LeaveRequestService

    if not principal.staff_profile_id:
        raise BadRequest("No staff profile linked to your account.")
    # Delegate to the canonical service — mirrors the review_leave fix below
    # and the main UI path (apps/frontend/views/leave_views.py) — so this
    # parallel /api/hr/leave endpoint enforces the same leave-balance
    # sufficiency check, WorkingDayCalculator days_charged/hours_covered
    # computation, LeaveTypePolicy.requires_attachment check, and coverage
    # bookkeeping instead of writing an unvalidated Leave row directly.
    # days_charged is computed server-side from start/end dates + policy; a
    # client-supplied "days" is intentionally not trusted.
    mapped = {
        "type": data.get("type") or data.get("leaveType"),
        "start_date": data.get("startDate") or data.get("start_date"),
        "end_date": data.get("endDate") or data.get("end_date"),
        "reason": data.get("reason"),
        "covering_staff": data.get("coveringStaff") or data.get("covering_staff"),
        "coverage_notes": data.get("coverageNotes") or data.get("coverage_notes"),
        "emergency_contact": data.get("emergencyContact")
        or data.get("emergency_contact"),
        "handover_notes": data.get("handoverNotes") or data.get("handover_notes"),
        "urgent_activities": data.get("urgentActivities")
        or data.get("urgent_activities"),
    }
    leave = LeaveRequestService.request_leave(
        principal.staff_profile, mapped, attachment_file
    )
    return _serialize_leave(leave)


def review_leave(leave_id: str, decision: str, principal) -> dict:
    from apps.core.exceptions import BadRequest
    from apps.hr.leave_services import LeaveApprovalService

    if decision not in ("approved", "rejected"):
        raise BadRequest("decision must be approved or rejected.")

    # Delegate the whole transition, do not re-implement it. This path used to
    # borrow only the authorization predicate and then write the row itself,
    # skipping five things the canonical service does: recalculating the leave
    # balance, creating the TemporaryCoverageAssignment, revoking any
    # overlapping prior coverage, and the two audit rows. A leave approved here
    # consumed no balance at all — the same 21 days could be spent twice — and
    # left no audit entry for an approval decision.
    #
    # `request_leave` above was fixed to delegate; this sibling was left behind.
    if decision == "approved":
        leave = LeaveApprovalService.approve_request(leave_id, principal)
    else:
        leave = LeaveApprovalService.reject_request(leave_id, principal)
    return _serialize_leave(leave)


def _serialize_leave(leave: Leave, include_reason: bool = True) -> dict:
    out = {
        "id": leave.id,
        "staffId": leave.staff_id,
        "type": leave.type,
        "startDate": leave.start_date,
        "endDate": leave.end_date,
        "days": leave.days,
        "status": leave.status,
        "reviewedByUserId": leave.reviewed_by_user_id,
        "reviewedAt": leave.reviewed_at.isoformat() if leave.reviewed_at else None,
    }
    if include_reason:
        out["reason"] = leave.reason
    return out
