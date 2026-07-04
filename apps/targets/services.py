"""Targets service — CD/IA annual commitments + cumulative progress."""
from __future__ import annotations

from apps.core.exceptions import BadRequest
from apps.core.fy import get_operational_fy

from .models import TargetSetting


def time_period(query: dict, principal=None) -> dict:
    from apps.core.fy import get_operational_fy
    from apps.accounts.models import StaffProfile, StaffTargetProfile
    from apps.schools.models import School
    from apps.activities.models import Activity

    fy = query.get("fy") or get_operational_fy()
    staff_id = query.get("staffId")
    if not staff_id and principal:
        staff_profile = getattr(principal, "staff_profile", None)
        if staff_profile:
            staff_id = staff_profile.id

    if not staff_id:
        return {
            "live": False,
            "fy": fy,
            "staffId": "",
            "totalPortfolio": 0,
            "annual": {"staffTarget": 0, "partnerTarget": 0, "total": 0},
            "rows": [],
            "dataQuality": []
        }

    sp = StaffProfile.objects.filter(id=staff_id).first()
    if not sp:
        return {
            "live": False,
            "fy": fy,
            "staffId": staff_id,
            "totalPortfolio": 0,
            "annual": {"staffTarget": 0, "partnerTarget": 0, "total": 0},
            "rows": [],
            "dataQuality": [f"Staff profile not found for ID {staff_id}."]
        }

    total_portfolio = School.objects.filter(account_owner_id=sp.id, deleted_at__isnull=True).count()

    tp = StaffTargetProfile.objects.filter(staff=sp, fy=fy).first()
    staff_target = (tp.visits_target + tp.trainings_target) if tp else 0
    partner_target = 0
    total_target = staff_target + partner_target

    staff_achieved_q1 = Activity.objects.filter(deleted_at__isnull=True, fy=fy, responsible_staff_id=sp.id, delivery_type="staff", status__in=["ia_verified", "closed", "accountant_confirmed"], quarter="Q1").count()
    staff_achieved_q2 = Activity.objects.filter(deleted_at__isnull=True, fy=fy, responsible_staff_id=sp.id, delivery_type="staff", status__in=["ia_verified", "closed", "accountant_confirmed"], quarter="Q2").count()
    staff_achieved_q3 = Activity.objects.filter(deleted_at__isnull=True, fy=fy, responsible_staff_id=sp.id, delivery_type="staff", status__in=["ia_verified", "closed", "accountant_confirmed"], quarter="Q3").count()
    staff_achieved_q4 = Activity.objects.filter(deleted_at__isnull=True, fy=fy, responsible_staff_id=sp.id, delivery_type="staff", status__in=["ia_verified", "closed", "accountant_confirmed"], quarter="Q4").count()

    partner_achieved_q1 = Activity.objects.filter(deleted_at__isnull=True, fy=fy, assigned_partner_id=sp.id, delivery_type="partner", status__in=["ia_verified", "closed", "accountant_confirmed"], quarter="Q1").count()
    partner_achieved_q2 = Activity.objects.filter(deleted_at__isnull=True, fy=fy, assigned_partner_id=sp.id, delivery_type="partner", status__in=["ia_verified", "closed", "accountant_confirmed"], quarter="Q2").count()
    partner_achieved_q3 = Activity.objects.filter(deleted_at__isnull=True, fy=fy, assigned_partner_id=sp.id, delivery_type="partner", status__in=["ia_verified", "closed", "accountant_confirmed"], quarter="Q3").count()
    partner_achieved_q4 = Activity.objects.filter(deleted_at__isnull=True, fy=fy, assigned_partner_id=sp.id, delivery_type="partner", status__in=["ia_verified", "closed", "accountant_confirmed"], quarter="Q4").count()

    rows = []
    periods_data = [
        ("Q1", 0.25, staff_achieved_q1, partner_achieved_q1),
        ("Mid-Year", 0.50, staff_achieved_q1 + staff_achieved_q2, partner_achieved_q1 + partner_achieved_q2),
        ("Q3", 0.75, staff_achieved_q1 + staff_achieved_q2 + staff_achieved_q3, partner_achieved_q1 + partner_achieved_q2 + partner_achieved_q3),
        ("End of Year", 1.00, staff_achieved_q1 + staff_achieved_q2 + staff_achieved_q3 + staff_achieved_q4, partner_achieved_q1 + partner_achieved_q2 + partner_achieved_q3 + partner_achieved_q4),
    ]

    for period, fraction, staff_ach, partner_ach in periods_data:
        st_tar = round(staff_target * fraction)
        pt_tar = round(partner_target * fraction)
        tot_tar = st_tar + pt_tar
        
        tot_ach = staff_ach + partner_ach
        
        st_pct = round(staff_ach / st_tar * 100) if st_tar else (100 if staff_ach else None)
        pt_pct = round(partner_ach / pt_tar * 100) if pt_tar else (100 if partner_ach else None)
        tot_pct = round(tot_ach / tot_tar * 100) if tot_tar else (100 if tot_ach else None)
        
        gap = max(0, tot_tar - tot_ach)
        
        if tot_pct is None:
            status = "No Target"
        elif tot_pct >= 100:
            status = "Ahead"
        elif tot_pct >= 90:
            status = "On Track"
        elif tot_pct >= 75:
            status = "Slightly Behind"
        elif tot_pct >= 50:
            status = "Behind"
        else:
            status = "Critical"

        rows.append({
            "period": period,
            "staff": {"target": st_tar, "achieved": staff_ach, "pct": st_pct},
            "partner": {"target": pt_tar, "achieved": partner_ach, "pct": pt_pct},
            "total": {"target": tot_tar, "achieved": tot_ach, "pct": tot_pct},
            "gap": gap,
            "status": status,
        })

    data_quality = []
    if staff_target == 0:
        data_quality.append("No annual target configured for this staff member.")
    if total_portfolio == 0:
        data_quality.append("No schools assigned to this staff member's portfolio.")

    return {
        "live": True,
        "fy": fy,
        "staffId": staff_id,
        "totalPortfolio": total_portfolio,
        "annual": {"staffTarget": staff_target, "partnerTarget": partner_target, "total": total_target},
        "rows": rows,
        "dataQuality": data_quality
    }


