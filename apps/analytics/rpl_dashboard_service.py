"""Regional Programme Lead dashboard — the regional CCE lead's operating view.

The owner described the role on 2026-09-12. The Regional Lead for
Christ-Centered Education gives strategic direction, coordination and
mentorship to the country programme teams of their region:

* Strategic guidance: regional CCE goals, and the KPIs training aligns to.
* Leadership and coaching: mentoring country Programme Leads so they build
  the capacity of their CCE Officers.
* Programme enhancement: training delivery, school follow-up and coaching
  practice across the operating countries.
* Collaboration and reporting: with the RVPs and the VP of CCE, on programme
  impact, regional priorities and strategic targets.

The page answers those four, in that order. It is a READ. The role plans,
approves and verifies nothing (apps/core/rbac.py), so every control here is a
link into the page where that work is done, never an action of its own.

The full role description followed (owner, 2026-09-13), and the page grew the
parts of it the platform holds data for: the SSA needs of each country's
schools and how far plans answer them ("using SSA data ... identify new
training priorities"), training quality from the lead's own observations and
the trainings delivered against each need, school networks and PLCs, the
meeting rhythm with Programme Leads, Country Directors, the RVP and the VP of
CCE, and the monthly report. The records behind the last three belong to the
lead (apps.cce_leadership) and carry no cost and no plan.

Every delivery figure is a fold of ``oversight_service.build_items``, the rows
Team Oversight lists, so a number on this page cannot disagree with the page
it drills into.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date

from django.db.models import Q

from apps.core.activity_types import (
    CLUSTER_MEETING_TYPES,
    SSA_TYPES,
    TRAINING_TYPES,
    VISIT_TYPES,
)
from apps.core.enums import ActivityType
from apps.planning import oversight_service as oversight


def _values(types) -> frozenset[str]:
    return frozenset(getattr(t, "value", t) for t in types)


# The coaching half of VISIT_TYPES. Named rather than redefined (see the rule
# at the top of apps/core/activity_types.py): this page asks a narrower
# question than "is this field contact?". The owner's "school follow-up and
# coaching practices" is the visits that go back to a school to support what a
# training started.
COACHING_FOLLOW_UP_TYPES = _values(
    (
        ActivityType.FOLLOW_UP_VISIT,
        ActivityType.COACHING_VISIT,
        ActivityType.TRAINING_FOLLOW_UP_VISIT,
        ActivityType.IN_SCHOOL_COACHING_VISIT,
        ActivityType.IN_SCHOOL_SUPPORT,
    )
)

# The programme's delivery families, in the order the role description names
# them. Anything unclaimed falls into the last row, so the rows always add up
# to the region's plan.
DELIVERY_FAMILIES: tuple[tuple[str, str, str, frozenset[str]], ...] = (
    (
        "training",
        "Teacher training",
        "Structured training delivered to teachers and school leaders.",
        _values(TRAINING_TYPES),
    ),
    (
        "coaching",
        "Coaching and follow-up",
        "Visits that return to a school to coach and follow up on training.",
        COACHING_FOLLOW_UP_TYPES,
    ),
    (
        "visits",
        "School visits",
        "Every other school visit, including SSA collection visits.",
        _values(VISIT_TYPES) - COACHING_FOLLOW_UP_TYPES,
    ),
    (
        "cluster",
        "Cluster meetings",
        "Convening a cluster of schools rather than visiting one.",
        _values(CLUSTER_MEETING_TYPES),
    ),
    (
        "ssa",
        "SSA assessment",
        "School self-assessment work that is not itself a visit.",
        _values(SSA_TYPES),
    ),
)
OTHER_FAMILY = (
    "other",
    "Partner and other work",
    "Partner activities, programme events and any other planned work.",
)

# Below this share of due work delivered, a team or a region is flagged.
EXECUTION_WARNING_PCT = 80
EXECUTION_DANGER_PCT = 50

# How many rows each list shows before sending the reader to the full page.
FOLLOW_UP_ROWS = 5
LEAD_ROWS = 60


def _initials(name: str) -> str:
    parts = [p for p in (name or "").replace(".", " ").split() if p]
    return "".join(p[0].upper() for p in parts[:2]) or "PL"


def _fold(items) -> dict:
    """The headline figures of a group of items — `summarize`, renamed for a
    table row. No second calculation."""
    summary = oversight.summarize(items)
    return {
        "planned": summary["total_planned"],
        "completed": summary["completed"],
        "due": summary["due_count"],
        "execution": summary["execution_progress"],
        "at_risk": summary["at_risk"],
        "awaiting_verification": summary["awaiting_verification"],
        "budget": summary["planned_budget"],
    }


def _tone(fold: dict) -> str:
    """The row's state, in the order a coach would raise it."""
    if not fold["planned"]:
        return "neutral"
    execution = fold["execution"]
    if (execution is not None and execution < EXECUTION_DANGER_PCT) or (
        fold["at_risk"] * 4 >= fold["planned"]
    ):
        return "danger"
    if (execution is not None and execution < EXECUTION_WARNING_PCT) or fold["at_risk"]:
        return "warning"
    return "success"


