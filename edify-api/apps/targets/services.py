"""Targets service — CD/IA annual commitments + cumulative progress."""
from __future__ import annotations

from apps.accounts.models import StaffTargetProfile
from apps.core.exceptions import BadRequest
from apps.core.fy import get_cumulative_target_percentage, get_operational_fy
from apps.core.rbac import EdifyRole

from .models import TargetSetting


def time_period(query: dict) -> dict:
    fy = query.get("fy") or get_operational_fy()
    staff_id = query.get("staffId")
    targets = {"visitsTarget": 0, "trainingsTarget": 0}
    if staff_id:
        tp = StaffTargetProfile.objects.filter(staff_id=staff_id, fy=fy).first()
        if tp:
            targets = {"visitsTarget": tp.visits_target, "trainingsTarget": tp.trainings_target}
    return {"fy": fy, "staffId": staff_id, **targets}


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
