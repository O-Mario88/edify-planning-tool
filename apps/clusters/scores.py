"""Cluster Health, Cluster Impact, the Teacher and Leader indices, Maturity.

Owner brief, 2026-10-08 (Cluster Management):

* "Cluster Health answers: is the cluster operating properly? ... Cluster
  Impact answers: is the cluster actually changing outcomes? ... Management
  needs to see both", kept apart;
* "Not a mysterious AI score. A transparent composite", with weights the
  Country Director and Impact Assessment set (``ClusterScoreSetting``);
* a Teacher Impact and a School Leadership Impact index, "configurable rather
  than hard-coded";
* a maturity level from Forming to Model Cluster, "make the criteria
  configurable".

How a score is made, so it can be read back:

1. Every part is a share out of 100 taken from records the platform already
   keeps (the session register, the plan, confirmed SSA pairs, enrolment and
   learning results, the loan register). Each carries its basis in words —
   "9 of 16 schools improved" — and that is shown beside it.
2. A part that cannot be measured is left out, not counted as zero, and the
   weights of the parts that can be are scaled up to fill its place. The score
   says how many parts it stands on, and below ``min_dimensions`` there is no
   score at all: one figure is not a composite.
3. Nothing here says a cluster's work *caused* a change. "Schools that
   attended ... and whose SSA rose" is contribution, and is worded so.

What is not collected anywhere is named in ``NOT_COLLECTED`` and shown as such
on the page, so an index never looks more complete than it is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from apps.ssa import change_rules

from . import outcomes
from . import profile_insights as insights

# (key, label, default weight). The Impact weights are the brief's own table.
HEALTH_DIMENSIONS = (
    ("meetings", "Meetings Held", 20),
    ("trainings", "Trainings Held", 20),
    ("attendance", "Attendance", 20),
    ("participation", "School Participation", 20),
    ("planning", "Planning", 10),
    ("follow_up", "Follow-up", 10),
)
IMPACT_DIMENSIONS = (
    ("ssa", "SSA Improvement", 25),
    ("training_effect", "Training Effectiveness", 15),
    ("meeting_engagement", "Meeting Engagement", 10),
    ("teacher", "Teacher Impact", 10),
    ("leader", "Leadership Impact", 10),
    ("enrolment", "Enrolment Growth", 10),
    ("exams", "Exam Improvement", 10),
    ("bt", "Business Transformation", 5),
    ("loans", "Loan Reach", 5),
)
TEACHER_DIMENSIONS = (
    ("training_attendance", "Training Attendance", 40),
    ("teaching_ssa", "Teacher's Environment SSA", 40),
    ("learning_env_ssa", "Learning Environment SSA", 20),
)
LEADER_DIMENSIONS = (
    ("meeting_attendance", "Meeting Attendance", 25),
    ("leadership_ssa", "Leadership SSA", 35),
    ("finance_ssa", "Financial Health SSA", 20),
    ("compliance_ssa", "Government Requirements SSA", 20),
)
SCORES = {
    "health": ("Cluster Health", HEALTH_DIMENSIONS),
    "impact": ("Cluster Impact", IMPACT_DIMENSIONS),
    "teacher": ("Teacher Impact", TEACHER_DIMENSIONS),
    "leader": ("School Leadership Impact", LEADER_DIMENSIONS),
}

#: The brief's indicators that no record on the platform holds yet. Listed on
#: the page; an index is not marked down for them and does not guess them.
NOT_COLLECTED = {
    "teacher": (
        "Share of a school's teachers trained (schools do not record how many "
        "teachers they have)",
        "Classroom practice adoption",
        "Lesson quality",
        "Teacher retention",
        "Teacher confidence",
    ),
    "leader": (
        "Financial management and planning adoption",
        "School governance and staff management",
    ),
}

MATURITY_LEVELS = (
    (1, "Forming"),
    (2, "Active"),
    (3, "Healthy"),
    (4, "High Impact"),
    (5, "Model Cluster"),
)
MATURITY_DEFAULTS = {
    #: Fewest parts a composite needs before it is given as a score.
    "min_dimensions": 3,
    "active_sessions": 2,
    "active_participation": 50,
    "healthy_health": 70,
    "healthy_ssa_improved": 50,
    "high_impact": 70,
    "model_health": 80,
    "model_impact": 80,
    "model_stories": 2,
}
MATURITY_LABELS = {
    "min_dimensions": "Fewest parts a score needs",
    "active_sessions": "Active: sessions held in the year",
    "active_participation": "Active: schools represented (%)",
    "healthy_health": "Healthy: Cluster Health at least",
    "healthy_ssa_improved": "Healthy: schools whose SSA improved (%)",
    "high_impact": "High Impact: Cluster Impact at least",
    "model_health": "Model Cluster: Cluster Health at least",
    "model_impact": "Model Cluster: Cluster Impact at least",
    "model_stories": "Model Cluster: approved change stories",
}

HIGH, MEDIUM = 70, 40


def band(score) -> tuple[str, str]:
    """High, Medium or Low (the brief's comparison table), with its tone."""
    if score is None:
        return "Not enough data", "neutral"
    if score >= HIGH:
        return "High", "success"
    if score >= MEDIUM:
        return "Medium", "warning"
    return "Low", "danger"


# ── Settings ─────────────────────────────────────────────────────────────────


@dataclass
class Settings:
    weights: dict[str, dict[str, float]]
    maturity: dict[str, float]
    set_by: str = ""
    set_at: object = None
    is_default: bool = True


def default_weights() -> dict[str, dict[str, float]]:
    return {
        key: {dim: float(weight) for dim, _label, weight in dimensions}
        for key, (_title, dimensions) in SCORES.items()
    }


def _clean_weights(key: str, stored) -> dict[str, float]:
    """The stored weights for one score, each part present and not negative.
    A part the stored row does not name keeps its default, so a part added
    later is counted rather than silently weighted zero."""
    weights = default_weights()[key]
    for dim, value in (stored or {}).items():
        if dim not in weights:
            continue
        try:
            weights[dim] = max(0.0, float(value))
        except (TypeError, ValueError):
            continue
    return weights


def current_settings() -> Settings:
    """The weights in force: the newest ``ClusterScoreSetting``, else the
    defaults. One query."""
    from .models import ClusterScoreSetting

    row = ClusterScoreSetting.objects.order_by("-created_at").first()
    if row is None:
        return Settings(weights=default_weights(), maturity=dict(MATURITY_DEFAULTS))
    maturity = dict(MATURITY_DEFAULTS)
    for key, value in (row.maturity_rules or {}).items():
        if key in maturity:
            try:
                maturity[key] = max(0.0, float(value))
            except (TypeError, ValueError):
                continue
    return Settings(
        weights={
            "health": _clean_weights("health", row.health_weights),
            "impact": _clean_weights("impact", row.impact_weights),
            "teacher": _clean_weights("teacher", row.teacher_weights),
            "leader": _clean_weights("leader", row.leader_weights),
        },
        maturity=maturity,
        set_by=row.set_by,
        set_at=row.created_at,
        is_default=False,
    )


def save_settings(*, weights: dict, maturity: dict, actor_id: str, note: str = ""):
    """Record new weights as a new row. A score whose weights are all zero
    would divide by nothing and mean nothing, so it is refused."""
    from apps.core.exceptions import BadRequest

    from .models import ClusterScoreSetting

    cleaned = {key: _clean_weights(key, weights.get(key)) for key in SCORES}
    for key, (title, _dimensions) in SCORES.items():
        if not any(cleaned[key].values()):
            raise BadRequest(f"{title} needs at least one part with a weight.")
    rules = dict(MATURITY_DEFAULTS)
    for key in rules:
        if key in (maturity or {}):
            try:
                rules[key] = max(0.0, float(maturity[key]))
            except (TypeError, ValueError):
                raise BadRequest(f"{MATURITY_LABELS[key]} must be a number.") from None
    return ClusterScoreSetting.objects.create(
        health_weights=cleaned["health"],
        impact_weights=cleaned["impact"],
        teacher_weights=cleaned["teacher"],
        leader_weights=cleaned["leader"],
        maturity_rules=rules,
        set_by=actor_id or "",
        note=(note or "").strip(),
    )


# ── A score and its parts ────────────────────────────────────────────────────


@dataclass
class Dimension:
    key: str
    label: str
    weight: float
    score: float | None = None
    basis: str = "Not measured yet"

    @property
    def is_scored(self) -> bool:
        return self.score is not None

    @property
    def display(self) -> str:
        return "—" if self.score is None else f"{round(self.score)}"


@dataclass
class Composite:
    key: str
    label: str
    dimensions: list[Dimension]
    min_dimensions: int = 3

    @property
    def scored(self) -> list[Dimension]:
        return [d for d in self.dimensions if d.is_scored and d.weight > 0]

    @property
    def score(self) -> int | None:
        parts = self.scored
        total = sum(d.weight for d in parts)
        if len(parts) < min(self.min_dimensions, len(self.dimensions)) or not total:
            return None
        return round(sum(d.score * d.weight for d in parts) / total)

    @property
    def band(self) -> tuple[str, str]:
        return band(self.score)

    @property
    def coverage(self) -> str:
        counted = [d for d in self.dimensions if d.weight > 0]
        return f"{len(self.scored)} of {len(counted)} parts measured"


def _share(part, whole) -> float | None:
    return round(100 * part / whole, 1) if whole else None


def _plural(n, word="school") -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _area_share(movement, area_key) -> tuple[float | None, str]:
    """Share of the compared schools that improved (or held a strong score)
    on one SSA area, with its basis."""
    area = next(a for a in movement["areas"] if a.key == area_key)
    if not area.compared:
        return None, "No school has a confirmed SSA in both years"
    better = area.improved + area.maintained_strong
    return (
        _share(better, area.compared),
        f"{better} of {_plural(area.compared)} improved, "
        f"FY {movement['previous_fy']} to FY {movement['fy']}",
    )


# ── The records a scorecard is read from ─────────────────────────────────────

_TRAINING_SESSIONS = ("cluster_training", "cluster_training_ssa_collection")


def _session_plan(cluster_ids, fy: str, today: date) -> dict[str, dict]:
    """Each cluster's meetings and group trainings in the year: how many were
    due by today, how many of those were delivered, and whether any is in the
    plan at all. One query. A cancelled, rejected or deferred session is not
    in anybody's plan and is not counted as due."""
    from apps.activities.models import Activity
    from apps.core.activity_types import NOT_IN_PLAN_ACTIVITY_STATUSES
    from apps.planning.school_planning_badges import (
        AWAITING_VERIFICATION_STATUSES,
        CLUSTER_SESSION_TYPES,
        VERIFIED_STATUSES,
    )

    delivered_statuses = AWAITING_VERIFICATION_STATUSES | VERIFIED_STATUSES
    plan = {
        cid: {
            "meetings": [0, 0],
            "trainings": [0, 0],
            "meeting_planned": False,
            "training_planned": False,
        }
        for cid in cluster_ids
    }
    if not plan:
        return plan
    for row in (
        Activity.objects.filter(
            cluster_id__in=list(plan),
            school__isnull=True,
            fy=fy,
            deleted_at__isnull=True,
            activity_type__in=CLUSTER_SESSION_TYPES,
        )
        .exclude(status__in=NOT_IN_PLAN_ACTIVITY_STATUSES)
        .values("cluster_id", "activity_type", "status", "planned_date")
    ):
        entry = plan[row["cluster_id"]]
        kind = "trainings" if row["activity_type"] in _TRAINING_SESSIONS else "meetings"
        entry[f"{kind[:-1]}_planned"] = True
        delivered = row["status"] in delivered_statuses
        due = delivered or (row["planned_date"] and row["planned_date"] <= today)
        if due:
            entry[kind][1] += 1
        if delivered:
            entry[kind][0] += 1
    return plan


def _funded_schools(members) -> dict[str, int]:
    """How many of each cluster's schools hold a funded loan.

    A count only — no lender, amount or record. The register keeps the records
    themselves to the roles it names (``scoped_loans``); a score has to be the
    same number for everyone who reads it, so it reads this minimised figure
    rather than the reader's own slice of the register.
    """
    from apps.business_transformation.models import MfiLoan

    school_cluster = {s["id"]: cid for cid, rows in members.items() for s in rows}
    counts = {cid: 0 for cid in members}
    if not school_cluster:
        return counts
    for school_id in (
        MfiLoan.objects.filter(
            school_id__in=list(school_cluster),
            deleted_at__isnull=True,
            status__in=outcomes._FUNDED,
        )
        .values_list("school_id", flat=True)
        .distinct()
    ):
        counts[school_cluster[school_id]] += 1
    return counts


def gather(cluster_ids, *, fy: str, principal=None, today: date | None = None) -> dict:
    """Every read a scorecard or a Cluster Management table needs, once.

    The same reads the cluster profile's tabs make, for all of ``cluster_ids``
    together. ``principal`` only decides which loan *records* are returned for
    display; no score depends on who is reading.
    """
    from django.utils import timezone

    cluster_ids = list(cluster_ids)
    fy = str(fy)
    today = today or timezone.localdate()
    members = insights.member_schools(cluster_ids)
    ssa_fy, movement = insights.ssa_movement_for_page(
        cluster_ids, fy=fy, members=members
    )
    return {
        "fy": fy,
        "today": today,
        "members": members,
        "attendance": insights.attendance_by_cluster(
            cluster_ids, fy=fy, members=members
        ),
        "ssa_fy": ssa_fy,
        "movement": movement,
        "enrolment": outcomes.enrolment_by_cluster(cluster_ids, fy=fy, members=members),
        "learning": outcomes.learning_by_cluster(cluster_ids, fy=fy, members=members),
        "loans": (
            outcomes.loans_by_cluster(cluster_ids, principal, members=members)
            if principal is not None
            else {cid: outcomes.LoanSummary() for cid in cluster_ids}
        ),
        "funded_schools": _funded_schools(members),
        "stories": outcomes.stories_by_cluster(cluster_ids, members=members),
        "plan": _session_plan(cluster_ids, fy, today),
    }


# ── Reading a scorecard from the records ─────────────────────────────────────


def trained_pairs(attendance, movement) -> list[dict]:
    """For each group training with a named SSA area, each member school that
    attended and can be compared on that area: did its score there rise?

    The trainings are those of the two years the SSA movement spans. This is
    the brief's "Training → participation → SSA improvement" as far as the
    records go: it shows what happened at the schools that took part, not what
    the training caused.
    """
    years = {movement["fy"], movement["previous_fy"]}
    by_area = movement["schools_by_area"]
    out = []
    for session in attendance["all_sessions"]:
        if not session.is_training or not session.area or session.fy not in years:
            continue
        rows = {r["id"]: r for r in by_area.get(session.area, [])}
        for school_id in session.attended_ids:
            row = rows.get(school_id)
            if row is None or row["verdict"] == insights.NOT_COMPARED:
                continue
            out.append(
                {
                    "session_id": session.id,
                    "course": session.name,
                    "area": session.area,
                    "school_id": school_id,
                    "change": row["change"],
                    "verdict": row["verdict"],
                    "better": row["verdict"]
                    in (change_rules.IMPROVED, change_rules.MAINTAINED_STRONG),
                }
            )
    return out


def _kind_attendance(attendance, member_ids, *, trainings: bool) -> tuple[int, int]:
    """(invitations kept, invitations) by member schools at this year's
    meetings, or at its group trainings."""
    kept = asked = 0
    for session in attendance["sessions"]:
        if session.is_training != trainings:
            continue
        asked += len(session.invited_ids & member_ids)
        kept += len(session.attended_ids & member_ids)
    return kept, asked


def _dimension_values(cid: str, facts: dict) -> dict[str, tuple[float | None, str]]:
    """Every part of every score for one cluster: (share out of 100, basis)."""
    attendance = facts["attendance"][cid]
    movement = facts["movement"][cid]
    plan = facts["plan"][cid]
    members = facts["members"].get(cid, [])
    member_ids = {s["id"] for s in members}
    school_count = len(members)
    fy = facts["fy"]
    none = (None, "Not measured yet")
    values: dict[str, tuple[float | None, str]] = {}

    for kind, word in (("meetings", "meeting"), ("trainings", "group training")):
        delivered, due = plan[kind]
        values[kind] = (
            (
                _share(delivered, due),
                f"{delivered} of {_plural(due, word)} due by now delivered, FY {fy}",
            )
            if due
            else (None, f"No {word} was due by now in FY {fy}")
        )

    values["attendance"] = (
        (
            float(attendance["rate"]),
            f"{attendance['attended_total']} of "
            f"{_plural(attendance['invited_total'], 'invitation')} kept, FY {fy}",
        )
        if attendance["rate"] is not None
        else (None, f"No invitation recorded in FY {fy}")
    )
    held = len(attendance["sessions"])
    values["participation"] = (
        (
            _share(attendance["represented"], school_count),
            f"{attendance['represented']} of {_plural(school_count)} came to at "
            f"least one session, FY {fy}",
        )
        if school_count and held
        else (None, f"No session with a register in FY {fy}")
    )
    planned = int(plan["meeting_planned"]) + int(plan["training_planned"])
    values["planning"] = (
        planned * 50.0,
        {
            0: f"No meeting or group training planned for FY {fy}",
            1: (
                f"A {'meeting' if plan['meeting_planned'] else 'group training'} "
                f"is planned for FY {fy}; no "
                f"{'group training' if plan['meeting_planned'] else 'meeting'}"
            ),
            2: f"A meeting and a group training are planned for FY {fy}",
        }[planned],
    )
    absent = len(attendance["drifting"])
    invited_ever = sum(1 for s in attendance["schools"] if s.invited or s.last_attended)
    values["follow_up"] = (
        (
            _share(school_count - absent, school_count),
            f"{_plural(absent)} absent from "
            f"{insights.MISSED_IN_A_ROW_ALERT} or more sessions in a row",
        )
        if school_count and (invited_ever or absent)
        else none
    )

    values["ssa"] = _area_share(movement, insights.OVERALL)
    pairs = trained_pairs(attendance, movement)
    better = sum(1 for p in pairs if p["better"])
    values["training_effect"] = (
        (
            _share(better, len(pairs)),
            f"{better} of {len(pairs)} trained-school readings rose in the area "
            "trained",
        )
        if pairs
        else (
            None,
            "No school attended a group training with a named SSA area and can "
            "be compared on it",
        )
    )
    kept, asked = _kind_attendance(attendance, member_ids, trainings=False)
    values["meeting_engagement"] = values["meeting_attendance"] = (
        (_share(kept, asked), f"{kept} of {_plural(asked, 'meeting invitation')} kept")
        if asked
        else (None, f"No meeting invitation recorded in FY {fy}")
    )
    kept, asked = _kind_attendance(attendance, member_ids, trainings=True)
    values["training_attendance"] = (
        (
            _share(kept, asked),
            f"{kept} of {_plural(asked, 'training invitation')} kept; "
            f"{_plural(attendance['teachers'], 'teacher')} reached",
        )
        if asked
        else (None, f"No group training invitation recorded in FY {fy}")
    )
    values["teaching_ssa"] = _area_share(movement, "teaching_environment")
    values["learning_env_ssa"] = _area_share(movement, "learning_environment")
    values["leadership_ssa"] = _area_share(movement, "leadership")
    values["finance_ssa"] = _area_share(movement, "financial_health")
    values["compliance_ssa"] = _area_share(movement, "government_requirement")

    enrolment = facts["enrolment"][cid]
    grew = sum(1 for r in enrolment.rows if (r["change"] or 0) > 0)
    values["enrolment"] = (
        (
            _share(grew, enrolment.compared),
            f"{grew} of {_plural(enrolment.compared)} grew, "
            f"FY {enrolment.previous_fy} to FY {enrolment.fy}",
        )
        if enrolment.compared
        else (None, "No school has an enrolment figure in both years")
    )
    learning = facts["learning"][cid]
    values["exams"] = (
        (
            _share(learning.improved, learning.compared),
            f"{learning.improved} of {_plural(learning.compared)} improved, "
            f"FY {learning.previous_fy} to FY {learning.fy}",
        )
        if learning.compared
        else (None, "No school has a confirmed learning result in both years")
    )
    bt_parts = [
        v[0]
        for v in (values["finance_ssa"], values["compliance_ssa"])
        if v[0] is not None
    ]
    values["bt"] = (
        (
            round(sum(bt_parts) / len(bt_parts), 1),
            "Schools improved on Financial Health and Government Requirements SSA",
        )
        if bt_parts
        else (
            None,
            "No school can be compared on Financial Health or Government Requirements",
        )
    )
    funded = facts["funded_schools"].get(cid, 0)
    values["loans"] = (
        (
            _share(funded, school_count),
            f"{funded} of {_plural(school_count)} hold a loan",
        )
        if school_count
        else none
    )
    return values


def _composite(key: str, values: dict, settings: Settings) -> Composite:
    title, dimensions = SCORES[key]
    weights = settings.weights[key]
    return Composite(
        key=key,
        label=title,
        dimensions=[
            Dimension(
                key=dim,
                label=label,
                weight=weights.get(dim, 0.0),
                score=values.get(dim, (None, ""))[0],
                basis=values.get(dim, (None, "Not measured yet"))[1],
            )
            for dim, label, _default in dimensions
        ],
        min_dimensions=int(settings.maturity["min_dimensions"]),
    )


@dataclass
class Scorecard:
    cluster_id: str
    health: Composite
    impact: Composite
    teacher: Composite
    leader: Composite
    maturity: dict = field(default_factory=dict)

    @property
    def composites(self) -> list[Composite]:
        return [self.health, self.impact, self.teacher, self.leader]


def _maturity(cid: str, facts: dict, card: Scorecard, settings: Settings) -> dict:
    """The cluster's level, and what each level asks against what it has.

    A level is reached only when every level below it is: a cluster with a
    high Impact score and no sessions this year is not a Model Cluster.
    """
    rules = settings.maturity
    attendance = facts["attendance"][cid]
    school_count = len(facts["members"].get(cid, []))
    sessions = len(attendance["sessions"])
    participation = _share(attendance["represented"], school_count) or 0
    ssa = next(d.score for d in card.impact.dimensions if d.key == "ssa")
    health, impact = card.health.score, card.impact.score
    stories = facts["stories"][cid].approved

    def at_least(value, floor) -> bool:
        return value is not None and value >= floor

    def shown(value, suffix="") -> str:
        return "not measured" if value is None else f"{round(value)}{suffix}"

    checks = [
        (
            1,
            school_count > 0,
            "The cluster has schools",
            _plural(school_count),
        ),
        (
            2,
            sessions >= rules["active_sessions"]
            and participation >= rules["active_participation"],
            f"{round(rules['active_sessions'])} sessions held in the year and "
            f"{round(rules['active_participation'])}% of schools represented",
            f"{_plural(sessions, 'session')}, {round(participation)}% represented",
        ),
        (
            3,
            at_least(health, rules["healthy_health"])
            and at_least(ssa, rules["healthy_ssa_improved"]),
            f"Cluster Health {round(rules['healthy_health'])} or more and "
            f"{round(rules['healthy_ssa_improved'])}% of schools' SSA improved",
            f"Health {shown(health)}, {shown(ssa, '%')} improved",
        ),
        (
            4,
            at_least(impact, rules["high_impact"]),
            f"Cluster Impact {round(rules['high_impact'])} or more",
            f"Impact {shown(impact)}",
        ),
        (
            5,
            at_least(health, rules["model_health"])
            and at_least(impact, rules["model_impact"])
            and stories >= rules["model_stories"],
            f"Health {round(rules['model_health'])} and Impact "
            f"{round(rules['model_impact'])} or more, with "
            f"{round(rules['model_stories'])} approved change stories",
            f"Health {shown(health)}, Impact {shown(impact)}, "
            f"{stories} approved stor{'y' if stories == 1 else 'ies'}",
        ),
    ]
    names = dict(MATURITY_LEVELS)
    level = 0
    criteria = []
    climbing = True
    for number, met, needs, has in checks:
        if climbing and met:
            level = number
        else:
            climbing = False
        criteria.append(
            {
                "level": number,
                "label": names[number],
                "met": bool(met),
                "reached": level >= number,
                "needs": needs,
                "has": has,
            }
        )
    return {
        "level": level,
        "label": names.get(level, "No schools yet"),
        "criteria": criteria,
        "next": next((c for c in criteria if not c["reached"]), None),
    }


def scorecards(
    cluster_ids, *, fy: str, facts=None, settings=None
) -> dict[str, Scorecard]:
    """Each cluster's scorecard, from ``facts`` (``gather``) when the caller
    already has them."""
    cluster_ids = list(cluster_ids)
    facts = facts or gather(cluster_ids, fy=fy)
    settings = settings or current_settings()
    cards = {}
    for cid in cluster_ids:
        values = _dimension_values(cid, facts)
        teacher = _composite("teacher", values, settings)
        leader = _composite("leader", values, settings)
        # The two indices are themselves parts of Cluster Impact.
        for key, index in (("teacher", teacher), ("leader", leader)):
            values[key] = (
                (float(index.score), f"{index.label} index, {index.coverage}")
                if index.score is not None
                else (None, f"{index.label} index has too few parts measured")
            )
        card = Scorecard(
            cluster_id=cid,
            health=_composite("health", values, settings),
            impact=_composite("impact", values, settings),
            teacher=teacher,
            leader=leader,
        )
        card.maturity = _maturity(cid, facts, card, settings)
        cards[cid] = card
    return cards


__all__ = [
    "Composite",
    "Dimension",
    "MATURITY_DEFAULTS",
    "MATURITY_LABELS",
    "MATURITY_LEVELS",
    "NOT_COLLECTED",
    "SCORES",
    "Scorecard",
    "Settings",
    "band",
    "current_settings",
    "default_weights",
    "gather",
    "save_settings",
    "scorecards",
    "trained_pairs",
]