_TONE_LABELS = {
    "neutral": "No plan yet",
    "danger": "Needs coaching",
    "warning": "Watch",
    "success": "On track",
}


def _family_of(activity_type: str) -> str:
    for key, _label, _hint, members in DELIVERY_FAMILIES:
        if activity_type in members:
            return key
    return OTHER_FAMILY[0]


# ── Countries of the plan ────────────────────────────────────────────────────
def _item_countries(items) -> list[str]:
    """Each item's country, in two queries rather than one per row.

    Oversight items carry the school's region but not its country, and the
    oversight query does not load it, so reading it off each row would be a
    query per activity. A school's country is its region's; cluster work with
    no school takes its cluster's district's region, or the cluster's own.
    """
    from apps.clusters.models import Cluster
    from apps.schools.models import School

    school_ids = {i.school_id for i in items if i.school_id}
    cluster_ids = {i.cluster_id for i in items if i.cluster_id and not i.school_id}
    by_school = (
        dict(
            School.objects.filter(id__in=school_ids).values_list(
                "id", "region__country"
            )
        )
        if school_ids
        else {}
    )
    by_cluster = {}
    if cluster_ids:
        for cluster_id, district_country, region_country in Cluster.objects.filter(
            id__in=cluster_ids
        ).values_list("id", "district__region__country", "region__country"):
            by_cluster[cluster_id] = district_country or region_country or ""
    return [
        (
            by_school.get(i.school_id)
            if i.school_id
            else by_cluster.get(i.cluster_id, "")
        )
        or ""
        for i in items
    ]


# ── Reach ────────────────────────────────────────────────────────────────────
def _reach(user) -> dict:
    """The countries this lead oversees and who works in them."""
    from apps.accounts.models import StaffProfile
    from apps.core.scoping import resolve_user_scope
    from apps.schools.models import School

    scope = resolve_user_scope(user)
    countries = list(scope.region_countries or ())
    region_ids = list(scope.region_ids or ())
    active = StaffProfile.objects.filter(
        user__status="active", user__deleted_at__isnull=True
    )
    if countries:
        active = active.filter(country__in=countries)
    return {
        "countries": countries,
        "assigned": bool(scope.region_assigned),
        "region_ids": region_ids,
        "lead_count": active.filter(user__roles__contains=["Program Lead"]).count(),
        "officer_count": active.filter(user__roles__contains=["CCEO"]).count(),
        "school_count": School.objects.filter(
            deleted_at__isnull=True, region_id__in=region_ids
        ).count()
        if region_ids
        else 0,
    }


# ── Programme Leads ──────────────────────────────────────────────────────────
def _lead_directory(item_lead_ids: set[str], countries: list[str]) -> dict:
    """Every Programme Lead in reach, plus any Lead the plan names.

    A Lead whose team planned nothing is exactly the Lead a coach needs to
    call, so the roster starts from the people rather than from the plan.
    """
    from django.db.models import Count, Q

    from apps.accounts.models import StaffProfile, StaffSupervisorAssignment

    in_reach = Q(
        user__status="active",
        user__deleted_at__isnull=True,
        user__roles__contains=["Program Lead"],
    )
    if countries:
        in_reach &= Q(country__in=countries)
    named = Q(id__in=[i for i in item_lead_ids if i])
    profiles = StaffProfile.objects.filter(in_reach | named).select_related("user")
    leads = {
        p.id: {
            "staff_id": p.id,
            "user_id": p.user_id,
            "name": getattr(p.user, "name", "") or getattr(p.user, "email", ""),
            "country": p.country or "",
        }
        for p in profiles
    }
    team_sizes = dict(
        StaffSupervisorAssignment.objects.filter(
            supervisor_id__in=leads.keys(),
            supervisee__user__status="active",
            supervisee__user__deleted_at__isnull=True,
        )
        .values("supervisor_id")
        .annotate(n=Count("supervisee_id", distinct=True))
        .values_list("supervisor_id", "n")
    )
    for staff_id, lead in leads.items():
        lead["team_size"] = team_sizes.get(staff_id, 0)
    return leads


