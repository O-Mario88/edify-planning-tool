"""Assignment — valid assignment options + direct-support capacity."""
from __future__ import annotations

from django.db.models import Count, Q

from apps.accounts.models import StaffSchoolAssignment, StaffSupportCapacity
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.schools.models import School


def get_options(query: dict, principal) -> dict:
    """Valid assignment options for a school + FY (staff the caller can assign)."""
    school_id = query.get("schoolId")
    fy = query.get("fy") or get_operational_fy()
    school = School.objects.filter(school_id=school_id).first() if school_id else None
    # Candidate staff: those in the school's district (simplified; legacy uses
    # geography + supervisor scoping).
    qs = StaffSchoolAssignment.objects.all()
    if school:
        same = StaffSchoolAssignment.objects.filter(school_id=school.id).values_list("staff_id", flat=True)
        return {
            "schoolId": school_id,
            "fy": fy,
            "currentlyAssignedStaffIds": list(same),
            "capacity": get_capacity_for(principal, {"staffId": None, "fy": fy}),
        }
    return {"fy": fy, "options": []}


def get_capacity(query: dict, principal) -> dict:
    return get_capacity_for(principal, query)


def get_capacity_for(principal, query: dict) -> dict:
    staff_id = query.get("staffId")
    fy = query.get("fy") or get_operational_fy()
    if not staff_id:
        return {"fy": fy}
    cap = StaffSupportCapacity.objects.filter(staff_id=staff_id, fy=fy, is_active=True).first()
    used = StaffSchoolAssignment.objects.filter(staff_id=staff_id).count()
    limit = cap.max_direct_schools_supported if cap else None
    return {
        "staffId": staff_id,
        "fy": fy,
        "maxDirectSchoolsSupported": limit,
        "used": used,
        "remaining": (limit - used) if limit is not None else None,
        "atCapacity": (limit is not None and used >= limit),
    }


def set_capacity(data: dict, principal) -> dict:
    staff_id = data.get("staffId")
    fy = data.get("fy") or get_operational_fy()
    max_schools = data.get("maxDirectSchoolsSupported")
    if not staff_id or max_schools is None:
        raise BadRequest("staffId and maxDirectSchoolsSupported are required.")
    cap, _ = StaffSupportCapacity.objects.update_or_create(
        staff_id=staff_id, fy=fy,
        defaults={
            "max_direct_schools_supported": max_schools,
            "set_by_user_id": principal.user_id,
            "set_by_role": principal.active_role,
            "is_active": True,
        },
    )
    return {"staffId": staff_id, "fy": fy, "maxDirectSchoolsSupported": cap.max_direct_schools_supported}


def assert_assignment_allowed(*, principal, internal_school_id=None, fy, responsible_staff_id=None,
                               assigned_partner_id=None, delivery_type="staff") -> None:
    """API-enforced assignment policy + staff support capacity. Raises Forbidden
    when the staff is over capacity for the FY."""
    if delivery_type == "partner":
        return  # Partners are NOT capped.
    if not responsible_staff_id or not internal_school_id:
        return
    # Already supports this school? Then not a NEW assignment.
    if StaffSchoolAssignment.objects.filter(staff_id=responsible_staff_id, school_id=internal_school_id).exists():
        return
    cap = StaffSupportCapacity.objects.filter(staff_id=responsible_staff_id, fy=fy, is_active=True).first()
    if cap:
        used = StaffSchoolAssignment.objects.filter(staff_id=responsible_staff_id).count()
        if used >= cap.max_direct_schools_supported:
            raise Forbidden(
                f"Staff is at direct-support capacity ({cap.max_direct_schools_supported} schools for FY{fy}). "
                "Assign a partner instead, or raise the capacity."
            )
