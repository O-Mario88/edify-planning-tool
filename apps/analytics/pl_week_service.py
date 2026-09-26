"""The Programme Lead's week: where the lead and their officers are working,
what is overdue from the week before, and what the partners did.

Owner, 2026-09-26: the Programme Lead's default dashboard is what the lead and
their CCEOs have planned and are working on this week, one tab per person, so
the lead can follow up with each of them; partner work has its own tab for
strict monitoring; and last week's unfinished work comes first, because it is
the freshest follow-up there is.

A read: it owns no table and writes nothing. Three rules keep it honest.

* An activity's day is its planned date, falling back to the scheduled
  timestamp. That is how "What needs you now" and Partner Monitoring date
  work, so an item is never overdue on one list and due this week on another.
  Rescheduling moves both dates together.
* An officer has completed an activity when the evidence is uploaded and the
  Salesforce ID entered: completing does both and hands it to the lead
  (`submitted_to_pl`). Each row therefore asks the lead for one of two things
  (owner, 2026-09-26): Verify, when the officer has completed it — the lead's
  own completion review — or Send to <officer>, when they have not.
* Each officer's tab has two lists, Overdue from last week and Due this week,
  each tabled as "What needs you now" tables the same work: School Visits,
  Group Trainings and Cluster Meetings, with the same columns. Completed work
  leaves both lists (owner, 2026-09-26): once verified, or with Impact
  Assessment, it is gone, so each list is only what still needs someone.
  Every row past its day is overdue and drawn in red. Older past-due work
  stays in the backlog, All overdue plans.
* Officers' tabs hold the work they deliver themselves; partner-delivered
  work is the Partners tab's, read from Partner Monitoring's own items so the
  two pages cannot disagree about a partner.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, timedelta
from urllib.parse import urlencode

from django.db.models import Q
from django.utils import timezone

from apps.activities.models import Activity
from apps.core.activity_types import (
    CLUSTER_MEETING_TYPES,
    COMPLETED_WORK_STATUSES,
    TRAINING_TYPES,
    VISIT_TYPES,
)
from apps.my_plan import past_due_service
from apps.my_plan.past_due_service import PastDueRows, activity_rows, reminder_sent_on

logger = logging.getLogger(__name__)

EVERYONE = "everyone"
ME = "me"
PARTNERS = "partners"

#: Work that was never going to happen: not late, not planned, not done. An
#: activity awaiting its school owner's approval is not a plan yet either.
RELEASED_STATUSES = (
    "cancelled",
    "rejected",
    "deferred",
    "not_planned",
    "awaiting_owner_approval",
)
#: Past the team: partner or legacy work that Impact Assessment is verifying.
WITH_IA_STATUSES = ("awaiting_ia_verification",)
#: Completed from the officer's side — evidence uploaded, Salesforce ID
#: entered — and waiting on the lead's verification.
AWAITING_LEAD_STATUSES = ("submitted_to_pl",)
#: Nothing left for the officer or the lead to do this week.
#: Verified work (the lead's verification, or on older work Impact
#: Assessment's) and work with Impact Assessment.
CLOSED_STATUSES = (*COMPLETED_WORK_STATUSES, *WITH_IA_STATUSES)
#: Delivered, with the evidence or the Salesforce ID still to go in.
NOT_SUBMITTED_STATUSES = ("evidence_uploaded", "evidence_accepted")
SF_MISSING_STATUSES = ("salesforce_id_required",)
STARTED_STATUSES = ("in_progress", "completion_started")
RETURNED_STATUSES = ("returned", "returned_by_pl", "returned_by_ia")

#: The three tables, grouped exactly as "What needs you now" groups them:
#: trainings, cluster meetings, and every other type with the school visits.
TABLES = (
    ("visits", "School Visits"),
    ("trainings", "Group Trainings"),
    ("meetings", "Cluster Meetings"),
)
OVERDUE = "overdue"
DUE_THIS_WEEK = "week"

#: How far either side of today the week arrows reach. Far enough to review a
#: quarter; near enough that a stray link cannot ask for a decade.
WEEK_REACH = 26
#: Rows per table page; a busy officer's week fits on one.
ROWS_PER_PAGE = 20

_CSS = {
    "success": "bg-emerald-50 text-emerald-700 border-emerald-200",
    "info": "edify-primary-soft edify-primary-text edify-primary-border",
    "warning": "bg-amber-50 text-amber-700 border-amber-200",
    "danger": "bg-rose-50 text-rose-700 border-rose-200",
    "neutral": "bg-slate-100 text-slate-600 border-slate-200",
}


# ── Dates ────────────────────────────────────────────────────────────────────
def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def resolve_week(raw, today: date) -> date:
    """The Monday of the week a request names (any day in it will do), or of
    this week when it names none, names nonsense or reaches too far."""
    this_week = monday_of(today)
    try:
        asked = monday_of(date.fromisoformat(str(raw or "").strip()[:10]))
    except ValueError:
        return this_week
    if abs((asked - this_week).days) > WEEK_REACH * 7:
        return this_week
    return asked


def activity_day(activity) -> date | None:
    """The planned date, falling back to the scheduled timestamp an older row
    carries on its own — the past-due rule's reading of when work is due."""
    if activity.planned_date:
        return activity.planned_date
    moment = activity.scheduled_date
    if not moment:
        return None
    if timezone.is_naive(moment):
        return moment.date()
    return timezone.localtime(moment).date()


