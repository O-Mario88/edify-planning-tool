"""What a cluster's own records say about its schools.

The reads behind the cluster profile's tabs and the Cluster Management tables
(owner brief, 2026-10-08: "Cluster Management becomes the integration,
aggregation, analysis and impact layer ... Do not create duplicate versions of
existing functionality"). Nothing here is stored and nothing is a second copy
of anything:

* attendance is the session register the person who ran a meeting or a group
  training filled in (``ClusterActivityAttendance``, with the older
  ``Activity.attended_school_ids`` beside it);
* SSA movement is the schools' confirmed SSA records, year on year, judged by
  ``apps.ssa.change_rules`` — the one definition of improved and declined;
* membership history is ``SchoolClusterMembership``.

A figure that cannot be proved from those records is left out and said so,
never estimated: a school is "invited" only where an invitation is recorded,
a delivered session with no register is counted as having none, and two SSA
readings that cannot be compared are "not compared", not "no change".

Each read has a ``*_by_cluster`` form that answers for many clusters in the
same few queries, so a table of every cluster in the country costs what one
profile costs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from apps.ssa import change_rules

#: Sessions missed in a row before a school is named as drifting away (the
#: brief's example: "4 schools have missed 3+ consecutive cluster meetings").
MISSED_IN_A_ROW_ALERT = 3

# ── Attendance ───────────────────────────────────────────────────────────────

SHOW_ALL = "all"
SHOW_MISSING = "missing"
SHOW_NEVER = "never"
SHOW_SESSIONS = "sessions"
ATTENDANCE_VIEWS = (SHOW_ALL, SHOW_MISSING, SHOW_NEVER, SHOW_SESSIONS)


@dataclass
class SessionRow:
    """One delivered meeting or group training, and who was in the room."""

    id: str
    held_on: date | None
    fy: str
    kind: str
    name: str
    invited: int = 0
    attended: int = 0
    teachers: int = 0
    leaders: int = 0
    is_training: bool = False
    #: The SSA area the session was planned to move, where one was named.
    area: str = ""
    owner_id: str = ""
    invited_ids: frozenset = frozenset()
    attended_ids: frozenset = frozenset()

    @property
    def has_invitations(self) -> bool:
        return self.invited > 0

    @property
    def rate(self) -> int | None:
        if not self.invited:
            return None
        return round(100 * min(self.attended, self.invited) / self.invited)


@dataclass
class SchoolAttendanceRow:
    """A member school's attendance at its cluster's sessions."""

    id: str
    code: str
    name: str
    cluster_id: str = ""
    invited: int = 0
    attended: int = 0
    last_attended: date | None = None
    missed_in_a_row: int = 0
    teachers: int = 0
    leaders: int = 0

    @property
    def rate(self) -> int | None:
        if not self.invited:
            return None
        return round(100 * self.attended / self.invited)

    @property
    def is_drifting(self) -> bool:
        return self.missed_in_a_row >= MISSED_IN_A_ROW_ALERT

    @property
    def standing(self) -> tuple[str, str]:
        """What the row says about the school, and the tone to say it in."""
        if self.is_drifting:
            return f"Missed {self.missed_in_a_row} in a row", "danger"
        if self.missed_in_a_row > 1:
            return f"Missed {self.missed_in_a_row} in a row", "warning"
        if self.missed_in_a_row:
            return "Missed the last session", "warning"
        if self.attended:
            return "Attending", "success"
        if self.invited:
            return "Not yet attended", "warning"
        return "Not invited", "neutral"


def member_schools(cluster_ids) -> dict[str, list[dict]]:
    """The operating schools of each cluster, by name."""
    from apps.schools.lifecycle_service import active_schools

    members: dict[str, list[dict]] = {cid: [] for cid in cluster_ids}
    if not members:
        return members
    for row in (
        active_schools()
        .filter(cluster_id__in=list(members))
        .order_by("name")
        .values("id", "school_id", "name", "cluster_id", "region__country")
    ):
        members[row["cluster_id"]].append(row)
    return members


def _delivered_sessions(cluster_ids):
    """The clusters' meetings and group trainings that were held.

    Delivered is the status at which the register is final
    (``school_planning_badges._POST_DELIVERY``): completed and waiting on a
    verifier, or verified. A planned, moved or cancelled session has no
    register to read.
    """
    from apps.activities.models import Activity
    from apps.planning.school_planning_badges import (
        AWAITING_VERIFICATION_STATUSES,
        CLUSTER_SESSION_TYPES,
        VERIFIED_STATUSES,
    )

    return Activity.objects.filter(
        cluster_id__in=list(cluster_ids),
        school__isnull=True,
        deleted_at__isnull=True,
        activity_type__in=CLUSTER_SESSION_TYPES,
        status__in=AWAITING_VERIFICATION_STATUSES | VERIFIED_STATUSES,
    ).select_related("catalogue_item", "training_course")


def _session_name(activity) -> tuple[str, str]:
    """(kind, name): a training is named by its catalogue course (owner,
    2026-10-06), a meeting by what kind of meeting it is."""
    from apps.activities.training_names import course_name_of, is_training

    if is_training(activity):
        return "Group Training", course_name_of(activity) or "Not yet named"
    return "Cluster Meeting", activity.get_activity_type_display()


def _attendance_of(cluster_id, schools, activities, register, fy: str) -> dict:
    """One cluster's attendance from its schools, sessions and register."""
    from apps.activities.training_names import is_training

    members = {
        row["id"]: SchoolAttendanceRow(
            id=row["id"],
            code=row["school_id"] or "",
            name=row["name"],
            cluster_id=cluster_id,
        )
        for row in schools
    }
    sessions: list[SessionRow] = []
    without_register = 0
    # (held_on, attended) per school, for the run of misses.
    timeline: dict[str, list[tuple[date | None, bool]]] = {
        school_id: [] for school_id in members
    }
    for activity in activities:
        rows = register.get(activity.id, {})
        # The older record of who came, kept on the activity itself.
        named = set(activity.attended_school_ids or [])
        came = {sid for sid, row in rows.items() if row["attended"]} | named
        asked = {sid for sid, row in rows.items() if row["invited"]} | came
        if not came:
            # Delivered, and nobody ticked: the register was not taken. That
            # is not the same as an empty room, so it is counted against no
            # school.
            without_register += 1
            continue
        held_on = activity.actual_delivery_date or activity.planned_date
        kind, name = _session_name(activity)
        session = SessionRow(
            id=activity.id,
            held_on=held_on,
            fy=str(activity.fy or ""),
            kind=kind,
            name=name,
            invited=len(asked),
            attended=len(came),
            is_training=is_training(activity),
            area=activity.focus_intervention or "",
            owner_id=activity.responsible_staff_id or "",
            invited_ids=frozenset(asked),
            attended_ids=frozenset(came),
        )
        for school_id in came:
            row = rows.get(school_id) or {}
            session.teachers += row.get("teachers") or 0
            session.leaders += row.get("leaders") or 0
        sessions.append(session)

        for school_id, school in members.items():
            if school_id not in asked:
                continue
            attended = school_id in came
            timeline[school_id].append((held_on, attended))
            if session.fy != fy:
                continue
            school.invited += 1
            if attended:
                school.attended += 1
                row = rows.get(school_id) or {}
                school.teachers += row.get("teachers") or 0
                school.leaders += row.get("leaders") or 0

    for school_id, school in members.items():
        newest_first = sorted(
            timeline[school_id], key=lambda entry: entry[0] or date.min, reverse=True
        )
        for held_on, attended in newest_first:
            if attended:
                school.last_attended = held_on
                break
            school.missed_in_a_row += 1

    sessions.sort(key=lambda s: s.held_on or date.min, reverse=True)
    year_sessions = [s for s in sessions if s.fy == fy]
    rows = list(members.values())
    invited_total = sum(s.invited for s in rows)
    attended_total = sum(s.attended for s in rows)
    return {
        "fy": fy,
        "schools": rows,
        "drifting": sorted(
            (s for s in rows if s.is_drifting),
            key=lambda s: (-s.missed_in_a_row, s.name),
        ),
        "never": [s for s in rows if s.invited and not s.attended],
        "sessions": year_sessions,
        "all_sessions": sessions,
        "sessions_all_years": len(sessions),
        "without_register": without_register,
        "represented": sum(1 for s in rows if s.attended),
        "invited_total": invited_total,
        "attended_total": attended_total,
        "rate": (
            round(100 * attended_total / invited_total) if invited_total else None
        ),
        "teachers": sum(s.teachers for s in rows),
        "leaders": sum(s.leaders for s in rows),
        "alert_after": MISSED_IN_A_ROW_ALERT,
    }


