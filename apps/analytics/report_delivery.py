"""Validated persistence and tracked in-app delivery for analytics digests."""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.audit.services import log as audit_log
from apps.messaging.services import workflow_message

from .analytics_dashboard_service import AnalyticsDashboardService
from .models import AnalyticsReportSchedule

ALLOWED_CATEGORIES = {"targets", "training", "reach", "ssa"}
CARD_CATEGORY = {
    "Overall Target Achievement": "targets",
    "Teachers Trained": "training",
    "School Leaders Trained": "training",
    "Students Impacted": "reach",
    "Schools Impacted": "reach",
    "Districts Covered": "reach",
    "Clusters Covered": "reach",
    "Total Activities Completed": "reach",
    "SSA Average": "ssa",
}


def send_analytics_snapshot(*, user, categories: list[str], now=None):
    """Create a private analytics Message and Notification immediately."""
    generated_at = now or timezone.now()
    dashboard = AnalyticsDashboardService.get_analytics_data(user, {})
    cards = [
        card
        for card in dashboard.get("kpi_strip_items", [])
        if CARD_CATEGORY.get(card.get("label")) in categories
    ]
    generated = timezone.localtime(generated_at).strftime("%Y-%m-%d %H:%M %Z")
    metric_lines = "\n".join(
        f"• {card.get('label', '')}: {card.get('value', '')}"
        + (f" — {card.get('helper', '')}" if card.get("helper") else "")
        for card in cards
    )
    thread = workflow_message(
        context_type="system",
        context_id=f"analytics-{user.id}",
        subject="Analytics snapshot",
        body=(
            f"Your analytics snapshot is ready.\n"
            f"Generated: {generated}\n\n"
            f"{metric_lines or 'No metrics matched the selected categories.'}\n\n"
            "Open Analytics to review the live dashboard or download the current CSV."
        ),
        recipient_ids=[str(user.id)],
        category="Strategic report",
        priority="normal",
    )
    if thread is None:
        raise RuntimeError("In-app message delivery was not confirmed")
    return thread


def next_run_at(frequency: str, *, now=None):
    """Return the next Kampala wall-clock delivery time."""
    local_now = timezone.localtime(now or timezone.now())
    if frequency == "daily":
        candidate = local_now.replace(hour=17, minute=0, second=0, microsecond=0)
        if candidate <= local_now:
            candidate += timedelta(days=1)
    elif frequency == "weekly":
        days_until_friday = (4 - local_now.weekday()) % 7
        candidate = (local_now + timedelta(days=days_until_friday)).replace(
            hour=16, minute=0, second=0, microsecond=0
        )
        if candidate <= local_now:
            candidate += timedelta(days=7)
    else:
        candidate = local_now.replace(
            day=1,
            hour=8,
            minute=0,
            second=0,
            microsecond=0,
        )
        if candidate <= local_now:
            year = local_now.year + (1 if local_now.month == 12 else 0)
            month = 1 if local_now.month == 12 else local_now.month + 1
            candidate = candidate.replace(year=year, month=month)
    return candidate


def deliver_due_schedules(*, limit: int = 50) -> int:
    """Deliver due schedules with row locks so parallel workers cannot double-send."""
    delivered = 0
    now = timezone.now()
    with transaction.atomic():
        schedules = list(
            AnalyticsReportSchedule.objects.select_for_update(skip_locked=True)
            .select_related("user")
            .filter(is_active=True, next_run_at__lte=now)
            .order_by("next_run_at")[:limit]
        )
        # Claim each row with a bounded retry timestamp, then release database
        # locks before any network I/O. A crashed worker naturally retries.
        AnalyticsReportSchedule.objects.filter(
            id__in=[schedule.id for schedule in schedules]
        ).update(last_attempt_at=now, next_run_at=now + timedelta(minutes=30))

    for schedule in schedules:
        schedule.last_attempt_at = now
        schedule.next_run_at = now + timedelta(minutes=30)
        try:
            send_analytics_snapshot(
                user=schedule.user,
                categories=schedule.categories,
                now=now,
            )
            schedule.last_delivered_at = now
            schedule.last_error = ""
            schedule.next_run_at = next_run_at(schedule.frequency, now=now)
            delivered += 1
            success = True
            reason = "Scheduled analytics digest delivered to in-app inbox"
        except Exception as exc:  # noqa: BLE001 - record failure for retry/ops
            schedule.last_error = str(exc)[:512]
            success = False
            reason = schedule.last_error
        schedule.save(
            update_fields=[
                "last_attempt_at",
                "last_delivered_at",
                "last_error",
                "next_run_at",
                "updated_at",
            ]
        )
        audit_log(
            action="analytics_report_delivery",
            subject_kind="AnalyticsReportSchedule",
            subject_id=str(schedule.id),
            actor_id=str(schedule.user_id),
            actor_role=schedule.user.active_role,
            success=success,
            reason=reason,
            payload={"recipient_user_id": str(schedule.user_id), "channel": "in_app"},
        )
    return delivered


__all__ = [
    "ALLOWED_CATEGORIES",
    "CARD_CATEGORY",
    "deliver_due_schedules",
    "next_run_at",
    "send_analytics_snapshot",
]
