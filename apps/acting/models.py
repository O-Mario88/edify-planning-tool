"""An acting appointment: one person, one acting role, one seat, one month.

The record says who was given whose seat, by whom and for which calendar
month. It changes nothing about the people it names: ``User.roles``,
``User.active_role`` and the reporting line (``StaffSupervisorAssignment``)
are never written by an appointment.

**The state is the dates.** ``TemporaryCoverageAssignment`` beside it keeps a
``status`` column that nothing ever moves to "expired", so every grant ever
made reads "active" for good. Here there is no stored status to go stale: an
appointment is Upcoming before its first day, Active from 00:00 on that day
to the end of its last (both in the platform's timezone), Expired after, and
Cancelled when ``cancelled_at`` is set. Access is read from that at the
moment of the request, so it starts and stops on the month boundary with
nobody doing anything. ``activated_at`` and ``expired_at`` are when the
lifecycle sweep recorded each transition in the audit log, never a switch.

Rows are never deleted: an ended or cancelled appointment is the record of
who held delegated authority and when.
"""

from __future__ import annotations

import datetime

from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from apps.core.models import CuidField, TimeStampedModel
from apps.core.rbac import EdifyRole

from .policy import ACTING_ROLES

UPCOMING = "upcoming"
ACTIVE = "active"
EXPIRED = "expired"
CANCELLED = "cancelled"

STATE_LABELS = {
    UPCOMING: "Upcoming",
    ACTIVE: "Active",
    EXPIRED: "Expired",
    CANCELLED: "Cancelled",
}


class LastDayOfMonth(models.Func):
    """The last day of the month a date falls in, as a date."""

    template = "(%(expressions)s + INTERVAL '1 month' - INTERVAL '1 day')::date"
    output_field = models.DateField()
    arity = 1


def today() -> datetime.date:
    """The calendar day in the platform's timezone (Africa/Nairobi)."""
    return timezone.localdate()


class ActingAssignmentQuerySet(models.QuerySet):
    def standing(self):
        """Not cancelled, whatever its dates."""
        return self.filter(cancelled_at__isnull=True)

    def active(self, on: datetime.date | None = None):
        on = on or today()
        return self.standing().filter(start_date__lte=on, end_date__gte=on)

    def upcoming(self, on: datetime.date | None = None):
        on = on or today()
        return self.standing().filter(start_date__gt=on)

    def history(self, on: datetime.date | None = None):
        """Ended or cancelled."""
        on = on or today()
        return self.filter(Q(cancelled_at__isnull=False) | Q(end_date__lt=on))