def summary(query: dict) -> dict:
    fy = query.get("fy") or get_operational_fy()
    settings = TargetSetting.objects.filter(fy=fy, is_active=True)
    return {
        "fy": fy,
        "targetCount": settings.count(),
        "byType": {t: settings.filter(target_type=t).count() for t in {s.target_type for s in settings}},
    }


def list_targets(query: dict) -> list[dict]:
    fy = query.get("fy") or get_operational_fy()
    qs = TargetSetting.objects.filter(fy=fy, is_active=True)
    if query.get("targetType"):
        qs = qs.filter(target_type=query["targetType"])
    if query.get("scopeType"):
        qs = qs.filter(scope_type=query["scopeType"])
    return [_serialize(t) for t in qs]


def set_target(data: dict, principal) -> dict:
    target_type = data.get("targetType")
    scope_type = data.get("scopeType")
    if not target_type or not scope_type:
        raise BadRequest("targetType and scopeType are required.")
    from django.utils import timezone

    # Deactivate prior active setting for the same type+scope+fy.
    TargetSetting.objects.filter(
        fy=data.get("fy") or get_operational_fy(),
        target_type=target_type,
        scope_type=scope_type,
        scope_id=data.get("scopeId"),
        is_active=True,
    ).update(is_active=False, effective_to=timezone.now())
    t = TargetSetting.objects.create(
        fy=data.get("fy") or get_operational_fy(),
        target_type=target_type,
        scope_type=scope_type,
        scope_id=data.get("scopeId"),
        target_value=data.get("targetValue"),
        target_unit=data.get("targetUnit", "percentage"),
        target_percentage=data.get("targetPercentage"),
        quarter_distribution=data.get("quarterDistribution"),
        set_by_user_id=principal.user_id,
        set_by_role=principal.active_role,
        notes=data.get("notes"),
    )
    return _serialize(t)


def _serialize(t: TargetSetting) -> dict:
    return {
        "id": t.id,
        "fy": t.fy,
        "targetType": t.target_type,
        "scopeType": t.scope_type,
        "scopeId": t.scope_id,
        "targetValue": t.target_value,
        "targetUnit": t.target_unit,
        "targetPercentage": t.target_percentage,
        "isActive": t.is_active,
    }
