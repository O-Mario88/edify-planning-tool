"""Core School Intelligence: one read of every Core school's performance.

Owner, 2026-10-17, the Core School Intelligence brief: "Both views must use
the same authoritative data and analytical logic. They must not calculate
different answers for the same school." The Core School Profile and Core
School Oversight both read `performance`; every figure is defined in
docs/core-school-intelligence-metrics.md, and each is the platform's existing
reading of it, not a second one:

* SSA — the latest confirmed record of each year (`ssa.year_comparison`), and
  improved / declined by `ssa.change_rules` over the pairs every impact page
  reads (`impact_engine.improvement_rows`);
* the package — the school's Core plan and its 2 + 2 split
  (`core_schools.package_split`);
* participation — the cluster attendance register's delivered sessions, and
  in-school trainings, as headcounts (owner, 2026-10-17);
* outcomes — `clusters.outcomes`' enrolment and learning reads;
* Champion — `ChampionEligibilityService.scan`, the official rule (owner,
  2026-10-17), read without writing.

A missing figure is None and shows as a dash or a reason, never a zero. The
whole read is a fixed number of queries whatever the number of schools.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from apps.ssa import change_rules

TRAJECTORY_LABELS = {
    change_rules.IMPROVED: "Improved",
    change_rules.NO_CHANGE: "No Change",
    change_rules.MAINTAINED_STRONG: "Maintained Strong",
    change_rules.DECLINED: "Declined",
    change_rules.NOT_COMPARABLE: "Not Compared",
}
TRAJECTORY_TONES = {
    change_rules.IMPROVED: "success",
    change_rules.MAINTAINED_STRONG: "success",
    change_rules.NO_CHANGE: "neutral",
    change_rules.DECLINED: "danger",
    change_rules.NOT_COMPARABLE: "",
}

#: Champion readiness, beside the stored Not Eligible / Potential Champion /
#: Champion (owner, 2026-10-17).
CHAMPION = "Champion"
POTENTIAL = "Potential Champion"
PROGRESSING = "Progressing"
NOT_YET = "Not Yet Ready"
INSUFFICIENT = "Insufficient Evidence"
CHAMPION_ORDER = (CHAMPION, POTENTIAL, PROGRESSING, NOT_YET, INSUFFICIENT)
#: The official rule's SSA bar (`ChampionEligibilityService`).
CHAMPION_LATEST_AVG = 8.0

#: What a school is listed for, each from an existing rule.
DECLINED_REASON = "SSA declined"
CRITICAL_REASON = "Critical SSA area"
NO_SSA_REASON = "No current-year SSA"
PACKAGE_REASON = "Package incomplete"
HANDOVER_REASON = "Partner hand-over not scheduled"
CANDIDATE_REASON = "Champion candidate"
ATTENTION_ORDER = (
    DECLINED_REASON,
    CRITICAL_REASON,
    NO_SSA_REASON,
    HANDOVER_REASON,
    PACKAGE_REASON,
    CANDIDATE_REASON,
)

GROUPINGS = {
    "cceo": "CCEO",
    "district": "District",
    "sub_region": "Sub-region",
    "cluster": "Cluster",
}


@dataclass
class CoreSchoolPerformance:
    id: str
    code: str
    name: str
    school_type: str = "core"
    type_label: str = "Core"
    district: str = ""
    sub_region: str = ""
    cluster_id: str = ""
    cluster: str = ""
    owner_id: str = ""
    owner: str = "Unassigned"
    # SSA
    ssa_now: float | None = None
    ssa_before: float | None = None
    ssa_change: float | None = None
    trajectory: str = change_rules.NOT_COMPARABLE
    rule_label: str = ""
    weakest: str = ""
    weakest_label: str = ""
    weakest_score: float | None = None
    # Package
    has_plan: bool = False
    visits_done: int = 0
    visits_target: int = 0
    trainings_done: int = 0
    trainings_target: int = 0
    staff_visits: int | None = None
    partner_visits: int | None = None
    staff_trainings: int | None = None
    partner_trainings: int | None = None
    handovers_assigned: int = 0
    handovers_scheduled: int = 0
    handovers_completed: int = 0
    # Participation (headcounts)
    invited: int = 0
    attended: int = 0
    teacher_attendances: int | None = None
    leader_attendances: int | None = None
    # Outcomes
    enrol_before: int | None = None
    enrol_after: int | None = None
    learn_before: float | None = None
    learn_after: float | None = None
    # Champion
    champion: str = INSUFFICIENT
    champion_score: float | None = None
    #: The official rule's inputs (`ChampionEligibilityService`), for the
    #: profile's checklist; None where the rule cannot judge the school.
    champion_metrics: dict | None = None
    attention: list[str] = field(default_factory=list)

    @property
    def has_current_ssa(self) -> bool:
        return self.ssa_now is not None

    @property
    def trajectory_label(self) -> str:
        return TRAJECTORY_LABELS[self.trajectory]

    @property
    def trajectory_tone(self) -> str:
        return TRAJECTORY_TONES[self.trajectory]

    @property
    def package_complete(self) -> bool | None:
        if not self.has_plan:
            return None
        target = self.visits_target + self.trainings_target
        return target > 0 and (
            self.visits_done >= self.visits_target
            and self.trainings_done >= self.trainings_target
        )

    @property
    def package_pct(self) -> int | None:
        target = self.visits_target + self.trainings_target
        if not self.has_plan or not target:
            return None
        done = min(self.visits_done, self.visits_target) + min(
            self.trainings_done, self.trainings_target
        )
        return round(100 * done / target)

    @property
    def package_label(self) -> str:
        if not self.has_plan:
            return "No package"
        return f"{self.package_pct}%"

    @property
    def attendance_rate(self) -> int | None:
        return round(100 * self.attended / self.invited) if self.invited else None

    @property
    def enrol_change(self) -> int | None:
        if self.enrol_before is None or self.enrol_after is None:
            return None
        return self.enrol_after - self.enrol_before

    @property
    def enrol_growth_pct(self) -> float | None:
        from apps.clusters.outcomes import _growth_pct

        return _growth_pct(self.enrol_before, self.enrol_after)

    @property
    def learn_change(self) -> float | None:
        if self.learn_before is None or self.learn_after is None:
            return None
        return round(self.learn_after - self.learn_before, 1)


# ── Reading ──────────────────────────────────────────────────────────────────


def scoped_core_schools(principal):
    """The operating Core schools ``principal`` may analyse, as a queryset:
    Core, Core Trained, Core Graduate and Champion (the lifecycle Core School
    Oversight has always listed), in the scope it has always read."""
    from apps.core_schools.lifecycle import CORE_LIFECYCLE_TYPES
    from apps.core_schools.oversight_service import scoped_core_queryset
    from apps.schools.lifecycle_service import active_schools

    base = active_schools().filter(school_type__in=CORE_LIFECYCLE_TYPES)
    return scoped_core_queryset(principal, base).select_related("district")


def performance(schools, *, fy: str) -> dict[str, CoreSchoolPerformance]:
    """Each school's figures for ``fy``, by school id."""
    schools = list(schools)
    fy = str(fy)
    rows = {s.id: _identity(s) for s in schools}
    if not rows:
        return rows
    _read_names(rows, schools)
    _read_ssa(rows, fy)
    _read_package(rows, schools, fy)
    _read_handovers(rows, fy)
    _read_participation(rows, fy)
    _read_outcomes(rows, fy)
    _read_champion(rows, schools)
    for row in rows.values():
        row.attention = _attention(row)
    return rows


