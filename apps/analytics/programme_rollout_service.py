"""Programme Rollout — how the programme is reaching a Programme Lead's schools
(owner, 2026-09-13).

The Programme Lead's role description asks them to "coordinate the rollout of
training programs, school self-assessments (SSA), and spiritual
transformation interventions". Before this page the facts were spread over the
PL dashboard, PL analytics, Team Oversight, SSA Performance, Coverage and
Training Feedback, each with its own idea of the team and of "trained". This
service answers the three rollout questions for one team, in one place:

* Trainings — what is planned and delivered, by intervention, by course and by
  officer; the schools, teachers and leaders reached; staff against partner
  delivery; what is due in the next 30 days; and what the Regional Lead's
  observations say about the courses and the partners delivering them.
* School self-assessments — which portfolio schools have a confirmed SSA this
  year, which were collected and wait on Impact Assessment, which are
  scheduled or handed to a partner, and which nobody has planned; per officer
  and per cluster, beside the cluster × intervention heatmap.
* Spiritual transformation — Christlike Behaviour and Exposure to the Word of
  God against the previous cycle, the schools weakest in either and whether a
  response is planned, the Christian Transformation, CC-SEL and camp
  programmes delivered by officers and partners, and the Regional Lead's
  Biblical-integration ratings.

Scope. The team is ``apps.hr.team_roster.team_members`` — the one definition
every Programme Lead surface reads — plus the lead's own portfolio. Admin
reads the page for one Programme Lead at a time, as that lead sees it: the
page is a team's, and an administrator is asked about one team, never about
the deployment at once. Every other role is refused here as well as at the
route.

Attribution. An activity belongs to the officer responsible for it, partner
work to the officer monitoring it, and anything else at a portfolio school to
the officer the school is assigned to. Both id forms (StaffProfile and User)
are honoured, as everywhere else (apps.core.scoping.owner_ids).

Vocabulary. "Delivered" is COMPLETED_WORK_STATUSES, the platform's one answer
to "is this finished?"; "held, in review" is the stretch between a training
happening and its verification. "Trained" is
``apps.activities.cluster_attendance.trained_school_ids``. "Has an SSA this
FY" is ``schools_with_confirmed_ssa`` below. Regional Lead observations are
the ones shared with the lead (apps.cce_leadership.services), never a draft.
Nothing here writes.

Cost. Each view is a fixed number of grouped queries whatever the size of the
team (apps/analytics/test_programme_rollout.py QueryBudgetTest), and the
payload is cached per viewer, view, year and day like the role dashboards
(apps.core.cache_utils.cached_role_dashboard).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from django.db.models import Q
from django.utils import timezone

from apps.activities.cluster_attendance import (
    CLUSTER_CREDIT_STATUSES,
    CLUSTER_TRAINING_TYPES,
    SCHOOL_TRAINING_TYPES,
    trained_school_ids,
)
from apps.core.activity_types import COMPLETED_WORK_STATUSES, TRAINING_TYPES
from apps.core.enums import ActivityStatus, ActivityType, SsaIntervention
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.metrics import percentage
from apps.core.fy import fy_options, get_fy_date_range, get_operational_fy
from apps.core.interventions import INTERVENTION_LABELS, intervention_abbr

PROGRAM_LEAD = "Program Lead"
ADMIN = "Admin"

PAGE_URL = "/programme-rollout"
VIEWS = ("trainings", "ssa", "spiritual")
DEFAULT_VIEW = "trainings"

#: "Trainings in the next 30 days" (owner's rollout list).
UPCOMING_DAYS = 30
UPCOMING_ROWS = 200
#: "Among the three weakest interventions" — the bulk list-view rule.
WEAKEST_COUNT = 3
#: A drawer lists at most this many schools and says when it stopped.
DRAWER_ROWS = 200

CB = SsaIntervention.CHRISTLIKE_BEHAVIOUR.value
WOG = SsaIntervention.EXPOSURE_TO_WORD_OF_GOD.value
SPIRITUAL_INTERVENTIONS = (CB, WOG)
#: Christlike Behaviour and Exposure to the Word of God lead every
#: intervention list on this page; the other six keep the canonical order.
INTERVENTION_ORDER: tuple[str, ...] = SPIRITUAL_INTERVENTIONS + tuple(
    value for value in SsaIntervention.values if value not in SPIRITUAL_INTERVENTIONS
)

# ── Activity status groups ───────────────────────────────────────────────────
# The four groups below and COMPLETED_WORK_STATUSES partition ActivityStatus
# (asserted in the tests), so every activity is counted in exactly one column.
#: Not yet anybody's plan, or withdrawn from it: never counted as planned.
NOT_PLANNED_STATUSES = (
    ActivityStatus.NOT_PLANNED.value,
    ActivityStatus.AWAITING_OWNER_APPROVAL.value,
    ActivityStatus.CANCELLED.value,
    ActivityStatus.REJECTED.value,
    ActivityStatus.DEFERRED.value,
)
#: Planned and still to happen.
LIVE_STATUSES = (
    ActivityStatus.PLANNED.value,
    ActivityStatus.SCHEDULED.value,
    ActivityStatus.ASSIGNED_TO_PARTNER.value,
    ActivityStatus.PARTNER_SCHEDULED.value,
    ActivityStatus.IN_PROGRESS.value,
    ActivityStatus.RESCHEDULED.value,
)
#: Held, with completion, evidence, the lead's review or verification open.
IN_REVIEW_STATUSES = (
    ActivityStatus.COMPLETION_STARTED.value,
    ActivityStatus.EVIDENCE_UPLOADED.value,
    ActivityStatus.EVIDENCE_ACCEPTED.value,
    ActivityStatus.SALESFORCE_ID_REQUIRED.value,
    ActivityStatus.SUBMITTED_TO_PL.value,
    ActivityStatus.RETURNED_BY_PL.value,
    ActivityStatus.AWAITING_IA_VERIFICATION.value,
    ActivityStatus.RETURNED_BY_IA.value,
    ActivityStatus.RETURNED.value,
)

STATUS_LABELS = dict(ActivityStatus.choices)
TYPE_LABELS = dict(ActivityType.choices)

# ── School self-assessment states ────────────────────────────────────────────
SSA_CONFIRMED = "confirmed"
SSA_AWAITING = "awaiting"
SSA_SCHEDULED = "scheduled"
SSA_NOT_PLANNED = "not_planned"
#: In precedence order: a school takes the first state it qualifies for.
SSA_STATES: tuple[tuple[str, str], ...] = (
    (SSA_CONFIRMED, "Confirmed SSA this FY"),
    (SSA_AWAITING, "Collected, awaiting IA verification"),
    (SSA_SCHEDULED, "Collection scheduled or with a partner"),
    (SSA_NOT_PLANNED, "No SSA collection planned"),
)
SSA_STATE_LABELS = dict(SSA_STATES)
SSA_STATE_TONES = {
    SSA_CONFIRMED: "success",
    SSA_AWAITING: "info",
    SSA_SCHEDULED: "warning",
    SSA_NOT_PLANNED: "danger",
}
#: Uploaded but not confirmed: Impact Assessment still has to verify it.
SSA_AWAITING_RECORD_STATUSES = ("pending", "flagged")

# ── Spiritual transformation programmes ──────────────────────────────────────
# Named by the catalogue's own fields, so a course added to the Christian
# Transformation category, or a new camp, joins the table without a code
# change (apps/activity_catalogue/seed_data.py).
CHRISTIAN_TRANSFORMATION = "Christian Transformation"
CC_SEL_CODE = "CC_SEL"
CAMP_CATALOGUE_TYPE = "youth_camp"
FAMILY_CT = "christian_transformation"
FAMILY_CC_SEL = "cc_sel"
FAMILY_CAMP = "camp"
SPIRITUAL_FAMILIES: tuple[tuple[str, str], ...] = (
    (FAMILY_CT, "Christian Transformation"),
    (FAMILY_CC_SEL, "CC-SEL"),
    (FAMILY_CAMP, "Camps"),
)

#: Regional Lead recommendations that ask for something to change.
CHANGE_RECOMMENDATIONS = ("strengthen", "replace")

# ── School lists a table cell opens ──────────────────────────────────────────
LIST_KINDS: dict[str, str] = {
    f"ssa_{SSA_CONFIRMED}": SSA_STATE_LABELS[SSA_CONFIRMED],
    f"ssa_{SSA_AWAITING}": SSA_STATE_LABELS[SSA_AWAITING],
    f"ssa_{SSA_SCHEDULED}": SSA_STATE_LABELS[SSA_SCHEDULED],
    f"ssa_{SSA_NOT_PLANNED}": SSA_STATE_LABELS[SSA_NOT_PLANNED],
    "not_trained": "Not yet trained this FY",
}
NO_CLUSTER = "none"


def _values(types) -> list[str]:
    return [getattr(t, "value", t) for t in types]


def _mean(values) -> float | None:
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 1) if values else None


def _day(value) -> str:
    return f"{value:%-d %b %Y}" if value else ""


# ── Scope ────────────────────────────────────────────────────────────────────
@dataclass
class Member:
    """One row owner: an officer on the team, or the lead's own portfolio."""

    staff_id: str
    user_id: str
    name: str
    is_lead: bool = False
    school_ids: set = field(default_factory=set)

    @property
    def ids(self) -> set[str]:
        return {value for value in (self.staff_id, self.user_id) if value}


