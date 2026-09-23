"""Who is online, and how many people signed in — for the Admin dashboard.

Owner, 2026-09-12: "The admin should also be able to see who is online. The
number of logins per day, per week."

Two facts, kept where they are cheap to read:

* ``User.last_seen_at`` — written by ``SlidingSessionMiddleware`` at most once
  per minute per active person (it already throttles the session touch on
  exactly that interval), so "online now" is one indexed query. The same
  touch records ``online_since`` (the start of the sitting), the page
  (``last_seen_path``) and the last write or drawer request on it
  (``last_seen_action``); writes touch on every request so an action between
  two beats is not lost.
* ``LoginEvent`` — one row per successful sign-in, from both the password and
  the MFA path in ``auth_views``.

"Online" means seen within the last ten minutes. A person who closes the tab
drops off the list within that window; nothing here needs a logout.

Owner, 2026-09-15: "Who's Online should show a green online beeping light and
those that are offline should show me the grey offline icon." And, later the
same day: "The admin and CD should know who logged in, who is online, how long
they have been online, what they were working on… group all the CCEO by their
PL." So the panel is a table of everyone with an account — status light,
name, how long they have been on, what they were doing, which part of the
system — with the CCEOs folded under their Program Lead and everyone else
under their role.

Owner, 2026-09-22: "Give PLs access to Who is online but restrict to their team
members only." A Programme Lead reads the same table, over their own reporting
line and nobody else's — themselves and the people they supervise. Every count
in it is of that team, not of the country, so the panel a Lead reads is about
the people they can actually ask. The scope is a set of user ids
(``team_user_ids``) handed to ``presence_summary``; without one it is still the
whole country, which is what the Admin and the Country Director read.
"""

from __future__ import annotations

from datetime import timedelta

import logging

from django.utils import timezone

logger = logging.getLogger(__name__)

ONLINE_WINDOW = timedelta(minutes=10)
# The panel is a glance, not a directory: the most recently seen people first.
PRESENCE_LIST_LIMIT = 50


def client_address(request) -> str | None:
    """The caller's address when it is one (apps.core.client_ip). An address
    that is not a valid IP is recorded as unknown, never raised: the first
    sign-in behind a malformed proxy header would otherwise have failed on the
    address column's validation (found by the change-password flow's test)."""
    from apps.core.client_ip import client_ip

    return client_ip(request)


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
        User.objects.filter(pk=user.pk).update(
            last_seen_at=now,
            online_since=now,
            last_seen_path="/dashboard",
            last_seen_action="",
        )
    except (DatabaseError, ValueError):  # pragma: no cover - defensive
        logger.exception(
            "presence: sign-in was not recorded for %s", getattr(user, "pk", None)
        )


# Requests that say nothing about what a person is doing.
_UNTRACKED_PREFIXES = (
    "/api/",
    "/static/",
    "/media/",
    "/health",
    "/favicon",
    "/realtime",
)
_READ_METHODS = ("GET", "HEAD", "OPTIONS")


def request_footprint(request) -> tuple[str, str] | None:
    """(page path, action) for a request, or None when it is not a person
    working on a page. The page is the document the person is on — for an
    htmx request that is HX-Current-URL, not the fragment fetched. The action
    is the request itself when it writes or opens a drawer; empty for a plain
    page load."""
    if request is None:
        return None
    path = request.path or "/"
    if path.startswith(_UNTRACKED_PREFIXES):
        return None
    htmx = request.headers.get("HX-Request") == "true"
    current = request.headers.get("HX-Current-URL") or ""
    from .presence_labels import page_path

    page = page_path(current) if htmx and current else path
    method = request.method or "GET"
    if method in _READ_METHODS and not htmx:
        action = ""
    else:
        action = f"{method} {path}"
    return page[:255], action[:255]


def touch_presence(user, request=None) -> None:
    """Mark the person as seen now, on this page, doing this. One UPDATE; the
    caller throttles reads to once a minute and sends every write. A touch
    after a gap longer than the online window starts a new sitting. Inside a
    request whose transaction has already failed, it does nothing."""
    from django.db import DatabaseError
    from django.db.models import Case, F, Q, Value, When

    from .models import User

    if not getattr(user, "is_authenticated", False):
        return
    # A session request carries the User; an API request the AuthPrincipal,
    # which names the same row as user_id.
    user_pk = (
        getattr(user, "pk", None)
        or getattr(user, "user_id", None)
        or getattr(user, "id", None)
    )
    if not user_pk:
        return
    now = timezone.now()
    values = {
        "last_seen_at": now,
        "online_since": Case(
            When(
                Q(online_since__isnull=True)
                | Q(last_seen_at__isnull=True)
                | Q(last_seen_at__lt=now - ONLINE_WINDOW),
                then=Value(now),
            ),
            default=F("online_since"),
        ),
    }
    footprint = request_footprint(request)
    if footprint:
        values["last_seen_path"], values["last_seen_action"] = footprint
    try:
        User.objects.filter(pk=user_pk).update(**values)
    except DatabaseError:
        return


