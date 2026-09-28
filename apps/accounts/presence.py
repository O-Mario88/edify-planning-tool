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
import re

from django.utils import timezone

logger = logging.getLogger(__name__)

ONLINE_WINDOW = timedelta(minutes=10)
# What the last beat of a sitting is worth: the page after it was read for a
# while that no request can show (the telemetry method's final-action credit).
FINAL_BEAT_SECONDS = 30
# The panel is a glance, not a directory: the most recently seen people first.
PRESENCE_LIST_LIMIT = 50


# The Who's Online filter (owner, 2026-09-28: "add the filter of day, week,
# month, quarter and FY"). A period is a run of calendar days in the platform's
# time zone; quarters and years are the operational ones (apps.core.fy).
PRESENCE_PERIODS: tuple[tuple[str, str], ...] = (
    ("day", "Day"),
    ("week", "Week"),
    ("month", "Month"),
    ("quarter", "Quarter"),
    ("fy", "Financial year"),
)
# Sign-in times listed per person; the count beside them is the whole period's.
LOGIN_TIMES_SHOWN = 20
# The Title column (owner, 2026-09-28: "Title (CCEO, PL…)"): the short name
# people use for a role, with the full one as the cell's title.
ROLE_TITLES = {
    "CCEO": "CCEO",
    "Program Lead": "PL",
    "RegionalProgramLead": "RPL",
    "CountryDirector": "CD",
    "RegionalVicePresident": "RVP",
    "ImpactAssessment": "IA",
    "Accountant": "Accountant",
    "HumanResources": "HR",
    "ProjectCoordinator": "Project Coordinator",
    "PartnerAdmin": "Partner Admin",
    "PartnerFieldOfficer": "Partner Officer",
    "BusinessTransformationOfficer": "BT Officer",
    "MfiPartnerAdmin": "MFI Admin",
    "MfiLoanOfficer": "MFI Loan Officer",
    "Admin": "Admin",
}


def _day_label(day, *, year: bool = True) -> str:
    return f"{day.day} {day.strftime('%b')}" + (f" {day.year}" if year else "")


def presence_period(period: str | None = None, on=None, *, today=None) -> dict:
    """The days a Who's Online period covers: ``start`` and ``end`` (both
    included), the key, the day it was chosen from and a label. An unknown
    period is a day; an unreadable date is today."""
    from datetime import date

    from apps.core.fy import (
        get_fy_date_range,
        get_operational_fy,
        get_quarter_date_range,
        get_quarter_for_date,
    )

    today = today or timezone.localdate()
    key = period if period in dict(PRESENCE_PERIODS) else "day"
    if isinstance(on, str):
        try:
            on = date.fromisoformat(on.strip())
        except ValueError:
            on = None
    on = on or today
    if key == "week":
        start = on - timedelta(days=on.weekday())  # Monday
        end = start + timedelta(days=6)
        if start.year != end.year:
            label = f"week of {_day_label(start)} – {_day_label(end)}"
        elif start.month != end.month:
            label = f"week of {_day_label(start, year=False)} – {_day_label(end)}"
        else:
            label = f"week of {start.day}–{_day_label(end)}"
    elif key == "month":
        start = on.replace(day=1)
        end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        label = start.strftime("%B %Y")
    elif key in ("quarter", "fy"):
        fy = get_operational_fy(on)
        if key == "quarter":
            quarter = get_quarter_for_date(on)
            first, after = get_quarter_date_range(fy, quarter)
            name = f"{quarter} FY{fy}"
        else:
            first, after = get_fy_date_range(fy)
            name = f"FY{fy}"
        start, end = first.date(), after.date() - timedelta(days=1)
        label = f"{name} ({start.strftime('%b %Y')} – {end.strftime('%b %Y')})"
    else:
        start = end = on
        label = "today" if on == today else f"{on.strftime('%a')} {_day_label(on)}"
    return {
        "key": key,
        "on": on,
        "start": start,
        "end": end,
        "label": label,
        "is_default": key == "day" and on == today,
    }