def _identity(school) -> CoreSchoolPerformance:
    return CoreSchoolPerformance(
        id=school.id,
        code=school.school_id or "",
        name=school.name,
        school_type=school.school_type or "",
        type_label=school.get_school_type_display() if school.school_type else "",
        district=getattr(school.district, "name", "") or "",
        cluster_id=school.cluster_id or "",
        owner_id=school.account_owner_id or "",
    )


def _read_names(rows, schools) -> None:
    """The CCEO, cluster and sub-region names: three queries for the set."""
    from apps.clusters.models import Cluster
    from apps.clusters.oversight_service import _label, _staff_directory
    from apps.geography.models import SubRegion

    directory = _staff_directory({r.owner_id for r in rows.values() if r.owner_id})
    clusters = dict(
        Cluster.objects.filter(
            id__in={r.cluster_id for r in rows.values() if r.cluster_id}
        ).values_list("id", "name")
    )
    sub_of = {s.id: s.sub_region_id for s in schools if s.sub_region_id}
    sub_regions = dict(
        SubRegion.objects.filter(id__in=set(sub_of.values())).values_list("id", "name")
    )
    for row in rows.values():
        owner = directory.get(row.owner_id)
        row.owner = _label(owner) if owner else "Unassigned"
        row.cluster = clusters.get(row.cluster_id, "")
        row.sub_region = sub_regions.get(sub_of.get(row.id), "")