def format_duration(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "—"
    seconds = int(seconds)
    if seconds < 60:
        return "just now" if seconds < 30 else "<1m"
    minutes, _ = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m"


def _person(row: dict, *, now, online: bool, logins: dict | None = None) -> dict:
    from .presence_labels import describe

    last_seen = row["last_seen_at"]
    since = row["online_since"]
    if online:
        duration = (now - since).total_seconds() if since else 0
    elif since and last_seen and last_seen >= since:
        duration = (last_seen - since).total_seconds()
    else:
        duration = None
    described = describe(row["last_seen_path"] or "", row["last_seen_action"] or "")
    # This person's own sign-ins. Distinct from `last_seen_at`, which is the
    # last page they touched and keeps moving through a sitting; `last_login_at`
    # is when that sitting began.
    signin = (logins or {}).get(row["id"]) or {}
    last_login = signin.get("last_at")
    return {
        **row,
        "online": online,
        "duration_seconds": duration,
        "duration_label": format_duration(duration) if last_seen else "never",
        "section": described["section"] if last_seen else "—",
        "working_on": described["working_on"] if last_seen else "Never signed in",
        "last_login_at": last_login,
        "login_count": signin.get("total", 0),
        "logins_today": signin.get("today_count", 0),
        "logins_this_week": signin.get("week_count", 0),
        "last_login_label": (
            format_duration((now - last_login).total_seconds()) if last_login else None
        ),
    }


def _program_lead_of() -> tuple[dict[str, str], dict[str, str]]:
    """CCEO user id → Program Lead user id, and PL user id → name, from the
    direct reporting lines."""
    from django.db.models import Q

    from .models import StaffSupervisorAssignment

    pl = "Program Lead"
    links = (
        StaffSupervisorAssignment.objects.filter(
            Q(supervisor__user__active_role=pl)
            | Q(supervisor__user__roles__contains=[pl]),
            supervisor__deleted_at__isnull=True,
            supervisee__deleted_at__isnull=True,
        )
        .values_list(
            "supervisee__user_id", "supervisor__user_id", "supervisor__user__name"
        )
        .order_by("supervisor__user__name")
    )
    lead_of: dict[str, str] = {}
    names: dict[str, str] = {}
    for cceo_user_id, pl_user_id, pl_name in links:
        lead_of.setdefault(cceo_user_id, pl_user_id)
        names[pl_user_id] = pl_name
    return lead_of, names


def team_user_ids(user) -> set[str]:
    """The people this person supervises, and themselves.

    The reporting line, not a role and not a geography: a Programme Lead's
    Who's Online answers "who on my team is working", so it holds exactly the
    officers whose work they are answerable for. Read from
    ``StaffSupervisorAssignment``, the same links the country table folds its
    groups by, so the Lead's own panel and the Admin's cannot disagree about
    who is on a team.
    """
    from .models import StaffSupervisorAssignment

    own = getattr(user, "id", None)
    ids = {own} if own else set()
    if own:
        ids.update(
            StaffSupervisorAssignment.objects.filter(
                supervisor__user_id=own,
                supervisor__deleted_at__isnull=True,
                supervisee__deleted_at__isnull=True,
            ).values_list("supervisee__user_id", flat=True)
        )
    ids.discard(None)
    return ids


def presence_groups(people: list[dict]) -> list[dict]:
    """The table's rows folded so a country's roster does not run to a
    hundred lines: one group per Program Lead holding their CCEOs, one for
    CCEOs nobody leads, then everyone else by role. Online people sort first
    inside a group; groups with someone online open by default."""
    from .hr_dashboard_service import ROLE_LABELS

    lead_of, lead_names = _program_lead_of()
    by_id = {p["id"]: p for p in people}
    groups: dict[str, dict] = {}

    def group(key, label, kind, order):
        return groups.setdefault(
            key,
            {
                "key": key,
                "label": label,
                "kind": kind,
                "order": order,
                "lead": None,
                "members": [],
            },
        )

    for p in people:
        role = p["active_role"] or ""
        if role == "Program Lead":
            g = group(f"pl:{p['id']}", p["name"], "program_lead", (0, p["name"]))
            g["lead"] = p
            continue
        if role == "CCEO":
            pl_id = lead_of.get(p["id"])
            if pl_id:
                g = group(
                    f"pl:{pl_id}",
                    lead_names.get(pl_id)
                    or by_id.get(pl_id, {}).get("name", "Program Lead"),
                    "program_lead",
                    (0, lead_names.get(pl_id, "")),
                )
                g["members"].append(p)
            else:
                group(
                    "cceo:unled", "CCEOs without a Program Lead", "cceo", (1, "")
                ).setdefault("members", []).append(p)
            continue
        label = ROLE_LABELS.get(role, role.replace("_", " ").title() or "Other")
        group(f"role:{role}", label, "role", (2, label))["members"].append(p)

    out = []
    for g in groups.values():
        g["members"].sort(key=lambda p: (not p["online"], p["name"]))
        everyone = ([g["lead"]] if g["lead"] else []) + g["members"]
        g["total"] = len(everyone)
        g["online"] = sum(1 for p in everyone if p["online"])
        g["open"] = g["online"] > 0
        out.append(g)
    out.sort(key=lambda g: (g["order"][0], -g["online"], g["order"][1]))
    return out


def presence_summary(*, now=None, only_user_ids=None) -> dict:
    """Who is online and how often people signed in.

    With *only_user_ids* the whole panel is about those people: the roster, the
    online count, the sign-in totals and the fourteen-day chart. A Programme
    Lead reading their team's panel must not see a country number beside a team
    roster — that is two different questions on one line. An empty set is a
    team of nobody, and is answered as such rather than falling back to the
    country.
    """
    from django.db.models import Count, F, Max, Q
    from django.db.models.functions import TruncDate

    from .models import LoginEvent, User

    now = now or timezone.now()
    local_now = timezone.localtime(now)
    today = local_now.date()
    week_start = today - timedelta(days=today.weekday())  # Monday
    since_online = now - ONLINE_WINDOW

    # Sign-ins per person (owner, 2026-09-16: "sign-ins should be a column
    # inside Who's Online so that we can tell when they last signed in").
    # The panel already counted sign-ins for the whole country; this is the
    # same LoginEvent rows grouped by who they belong to, in one query, so a
    # roster of a hundred people still costs one read rather than a hundred.
    # `last_seen_at` is not this: it is the last page touched in a sitting,
    # which keeps moving long after the sign-in that began it.
    day_start = timezone.make_aware(
        timezone.datetime.combine(today, timezone.datetime.min.time()),
        timezone.get_current_timezone(),
    )
    week_start_dt = day_start - timedelta(days=today.weekday())
    events = LoginEvent.objects.filter(user__deleted_at__isnull=True)
    if only_user_ids is not None:
        events = events.filter(user_id__in=list(only_user_ids))
    logins_by_user = {
        row["user_id"]: row
        for row in events.values("user_id").annotate(
            last_at=Max("at"),
            total=Count("id"),
            today_count=Count("id", filter=Q(at__gte=day_start)),
            week_count=Count("id", filter=Q(at__gte=week_start_dt)),
        )
    }

    roster = User.objects.filter(is_active=True, deleted_at__isnull=True)
    if only_user_ids is not None:
        roster = roster.filter(id__in=list(only_user_ids))
    people = roster.values(
        "id",
        "name",
        "email",
        "active_role",
        "last_seen_at",
        "online_since",
        "last_seen_path",
        "last_seen_action",
    )
    online = [
        _person(person, now=now, online=True, logins=logins_by_user)
        for person in people.filter(last_seen_at__gte=since_online).order_by(
            "-last_seen_at"
        )[:PRESENCE_LIST_LIMIT]
    ]
    # Offline: seen before the window, or never. Most recently seen first, and
    # the people who have never signed in last.
    offline = [
        _person(person, now=now, online=False, logins=logins_by_user)
        for person in people.exclude(last_seen_at__gte=since_online).order_by(
            F("last_seen_at").desc(nulls_last=True), "name"
        )[:PRESENCE_LIST_LIMIT]
    ]
    # The table: everyone, folded by Program Lead and role (no cap — the
    # groups are what keep it short).
    everyone = [
        _person(
            person,
            now=now,
            online=bool(
                person["last_seen_at"] and person["last_seen_at"] >= since_online
            ),
            logins=logins_by_user,
        )
        for person in people.order_by("name")
    ]
    groups = presence_groups(everyone)

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
        "offline": offline,
        "offline_count": len(offline),
        "groups": groups,
        "people_count": len(everyone),
        "window_minutes": int(ONLINE_WINDOW.total_seconds() // 60),
        "logins_today": logins_today,
        "logins_this_week": logins_this_week,
        "logins_last_7_days": logins_last_7_days,
        "daily": daily,
        "weekly": weekly,
        "peak_day": max(daily, key=lambda d: d["count"])["count"] if daily else 0,
    }