def _lead_roster(
    pairs, *, countries, fy, follow_ups_by_lead, last_coaching=None
) -> dict:
    by_lead: dict[str, list] = defaultdict(list)
    for item, country in pairs:
        by_lead[item.supervising_pl_id or ""].append((item, country))
    unassigned = [item for item, _country in by_lead.pop("", [])]
    leads = _lead_directory(set(by_lead), countries)

    rows = []
    for staff_id, lead in leads.items():
        lead_pairs = by_lead.get(staff_id, [])
        lead_items = [item for item, _country in lead_pairs]
        fold = _fold(lead_items)
        tone = _tone(fold)
        officer_ids = {
            i.operational_owner_id for i in lead_items if i.operational_owner_id
        }
        item_countries = Counter(country for _item, country in lead_pairs if country)
        rows.append(
            {
                **lead,
                **fold,
                "initials": _initials(lead["name"]),
                "country": lead["country"]
                or (item_countries.most_common(1)[0][0] if item_countries else ""),
                "active_officers": len(officer_ids),
                "tone": tone,
                "tone_label": _TONE_LABELS[tone],
                "open_follow_ups": follow_ups_by_lead.get(staff_id, 0),
                "last_coaching": (last_coaching or {}).get(staff_id),
                "oversight_url": (
                    f"/team-planning-oversight/?program_lead={staff_id}&fy={fy}"
                ),
            }
        )
    severity = {"danger": 0, "warning": 1, "neutral": 2, "success": 3}
    rows.sort(
        key=lambda r: (
            severity[r["tone"]],
            -(r["at_risk"] or 0),
            r["execution"] if r["execution"] is not None else 101,
            r["name"],
        )
    )
    return {
        "rows": rows[:LEAD_ROWS],
        "total": len(rows),
        "needs_coaching": sum(1 for r in rows if r["tone"] == "danger"),
        "unassigned": _fold(unassigned) if unassigned else None,
        "unassigned_url": (
            f"/team-planning-oversight/?program_lead=unassigned&fy={fy}"
        ),
    }


# ── Delivery mix ─────────────────────────────────────────────────────────────
def _delivery_mix(items) -> list[dict]:
    buckets: dict[str, list] = defaultdict(list)
    for item in items:
        buckets[_family_of(item.activity_type)].append(item)
    families = [(key, label, hint) for key, label, hint, _m in DELIVERY_FAMILIES]
    families.append(OTHER_FAMILY)
    rows = []
    for key, label, hint in families:
        fold = _fold(buckets.get(key, []))
        if key == OTHER_FAMILY[0] and not fold["planned"]:
            continue
        completed_pct = (
            round(fold["completed"] * 100 / fold["planned"]) if fold["planned"] else 0
        )
        rows.append(
            {
                "key": key,
                "label": label,
                "hint": hint,
                **fold,
                "completed_pct": min(completed_pct, 100),
                "tone": _tone(fold),
            }
        )
    return rows


# ── Countries ────────────────────────────────────────────────────────────────
def _countries(pairs, *, countries, ssa_by_country) -> list[dict]:
    by_country: dict[str, list] = defaultdict(list)
    for item, country in pairs:
        by_country[country].append(item)
    names = list(dict.fromkeys([*countries, *sorted(k for k in by_country if k)]))
    if by_country.get(""):
        # Work whose school or cluster names no country is still the region's
        # work; it is listed last rather than dropped from the totals.
        names.append("")
    rows = []
    for name in names:
        country_items = by_country.get(name, [])
        fold = _fold(country_items)
        rows.append(
            {
                "name": name,
                **fold,
                "tone": _tone(fold),
                "leads": len(
                    {i.supervising_pl_id for i in country_items if i.supervising_pl_id}
                ),
                "officers": len(
                    {
                        i.operational_owner_id
                        for i in country_items
                        if i.operational_owner_id
                    }
                ),
                "schools_reached": len(
                    {i.school_id for i in country_items if i.school_id}
                ),
                "ssa": ssa_by_country.get(name),
            }
        )
    return rows