def _dated_between(start: date, end: date) -> Q:
    return Q(planned_date__range=(start, end)) | Q(
        planned_date__isnull=True, scheduled_date__date__range=(start, end)
    )


def _day_label(day: date | None) -> str:
    return f"{day:%a %-d %b}" if day else "No date"


# ── One activity, in words ───────────────────────────────────────────────────
def week_status(status: str, day: date | None, today: date) -> dict:
    """Where an activity stands, and what it asks of the lead.

    `action` is "verify" when the officer has completed it (evidence and
    Salesforce ID in, waiting on the lead), "send" when they have not, and
    "none" once it is verified or with Impact Assessment. `done` is whether
    the officer's part is finished; `tone` colours the week board.
    """
    past = bool(day and day < today)
    if status in COMPLETED_WORK_STATUSES:
        key, label, tone, action = "verified", "Verified", "success", "none"
    elif status in WITH_IA_STATUSES:
        key, label, tone, action = "with_ia", "With Impact Assessment", "info", "none"
    elif status in AWAITING_LEAD_STATUSES:
        key, label, tone, action = (
            "awaiting_you",
            "Awaiting your verification",
            "info",
            "verify",
        )
    elif status in SF_MISSING_STATUSES:
        key, label, tone, action = (
            "sf_missing",
            "Salesforce ID missing",
            "warning",
            "send",
        )
    elif status in NOT_SUBMITTED_STATUSES:
        key, label, tone, action = (
            "not_submitted",
            "Evidence uploaded, not submitted",
            "warning",
            "send",
        )
    elif status in STARTED_STATUSES:
        key, label, tone, action = "started", "In Progress", "warning", "send"
    elif status in RETURNED_STATUSES:
        key, label, tone, action = "returned", "Returned", "danger", "send"
    elif past:
        key, label, tone, action = "past_due", "Past Due", "danger", "send"
    elif day == today:
        key, label, tone, action = "today", "Due today", "neutral", "send"
    else:
        key, label, tone, action = "scheduled", "Scheduled", "neutral", "send"
    return {
        "key": key,
        "label": label,
        "tone": tone,
        "css": _CSS[tone],
        "action": action,
        "done": key in ("verified", "with_ia", "awaiting_you"),
        "open": key not in ("verified", "with_ia"),
    }