class ActingAssignment(TimeStampedModel):
    id = CuidField()
    #: The policy entry (``apps.acting.policy.ACTING_ROLES``).
    role_key = models.CharField(
        max_length=32,
        choices=[(key, entry.label) for key, entry in ACTING_ROLES.items()],
    )
    #: The role whose operational capabilities are delegated.
    acting_role = models.CharField(
        max_length=64, choices=[(r.value, r.value) for r in EdifyRole]
    )
    appointee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="acting_assignments",
    )
    #: The appointee's permanent role when appointed. A record of the day,
    #: never read to decide access.
    appointee_role = models.CharField(max_length=64)
    appointed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="acting_appointments_made",
    )
    appointed_by_role = models.CharField(max_length=64)
    scope_type = models.CharField(max_length=32)
    #: The substantive leader whose seat is delegated. The scope is read from
    #: this seat when a request is made, so a person who joins or leaves the
    #: team mid-month joins or leaves the acting leader's reach with them.
    seat = models.ForeignKey(
        "accounts.StaffProfile",
        on_delete=models.PROTECT,
        related_name="acting_assignments",
    )
    country = models.CharField(max_length=64, blank=True, default="")
    start_date = models.DateField()
    end_date = models.DateField()

    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    cancel_reason = models.CharField(max_length=512, blank=True, default="")
    # When the lifecycle sweep recorded each transition (see the docstring).
    reminded_at = models.DateTimeField(null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    expired_at = models.DateTimeField(null=True, blank=True)

    #: Whether the appointee is working in the acting capacity or in their
    #: own role. Theirs to switch from the account menu; it survives signing
    #: out, and it is only ever read while the appointment is active.
    in_capacity = models.BooleanField(default=True)

    #: What was granted, as it stood when the appointment was made: the
    #: policy entry's delegated and withheld sets and the people in the seat.
    #: For the auditor; access is always resolved from the live policy.
    grant_snapshot = models.JSONField(default=dict, blank=True)
    #: The earlier state of an appointment that was changed before it began.
    revisions = models.JSONField(default=list, blank=True)

    objects = ActingAssignmentQuerySet.as_manager()

    class Meta:
        db_table = "acting_assignment"
        ordering = ["-start_date", "-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_date__gte=F("start_date")),
                name="acting_window_ordered",
            ),
            # A whole calendar month, held by the database: it begins on the
            # first and ends on the last day of that same month.
            models.CheckConstraint(
                condition=Q(start_date__day=1),
                name="acting_window_starts_on_first",
            ),
            # `LastDayOfMonth` keeps the arithmetic in dates. The ORM's own
            # day extraction converts through the session's time zone, and
            # midnight on the first in Nairobi is 21:00 the day before in
            # UTC: the same rule built from ExtractDay read 31 for
            # 1 November and refused every month.
            models.CheckConstraint(
                condition=Q(end_date=LastDayOfMonth(F("start_date"))),
                name="acting_window_is_one_month",
            ),
            models.CheckConstraint(
                condition=~Q(appointee=F("appointed_by")),
                name="acting_never_self_appointed",
            ),
            # One acting leader per seat and month. Periods are whole months,
            # so equal first days are the only way two can overlap and no
            # range exclusion (and no btree_gist extension) is needed.
            models.UniqueConstraint(
                fields=["seat", "role_key", "start_date"],
                condition=Q(cancelled_at__isnull=True),
                name="uniq_standing_acting_per_seat_month",
            ),
            # One acting appointment per person and month, of any kind: an
            # Acting PL is not also an Acting CD, nor acting for two teams.
            models.UniqueConstraint(
                fields=["appointee", "start_date"],
                condition=Q(cancelled_at__isnull=True),
                name="uniq_standing_acting_per_person_month",
            ),
        ]
        indexes = [
            models.Index(
                fields=["country", "start_date"], name="acting_country_month_idx"
            ),
            models.Index(fields=["end_date"], name="acting_end_date_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.label} · {self.period_label}"

    # ── What it is ──────────────────────────────────────────────────────────
    @property
    def policy(self):
        return ACTING_ROLES[self.role_key]

    @property
    def label(self) -> str:
        return self.policy.label

    @property
    def short_label(self) -> str:
        return self.policy.short_label

    @property
    def period_label(self) -> str:
        return self.start_date.strftime("%B %Y")

    @property
    def effective_label(self) -> str:
        """ "October 1 – October 31, 2026"."""
        return (
            f"{self.start_date.strftime('%B')} {self.start_date.day} – "
            f"{self.end_date.strftime('%B')} {self.end_date.day}, {self.end_date.year}"
        )

    @property
    def short_period_label(self) -> str:
        """ "1 – 31 Oct 2026", for a table column."""
        return (
            f"{self.start_date.day} – {self.end_date.day} "
            f"{self.start_date.strftime('%b %Y')}"
        )

    # ── Where it is in its life ─────────────────────────────────────────────
    def state(self, on: datetime.date | None = None) -> str:
        if self.cancelled_at is not None:
            return CANCELLED
        on = on or today()
        if on < self.start_date:
            return UPCOMING
        if on > self.end_date:
            return EXPIRED
        return ACTIVE

    @property
    def state_label(self) -> str:
        return STATE_LABELS[self.state()]

    def is_active(self, on: datetime.date | None = None) -> bool:
        return self.state(on) == ACTIVE

    def is_upcoming(self, on: datetime.date | None = None) -> bool:
        return self.state(on) == UPCOMING


__all__ = [
    "ACTIVE",
    "CANCELLED",
    "EXPIRED",
    "STATE_LABELS",
    "UPCOMING",
    "ActingAssignment",
    "today",
]