# ── Regional priorities ──────────────────────────────────────────────────────
def _regional_priorities(fy: str) -> dict:
    """The regional priorities and how far the plan has carried them.

    The regional cycle can run ahead of the operating year (dev data holds the
    FY2027 regional plan while FY2026 is being delivered), so a year with no
    regional priorities shows the most recent cycle and says which one.
    """
    from django.db.models import Count

    from apps.hr.models import StrategicPriority
    from apps.hr.target_distribution import (
        classify_achievement,
        milestone_plan_progress,
    )

    regional = StrategicPriority.objects.filter(level="regional").exclude(
        status="archived"
    )
    shown_fy = (
        fy
        if regional.filter(fy=fy).exists()
        else regional.order_by("-fy").values_list("fy", flat=True).first()
    )
    if not shown_fy:
        return {"fy": fy, "shown_fy": None, "rows": []}

    priorities = list(
        regional.filter(fy=shown_fy)
        .annotate(country_translations=Count("translations", distinct=True))
        .order_by("sequence", "title")
        .prefetch_related("milestones")
    )
    milestones = [m for p in priorities for m in p.milestones.all()]
    progress = milestone_plan_progress(milestones, fy=shown_fy)

    rows = []
    for priority in priorities:
        own = [progress[m.id] for m in priority.milestones.all() if m.id in progress]
        pcts = [p["pct"] for p in own if p["pct"] is not None]
        planned_pcts = [p["planned_pct"] for p in own if p["planned_pct"] is not None]
        has_work = any(p["has_work"] for p in own)
        pct = round(sum(pcts) / len(pcts), 1) if pcts else None
        on_track = sum(
            1 for p in own if (p.get("classification") or {}).get("tone") == "success"
        )
        rows.append(
            {
                "id": priority.id,
                "title": priority.title,
                "status": priority.get_status_display(),
                "is_published": priority.status == "published",
                "milestones": len(priority.milestones.all()),
                "measured": len(own),
                "on_track": on_track,
                "country_translations": priority.country_translations,
                # Shaped like one milestone_plan_progress entry so the shared
                # meter draws it. Counts are milestones, because a priority's
                # milestones measure schools, teachers and activities, and
                # adding those together would mean nothing.
                "progress": None
                if not own
                else {
                    "unit": "milestones",
                    "target": len(own) or None,
                    "planned": sum(1 for p in own if p["planned"]),
                    "completed": sum(1 for p in own if p["completed"]),
                    "verified": None,
                    "year": shown_fy,
                    "has_work": has_work,
                    "started": all(p["started"] for p in own) if own else True,
                    "pct": pct,
                    "planned_pct": (
                        round(sum(planned_pcts) / len(planned_pcts), 1)
                        if planned_pcts
                        else None
                    ),
                    "classification": (
                        classify_achievement(pct)
                        if pct is not None and has_work
                        else None
                    ),
                },
            }
        )
    return {"fy": fy, "shown_fy": shown_fy, "rows": rows}


# ── Follow-ups ───────────────────────────────────────────────────────────────
def _follow_ups(user, *, fy: str) -> dict:
    """The follow-ups this lead has sent, and where each one stands."""
    from apps.accounts.models import StaffProfile
    from apps.accounts.models import User
    from apps.planning.action_models import ACTIVE_STATES, ActionState, TeamAction

    today = date.today()
    sent = TeamAction.objects.filter(sender_id=user.id)
    active = list(
        sent.filter(state__in=ACTIVE_STATES).order_by("due_date", "-detected_at")[:200]
    )
    overdue = [
        a
        for a in active
        if a.state == ActionState.OVERDUE or (a.due_date and a.due_date < today)
    ]
    resolved = sent.filter(state=ActionState.RESOLVED, fy=fy).count()

    recipient_ids = {a.recipient_id for a in active}
    names = dict(User.objects.filter(id__in=recipient_ids).values_list("id", "name"))
    lead_of_user = dict(
        StaffProfile.objects.filter(user_id__in=recipient_ids).values_list(
            "user_id", "id"
        )
    )
    by_lead: Counter = Counter(
        lead_of_user.get(a.recipient_id) for a in active if a.recipient_id
    )
    rows = [
        {
            "recipient": names.get(a.recipient_id) or "Unknown recipient",
            "action": a.requested_action
            or (a.issue_type or "").replace("_", " ").capitalize(),
            "due_date": a.due_date,
            "is_overdue": a in overdue,
            "state": a.get_state_display(),
        }
        for a in active[:FOLLOW_UP_ROWS]
    ]
    return {
        "active": len(active),
        "overdue": len(overdue),
        "resolved": resolved,
        "rows": rows,
        "by_lead": {k: v for k, v in by_lead.items() if k},
    }