def _read_ssa(rows, fy: str) -> None:
    from apps.analytics.impact_engine import improvement_rows
    from apps.core.enums import SsaIntervention
    from apps.schools.models import School
    from apps.ssa.year_comparison import school_current_scores, school_year_scores

    ids = list(rows)
    years = school_year_scores(ids, fy)
    now = school_current_scores(ids, fy)
    country = dict(
        School.objects.filter(id__in=ids).values_list("id", "region__country")
    )

    def country_for(school_id):
        return country.get(school_id) or ""

    book = change_rules.RuleBook()
    pairs = change_rules.classify_pairs(
        improvement_rows(ids, fy) or [], book=book, country_for=country_for
    )
    verdicts = change_rules.school_verdicts(pairs, book=book, country_for=country_for)
    labels = dict(SsaIntervention.choices)
    for school_id, row in rows.items():
        year = years.get(school_id, {})
        row.ssa_now = year.get("current")
        row.ssa_before = year.get("previous")
        verdict = verdicts.get(school_id)
        if verdict and verdict["classification"] != change_rules.NOT_COMPARABLE:
            row.trajectory = verdict["classification"]
            if verdict["mean_delta"] is not None:
                row.ssa_change = round(verdict["mean_delta"], 1)
            row.rule_label = verdict["rule_label"]
        areas = now.get(school_id, {}).get("areas", {})
        if areas:
            key = min(areas, key=lambda k: (areas[k], k))
            row.weakest = key
            row.weakest_label = labels.get(key, key.replace("_", " ").title())
            row.weakest_score = areas[key]


def _read_package(rows, schools, fy: str) -> None:
    from apps.core_schools.models import CorePlan
    from apps.core_schools.package_split import (
        PARTNER,
        STAFF,
        TRAINING,
        VISIT,
        package_splits,
    )

    by_key = {}
    for school in schools:
        by_key[school.id] = school.id
        if school.school_id:
            by_key[school.school_id] = school.id
    for plan in CorePlan.objects.filter(school_id__in=list(by_key), fy=fy):
        row = rows[by_key[plan.school_id]]
        row.has_plan = True
        row.visits_done = plan.visits_completed
        row.visits_target = plan.visits_target
        row.trainings_done = plan.trainings_completed
        row.trainings_target = plan.trainings_target
    for school_id, split in package_splits(schools, fy).items():
        if school_id not in rows or not split.has_package:
            continue
        row = rows[school_id]
        row.staff_visits = split.used(VISIT, STAFF)
        row.partner_visits = split.used(VISIT, PARTNER)
        row.staff_trainings = split.used(TRAINING, STAFF)
        row.partner_trainings = split.used(TRAINING, PARTNER)


def _read_handovers(rows, fy: str) -> None:
    """Partner hand-overs made in the year: a hand-over carries no year of
    its own, so the year it was made is the year it is read in."""
    from django.db.models import Count, Q

    from apps.core.fy import get_fy_date_range
    from apps.partners.models import PartnerAssignment

    start, end = get_fy_date_range(fy)
    scheduled = (
        PartnerAssignment.STATUS_SCHEDULED,
        PartnerAssignment.STATUS_PARTNER_SCHEDULED,
    )
    for found in (
        PartnerAssignment.objects.filter(
            school_id__in=list(rows), created_at__gte=start, created_at__lt=end
        )
        .values("school_id")
        .annotate(
            assigned=Count(
                "id", filter=Q(status__in=PartnerAssignment.UNSCHEDULED_STATUSES)
            ),
            scheduled=Count("id", filter=Q(status__in=scheduled)),
            completed=Count("id", filter=Q(status=PartnerAssignment.STATUS_COMPLETED)),
        )
    ):
        row = rows[found["school_id"]]
        row.handovers_assigned = found["assigned"]
        row.handovers_scheduled = found["scheduled"]
        row.handovers_completed = found["completed"]


