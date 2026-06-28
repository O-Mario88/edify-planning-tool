"""Command-center service — recommendation-led home feed + persistent alerts."""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from apps.activities.models import Activity
from apps.core.fy import get_operational_fy
from apps.core.scoping import resolve_user_scope, school_queryset
from apps.schools.models import School

from .models import CommandCenterAlert, CommandCenterAlertDismissal


def today(principal) -> dict:
    """'What must I do next' — role-tailored action items."""
    scope = resolve_user_scope(principal)
    fy = get_operational_fy()
    
    critical_items = []
    action_items = []
    attention_items = []

    # IA: activities awaiting verification.
    if scope.can_approve:
        ia_qs = Activity.objects.filter(status="awaiting_ia_verification", deleted_at__isnull=True)
        n = ia_qs.count()
        if n:
            action_items.append({
                "id": "ia-verify",
                "priority": "critical" if n > 5 else "high",
                "title": "Awaiting IA Verification",
                "reason": f"{n} activities need your impact review and verification.",
                "href": "/queue",
                "count": n
            })

    # Accountant: payment queue.
    from apps.core.rbac import Permission
    if Permission.PAYMENT_ACT.value in scope.permissions:
        pay_qs = Activity.objects.filter(payment_status="ia_confirmed", deleted_at__isnull=True)
        n = pay_qs.count()
        if n:
            action_items.append({
                "id": "payment-clear",
                "priority": "critical" if n > 10 else "high",
                "title": "Pending Payments",
                "reason": f"{n} partner payments need to be cleared.",
                "href": "/payments",
                "count": n
            })

    # Field staff (CCEO): SSA-missing schools in scope (planning-locked).
    if scope.school_ids:
        schools = School.objects.filter(id__in=scope.school_ids, deleted_at__isnull=True).exclude(current_fy_ssa_status="done")
        n = schools.count()
        if n:
            critical_items.append({
                "id": "ssa-missing",
                "priority": "critical",
                "title": "SSA Missing",
                "reason": f"{n} schools in your scope need an SSA before you can plan visits.",
                "href": "/schools",
                "count": n
            })

    total_critical = len(critical_items)
    total_action = len(action_items)
    total_attention = len(attention_items)
    total = total_critical + total_action + total_attention
    
    groups = []
    if critical_items:
        groups.append({
            "key": "critical",
            "label": "Critical Focus",
            "items": critical_items
        })
    if action_items:
        groups.append({
            "key": "action",
            "label": "Next Actions",
            "items": action_items
        })
    if attention_items:
        groups.append({
            "key": "attention",
            "label": "Under Review",
            "items": attention_items
        })

    return {
        "live": True,
        "fy": fy,
        "summary": {
            "total": total,
            "critical": total_critical,
            "action": total_action,
            "attention": total_attention
        },
        "groups": groups
    }


def alerts(principal) -> list[dict]:
    """Open alerts not dismissed by the caller."""
    now = timezone.now()
    dismissed_ids = set(
        CommandCenterAlertDismissal.objects.filter(user_id=principal.user_id, dismissed_until__gt=now).values_list("alert_id", flat=True)
    )
    qs = CommandCenterAlert.objects.filter(status="open").exclude(id__in=dismissed_ids).order_by("-severity", "-updated_at")
    return [_serialize(a) for a in qs]


def alerts_summary(principal) -> dict:
    qs = CommandCenterAlert.objects.filter(status="open")
    return {
        "total": qs.count(),
        "urgent": qs.filter(severity="urgent").count(),
        "high": qs.filter(severity="high").count(),
    }


def dismiss(alert_id: str, data: dict, principal) -> dict:
    from apps.core.exceptions import NotFoundError

    alert = CommandCenterAlert.objects.filter(id=alert_id).first()
    if not alert:
        raise NotFoundError("Alert not found.")
    hours = int(data.get("hours", 24))
    dismissed_until = timezone.now() + timedelta(hours=hours)
    CommandCenterAlertDismissal.objects.update_or_create(
        alert=alert, user_id=principal.user_id, defaults={"dismissed_until": dismissed_until}
    )
    return {"ok": True, "alertId": alert_id, "dismissedUntil": dismissed_until.isoformat()}


def _serialize(a: CommandCenterAlert) -> dict:
    return {
        "id": a.id,
        "alertType": a.alert_type,
        "severity": a.severity,
        "title": a.title,
        "body": a.body,
        "targetRoute": a.target_route,
        "scope": a.scope,
        "status": a.status,
    }