# ── SSA needs and training priorities ────────────────────────────────────────
TOP_NEEDS = 3
NEEDS_PER_COUNTRY = 3


def _ssa_needs(reach: dict, fy: str) -> dict:
    """What each country's schools most need, and how far plans answer it.

    A school's needs are its three weakest interventions on its latest
    confirmed SSA, read by the one bulk rule every list view uses
    (`bulk_weakest`). A country's priorities are the interventions most often
    among its schools' needs; its plans are the year's live plans, judged when
    they were made (apps.ssa.plan_alignment).
    """
    from apps.activities.models import Activity
    from apps.cce_leadership.services import activities_in_countries
    from apps.core.interventions import INTERVENTION_LABELS, intervention_abbr
    from apps.schools.models import School
    from apps.ssa.plan_alignment import INFORMED, LIVE_PLAN_STATUSES
    from apps.ssa.recommendation_engine import bulk_weakest
    from apps.ssa.recommendation_models import RecommendationState, SsaRecommendation

    countries = reach["countries"]
    country_of = (
        dict(
            School.objects.filter(
                deleted_at__isnull=True, region_id__in=reach["region_ids"]
            ).values_list("id", "region__country")
        )
        if reach["region_ids"]
        else {}
    )
    schools_by_country: Counter = Counter(c or "" for c in country_of.values())
    assessed: Counter = Counter()
    needs: dict[str, Counter] = defaultdict(Counter)
    for school_id, weakest in bulk_weakest(list(country_of), n=TOP_NEEDS).items():
        country = country_of.get(school_id) or ""
        assessed[country] += 1
        for row in weakest:
            needs[country][row["intervention"]] += 1

    plans: dict[str, Counter] = defaultdict(Counter)
    if countries:
        for alignment, school_country, cluster_country, region_country in (
            Activity.objects.filter(
                activities_in_countries(countries),
                deleted_at__isnull=True,
                fy=fy,
                status__in=LIVE_PLAN_STATUSES,
            )
            .exclude(ssa_alignment="")
            .values_list(
                "ssa_alignment",
                "school__region__country",
                "cluster__district__region__country",
                "cluster__region__country",
            )
        ):
            country = school_country or cluster_country or region_country or ""
            plans[country]["judged"] += 1
            plans[country]["informed"] += alignment in INFORMED
            plans[country][alignment] += 1

    open_needs: Counter = Counter()
    if countries:
        open_needs.update(
            country or ""
            for country in SsaRecommendation.objects.filter(
                school__region__country__in=countries,
                state__in=(
                    RecommendationState.GENERATED,
                    RecommendationState.ACCEPTED,
                    RecommendationState.DEFERRED,
                ),
            ).values_list("school__region__country", flat=True)
        )

    def priorities(counter: Counter, base: int) -> list[dict]:
        ranked = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
        return [
            {
                "code": code,
                "label": INTERVENTION_LABELS.get(code, code),
                "abbr": intervention_abbr(code),
                "schools": count,
                "share": round(count * 100 / base) if base else 0,
            }
            for code, count in ranked[:NEEDS_PER_COUNTRY]
        ]

    rows = []
    for country in countries:
        judged = plans[country]["judged"]
        rows.append(
            {
                "country": country,
                "schools": schools_by_country.get(country, 0),
                "assessed": assessed.get(country, 0),
                "priorities": priorities(needs[country], assessed.get(country, 0)),
                "plans_judged": judged,
                "informed_pct": (
                    round(plans[country]["informed"] * 100 / judged) if judged else None
                ),
                "off_priority": plans[country]["off_priority"],
                "no_focus": plans[country]["no_focus"],
                "open_recommendations": open_needs.get(country, 0),
            }
        )
    region_needs: Counter = Counter()
    for counter in needs.values():
        region_needs.update(counter)
    judged = sum(plans[c]["judged"] for c in countries)
    informed = sum(plans[c]["informed"] for c in countries)
    total_assessed = sum(assessed.values())
    return {
        "rows": rows,
        "region": {
            "assessed": total_assessed,
            "schools": sum(schools_by_country.values()),
            "priorities": priorities(region_needs, total_assessed),
            "plans_judged": judged,
            "informed_pct": round(informed * 100 / judged) if judged else None,
            "off_priority": sum(plans[c]["off_priority"] for c in countries),
            "open_recommendations": sum(open_needs.values()),
        },
    }


