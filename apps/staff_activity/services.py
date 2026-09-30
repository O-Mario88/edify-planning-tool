"""The Staff Activity Log: how staff use the platform, and what they get done.

Owner, 2026-09-29, replacing the Who's Online table. Two layers, never mixed:

* Platform engagement — successful sign-ins (``LoginEvent``, one per
  authentication, never a refresh), active time (``PresenceTime``, credited by
  the server between beats at most the idle threshold apart, so an open tab
  nobody touches stops counting, and deduplicated across tabs and devices
  because a person has one beat pointer, not one per session), the parts of
  the tool used, and each session's span, active and idle time.
* Meaningful actions — governed workflow transitions the person made, read
  from the audit chain through ``registry.MEANINGFUL_ACTIONS``. A page view is
  never an action; a failed transition is counted as failed, not done.

Time in the platform is a management and adoption signal, never a performance
score: nothing here ranks people, and "Follow-up suggested" only offers the
manager a conversation. Performance comes from targets and verified work.

Readers (docs/STAFF_TIME_STANDARD.md §5): a Programme Lead reads the people
they supervise and nobody else; a Country Director reads the country grouped
by Programme Lead; the Admin reads the country for technical support and
raises no follow-ups.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta

from django.utils import timezone

from apps.accounts.presence import (
    PRESENCE_PERIODS,
    ROLE_TITLES,
    _credit_for,
    activity_setting,
    format_minutes,
    is_untracked_path,
    presence_period,
    team_user_ids,
)

PROGRAM_LEAD = "Program Lead"
COUNTRY_DIRECTOR = "CountryDirector"
ADMIN = "Admin"
CCEO = "CCEO"

# The staff whose platform use the log covers (owner, 2026-09-29: "restrict
# roles to CCEO and PL since they are the focus to make sure they are using
# the system; the rest of the roles don't have to be added"): the field
# officers and their Programme Leads. Leadership, finance, HR, IA, BT and
# coordinator accounts are not listed, nor partner, MFI or Admin accounts.
INTERNAL_ROLES = (CCEO, PROGRAM_LEAD)

ROLE_FILTER_LABELS = {
    CCEO: "CCEO",
    PROGRAM_LEAD: "Program Lead",
    "RegionalProgramLead": "Regional PL",
    COUNTRY_DIRECTOR: "Country Director",
    "RegionalVicePresident": "RVP",
    "ImpactAssessment": "Impact Assessment",
    "Accountant": "Accountant",
    "HumanResources": "HR",
    "ProjectCoordinator": "Project Coordinator",
    "BusinessTransformationOfficer": "BT Officer",
}

STATUS_OPTIONS = (
    ("online", "Online"),
    ("idle", "Idle"),
    ("offline", "Offline"),
    ("no_login", "No login"),
    ("on_leave", "On approved leave"),
    ("follow_up", "Follow-up suggested"),
)

STATUS_TONES = {
    "online": "success",
    "idle": "warning",
    "offline": "neutral",
    "on_leave": "info",
}

# Follow-up suggestions (§9.1). Deliberately few and conservative: a
# suggestion is an offer to talk, and a noisy one teaches managers to ignore it.
FAILED_ACTIONS_SUGGESTION = 3
EXCESSIVE_TIME_FACTOR = 3
EXCESSIVE_TIME_FLOOR_SECONDS = 2 * 60 * 60
LOW_ENGAGEMENT_MIN_EXPECTED_DAYS = 3

# Detail panes stay short; each lists its total beside the rows it shows.
SESSIONS_SHOWN = 10
ACTIONS_SHOWN = 12


# ── Who may read whom ────────────────────────────────────────────────────────
def viewer_scope(user) -> dict | None:
    """What this reader's log covers, or None when the page is not theirs.

    ``mode`` is "team" (a Programme Lead: themselves and the people they
    supervise, including a covered Lead's officers while the cover lasts) or
    "country" (the Country Director and the Admin). ``can_follow_up`` is
    False for the Admin, whose access is technical support, not management;
    ``self_id`` is the reader when their own row is in the log, which nobody
    follows up with.
    """
    role = getattr(user, "active_role", "") or ""
    own = getattr(user, "id", None)
    if role == PROGRAM_LEAD:
        # The Lead's own row heads their team (owner, 2026-09-29: "Add the PL
        # on staff activity table too").
        ids = _tracked(team_user_ids(user))
        return {
            "mode": "team",
            "role": role,
            "ids": ids,
            "self_id": own if own in ids else None,
            "can_follow_up": True,
        }
    if role in (COUNTRY_DIRECTOR, ADMIN):
        return {
            "mode": "country",
            "role": role,
            "ids": country_roster_ids(user),
            "can_follow_up": role == COUNTRY_DIRECTOR,
        }
    return None


def _tracked(ids) -> set[str]:
    """The ids among these whose role the log covers (INTERNAL_ROLES)."""
    from apps.accounts.models import User

    return set(
        User.objects.filter(
            id__in=list(ids), active_role__in=INTERNAL_ROLES
        ).values_list("id", flat=True)
    )


def country_roster_ids(user) -> set[str]:
    """Every active CCEO and Programme Lead in the reader's country."""
    from apps.accounts.models import StaffProfile, User

    country = (
        StaffProfile.objects.filter(user_id=getattr(user, "id", None))
        .values_list("country", flat=True)
        .first()
    )
    people = User.objects.filter(
        is_active=True, deleted_at__isnull=True, active_role__in=INTERNAL_ROLES
    )
    if country:
        people = people.filter(staff_profile__country=country)
    ids = set(people.values_list("id", flat=True))
    ids.discard(getattr(user, "id", None))
    return ids


def can_read_person(viewer, person_id: str) -> bool:
    scope = viewer_scope(viewer)
    return bool(scope and person_id in scope["ids"])


# ── Periods ──────────────────────────────────────────────────────────────────
def activity_period(period=None, on=None, *, today=None) -> dict:
    """Day, week (Monday–Sunday), month, FY quarter or financial year — the
    platform's October–September calendar (apps.core.fy), shared with the
    presence record so the two cannot disagree."""
    chosen = presence_period(period, on, today=today)
    today = today or timezone.localdate()
    # The days of the period that have happened: a week read on Tuesday is
    # judged on Monday and Tuesday, not on days still to come.
    chosen["elapsed_end"] = min(chosen["end"], today)
    chosen["is_future"] = chosen["start"] > today
    return chosen


def _bounds(chosen: dict) -> tuple[datetime, datetime]:
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(
        datetime.combine(chosen["start"], datetime.min.time()), tz
    )
    end = timezone.make_aware(
        datetime.combine(chosen["end"] + timedelta(days=1), datetime.min.time()), tz
    )
    return start, end


# ── Expected working days ────────────────────────────────────────────────────
def _holidays(start: date, end: date) -> frozenset:
    from apps.hr.leave_services import PublicHolidayService

    return frozenset(PublicHolidayService.get_holidays_in_range(start, end))


def _leave_days(profile_ids) -> dict[str, frozenset]:
    """Approved leave days per staff profile, in one query (the canonical
    leave workflow's approved rows)."""
    from apps.accounts.models import Leave
    from apps.targets.fy_calendar import FinancialYearCalendarService

    spans: dict[str, list] = defaultdict(list)
    for staff_id, start, end in Leave.objects.filter(
        status="approved", staff_id__in=[p for p in profile_ids if p]
    ).values_list("staff_id", "start_date", "end_date"):
        spans[staff_id].append((start, end))
    return {
        staff_id: FinancialYearCalendarService._leave_day_set(person_spans)
        for staff_id, person_spans in spans.items()
    }


def _working_days(start: date, end: date, holidays, leave) -> tuple[int, int]:
    """(expected working days, days of approved leave that were working days)
    in [start, end]: weekdays that are not public holidays."""
    expected = on_leave = 0
    day = start
    while day <= end:
        if day.weekday() < 5 and day not in holidays:
            if day in leave:
                on_leave += 1
            else:
                expected += 1
        day += timedelta(days=1)
    return expected, on_leave


# ── Formatting ───────────────────────────────────────────────────────────────
def _initials(name: str) -> str:
    parts = [p for p in (name or "").replace("'", "").split() if p[:1].isalpha()]
    if not parts:
        return "?"
    return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()


def _clock(at, *, today) -> str:
    """A time as short as it reads: 07:01 today, 28/09 07:01 otherwise."""
    if not at:
        return "—"
    local = timezone.localtime(at)
    if local.date() == today:
        return local.strftime("%H:%M")
    return local.strftime("%d/%m %H:%M")


def _duration(seconds) -> str:
    return format_minutes(seconds)


# ── The log ──────────────────────────────────────────────────────────────────
def activity_log(
    viewer,
    *,
    period=None,
    on=None,
    role=None,
    program_lead=None,
    status=None,
    q=None,
    now=None,
) -> dict:
    """The page's figures for one reader and one period.

    Every summary, chart and row answers the same filters: the strip counts
    the rows the table lists.
    """
    now = now or timezone.now()
    today = timezone.localtime(now).date()
    scope = viewer_scope(viewer)
    if scope is None:
        raise PermissionError(
            "The Staff Activity Log is for Programme Leads and the Country Director."
        )
    chosen = activity_period(period, on, today=today)
    everyone = _people(scope["ids"], chosen, now=now, today=today)
    for person in everyone:
        _mark_self(person, scope)
    # The reader's own row first; the rest keep their order.
    everyone.sort(key=lambda p: not p["is_self"])

    # The Programme Lead column: whose team a person is on.
    leads = _program_leads(everyone)
    for person in everyone:
        person["program_lead"] = leads.get(person["id"])

    filtered = [
        p
        for p in everyone
        if (not role or p["active_role"] == role)
        and (
            not program_lead
            or p["id"] == program_lead
            or (p["program_lead"] or {}).get("id") == program_lead
        )
        and (not status or _matches_status(p, status))
        and (not q or q.lower() in (p["name"] or "").lower())
    ]

    return {
        "scope": scope,
        "period": chosen,
        "period_options": PRESENCE_PERIODS,
        "people": filtered,
        "groups": _groups(filtered, scope["mode"]),
        "kpis": _kpis(filtered, scope),
        "insights": _insights(filtered, chosen, now=now, today=today),
        "role_options": [
            (key, ROLE_FILTER_LABELS[key])
            for key in INTERNAL_ROLES
            if any(p["active_role"] == key for p in everyone)
        ],
        "program_lead_options": sorted(
            {
                (p["program_lead"]["id"], p["program_lead"]["name"])
                for p in everyone
                if p["program_lead"]
            }
            | {
                (p["id"], p["name"])
                for p in everyone
                if p["active_role"] == PROGRAM_LEAD
            },
            key=lambda item: item[1],
        ),
        "status_options": STATUS_OPTIONS,
        "filters": {
            "role": role or "",
            "program_lead": program_lead or "",
            "status": status or "",
            "q": q or "",
        },
        "total_people": len(everyone),
        "idle_minutes": activity_setting("IDLE_SECONDS") // 60,
    }


def _mark_self(person: dict, scope: dict) -> None:
    """Whether this row is the reader's own. Nobody follows up with
    themselves, so their own row suggests no follow-up."""
    person["is_self"] = bool(scope.get("self_id")) and person["id"] == scope.get(
        "self_id"
    )
    if not person["is_self"]:
        return
    person["suggestions"] = []
    if person["usage_key"] == "follow_up":
        person["usage_key"], person["usage_label"], person["usage_tone"] = (
            "normal",
            "Normal",
            "good",
        )


def _matches_status(person: dict, status: str) -> bool:
    if status == "follow_up":
        return bool(person["suggestions"]) or bool(person["open_follow_ups"])
    if status == "no_login":
        return person["usage_key"] == "no_login"
    return person["status_key"] == status


def _people(ids, chosen: dict, *, now, today) -> list[dict]:
    """One dict per person in scope with the period's figures, built in a
    fixed number of queries whatever the size of the roster."""
    from django.db.models import Count, F, Max, Min, Sum

    from apps.accounts.models import LoginEvent, PresenceTime, User
    from apps.accounts.presence_labels import describe

    ids = list(ids)
    if not ids:
        return []
    start_dt, end_dt = _bounds(chosen)

    rows = list(
        User.objects.filter(id__in=ids, is_active=True, deleted_at__isnull=True).values(
            "id",
            "name",
            "email",
            "active_role",
            "last_seen_at",
            "last_seen_path",
            "last_seen_action",
            "last_seen_login_id",
            profile_id=F("staff_profile__id"),
            district_id=F("staff_profile__primary_district_id"),
        )
    )
    ids = [r["id"] for r in rows]

    # Sign-ins in the period: one per authentication.
    logins = {
        r["user_id"]: r
        for r in LoginEvent.objects.filter(
            user_id__in=ids, at__gte=start_dt, at__lt=end_dt
        )
        .values("user_id")
        .annotate(n=Count("id"), first=Min("at"), last=Max("at"))
    }
    # Sessions that were active in the period (a session opened the evening
    # before still counts its morning).
    sessions = {
        r["user_id"]: r
        for r in LoginEvent.objects.filter(
            user_id__in=ids, at__lt=end_dt, last_active_at__gte=start_dt
        )
        .values("user_id")
        .annotate(first=Min("at"), last=Max("last_active_at"))
    }
    # Active time, and where it went.
    spent: dict[str, dict] = defaultdict(
        lambda: {"seconds": 0, "sections": defaultdict(int)}
    )
    for r in (
        PresenceTime.objects.filter(
            user_id__in=ids, day__gte=chosen["start"], day__lte=chosen["end"]
        )
        .values("user_id", "section")
        .annotate(total=Sum("seconds"))
    ):
        spent[r["user_id"]]["seconds"] += r["total"] or 0
        spent[r["user_id"]]["sections"][r["section"]] += r["total"] or 0

    actions = meaningful_action_counts(ids, start_dt, end_dt)
    supervisors = _supervisor_names(ids)
    regions = _regions({r["district_id"] for r in rows if r["district_id"]})
    holidays = _holidays(chosen["start"], chosen["end"])
    leave = _leave_days({r["profile_id"] for r in rows})
    follow_ups = _open_follow_ups(ids)
    online_after = now - timedelta(seconds=activity_setting("ONLINE_SECONDS"))
    from django.conf import settings

    session_after = now - timedelta(seconds=settings.SESSION_COOKIE_AGE)
    ended = _signed_out(rows)

    people = []
    for r in rows:
        uid = r["id"]
        time = spent.get(uid) or {"seconds": 0, "sections": {}}
        seconds = time["seconds"]
        sections = dict(time["sections"])
        # The time since the last beat, counted as the next beat will count
        # it, so a total read mid-sitting does not jump when the beat lands.
        last_seen = r["last_seen_at"]
        path = r["last_seen_path"] or ""
        if (
            last_seen
            and path
            and not is_untracked_path(path)
            and chosen["start"] <= timezone.localtime(last_seen).date() <= chosen["end"]
        ):
            pending = _credit_for((now - last_seen).total_seconds())
            section = describe(path, r["last_seen_action"] or "")["section"][:64]
            seconds += pending
            sections[section] = sections.get(section, 0) + pending

        signin = logins.get(uid) or {}
        session = sessions.get(uid) or {}
        first_active = (
            max(session["first"], start_dt)
            if session.get("first")
            else signin.get("first")
        )
        last_active = None
        if last_seen and start_dt <= last_seen < end_dt:
            last_active = last_seen
        elif session.get("last"):
            last_active = min(session["last"], end_dt)

        # Where they are now (the live status is always about now).
        if uid in ended and (not last_seen or ended[uid] >= last_seen):
            status_key = "offline"
        elif last_seen and last_seen >= online_after:
            status_key = "online"
        elif last_seen and last_seen >= session_after and path:
            status_key = "idle"
        else:
            status_key = "offline"
        person_leave = leave.get(r["profile_id"], frozenset())
        if status_key == "offline" and today in person_leave:
            status_key = "on_leave"

        expected, leave_days = _working_days(
            chosen["start"], chosen["elapsed_end"], holidays, person_leave
        )
        act = actions.get(uid) or {}
        described = (
            describe(path, r["last_seen_action"] or "")
            if path and not is_untracked_path(path)
            else None
        )
        person = {
            "id": uid,
            "name": r["name"] or r["email"],
            "email": r["email"],
            "initials": _initials(r["name"] or r["email"]),
            "active_role": r["active_role"] or "",
            "title": ROLE_TITLES.get(r["active_role"] or "", r["active_role"] or "—"),
            "supervisor": supervisors.get(uid, ""),
            "region": regions.get(r["district_id"], ""),
            "logins": signin.get("n", 0),
            "first_active": first_active,
            "first_active_label": _clock(first_active, today=today),
            "last_active": last_active,
            "last_active_label": _clock(last_active, today=today),
            "active_seconds": seconds,
            "active_label": _duration(seconds),
            "sections": sections,
            "last_page": described["section"] if described else "—",
            "last_task": described["working_on"] if described else "—",
            "last_action": act.get("last_label", ""),
            "last_action_at": act.get("last_at"),
            "last_action_label": _clock(act.get("last_at"), today=today)
            if act.get("last_at")
            else "",
            "actions": act.get("done", 0),
            "failed": act.get("failed", 0),
            "schools": act.get("schools", 0),
            "status_key": status_key,
            "status_label": dict(STATUS_OPTIONS).get(status_key, "Offline"),
            "status_tone": STATUS_TONES.get(status_key, "neutral"),
            "expected_days": expected,
            "leave_days": leave_days,
            "open_follow_ups": follow_ups.get(uid, []),
        }
        people.append(person)

    _judge_usage(people, chosen)
    people.sort(key=lambda p: (p["status_key"] != "online", (p["name"] or "").lower()))
    return people


def _signed_out(rows) -> dict[str, datetime]:
    """When each person's current session was ended by signing out."""
    from apps.accounts.models import LoginEvent

    login_ids = [r["last_seen_login_id"] for r in rows if r["last_seen_login_id"]]
    return {
        user_id: ended_at
        for user_id, ended_at in LoginEvent.objects.filter(
            id__in=login_ids, ended_at__isnull=False
        ).values_list("user_id", "ended_at")
    }


def _judge_usage(people: list[dict], chosen: dict) -> None:
    """The Usage Status column and the follow-up suggestions (§9.1).

    Role-aware: excessive time is judged against colleagues in the same role,
    never against one number of hours for everyone. Nothing here is a score.
    """
    by_role: dict[str, list[int]] = defaultdict(list)
    for p in people:
        if p["active_seconds"]:
            by_role[p["active_role"]].append(p["active_seconds"])
    role_median = {
        role: statistics.median(values)
        for role, values in by_role.items()
        if len(values) >= 3
    }
    for p in people:
        suggestions = []
        if chosen["is_future"]:
            usage = ("not_expected", "Not yet", "muted")
        elif p["expected_days"] == 0:
            usage = (
                ("on_leave", "On approved leave", "calm")
                if p["leave_days"]
                else ("not_expected", "No expected activity", "muted")
            )
        elif p["logins"] == 0 and p["active_seconds"] == 0:
            usage = ("no_login", "No login", "alarm")
            suggestions.append(("no_login", "No sign-in on an expected working day"))
        else:
            usage = ("normal", "Normal", "good")
        if usage[0] == "normal":
            if (
                p["actions"] == 0
                and p["expected_days"] >= LOW_ENGAGEMENT_MIN_EXPECTED_DAYS
            ):
                suggestions.append(
                    (
                        "low_engagement",
                        "Signed in, but no meaningful action in the period",
                    )
                )
            if p["failed"] >= FAILED_ACTIONS_SUGGESTION:
                suggestions.append(
                    ("repeated_errors", f"{p['failed']} failed actions in the period")
                )
            median = role_median.get(p["active_role"])
            if (
                median
                and p["active_seconds"] >= EXCESSIVE_TIME_FLOOR_SECONDS
                and p["active_seconds"] >= EXCESSIVE_TIME_FACTOR * median
            ):
                suggestions.append(
                    (
                        "excessive_time",
                        f"{_duration(p['active_seconds'])} active — over {EXCESSIVE_TIME_FACTOR}× "
                        "the median for the role; a workflow may be hard to use",
                    )
                )
            if suggestions:
                usage = ("follow_up", "Follow-up suggested", "watch")
        p["usage_key"], p["usage_label"], p["usage_tone"] = usage
        p["suggestions"] = [{"trigger": t, "reason": r} for t, r in suggestions]


def meaningful_action_counts(ids, start_dt, end_dt) -> dict[str, dict]:
    """Per person: meaningful actions done, failed, distinct schools acted on
    and the latest action — from the audit chain, in three queries."""
    from django.db.models import Count, OuterRef, Q, Subquery

    from apps.activities.models import Activity
    from apps.audit.models import AuditLog

    from .registry import (
        ACTIVITY_SUBJECTS,
        FAILED_REQUEST_ACTIONS,
        MEANINGFUL_ACTIONS,
        SCHOOL_SUBJECTS,
    )

    keys = list(MEANINGFUL_ACTIONS)
    rows = AuditLog.objects.filter(
        actor_id__in=list(ids), created_at__gte=start_dt, created_at__lt=end_dt
    )
    out: dict[str, dict] = defaultdict(dict)
    for r in (
        rows.filter(Q(action__in=keys) | Q(action__in=FAILED_REQUEST_ACTIONS))
        .values("actor_id")
        .annotate(
            done=Count("id", filter=Q(action__in=keys, success=True)),
            failed=Count("id", filter=Q(success=False)),
        )
    ):
        out[r["actor_id"]]["done"] = r["done"]
        out[r["actor_id"]]["failed"] = r["failed"]

    school_of_activity = Activity.all_objects.filter(id=OuterRef("subject_id")).values(
        "school_id"
    )[:1]
    touched = rows.filter(
        action__in=[k for k, d in MEANINGFUL_ACTIONS.items() if d.school], success=True
    )
    for actor_id, school_id in (
        touched.filter(subject_kind__in=SCHOOL_SUBJECTS)
        .values_list("actor_id", "subject_id")
        .distinct()
    ):
        out[actor_id].setdefault("_schools", set()).add(school_id)
    for actor_id, school_id in (
        touched.filter(subject_kind__in=ACTIVITY_SUBJECTS)
        .annotate(school=Subquery(school_of_activity))
        .values_list("actor_id", "school")
        .distinct()
    ):
        if school_id:
            out[actor_id].setdefault("_schools", set()).add(school_id)

    latest = (
        rows.filter(action__in=keys, success=True)
        .order_by("actor_id", "-created_at")
        .distinct("actor_id")
        .values_list("actor_id", "action", "created_at")
    )
    for actor_id, action, at in latest:
        out[actor_id]["last_label"] = MEANINGFUL_ACTIONS[action].label
        out[actor_id]["last_at"] = at
    for value in out.values():
        value["schools"] = len(value.pop("_schools", ()))
    return out


def _supervisor_names(ids) -> dict[str, str]:
    """Each person's direct manager (the first reporting line, by name)."""
    from apps.accounts.models import StaffSupervisorAssignment

    names: dict[str, str] = {}
    for supervisee, name in (
        StaffSupervisorAssignment.objects.filter(
            supervisee__user_id__in=list(ids),
            supervisor__deleted_at__isnull=True,
            supervisee__deleted_at__isnull=True,
            supervisor__user__active_role__in=(
                PROGRAM_LEAD,
                COUNTRY_DIRECTOR,
                "RegionalProgramLead",
                "HumanResources",
            ),
        )
        .order_by("supervisor__user__name")
        .values_list("supervisee__user_id", "supervisor__user__name")
    ):
        names.setdefault(supervisee, name or "")
    return names


def _program_leads(people: list[dict]) -> dict[str, dict]:
    """person id → their Programme Lead {id, name}, from the direct reporting
    lines (the same links Who's Online folded its groups by)."""
    from apps.accounts.presence import _program_lead_of

    lead_of, names = _program_lead_of()
    return {
        p["id"]: {"id": lead_of[p["id"]], "name": names.get(lead_of[p["id"]], "")}
        for p in people
        if p["id"] in lead_of
    }


def _regions(district_ids) -> dict[str, str]:
    from apps.geography.models import District

    return dict(
        District.objects.filter(id__in=list(district_ids)).values_list(
            "id", "region__name"
        )
    )


def _open_follow_ups(ids) -> dict[str, list[dict]]:
    from .models import OPEN_STATUSES, StaffUsageFollowUp

    out: dict[str, list[dict]] = defaultdict(list)
    for fu in StaffUsageFollowUp.objects.filter(
        subject_id__in=list(ids), status__in=OPEN_STATUSES
    ).values("id", "subject_id", "status", "trigger", "due_date"):
        out[fu["subject_id"]].append(fu)
    return out


# ── Grouping, summary strip and insights ─────────────────────────────────────
def _groups(people: list[dict], mode: str) -> list[dict]:
    """A Programme Lead reads one list. The country reads each Programme
    Lead's team under the Lead, then everyone else by role (§8.3)."""
    if mode == "team":
        return [
            {
                "key": "team",
                "label": "",
                "kind": "team",
                "lead": None,
                "members": people,
            }
        ]
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
        if p["active_role"] == PROGRAM_LEAD:
            group(f"pl:{p['id']}", p["name"], "program_lead", (0, p["name"]))[
                "lead"
            ] = p
        elif p["program_lead"]:
            lead = p["program_lead"]
            group(f"pl:{lead['id']}", lead["name"], "program_lead", (0, lead["name"]))[
                "members"
            ].append(p)
        elif p["active_role"] == CCEO:
            group("cceo:unled", "CCEOs without a Program Lead", "cceo", (1, ""))[
                "members"
            ].append(p)
        else:
            label = ROLE_FILTER_LABELS.get(
                p["active_role"], p["active_role"] or "Other"
            )
            group(f"role:{p['active_role']}", label, "role", (2, label))[
                "members"
            ].append(p)
    out = []
    for g in groups.values():
        everyone = ([g["lead"]] if g["lead"] else []) + g["members"]
        g["total"] = len(everyone)
        g["online"] = sum(1 for p in everyone if p["status_key"] == "online")
        g["active_seconds"] = sum(p["active_seconds"] for p in everyone)
        g["active_label"] = _duration(g["active_seconds"])
        g["actions"] = sum(p["actions"] for p in everyone)
        g["no_login"] = sum(1 for p in everyone if p["usage_key"] == "no_login")
        out.append(g)
    out.sort(key=lambda g: g["order"])
    return out


def _kpis(people: list[dict], scope: dict) -> dict:
    expected = [p for p in people if p["expected_days"] > 0]
    active = [p for p in people if p["logins"] or p["active_seconds"]]
    seconds = [p["active_seconds"] for p in active]
    open_follow_ups = sum(len(p["open_follow_ups"]) for p in people)
    return {
        "staff_expected": len(expected),
        "staff_total": len(people),
        "staff_active": len(active),
        "active_share": round(len(active) / len(expected) * 100) if expected else None,
        "no_login": sum(1 for p in people if p["usage_key"] == "no_login"),
        "total_active_seconds": sum(seconds),
        "total_active_label": _duration(sum(seconds)),
        "median_active_label": _duration(statistics.median(seconds))
        if seconds
        else "0m",
        "meaningful_actions": sum(p["actions"] for p in people),
        "schools": sum(p["schools"] for p in people),
        "open_follow_ups": open_follow_ups,
        "suggested": sum(
            1 for p in people if p["suggestions"] and not p["open_follow_ups"]
        ),
    }


def _insights(people: list[dict], chosen: dict, *, now, today) -> dict:
    """The side panel: live status, where the time went, the trend and the
    devices — all over the rows the table lists."""
    from django.db.models import Count

    from apps.accounts.models import LoginEvent, PresenceTime

    ids = [p["id"] for p in people]
    counts = {key: 0 for key in ("online", "idle", "offline", "on_leave")}
    for p in people:
        counts[p["status_key"]] = counts.get(p["status_key"], 0) + 1
    total = len(people) or 1
    status = [
        {
            "key": key,
            "label": dict(STATUS_OPTIONS)[key],
            "count": counts[key],
            "share": round(counts[key] / total * 100),
        }
        for key in ("online", "idle", "offline", "on_leave")
    ]

    modules: dict[str, int] = defaultdict(int)
    for p in people:
        for section, seconds in p["sections"].items():
            modules[section] += seconds
    all_seconds = sum(modules.values())
    ranked = sorted(modules.items(), key=lambda kv: -kv[1])
    top, rest = ranked[:5], ranked[5:]
    if rest:
        top.append(("Other", sum(s for _, s in rest)))
    module_rows = [
        {
            "label": label,
            "seconds": seconds,
            "time": _duration(seconds),
            "share": round(seconds / all_seconds * 100) if all_seconds else 0,
        }
        for label, seconds in top
    ]

    # Active staff per day, the seven days up to the period's end.
    trend_end = chosen["elapsed_end"]
    trend_start = trend_end - timedelta(days=6)
    per_day = dict(
        PresenceTime.objects.filter(
            user_id__in=ids, day__gte=trend_start, day__lte=trend_end
        )
        .values("day")
        .annotate(n=Count("user_id", distinct=True))
        .values_list("day", "n")
    )
    trend = [
        {
            "day": trend_start + timedelta(days=i),
            "label": (trend_start + timedelta(days=i)).strftime("%a"),
            "count": per_day.get(trend_start + timedelta(days=i), 0),
        }
        for i in range(7)
    ]
    peak = max((d["count"] for d in trend), default=0) or 1
    for d in trend:
        d["height"] = round(d["count"] / peak * 100)

    start_dt, end_dt = _bounds(chosen)
    devices = dict(
        LoginEvent.objects.filter(user_id__in=ids, at__gte=start_dt, at__lt=end_dt)
        .exclude(device="")
        .values("device")
        .annotate(n=Count("id"))
        .values_list("device", "n")
    )
    device_total = sum(devices.values())
    device_rows = [
        {
            "key": key,
            "label": label,
            "count": devices.get(key, 0),
            "share": round(devices.get(key, 0) / device_total * 100)
            if device_total
            else 0,
        }
        for key, label in (
            ("desktop", "Desktop"),
            ("mobile", "Mobile"),
            ("tablet", "Tablet"),
        )
    ]
    return {
        "status": status,
        "online": counts["online"],
        "modules": module_rows,
        "trend": trend,
        "devices": device_rows,
        "device_total": device_total,
    }


# ── One person, opened ───────────────────────────────────────────────────────
def person_detail(viewer, person_id: str, *, period=None, on=None, now=None) -> dict:
    """The expanded row: sign-in history, time by part of the tool, the
    meaningful-action timeline, the period trend and follow-ups. Loaded only
    when a row is opened."""
    from django.db.models import Count, Q

    from apps.accounts.models import LoginEvent, PresenceTime, User
    from apps.audit.models import AuditLog
    from django.conf import settings

    from .models import StaffUsageFollowUp
    from .registry import FAILED_REQUEST_ACTIONS, MEANINGFUL_ACTIONS, record_link

    if not can_read_person(viewer, person_id):
        raise PermissionError("Not in your scope.")
    now = now or timezone.now()
    today = timezone.localtime(now).date()
    chosen = activity_period(period, on, today=today)
    start_dt, end_dt = _bounds(chosen)
    person = next(iter(_people([person_id], chosen, now=now, today=today)), None)
    if person is None:
        raise PermissionError("Not in your scope.")
    _mark_self(person, viewer_scope(viewer))
    user = User.objects.get(pk=person_id)

    # A. Sign-in history.
    session_rows = LoginEvent.objects.filter(user_id=person_id, at__lt=end_dt).filter(
        Q(at__gte=start_dt) | Q(last_active_at__gte=start_dt)
    )
    session_total = session_rows.count()
    sessions = []
    current_login = user.last_seen_login_id
    timeout = timedelta(seconds=settings.SESSION_COOKIE_AGE)
    for s in session_rows.order_by("-at")[:SESSIONS_SHOWN]:
        active = s.active_seconds
        last_active = s.last_active_at or s.at
        is_current = (
            s.pk == current_login
            and not s.ended_at
            and user.last_seen_at
            and now - user.last_seen_at < timeout
        )
        if is_current:
            pending = _credit_for((now - user.last_seen_at).total_seconds())
            active += pending
            last_active = max(last_active, user.last_seen_at)
            end = now
            ended = "Current session"
        elif s.ended_at:
            end = s.ended_at
            ended = f"Signed out {_clock(s.ended_at, today=today)}"
        else:
            end = last_active
            ended = f"Timed out after {_clock(last_active, today=today)}"
        span = max(0, int((end - s.at).total_seconds()))
        active = min(active, span) if span else active
        sessions.append(
            {
                "at": s.at,
                "at_label": timezone.localtime(s.at).strftime("%a %d %b %Y, %H:%M"),
                "device": (s.device or "unknown").title(),
                "span_label": _duration(span),
                "active_label": _duration(active),
                "idle_label": _duration(max(0, span - active)),
                "ended": ended,
                "current": bool(is_current),
            }
        )

    # B. Time by part of the tool, with the actions done there.
    actions = AuditLog.objects.filter(
        actor_id=person_id, created_at__gte=start_dt, created_at__lt=end_dt
    )
    done = actions.filter(action__in=list(MEANINGFUL_ACTIONS), success=True)
    per_module_actions: dict[str, int] = defaultdict(int)
    for action, n in (
        done.values("action").annotate(n=Count("id")).values_list("action", "n")
    ):
        per_module_actions[MEANINGFUL_ACTIONS[action].module] += n
    sections = person["sections"]
    module_names = sorted(
        set(sections) | set(per_module_actions),
        key=lambda m: (-sections.get(m, 0), m),
    )
    total = person["active_seconds"] or 0
    modules = [
        {
            "label": m,
            "time": _duration(sections.get(m, 0)),
            "share": round(sections.get(m, 0) / total * 100) if total else 0,
            "actions": per_module_actions.get(m, 0),
        }
        for m in module_names
    ]
    tasks = (
        PresenceTime.objects.filter(
            user_id=person_id, day__gte=chosen["start"], day__lte=chosen["end"]
        )
        .values("working_on")
        .distinct()
        .count()
    )

    # C. Meaningful-action timeline (successful and failed).
    timeline_rows = actions.filter(
        Q(action__in=list(MEANINGFUL_ACTIONS)) | Q(action__in=FAILED_REQUEST_ACTIONS)
    ).order_by("-created_at")
    timeline_total = timeline_rows.count()
    timeline = []
    for a in timeline_rows[:ACTIONS_SHOWN]:
        definition = MEANINGFUL_ACTIONS.get(a.action)
        timeline.append(
            {
                "at_label": _clock(a.created_at, today=today),
                "label": definition.label if definition else "A request failed",
                "module": definition.module if definition else (a.reason or "")[:80],
                "outcome": "Successful" if a.success else "Failed",
                "ok": a.success,
                "link": record_link(a.subject_kind, a.subject_id) if a.success else "",
            }
        )

    # D. The period trend: by day up to a month, by week for a quarter, by
    # month for a year.
    trend = _person_trend(person_id, chosen, done)
    login_days = (
        LoginEvent.objects.filter(user_id=person_id, at__gte=start_dt, at__lt=end_dt)
        .dates("at", "day")
        .count()
    )

    follow_ups = list(
        StaffUsageFollowUp.objects.filter(subject_id=person_id)
        .select_related("created_by", "assignee")
        .order_by("-created_at")[:5]
    )
    return {
        "person": person,
        "period": chosen,
        "sessions": sessions,
        "session_total": session_total,
        "modules": modules,
        "tasks": tasks,
        "timeline": timeline,
        "timeline_total": timeline_total,
        "trend": trend,
        "login_days": login_days,
        "follow_ups": follow_ups,
        "profile": {
            "email": user.email,
        },
    }


def _person_trend(person_id: str, chosen: dict, done_actions) -> list[dict]:
    from django.db.models import Count, Sum
    from django.db.models.functions import TruncDate

    from apps.accounts.models import PresenceTime

    start, end = chosen["start"], chosen["elapsed_end"]
    if end < start:
        return []
    days = (end - start).days + 1
    if days <= 31:

        def bucket(d):
            return d

        def label(d):
            return d.strftime("%a %d") if days > 7 else d.strftime("%a")
    elif days <= 100:

        def bucket(d):
            return d - timedelta(days=d.weekday())

        def label(d):
            return d.strftime("%d %b")
    else:

        def bucket(d):
            return d.replace(day=1)

        def label(d):
            return d.strftime("%b")

    seconds: dict = defaultdict(int)
    for day, total in (
        PresenceTime.objects.filter(user_id=person_id, day__gte=start, day__lte=end)
        .values("day")
        .annotate(t=Sum("seconds"))
        .values_list("day", "t")
    ):
        seconds[bucket(day)] += total or 0
    actions: dict = defaultdict(int)
    for day, n in (
        done_actions.annotate(d=TruncDate("created_at"))
        .values("d")
        .annotate(n=Count("id"))
        .values_list("d", "n")
    ):
        if day:
            actions[bucket(day)] += n
    keys = []
    d = start
    while d <= end:
        k = bucket(d)
        if k not in keys:
            keys.append(k)
        d += timedelta(days=1)
    peak = max([seconds[k] for k in keys] + [1])
    return [
        {
            "label": label(k),
            "time": _duration(seconds[k]),
            "actions": actions[k],
            "height": round(seconds[k] / peak * 100),
        }
        for k in keys
    ]