def kind_of(activity_type: str) -> str:
    """What the week board calls a piece of work."""
    if activity_type in VISIT_TYPES:
        return "visit"
    if activity_type in TRAINING_TYPES:
        return "training"
    if activity_type in CLUSTER_MEETING_TYPES:
        return "meeting"
    return "other"


def table_of(activity_type: str) -> str:
    """Which of the three tables a piece of work sits in: "What needs you
    now"'s own grouping, so the two pages never table it differently."""
    if activity_type in past_due_service.TRAINING_TYPES:
        return "trainings"
    if activity_type in past_due_service.MEETING_TYPES:
        return "meetings"
    return "visits"


def _place(activity) -> tuple[str, str, str]:
    """(where, district, link) — the school, else the cluster, else the venue
    of work that has no school to inherit a place from."""
    school = activity.school if activity.school_id else None
    if school is not None:
        district = school.district.name if school.district_id else ""
        return school.name, district, f"/schools/{school.id}"
    cluster = activity.cluster if activity.cluster_id else None
    if cluster is not None:
        district = cluster.district.name if cluster.district_id else ""
        return cluster.name, district, f"/clusters/{cluster.id}"
    event_district = activity.event_district.name if activity.event_district_id else ""
    if activity.venue:
        return activity.venue, event_district, ""
    if event_district:
        return event_district, "", ""
    return "No place recorded", "", ""


def _row(activity, today: date) -> dict:
    """One activity as the week board draws it."""
    day = activity_day(activity)
    state = week_status(activity.status, day, today)
    where, district, place_url = _place(activity)
    title = activity.get_activity_type_display()
    detail = (activity.activity_name_snapshot or "").strip()
    return {
        "id": activity.id,
        "day": day,
        "kind": kind_of(activity.activity_type),
        "table": table_of(activity.activity_type),
        "type_label": title,
        "detail": detail if detail and detail.lower() != title.lower() else "",
        "where": where,
        "district": district,
        "place_url": place_url,
        "state": state["key"],
        "state_label": state["label"],
        "tone": state["tone"],
        "done": state["done"],
        "open": state["open"],
        "awaiting_you": state["action"] == "verify",
        # Past its day and the officer's part still not done.
        "behind": not state["done"] and bool(day and day < today),
    }


def table_rows(activity_ids, *, own_ids, today: date, send_until: date) -> list[dict]:
    """The table rows for these activities: "What needs you now"'s rows, with
    the week's status and the one action each asks of the lead.

    `send_until` is the last day a reminder can be sent for — the end of the
    real current week, the reach of the Send to endpoint — so a row the
    endpoint would refuse is never offered one.
    """
    rows = activity_rows(activity_ids, own_ids=own_ids, today=today)
    ids = [r["id"] for r in rows]
    sent_on = reminder_sent_on(ids)
    salesforce, evidence = _completion_records(ids)
    for row in rows:
        # The two halves of completing (owner, 2026-09-26): the Salesforce
        # ID, and the uploaded form. Blank here reads "Not in SF" and "No
        # Evidence Uploaded" in the tables.
        row["salesforce_id"] = salesforce.get(row["id"], "")
        row["evidence_label"] = _evidence_label(
            table_of(row["activity_type"]), evidence.get(row["id"], set())
        )
        day = row["planned_date"]
        state = week_status(row["status"], day, today)
        row["status_label"] = state["label"]
        row["status_class"] = state["css"]
        # Overdue: past its day and not yet verified — drawn red, whoever
        # it now waits on (owner, 2026-09-26: "all overdue activities").
        row["is_overdue"] = bool(day and day < today and state["open"])
        if row["is_own"]:
            # The lead's own work keeps "What needs you now"'s own actions.
            action = "own" if state["action"] == "send" else "none"
        elif state["action"] == "verify":
            action = "verify"
        elif state["action"] == "send" and day and day <= send_until:
            action = "sent" if row["reminder_sent"] else "send"
        else:
            action = "none"
        row["action"] = action
        row["sent_on"] = sent_on.get(row["id"])
    return rows