# ── Training quality ─────────────────────────────────────────────────────────
def _training_quality(user, reach: dict, fy: str) -> dict:
    """Trainings planned and delivered against each SSA need, and what the
    lead's own observations say about their quality."""
    from apps.activities.models import Activity
    from apps.cce_leadership.models import ObservationRecommendation
    from apps.cce_leadership.services import (
        activities_in_countries,
        observation_summary,
        training_label,
    )
    from apps.core.activity_types import COMPLETED_WORK_STATUSES, TRAINING_TYPES
    from apps.core.interventions import INTERVENTION_LABELS
    from apps.ssa.plan_alignment import LIVE_PLAN_STATUSES

    by_focus: dict[str, Counter] = defaultdict(Counter)
    if reach["countries"]:
        for focus, status in (
            Activity.objects.filter(
                activities_in_countries(reach["countries"]),
                deleted_at__isnull=True,
                fy=fy,
                activity_type__in=[str(t) for t in TRAINING_TYPES],
            )
            .filter(
                Q(status__in=LIVE_PLAN_STATUSES) | Q(status__in=COMPLETED_WORK_STATUSES)
            )
            .values_list("focus_intervention", "status")
        ):
            key = focus or ""
            by_focus[key]["planned"] += 1
            by_focus[key]["delivered"] += status in COMPLETED_WORK_STATUSES
    rows = [
        {
            "code": code,
            "label": INTERVENTION_LABELS.get(code, "No intervention named"),
            "planned": counts["planned"],
            "delivered": counts["delivered"],
            "delivered_pct": (
                round(counts["delivered"] * 100 / counts["planned"])
                if counts["planned"]
                else 0
            ),
        }
        for code, counts in sorted(
            by_focus.items(), key=lambda kv: (kv[0] == "", -kv[1]["planned"], kv[0])
        )
    ]
    observations = observation_summary(user, fy=fy)
    labels = dict(ObservationRecommendation.choices)
    latest = [
        {
            "id": o.id,
            "held_on": o.held_on,
            "training": training_label(o.activity) if o.activity_id else o.subject,
            "country": o.country,
            "average_rating": o.average_rating,
            "recommendation": labels.get(o.recommendation, ""),
            "state": (
                "Acknowledged"
                if o.acknowledged_at
                else "Shared"
                if o.feedback_shared_at
                else "Not shared yet"
            ),
            "tone": (
                "success"
                if o.acknowledged_at
                else "warning"
                if o.feedback_shared_at
                else "neutral"
            ),
        }
        for o in observations["rows"]
    ]
    return {
        "rows": rows,
        "planned": sum(r["planned"] for r in rows),
        "delivered": sum(r["delivered"] for r in rows),
        "observed": observations["count"],
        "average_rating": observations["average_rating"],
        "unshared": observations["unshared"],
        "awaiting_acknowledgement": observations["awaiting_acknowledgement"],
        "recommendations": [
            {"label": labels[value], "count": count}
            for value, count in observations["recommendations"].items()
            if count
        ],
        "latest": latest,
    }


# ── School networks and PLCs ─────────────────────────────────────────────────
NETWORK_ACTIVE_DAYS = 90