def attendance_by_cluster(cluster_ids, *, fy: str, members=None) -> dict[str, dict]:
    """Who came to each cluster's sessions, school by school.

    Invited and Attended count the sessions of fiscal year ``fy``; "missed in
    a row" counts back from the latest session a school was invited to,
    across years, because a school that stopped coming in August has not
    started again on 1 October.

    Three queries whatever the number of clusters: the member schools, the
    delivered sessions, their register.
    """
    from apps.activities.models import ClusterActivityAttendance

    cluster_ids = list(cluster_ids)
    fy = str(fy)
    members = members if members is not None else member_schools(cluster_ids)
    sessions: dict[str, list] = {cid: [] for cid in cluster_ids}
    for activity in _delivered_sessions(cluster_ids) if cluster_ids else ():
        sessions[activity.cluster_id].append(activity)
    activity_ids = [a.id for rows in sessions.values() for a in rows]
    register: dict[str, dict[str, dict]] = {}
    if activity_ids:
        for row in ClusterActivityAttendance.objects.filter(
            activity_id__in=activity_ids
        ).values(
            "activity_id", "school_id", "invited", "attended", "teachers", "leaders"
        ):
            register.setdefault(row["activity_id"], {})[row["school_id"]] = row
    return {
        cid: _attendance_of(cid, members.get(cid, []), sessions[cid], register, fy)
        for cid in cluster_ids
    }