@dataclass
class RolloutScope:
    lead_staff_id: str | None
    lead_user_id: str | None
    lead_name: str
    #: True when an administrator reads a lead's team.
    support_view: bool
    officers: list[Member]
    lead: Member | None
    #: School id → {"name", "district", "cluster_id"} for the whole portfolio.
    schools: dict
    cluster_names: dict
    #: Admin's choice of Programme Lead: (staff profile id, name).
    leads: list = field(default_factory=list)
    owner_by_id: dict = field(default_factory=dict, init=False)
    owners_by_school: dict = field(default_factory=dict, init=False)

    def __post_init__(self):
        for member in self.everyone:
            for identity in member.ids:
                self.owner_by_id.setdefault(identity, member.staff_id)
            for school_id in member.school_ids:
                self.owners_by_school.setdefault(school_id, []).append(member.staff_id)

    @property
    def everyone(self) -> list[Member]:
        return [*self.officers, *([self.lead] if self.lead else [])]

    @property
    def school_ids(self) -> set[str]:
        return set(self.schools)

    @property
    def staff_ids(self) -> list[str]:
        return [member.staff_id for member in self.everyone if member.staff_id]

    @property
    def cluster_ids(self) -> set[str]:
        return {s["cluster_id"] for s in self.schools.values() if s["cluster_id"]}

    def member(self, staff_id: str) -> Member | None:
        return next((m for m in self.everyone if m.staff_id == staff_id), None)

    def rows(self, attributed=()) -> list[Member]:
        """The officers, then the lead's own portfolio when it holds schools
        or any of the work being counted."""
        rows = list(self.officers)
        if self.lead and (self.lead.school_ids or self.lead.staff_id in attributed):
            rows.append(self.lead)
        return rows

    def attribute(self, responsible, monitor, school_id) -> str | None:
        for identity in (responsible, monitor):
            owner = self.owner_by_id.get(identity) if identity else None
            if owner:
                return owner
        owners = self.owners_by_school.get(school_id or "")
        return owners[0] if owners else None

    def school_ref(self):
        """The portfolio as a subquery, so `school_id__in` never ships the
        materialised id list (apps.analytics.pl_analytics_service PLScope)."""
        from apps.accounts.models import StaffSchoolAssignment
        from apps.schools.models import School

        return School.objects.filter(
            id__in=StaffSchoolAssignment.objects.filter(
                staff_id__in=self.staff_ids
            ).values("school_id")
        ).values("id")

    def activity_filter(self) -> Q:
        """The team's activities: owned or monitored by anyone on it, or held
        at a portfolio school."""
        ids = sorted(self.owner_by_id)
        condition = Q(responsible_staff_id__in=ids) | Q(monitored_by_staff_id__in=ids)
        if self.schools:
            condition |= Q(school_id__in=self.school_ref())
        return condition


def _admin_lead(lead: str | None):
    from apps.accounts.models import StaffProfile, StaffSupervisorAssignment

    profiles = list(
        StaffProfile.objects.filter(
            user__roles__contains=[PROGRAM_LEAD],
            user__is_active=True,
            user__deleted_at__isnull=True,
        )
        .select_related("user")
        .order_by("user__name", "id")
    )
    options = [(p.id, p.user.name or p.user.email) for p in profiles]
    chosen = next((p for p in profiles if p.id == lead), None)
    if chosen is None and profiles:
        # An administrator lands on a lead who has a team, not on an empty page.
        supervising = set(
            StaffSupervisorAssignment.objects.filter(
                supervisor_id__in=[p.id for p in profiles]
            ).values_list("supervisor_id", flat=True)
        )
        chosen = next((p for p in profiles if p.id in supervising), profiles[0])
    if chosen is None:
        return None, options
    user = chosen.user
    user._staff_profile_id_cache = chosen.id
    return user, options


def resolve_rollout_scope(principal, *, lead: str | None = None) -> RolloutScope:
    """The team whose rollout the page shows.

    A Programme Lead always reads their own team; a `lead` they pass is
    ignored. Admin reads the chosen lead's team (or the first lead with one).
    """
    from apps.accounts.models import StaffSchoolAssignment
    from apps.clusters.models import Cluster
    from apps.hr.team_roster import team_members
    from apps.schools.models import School

    role = getattr(principal, "active_role", "") or ""
    options: list = []
    if role == PROGRAM_LEAD:
        lead_user = principal
    elif role == ADMIN:
        lead_user, options = _admin_lead(lead)
    else:
        raise Forbidden(
            "Programme Rollout shows a Programme Lead's team; your role reads "
            "delivery from its own pages."
        )
    if lead_user is None:
        return RolloutScope(
            lead_staff_id=None,
            lead_user_id=None,
            lead_name="",
            support_view=role == ADMIN,
            officers=[],
            lead=None,
            schools={},
            cluster_names={},
            leads=options,
        )

    lead_staff_id = lead_user.staff_profile_id
    officers = [
        Member(
            staff_id=profile.id,
            user_id=profile.user_id,
            name=profile.user.name or profile.user.email,
        )
        for profile in team_members(lead_user)
    ]
    own = Member(
        staff_id=lead_staff_id or "",
        user_id=lead_user.id,
        name=lead_user.name or lead_user.email,
        is_lead=True,
    )
    by_staff = {m.staff_id: m for m in [*officers, own] if m.staff_id}
    assignments = list(
        StaffSchoolAssignment.objects.filter(staff_id__in=list(by_staff)).values_list(
            "staff_id", "school_id"
        )
    )
    schools = {
        school_id: {"name": name, "district": district or "", "cluster_id": cluster_id}
        for school_id, name, district, cluster_id in School.objects.filter(
            id__in={school_id for _staff, school_id in assignments}
        ).values_list("id", "name", "district__name", "cluster_id")
    }
    for staff_id, school_id in assignments:
        if school_id in schools:
            by_staff[staff_id].school_ids.add(school_id)
    cluster_ids = {s["cluster_id"] for s in schools.values() if s["cluster_id"]}
    cluster_names = (
        dict(Cluster.objects.filter(id__in=cluster_ids).values_list("id", "name"))
        if cluster_ids
        else {}
    )
    return RolloutScope(
        lead_staff_id=lead_staff_id,
        lead_user_id=lead_user.id,
        lead_name=own.name,
        support_view=role == ADMIN,
        officers=officers,
        lead=own if own.staff_id else None,
        schools=schools,
        cluster_names=cluster_names,
        leads=options,
    )


def _member_links(member: Member, fy: str) -> dict:
    owner = "mine" if member.is_lead else member.staff_id
    return {
        "oversight_url": f"/team-planning-oversight/?owner={owner}&fy={fy}",
        "profile_url": ""
        if member.is_lead
        else f"/staff/{member.user_id}?from={PAGE_URL}",
    }