#: The form each table's work is completed with (owner, 2026-09-26): the
#: visit form for a school visit, the attendance register for a group
#: training or a cluster meeting.
EXPECTED_EVIDENCE = {
    "visits": ("visit_form", "Visit Form"),
    "trainings": ("attendance_form", "Attendance"),
    "meetings": ("attendance_form", "Attendance"),
}


def _completion_records(activity_ids) -> tuple[dict[str, str], dict[str, set]]:
    """Each activity's Salesforce ID, and the kinds of evidence uploaded for
    it — two queries for a page of rows. Evidence counts as uploaded the way
    completion counts it: any record not quarantined."""
    if not activity_ids:
        return {}, {}
    from apps.evidence.models import EvidenceRecord

    salesforce = {
        activity_id: (value or "").strip()
        for activity_id, value in Activity.objects.filter(
            id__in=activity_ids
        ).values_list("id", "salesforce_activity_id")
    }
    evidence: dict[str, set] = defaultdict(set)
    for activity_id, kind in EvidenceRecord.objects.filter(
        activity_id__in=activity_ids, quarantined=False
    ).values_list("activity_id", "kind"):
        evidence[activity_id].add(kind)
    return salesforce, evidence


def _evidence_label(table: str, kinds: set) -> str:
    """ "Visit Form" or "Attendance" once the table's form is uploaded; the
    kinds that were uploaded when it is some other evidence, so the cell is
    never "No Evidence Uploaded" over a file that is there; else blank."""
    if not kinds:
        return ""
    expected, label = EXPECTED_EVIDENCE[table]
    if expected in kinds:
        return label
    from apps.core.enums import EvidenceKind

    names = []
    for kind in sorted(kinds):
        try:
            names.append(EvidenceKind(kind).label)
        except ValueError:
            names.append(kind.replace("_", " ").capitalize())
    return ", ".join(names)


def team_week_activity(user, activity_id: str):
    """This Lead's officer's activity by id, if the week may send its officer a
    reminder for it; else None.

    The rows Send to is offered on: an officer on this Lead's team delivers it
    themselves, the officer has not completed it, it is not cancelled or
    otherwise released, and it is due by the end of this week — overdue work
    and this week's work, never a plan further ahead.
    """
    if getattr(user, "active_role", "") != "Program Lead":
        return None
    from apps.hr.team_roster import team_members

    team_ids: list[str] = []
    for member in team_members(user):
        team_ids.append(member.id)
        if member.user_id:
            team_ids.append(member.user_id)
    if not team_ids:
        return None
    week_end = monday_of(timezone.localdate()) + timedelta(days=6)
    return (
        Activity.objects.filter(
            id=activity_id,
            deleted_at__isnull=True,
            responsible_staff_id__in=team_ids,
        )
        .exclude(delivery_type="partner")
        .exclude(
            status__in=(
                *CLOSED_STATUSES,
                *AWAITING_LEAD_STATUSES,
                *RELEASED_STATUSES,
            )
        )
        .filter(
            Q(planned_date__lte=week_end)
            | Q(planned_date__isnull=True, scheduled_date__date__lte=week_end)
        )
        .select_related("school", "cluster")
        .first()
    )


