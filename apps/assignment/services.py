"""Assignment — valid assignment options + direct-support capacity."""

from __future__ import annotations


from apps.accounts.models import StaffSchoolAssignment, StaffSupportCapacity
from apps.core.exceptions import BadRequest
from apps.core.fy import get_operational_fy
from apps.schools.models import School


def get_options(query: dict, principal) -> dict:
    """Valid assignment options for a school + FY (staff the caller can assign)."""
    school_id = query.get("schoolId")
    fy = query.get("fy") or get_operational_fy()
    school = School.objects.filter(school_id=school_id).first() if school_id else None

    if school:
        same = StaffSchoolAssignment.objects.filter(school_id=school.id).values_list(
            "staff_id", flat=True
        )

        # 1. Capacity
        staff_id = principal.staff_profile_id
        cap = StaffSupportCapacity.objects.filter(
            staff_id=staff_id, fy=fy, is_active=True
        ).first()
        used = StaffSchoolAssignment.objects.filter(staff_id=staff_id).count()
        limit = cap.max_direct_schools_supported if cap else 10
        remaining = max(0, limit - used)
        at_limit = used >= limit
        near_limit = limit > 0 and used / limit >= 0.9 and used < limit
        capacity_dict = {
            "staffId": staff_id or "",
            "fy": fy,
            "max": limit,
            "used": used,
            "remaining": remaining,
            "atLimit": at_limit,
            "nearLimit": near_limit,
        }

        # 2. Options
        options = []
        is_direct_owner = school.account_owner_id == staff_id

        # Supervised schools & CCEOs
        is_supervised_school = False
        supervised_cceos = []
        if staff_id:
            from apps.accounts.models import StaffSupervisorAssignment

            supervised_cceo_ids = list(
                StaffSupervisorAssignment.objects.filter(
                    supervisor_id=staff_id
                ).values_list("supervisee_id", flat=True)
            )
            if school.account_owner_id in supervised_cceo_ids:
                is_supervised_school = True

            # Retrieve details of supervised CCEOs
            from apps.accounts.models import StaffProfile

            profiles = StaffProfile.objects.filter(
                id__in=supervised_cceo_ids
            ).select_related("user")
            for p in profiles:
                supervised_cceos.append(
                    {"staffId": p.id, "name": p.user.name if p.user else "Staff"}
                )

        role = principal.active_role

        # Self option
        if role == "CCEO" or (role == "Program Lead" and is_direct_owner):
            school_already_supported = StaffSchoolAssignment.objects.filter(
                staff_id=staff_id, school_id=school.id
            ).exists()
            self_enabled = school_already_supported or (remaining > 0)
            self_reason = None
            if not self_enabled:
                self_reason = f"Direct support limit reached ({limit} schools). Assign this to a partner."
            options.append(
                {
                    "type": "self",
                    "label": "Assign to Myself",
                    "enabled": self_enabled,
                    "reason": self_reason,
                }
            )

        # Staff option (PL assigns to supervised CCEO)
        if role == "Program Lead" and is_supervised_school:
            for c in supervised_cceos:
                options.append(
                    {
                        "type": "staff",
                        "label": f"Assign · {c['name']}",
                        "enabled": True,
                        "staffId": c["staffId"],
                    }
                )

        # Partner option
        partner_enabled = True
        partner_reason = None
        if role == "Program Lead" and not is_direct_owner and not is_supervised_school:
            partner_enabled = False
            partner_reason = "This school belongs to a CCEO you supervise. Assign to the responsible CCEO, or request a partner-assignment override."

        options.append(
            {
                "type": "partner",
                "label": "Assign · Partner",
                "enabled": partner_enabled,
                "reason": partner_reason,
            }
        )

        return {
            "schoolId": school_id,
            "fy": fy,
            "currentlyAssignedStaffIds": list(same),
            "capacity": capacity_dict,
            "options": options,
            "assignments": [],
        }
    return {"fy": fy, "options": [], "assignments": []}


def get_capacity(query: dict, principal) -> dict:
    return get_capacity_for(principal, query)


def get_capacity_for(principal, query: dict) -> dict:
    staff_id = query.get("staffId")
    fy = query.get("fy") or get_operational_fy()
    if not staff_id:
        return {"fy": fy}
    cap = StaffSupportCapacity.objects.filter(
        staff_id=staff_id, fy=fy, is_active=True
    ).first()
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
        staff_id=staff_id,
        fy=fy,
        defaults={
            "max_direct_schools_supported": max_schools,
            "set_by_user_id": principal.user_id,
            "set_by_role": principal.active_role,
            "is_active": True,
        },
    )
    return {
        "staffId": staff_id,
        "fy": fy,
        "maxDirectSchoolsSupported": cap.max_direct_schools_supported,
    }