def _member_name(member: Member, scope: RolloutScope) -> str:
    if not member.is_lead:
        return member.name
    return (
        f"{member.name} (own portfolio)" if scope.support_view else "Your own portfolio"
    )


def _people_names(scope: RolloutScope, identities) -> dict[str, str]:
    """Names for people outside the team a row still has to name."""
    from apps.accounts.models import StaffProfile

    unknown = {i for i in identities if i and i not in scope.owner_by_id}
    if not unknown:
        return {}
    names: dict[str, str] = {}
    for staff_id, user_id, name in StaffProfile.all_objects.filter(
        Q(id__in=unknown) | Q(user_id__in=unknown)
    ).values_list("id", "user_id", "user__name"):
        names[staff_id] = name or ""
        names[user_id] = name or ""
    return names


def _partner_names(partner_ids) -> dict[str, str]:
    from apps.partners.models import Partner

    ids = {p for p in partner_ids if p}
    if not ids:
        return {}
    return dict(Partner.all_objects.filter(id__in=ids).values_list("id", "name"))


# ── Trainings ────────────────────────────────────────────────────────────────
TRAINING_FIELDS = (
    "id",
    "activity_type",
    "status",
    "planned_date",
    "focus_intervention",
    "delivery_type",
    "assigned_partner_id",
    "responsible_staff_id",
    "monitored_by_staff_id",
    "school_id",
    "cluster_id",
    "teachers_attended",
    "leaders_attended",
    "attended_school_ids",
    "catalogue_item_id",
    "catalogue_item__is_training_course",
    "training_course_id",
    "activity_name_snapshot",
    "school__name",
    "cluster__name",
)


def _course_id(row: dict) -> str | None:
    """The governed course a training taught: the in-school course when one
    was chosen, else the catalogue item when that item is itself a course."""
    if row.get("training_course_id"):
        return row["training_course_id"]
    if row.get("catalogue_item__is_training_course"):
        return row.get("catalogue_item_id")
    return None


def _reach(rows) -> dict[str, set[str]]:
    """Schools each delivered training reached, by the rules
    trained_school_ids applies: a school-level training reaches its school;
    a cluster training reaches the schools whose attendance was confirmed,
    once verified, plus the legacy attendance array."""
    from apps.activities.models import ClusterActivityAttendance

    school_types = set(_values(SCHOOL_TRAINING_TYPES))
    cluster_types = set(_values(CLUSTER_TRAINING_TYPES))
    reach: dict[str, set[str]] = defaultdict(set)
    cluster_sessions = []
    for row in rows:
        if row["activity_type"] in school_types:
            if row["status"] in COMPLETED_WORK_STATUSES and row["school_id"]:
                reach[row["id"]].add(row["school_id"])
        elif (
            row["activity_type"] in cluster_types
            and row["status"] in CLUSTER_CREDIT_STATUSES
        ):
            cluster_sessions.append(row["id"])
            reach[row["id"]].update(row.get("attended_school_ids") or [])
    if cluster_sessions:
        for activity_id, school_id in ClusterActivityAttendance.objects.filter(
            activity_id__in=cluster_sessions, attended=True
        ).values_list("activity_id", "school_id"):
            reach[activity_id].add(school_id)
    return reach


def _fold(rows, reach) -> dict:
    """The rollout figures of a group of trainings."""
    delivered = [r for r in rows if r["status"] in COMPLETED_WORK_STATUSES]
    reached: set[str] = set()
    for row in delivered:
        reached |= reach.get(row["id"], set())
    planned = len(rows)
    return {
        "planned": planned,
        "delivered": len(delivered),
        "in_review": sum(1 for r in rows if r["status"] in IN_REVIEW_STATUSES),
        "to_deliver": sum(1 for r in rows if r["status"] in LIVE_STATUSES),
        "delivered_share": percentage(len(delivered), planned),
        "schools_reached": len(reached),
        "teachers": sum(r["teachers_attended"] or 0 for r in delivered),
        "leaders": sum(r["leaders_attended"] or 0 for r in delivered),
        "by_staff": sum(1 for r in delivered if r["delivery_type"] != "partner"),
        "by_partner": sum(1 for r in delivered if r["delivery_type"] == "partner"),
    }


def _training_rows(scope: RolloutScope, fy: str) -> list[dict]:
    from apps.activities.models import Activity

    if not scope.owner_by_id:
        return []
    return list(
        Activity.objects.filter(
            scope.activity_filter(),
            fy=fy,
            deleted_at__isnull=True,
            activity_type__in=_values(TRAINING_TYPES),
        )
        .exclude(status__in=NOT_PLANNED_STATUSES)
        .order_by("planned_date", "id")
        .values(*TRAINING_FIELDS)
    )


def _courses(referenced) -> dict[str, dict]:
    """Every active governed training course, and any other catalogue item a
    counted activity names, with its primary SSA intervention."""
    from apps.activity_catalogue.models import (
        ActivityCatalogueItem,
        ActivityInterventionMapping,
    )

    items = {
        row["id"]: row
        for row in ActivityCatalogueItem.objects.filter(
            Q(is_training_course=True, status="active")
            | Q(id__in={i for i in referenced if i})
        ).values(
            "id",
            "display_name",
            "training_category",
            "stable_code",
            "activity_type",
            "is_training_course",
        )
    }
    interventions: dict[str, str] = {}
    for item_id, intervention in (
        ActivityInterventionMapping.objects.filter(
            catalogue_item_id__in=list(items),
            active=True,
            intervention__isnull=False,
        )
        .order_by("-is_primary", "priority", "id")
        .values_list("catalogue_item_id", "intervention")
    ):
        interventions.setdefault(item_id, intervention)
    for item_id, item in items.items():
        item["intervention"] = interventions.get(item_id) or ""
    return items


def _training_name(row: dict, courses: dict, prefix: str = "") -> str:
    course = courses.get(_course_id(row) or "")
    if course:
        return course["display_name"]
    return (
        row.get(f"{prefix}activity_name_snapshot")
        or TYPE_LABELS.get(row.get(f"{prefix}activity_type") or "", "")
        or "Training"
    )


def _observation_queryset(principal, scope: RolloutScope, fy: str):
    """Training observations the Regional Lead shared with this lead.

    The lead's own reach is the Training Feedback register's
    (feedback_visible_to); Admin's support view reads exactly what that lead
    reads. Unshared drafts stay with the Regional Lead."""
    from apps.cce_leadership.models import EngagementKind, RegionalEngagement
    from apps.cce_leadership.services import feedback_visible_to

    if not scope.lead_staff_id:
        return RegionalEngagement.objects.none()
    if scope.support_view:
        observations = RegionalEngagement.objects.filter(
            kind=EngagementKind.TRAINING_OBSERVATION,
            feedback_shared_at__isnull=False,
            program_lead_ids__contains=[scope.lead_staff_id],
        )
    else:
        observations = feedback_visible_to(principal)
    return observations.filter(fy=fy)


OBSERVATION_FIELDS = (
    "id",
    "held_on",
    "subject",
    "recommendation",
    "acknowledged_at",
    "lead_response",
    "rating_biblical_integration",
    "rating_need_alignment",
    "rating_facilitation",
    "rating_participation",
    "rating_application",
    "activity_id",
    "activity__activity_type",
    "activity__activity_name_snapshot",
    "activity__planned_date",
    "activity__delivery_type",
    "activity__assigned_partner_id",
    "activity__responsible_staff_id",
    "activity__monitored_by_staff_id",
    "activity__school_id",
    "activity__school__name",
    "activity__cluster__name",
    "activity__training_course_id",
    "activity__catalogue_item_id",
    "activity__catalogue_item__is_training_course",
)