# ── The week ─────────────────────────────────────────────────────────────────
class PLWeek:
    """Everything the This Week view draws, for one lead, week and tab."""

    def __init__(
        self,
        user,
        *,
        fy: str,
        who: str = "",
        week=None,
        today=None,
        listing: str = "",
    ):
        from apps.analytics.pl_dashboard_service import DashboardContext

        self.user = user
        self.fy = fy
        self.listing = (listing or "").strip()
        self.today = today or timezone.localdate()
        self.start = resolve_week(week, self.today)
        self.end = self.start + timedelta(days=6)
        self.previous_start = self.start - timedelta(days=7)
        self.ctx = DashboardContext(user, fy, today=self.today)
        self.people = self._people()
        keys = {p["key"] for p in self.people}
        who = (who or "").strip()
        self.who = who if who in keys or who == PARTNERS else EVERYONE

    # ── Who ──────────────────────────────────────────────────────────────────
    def _people(self) -> list[dict]:
        """You first, then your officers by name. Each person carries both of
        the identifier spaces an activity's owner can be stamped in."""
        user = self.user
        me_ids = {i for i in (user.id, getattr(user, "staff_profile_id", None)) if i}
        people = [
            {
                "key": ME,
                "name": "You",
                "full_name": user.name,
                "first_name": "You",
                "staff_id": getattr(user, "staff_profile_id", None),
                "ids": me_ids,
                "is_me": True,
            }
        ]
        for officer in self.ctx.team:
            ids = {officer["staff_id"]}
            if officer.get("user_id"):
                ids.add(officer["user_id"])
            name = officer.get("name") or "CCEO"
            people.append(
                {
                    "key": officer["staff_id"],
                    "name": name,
                    "full_name": name,
                    "first_name": name.split()[0],
                    "staff_id": officer["staff_id"],
                    "ids": ids,
                    "is_me": False,
                }
            )
        return people

    # ── Reads ────────────────────────────────────────────────────────────────
    def _activities(self) -> list:
        """Both weeks' own-delivered work for everyone on the page, one query."""
        owner_ids = {i for p in self.people for i in p["ids"]}
        if not owner_ids:
            return []
        return list(
            Activity.objects.filter(
                deleted_at__isnull=True, responsible_staff_id__in=owner_ids
            )
            .exclude(delivery_type="partner")
            .exclude(status__in=RELEASED_STATUSES)
            .filter(_dated_between(self.previous_start, self.end))
            .select_related(
                "school",
                "school__district",
                "cluster",
                "cluster__district",
                "event_district",
            )
            .order_by("planned_date", "scheduled_date", "id")
        )

    def _leave(self) -> dict[str, list[tuple[date, date]]]:
        """Approved leave overlapping the week, by StaffProfile id. Leave dates
        are stored as text, so they are read in Python rather than compared
        as strings in the database."""
        from apps.accounts.models import Leave

        staff_ids = [p["staff_id"] for p in self.people if p["staff_id"]]
        if not staff_ids:
            return {}
        out: dict[str, list[tuple[date, date]]] = defaultdict(list)
        for leave in Leave.objects.filter(
            staff_id__in=staff_ids,
            status="approved",
            end_date__gte=self.start.isoformat(),
        ):
            try:
                begins = date.fromisoformat(str(leave.start_date)[:10])
                ends = date.fromisoformat(str(leave.end_date)[:10])
            except ValueError:
                continue
            if begins <= self.end and ends >= self.start:
                out[leave.staff_id].append((begins, ends))
        return out

    # ── Build ────────────────────────────────────────────────────────────────
    def build(self) -> dict:
        activities = self._activities()
        owner_of = {i: p["key"] for p in self.people for i in p["ids"]}

        this_week: dict[str, list[dict]] = defaultdict(list)
        overdue: dict[str, list[dict]] = defaultdict(list)
        for activity in activities:
            key = owner_of.get(activity.responsible_staff_id)
            if key is None:
                continue
            row = _row(activity, self.today)
            day = row["day"]
            if day and day >= self.start:
                this_week[key].append(row)
            elif row["open"] and day and day < self.today:
                # Last week's work that is not verified or with IA: still the
                # officer's to complete, or the lead's to verify.
                overdue[key].append(row)

        leave = self._leave()
        days = [self.start + timedelta(days=i) for i in range(7)]
        weekend_used = any(
            r["day"] and r["day"].weekday() >= 5
            for rows in this_week.values()
            for r in rows
        )
        shown_days = days if weekend_used else days[:5]

        people = []
        for person in self.people:
            rows = this_week.get(person["key"], [])
            late = overdue.get(person["key"], [])
            spans = leave.get(person["staff_id"], [])
            behind = sum(1 for r in rows if r["behind"])
            awaiting = sum(1 for r in rows if r["awaiting_you"])
            people.append(
                {
                    **{k: v for k, v in person.items() if k != "ids"},
                    "url": self.url(who=person["key"]),
                    "query": self.query(who=person["key"]),
                    "overdue_query": self.query(who=person["key"], listing=OVERDUE),
                    "overdue_count": len(late),
                    "planned": len(rows),
                    "done": sum(1 for r in rows if r["done"]),
                    "closed": sum(1 for r in rows if not r["open"]),
                    "behind": behind,
                    "awaiting_you": awaiting,
                    # What asks the lead to act: last week's open work, and
                    # this week's that is behind or waiting on verification.
                    "needs_you": 0
                    if person["is_me"]
                    else len(late) + behind + awaiting,
                    "cells": [
                        {
                            "day": day,
                            "rows": [r for r in rows if r["day"] == day],
                            "on_leave": any(b <= day <= e for b, e in spans),
                            "is_today": day == self.today,
                        }
                        for day in shown_days
                    ],
                }
            )

        is_current = self.start == monday_of(self.today)
        data = {
            "who": self.who,
            "fy": self.fy,
            "start": self.start,
            "end": self.end,
            "today": self.today,
            "is_current": is_current,
            "is_past": self.end < self.today,
            "range_label": self.range_label(),
            "previous_url": self.url(who=self.who, week=self.start - timedelta(days=7)),
            "next_url": self.url(who=self.who, week=self.start + timedelta(days=7)),
            "previous_query": self.query(
                who=self.who, week=self.start - timedelta(days=7)
            ),
            "next_query": self.query(who=self.who, week=self.start + timedelta(days=7)),
            "current_query": self.query(who=self.who, week=monday_of(self.today)),
            "days": [
                {
                    "date": d,
                    "label": f"{d:%a}",
                    "number": f"{d:%-d %b}",
                    "is_today": d == self.today,
                }
                for d in shown_days
            ],
            "people": people,
            "tabs": self.tabs(people),
            "overdue_total": sum(len(rows) for rows in overdue.values()),
            "previous_label": f"week of {self.previous_start:%-d %b}",
            "overdue_label": (
                "Overdue from last week"
                if is_current
                else f"Overdue from the week of {self.previous_start:%-d %b}"
            ),
            "rows_per_page": ROWS_PER_PAGE,
        }
        if self.who == PARTNERS:
            data["partners"] = self.partners()
        elif self.who != EVERYONE:
            person = next(p for p in people if p["key"] == self.who)
            data["person"] = self.person(
                person,
                week_rows=this_week.get(self.who, []),
                overdue_rows=overdue.get(self.who, []),
                spans=leave.get(person["staff_id"], []),
                overdue_label=data["overdue_label"],
            )
        return data

    def person(self, person, *, week_rows, overdue_rows, spans, overdue_label) -> dict:
        """One person's tab: Overdue and Due this week, each as the three
        tables. Opens on Overdue while there is any, else on the week."""
        # Completed work leaves the lists: verified, or with Impact
        # Assessment, there is nothing left to follow up.
        week_rows = [r for r in week_rows if r["open"]]
        lists = {OVERDUE: overdue_rows, DUE_THIS_WEEK: week_rows}
        chosen = self.listing if self.listing in lists else ""
        if not chosen:
            chosen = OVERDUE if overdue_rows else DUE_THIS_WEEK
        rows = lists[chosen]
        own_ids = self.ctx.own_ids
        send_until = monday_of(timezone.localdate()) + timedelta(days=6)

        def build(ids):
            return table_rows(
                ids, own_ids=own_ids, today=self.today, send_until=send_until
            )

        tables = []
        for key, title in TABLES:
            ids = [r["id"] for r in rows if r["table"] == key]
            tables.append(
                {
                    "key": key,
                    "title": title,
                    "rows": PastDueRows(ids, build),
                    "count": len(ids),
                    "page_param": f"wk_{key}_page",
                }
            )
        return {
            **person,
            "listing": chosen,
            "listing_is_overdue": chosen == OVERDUE,
            "lists": [
                {
                    "key": OVERDUE,
                    "label": overdue_label,
                    "count": len(overdue_rows),
                    "query": self.query(who=person["key"], listing=OVERDUE),
                    "active": chosen == OVERDUE,
                },
                {
                    "key": DUE_THIS_WEEK,
                    "label": "Due this week",
                    "count": len(week_rows),
                    "query": self.query(who=person["key"], listing=DUE_THIS_WEEK),
                    "active": chosen == DUE_THIS_WEEK,
                },
            ],
            "tables": tables,
            "send_name": "" if person["is_me"] else person["first_name"],
            "leave": [
                f"{max(b, self.start):%a %-d %b} – {min(e, self.end):%a %-d %b}"
                for b, e in spans
            ],
        }

    # ── Partners ─────────────────────────────────────────────────────────────
    def partners(self) -> dict:
        """Partner work the lead's team monitors: what was dated this week and
        where it stands, then what is still late from before it — exceptions
        first, one partner at a time, as Partner Monitoring reads them."""
        from apps.core.fy import get_operational_fy
        from apps.planning import partner_oversight_service as oversight

        first = get_operational_fy(self.start)
        years = (str(int(first) - 1), first, get_operational_fy(self.end))
        try:
            items = oversight.build_items(self.user, fy=first, fys=years)
        except Exception:  # noqa: BLE001 - the tab shows its empty state
            logger.exception("Programme Lead week: partner items failed")
            return {"groups": [], "failed": True, **_partner_totals([])}

        rows = []
        for item in items:
            row = _partner_row(item, self.start, self.end, self.today)
            if row is not None:
                rows.append(row)

        groups: dict[str, dict] = {}
        for row in rows:
            group = groups.setdefault(
                row["partner_id"] or row["partner_name"],
                {
                    "partner_id": row["partner_id"],
                    "partner_name": row["partner_name"],
                    "url": "/partner-oversight/?"
                    + urlencode({"partner": row["partner_id"]})
                    if row["partner_id"]
                    else "/partner-oversight/",
                    "rows": [],
                },
            )
            group["rows"].append(row)
        ordered = []
        for group in groups.values():
            group["rows"].sort(key=lambda r: (r["rank"], r["date"] or self.start))
            group.update(_partner_totals(group["rows"]))
            # Keyed on the partner, not the position, so a page link still
            # pages the same partner after the order changes.
            group["page_param"] = f"partner_{group['partner_id'] or 'other'}_page"
            ordered.append(group)
        ordered.sort(key=lambda g: (-g["exceptions"], g["partner_name"].lower()))
        return {"groups": ordered, "failed": False, **_partner_totals(rows)}

    # ── Links ────────────────────────────────────────────────────────────────
    def query(self, *, who: str, week: date | None = None, listing: str = "") -> str:
        """The dashboard query string for a tab, a list or a week. Templates
        write "/dashboard?{{ …query }}", so every link names its route."""
        query = {"fy": self.fy, "view": "week"}
        week = week or self.start
        if week != monday_of(self.today):
            query["week"] = week.isoformat()
        if who and who != EVERYONE:
            query["who"] = who
        if listing:
            query["list"] = listing
        return urlencode(query)

    def url(self, *, who: str, week: date | None = None, listing: str = "") -> str:
        return f"/dashboard?{self.query(who=who, week=week, listing=listing)}"

    def tabs(self, people: list[dict]) -> list[dict]:
        tabs = [
            {
                "key": EVERYONE,
                "label": "Everyone",
                "count": None,
                "query": self.query(who=EVERYONE),
            }
        ]
        for person in people:
            tabs.append(
                {
                    "key": person["key"],
                    "label": "Me" if person["is_me"] else person["name"],
                    # What waits on the lead is the reason to open a tab.
                    "count": person["needs_you"] or None,
                    "query": person["query"],
                }
            )
        tabs.append(
            {
                "key": PARTNERS,
                "label": "Partners",
                "count": None,
                "query": self.query(who=PARTNERS),
            }
        )
        for tab in tabs:
            tab["active"] = tab["key"] == self.who
        return tabs

    def range_label(self) -> str:
        if self.start.month == self.end.month:
            return f"{self.start:%-d}–{self.end:%-d %B %Y}"
        if self.start.year == self.end.year:
            return f"{self.start:%-d %b} – {self.end:%-d %b %Y}"
        return f"{self.start:%-d %b %Y} – {self.end:%-d %b %Y}"