def _delivered():
    """The statuses at which a session's register is final: the Cluster
    Profile attendance register's rule (`clusters.profile_insights`)."""
    from apps.planning.school_planning_badges import (
        AWAITING_VERIFICATION_STATUSES,
        VERIFIED_STATUSES,
    )

    return AWAITING_VERIFICATION_STATUSES | VERIFIED_STATUSES


def _add(current: int | None, value) -> int | None:
    if value is None:
        return current
    return (current or 0) + int(value)


def _read_participation(rows, fy: str) -> None:
    from apps.activities.models import Activity, ClusterActivityAttendance
    from apps.core.activity_types import TRAINING_TYPES
    from apps.planning.school_planning_badges import CLUSTER_SESSION_TYPES

    delivered = _delivered()
    for (
        invited,
        attended,
        school_id,
        teachers,
        leaders,
    ) in ClusterActivityAttendance.objects.filter(
        school_id__in=list(rows),
        activity__deleted_at__isnull=True,
        activity__activity_type__in=CLUSTER_SESSION_TYPES,
        activity__status__in=delivered,
        activity__fy=fy,
    ).values_list("invited", "attended", "school_id", "teachers", "leaders"):
        row = rows[school_id]
        if invited:
            row.invited += 1
            row.attended += 1 if attended else 0
        if attended:
            row.teacher_attendances = _add(row.teacher_attendances, teachers)
            row.leader_attendances = _add(row.leader_attendances, leaders)
    for school_id, teachers, leaders in (
        Activity.objects.filter(
            school_id__in=list(rows),
            deleted_at__isnull=True,
            activity_type__in=TRAINING_TYPES,
            status__in=delivered,
            fy=fy,
        )
        .exclude(activity_type__in=CLUSTER_SESSION_TYPES)
        .values_list("school_id", "teachers_attended", "leaders_attended")
    ):
        row = rows[school_id]
        row.teacher_attendances = _add(row.teacher_attendances, teachers)
        row.leader_attendances = _add(row.leader_attendances, leaders)


def _read_outcomes(rows, fy: str) -> None:
    from apps.clusters.outcomes import _school_scores
    from apps.schools.models import SchoolEnrollmentHistory

    previous = str(int(fy) - 1)
    ids = list(rows)
    for school_id, year, enrolment in SchoolEnrollmentHistory.objects.filter(
        school_id__in=ids, fy__in=[fy, previous]
    ).values_list("school_id", "fy", "enrollment"):
        if str(year) == fy:
            rows[school_id].enrol_after = enrolment
        else:
            rows[school_id].enrol_before = enrolment
    for school_id, years in _school_scores(ids, [fy, previous]).items():
        rows[school_id].learn_after = years.get(fy, {}).get("pct")
        rows[school_id].learn_before = years.get(previous, {}).get("pct")


def _read_champion(rows, schools) -> None:
    from apps.core_schools.champion_services import ChampionEligibilityService
    from apps.core_schools.models import CoreSchoolProfile

    id_of = {s.school_id: s.id for s in schools if s.school_id}
    stored = dict(
        CoreSchoolProfile.objects.filter(school_id__in=list(id_of)).values_list(
            "school_id", "champion_status"
        )
    )
    judged = {
        profile.school_id: metrics
        for profile, _school, metrics in ChampionEligibilityService.scan(list(id_of))
    }
    for row in rows.values():
        if row.school_type == "champion":
            row.champion = CHAMPION
    for code, school_id in id_of.items():
        row = rows[school_id]
        metrics = judged.get(code)
        row.champion_score = metrics["score"] if metrics else None
        row.champion_metrics = metrics
        if row.school_type == "champion" or stored.get(code) in (
            "Champion",
            "Approved Champion",
        ):
            row.champion = CHAMPION
        elif not row.has_plan or not row.has_current_ssa:
            row.champion = INSUFFICIENT
        elif metrics and metrics["eligible"]:
            row.champion = POTENTIAL
        elif (
            metrics and metrics["latest_avg"] >= CHAMPION_LATEST_AVG
        ) or row.trajectory == change_rules.IMPROVED:
            row.champion = PROGRESSING
        else:
            row.champion = NOT_YET