def cluster_attendance(cluster, *, fy: str) -> dict:
    """One cluster's attendance (``attendance_by_cluster`` for one)."""
    return attendance_by_cluster([cluster.id], fy=fy)[cluster.id]


# ── SSA movement ─────────────────────────────────────────────────────────────

OVERALL = "overall"
NOT_COMPARED = "not_compared"

#: The verdicts a count can be opened by, in the order the columns read.
VERDICT_LABELS = {
    change_rules.IMPROVED: "Improved",
    change_rules.NO_CHANGE: "No Change",
    change_rules.MAINTAINED_STRONG: "Maintained Strong",
    change_rules.DECLINED: "Declined",
    NOT_COMPARED: "Not Compared",
}
VERDICT_TONES = {
    change_rules.IMPROVED: "success",
    change_rules.MAINTAINED_STRONG: "success",
    change_rules.NO_CHANGE: "neutral",
    change_rules.DECLINED: "danger",
    NOT_COMPARED: "neutral",
}


@dataclass
class AreaMovement:
    """One SSA area's year-on-year movement across a cluster's schools."""

    key: str
    label: str
    compared: int = 0
    before: float | None = None
    after: float | None = None
    improved: int = 0
    no_change: int = 0
    maintained_strong: int = 0
    declined: int = 0
    not_compared: int = 0

    @property
    def change(self) -> float | None:
        if self.before is None or self.after is None:
            return None
        return round(self.after - self.before, 1)

    @property
    def held(self) -> int:
        """No change and maintained strong, the two ways of holding a score."""
        return self.no_change + self.maintained_strong

    @property
    def improved_pct(self) -> int | None:
        """Share of the compared schools that improved."""
        if not self.compared:
            return None
        return round(100 * self.improved / self.compared)


def _mean(values) -> float | None:
    values = [float(v) for v in values if v is not None]
    return round(sum(values) / len(values), 1) if values else None


def ssa_years_with_records(cluster) -> list[str]:
    """Fiscal years in which a member school has a confirmed SSA, newest first."""
    from apps.core.enums import VerificationStatus
    from apps.schools.lifecycle_service import active_schools
    from apps.ssa.models import SsaRecord

    return sorted(
        {
            str(fy)
            for fy in SsaRecord.objects.filter(
                school__in=active_schools().filter(cluster_id=cluster.id),
                deleted_at__isnull=True,
                verification_status=VerificationStatus.CONFIRMED.value,
            )
            .values_list("fy", flat=True)
            .distinct()
            if str(fy).isdigit()
        },
        reverse=True,
    )


