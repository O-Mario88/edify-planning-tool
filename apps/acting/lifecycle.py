"""Recording an appointment's life: the reminder, the start and the end.

**Nothing here grants or removes access.** An appointment is active on its
dates (``ActingAssignment.state``), read at the moment of each request, so an
acting leader has the seat from 00:00 on the first of the month and loses it
at the end of the last day whether this sweep runs or not. The sweep writes
down that it happened: it puts the transition in the audit log, tells the
people concerned, and stamps the row so each is said once.

Run hourly by the scheduler (``acting_lifecycle`` in apps.realtime.registry),
and safe to run at any time: every step is keyed on a stamp it sets itself.
"""

from __future__ import annotations

import datetime

from django.db import transaction
from django.utils import timezone

from . import services
from .models import ActingAssignment, today

#: How many days ahead of the first day the appointee is reminded.
REMINDER_DAYS = 3


def sweep(on: datetime.date | None = None) -> int:
    """Record every transition that is due. Returns how many it recorded."""
    on = on or today()
    return _remind(on) + _activate(on) + _expire(on)


def _locked(assignment_id, **still):
    return (
        ActingAssignment.objects.select_for_update()
        .filter(id=assignment_id, cancelled_at__isnull=True, **still)
        .select_related("appointee", "appointed_by", "seat__user")
        .first()
    )


def _remind(on) -> int:
    due = ActingAssignment.objects.upcoming(on).filter(
        start_date__lte=on + datetime.timedelta(days=REMINDER_DAYS),
        reminded_at__isnull=True,
    )
    done = 0
    for assignment_id in list(due.values_list("id", flat=True)):
        with transaction.atomic():
            row = _locked(assignment_id, reminded_at__isnull=True)
            if row is None:
                continue
            row.reminded_at = timezone.now()
            row.save(update_fields=["reminded_at", "updated_at"])
            services._notify(
                "acting.reminder",
                row,
                f"Your {row.short_label} assignment begins "
                f"{row.start_date.strftime('%B')} {row.start_date.day}.",
                (
                    f"You are {row.label} for {row.period_label} "
                    f"({row.effective_label}), appointed by "
                    f"{row.appointed_by.name}. Scope: {services.scope_label(row)}. "
                    "It starts by itself on the first day."
                ),
                [row.appointee],
            )
            done += 1
    return done


def _activate(on) -> int:
    due = ActingAssignment.objects.standing().filter(
        start_date__lte=on, end_date__gte=on, activated_at__isnull=True
    )
    done = 0
    for assignment_id in list(due.values_list("id", flat=True)):
        with transaction.atomic():
            row = _locked(assignment_id, activated_at__isnull=True)
            if row is None:
                continue
            row.activated_at = timezone.now()
            row.save(update_fields=["activated_at", "updated_at"])
            _audit("acting_assignment.activated", row)
            services._notify(
                "acting.started",
                row,
                f"You are {row.short_label} for {row.period_label}.",
                (
                    f"Your {row.label} appointment is in effect until "
                    f"{row.end_date.strftime('%B')} {row.end_date.day}. Scope: "
                    f"{services.scope_label(row)}. Switch between "
                    f"{row.short_label} and your {row.appointee_role} role from "
                    "the account menu."
                ),
                [row.appointee],
            )
            done += 1
    return done


def _expire(on) -> int:
    due = ActingAssignment.objects.standing().filter(
        end_date__lt=on, expired_at__isnull=True
    )
    done = 0
    for assignment_id in list(due.values_list("id", flat=True)):
        with transaction.atomic():
            row = _locked(assignment_id, expired_at__isnull=True)
            if row is None:
                continue
            row.expired_at = timezone.now()
            row.save(update_fields=["expired_at", "updated_at"])
            services.sync_hint(row.appointee_id)
            _audit("acting_assignment.expired", row)
            services._notify(
                "acting.ended",
                row,
                f"Your {row.short_label} appointment for {row.period_label} has ended.",
                (
                    f"Your {row.label} access ended on "
                    f"{row.end_date.strftime('%B')} {row.end_date.day}. You "
                    f"continue as {row.appointee_role}."
                ),
                [row.appointee],
            )
            done += 1
    return done


def _audit(action: str, row: ActingAssignment) -> None:
    from apps.audit.services import log as audit_log

    audit_log(
        action=action,
        subject_kind="ActingAssignment",
        subject_id=row.id,
        payload=services._describe(row),
    )


__all__ = ["REMINDER_DAYS", "sweep"]