def _attention(row: CoreSchoolPerformance) -> list[str]:
    from apps.core.enums import ssa_score_band

    reasons = []
    if row.trajectory == change_rules.DECLINED:
        reasons.append(DECLINED_REASON)
    if (
        row.weakest_score is not None
        and ssa_score_band(row.weakest_score)[0] == "Critical"
    ):
        reasons.append(CRITICAL_REASON)
    if not row.has_current_ssa:
        reasons.append(NO_SSA_REASON)
    if row.handovers_assigned:
        reasons.append(HANDOVER_REASON)
    if row.package_complete is False:
        reasons.append(PACKAGE_REASON)
    if row.champion == POTENTIAL:
        reasons.append(CANDIDATE_REASON)
    return reasons


def interventions(school, *, fy: str) -> dict:
    """One school's eight SSA interventions in ``fy`` against the year
    before: each previous and latest score (the latest confirmed record of
    each year), the change and its `change_rules` verdict where the two
    readings are comparable, and the platform's band. The strongest and
    weakest now, and the largest gain and drop, are kept apart: the lowest
    area is not necessarily the one that fell most."""
    from apps.analytics.impact_engine import improvement_rows
    from apps.core.enums import SsaIntervention, ssa_score_band
    from apps.ssa.year_comparison import school_current_scores

    fy = str(fy)
    previous_fy = str(int(fy) - 1)
    now = school_current_scores([school.id], fy).get(school.id, {}).get("areas", {})
    before = (
        school_current_scores([school.id], previous_fy)
        .get(school.id, {})
        .get("areas", {})
    )
    country = getattr(getattr(school, "region", None), "country", "") or ""
    pairs = {
        pair["intervention"]: pair
        for pair in change_rules.classify_pairs(
            improvement_rows([school.id], fy) or [],
            book=change_rules.RuleBook(),
            country_for=lambda _school_id: country,
        )
    }
    rows = []
    for key, label in SsaIntervention.choices:
        pair = pairs.get(key)
        verdict = pair["classification"] if pair else change_rules.NOT_COMPARABLE
        latest = now.get(key)
        rows.append(
            {
                "key": key,
                "label": label,
                "previous": before.get(key),
                "latest": latest,
                "change": round(pair["delta"], 1) if pair else None,
                "verdict": verdict,
                "verdict_label": TRAJECTORY_LABELS[verdict],
                "tone": TRAJECTORY_TONES[verdict],
                "band": ssa_score_band(latest)[0] if latest is not None else "",
                "rule_label": pair["rule_label"] if pair else "",
            }
        )
    scored = [r for r in rows if r["latest"] is not None]
    moved = [r for r in rows if r["change"] is not None]
    gains = [r for r in moved if r["change"] > 0]
    drops = [r for r in moved if r["change"] < 0]
    return {
        "fy": fy,
        "previous_fy": previous_fy,
        "rows": rows,
        "strongest": max(scored, key=lambda r: (r["latest"], r["key"]))
        if scored
        else None,
        "weakest": min(scored, key=lambda r: (r["latest"], r["key"]))
        if scored
        else None,
        "largest_gain": max(gains, key=lambda r: (r["change"], r["key"]))
        if gains
        else None,
        "largest_drop": min(drops, key=lambda r: (r["change"], r["key"]))
        if drops
        else None,
        "improved": sum(1 for r in moved if r["verdict"] == change_rules.IMPROVED),
        "declined": sum(1 for r in moved if r["verdict"] == change_rules.DECLINED),
        "steady": sum(
            1
            for r in moved
            if r["verdict"] in (change_rules.NO_CHANGE, change_rules.MAINTAINED_STRONG)
        ),
        "not_compared": len(rows) - len(moved),
    }


def recommendations(schools) -> dict[str, list]:
    """Each school's recorded SSA recommendations still open or in hand, by
    rank (`ssa.recommendation_service`: one live record per need, its
    recommended catalogue training or why none is mapped, and its state).
    The Core pages show these records; they make none of their own, and
    reading them changes nothing. One query."""
    from apps.ssa.recommendation_models import (
        LIVE_STATES,
        RecommendationState,
        SsaRecommendation,
    )

    schools = list(schools)
    out: dict[str, list] = {s.id: [] for s in schools}
    for rec in (
        SsaRecommendation.objects.filter(
            school_id__in=list(out),
            state__in=[*LIVE_STATES, RecommendationState.PLANNED],
        )
        .select_related("recommended_item")
        .order_by("school_id", "rank", "intervention")
    ):
        out[rec.school_id].append(rec)
    return out