def _movement_of(schools, by_school, verdicts, has_now, has_before, fy, book) -> dict:
    """One cluster's SSA movement from its schools' classified pairs."""
    from apps.core.enums import SsaIntervention

    previous_fy = str(int(fy) - 1)

    def why_not(school_id: str) -> str:
        if school_id not in has_now and school_id not in has_before:
            return f"No confirmed SSA in FY {previous_fy} or FY {fy}"
        if school_id not in has_now:
            return f"No confirmed SSA in FY {fy}"
        if school_id not in has_before:
            return f"No confirmed SSA in FY {previous_fy}"
        return (
            f"Readings less than {change_rules.MIN_INTERVAL_DAYS} days apart, "
            "or no SSA area scored in both years"
        )

    def school_row(member, *, before, after, verdict, note="") -> dict:
        delta = (
            round(after - before, 1)
            if before is not None and after is not None
            else None
        )
        return {
            "id": member["id"],
            "code": member["school_id"] or "",
            "name": member["name"],
            "before": before,
            "after": after,
            "change": delta,
            "verdict": verdict,
            "verdict_label": VERDICT_LABELS[verdict],
            "tone": VERDICT_TONES[verdict],
            "note": note,
        }

    overall = AreaMovement(key=OVERALL, label="All SSA Areas")
    overall_schools: list[dict] = []
    for member in schools:
        school_pairs = by_school.get(member["id"])
        verdict = verdicts.get(member["id"])
        if (
            not school_pairs
            or verdict is None
            or verdict["classification"] == change_rules.NOT_COMPARABLE
        ):
            overall.not_compared += 1
            overall_schools.append(
                school_row(
                    member,
                    before=None,
                    after=None,
                    verdict=NOT_COMPARED,
                    note=why_not(member["id"]),
                )
            )
            continue
        overall.compared += 1
        setattr(
            overall,
            verdict["classification"],
            getattr(overall, verdict["classification"]) + 1,
        )
        overall_schools.append(
            school_row(
                member,
                before=_mean(p["prev_score"] for p in school_pairs.values()),
                after=_mean(p["curr_score"] for p in school_pairs.values()),
                verdict=verdict["classification"],
            )
        )
    compared_rows = [r for r in overall_schools if r["verdict"] != NOT_COMPARED]
    overall.before = _mean(r["before"] for r in compared_rows)
    overall.after = _mean(r["after"] for r in compared_rows)

    areas = [overall]
    schools_by_area = {OVERALL: overall_schools}
    for intervention in SsaIntervention:
        area = AreaMovement(key=intervention.value, label=intervention.label)
        rows = []
        scored = []
        for member in schools:
            pair = (by_school.get(member["id"]) or {}).get(intervention.value)
            if pair is None:
                area.not_compared += 1
                rows.append(
                    school_row(
                        member,
                        before=None,
                        after=None,
                        verdict=NOT_COMPARED,
                        note=(
                            why_not(member["id"])
                            if member["id"] not in by_school
                            else "Not scored in both years"
                        ),
                    )
                )
                continue
            scored.append(pair)
            area.compared += 1
            setattr(
                area,
                pair["classification"],
                getattr(area, pair["classification"]) + 1,
            )
            rows.append(
                school_row(
                    member,
                    before=round(pair["prev_score"], 1),
                    after=round(pair["curr_score"], 1),
                    verdict=pair["classification"],
                )
            )
        area.before = _mean(p["prev_score"] for p in scored)
        area.after = _mean(p["curr_score"] for p in scored)
        areas.append(area)
        schools_by_area[intervention.value] = rows

    return {
        "fy": fy,
        "previous_fy": previous_fy,
        "areas": areas,
        "overall": overall,
        "schools_by_area": schools_by_area,
        "school_count": len(schools),
        "compared": overall.compared,
        "rule_label": change_rules.rule_label_for(book),
        "rule_sentence": change_rules.RULE_SENTENCE,
    }


def ssa_movement_by_cluster(cluster_ids, *, fy: str, members=None) -> dict[str, dict]:
    """Each cluster's SSA movement from fiscal year ``fy - 1`` to ``fy``.

    A school is compared where it has a confirmed SSA in both years
    (``impact_engine.improvement_rows``, the pairs every impact page reads),
    and each pair is judged by ``apps.ssa.change_rules``. The overall row is
    the school's verdict across its areas, not an average of the area rows.
    A school with no pair is "not compared" and is in no average.

    The same handful of queries whatever the number of clusters.
    """
    from apps.analytics.impact_engine import (
        _latest_confirmed_records,
        improvement_rows,
    )

    cluster_ids = list(cluster_ids)
    fy = str(fy)
    members = members if members is not None else member_schools(cluster_ids)
    school_ids = [s["id"] for rows in members.values() for s in rows]
    countries = {
        s["id"]: s["region__country"] or "" for rows in members.values() for s in rows
    }

    def country_for(school_id):
        return countries.get(school_id, "")

    book = change_rules.RuleBook()
    raw = improvement_rows(school_ids, fy) or []
    pairs = change_rules.classify_pairs(raw, book=book, country_for=country_for)
    verdicts = change_rules.school_verdicts(pairs, book=book, country_for=country_for)
    by_school: dict[str, dict[str, dict]] = {}
    for pair in pairs:
        by_school.setdefault(pair["school_id"], {})[pair["intervention"]] = pair

    # Why a school is in no comparison: which year has no confirmed SSA, or
    # the two readings are the same assessment period read twice.
    has_now = set(_latest_confirmed_records(school_ids, fy)) if school_ids else set()
    has_before = (
        set(_latest_confirmed_records(school_ids, str(int(fy) - 1)))
        if school_ids
        else set()
    )
    return {
        cid: _movement_of(
            members.get(cid, []), by_school, verdicts, has_now, has_before, fy, book
        )
        for cid in cluster_ids
    }


