"""Canonical REG-02 scheduling-calendar policy.

The single source every scheduling surface — Planning, My Plan rescheduling,
Partner scheduling, Core School scheduling, Project scheduling, Daily Visit
Batches, Route feasibility, Budget Amendment reschedule, calendar views,
APIs, HTMX endpoints, background jobs — must call before committing a date.
One surface must never block a date another surface allows.

Rule:
- Sunday is always blocked.
- Saturday is never blocked by this policy (existing org policy permits it).
- A public holiday blocks — PublicHoliday and CalendarBlock(PUBLIC_HOLIDAY)
  are two independent sources; both are checked here.
- An organizational blackout date (CalendarBlock BLACKOUT_DATE) blocks.
- Approved leave blocks scheduling for the affected staff member; pending
  leave and high weekly workload only warn.
- STAFF_CONFERENCE / REGIONAL_EVENT / ORG_EVENT / CUSTOM_BLOCK calendar
  events are role/geography-scoped bonus blockers, evaluated only when a
  user is known.

``user`` is optional throughout: callers that only know the *date* (no
resolvable staff identity yet, e.g. a route-feasibility preview before
anyone is assigned) still get the always-on Sunday/holiday/blackout gate;
the leave and role-scoped checks are skipped when no user is given.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import (
    CalendarBlock,
    Leave,
    PublicHoliday,
    StaffGeographyAssignment,
    StaffProfile,
    User,
)


def resolve_scheduling_user(staff_or_user_id: str | None):
    """Resolve the app's compatible staff/user identity to its User row.

    Operational records now use the StaffProfile id as their canonical staff
    identity, while a small amount of legacy data (and Admin users without a
    profile) still carries a User id. Every scheduling check must understand
    both shapes; otherwise a staff member on leave could be scheduled simply
    because the lookup only attempted the legacy User-id representation.
    """
    if not staff_or_user_id:
        return None
    return User.objects.filter(
        Q(id=staff_or_user_id) | Q(staff_profile__id=staff_or_user_id)
    ).first()


def canonical_staff_identity(staff_or_user_id: str | None) -> str | None:
    """Prefer a StaffProfile id, retaining a valid legacy User id as fallback."""
    user = resolve_scheduling_user(staff_or_user_id)
    return user.staff_profile_id if user and user.staff_profile_id else staff_or_user_id


def activity_owner_ids(staff_or_user) -> list[str]:
    """Return every persisted Activity owner identity for a staff member.

    Activities historically stored a User id in responsible_staff_id. New
    activities use the StaffProfile id so a person has one staff identity
    throughout planning, assignments, and reporting. Availability must see
    both representations until historical Activity data is normalized.
    """
    if isinstance(staff_or_user, StaffProfile):
        ids = [staff_or_user.id, staff_or_user.user_id]
    else:
        profile_id = (
            StaffProfile.objects.filter(user_id=staff_or_user.id)
            .values_list("id", flat=True)
            .first()
        )
        ids = [staff_or_user.id, profile_id]
    return list(dict.fromkeys(value for value in ids if value))


def scheduled_datetime_window(
    start_date: date, end_date: date
) -> tuple[datetime, datetime]:
    """Return an aware, half-open scheduled-date range for inclusive dates."""
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(start_date, datetime.min.time()), tz)
    end = timezone.make_aware(
        datetime.combine(end_date + timedelta(days=1), datetime.min.time()), tz
    )
    return start, end


def _coerce_date(check_date):
    if isinstance(check_date, datetime):
        return check_date.date()
    if isinstance(check_date, date):
        return check_date
    try:
        return date.fromisoformat(str(check_date)[:10])
    except (TypeError, ValueError):
        return None


class SchedulingPolicyService:
    """The REG-02 gate. Call check(user, check_date) before committing any
    Activity/slot/route date. ``user`` may be None when no staff identity is
    known yet — the always-on Sunday/holiday/blackout gate still applies."""

    @staticmethod
    def check(user, check_date) -> dict:
        d = _coerce_date(check_date)
        if d is None:
            return {
                "status": "available",
                "reasons": [],
                "blockers": [],
                "warnings": [],
            }

        blockers: list[str] = []
        warnings: list[str] = []

        if d.weekday() == 6:
            blockers.append("Scheduling on Sundays is blocked.")

        public_holiday = PublicHoliday.objects.filter(date=d).first()
        if public_holiday:
            blockers.append(f"This date is a public holiday: {public_holiday.name}.")

        sp = StaffProfile.objects.filter(user=user).first() if user else None

        h_blocks = CalendarBlock.objects.filter(
            is_active=True, start_date__lte=d, end_date__gte=d
        )
        for b in h_blocks:
            if b.block_type == "PUBLIC_HOLIDAY":
                blockers.append(f"This date is a public holiday: {b.title}.")
            elif b.block_type == "BLACKOUT_DATE":
                blockers.append(
                    f"This date is an organizational blackout date: {b.title}."
                )
            elif not user:
                continue
            elif b.block_type == "STAFF_CONFERENCE":
                role_restricted = False
                if b.applies_to_roles and user.active_role not in b.applies_to_roles:
                    role_restricted = True
                if not b.applies_to_all_roles and not role_restricted:
                    pass
                else:
                    blockers.append(
                        f"Staff Conference Week: {b.title} blocks scheduling."
                    )
            elif b.block_type in ("REGIONAL_EVENT", "ORG_EVENT", "CUSTOM_BLOCK"):
                geo_blocked = True
                if b.region:
                    if (
                        sp
                        and not StaffGeographyAssignment.objects.filter(
                            staff=sp, region=b.region
                        ).exists()
                    ):
                        geo_blocked = False
                if geo_blocked:
                    blockers.append(f"Blocked by calendar event: {b.title}.")

        if user and sp:
            d_str = d.isoformat()
            if Leave.objects.filter(
                staff=sp, status="approved", start_date__lte=d_str, end_date__gte=d_str
            ).exists():
                blockers.append(f"{user.name} is on approved leave on this date.")
            elif Leave.objects.filter(
                staff=sp, status="pending", start_date__lte=d_str, end_date__gte=d_str
            ).exists():
                warnings.append(
                    f"{user.name} has a pending leave request on this date."
                )

        if user:
            from apps.activities.models import Activity

            start_of_week = d - timedelta(days=d.weekday())
            end_of_week = start_of_week + timedelta(days=6)
            scheduled_start, scheduled_end = scheduled_datetime_window(
                start_of_week, end_of_week
            )
            week_count = (
                Activity.objects.filter(
                    responsible_staff_id__in=activity_owner_ids(user),
                    scheduled_date__gte=scheduled_start,
                    scheduled_date__lt=scheduled_end,
                )
                .exclude(status__in=["cancelled", "completed"])
                .count()
            )
            if week_count >= 5:
                warnings.append(
                    f"High workload warning: {user.name} has {week_count} activities scheduled this week."
                )

        status = "available"
        if blockers:
            status = "blocked"
        elif warnings:
            status = "warning"

        return {
            "status": status,
            "reasons": blockers + warnings,
            "blockers": blockers,
            "warnings": warnings,
        }

    @staticmethod
    def check_date(check_date, *, user=None) -> dict:
        """Same as check(), with the date-first argument order that reads
        naturally for callers which may not have a resolvable user yet
        (route feasibility, calendar-only previews)."""
        return SchedulingPolicyService.check(user, check_date)