def _observation_rows(principal, scope: RolloutScope, fy: str) -> list[dict]:
    from apps.cce_leadership.models import OBSERVATION_CRITERIA

    rows = list(
        _observation_queryset(principal, scope, fy)
        .order_by("-held_on", "-created_at")
        .values(*OBSERVATION_FIELDS)
    )
    for row in rows:
        row["average"] = _mean(
            [row[name] for name, _label, _hint in OBSERVATION_CRITERIA]
        )
        row["course_id"] = _course_id(
            {
                "training_course_id": row["activity__training_course_id"],
                "catalogue_item_id": row["activity__catalogue_item_id"],
                "catalogue_item__is_training_course": row[
                    "activity__catalogue_item__is_training_course"
                ],
            }
        )
        row["partner_id"] = (
            row["activity__assigned_partner_id"]
            if row["activity__delivery_type"] == "partner"
            else None
        )
        row["owner"] = scope.attribute(
            row["activity__responsible_staff_id"],
            row["activity__monitored_by_staff_id"],
            row["activity__school_id"],
        )
        row["is_open"] = (
            row["recommendation"] in CHANGE_RECOMMENDATIONS
            and row["acknowledged_at"] is None
        )
    return rows


def _observation_fold(rows) -> dict:
    return {
        "observed": len(rows),
        "rating": _mean([r["average"] for r in rows]),
        "biblical": _mean([r["rating_biblical_integration"] for r in rows]),
        "open_recommendations": sum(1 for r in rows if r["is_open"]),
    }


def _partner_follow_ups(scope: RolloutScope, observation_ids) -> dict:
    """The lead's own partner engagements that answered an observation."""
    from apps.partners.models import PartnerEngagement

    if not observation_ids or not scope.lead_user_id:
        return {}
    latest: dict = {}
    for source_id, held_on in PartnerEngagement.objects.filter(
        author_id=scope.lead_user_id, source_engagement_id__in=list(observation_ids)
    ).values_list("source_engagement_id", "held_on"):
        if source_id not in latest or held_on > latest[source_id]:
            latest[source_id] = held_on
    return latest


def _upcoming(scope: RolloutScope, today: date) -> list[dict]:
    from apps.activities.models import Activity

    if not scope.owner_by_id:
        return []
    return list(
        Activity.objects.filter(
            scope.activity_filter(),
            deleted_at__isnull=True,
            activity_type__in=_values(TRAINING_TYPES),
            status__in=LIVE_STATUSES,
            planned_date__gte=today,
            planned_date__lte=today + timedelta(days=UPCOMING_DAYS),
        )
        .order_by("planned_date", "id")
        .values(*TRAINING_FIELDS)[:UPCOMING_ROWS]
    )


def trainings_rollout(principal, scope: RolloutScope, fy: str, today: date) -> dict:
    rows = _training_rows(scope, fy)
    upcoming_rows = _upcoming(scope, today)
    observations = _observation_rows(principal, scope, fy)
    reach = _reach(rows)
    courses = _courses(
        {_course_id(r) for r in rows}
        | {_course_id(r) for r in upcoming_rows}
        | {r["course_id"] for r in observations}
    )
    partner_names = _partner_names(
        {r["assigned_partner_id"] for r in rows + upcoming_rows}
        | {r["partner_id"] for r in observations}
    )
    people = _people_names(
        scope,
        {r["responsible_staff_id"] for r in upcoming_rows}
        | {r["activity__responsible_staff_id"] for r in observations},
    )

    def delivered_by(owner, partner_id, delivery_type, responsible) -> str:
        if delivery_type == "partner":
            return partner_names.get(partner_id or "", "Training partner")
        member = scope.member(owner or "")
        if member and member.ids & {responsible}:
            return _member_name(member, scope)
        return people.get(responsible or "") or (
            _member_name(member, scope) if member else "Edify staff"
        )

    # By intervention: all eight, Christlike Behaviour and the Word of God first.
    by_focus: dict[str, list] = defaultdict(list)
    for row in rows:
        by_focus[row["focus_intervention"] or ""].append(row)
    interventions = [
        {
            "code": code,
            "abbr": intervention_abbr(code),
            "name": INTERVENTION_LABELS.get(code, code),
            **_fold(by_focus.get(code, []), reach),
        }
        for code in INTERVENTION_ORDER
    ]
    if by_focus.get(""):
        interventions.append(
            {
                "code": "",
                "abbr": "—",
                "name": "No intervention named",
                **_fold(by_focus[""], reach),
            }
        )

    # By course, with what the Regional Lead observed of each.
    by_course: dict[str, list] = defaultdict(list)
    for row in rows:
        by_course[_course_id(row) or ""].append(row)
    observed_by_course: dict[str, list] = defaultdict(list)
    for observation in observations:
        observed_by_course[observation["course_id"] or ""].append(observation)
    course_rows = []
    for course_id, course in courses.items():
        if not course["is_training_course"] and not by_course.get(course_id):
            continue
        course_rows.append(
            {
                "id": course_id,
                "name": course["display_name"],
                "category": course["training_category"] or "Other",
                "abbr": intervention_abbr(course["intervention"])
                if course["intervention"]
                else "—",
                "intervention_name": INTERVENTION_LABELS.get(
                    course["intervention"], "No SSA intervention"
                ),
                **_fold(by_course.get(course_id, []), reach),
                **_observation_fold(observed_by_course.get(course_id, [])),
            }
        )
    course_rows.sort(key=lambda r: (-r["planned"], -r["delivered"], r["name"]))
    if by_course.get(""):
        course_rows.append(
            {
                "id": "",
                "name": "Training with no course named",
                "category": "—",
                "abbr": "—",
                "intervention_name": "",
                **_fold(by_course[""], reach),
                **_observation_fold(observed_by_course.get("", [])),
            }
        )

    # By officer, against their own portfolio.
    by_owner: dict[str, list] = defaultdict(list)
    for row in rows:
        owner = scope.attribute(
            row["responsible_staff_id"], row["monitored_by_staff_id"], row["school_id"]
        )
        if owner:
            by_owner[owner].append(row)
    trained = (
        trained_school_ids(scope.school_ref(), fy=fy) & scope.school_ids
        if scope.schools
        else set()
    )
    officer_rows = []
    for member in scope.rows(attributed=set(by_owner)):
        member_rows = by_owner.get(member.staff_id, [])
        trained_here = trained & member.school_ids
        next_dates = [
            r["planned_date"]
            for r in member_rows
            if r["status"] in LIVE_STATUSES
            and r["planned_date"]
            and r["planned_date"] >= today
        ]
        officer_rows.append(
            {
                "staff_id": member.staff_id,
                "name": _member_name(member, scope),
                "is_lead": member.is_lead,
                "portfolio": len(member.school_ids),
                "schools_trained": len(trained_here),
                "schools_untrained": len(member.school_ids) - len(trained_here),
                "trained_share": percentage(len(trained_here), len(member.school_ids)),
                "next_training": min(next_dates) if next_dates else None,
                **_fold(member_rows, reach),
                **_member_links(member, fy),
            }
        )

    upcoming = []
    for row in upcoming_rows:
        owner = scope.attribute(
            row["responsible_staff_id"], row["monitored_by_staff_id"], row["school_id"]
        )
        upcoming.append(
            {
                "id": row["id"],
                "date": row["planned_date"],
                "training": _training_name(row, courses),
                "place": row["school__name"]
                or row["cluster__name"]
                or "No school or cluster",
                "delivered_by": delivered_by(
                    owner,
                    row["assigned_partner_id"],
                    row["delivery_type"],
                    row["responsible_staff_id"],
                ),
                "delivery": "Partner" if row["delivery_type"] == "partner" else "Staff",
                "abbr": intervention_abbr(row["focus_intervention"])
                if row["focus_intervention"]
                else "—",
                "status_label": STATUS_LABELS.get(row["status"], row["status"]),
                "url": f"/activities/{row['id']}",
            }
        )

    # Regional Lead observations, by who delivered.
    by_deliverer: dict[str, list] = defaultdict(list)
    for observation in observations:
        by_deliverer[observation["partner_id"] or ""].append(observation)
    deliverer_rows = [
        {
            "name": partner_names.get(partner_id, "Training partner"),
            "kind": "Training partner",
            **_observation_fold(group),
        }
        for partner_id, group in by_deliverer.items()
        if partner_id
    ]
    deliverer_rows.sort(key=lambda r: (-r["open_recommendations"], r["name"]))
    if by_deliverer.get(""):
        deliverer_rows.insert(
            0,
            {
                "name": "Your officers" if not scope.support_view else "The officers",
                "kind": "Edify staff",
                **_observation_fold(by_deliverer[""]),
            },
        )

    follow_ups = _partner_follow_ups(
        scope, [o["id"] for o in observations if o["recommendation"]]
    )
    recommendation_labels = _recommendation_labels()
    recommendations = []
    for observation in observations:
        if observation["recommendation"] not in CHANGE_RECOMMENDATIONS:
            continue
        followed = follow_ups.get(observation["id"])
        recommendations.append(
            {
                "id": observation["id"],
                "training": _observation_training(observation, courses),
                "delivered_by": delivered_by(
                    observation["owner"],
                    observation["partner_id"],
                    observation["activity__delivery_type"],
                    observation["activity__responsible_staff_id"],
                ),
                "held_on": observation["held_on"],
                "recommendation": recommendation_labels.get(
                    observation["recommendation"], observation["recommendation"]
                ),
                "rating": observation["average"],
                "state": _feedback_state(observation, scope),
                "state_tone": "warning" if observation["is_open"] else "success",
                "is_open": observation["is_open"],
                "follow_up": f"Partner engagement {_day(followed)}" if followed else "",
            }
        )
    recommendations.sort(key=lambda r: (not r["is_open"], r["held_on"]))

    summary = _fold(rows, reach)
    return {
        "summary": {
            **summary,
            "portfolio": len(scope.schools),
            "schools_trained": len(trained),
            "upcoming": len(upcoming_rows),
            **_observation_fold(observations),
        },
        "interventions": interventions,
        "courses": course_rows,
        "officers": officer_rows,
        "upcoming": upcoming,
        "upcoming_days": UPCOMING_DAYS,
        "observations_by_deliverer": deliverer_rows,
        "recommendations": recommendations,
    }


