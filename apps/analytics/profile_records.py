"""Profile records: the records a figure of a profile opens.

Owner's brief, 2026-10-10: "Every number must be traceable. There must be
zero orphan KPIs ... The user must always be able to go: Summary → Breakdown
→ Actual Records", and "Every number is a live, traceable summary of
authoritative records — not a decorative KPI."

`profile_intelligence.build` makes the summary and its breakdowns (by
sub-region, district, sub-county, cluster, school). This module is the third
layer: `records(profile, what)` lists the activities, register lines, SSA
records, stories, results, hand-overs and loans a figure counted, read with
the same filters the figure was counted with, so the list's length (or its
total line) is the figure.

It also holds the operational reads a profile shows in full rather than as
one number: training by channel (`channels`: in-school, group and online,
each kept apart — "Online training attendance must be treated as a
first-class training channel"), cluster meetings (`meetings`) and change
stories (`stories`).

Nothing here is stored. A list is paged where it is read: a table of rows is
a lazy sequence (`Rows`) over its queryset, so a country's visits cost one
COUNT and one page.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from django.db.models import Count, Q, Sum

from apps.analytics import profile_intelligence as engine
from apps.core.activity_types import (
    COMPLETED_WORK_STATUSES,
    NOT_STARTED_ACTIVITY_STATUSES,
)

__all__ = [
    "RECORDS",
    "Rows",
    "channels",
    "focus_work",
    "identity",
    "meetings",
    "records",
    "stories",
]

ONLINE = "online"


class Rows(Sequence):
    """A queryset read a page at a time, each row made by ``make``."""

    def __init__(self, queryset, make, *, batch=None):
        self._queryset = queryset
        self._make = make
        #: ``batch(page of raw rows)`` → whatever ``make`` needs beside a row
        #: (names looked up once for the page, never once per row).
        self._batch = batch
        self._count = None

    def __len__(self) -> int:
        if self._count is None:
            self._count = self._queryset.count()
        return self._count

    def __getitem__(self, index):
        if isinstance(index, slice):
            page = list(self._queryset[index])
            extra = self._batch(page) if self._batch else None
            return [self._make(row, extra) for row in page]
        row = self._queryset[index]
        return self._make(row, self._batch([row]) if self._batch else None)


def cell(value, href: str = "", tone: str = "", kind: str = "") -> dict:
    """One cell of a record table. ``kind`` is "num", "date" or "" (text); a
    missing count is 0 and a missing text a dash, said in the template."""
    if not kind and isinstance(value, (int, float)) and not isinstance(value, bool):
        kind = "num"
    return {"value": value, "href": href, "tone": tone, "kind": kind}


def _table(key, title, caption, columns, rows, *, footer="", total=None) -> dict:
    return {
        "key": key,
        "title": title,
        "caption": caption,
        "columns": columns,
        "rows": rows,
        "footer": footer,
        #: A closing line of sums, where the figure is a sum and not a count.
        "total": total,
    }


def _day(activity: dict):
    scheduled = activity.get("scheduled_date")
    return (
        activity.get("actual_delivery_date")
        or activity.get("planned_date")
        or (scheduled.date() if scheduled else None)
    )


def _status(value: str) -> str:
    return str(value or "").replace("_", " ").capitalize()


def _type_label(value: str) -> str:
    from apps.core.enums import ActivityType

    return dict(ActivityType.choices).get(value, _status(value))


# ── Work: visits, trainings, meetings ───────────────────────────────────────
_WORK_FIELDS = (
    "id",
    "activity_type",
    "programme_delivery_mode",
    "status",
    "planned_date",
    "scheduled_date",
    "actual_delivery_date",
    "school_id",
    "school__name",
    "school__school_id",
    "cluster_id",
    "cluster__name",
    "delivery_type",
    "responsible_staff_id",
    "assigned_partner_id",
    "teachers_attended",
    "leaders_attended",
    "focus_intervention",
    "training_course__display_name",
)


def _work(profile: dict):
    scope = profile["scope"]
    cluster_ids = [row["id"] for row in profile["clusters"]]
    window = engine.period_window(profile["fy"], profile["period"])
    return engine._activities(scope, cluster_ids, profile["fy"], window)


def _people_names(page) -> dict:
    from apps.accounts.models import StaffProfile
    from apps.partners.models import Partner

    staff_ids = {row["responsible_staff_id"] for row in page} - {None, ""}
    partner_ids = {row["assigned_partner_id"] for row in page} - {None, ""}
    names: dict[str, str] = {}
    if staff_ids:
        for pk, user_id, name, email in StaffProfile.objects.filter(
            Q(id__in=staff_ids) | Q(user_id__in=staff_ids)
        ).values_list("id", "user_id", "user__name", "user__email"):
            names[pk] = names[user_id] = name or email or ""
    if partner_ids:
        names.update(
            Partner.objects.filter(id__in=partner_ids).values_list("id", "name")
        )
    return names


_WORK_COLUMNS = (
    ("Date", "date"),
    ("Activity", ""),
    ("School ID", ""),
    ("School / Cluster", ""),
    ("Delivered By", ""),
    ("Status", ""),
)


def _work_row(row: dict, names: dict) -> list[dict]:
    by = names.get(row["assigned_partner_id"] or "") or names.get(
        row["responsible_staff_id"] or "", ""
    )
    label = row["training_course__display_name"] or _type_label(row["activity_type"])
    if row["programme_delivery_mode"] == ONLINE:
        label = f"{label} (online)"
    done = row["status"] in COMPLETED_WORK_STATUSES
    if row["school_id"]:
        place = cell(row["school__name"], f"/schools/{row['school_id']}")
    elif row["cluster_id"]:
        place = cell(row["cluster__name"], f"/clusters/{row['cluster_id']}")
    else:
        place = cell("")
    return [
        cell(_day(row), kind="date"),
        cell(label, f"/activities/{row['id']}"),
        cell(row["school__school_id"] or ""),
        place,
        cell(by),
        cell(_status(row["status"]), tone="success" if done else ""),
    ]


def _work_table(key, title, caption, queryset) -> dict:
    rows = Rows(
        queryset.values(*_WORK_FIELDS).order_by(
            "-planned_date", "-scheduled_date", "id"
        ),
        _work_row,
        batch=_people_names,
    )
    return _table(key, title, caption, _WORK_COLUMNS, rows)


def _today():
    from django.utils import timezone

    return timezone.localdate()


def _past():
    today = _today()
    return Q(planned_date__lt=today) | Q(
        planned_date__isnull=True, scheduled_date__date__lt=today
    )


_DONE = Q(status__in=COMPLETED_WORK_STATUSES)
_WAITING = Q(status__in=NOT_STARTED_ACTIVITY_STATUSES)
_IN_SCHOOL = Q(school_id__isnull=False)
_GROUP = Q(school__isnull=True)
_ONLINE = Q(programme_delivery_mode=ONLINE)


def _work_kinds() -> dict:
    """``what`` → (title, the home tab, the filter on the scope's work)."""
    visit = Q(activity_type__in=engine._VISITS)
    training = Q(activity_type__in=engine._TRAININGS)
    meeting = Q(activity_type__in=engine._MEETINGS)
    return {
        "visits": ("School visits in the plan", visit),
        "visits_done": ("School visits completed", visit & _DONE),
        "visits_overdue": ("School visits past their date", visit & _WAITING & _past()),
        "trainings": ("Trainings in the plan", training),
        "trainings_done": ("Trainings completed", training & _DONE),
        "trainings_in_school": (
            "In-school trainings in the plan",
            training & _IN_SCHOOL & ~_ONLINE,
        ),
        "trainings_in_school_done": (
            "In-school trainings completed",
            training & _IN_SCHOOL & ~_ONLINE & _DONE,
        ),
        "trainings_partner": (
            "In-school trainings dated by a partner",
            training & _IN_SCHOOL & ~_ONLINE & Q(delivery_type="partner"),
        ),
        "trainings_group": (
            "Group trainings in the plan",
            training & _GROUP & ~_ONLINE,
        ),
        "trainings_group_done": (
            "Group trainings completed",
            training & _GROUP & ~_ONLINE & _DONE,
        ),
        "trainings_online": ("Online trainings in the plan", training & _ONLINE),
        "trainings_online_done": (
            "Online trainings completed",
            training & _ONLINE & _DONE,
        ),
        "meetings": ("Cluster meetings in the plan", meeting),
        "meetings_done": ("Cluster meetings held", meeting & _DONE),
        "meetings_upcoming": (
            "Cluster meetings still to come",
            meeting & _WAITING & ~_past(),
        ),
        "meetings_overdue": (
            "Cluster meetings past their date",
            meeting & _WAITING & _past(),
        ),
    }


# ── People trained: the register behind the figure ──────────────────────────
def _trained_tables(profile: dict, types, key: str, title: str) -> list[dict]:
    """The completed sessions that recorded teachers or school leaders for
    the scope's schools: a school's own trainings, and the register lines of
    group sessions. The two totals added are the figure."""
    from apps.activities.models import ClusterActivityAttendance

    scope, fy = profile["scope"], profile["fy"]
    window = engine.period_window(fy, profile["period"])
    own = (
        _work(profile)
        .filter(_DONE, _IN_SCHOOL, activity_type__in=types)
        .values(*_WORK_FIELDS)
        .order_by("-planned_date", "id")
    )
    own_total = own.aggregate(t=Sum("teachers_attended"), n=Sum("leaders_attended"))
    register = (
        ClusterActivityAttendance.objects.filter(
            school_id__in=scope.schools.values("id"),
            attended=True,
            activity_id__in=engine._sessions(fy, window)
            .filter(activity_type__in=types)
            .values("id"),
        )
        .values(
            "activity_id",
            "activity__activity_type",
            "activity__programme_delivery_mode",
            "activity__training_course__display_name",
            "activity__planned_date",
            "activity__actual_delivery_date",
            "activity__cluster_id",
            "activity__cluster__name",
            "school_id",
            "school__name",
            "school__school_id",
            "teachers",
            "leaders",
        )
        .order_by("-activity__planned_date", "school__name", "id")
    )
    register_total = register.aggregate(t=Sum("teachers"), n=Sum("leaders"))

    def own_row(row, _extra):
        return [
            cell(_day(row), kind="date"),
            cell(
                row["training_course__display_name"]
                or _type_label(row["activity_type"]),
                f"/activities/{row['id']}",
            ),
            cell(row["school__school_id"] or ""),
            cell(row["school__name"], f"/schools/{row['school_id']}"),
            cell(row["teachers_attended"] or 0),
            cell(row["leaders_attended"] or 0),
        ]

    def register_row(row, _extra):
        label = row["activity__training_course__display_name"] or _type_label(
            row["activity__activity_type"]
        )
        if row["activity__programme_delivery_mode"] == ONLINE:
            label = f"{label} (online)"
        return [
            cell(
                row["activity__actual_delivery_date"] or row["activity__planned_date"],
                kind="date",
            ),
            cell(label, f"/activities/{row['activity_id']}"),
            cell(
                row["activity__cluster__name"] or "",
                f"/clusters/{row['activity__cluster_id']}"
                if row["activity__cluster_id"]
                else "",
            ),
            cell(row["school__school_id"] or ""),
            cell(row["school__name"], f"/schools/{row['school_id']}"),
            cell(row["teachers"] or 0),
            cell(row["leaders"] or 0),
        ]

    tables = []
    if types == engine._TRAININGS:
        tables.append(
            _table(
                f"{key}-in-school",
                f"{title}: in-school trainings",
                "Each completed in-school training at these schools with the "
                "teachers and school leaders recorded on it.",
                (
                    ("Date", "date"),
                    ("Training", ""),
                    ("School ID", ""),
                    ("School", ""),
                    ("Teachers", "num"),
                    ("School Leaders", "num"),
                ),
                Rows(own, own_row),
                total=[
                    "Total",
                    "",
                    "",
                    "",
                    own_total["t"] or 0,
                    own_total["n"] or 0,
                ],
            )
        )
    tables.append(
        _table(
            f"{key}-register",
            f"{title}: the attendance register",
            "Each of these schools recorded as attending a completed session, "
            "with the teachers and school leaders the register holds for it.",
            (
                ("Date", "date"),
                ("Session", ""),
                ("Cluster", ""),
                ("School ID", ""),
                ("School", ""),
                ("Teachers", "num"),
                ("School Leaders", "num"),
            ),
            Rows(register, register_row),
            total=[
                "Total",
                "",
                "",
                "",
                "",
                register_total["t"] or 0,
                register_total["n"] or 0,
            ],
        )
    )
    return tables


# ── Schools: enrolment, growth ──────────────────────────────────────────────
def _school_cells(school: dict) -> list[dict]:
    return [
        cell(school["school_id"] or ""),
        cell(school["name"], f"/schools/{school['id']}"),
    ]


def _enrolment_tables(profile: dict, compared_only: bool) -> list[dict]:
    """Each school's enrolment in the year and in the one before
    (`schools.SchoolEnrollmentHistory`, the figures `clusters.outcomes`
    compares); with ``compared_only`` only the schools with both."""
    from apps.schools.models import SchoolEnrollmentHistory
    from apps.ssa.year_comparison import previous_fy

    fy = profile["fy"]
    before = previous_fy(fy)
    by_school: dict[str, dict[str, int]] = defaultdict(dict)
    for school_id, year, enrolment in (
        SchoolEnrollmentHistory.objects.filter(
            school_id__in=[s["id"] for s in profile["_schools"]],
            fy__in=[y for y in (fy, before) if y],
        )
        .order_by("school_id", "fy", "recorded_at")
        .values_list("school_id", "fy", "enrollment")
    ):
        by_school[school_id][year] = enrolment
    rows = []
    for school in profile["_schools"]:
        years = by_school.get(school["id"], {})
        was, now = years.get(before), years.get(fy)
        if compared_only and (was is None or now is None):
            continue
        change = now - was if was is not None and now is not None else None
        rows.append(
            [
                *_school_cells(school),
                cell(was, kind="opt"),
                cell(now, kind="opt"),
                cell(
                    change,
                    kind="opt",
                    tone="success"
                    if change and change > 0
                    else "danger"
                    if change and change < 0
                    else "",
                ),
                cell(school["enrollment"], kind="opt"),
            ]
        )
    title = "Enrolment growth" if compared_only else "Enrolment"
    return [
        _table(
            "enrolment",
            f"{title}: school by school",
            "Each school's recorded enrolment in the year before and in this "
            "year, the change, and the enrolment on its profile today.",
            (
                ("School ID", ""),
                ("School", ""),
                (profile["previous_label"], "num"),
                (profile["fy_label"], "num"),
                ("Change", "num"),
                ("On Profile", "num"),
            ),
            rows,
            footer="A school is compared only with a figure recorded in both "
            "years. On Profile is the enrolment the school's record holds now; "
            "the profile's Enrolment figure is these added up.",
        )
    ]


# ── Learning results ────────────────────────────────────────────────────────
def _learning_tables(profile: dict) -> list[dict]:
    from apps.impact.models import LearningAssessmentResult
    from apps.ssa.year_comparison import previous_fy

    fy = profile["fy"]
    results = (
        LearningAssessmentResult.objects.filter(
            school_id__in=profile["scope"].schools.values("id"),
            fy__in=[y for y in (fy, previous_fy(fy)) if y],
            deleted_at__isnull=True,
        )
        .values(
            "id",
            "school_id",
            "school__name",
            "school__school_id",
            "fy",
            "assessed_on",
            "assessment_type",
            "subject",
            "grade_level",
            "learners_tested",
            "mean_score",
            "max_score",
            "verification_status",
        )
        .order_by("-assessed_on", "school__name", "id")
    )

    def make(row, _extra):
        share = None
        if row["mean_score"] is not None and row["max_score"]:
            share = round(float(row["mean_score"]) * 100 / float(row["max_score"]), 1)
        return [
            cell(row["assessed_on"], kind="date"),
            cell(row["school__school_id"] or ""),
            cell(row["school__name"], f"/schools/{row['school_id']}"),
            cell(_status(row["assessment_type"])),
            cell(" · ".join(x for x in (row["subject"], row["grade_level"]) if x)),
            cell(row["learners_tested"], kind="opt"),
            cell(f"{share}%" if share is not None else "", kind="opt"),
            cell(_status(row["verification_status"])),
        ]

    return [
        _table(
            "learning",
            "Learning results: the assessments",
            "Each learning assessment recorded for these schools in this year "
            "and the year before.",
            (
                ("Date", "date"),
                ("School ID", ""),
                ("School", ""),
                ("Assessment", ""),
                ("Subject · Class", ""),
                ("Learners Tested", "num"),
                ("Mean Score", "num"),
                ("Verification", ""),
            ),
            Rows(results, make),
            footer="The profile's figure reads confirmed results only, and "
            "compares a school only when it has them in both years.",
        )
    ]


# ── SSA ─────────────────────────────────────────────────────────────────────
def _ssa_tables(profile: dict) -> list[dict]:
    from apps.ssa.current_year import CURRENT_SSA_STATUSES
    from apps.ssa.models import SsaRecord

    records = (
        SsaRecord.objects.filter(
            school_id__in=profile["scope"].schools.values("id"),
            fy=profile["fy"],
            deleted_at__isnull=True,
            verification_status__in=CURRENT_SSA_STATUSES,
        )
        .values(
            "id",
            "school_id",
            "school__name",
            "school__school_id",
            "date_of_ssa",
            "average_score",
            "verification_status",
            "collector_type",
        )
        .order_by("-date_of_ssa", "school__name", "id")
    )

    def make(row, _extra):
        score = profile["_scores"].get(row["school_id"], {})
        return [
            cell(row["date_of_ssa"], kind="date"),
            cell(row["school__school_id"] or ""),
            cell(row["school__name"], f"/schools/{row['school_id']}?tab=ssa"),
            cell(row["average_score"], kind="score"),
            cell(score.get("previous"), kind="score"),
            cell(_status(row["verification_status"])),
            cell(_status(row["collector_type"])),
        ]

    return [
        _table(
            "ssa",
            f"Confirmed SSA records, {profile['fy_label']}",
            "Every confirmed SSA record of these schools in the year. A "
            "school's score for the year is its latest one.",
            (
                ("Date Of SSA", "date"),
                ("School ID", ""),
                ("School", ""),
                ("Average Score", "num"),
                (f"Previous ({profile['previous_label']})", "num"),
                ("Verification", ""),
                ("Collected By", ""),
            ),
            Rows(records, make),
            footer="The profile's average is the mean of each school's latest "
            "confirmed record of the year, so a school assessed twice counts "
            "once.",
        )
    ]


def _intervention_tables(profile: dict, key: str) -> list[dict]:
    """One intervention: each school's baseline, this year's score and the
    change, then the year's work that named it as its focus."""
    from apps.core.enums import SsaIntervention
    from apps.ssa import year_comparison
    from apps.ssa.change_rules import RuleBook

    labels = dict(SsaIntervention.choices)
    if key not in labels:
        return []
    by_school = year_comparison.school_intervention_scores(
        profile["scope"].schools.values("id"), profile["fy"], key
    )
    book = RuleBook()
    rows = []
    for school in profile["_schools"]:
        score = by_school.get(school["id"])
        if not score:
            continue
        verdict = engine._change(
            score["previous"], score["current"], book=book, intervention=key
        )
        rows.append(
            [
                *_school_cells(school),
                cell(score["previous"], kind="score"),
                cell(score["current"], kind="score"),
                cell(verdict["change"], kind="change", tone=verdict["tone"]),
                cell(verdict["status_label"]),
            ]
        )
    focus = _work(profile).filter(
        Q(focus_intervention=key) | Q(purpose_intervention=key)
    )
    return [
        _table(
            "intervention-schools",
            f"{labels[key]}: school by school",
            f"Each school's confirmed {labels[key]} score in the previous year "
            "and in this year, the change and what the change is called.",
            (
                ("School ID", ""),
                ("School", ""),
                (f"Previous ({profile['previous_label']})", "num"),
                (f"Current ({profile['fy_label']})", "num"),
                ("Change", "num"),
                ("Status", ""),
            ),
            rows,
            footer="A school with no confirmed score for this intervention in "
            "either year is not listed.",
        ),
        _work_table(
            "intervention-work",
            f"{labels[key]}: the work that named it",
            "The year's visits, trainings and meetings in this portfolio whose "
            f"focus is {labels[key]}.",
            focus,
        ),
    ]


# ── Stories ─────────────────────────────────────────────────────────────────
def _story_queryset(profile: dict):
    from apps.core.fy import get_fy_date_range
    from apps.targets.models import MostSignificantChangeStory, MSCSStatus

    cluster_ids = [row["id"] for row in profile["clusters"]]
    start, end = get_fy_date_range(str(profile["fy"]))
    return (
        MostSignificantChangeStory.objects.filter(
            Q(school_id__in=profile["scope"].schools.values("id"))
            | Q(school__isnull=True, cluster_id__in=cluster_ids),
            story_date__gte=start.date(),
            story_date__lt=end.date(),
        )
        # A draft is its author's own.
        .exclude(status=MSCSStatus.DRAFT)
    )


def stories(profile: dict) -> dict:
    """Most Significant Change stories about the scope's schools and clusters
    in the year: how many, how many approved (the only ones that count as
    evidence), those still with a reviewer, by intervention, and the latest.
    Two queries."""
    from apps.core.enums import SsaIntervention
    from apps.targets.models import MSCSStatus

    queryset = _story_queryset(profile)
    counts = queryset.aggregate(
        total=Count("id"),
        approved=Count("id", filter=Q(status=MSCSStatus.APPROVED)),
        waiting=Count(
            "id", filter=Q(status__in=[MSCSStatus.SUBMITTED, MSCSStatus.RETURNED])
        ),
        schools=Count("school_id", distinct=True),
    )
    labels = dict(SsaIntervention.choices)
    latest = list(
        queryset.values(
            "id", "title", "story_date", "status", "intervention", "school__name"
        ).order_by("-story_date", "-created_at")[:5]
    )
    by_area: dict[str, int] = defaultdict(int)
    for row in queryset.values_list("intervention").annotate(n=Count("id")):
        by_area[labels.get(row[0], "No intervention tagged")] += row[1]
    for row in latest:
        row["status_label"] = _status(row["status"])
        row["area"] = labels.get(row["intervention"], "")
    return {
        **counts,
        "latest": latest,
        "areas": sorted(by_area.items(), key=lambda item: (-item[1], item[0])),
    }


def _story_tables(profile: dict, approved_only: bool) -> list[dict]:
    from apps.core.enums import SsaIntervention
    from apps.targets.models import MSCSStatus

    labels = dict(SsaIntervention.choices)
    queryset = _story_queryset(profile)
    if approved_only:
        queryset = queryset.filter(status=MSCSStatus.APPROVED)
    queryset = queryset.values(
        "id",
        "title",
        "story_date",
        "status",
        "intervention",
        "outcome_area",
        "school_id",
        "school__name",
        "school__school_id",
        "evidence_uri",
    ).order_by("-story_date", "-created_at", "id")

    def make(row, _extra):
        return [
            cell(row["story_date"], kind="date"),
            cell(row["title"]),
            cell(row["school__school_id"] or ""),
            cell(
                row["school__name"] or "",
                f"/schools/{row['school_id']}" if row["school_id"] else "",
            ),
            cell(labels.get(row["intervention"], "")),
            cell(_status(row["outcome_area"])),
            cell(
                _status(row["status"]),
                tone="success" if row["status"] == MSCSStatus.APPROVED else "",
            ),
            cell("Yes" if row["evidence_uri"] else "No"),
        ]

    return [
        _table(
            "stories",
            "Most Significant Change stories" + (": approved" if approved_only else ""),
            "Stories written about these schools and clusters in the year, "
            "newest first. A draft is its author's own and is not listed.",
            (
                ("Story Date", "date"),
                ("Title", ""),
                ("School ID", ""),
                ("School", ""),
                ("Intervention", ""),
                ("Outcome Area", ""),
                ("Status", ""),
                ("Evidence", ""),
            ),
            Rows(queryset, make),
            footer="Only an approved story counts as evidence.",
        )
    ]


# ── Hand-overs ──────────────────────────────────────────────────────────────
def _handover_queryset(profile: dict):
    from apps.partners.models import PartnerAssignment

    scope = profile["scope"]
    handovers = PartnerAssignment.objects.filter(
        school_id__in=scope.schools.values("id")
    ).exclude(status__in=PartnerAssignment.RELEASED_STATUSES)
    if scope.partner_id:
        handovers = handovers.filter(partner_id=scope.partner_id)
    return handovers


def _handover_tables(profile: dict, stage: str) -> list[dict]:
    from apps.partners.models import PartnerAssignment

    queryset = _handover_queryset(profile)
    waiting = Q(status__in=PartnerAssignment.UNSCHEDULED_STATUSES)
    completed = Q(status=PartnerAssignment.STATUS_COMPLETED)
    title = "Hand-overs a partner holds"
    if stage == "awaiting":
        queryset, title = queryset.filter(waiting), "Awaiting the partner's date"
    elif stage == "scheduled":
        queryset, title = (
            queryset.exclude(waiting).exclude(completed),
            "Dated by the partner",
        )
    elif stage == "completed":
        queryset, title = queryset.filter(completed), "Completed by the partner"
    queryset = queryset.values(
        "id",
        "school_id",
        "school__name",
        "school__school_id",
        "partner_id",
        "partner__name",
        "expected_activity_type",
        "status",
        "scheduled_date",
        "scheduled_activity_id",
        "created_at",
    ).order_by("-created_at", "id")

    def make(row, _extra):
        return [
            cell(row["created_at"].date() if row["created_at"] else None, kind="date"),
            cell(row["school__school_id"] or ""),
            cell(row["school__name"], f"/schools/{row['school_id']}"),
            cell(row["partner__name"] or "", f"/partners/{row['partner_id']}"),
            cell(_type_label(row["expected_activity_type"] or "")),
            cell(
                row["scheduled_date"],
                f"/activities/{row['scheduled_activity_id']}"
                if row["scheduled_activity_id"]
                else "",
                kind="date",
            ),
            cell(_status(row["status"])),
        ]

    return [
        _table(
            "handovers",
            title,
            "Each hand-over of one of these schools to a partner that has not "
            "been taken back, with where it stands. Assigned is not scheduled "
            "is not completed.",
            (
                ("Assigned On", "date"),
                ("School ID", ""),
                ("School", ""),
                ("Partner", ""),
                ("Work", ""),
                ("Partner's Date", "date"),
                ("Status", ""),
            ),
            Rows(queryset, make),
        )
    ]


# ── Partners, loans ─────────────────────────────────────────────────────────
def _partner_tables(profile: dict) -> list[dict]:
    rows = [
        [
            cell(name or "", f"/partners/{partner_id}"),
            cell(schools),
            cell(handovers),
        ]
        for partner_id, name, schools, handovers in _handover_queryset(profile)
        .values_list("partner_id", "partner__name")
        .annotate(schools=Count("school_id", distinct=True), handovers=Count("id"))
        .order_by("partner__name", "partner_id")
        .values_list("partner_id", "partner__name", "schools", "handovers")
    ]
    return [
        _table(
            "partners",
            "Partners serving these schools",
            "Each partner holding a hand-over at one of these schools, with "
            "the schools and the hand-overs it holds.",
            (("Partner", ""), ("Schools", "num"), ("Hand-overs", "num")),
            rows,
        )
    ]


def _loan_tables(profile: dict, principal) -> list[dict]:
    from apps.clusters import outcomes
    from apps.core.permissions import RolePermissionService

    if principal is None or not RolePermissionService.can_view_page(principal, "loans"):
        return []
    loans = outcomes.loans_by_cluster(
        ["scope"], principal, members={"scope": profile["_schools"]}
    )["scope"]
    rows = [
        [
            cell(row["disbursed_on"], kind="date"),
            cell(row["code"]),
            cell(row["name"], f"/schools/{row['school_pk']}"),
            cell(row["lender"]),
            cell(row["purpose"]),
            cell(row["approved"], kind="money"),
            cell(row["disbursed"], kind="money"),
            cell(row["status_label"], tone=row["tone"]),
        ]
        for row in loans.rows
    ]
    return [
        _table(
            "loans",
            "School loans",
            "Each loan of these schools on the loan register that you may "
            "read, with its lender, purpose and status.",
            (
                ("Disbursed On", "date"),
                ("School ID", ""),
                ("School", ""),
                ("Lender", ""),
                ("Purpose", ""),
                ("Approved", "num"),
                ("Disbursed", "num"),
                ("Status", ""),
            ),
            rows,
        )
    ]


def _case_tables(profile: dict, principal) -> list[dict]:
    from apps.business_transformation.models import TransformationCase
    from apps.core.permissions import RolePermissionService

    if principal is None or not RolePermissionService.can_view_page(principal, "loans"):
        return []
    cases = (
        TransformationCase.objects.filter(
            school_id__in=profile["scope"].schools.values("id"),
            deleted_at__isnull=True,
        )
        .values(
            "id",
            "school_id",
            "school__name",
            "school__school_id",
            "status",
            "created_at",
        )
        .order_by("-created_at", "id")
    )

    def make(row, _extra):
        return [
            cell(row["created_at"].date() if row["created_at"] else None, kind="date"),
            cell(row["school__school_id"] or ""),
            cell(row["school__name"], f"/schools/{row['school_id']}"),
            cell(_status(row["status"])),
        ]

    return [
        _table(
            "cases",
            "Business Transformation cases",
            "Each Business Transformation case of these schools.",
            (("Opened", "date"), ("School ID", ""), ("School", ""), ("Status", "")),
            Rows(cases, make),
        )
    ]


# ── Cluster sessions: Cluster Management's register ─────────────────────────
def _cluster_tables(profile: dict, what: str) -> list[dict]:
    """The sessions the scope's clusters held in the year, and each member
    school's attendance at them — the read the cluster's own profile uses
    (`apps.clusters.profile_insights.attendance_by_cluster`), so a total
    here is the Clusters tab's figure. A cluster's figures are the whole
    cluster's, wherever its schools are."""
    from apps.clusters import profile_insights as insights

    names = {row["id"]: row["name"] for row in profile["clusters"]}
    if not names:
        return []
    attendance = insights.attendance_by_cluster(list(names), fy=profile["fy"])

    def cluster_cell(cluster_id):
        return cell(names.get(cluster_id, ""), f"/clusters/{cluster_id}")

    if what == "cluster_sessions":
        rows = [
            [
                cell(session.held_on, kind="date"),
                cell(session.name, f"/activities/{session.id}"),
                cluster_cell(cluster_id),
                cell(session.invited),
                cell(session.attended),
                cell(
                    f"{session.rate}%" if session.rate is not None else "", kind="opt"
                ),
                cell(session.teachers),
                cell(session.leaders),
            ]
            for cluster_id in names
            for session in attendance[cluster_id]["sessions"]
        ]
        rows.sort(key=lambda r: (r[0]["value"] is None, r[0]["value"]), reverse=True)
        return [
            _table(
                "cluster-sessions",
                "Sessions held",
                "Each cluster meeting and group training these clusters held "
                "in the year, with the schools invited and attending and the "
                "teachers and school leaders recorded.",
                (
                    ("Held On", "date"),
                    ("Session", ""),
                    ("Cluster", ""),
                    ("Schools Invited", "num"),
                    ("Schools Attending", "num"),
                    ("Attendance", "num"),
                    ("Teachers", "num"),
                    ("School Leaders", "num"),
                ),
                rows,
            )
        ]
    schools = [
        (cluster_id, school)
        for cluster_id in names
        for school in attendance[cluster_id]["schools"]
        if what != "cluster_absent" or school.is_drifting
    ]
    rows = [
        [
            cluster_cell(cluster_id),
            cell(school.code),
            cell(school.name, f"/schools/{school.id}"),
            cell(school.invited),
            cell(school.attended),
            cell(f"{school.rate}%" if school.rate is not None else "", kind="opt"),
            cell(school.teachers),
            cell(school.leaders),
            cell(school.last_attended, kind="date"),
            cell(school.standing[0], tone=school.standing[1]),
        ]
        for cluster_id, school in schools
    ]
    absent = what == "cluster_absent"
    return [
        _table(
            "cluster-attendance",
            "Schools absent from sessions in a row"
            if absent
            else "Attendance at cluster sessions, school by school",
            "Each member school of these clusters with the year's sessions it "
            "was invited to and attended, the teachers and school leaders "
            "recorded for it, when it last attended and where it stands.",
            (
                ("Cluster", ""),
                ("School ID", ""),
                ("School", ""),
                ("Invited", "num"),
                ("Attended", "num"),
                ("Attendance", "num"),
                ("Teachers", "num"),
                ("School Leaders", "num"),
                ("Last Attended", "date"),
                ("Standing", ""),
            ),
            rows,
            total=None
            if absent
            else [
                "Total",
                "",
                "",
                sum(school.invited for _c, school in schools),
                sum(school.attended for _c, school in schools),
                "",
                sum(school.teachers for _c, school in schools),
                sum(school.leaders for _c, school in schools),
                "",
                "",
            ],
        )
    ]


# ── The one door ────────────────────────────────────────────────────────────
#: ``what`` → (the tab the figure lives on, what the list is called). The
#: work lists (`_work_kinds`) are added below.
RECORDS = {
    "teachers_trained": ("overview", "Teachers trained"),
    "leaders_trained": ("overview", "School leaders trained"),
    "at_meetings": ("overview", "Teachers and school leaders at cluster meetings"),
    "enrolment": ("overview", "Enrolment"),
    "enrolment_growth": ("overview", "Enrolment growth"),
    "learning": ("overview", "Learning results"),
    "ssa": ("ssa", "Confirmed SSA records"),
    "intervention": ("ssa", "SSA intervention"),
    "stories": ("overview", "Most Significant Change stories"),
    "stories_approved": ("overview", "Approved stories"),
    "handovers": ("overview", "Hand-overs a partner holds"),
    "handovers_awaiting": ("overview", "Awaiting the partner's date"),
    "handovers_scheduled": ("overview", "Dated by the partner"),
    "handovers_completed": ("overview", "Completed by the partner"),
    "partners": ("overview", "Partners"),
    "loans": ("overview", "School loans"),
    "cases": ("overview", "Business Transformation cases"),
    "cluster_sessions": ("clusters", "Sessions held"),
    "cluster_attendance": ("clusters", "Attendance at cluster sessions"),
    "cluster_absent": ("clusters", "Schools absent from sessions in a row"),
    **{key: ("activities", title) for key, (title, _f) in _work_kinds().items()},
}


def records(profile: dict, what: str, *, key: str = "", principal=None) -> list[dict]:
    """The tables of records behind the figure ``what`` of ``profile``
    (`RECORDS`); an empty list for a figure that names none or one the reader
    may not open."""
    work = _work_kinds()
    if what in work:
        title, where = work[what]
        return [
            _work_table(
                what,
                title,
                f"{title} at this portfolio's schools and clusters, "
                f"{profile['fy_label']}"
                + (f", {profile['period_label']}" if profile["period_label"] else "")
                + ". In the plan leaves out work that was cancelled, rejected "
                "or deferred.",
                _work(profile).filter(where),
            )
        ]
    if what in ("teachers_trained", "leaders_trained"):
        return _trained_tables(profile, engine._TRAININGS, what, RECORDS[what][1])
    if what == "at_meetings":
        return _trained_tables(profile, engine._MEETINGS, what, "At cluster meetings")
    if what in ("enrolment", "enrolment_growth"):
        return _enrolment_tables(profile, what == "enrolment_growth")
    if what == "learning":
        return _learning_tables(profile)
    if what == "ssa":
        return _ssa_tables(profile)
    if what == "intervention":
        return _intervention_tables(profile, key)
    if what in ("stories", "stories_approved"):
        return _story_tables(profile, what == "stories_approved")
    if what.startswith("handovers"):
        return _handover_tables(profile, what.partition("_")[2])
    if what == "partners":
        return _partner_tables(profile)
    if what == "loans":
        return _loan_tables(profile, principal)
    if what == "cases":
        return _case_tables(profile, principal)
    if what.startswith("cluster_"):
        return _cluster_tables(profile, what)
    return []


# ── Training by channel ─────────────────────────────────────────────────────
def channels(profile: dict) -> list[dict]:
    """The year's training in the scope by the way it is delivered — at the
    school, to a group, online — each with what is in the plan, what is still
    to come, what is completed and who was recorded there. Online is a
    channel of its own (the brief, 2026-10-10), never folded into group
    training. Three queries."""
    from apps.activities.models import ClusterActivityAttendance

    scope, fy = profile["scope"], profile["fy"]
    window = engine.period_window(fy, profile["period"])
    training = _work(profile).filter(activity_type__in=engine._TRAININGS)
    partner = Q(delivery_type="partner")
    counts = training.aggregate(
        in_school=Count("id", filter=_IN_SCHOOL & ~_ONLINE),
        in_school_staff=Count("id", filter=_IN_SCHOOL & ~_ONLINE & ~partner),
        in_school_partner=Count("id", filter=_IN_SCHOOL & ~_ONLINE & partner),
        in_school_done=Count("id", filter=_IN_SCHOOL & ~_ONLINE & _DONE),
        in_school_schools=Count(
            "school_id", filter=_IN_SCHOOL & ~_ONLINE & _DONE, distinct=True
        ),
        in_school_teachers=Sum(
            "teachers_attended", filter=_IN_SCHOOL & ~_ONLINE & _DONE
        ),
        in_school_leaders=Sum("leaders_attended", filter=_IN_SCHOOL & ~_ONLINE & _DONE),
        group=Count("id", filter=_GROUP & ~_ONLINE),
        group_waiting=Count("id", filter=_GROUP & ~_ONLINE & _WAITING),
        group_done=Count("id", filter=_GROUP & ~_ONLINE & _DONE),
        online=Count("id", filter=_ONLINE),
        online_waiting=Count("id", filter=_ONLINE & _WAITING),
        online_done=Count("id", filter=_ONLINE & _DONE),
    )
    # The register of the completed sessions, for the scope's schools.
    sessions = engine._sessions(fy, window).filter(activity_type__in=engine._TRAININGS)
    online = Q(activity__programme_delivery_mode=ONLINE)
    register = ClusterActivityAttendance.objects.filter(
        school_id__in=scope.schools.values("id"),
        activity_id__in=sessions.values("id"),
    ).aggregate(
        group_invited=Count("id", filter=~online & Q(invited=True)),
        group_attended=Count("id", filter=~online & Q(attended=True)),
        group_teachers=Sum("teachers", filter=~online & Q(attended=True)),
        group_leaders=Sum("leaders", filter=~online & Q(attended=True)),
        online_invited=Count("id", filter=online & Q(invited=True)),
        online_attended=Count("id", filter=online & Q(attended=True)),
        online_teachers=Sum("teachers", filter=online & Q(attended=True)),
        online_leaders=Sum("leaders", filter=online & Q(attended=True)),
    )
    # A hand-over for training that the partner has not dated yet.
    assigned = (
        _handover_queryset(profile)
        .filter(expected_activity_type__in=engine._TRAININGS)
        .count()
    )

    def rate(attended, invited):
        return round(attended * 100 / invited) if invited else 0

    def people(prefix):
        return (register[f"{prefix}_teachers"] or 0) + (
            register[f"{prefix}_leaders"] or 0
        )

    return [
        {
            "key": "in_school",
            "label": "In-school training",
            "planned": counts["in_school"],
            "what": "trainings_in_school",
            "staff_planned": counts["in_school_staff"],
            "partner_assigned": assigned,
            "partner_scheduled": counts["in_school_partner"],
            "completed": counts["in_school_done"],
            "schools": counts["in_school_schools"],
            "people": (counts["in_school_teachers"] or 0)
            + (counts["in_school_leaders"] or 0),
            "invited": None,
            "attended": None,
            "rate": None,
        },
        {
            "key": "group",
            "label": "Group training",
            "planned": counts["group"],
            "what": "trainings_group",
            "scheduled": counts["group_waiting"],
            "completed": counts["group_done"],
            "schools": register["group_attended"],
            "people": people("group"),
            "invited": register["group_invited"],
            "attended": register["group_attended"],
            "rate": rate(register["group_attended"], register["group_invited"]),
        },
        {
            "key": "online",
            "label": "Online training",
            "planned": counts["online"],
            "what": "trainings_online",
            "scheduled": counts["online_waiting"],
            "completed": counts["online_done"],
            "schools": register["online_attended"],
            "people": people("online"),
            "invited": register["online_invited"],
            "attended": register["online_attended"],
            "rate": rate(register["online_attended"], register["online_invited"]),
        },
    ]


# ── Cluster meetings ────────────────────────────────────────────────────────
def meetings(profile: dict) -> dict:
    """The year's cluster meetings in the scope: by what each is for, in the
    plan, held, still to come and past its date; the schools represented and
    the attendance at those held; and the next ones. Three queries."""
    from apps.activities.models import ClusterActivityAttendance
    from apps.core.enums import MeetingKind

    scope, fy = profile["scope"], profile["fy"]
    window = engine.period_window(fy, profile["period"])
    work = _work(profile).filter(activity_type__in=engine._MEETINGS)
    labels = dict(MeetingKind.choices)
    kinds = [
        {
            "label": labels.get(kind, "Meeting"),
            "planned": planned,
            "held": held,
        }
        for kind, planned, held in work.values_list("meeting_kind")
        .annotate(planned=Count("id"), held=Count("id", filter=_DONE))
        .order_by("meeting_kind")
        .values_list("meeting_kind", "planned", "held")
    ]
    register = ClusterActivityAttendance.objects.filter(
        school_id__in=scope.schools.values("id"),
        activity_id__in=engine._sessions(fy, window)
        .filter(activity_type__in=engine._MEETINGS)
        .values("id"),
    ).aggregate(
        n_invited=Count("id", filter=Q(invited=True)),
        n_attended=Count("id", filter=Q(attended=True)),
        n_schools=Count("school_id", filter=Q(attended=True), distinct=True),
    )
    upcoming = list(
        work.filter(_WAITING & ~_past())
        .values("id", "planned_date", "scheduled_date", "cluster_id", "cluster__name")
        .order_by("planned_date", "scheduled_date", "id")[:5]
    )
    for row in upcoming:
        row["day"] = _day(row)
    figures = profile["execution"]["meetings"]
    return {
        "planned": figures["planned"],
        "held": figures["completed"],
        "upcoming_count": figures["upcoming"],
        "overdue": figures["overdue"],
        "kinds": kinds,
        "invited": register["n_invited"],
        "attended": register["n_attended"],
        "schools": register["n_schools"],
        "rate": round(register["n_attended"] * 100 / register["n_invited"])
        if register["n_invited"]
        else 0,
        "upcoming": upcoming,
    }


# ── Who and where: the header of a profile ──────────────────────────────────
def _holders(owner_ids) -> tuple[list[dict], list[dict]]:
    """The people who hold schools (``owner_ids`` are staff ids or user ids)
    and the Programme Leads they report to: two lists of ``{"id" (the user's,
    which a staff profile's address takes), "name"}``. Two queries."""
    from apps.accounts.models import StaffProfile, StaffSupervisorAssignment

    owner_ids = {str(i) for i in owner_ids if i}
    if not owner_ids:
        return [], []
    staff = {
        pk: {"id": user_id, "name": name or email or "Unnamed"}
        for pk, user_id, name, email in StaffProfile.objects.filter(
            Q(id__in=owner_ids) | Q(user_id__in=owner_ids)
        ).values_list("id", "user_id", "user__name", "user__email")
    }
    leads = {
        user_id: {"id": user_id, "name": name or email or "Unnamed"}
        for user_id, name, email in StaffSupervisorAssignment.objects.filter(
            supervisee_id__in=list(staff)
        )
        .values_list(
            "supervisor__user_id", "supervisor__user__name", "supervisor__user__email"
        )
        .distinct()
    }
    by_name = lambda row: row["name"].casefold()  # noqa: E731
    return sorted(staff.values(), key=by_name), sorted(leads.values(), key=by_name)


def _people_fact(label: str, people: list[dict], *, link: bool) -> dict:
    """One header fact naming people: up to three by name, then a count."""
    shown = people[:3]
    more = len(people) - len(shown)
    return {
        "label": label if len(people) == 1 else f"{label}s",
        "people": [
            {"name": p["name"], "href": f"/staff/{p['id']}" if link else ""}
            for p in shown
        ],
        "more": more,
        "value": "" if people else "Not assigned",
        "href": "",
    }


def identity(
    profile: dict, subject=None, *, may_open_staff: bool = False
) -> list[dict]:
    """What a profile's header says about its subject (the brief,
    2026-10-10: "What am I looking at, and what does this profile control or
    represent?"): its type, where it sits, who owns it, the year and its
    status. Read from the subject's own record and the scope's schools —
    nothing kept apart for the header."""
    from apps.core.enums import SchoolType

    scope = profile["scope"]
    schools = profile["_schools"]
    staff, leads = _holders({s["account_owner_id"] for s in schools})
    facts: list[dict] = []

    def fact(label, value, href=""):
        if value not in (None, ""):
            facts.append({"label": label, "value": value, "href": href})

    def place(school_like):
        district = getattr(school_like, "district", None)
        if district is not None:
            fact("District", district.name, f"/districts/{district.id}")
            if district.sub_region_id:
                fact(
                    "Sub-region",
                    district.sub_region.name,
                    f"/sub-regions/{district.sub_region_id}",
                )

    kind = scope.kind
    if kind == "school" and subject is not None:
        fact("School ID", subject.school_id)
        fact("Type", dict(SchoolType.choices).get(subject.school_type, ""))
        place(subject)
        if subject.sub_county_id:
            fact("Sub-county", subject.sub_county.name)
        cluster_names = profile["_cluster_names"]
        if subject.cluster_id in cluster_names:
            fact(
                "Cluster",
                cluster_names[subject.cluster_id],
                f"/clusters/{subject.cluster_id}",
            )
        facts.append(_people_fact("CCEO", staff, link=may_open_staff))
        facts.append(_people_fact("Programme Lead", leads, link=may_open_staff))
        partners = list(
            _handover_queryset(profile)
            .values_list("partner_id", "partner__name")
            .distinct()
            .order_by("partner__name")
        )
        if partners:
            facts.append(
                {
                    "label": "Partner" if len(partners) == 1 else "Partners",
                    "people": [
                        {"name": name, "href": f"/partners/{pk}"}
                        for pk, name in partners[:3]
                    ],
                    "more": max(len(partners) - 3, 0),
                    "value": "",
                    "href": "",
                }
            )
        fact("Status", "Closed" if subject.is_closed else "Operating")
    elif kind == "cluster" and subject is not None:
        fact("Type", "Cluster")
        place(subject)
        if subject.sub_county_name:
            fact("Sub-county", subject.sub_county_name)
        fact("Cluster Leader", subject.cluster_leader_name)
        facts.append(_people_fact("CCEO", staff, link=may_open_staff))
        facts.append(_people_fact("Programme Lead", leads, link=may_open_staff))
        fact("Status", _status(subject.status))
    elif kind == "district" and subject is not None:
        fact("Type", "District")
        if subject.sub_region_id:
            fact(
                "Sub-region",
                subject.sub_region.name,
                f"/sub-regions/{subject.sub_region_id}",
            )
        facts.append(_people_fact("Programme Lead", leads, link=may_open_staff))
        facts.append(_people_fact("CCEO", staff, link=may_open_staff))
    elif kind == "sub_region" and subject is not None:
        fact("Type", "Sub-region")
        if subject.region_id:
            fact("Region", subject.region.name)
            fact("Country", getattr(subject.region, "country", ""))
        fact("Districts", profile["portfolio"]["districts"])
        facts.append(_people_fact("Programme Lead", leads, link=may_open_staff))
        facts.append(_people_fact("CCEO", staff, link=may_open_staff))
    elif kind == "country":
        fact("Type", "Country")
        fact("Sub-regions", len({s["sub_region"] for s in schools if s["sub_region"]}))
        fact("Districts", profile["portfolio"]["districts"])
        facts.append(_people_fact("Programme Lead", leads, link=may_open_staff))
        fact("Staff Holding Schools", len(staff))
    elif kind in ("staff", "program_lead"):
        fact("Type", "Programme Lead" if kind == "program_lead" else "Staff")
        fact("Districts", profile["portfolio"]["districts"])
        if kind == "program_lead":
            fact("Team Members Holding Schools", len(staff))
        else:
            facts.append(_people_fact("Programme Lead", leads, link=may_open_staff))
    elif kind == "partner":
        fact("Type", "Partner")
        fact("Districts", profile["portfolio"]["districts"])
    fact("Fiscal Year", profile["fy_label"])
    return facts


def focus_work(profile: dict) -> dict[str, dict]:
    """``{intervention: {"planned", "done"}}``: the year's work in the scope
    that names each intervention as its focus. One query."""
    out: dict[str, dict] = {}
    for key, planned, done in (
        _work(profile)
        .exclude(focus_intervention__isnull=True)
        .exclude(focus_intervention="")
        .values_list("focus_intervention")
        .annotate(planned=Count("id"), done=Count("id", filter=_DONE))
        .values_list("focus_intervention", "planned", "done")
    ):
        out[key] = {"planned": planned, "done": done}
    return out