def presence_filters(request) -> dict:
    """The period and day a Who's Online request asked for, as keyword
    arguments for ``presence_summary``."""
    if request is None:
        return {}
    return {
        "period": request.GET.get("presence_period") or None,
        "on": request.GET.get("presence_on") or None,
    }


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
    "/sw.js",
    "/manifest",
    "/robots.txt",
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
    # A file (the service worker, a manifest, a map) is the browser's
    # machinery, not a page: "/sw.js" read as a part of the tool called
    # "Sw.Js" and was credited the minutes of whoever's browser fetched it.
    if path.startswith(_UNTRACKED_PREFIXES) or "." in path.rsplit("/", 1)[-1]:
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
    # The beat before this one, as the request loaded it (no extra read). The
    # time since it belongs to the page and task it recorded (owner,
    # 2026-09-28: how long, on which part, working on what).
    previous_seen = getattr(user, "last_seen_at", None)
    previous_path = getattr(user, "last_seen_path", None) or ""
    previous_action = getattr(user, "last_seen_action", None) or ""
    try:
        rows = User.objects.filter(pk=user_pk)
        # Guarded on the beat it read, so two requests at once cannot both
        # credit the same minutes: the second finds the beat moved and only
        # updates the presence.
        won = (
            rows.filter(last_seen_at=previous_seen).update(**values)
            if previous_seen and previous_path
            else 0
        )
        if not won:
            rows.update(**values)
            return
        credit_presence_time(
            user_pk,
            previous_seen,
            previous_path,
            previous_action,
            seconds=_credit_for((now - previous_seen).total_seconds()),
        )
    except DatabaseError:
        return


def _credit_for(gap: float) -> int:
    """Seconds a gap between two beats is worth: all of it inside a sitting,
    the final-beat credit when the sitting had ended in between."""
    if gap <= 0:
        return 0
    if gap <= ONLINE_WINDOW.total_seconds():
        return int(gap)
    return FINAL_BEAT_SECONDS


def credit_presence_time(user_pk, at, path: str, action: str, *, seconds: int) -> None:
    """Add seconds to the person's day, part of the tool and task at ``at``."""
    from django.db import IntegrityError, transaction
    from django.db.models import F

    from .models import PresenceTime
    from .presence_labels import describe

    if seconds <= 0:
        return
    described = describe(path, action)
    slot = {
        "user_id": user_pk,
        "day": timezone.localtime(at).date(),
        "section": described["section"][:64],
        "working_on": described["working_on"][:128],
    }
    if PresenceTime.objects.filter(**slot).update(seconds=F("seconds") + seconds):
        return
    try:
        with transaction.atomic():
            PresenceTime.objects.create(**slot, seconds=seconds)
    except IntegrityError:
        PresenceTime.objects.filter(**slot).update(seconds=F("seconds") + seconds)


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


