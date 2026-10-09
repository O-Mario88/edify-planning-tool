"""The interventions a cluster's schools received, traced to what changed.

Owner brief, 2026-10-08 (Cluster Management, "The most important data
relationship"): "I would introduce a concept of Cluster Intervention. Every
intervention can be associated with: Cluster, School, Intervention type, SSA
area, Activity, Participants, Date, Owner, Evidence, Outcome, Impact. Then the
platform can trace: Cluster → Intervention → Activity → School → ... →
Outcome → SSA". And, of the end state: "Why did SSA improve? ... Which schools
have not benefited? ... Plan next action".

The same brief's architectural rule is "establish relationships between the
existing authoritative records" and "do not create duplicate versions". So the
intervention is not a new table that somebody has to keep in step with the
activity it describes: it is the activity, the loan and the SSA pair, read
together. One ledger row is one delivered thing — a group training or cluster
meeting (with the schools the register says came), a visit or training at a
member school, a loan disbursed to one — with who delivered it, the evidence
on it, and how the SSA area it was aimed at moved at the schools it reached.

"Moved" is what the schools' confirmed SSA records show. It is never claimed
that the intervention caused it (the brief: "Schools participating in the
intervention experienced...").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from apps.ssa import change_rules

from . import outcomes
from . import profile_insights as insights

VIEW_LEDGER = "all"
VIEW_AREAS = "areas"
VIEW_UNREACHED = "unreached"
VIEWS = (VIEW_LEDGER, VIEW_AREAS, VIEW_UNREACHED)


@dataclass
class InterventionRow:
    """One delivered intervention."""

    key: str
    held_on: date | None
    kind: str
    name: str
    area: str = ""
    area_label: str = ""
    activity_id: str = ""
    loan_id: str = ""
    school_pk: str = ""
    school_code: str = ""
    school_name: str = ""
    reach: str = ""
    owner: str = ""
    evidence: int | None = None
    school_ids: frozenset = frozenset()
    compared: int = 0
    better: int = 0
    worse: int = 0
    change: float | None = None

    @property
    def outcome(self) -> str:
        """How the area this was aimed at moved at the schools it reached."""
        if not self.area:
            return "No SSA area named"
        if not self.compared:
            return "Schools not yet compared on this area"
        if self.school_pk:
            sign = "+" if (self.change or 0) > 0 else ""
            return f"{self.area_label} {sign}{self.change:.1f}"
        return f"{self.better} of {self.compared} schools rose on {self.area_label}" + (
            f", {self.worse} fell" if self.worse else ""
        )

    @property
    def outcome_tone(self) -> str:
        if not self.area or not self.compared:
            return "neutral"
        if self.school_pk:
            return (
                "success"
                if (self.change or 0) > 0
                else ("danger" if (self.change or 0) < 0 else "neutral")
            )
        if self.better * 2 >= self.compared:
            return "success"
        return "danger" if self.worse * 2 > self.compared else "neutral"


@dataclass
class AreaTrace:
    """One SSA area: what was done on it and how the schools reached moved."""

    key: str
    label: str
    interventions: int = 0
    reached: set = field(default_factory=set)
    compared: int = 0
    better: int = 0
    worse: int = 0
    before: float | None = None
    after: float | None = None

    @property
    def reached_count(self) -> int:
        return len(self.reached)

    @property
    def change(self) -> float | None:
        if self.before is None or self.after is None:
            return None
        return round(self.after - self.before, 1)


def _owner_names(owner_ids) -> dict[str, str]:
    from .oversight_service import _label, _staff_directory

    return {
        key: _label(profile)
        for key, profile in _staff_directory(set(owner_ids)).items()
    }


def _school_activities(school_ids, fy: str):
    """Delivered visits, trainings and SSA work at the member schools.

    Delivered as on every other read here: completed and with a verifier, or
    verified. Planned and cancelled work is somebody's intention, not an
    intervention a school received.
    """
    from apps.activities.models import Activity
    from apps.planning.school_planning_badges import (
        AWAITING_VERIFICATION_STATUSES,
        VERIFIED_STATUSES,
    )

    return (
        Activity.objects.filter(
            school_id__in=list(school_ids),
            fy=fy,
            deleted_at__isnull=True,
            status__in=AWAITING_VERIFICATION_STATUSES | VERIFIED_STATUSES,
        )
        .select_related("catalogue_item", "training_course")
        .order_by("-actual_delivery_date", "-planned_date")
    )


def cluster_interventions(cluster, *, fy: str, principal=None, area: str = "") -> dict:
    """The cluster's delivered interventions in fiscal year ``fy``, each traced
    to the SSA movement of the schools it reached; the same folded by SSA
    area; and the member schools no intervention reached.

    The SSA movement is the cluster's own (``ssa_movement_for_page``), so an
    outcome here is the figure the SSA Movement tab shows for that school and
    area. Seven queries whatever the size of the cluster.
    """
    from apps.activities.training_names import course_name_of, is_training
    from apps.core.enums import SsaIntervention
    from apps.evidence.models import EvidenceRecord
    from django.db.models import Count

    fy = str(fy)
    members = insights.member_schools([cluster.id])
    schools = members[cluster.id]
    by_id = {s["id"]: s for s in schools}
    attendance = insights.attendance_by_cluster([cluster.id], fy=fy, members=members)[
        cluster.id
    ]
    ssa_fy, movement_all = insights.ssa_movement_for_page(
        [cluster.id], fy=fy, members=members
    )
    movement = movement_all[cluster.id]
    area_rows = {
        key: {r["id"]: r for r in rows}
        for key, rows in movement["schools_by_area"].items()
    }
    labels = dict(SsaIntervention.choices)

    def judge(row: InterventionRow) -> None:
        """Fill in how the row's area moved at the schools it reached."""
        if not row.area:
            return
        changes = []
        for school_id in row.school_ids:
            verdict = (area_rows.get(row.area) or {}).get(school_id)
            if verdict is None or verdict["verdict"] == insights.NOT_COMPARED:
                continue
            row.compared += 1
            changes.append(verdict["change"])
            if verdict["verdict"] in (
                change_rules.IMPROVED,
                change_rules.MAINTAINED_STRONG,
            ):
                row.better += 1
            elif verdict["verdict"] == change_rules.DECLINED:
                row.worse += 1
        if changes:
            row.change = round(sum(changes) / len(changes), 1)

    rows: list[InterventionRow] = []
    for session in attendance["sessions"]:
        reached = session.attended_ids & set(by_id)
        rows.append(
            InterventionRow(
                key=f"session-{session.id}",
                held_on=session.held_on,
                kind=session.kind,
                name=session.name,
                area=session.area,
                area_label=labels.get(session.area, ""),
                activity_id=session.id,
                reach=(
                    f"{len(reached)} of {len(session.invited_ids & set(by_id))} "
                    f"schools; {session.teachers} teachers, {session.leaders} leaders"
                ),
                owner=session.owner_id,
                school_ids=frozenset(reached),
            )
        )

    activities = list(_school_activities(by_id, fy)) if by_id else []
    for activity in activities:
        school = by_id[activity.school_id]
        rows.append(
            InterventionRow(
                key=f"activity-{activity.id}",
                held_on=activity.actual_delivery_date or activity.planned_date,
                kind=activity.get_activity_type_display(),
                name=(
                    (course_name_of(activity) or "Not yet named")
                    if is_training(activity)
                    else (
                        activity.catalogue_item.display_name
                        if activity.catalogue_item_id
                        else activity.get_activity_type_display()
                    )
                ),
                area=activity.focus_intervention or "",
                area_label=labels.get(activity.focus_intervention or "", ""),
                activity_id=activity.id,
                school_pk=school["id"],
                school_code=school["school_id"] or "",
                school_name=school["name"],
                reach="1 school",
                owner=activity.responsible_staff_id or "",
                school_ids=frozenset([school["id"]]),
            )
        )

    evidence = dict(
        EvidenceRecord.objects.filter(
            activity_id__in=[r.activity_id for r in rows if r.activity_id]
        )
        .values_list("activity_id")
        .annotate(n=Count("id"))
    )
    names = _owner_names(r.owner for r in rows)
    for row in rows:
        row.evidence = evidence.get(row.activity_id, 0)
        row.owner = names.get(row.owner, "") if row.owner else ""
        judge(row)

    # A loan is an intervention too (the brief: "Loan → intervention → school
    # improvement"), shown as far as the reader may read the loan register.
    if principal is not None and by_id:
        from apps.core.fy import get_fy_date_range

        start, end = get_fy_date_range(fy)
        loans = outcomes.loans_by_cluster([cluster.id], principal, members=members)[
            cluster.id
        ]
        for loan in loans.rows:
            day = loan["disbursed_on"]
            if not day or not (start.date() <= day < end.date()):
                continue
            rows.append(
                InterventionRow(
                    key=f"loan-{loan['id']}",
                    held_on=day,
                    kind="Loan",
                    name=loan["purpose"] or "Loan",
                    loan_id=loan["id"],
                    school_pk=loan["school_pk"],
                    school_code=loan["code"],
                    school_name=loan["name"],
                    reach="1 school",
                    owner=loan["lender"],
                    school_ids=frozenset([loan["school_pk"]]),
                )
            )

    rows.sort(key=lambda r: r.held_on or date.min, reverse=True)

    traces = {key: AreaTrace(key=key, label=label) for key, label in labels.items()}
    reached_any: set = set()
    for row in rows:
        reached_any |= row.school_ids
        if row.area in traces:
            traces[row.area].interventions += 1
            traces[row.area].reached |= row.school_ids
    for key, trace in traces.items():
        verdicts = [
            v
            for school_id, v in (area_rows.get(key) or {}).items()
            if school_id in trace.reached and v["verdict"] != insights.NOT_COMPARED
        ]
        trace.compared = len(verdicts)
        trace.better = sum(
            1
            for v in verdicts
            if v["verdict"] in (change_rules.IMPROVED, change_rules.MAINTAINED_STRONG)
        )
        trace.worse = sum(1 for v in verdicts if v["verdict"] == change_rules.DECLINED)
        if verdicts:
            trace.before = round(sum(v["before"] for v in verdicts) / len(verdicts), 1)
            trace.after = round(sum(v["after"] for v in verdicts) / len(verdicts), 1)

    unreached = [s for s in schools if s["id"] not in reached_any]
    area = area if area in traces else ""
    return {
        "fy": fy,
        "ssa_fy": ssa_fy,
        "ssa_previous_fy": str(int(ssa_fy) - 1),
        "area": area,
        "area_label": labels.get(area, ""),
        "rows": [r for r in rows if not area or r.area == area],
        "all_rows": rows,
        "areas": list(traces.values()),
        "unreached": [
            {"id": s["id"], "code": s["school_id"] or "", "name": s["name"]}
            for s in unreached
        ],
        "school_count": len(schools),
        "reached_count": len(schools) - len(unreached),
    }