# ── Partner rows ─────────────────────────────────────────────────────────────
#: Exceptions first, then what is under way, then what the partner did, and
#: what is still to come last: the week is reviewed for what happened.
_PARTNER_RANK = {
    "late_before": 0,
    "not_delivered": 1,
    "started": 2,
    "today": 3,
    "done": 4,
    "upcoming": 5,
}


def _partner_row(item, start: date, end: date, today: date) -> dict | None:
    """One partner item as this week's page reads it, or None when it neither
    falls in the week nor is still late from before it."""
    risks = {risk.get("key") for risk in (item.risks or [])}
    day = item.scheduled_date if item.is_scheduled else None
    if day and start <= day <= end:
        status = item.execution_status
        if status == "Evidence Submitted":
            verified = item.ia_status_label == "Verified"
            state, label, tone = (
                "done",
                "Verified" if verified else "Evidence submitted",
                "success",
            )
        elif status == "In Progress":
            state, label, tone = "started", "In progress", "warning"
        elif day < today:
            state, label, tone = "not_delivered", "Not delivered", "danger"
        elif day == today:
            state, label, tone = "today", "Today", "info"
        else:
            state, label, tone = "upcoming", "Upcoming", "neutral"
    elif day and day < start and "partner_delivery_overdue" in risks:
        state, label, tone = "late_before", f"Late since {day:%-d %b}", "danger"
    elif not day and "partner_schedule_overdue" in risks and item.schedule_by_date:
        if item.schedule_by_date >= start:
            return None
        state, label, tone = (
            "late_before",
            f"Not scheduled, due {item.schedule_by_date:%-d %b}",
            "danger",
        )
    else:
        return None
    from apps.core.enums import ActivityType
    from apps.planning.partner_oversight_service import choice_label

    return {
        "partner_id": item.partner_id or "",
        "partner_name": item.partner_name or "Partner",
        "date": day or item.schedule_by_date,
        "date_label": _day_label(day or item.schedule_by_date),
        "where": item.school_name or item.cluster_name or "No place recorded",
        "district": item.district,
        "activity": item.training_name
        or choice_label(item.activity_type, ActivityType)
        or "Partner work",
        "officer": item.responsible_cceo_name,
        "state": state,
        "state_label": label,
        "tone": tone,
        "rank": _PARTNER_RANK[state],
        "next_action": item.next_action,
        "assignment_id": item.partner_assignment_id or "",
    }


def _partner_totals(rows: list[dict]) -> dict:
    count = defaultdict(int)
    for row in rows:
        count[row["state"]] += 1
    return {
        "done": count["done"],
        "started": count["started"],
        "not_delivered": count["not_delivered"],
        "late_before": count["late_before"],
        "upcoming": count["upcoming"] + count["today"],
        "exceptions": count["not_delivered"] + count["late_before"],
        "total": len(rows),
    }


def build_week(
    user, *, fy: str, who: str = "", week=None, today=None, listing: str = ""
) -> dict:
    return PLWeek(user, fy=fy, who=who, week=week, today=today, listing=listing).build()