def _networks(reach: dict, *, today: date) -> dict:
    """Clusters are the platform's school networks and professional learning
    communities: whether each country's clusters are meeting, and how many
    schools come."""
    from datetime import timedelta

    from django.db.models import Count

    from apps.activities.models import Activity, ClusterActivityAttendance
    from apps.clusters.models import Cluster
    from apps.core.activity_types import CLUSTER_MEETING_TYPES, COMPLETED_WORK_STATUSES
    from apps.core.enums import ActivityType, ClusterRecordStatus
    from apps.schools.models import School

    countries = reach["countries"]
    if not countries:
        return {"rows": [], "region": None, "days": NETWORK_ACTIVE_DAYS}
    in_countries = Q(district__region__country__in=countries) | Q(
        district__isnull=True, region__country__in=countries
    )
    clusters = {
        cluster_id: district_country or region_country or ""
        for cluster_id, district_country, region_country in Cluster.objects.filter(
            in_countries,
            deleted_at__isnull=True,
            status=ClusterRecordStatus.ACTIVE,
        ).values_list("id", "district__region__country", "region__country")
    }
    session_types = [str(t) for t in CLUSTER_MEETING_TYPES] + [
        ActivityType.CLUSTER_TRAINING.value,
        ActivityType.CLUSTER_TRAINING_SSA_COLLECTION.value,
    ]
    sessions = list(
        Activity.objects.filter(
            cluster_id__in=list(clusters),
            deleted_at__isnull=True,
            activity_type__in=session_types,
            status__in=COMPLETED_WORK_STATUSES,
            planned_date__gte=today - timedelta(days=NETWORK_ACTIVE_DAYS),
            planned_date__lte=today,
        ).values_list("id", "cluster_id")
    )
    attended = dict(
        ClusterActivityAttendance.objects.filter(
            activity_id__in=[sid for sid, _c in sessions], attended=True
        )
        .values("activity_id")
        .annotate(n=Count("id"))
        .order_by()
        .values_list("activity_id", "n")
    )
    schools = defaultdict(Counter)
    for country, status in School.objects.filter(
        deleted_at__isnull=True, region_id__in=reach["region_ids"]
    ).values_list("region__country", "cluster_status"):
        schools[country or ""]["total"] += 1
        schools[country or ""]["clustered"] += status == "clustered"

    def fold(country_filter):
        ids = {cid for cid, country in clusters.items() if country_filter(country)}
        country_sessions = [(sid, cid) for sid, cid in sessions if cid in ids]
        meeting = {cid for _sid, cid in country_sessions}
        counts = [attended.get(sid, 0) for sid, _cid in country_sessions]
        with_attendance = [n for n in counts if n]
        return {
            "clusters": len(ids),
            "meeting": len(meeting),
            "quiet": len(ids) - len(meeting),
            "sessions": len(country_sessions),
            "average_schools": (
                round(sum(with_attendance) / len(with_attendance), 1)
                if with_attendance
                else None
            ),
        }

    rows = []
    for country in countries:
        total = schools[country]["total"]
        rows.append(
            {
                "country": country,
                **fold(lambda c, country=country: c == country),
                "schools": total,
                "clustered_pct": (
                    round(schools[country]["clustered"] * 100 / total)
                    if total
                    else None
                ),
            }
        )
    total = sum(schools[c]["total"] for c in countries)
    return {
        "rows": rows,
        "region": {
            **fold(lambda c: True),
            "schools": total,
            "clustered_pct": (
                round(sum(schools[c]["clustered"] for c in countries) * 100 / total)
                if total
                else None
            ),
        },
        "days": NETWORK_ACTIVE_DAYS,
    }