def _recommendation_labels() -> dict[str, str]:
    from apps.cce_leadership.models import ObservationRecommendation

    return dict(ObservationRecommendation.choices)


def _observation_training(observation: dict, courses: dict) -> str:
    if not observation["activity_id"]:
        return observation["subject"]
    name = _training_name(
        {
            "training_course_id": observation["activity__training_course_id"],
            "catalogue_item_id": observation["activity__catalogue_item_id"],
            "catalogue_item__is_training_course": observation[
                "activity__catalogue_item__is_training_course"
            ],
            "activity_name_snapshot": observation["activity__activity_name_snapshot"],
            "activity_type": observation["activity__activity_type"],
        },
        courses,
    )
    place = (
        observation["activity__school__name"]
        or observation["activity__cluster__name"]
        or ""
    )
    return " · ".join(part for part in (name, place) if part)


def _feedback_state(observation: dict, scope: RolloutScope) -> str:
    if observation["acknowledged_at"]:
        return "Answered"
    return (
        "Awaiting the Programme Lead" if scope.support_view else "Awaiting your answer"
    )


# ── School self-assessments ──────────────────────────────────────────────────
def ssa_records_this_fy(school_ids, fy: str):
    """SSA records of `school_ids` for the financial year: the record's own
    `fy`, never a soft-deleted row."""
    from apps.ssa.models import SsaRecord

    return SsaRecord.objects.filter(
        school_id__in=school_ids, fy=fy, deleted_at__isnull=True
    )


def schools_with_confirmed_ssa(school_ids, fy: str) -> set[str]:
    """THE answer to "has this school an SSA this FY?" on Programme Rollout:
    a confirmed record for the year. Unverified uploads do not count
    (apps.ssa.services.latest_applicable_record)."""
    return set(
        ssa_records_this_fy(school_ids, fy)
        .filter(verification_status=SSA_CONFIRMED)
        .order_by()
        .values_list("school_id", flat=True)
        .distinct()
    )


def _ssa_collection_types() -> tuple[str, ...]:
    from apps.analytics.pl_analytics_service import SSA_COLLECTION_TYPES

    return tuple(SSA_COLLECTION_TYPES)


def ssa_states(scope: RolloutScope, fy: str) -> dict[str, dict]:
    """Each portfolio school's SSA state for the year, with the fact behind it.

    A school takes the first state it qualifies for: a confirmed record; a
    record Impact Assessment has not confirmed, or a collection already held;
    a collection planned or scheduled, or an unscheduled partner hand-over;
    otherwise nothing is planned. Cluster collections count for the schools
    invited or recorded at them, or every portfolio school in the cluster when
    none is recorded."""
    from apps.activities.models import Activity, ClusterActivityAttendance
    from apps.partners.models import PartnerAssignment

    portfolio = scope.school_ids
    if not portfolio:
        return {}
    facts: dict[str, dict[str, list]] = {sid: defaultdict(list) for sid in portfolio}

    # One read of the year's records, judged by the same rule as
    # schools_with_confirmed_ssa: the record's fy, not deleted, confirmed.
    confirmed: dict[str, object] = {}
    for school_id, status, taken_on in (
        ssa_records_this_fy(scope.school_ref(), fy)
        .order_by("school_id", "-date_of_ssa")
        .values_list("school_id", "verification_status", "date_of_ssa")
    ):
        if school_id not in facts:
            continue
        if status == SSA_CONFIRMED:
            confirmed.setdefault(school_id, taken_on)
        elif status in SSA_AWAITING_RECORD_STATUSES:
            facts[school_id][SSA_AWAITING].append(
                f"Uploaded {_day(taken_on)}, not yet verified"
            )

    collection_types = _ssa_collection_types()
    clusters = scope.cluster_ids
    collections = list(
        Activity.objects.filter(
            scope.activity_filter()
            | Q(school__isnull=True, cluster_id__in=sorted(clusters)),
            fy=fy,
            deleted_at__isnull=True,
            activity_type__in=collection_types,
        )
        .exclude(status__in=NOT_PLANNED_STATUSES)
        .order_by("planned_date", "id")
        .values(
            "id",
            "school_id",
            "cluster_id",
            "status",
            "planned_date",
            "delivery_type",
            "assigned_partner_id",
            "attended_school_ids",
        )
    )
    cluster_sessions = [c["id"] for c in collections if not c["school_id"]]
    invited: dict[str, set[str]] = defaultdict(set)
    if cluster_sessions:
        for activity_id, school_id in ClusterActivityAttendance.objects.filter(
            activity_id__in=cluster_sessions
        ).values_list("activity_id", "school_id"):
            invited[activity_id].add(school_id)
    members_of_cluster: dict[str, set[str]] = defaultdict(set)
    for school_id, school in scope.schools.items():
        if school["cluster_id"]:
            members_of_cluster[school["cluster_id"]].add(school_id)

    assignments = list(
        PartnerAssignment.objects.filter(
            Q(school_id__in=scope.school_ref())
            | Q(school__isnull=True, cluster_id__in=sorted(clusters)),
            status__in=PartnerAssignment.UNSCHEDULED_STATUSES,
            created_at__gte=get_fy_date_range(fy)[0],
            created_at__lt=get_fy_date_range(fy)[1],
        )
        .filter(
            Q(expected_activity_type__in=collection_types)
            | Q(catalogue_item__workflow_kind__in=collection_types)
        )
        .values_list("school_id", "cluster_id", "partner_id")
    )
    partner_names = _partner_names(
        {c["assigned_partner_id"] for c in collections} | {a[2] for a in assignments}
    )

    for collection in collections:
        if collection["school_id"]:
            schools = {collection["school_id"]}
        else:
            schools = invited.get(collection["id"], set()) | set(
                collection["attended_school_ids"] or []
            )
            schools = schools or members_of_cluster.get(collection["cluster_id"], set())
        status = collection["status"]
        when = _day(collection["planned_date"])
        by_partner = (
            partner_names.get(collection["assigned_partner_id"] or "", "a partner")
            if collection["delivery_type"] == "partner"
            else ""
        )
        for school_id in schools & portfolio:
            if status in LIVE_STATUSES:
                facts[school_id][SSA_SCHEDULED].append(
                    f"Collection {STATUS_LABELS.get(status, status).lower()}"
                    + (f" {when}" if when else "")
                    + (f" with {by_partner}" if by_partner else "")
                )
            else:
                facts[school_id][SSA_AWAITING].append(
                    f"Collection held{f' {when}' if when else ''}, "
                    f"{STATUS_LABELS.get(status, status).lower()}"
                )
    for school_id, cluster_id, partner_id in assignments:
        schools = (
            {school_id} if school_id else members_of_cluster.get(cluster_id, set())
        )
        for sid in schools & portfolio:
            facts[sid][SSA_SCHEDULED].append(
                f"Handed to {partner_names.get(partner_id, 'a partner')}, not yet scheduled"
            )

    states = {}
    for school_id in portfolio:
        if school_id in confirmed:
            state = SSA_CONFIRMED
            detail = f"Confirmed {_day(confirmed[school_id])}".strip()
        else:
            state = next(
                (key for key in (SSA_AWAITING, SSA_SCHEDULED) if facts[school_id][key]),
                SSA_NOT_PLANNED,
            )
            detail = (
                facts[school_id][state][0]
                if state != SSA_NOT_PLANNED
                else "No SSA collection planned this FY"
            )
        states[school_id] = {"state": state, "detail": detail}
    return states