def course_effectiveness(facts: dict) -> list[dict]:
    """Across clusters: for each training course, how the SSA area it was
    aimed at moved at the schools that attended (the brief's "Which
    interventions produce the greatest improvement?").

    ``facts`` is ``scores.gather``. A school is counted once per training it
    attended. The mean change is across those readings; a course with fewer
    than a handful of readings says so by its count, and nothing here is a
    claim of cause.
    """
    from apps.core.enums import SsaIntervention

    from .scores import trained_pairs

    labels = dict(SsaIntervention.choices)
    courses: dict[tuple[str, str], dict] = {}
    for cid, attendance in facts["attendance"].items():
        sessions = set()
        for pair in trained_pairs(attendance, facts["movement"][cid]):
            entry = courses.setdefault(
                (pair["course"], pair["area"]),
                {
                    "course": pair["course"],
                    "area": labels.get(pair["area"], pair["area"]),
                    "sessions": set(),
                    "clusters": set(),
                    "readings": 0,
                    "better": 0,
                    "total_change": 0.0,
                },
            )
            sessions.add(pair["session_id"])
            entry["sessions"].add(pair["session_id"])
            entry["clusters"].add(cid)
            entry["readings"] += 1
            entry["better"] += int(pair["better"])
            entry["total_change"] += pair["change"] or 0.0
    out = []
    for entry in courses.values():
        out.append(
            {
                "course": entry["course"],
                "area": entry["area"],
                "sessions": len(entry["sessions"]),
                "clusters": len(entry["clusters"]),
                "readings": entry["readings"],
                "better": entry["better"],
                "better_pct": round(100 * entry["better"] / entry["readings"]),
                "mean_change": round(entry["total_change"] / entry["readings"], 1),
            }
        )
    out.sort(key=lambda row: (-row["mean_change"], row["course"]))
    return out


__all__ = [
    "AreaTrace",
    "InterventionRow",
    "VIEWS",
    "VIEW_AREAS",
    "VIEW_LEDGER",
    "VIEW_UNREACHED",
    "cluster_interventions",
    "course_effectiveness",
]