# ── Attention ────────────────────────────────────────────────────────────────
def _attention(
    *, summary, roster, follow_ups, fy, rhythm=None, report=None
) -> list[dict]:
    cards = []
    if report and report["previous_overdue"]:
        period = report["previous_period"]
        cards.append(
            {
                "tone": "danger",
                "title": f"{period:%B} CCE report not submitted",
                "body": (
                    f"It was due to the RVP and the VP of CCE by "
                    f"{report['previous_due_by']:%-d %B}."
                ),
                "action": "Open monthly reports",
                "url": "/cce-leadership/reports",
            }
        )
    worst = next((r for r in roster["rows"] if r["tone"] == "danger"), None)
    if worst:
        cards.append(
            {
                "tone": "danger",
                "title": f"{worst['name']} needs coaching",
                "body": (
                    f"{worst['at_risk']} of {worst['planned']} planned activities at risk"
                    + (
                        f"; {worst['execution']}% of due work delivered."
                        if worst["execution"] is not None
                        else "."
                    )
                ),
                "action": "Open their team plan",
                "url": worst["oversight_url"],
            }
        )
    if rhythm and rhythm["counts"]["attention"]:
        slipped = [r for r in rhythm["rows"] if r["state"] in ("overdue", "missed")]
        first = slipped[0]
        count = len(slipped)
        cards.append(
            {
                "tone": "danger",
                "title": f"{count} engagement{'s' if count != 1 else ''} overdue",
                "body": (
                    f"{first['label']} · {first['subject']}"
                    + (f": {first['note']}." if first["note"] else ".")
                ),
                "action": "Open the engagement log",
                "url": "/cce-leadership/engagements",
            }
        )
    if follow_ups["overdue"]:
        cards.append(
            {
                "tone": "danger",
                "title": f"{follow_ups['overdue']} follow-up"
                f"{'s' if follow_ups['overdue'] != 1 else ''} past due",
                "body": "A Programme Lead has not closed an action you sent.",
                "action": "Review actions sent",
                "url": "/actions/sent",
            }
        )
    if roster["unassigned"]:
        count = roster["unassigned"]["planned"]
        cards.append(
            {
                "tone": "warning",
                "title": f"{count} activit{'ies' if count != 1 else 'y'} without a Programme Lead",
                "body": "Their officers have no supervisor on record, so no Lead is coaching this work.",
                "action": "See the unassigned work",
                "url": roster["unassigned_url"],
            }
        )
    if summary["awaiting_verification"]:
        count = summary["awaiting_verification"]
        cards.append(
            {
                "tone": "warning",
                "title": f"{count} completed activit{'ies' if count != 1 else 'y'} awaiting verification",
                "body": "Delivered work earns no credit until Impact Assessment verifies it.",
                "action": "Open Team Oversight",
                "url": f"/team-planning-oversight/?fy={fy}",
            }
        )
    execution = summary["execution_progress"]
    if execution is not None and execution < EXECUTION_WARNING_PCT:
        cards.append(
            {
                "tone": "warning",
                "title": f"Regional delivery at {execution}% of due work",
                "body": (
                    f"{summary['completed']} of {summary['due_count']} activities "
                    "due so far are complete."
                ),
                "action": "Open Team Oversight",
                "url": f"/team-planning-oversight/?fy={fy}",
            }
        )
    return cards[:3]


# ── The page ─────────────────────────────────────────────────────────────────
class RegionalLeadDashboardService:
    @staticmethod
    def get_dashboard(user, *, fy: str) -> dict:
        from apps.analytics.ssa_performance_service import regional_ssa_headline

        from apps.cce_leadership.services import report_state, rhythm

        today = date.today()
        reach = _reach(user)
        items = oversight.build_items(user, fy=fy)
        pairs = list(zip(items, _item_countries(items)))
        summary = oversight.summarize(items)
        follow_ups = _follow_ups(user, fy=fy)
        engagement_rhythm = rhythm(user, today=today)
        report = report_state(user, today=today)
        roster = _lead_roster(
            pairs,
            countries=reach["countries"],
            fy=fy,
            follow_ups_by_lead=follow_ups["by_lead"],
            last_coaching=engagement_rhythm["last_coaching"],
        )
        ssa = regional_ssa_headline(user, fy=fy)
        return {
            "fy": fy,
            "reach": reach,
            "summary": summary,
            "attention": _attention(
                summary=summary,
                roster=roster,
                follow_ups=follow_ups,
                fy=fy,
                rhythm=engagement_rhythm,
                report=report,
            ),
            "roster": roster,
            "rhythm": engagement_rhythm,
            "report": report,
            "ssa_needs": _ssa_needs(reach, fy),
            "training_quality": _training_quality(user, reach, fy),
            "networks": _networks(reach, today=today),
            "delivery_mix": _delivery_mix(items),
            "countries": _countries(
                pairs,
                countries=reach["countries"],
                ssa_by_country=ssa["by_country"],
            ),
            "ssa": ssa,
            "priorities": _regional_priorities(fy),
            "follow_ups": follow_ups,
        }