def _state_counts(school_ids, states) -> dict:
    counts = {key: 0 for key, _label in SSA_STATES}
    for school_id in school_ids:
        entry = states.get(school_id)
        if entry:
            counts[entry["state"]] += 1
    total = len(school_ids)
    return {
        "portfolio": total,
        "confirmed": counts[SSA_CONFIRMED],
        "awaiting": counts[SSA_AWAITING],
        "scheduled": counts[SSA_SCHEDULED],
        "not_planned": counts[SSA_NOT_PLANNED],
        "coverage": percentage(counts[SSA_CONFIRMED], total),
    }


def _analytics_scope(scope: RolloutScope):
    """The portfolio in the shape the PL analytics helpers read, so the
    heatmap and the cycle averages are the dashboard's own calculations."""
    from apps.analytics.pl_analytics_service import PLScope

    school_ids = sorted(scope.school_ids)
    return PLScope(
        user=None,
        pl_staff_id=scope.lead_staff_id,
        cceos=[],
        responsible_ids=set(scope.owner_by_id),
        school_ids=school_ids,
        school_ref=school_ids,
        district_ids=[],
        cluster_ids=sorted(scope.cluster_ids),
        school_filtered=True,
    )


def ssa_rollout(scope: RolloutScope, fy: str) -> dict:
    from apps.analytics.pl_dashboard_service import ProgramLeadDashboardService

    states = ssa_states(scope, fy)
    officers = [
        {
            "staff_id": member.staff_id,
            "name": _member_name(member, scope),
            "is_lead": member.is_lead,
            **_state_counts(member.school_ids, states),
            **_member_links(member, fy),
        }
        for member in scope.rows()
    ]
    by_cluster: dict[str, set[str]] = defaultdict(set)
    for school_id, school in scope.schools.items():
        by_cluster[school["cluster_id"] or NO_CLUSTER].add(school_id)
    cluster_rows = []
    for cluster_id, school_ids in by_cluster.items():
        owners = {
            owner for sid in school_ids for owner in scope.owners_by_school.get(sid, [])
        }
        cluster_rows.append(
            {
                "cluster": cluster_id,
                "name": scope.cluster_names.get(cluster_id, "Cluster")
                if cluster_id != NO_CLUSTER
                else "Not in a cluster",
                "officers": ", ".join(
                    sorted(
                        _member_name(scope.member(owner), scope)
                        for owner in owners
                        if scope.member(owner)
                    )
                ),
                **_state_counts(school_ids, states),
            }
        )
    cluster_rows.sort(
        key=lambda r: (
            r["cluster"] == NO_CLUSTER,
            r["coverage"] if r["coverage"] is not None else 101,
            -r["not_planned"],
            r["name"],
        )
    )
    matrix = (
        ProgramLeadDashboardService.ssa_cluster_matrix(_analytics_scope(scope), fy)
        if scope.schools
        else {"rows": [], "columns": [], "codes": []}
    )
    return {
        "summary": _state_counts(scope.school_ids, states),
        "states": [
            {"key": key, "name": label, "tone": SSA_STATE_TONES[key]}
            for key, label in SSA_STATES
        ],
        "officers": officers,
        "clusters": cluster_rows,
        "matrix": matrix,
        "matrix_headers": [
            {"code": code, "name": name}
            for code, name in zip(matrix.get("codes", []), matrix.get("columns", []))
        ],
    }


# ── Spiritual transformation ─────────────────────────────────────────────────
def _spiritual_programmes() -> dict[str, dict]:
    from apps.activity_catalogue.models import ActivityCatalogueItem

    programmes = {}
    for row in ActivityCatalogueItem.objects.filter(
        Q(training_category=CHRISTIAN_TRANSFORMATION)
        | Q(stable_code=CC_SEL_CODE)
        | Q(activity_type=CAMP_CATALOGUE_TYPE)
    ).values("id", "display_name", "training_category", "stable_code", "activity_type"):
        if row["stable_code"] == CC_SEL_CODE:
            row["family"] = FAMILY_CC_SEL
        elif row["activity_type"] == CAMP_CATALOGUE_TYPE:
            row["family"] = FAMILY_CAMP
        else:
            row["family"] = FAMILY_CT
        programmes[row["id"]] = row
    return programmes


def _programme_id(row: dict, programmes: dict) -> str | None:
    for key in ("training_course_id", "catalogue_item_id"):
        if row.get(key) in programmes:
            return row[key]
    return None