def ssa_movement_for_page(cluster_ids, *, fy: str, members=None) -> tuple[str, dict]:
    """(year, movement) for a table of clusters read in fiscal year ``fy``.

    The movement into ``fy`` where any of these clusters has a school compared
    in it, else the movement into the year before: on 1 October the new year
    holds no SSA yet, and a column that stayed blank for a quarter would be
    read as "nothing changed". The year is returned so the column can say
    which two years it compares.
    """
    cluster_ids = list(cluster_ids)
    fy = str(fy)
    members = members if members is not None else member_schools(cluster_ids)
    movement = ssa_movement_by_cluster(cluster_ids, fy=fy, members=members)
    if any(m["compared"] for m in movement.values()):
        return fy, movement
    earlier = str(int(fy) - 1)
    fallback = ssa_movement_by_cluster(cluster_ids, fy=earlier, members=members)
    if any(m["compared"] for m in fallback.values()):
        return earlier, fallback
    return fy, movement


def cluster_ssa_movement(cluster, *, fy: str) -> dict:
    """One cluster's SSA movement (``ssa_movement_by_cluster`` for one)."""
    return ssa_movement_by_cluster([cluster.id], fy=fy)[cluster.id]


def ssa_schools(movement: dict, area: str, verdict: str) -> dict | None:
    """The schools behind one count of the SSA movement table."""
    rows = movement["schools_by_area"].get(area)
    if rows is None or verdict not in VERDICT_LABELS:
        return None
    wanted = (
        {change_rules.NO_CHANGE, change_rules.MAINTAINED_STRONG}
        if verdict == change_rules.NO_CHANGE
        else {verdict}
    )
    label = next(a.label for a in movement["areas"] if a.key == area)
    return {
        "area": area,
        "area_label": label,
        "verdict": verdict,
        "verdict_label": VERDICT_LABELS[verdict],
        "rows": [r for r in rows if r["verdict"] in wanted],
    }


# ── Membership history ───────────────────────────────────────────────────────


def cluster_membership_history(cluster) -> dict:
    """Every school that has belonged to this cluster, with when, who and why.

    A school that moved on keeps its row, so last year's figures can still be
    traced to the schools that were members then. Two queries: the rows and
    the names of the people who made the changes.
    """
    from django.db.models import F

    from apps.accounts.models import User

    from .models import SchoolClusterMembership

    rows = list(
        SchoolClusterMembership.objects.filter(cluster_id=cluster.id)
        .select_related("school", "school_district", "cluster_district")
        # Current members (no end date) first, then the latest to leave.
        .order_by(F("ended_at").desc(nulls_first=True), "school__name")
    )
    actor_ids = {r.started_by for r in rows if r.started_by} | {
        r.ended_by for r in rows if r.ended_by
    }
    names = (
        dict(User.objects.filter(id__in=actor_ids).values_list("id", "name"))
        if actor_ids
        else {}
    )
    history = [
        {
            "school_id": r.school_id,
            "code": r.school.school_id or "",
            "name": r.school.name,
            "district": r.school_district.name if r.school_district_id else "",
            "cross_district": r.is_cross_district,
            "joined": r.started_at,
            "left": r.ended_at,
            "is_member": r.ended_at is None,
            "joined_by": names.get(r.started_by, ""),
            "ended_by": names.get(r.ended_by, ""),
            "start_reason": r.start_reason,
            "end_reason": r.end_reason,
        }
        for r in rows
    ]
    return {
        "rows": history,
        "current": sum(1 for r in history if r["is_member"]),
        "former": sum(1 for r in history if not r["is_member"]),
    }


__all__ = [
    "ATTENDANCE_VIEWS",
    "MISSED_IN_A_ROW_ALERT",
    "NOT_COMPARED",
    "OVERALL",
    "SHOW_ALL",
    "SHOW_MISSING",
    "SHOW_NEVER",
    "SHOW_SESSIONS",
    "VERDICT_LABELS",
    "attendance_by_cluster",
    "member_schools",
    "cluster_attendance",
    "cluster_membership_history",
    "cluster_ssa_movement",
    "ssa_movement_by_cluster",
    "ssa_movement_for_page",
    "ssa_schools",
    "ssa_years_with_records",
]