# ── Aggregating ──────────────────────────────────────────────────────────────


def _mean(values) -> float | None:
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 1) if values else None


def summarise(rows) -> dict:
    """A group's figures, each with the schools it rests on. A rate is its
    totals' ratio, never a mean of rates; an average is over the schools
    that have the figure."""
    rows = list(rows)
    compared = [r for r in rows if r.trajectory != change_rules.NOT_COMPARABLE]
    planned = [r for r in rows if r.has_plan]
    invited = sum(r.invited for r in rows)
    attended = sum(r.attended for r in rows)
    enrolled = [r for r in rows if r.enrol_change is not None]
    before = sum(r.enrol_before for r in enrolled)
    learning = [r.learn_change for r in rows if r.learn_change is not None]
    readiness: dict[str, int] = defaultdict(int)
    reasons: dict[str, int] = defaultdict(int)
    for r in rows:
        readiness[r.champion] += 1
        for reason in r.attention:
            reasons[reason] += 1
    steady = (change_rules.NO_CHANGE, change_rules.MAINTAINED_STRONG)
    return {
        "schools": len(rows),
        "with_current_ssa": sum(1 for r in rows if r.has_current_ssa),
        "avg_latest": _mean(r.ssa_now for r in rows),
        "compared": len(compared),
        "improved": sum(1 for r in compared if r.trajectory == change_rules.IMPROVED),
        "declined": sum(1 for r in compared if r.trajectory == change_rules.DECLINED),
        "steady": sum(1 for r in compared if r.trajectory in steady),
        "not_compared": len(rows) - len(compared),
        "avg_change": _mean(r.ssa_change for r in compared),
        "with_plan": len(planned),
        "package_complete": sum(1 for r in planned if r.package_complete),
        "visits_done": sum(min(r.visits_done, r.visits_target) for r in planned),
        "visits_target": sum(r.visits_target for r in planned),
        "trainings_done": sum(
            min(r.trainings_done, r.trainings_target) for r in planned
        ),
        "trainings_target": sum(r.trainings_target for r in planned),
        "staff_visits": sum(r.staff_visits or 0 for r in rows),
        "partner_visits": sum(r.partner_visits or 0 for r in rows),
        "handovers_assigned": sum(r.handovers_assigned for r in rows),
        "handovers_scheduled": sum(r.handovers_scheduled for r in rows),
        "handovers_completed": sum(r.handovers_completed for r in rows),
        "invited": invited,
        "attended": attended,
        "attendance_rate": round(100 * attended / invited) if invited else None,
        "teacher_attendances": sum(r.teacher_attendances or 0 for r in rows),
        "leader_attendances": sum(r.leader_attendances or 0 for r in rows),
        "enrol_compared": len(enrolled),
        "enrol_change": sum(r.enrol_change for r in enrolled) if enrolled else None,
        "enrol_growth_pct": (
            round(100 * sum(r.enrol_change for r in enrolled) / before, 1)
            if enrolled and before
            else None
        ),
        "learn_compared": len(learning),
        "learn_change": _mean(learning),
        "readiness": {key: readiness.get(key, 0) for key in CHAMPION_ORDER},
        "attention": {key: reasons.get(key, 0) for key in ATTENTION_ORDER},
        "needs_attention": sum(
            1 for r in rows if set(r.attention) - {CANDIDATE_REASON}
        ),
    }


def groups(rows, by: str) -> list[dict]:
    """The schools by CCEO, district, sub-region or cluster — each school in
    exactly one group, its own — with each group's summary, largest first."""
    buckets: dict[str, list] = defaultdict(list)
    for row in rows:
        buckets[_group_label(row, by)].append(row)
    return sorted(
        (
            {"label": label, "rows": members, "summary": summarise(members)}
            for label, members in buckets.items()
        ),
        key=lambda g: (-len(g["rows"]), g["label"]),
    )


def _group_label(row: CoreSchoolPerformance, by: str) -> str:
    value = {
        "cceo": row.owner,
        "district": row.district,
        "sub_region": row.sub_region,
        "cluster": row.cluster,
    }[by]
    return value or "Not recorded"