def spiritual_rollout(principal, scope: RolloutScope, fy: str, today: date) -> dict:
    from apps.activities.models import Activity
    from apps.analytics.pl_analytics_service import PLAnalyticsService, ssa_band
    from apps.ssa.models import SsaScore
    from apps.ssa.recommendation_engine import bulk_weakest

    pls = _analytics_scope(scope)
    families = dict(SPIRITUAL_FAMILIES)

    # Team averages against the previous cycle — PL analytics' own figures.
    cycle = (
        PLAnalyticsService.ssa_interventions(pls, fy)
        if scope.schools
        else {"rows": [], "latest_fy": None, "prev_fy": None, "has_data": False}
    )
    team_scores = {
        row["value"]: row
        for row in cycle["rows"]
        if row["value"] in SPIRITUAL_INTERVENTIONS
    }
    latest_fy, prev_fy = cycle["latest_fy"], cycle["prev_fy"]
    scores = [
        {
            "code": code,
            "abbr": intervention_abbr(code),
            "name": INTERVENTION_LABELS[code],
            "score": (team_scores.get(code) or {}).get("score"),
            "delta": (team_scores.get(code) or {}).get("delta"),
            "band": (team_scores.get(code) or {}).get("band") or ssa_band(None)[0],
            "tone": (team_scores.get(code) or {}).get("tone") or "neutral",
        }
        for code in SPIRITUAL_INTERVENTIONS
    ]

    # Per officer, flat over records as the team figure is.
    per_school: dict[tuple, list[float]] = defaultdict(list)
    cycles = [c for c in (latest_fy, prev_fy) if c]
    if cycles:
        for school_id, record_fy, intervention, value in SsaScore.objects.filter(
            ssa_record__school_id__in=pls.school_ids,
            ssa_record__verification_status=SSA_CONFIRMED,
            ssa_record__deleted_at__isnull=True,
            ssa_record__fy__in=cycles,
            intervention__in=SPIRITUAL_INTERVENTIONS,
        ).values_list(
            "ssa_record__school_id", "ssa_record__fy", "intervention", "score"
        ):
            per_school[(school_id, record_fy, intervention)].append(value)

    def officer_score(member, code, cycle_fy):
        values = [
            v
            for sid in member.school_ids
            for v in per_school.get((sid, cycle_fy, code), [])
        ]
        return _mean(values) if cycle_fy else None

    # Schools weakest in Christlike Behaviour or the Word of God.
    weakest = bulk_weakest(sorted(scope.school_ids), n=WEAKEST_COUNT)
    weak = {
        school_id: [w for w in items if w["intervention"] in SPIRITUAL_INTERVENTIONS]
        for school_id, items in weakest.items()
    }
    weak = {school_id: items for school_id, items in weak.items() if items}
    responses: dict[tuple[str, str], list[dict]] = defaultdict(list)
    if weak:
        weak_clusters = sorted(
            {
                scope.schools[sid]["cluster_id"]
                for sid in weak
                if scope.schools[sid]["cluster_id"]
            }
        )
        planned = (
            Activity.objects.filter(fy=fy, deleted_at__isnull=True)
            .exclude(status__in=NOT_PLANNED_STATUSES)
            .filter(
                Q(school_id__in=sorted(weak))
                | Q(school__isnull=True, cluster_id__in=weak_clusters)
            )
            .filter(
                Q(focus_intervention__in=SPIRITUAL_INTERVENTIONS)
                | Q(
                    secondary_focus_interventions__overlap=list(SPIRITUAL_INTERVENTIONS)
                )
            )
            .order_by("planned_date", "id")
            .values(
                "id",
                "school_id",
                "cluster_id",
                "status",
                "planned_date",
                "focus_intervention",
                "secondary_focus_interventions",
                "activity_type",
                "activity_name_snapshot",
                "training_course__display_name",
            )
        )
        members_of_cluster: dict[str, set[str]] = defaultdict(set)
        for sid in weak:
            if scope.schools[sid]["cluster_id"]:
                members_of_cluster[scope.schools[sid]["cluster_id"]].add(sid)
        for activity in planned:
            targets = {
                activity["focus_intervention"],
                *(activity["secondary_focus_interventions"] or []),
            }
            schools = (
                {activity["school_id"]}
                if activity["school_id"]
                else members_of_cluster.get(activity["cluster_id"], set())
            )
            for sid in schools:
                for code in targets & set(SPIRITUAL_INTERVENTIONS):
                    responses[(sid, code)].append(activity)

    own = scope.lead.school_ids if scope.lead and not scope.support_view else set()
    weak_rows = []
    for school_id, items in weak.items():
        school = scope.schools[school_id]
        answered = []
        missing = []
        for item in items:
            found = responses.get((school_id, item["intervention"]))
            abbr = intervention_abbr(item["intervention"])
            if found:
                first = found[0]
                name = (
                    first["training_course__display_name"]
                    or first["activity_name_snapshot"]
                    or TYPE_LABELS.get(first["activity_type"], "Activity")
                )
                when = _day(first["planned_date"])
                answered.append(f"{abbr}: {name}{f' · {when}' if when else ''}")
            else:
                missing.append(item)
        if not missing:
            state, tone = "Planned", "success"
        elif answered:
            state, tone = "Partly planned", "warning"
        else:
            state, tone = "No plan", "danger"
        owners = scope.owners_by_school.get(school_id, [])
        first_missing = missing[0]["intervention"] if missing else ""
        weak_rows.append(
            {
                "school_id": school_id,
                "name": school["name"],
                "district": school["district"],
                "cluster": scope.cluster_names.get(school["cluster_id"] or "", ""),
                "officer": ", ".join(
                    _member_name(scope.member(o), scope)
                    for o in owners
                    if scope.member(o)
                ),
                "weak": [
                    {
                        "abbr": intervention_abbr(w["intervention"]),
                        "name": INTERVENTION_LABELS[w["intervention"]],
                        "score": round(w["score"], 1),
                        "tone": ssa_band(w["score"])[2],
                    }
                    for w in items
                ],
                "lowest": min(w["score"] for w in items),
                "responses": " · ".join(answered) or "Nothing planned this FY",
                "state": state,
                "tone": tone,
                "has_gap": bool(missing),
                "school_url": f"/schools/{school_id}",
                # The lead plans their own portfolio only; a supervised school
                # is the officer's to plan (owner-approved visit rule, SEC-01).
                "plan_url": (
                    f"/planning/schedule-modal?school_id={school_id}"
                    f"&focus_intervention={first_missing}"
                )
                if missing and school_id in own
                else "",
            }
        )
    weak_rows.sort(key=lambda r: (not r["has_gap"], r["lowest"], r["name"]))

    officers = []
    for member in scope.rows():
        member_weak = [r for r in weak_rows if r["school_id"] in member.school_ids]
        entry = {
            "staff_id": member.staff_id,
            "name": _member_name(member, scope),
            "is_lead": member.is_lead,
            "portfolio": len(member.school_ids),
            "weak_schools": len(member_weak),
            "weak_without_plan": sum(1 for r in member_weak if r["has_gap"]),
            **_member_links(member, fy),
        }
        entry["scores"] = []
        for code in SPIRITUAL_INTERVENTIONS:
            current = officer_score(member, code, latest_fy)
            previous = officer_score(member, code, prev_fy)
            entry["scores"].append(
                {
                    "code": code,
                    "abbr": intervention_abbr(code),
                    "name": INTERVENTION_LABELS[code],
                    "score": current,
                    "tone": ssa_band(current)[2],
                    "delta": round(current - previous, 1)
                    if current is not None and previous is not None
                    else None,
                }
            )
        officers.append(entry)

    # Christian Transformation, CC-SEL and camps, by programme and deliverer.
    programmes = _spiritual_programmes()
    rows = []
    if programmes and scope.owner_by_id:
        rows = list(
            Activity.objects.filter(
                scope.activity_filter(), fy=fy, deleted_at__isnull=True
            )
            .filter(
                Q(training_course_id__in=list(programmes))
                | Q(catalogue_item_id__in=list(programmes))
            )
            .exclude(status__in=NOT_PLANNED_STATUSES)
            .order_by("planned_date", "id")
            .values(*TRAINING_FIELDS)
        )
    reach = _reach(rows)
    by_programme: dict[str, list] = defaultdict(list)
    for row in rows:
        by_programme[_programme_id(row, programmes) or ""].append(row)
    programme_rows = [
        {
            "id": programme_id,
            "name": programme["display_name"],
            "family": families[programme["family"]],
            **_fold(by_programme.get(programme_id, []), reach),
        }
        for programme_id, programme in programmes.items()
        if by_programme.get(programme_id)
    ]
    programme_rows.sort(key=lambda r: (r["family"], -r["delivered"], r["name"]))

    partner_names = _partner_names({r["assigned_partner_id"] for r in rows})
    deliverers: dict[tuple[str, str], dict] = {}
    for row in rows:
        family = programmes[_programme_id(row, programmes)]["family"]
        if row["delivery_type"] == "partner":
            key = ("partner", row["assigned_partner_id"] or "")
            name = partner_names.get(key[1], "Training partner")
            kind = "Training partner"
        else:
            owner = scope.attribute(
                row["responsible_staff_id"],
                row["monitored_by_staff_id"],
                row["school_id"],
            )
            member = scope.member(owner or "")
            key = ("member", owner or "")
            name = _member_name(member, scope) if member else "Edify staff"
            kind = "Programme Lead" if member and member.is_lead else "Officer"
        entry = deliverers.setdefault(
            key,
            {
                "name": name,
                "kind": kind,
                FAMILY_CT: 0,
                FAMILY_CC_SEL: 0,
                FAMILY_CAMP: 0,
                "delivered": 0,
                "to_deliver": 0,
            },
        )
        if row["status"] in COMPLETED_WORK_STATUSES:
            entry[family] += 1
            entry["delivered"] += 1
        elif row["status"] in LIVE_STATUSES:
            entry["to_deliver"] += 1
    deliverer_rows = sorted(
        deliverers.values(),
        key=lambda r: (r["kind"] == "Training partner", -r["delivered"], r["name"]),
    )

    # The Regional Lead's Biblical-integration ratings.
    observations = _observation_rows(principal, scope, fy)
    courses = _courses({o["course_id"] for o in observations})
    observation_partners = _partner_names({o["partner_id"] for o in observations})
    people = _people_names(
        scope, {o["activity__responsible_staff_id"] for o in observations}
    )
    recommendation_labels = _recommendation_labels()
    rating_labels = _rating_labels()
    latest = []
    for observation in observations:
        if observation["partner_id"]:
            by = observation_partners.get(observation["partner_id"], "Training partner")
        else:
            member = scope.member(observation["owner"] or "")
            by = people.get(observation["activity__responsible_staff_id"] or "") or (
                _member_name(member, scope) if member else "Edify staff"
            )
        biblical = observation["rating_biblical_integration"]
        latest.append(
            {
                "id": observation["id"],
                "training": _observation_training(observation, courses),
                "delivered_by": by,
                "held_on": observation["held_on"],
                "biblical": biblical,
                "biblical_label": rating_labels.get(biblical, ""),
                "biblical_tone": "success"
                if (biblical or 0) >= 3
                else ("warning" if biblical == 2 else ("danger" if biblical else "")),
                "is_spiritual": observation["course_id"] in programmes,
                "recommendation": recommendation_labels.get(
                    observation["recommendation"], ""
                ),
                "state": _feedback_state(observation, scope),
            }
        )
    spiritual_observations = [o for o in observations if o["course_id"] in programmes]

    weak_without_plan = sum(1 for r in weak_rows if r["has_gap"])
    delivered_programmes = sum(r["delivered"] for r in programme_rows)
    return {
        "summary": {
            "pair": " or ".join(intervention_abbr(c) for c in SPIRITUAL_INTERVENTIONS),
            "latest_fy": latest_fy,
            "prev_fy": prev_fy,
            "weak_schools": len(weak_rows),
            "weak_without_plan": weak_without_plan,
            "programmes_delivered": delivered_programmes,
            "programmes_to_deliver": sum(r["to_deliver"] for r in programme_rows),
            "observed": len(observations),
            "biblical": _mean([o["rating_biblical_integration"] for o in observations]),
            "spiritual_observed": len(spiritual_observations),
            "spiritual_biblical": _mean(
                [o["rating_biblical_integration"] for o in spiritual_observations]
            ),
        },
        "scores": scores,
        "officers": officers,
        "weak_schools": weak_rows,
        "programmes": programme_rows,
        "deliverers": deliverer_rows,
        "families": [{"key": key, "name": label} for key, label in SPIRITUAL_FAMILIES],
        "observations": latest,
    }


