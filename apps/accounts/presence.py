"""Who is online, and how many people signed in — for the Admin dashboard.

Owner, 2026-09-12: "The admin should also be able to see who is online. The
number of logins per day, per week."

Two facts, kept where they are cheap to read:

* ``User.last_seen_at`` — written by ``SlidingSessionMiddleware`` at most once
  per minute per active person (it already throttles the session touch on
  exactly that interval), so "online now" is one indexed query.
* ``LoginEvent`` — one row per successful sign-in, from both the password and
  the MFA path in ``auth_views``.

"Online" means seen within the last ten minutes. A person who closes the tab
drops off the list within that window; nothing here needs a logout.
"""

from __future__ import annotations

from datetime import timedelta

import logging

from django.utils import timezone

logger = logging.getLogger(__name__)

ONLINE_WINDOW = timedelta(minutes=10)


def client_address(request) -> str | None:
    """The caller's address when it is one. A proxy header or REMOTE_ADDR that
    is not a valid IP is recorded as unknown, never raised: the first sign-in
    behind a malformed X-Forwarded-For would otherwise have failed on the
    address column's validation (found by the change-password flow's test)."""
    import ipaddress

    forwarded = (request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip()
    candidate = forwarded or (request.META.get("REMOTE_ADDR") or "").strip()
    if not candidate:
        return None
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def record_login(request, user) -> None:
    """Record a successful sign-in. Never lets a bookkeeping failure break the
    sign-in it records."""
    from django.db import DatabaseError

    from .models import LoginEvent, User

    now = timezone.now()
    try:
        LoginEvent.objects.create(
            user=user,
            at=now,
            role=getattr(user, "active_role", "") or "",
            ip=client_address(request),
            user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:256],
        )
        User.objects.filter(pk=user.pk).update(last_seen_at=now)
    except (DatabaseError, ValueError):  # pragma: no cover - defensive
        logger.exception(
            "presence: sign-in was not recorded for %s", getattr(user, "pk", None)
        )


def touch_presence(user) -> None:
    """Mark the person as seen now. One UPDATE; the caller throttles. Inside a
    request whose transaction has already failed, it does nothing."""
    from django.db import DatabaseError

    from .models import User

    if not getattr(user, "is_authenticated", False):
        return
    try:
        User.objects.filter(pk=user.pk).update(last_seen_at=timezone.now())
    except DatabaseError:
        return


def presence_summary(*, now=None) -> dict:
    from django.db.models import Count
    from django.db.models.functions import TruncDate

    from .models import LoginEvent, User

    now = now or timezone.now()
    local_now = timezone.localtime(now)
    today = local_now.date()
    week_start = today - timedelta(days=today.weekday())  # Monday
    since_online = now - ONLINE_WINDOW

    online = list(
        User.objects.filter(
            last_seen_at__gte=since_online, is_active=True, deleted_at__isnull=True
        )
        .order_by("-last_seen_at")
        .values("id", "name", "email", "active_role", "last_seen_at")[:50]
    )

    events = LoginEvent.objects.filter(user__deleted_at__isnull=True)
    day_start = timezone.make_aware(
        timezone.datetime.combine(today, timezone.datetime.min.time()),
        timezone.get_current_timezone(),
    )
    week_start_dt = day_start - timedelta(days=today.weekday())
    logins_today = events.filter(at__gte=day_start).count()
    logins_this_week = events.filter(at__gte=week_start_dt).count()
    logins_last_7_days = events.filter(at__gte=now - timedelta(days=7)).count()

    # Fourteen days of daily counts, every day present even when zero.
    since_days = day_start - timedelta(days=13)
    per_day = {
        row["day"]: row["n"]
        for row in events.filter(at__gte=since_days)
        .annotate(day=TruncDate("at"))
        .values("day")
        .annotate(n=Count("id"))
    }
    daily = [
        {
            "date": today - timedelta(days=offset),
            "count": per_day.get(today - timedelta(days=offset), 0),
        }
        for offset in range(13, -1, -1)
    ]
    # Eight weeks of weekly counts, Monday to Sunday.
    weekly = []
    for back in range(7, -1, -1):
        start = week_start - timedelta(weeks=back)
        start_dt = week_start_dt - timedelta(weeks=back)
        weekly.append(
            {
                "week_start": start,
                "count": events.filter(
                    at__gte=start_dt, at__lt=start_dt + timedelta(weeks=1)
                ).count(),
            }
        )
    return {
        "online": online,
        "online_count": len(online),
        "window_minutes": int(ONLINE_WINDOW.total_seconds() // 60),
        "logins_today": logins_today,
        "logins_this_week": logins_this_week,
        "logins_last_7_days": logins_last_7_days,
        "daily": daily,
        "weekly": weekly,
        "peak_day": max(daily, key=lambda d: d["count"])["count"] if daily else 0,
    }