def format_minutes(seconds: float | None) -> str:
    """Time on the tool, in hours and minutes (owner, 2026-09-28: "show
    minutes"). Never days: a financial year's hours read as hours."""
    seconds = int(seconds or 0)
    if seconds <= 0:
        return "0m"
    if seconds < 60:
        return "<1m"
    hours, minutes = divmod(seconds // 60, 60)
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m"


def _person(
    row: dict,
    *,
    now,
    online: bool,
    logins: dict | None = None,
    spent: dict | None = None,
    signins: dict | None = None,
) -> dict:
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
    person = {
        **row,
        "online": online,
        "duration_seconds": duration,
        # A sitting in hours and minutes, like every other time in the table
        # ("just now" read as a duration for someone who had left).
        "duration_label": format_minutes(duration) if last_seen else "never",
        "section": described["section"] if last_seen else "—",
        "working_on": described["working_on"] if last_seen else "Never signed in",
        "last_login_at": last_login,
        "login_count": signin.get("total", 0),
        "logins_today": signin.get("today_count", 0),
        "logins_this_week": signin.get("week_count", 0),
        "last_login_label": (
            format_duration((now - last_login).total_seconds()) if last_login else None
        ),
        "last_seen_label": (
            format_duration((now - last_seen).total_seconds()) if last_seen else None
        ),
        "title": ROLE_TITLES.get(row["active_role"] or "", row["active_role"] or "—"),
        # The chosen period (owner, 2026-09-28): time on the tool, where it
        # went and what on, and the sign-ins inside the period.
        **_period_figures(spent, signins, now=now),
    }
    # Owner, 2026-09-28: the page, what they are doing on it, then "other
    # part of the system accessed, duration of access" — every other part
    # the period's time went to.
    current = person["section"]
    # Beside its own column the page need not be said twice: "Dashboard" and
    # "Viewing Dashboard" read as "Dashboard" and "Viewing".
    person["working_label"] = (
        "Viewing"
        if person["working_on"] == f"Viewing {current}"
        else person["working_on"]
    )
    person["other_sections"] = [
        part for part in person["period_sections"] if part["section"] != current
    ]
    # Login day, date and time: the period's latest, else the last ever.
    person["login_at"] = person["period_last_login"] or last_login
    return person


def _when_label(at, *, now) -> str | None:
    """A sign-in time as short as it can be read: the time alone today, the
    day and month before it otherwise. All figures, so the table keeps the
    column whole instead of cutting the time off."""
    if not at:
        return None
    local = timezone.localtime(at)
    if local.date() == timezone.localtime(now).date():
        return local.strftime("%H:%M")
    return local.strftime("%d/%m %H:%M")


def _period_figures(spent: dict | None, signins: dict | None, *, now) -> dict:
    spent = spent or {}
    signins = signins or {}
    seconds = spent.get("seconds", 0)
    sections = sorted(
        (
            {
                "section": section,
                "seconds": total,
                "label": format_minutes(total),
            }
            for section, total in (spent.get("sections") or {}).items()
        ),
        key=lambda item: (-item["seconds"], item["section"]),
    )
    tasks = sorted(
        (
            {
                "working_on": working_on,
                "section": section,
                "seconds": total,
                "label": format_minutes(total),
            }
            for (section, working_on), total in (spent.get("tasks") or {}).items()
        ),
        key=lambda item: (-item["seconds"], item["working_on"]),
    )
    for item in sections:
        item["tasks"] = [task for task in tasks if task["section"] == item["section"]]
    return {
        "period_seconds": seconds,
        "period_time_label": format_minutes(seconds),
        "period_sections": sections,
        "period_tasks": tasks,
        "period_logins": signins.get("count", 0),
        "period_first_login": signins.get("first"),
        "period_last_login": signins.get("last"),
        "period_last_login_label": _when_label(signins.get("last"), now=now),
        "period_login_times": signins.get("times", []),
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
        # A Lead covering an absent Lead leads that Lead's officers while the
        # cover is active (apps.hr.team_roster.team_members). Team Today and
        # the past-due tables already count them; Who's Online now does too,
        # so the Lead's views agree about who is on the team.
        from apps.hr.team_roster import team_members

        ids.update(member.user_id for member in team_members(user))
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
        # A role with no plural label reads as words, not one run-together
        # word ("BusinessTransformationOfficer" was "Businesstransformationofficer").
        label = ROLE_LABELS.get(
            role, re.sub(r"(?<=[a-z])(?=[A-Z])", " ", role).replace("_", " ") or "Other"
        )
        group(f"role:{role}", label, "role", (2, label))["members"].append(p)

    out = []
    for g in groups.values():
        g["members"].sort(key=lambda p: (not p["online"], p["name"]))
        everyone = ([g["lead"]] if g["lead"] else []) + g["members"]
        g["total"] = len(everyone)
        g["online"] = sum(1 for p in everyone if p["online"])
        g["period_seconds"] = sum(p.get("period_seconds", 0) for p in everyone)
        g["period_time_label"] = format_minutes(g["period_seconds"])
        g["open"] = g["online"] > 0
        out.append(g)
    out.sort(key=lambda g: (g["order"][0], -g["online"], g["order"][1]))
    return out


def presence_summary(*, now=None, only_user_ids=None, period=None, on=None) -> dict:
    """Who is online and how often people signed in.

    *period* (day, week, month, quarter, fy) and *on*, a day inside it, choose
    the stretch the time and sign-in columns cover (owner, 2026-09-28); the
    default is today. Online now is always now.

    With *only_user_ids* the whole panel is about those people: the roster, the
    online count, the sign-in totals and the fourteen-day chart. A Programme
    Lead reading their team's panel must not see a country number beside a team
    roster — that is two different questions on one line. An empty set is a
    team of nobody, and is answered as such rather than falling back to the
    country.
    """
    from django.db.models import Count, F, Max, Min, Q, Sum, Window
    from django.db.models.functions import RowNumber, TruncDate

    from .models import LoginEvent, PresenceTime, User

    now = now or timezone.now()
    local_now = timezone.localtime(now)
    today = local_now.date()
    chosen = presence_period(period, on, today=today)
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

    # The period's sign-ins: how many, the first and last, and the latest
    # times themselves (two queries for the whole roster).
    tz = timezone.get_current_timezone()
    period_from = timezone.make_aware(
        timezone.datetime.combine(chosen["start"], timezone.datetime.min.time()), tz
    )
    period_to = timezone.make_aware(
        timezone.datetime.combine(
            chosen["end"] + timedelta(days=1), timezone.datetime.min.time()
        ),
        tz,
    )
    in_period = events.filter(at__gte=period_from, at__lt=period_to)
    signins_by_user = {
        row["user_id"]: {"count": row["n"], "first": row["first"], "last": row["last"]}
        for row in in_period.values("user_id").annotate(
            n=Count("id"), first=Min("at"), last=Max("at")
        )
    }
    latest = (
        in_period.annotate(
            nth=Window(RowNumber(), partition_by=F("user_id"), order_by=F("at").desc())
        )
        .filter(nth__lte=LOGIN_TIMES_SHOWN)
        .order_by("user_id", "-at")
        .values_list("user_id", "at")
    )
    for user_id, at in latest:
        signins_by_user.setdefault(user_id, {}).setdefault("times", []).append(at)

    # Time on the tool in the period, by part of the tool and task, summed in
    # the database (one row per person, part and task).
    spent_rows = PresenceTime.objects.filter(
        day__gte=chosen["start"],
        day__lte=chosen["end"],
        user__deleted_at__isnull=True,
    )
    if only_user_ids is not None:
        spent_rows = spent_rows.filter(user_id__in=list(only_user_ids))
    spent_by_user: dict[str, dict] = {}
    for row in spent_rows.values("user_id", "section", "working_on").annotate(
        total=Sum("seconds")
    ):
        spent = spent_by_user.setdefault(
            row["user_id"], {"seconds": 0, "sections": {}, "tasks": {}}
        )
        total = row["total"] or 0
        spent["seconds"] += total
        spent["sections"][row["section"]] = (
            spent["sections"].get(row["section"], 0) + total
        )
        spent["tasks"][(row["section"], row["working_on"])] = total

    def person(row, *, online):
        return _person(
            row,
            now=now,
            online=online,
            logins=logins_by_user,
            spent=spent_by_user.get(row["id"]),
            signins=signins_by_user.get(row["id"]),
        )

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
        person(row, online=True)
        for row in people.filter(last_seen_at__gte=since_online).order_by(
            "-last_seen_at"
        )[:PRESENCE_LIST_LIMIT]
    ]
    # Offline: seen before the window, or never. Most recently seen first, and
    # the people who have never signed in last.
    offline = [
        person(row, online=False)
        for row in people.exclude(last_seen_at__gte=since_online).order_by(
            F("last_seen_at").desc(nulls_last=True), "name"
        )[:PRESENCE_LIST_LIMIT]
    ]
    # The table: everyone, folded by Program Lead and role (no cap — the
    # groups are what keep it short).
    everyone = [
        person(
            row,
            online=bool(row["last_seen_at"] and row["last_seen_at"] >= since_online),
        )
        for row in people.order_by("name")
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
        "period": chosen,
        "period_options": PRESENCE_PERIODS,
        "period_logins": sum(p["period_logins"] for p in everyone),
        "period_seconds": sum(p["period_seconds"] for p in everyone),
        "period_time_label": format_minutes(sum(p["period_seconds"] for p in everyone)),
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