def _rating_labels() -> dict:
    from apps.cce_leadership.models import RATING_SCALE

    return dict(RATING_SCALE)


# ── The page ─────────────────────────────────────────────────────────────────
def clean_view(value) -> str:
    value = (value or "").strip().lower()
    return value if value in VIEWS else DEFAULT_VIEW


def clean_fy(value) -> str:
    value = (value or "").strip()
    return value if value in fy_options() else get_operational_fy()


def _scope_summary(scope: RolloutScope) -> dict:
    return {
        "lead_staff_id": scope.lead_staff_id or "",
        "lead_name": scope.lead_name,
        "support_view": scope.support_view,
        "officer_count": len(scope.officers),
        "school_count": len(scope.schools),
        "own_school_count": len(scope.lead.school_ids) if scope.lead else 0,
        "cluster_count": len(scope.cluster_ids),
        "leads": list(scope.leads),
        "has_lead": bool(scope.lead_user_id),
    }


def build_rollout(principal, *, view: str, fy: str, lead=None, today=None) -> dict:
    today = today or timezone.localdate()
    scope = resolve_rollout_scope(principal, lead=lead)
    payload = {"view": view, "fy": fy, "today": today, "scope": _scope_summary(scope)}
    if view == "ssa":
        payload["ssa"] = ssa_rollout(scope, fy)
    elif view == "spiritual":
        payload["spiritual"] = spiritual_rollout(principal, scope, fy, today)
    else:
        payload["trainings"] = trainings_rollout(principal, scope, fy, today)
    return payload


def get_rollout(principal, *, view=None, fy=None, lead=None, today=None) -> dict:
    """The page's payload for one view, cached like a role dashboard: keyed by
    the viewer, the view, the year, the lead an administrator chose and the
    day (so "the next 30 days" moves at midnight). Only the view asked for is
    built."""
    from apps.core.cache_utils import cached_role_dashboard

    view = clean_view(view)
    fy = clean_fy(fy)
    today = today or timezone.localdate()
    lead = (
        (lead or "").strip() if getattr(principal, "active_role", "") == ADMIN else ""
    )
    if getattr(principal, "active_role", "") not in (PROGRAM_LEAD, ADMIN):
        raise Forbidden("Programme Rollout shows a Programme Lead's team.")
    return cached_role_dashboard(
        "programme_rollout",
        principal,
        (view, fy, lead, today.isoformat()),
        lambda: build_rollout(
            principal, view=view, fy=fy, lead=lead or None, today=today
        ),
    )


def school_list(
    principal, *, kind: str, fy=None, member=None, cluster=None, lead=None
) -> dict:
    """The schools behind one cell: an officer's (or a cluster's, or the
    team's) schools in one SSA state, or not yet trained this year.

    Refuses an officer or cluster outside the lead's team rather than showing
    an empty list, so a hand-edited link cannot read another team."""
    if kind not in LIST_KINDS:
        raise BadRequest("Choose which schools to list.")
    fy = clean_fy(fy)
    lead = lead if getattr(principal, "active_role", "") == ADMIN else None
    scope = resolve_rollout_scope(principal, lead=lead)
    member = (member or "").strip()
    cluster = (cluster or "").strip()
    if member:
        found = scope.member(member)
        if found is None:
            raise NotFoundError("That officer is not on this team.")
        school_ids = set(found.school_ids)
        whose = _member_name(found, scope)
    elif cluster:
        if cluster != NO_CLUSTER and cluster not in scope.cluster_ids:
            raise NotFoundError("That cluster holds none of this team's schools.")
        school_ids = {
            sid
            for sid, school in scope.schools.items()
            if (school["cluster_id"] or NO_CLUSTER) == cluster
        }
        whose = (
            scope.cluster_names.get(cluster, "Cluster")
            if cluster != NO_CLUSTER
            else "Schools not in a cluster"
        )
    else:
        school_ids = scope.school_ids
        whose = "The whole team" if scope.officers else "Your portfolio"

    if kind == "not_trained":
        trained = trained_school_ids(scope.school_ref(), fy=fy) if school_ids else set()
        chosen = {sid: "No verified training this FY" for sid in school_ids - trained}
    else:
        wanted = kind.removeprefix("ssa_")
        states = ssa_states(scope, fy)
        chosen = {
            sid: states[sid]["detail"]
            for sid in school_ids
            if states.get(sid, {}).get("state") == wanted
        }
    rows = sorted(
        (
            {
                "school_id": sid,
                "name": scope.schools[sid]["name"],
                "district": scope.schools[sid]["district"],
                "cluster": scope.cluster_names.get(
                    scope.schools[sid]["cluster_id"] or "", ""
                ),
                "officer": ", ".join(
                    _member_name(scope.member(o), scope)
                    for o in scope.owners_by_school.get(sid, [])
                    if scope.member(o)
                ),
                "detail": detail,
                "url": f"/schools/{sid}",
            }
            for sid, detail in chosen.items()
            if sid in scope.schools
        ),
        key=lambda r: (r["name"], r["school_id"]),
    )
    return {
        "title": LIST_KINDS[kind],
        "subtitle": f"{whose} · FY {fy}",
        "rows": rows[:DRAWER_ROWS],
        "total": len(rows),
        "truncated": len(rows) > DRAWER_ROWS,
        "fy": fy,
    }
