"""Planned and completed activities on a profile page.

Owner, 2026-09-28: "add list of planned and completed activities on every
profile (Cluster, school, organization...) with the action button to complete,
view activity, reschedule and cancel activities."

Every profile — a school, a cluster, a partner organisation, a district, a
project, a staff member — asks its own question of the activity table (which
rows belong here), and then shows the answer the same way: two tabs, Planned
and Completed, each a paged table whose rows carry one Actions menu. This
module is the second half. Each profile view hands it a queryset; it splits,
orders, pages and decorates it, and `partials/components/profile_activities.html`
draws it.

The split follows the Planning badges (apps.planning.school_planning_badges),
so a profile and a Planning row cannot disagree about whether work is
planned or done:

* Planned — a live plan still to be delivered (planned, scheduled, with a
  partner, in progress) or returned for replanning, plus a visit request
  awaiting its school owner's approval.
* Completed — delivered: submitted and awaiting verification, or verified.

Cancelled, rejected, deferred and never-planned rows are neither.

Actions are the server's own rules, asked per row, so a menu never offers what
the endpoint behind it would refuse (owner, 2026-09-27: role-blocked features
are hidden, not greyed):

* View — every row; the drawer re-checks `can_view_record`.
* Edit — staff work the reader may run: open while it is still scheduled,
  greyed with its reason once it has been carried out (owner, 2026-10-02;
  apps.activities.editing). A status lock is shown; a role lock is hidden.
* Complete, Reschedule, Cancel — open staff work the reader may execute: the
  same `_assert_in_scope`, `_assert_may_schedule` and `_assert_may_execute`
  the actions themselves run, and the `my_plan` page gate the drawers carry.
  A supervisor reads their team's work and does not run it (§1B), so a
  Programme Lead sees View on a CCEO's row and all four on their own.
  Partner-delivered work is completed by the partner and confirmed on Partner
  Monitoring, so it offers View only here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from django.db.models import F
from django.db.models.functions import Coalesce

from apps.core.clock import local_day
from apps.core.pagination import paginate_rows
from apps.planning.school_planning_badges import (
    AWAITING_VERIFICATION_STATUSES,
    NEEDS_REPLANNING_STATUSES,
    PLANNED_STATUSES,
    VERIFIED_STATUSES,
)

#: Rows per page in each tab: the platform's table page (owner, 2026-10-02:
#: every table holds 50 records a page).
PAGE_SIZE = 50

#: Work still to be delivered — the Planned tab.
OPEN_STATUSES = frozenset(
    PLANNED_STATUSES | NEEDS_REPLANNING_STATUSES | {"awaiting_owner_approval"}
)
#: Work delivered — the Completed tab.
DELIVERED_STATUSES = frozenset(AWAITING_VERIFICATION_STATUSES | VERIFIED_STATUSES)
#: Delivered, but the executor has not yet submitted it: their Complete action
#: still has the Salesforce ID or the evidence to take.
_STILL_COMPLETING = frozenset(
    {"evidence_uploaded", "evidence_accepted", "salesforce_id_required"}
)

TABS = ("planned", "completed")

# Badge tones (components/badge.html): green done, blue planned or waiting on
# a reviewer, amber for what needs the executor, red for overdue or returned
# (owner, 2026-09-27: "green done / blue planned").
TONE_DONE = "success"
TONE_PLANNED = "info"
TONE_ATTENTION = "warning"
TONE_LATE = "danger"


@dataclass
class ProfileActivityRow:
    id: str
    title: str
    type_label: str
    day: date | None
    end_day: date | None
    subject: str
    subject_url: str
    executor: str
    purpose: str
    status_label: str
    status_tone: str
    is_partner_work: bool = False
    may_view: bool = True
    may_complete: bool = False
    complete_label: str = "Complete"
    may_reschedule: bool = False
    may_cancel: bool = False
    #: Edit (owner, 2026-10-02): offered while the work is still scheduled,
    #: greyed once it has been carried out (apps.activities.editing).
    may_edit: bool = False
    edit_locked: bool = False

    @property
    def has_owner_actions(self) -> bool:
        return self.may_complete or self.may_reschedule or self.may_cancel


@dataclass
class ProfileActivities:
    """Both tabs of one profile's activity section."""

    param: str
    active_tab: str
    planned: dict = field(default_factory=dict)
    completed: dict = field(default_factory=dict)
    overdue: int = 0

    @property
    def tab_param(self) -> str:
        return f"{self.param}_tab"

    @property
    def planned_param(self) -> str:
        return f"{self.param}_planned_page"

    @property
    def completed_param(self) -> str:
        return f"{self.param}_done_page"

    @property
    def planned_total(self) -> int:
        return self.planned.get("total", 0)

    @property
    def completed_total(self) -> int:
        return self.completed.get("total", 0)


# ── Which activities belong to each profile ──────────────────────────────────
# Each returns an unordered queryset; `profile_activities` orders and pages it.


def for_school(school):
    """Work at the school, and the cluster sessions it was invited to or
    attended — the same link the Planning training badge reads
    (ClusterActivityAttendance), never mere cluster membership."""
    from django.db.models import Q

    from apps.activities.models import Activity, ClusterActivityAttendance

    sessions = ClusterActivityAttendance.objects.filter(school_id=school.id).filter(
        Q(invited=True) | Q(attended=True)
    )
    return Activity.objects.filter(
        Q(school_id=school.id) | Q(id__in=sessions.values("activity_id"))
    )


def for_cluster(cluster):
    """The cluster's own sessions and the work at its member schools."""
    from django.db.models import Q

    from apps.activities.models import Activity
    from apps.schools.models import School

    members = School.objects.filter(cluster_id=cluster.id, deleted_at__isnull=True)
    return Activity.objects.filter(
        Q(cluster_id=cluster.id) | Q(school_id__in=members.values("id"))
    )


def for_partner(partner_id):
    """Work the partner delivers, or facilitates for a staff training."""
    from django.db.models import Q

    from apps.activities.models import Activity

    return Activity.objects.filter(
        Q(assigned_partner_id=partner_id) | Q(facilitating_partner_id=partner_id)
    )


def for_district(district_id):
    """Work at the district's schools, its clusters' sessions, and programme
    events held in it."""
    from django.db.models import Q

    from apps.activities.models import Activity

    return Activity.objects.filter(
        Q(school__district_id=district_id)
        | Q(cluster__district_id=district_id)
        | Q(school__isnull=True, cluster__isnull=True, event_district_id=district_id)
    )


def visible_to(queryset, principal):
    """Narrow a profile's activities to the reader's scope.

    For a profile page that is itself not scoped — a district is a place, and
    any planner may open it — so a Programme Lead reads their team's work
    there, not the whole district's. Country readers keep everything.
    """
    from django.db.models import Q

    from apps.core.scoping import owner_ids, resolve_user_scope

    scope = resolve_user_scope(principal)
    if scope.country_scope:
        return queryset
    mine = owner_ids(principal)
    return queryset.filter(
        Q(school_id__in=scope.school_ids or [])
        | Q(cluster_id__in=scope.cluster_ids or [])
        | Q(responsible_staff_id__in=list(scope.staff_ids or []) + mine)
        | Q(monitored_by_staff_id__in=mine)
        | Q(assigned_partner_id__in=scope.partner_ids or [])
    )


def for_project(project_id):
    from apps.activities.models import Activity

    return Activity.objects.filter(project_id=project_id)


def for_staff(ids):
    """The person's own work, in both id spaces it is written in
    (`apps.core.scoping.owner_ids`), and partner work they monitor."""
    from django.db.models import Q

    from apps.activities.models import Activity

    ids = [i for i in ids if i]
    return Activity.objects.filter(
        Q(responsible_staff_id__in=ids) | Q(monitored_by_staff_id__in=ids)
    )


def _page(request, param: str) -> int:
    try:
        return max(1, int(request.GET.get(param) or 1))
    except (TypeError, ValueError):
        return 1


def profile_activities(
    request,
    queryset,
    *,
    param: str = "acts",
    subject: str = "school",
    today: date | None = None,
) -> ProfileActivities:
    """The Planned and Completed tables for one profile.

    `queryset` is the profile's own question — the activities that belong to
    this school, cluster, partner… — and may be unordered. `subject` names
    what the Where column shows: "school", "cluster" or "auto" (the school a
    visit is at, else the cluster a session is for). `param` prefixes every
    query parameter, so two profiles' tables on one page never page together.
    """
    today = today or date.today()
    live = queryset.filter(deleted_at__isnull=True)
    planned_qs = live.filter(status__in=OPEN_STATUSES).order_by(
        F("planned_date").asc(nulls_last=True), "created_at", "id"
    )
    completed_qs = (
        live.filter(status__in=DELIVERED_STATUSES)
        .annotate(_done_on=Coalesce("actual_delivery_date", "planned_date"))
        .order_by(F("_done_on").desc(nulls_last=True), "-created_at", "id")
    )
    result = ProfileActivities(param=param, active_tab="planned")
    requested = (request.GET.get(result.tab_param) or "").strip()

    result.planned = paginate_rows(
        planned_qs.select_related("school", "cluster"),
        page=_page(request, result.planned_param),
        page_size=PAGE_SIZE,
    )
    result.completed = paginate_rows(
        completed_qs.select_related("school", "cluster"),
        page=_page(request, result.completed_param),
        page_size=PAGE_SIZE,
    )
    result.overdue = planned_qs.filter(
        planned_date__lt=today, status__in=PLANNED_STATUSES
    ).count()
    if requested in TABS:
        result.active_tab = requested
    elif not result.planned["total"] and result.completed["total"]:
        # Nothing left to deliver: open on what was delivered rather than on
        # an empty table.
        result.active_tab = "completed"

    rows = list(result.planned["rows"]) + list(result.completed["rows"])
    decorated = _decorate(request.user, rows, subject=subject, today=today)
    result.planned["rows"] = decorated[: len(result.planned["rows"])]
    result.completed["rows"] = decorated[len(result.planned["rows"]) :]
    return result


def _decorate(principal, activities, *, subject: str, today: date) -> list:
    from apps.core.enums import ActivityType, SsaIntervention
    from apps.core.permissions import RolePermissionService

    if not activities:
        return []
    staff = _staff_names(a.responsible_staff_id for a in activities)
    partners = _partner_names(a.assigned_partner_id for a in activities)
    type_labels = dict(ActivityType.choices)
    interventions = dict(SsaIntervention.choices)
    may_run_pages = RolePermissionService.can_view_page(principal, "my_plan")

    rows = []
    for a in activities:
        is_partner = a.delivery_type == "partner" or a.status in (
            "assigned_to_partner",
            "partner_scheduled",
        )
        type_label = type_labels.get(
            a.activity_type, (a.activity_type or "").replace("_", " ").title()
        )
        label, tone = _status(a, today)
        where, where_url = _subject(a, subject)
        executor = (
            partners.get(a.assigned_partner_id, "Partner")
            if is_partner and a.assigned_partner_id
            else staff.get(a.responsible_staff_id, "")
        )
        purpose = interventions.get(a.purpose_intervention or "", "") or (
            a.activity_purpose_text or ""
        )
        row = ProfileActivityRow(
            id=a.id,
            title=a.activity_name_snapshot or type_label,
            type_label=type_label,
            day=a.actual_delivery_date
            if a.status in DELIVERED_STATUSES and a.actual_delivery_date
            else a.planned_date
            or (local_day(a.scheduled_date) if a.scheduled_date else None),
            end_day=a.end_date if a.end_date and a.end_date != a.planned_date else None,
            subject=where,
            subject_url=where_url,
            executor=executor or "—",
            purpose=purpose,
            status_label=label,
            status_tone=tone,
            is_partner_work=is_partner,
        )
        if may_run_pages and not is_partner and _may_run(a, principal):
            from apps.activities.editing import is_editable, is_executed

            row.may_edit = is_editable(a)
            row.edit_locked = is_executed(a)
            if a.status in OPEN_STATUSES:
                awaiting = a.status == "awaiting_owner_approval"
                # A visit request is the owner's to decide: the requester
                # withdraws it (Cancel) rather than completing or moving it.
                row.may_complete = not awaiting and a.status not in (
                    NEEDS_REPLANNING_STATUSES
                )
                # Work already under way keeps its day (services.reschedule
                # refuses it; owner, 2026-10-02).
                row.may_reschedule = not awaiting and not row.edit_locked
                row.may_cancel = True
            elif a.status in _STILL_COMPLETING:
                row.may_complete = True
                row.complete_label = "Finish completion"
        rows.append(row)
    return rows


def _may_run(activity, principal) -> bool:
    """The three checks the complete, reschedule and cancel services run."""
    from apps.activities.services import (
        _assert_in_scope,
        _assert_may_execute,
        _assert_may_schedule,
    )
    from apps.core.exceptions import BadRequest, Forbidden, NotFoundError

    try:
        _assert_in_scope(activity, principal)
        _assert_may_schedule(activity, principal)
        _assert_may_execute(activity, principal)
    except (Forbidden, BadRequest, NotFoundError):
        return False
    return True


def _status(activity, today: date) -> tuple[str, str]:
    """The status a profile row reads, in the platform's words.

    Delivered work reads as the Planning badges and the cluster oversight
    tables read it: Complete once verified, PL Pending / IA Pending while a
    reviewer holds it. Planned work adds the one thing a monitor most needs
    and My Plan's labels leave to a separate table: a date already passed.
    """
    status = activity.status or ""
    if status in VERIFIED_STATUSES:
        return "Complete", TONE_DONE
    if status == "submitted_to_pl":
        return "PL Pending", TONE_PLANNED
    if status == "awaiting_ia_verification":
        return "IA Pending", TONE_PLANNED
    if status == "completed":
        return "Awaiting Verification", TONE_PLANNED
    if status in _STILL_COMPLETING:
        if status == "salesforce_id_required" or not activity.salesforce_activity_id:
            return "Activity ID Missing", TONE_ATTENTION
        return "Evidence Uploaded", TONE_ATTENTION
    if status in NEEDS_REPLANNING_STATUSES:
        return "Returned for Correction", TONE_LATE
    if status == "awaiting_owner_approval":
        return "Awaiting Owner Approval", TONE_ATTENTION
    if status == "assigned_to_partner":
        return "Partner to Schedule", TONE_PLANNED
    if status == "partner_scheduled":
        label = "Partner Scheduled"
    elif status in ("in_progress", "completion_started"):
        return "In Progress", TONE_PLANNED
    else:
        label = "Rescheduled" if (activity.reschedule_count or 0) else "Scheduled"
    day = activity.planned_date
    if day and day < today:
        return "Overdue", TONE_LATE
    if day == today:
        return "Due Today", TONE_ATTENTION
    return label, TONE_PLANNED


def _subject(activity, subject: str) -> tuple[str, str]:
    school = activity.school if activity.school_id else None
    cluster = activity.cluster if activity.cluster_id else None
    if subject == "cluster" and cluster:
        return cluster.name, f"/clusters/{cluster.id}"
    if school and subject in ("school", "auto"):
        return school.name, f"/schools/{school.school_id}"
    if cluster:
        return cluster.name, f"/clusters/{cluster.id}"
    if school:
        return school.name, f"/schools/{school.school_id}"
    return (activity.venue or "Programme work"), ""


def _staff_names(staff_ids) -> dict[str, str]:
    """Names in both id spaces an activity's owner is written in."""
    from django.db.models import Q

    from apps.accounts.models import StaffProfile, User

    ids = {i for i in staff_ids if i}
    if not ids:
        return {}
    names: dict[str, str] = {}
    for profile in StaffProfile.objects.filter(
        Q(id__in=ids) | Q(user_id__in=ids)
    ).select_related("user"):
        name = (profile.user.name or profile.user.email) if profile.user_id else ""
        names[profile.id] = name
        if profile.user_id:
            names[str(profile.user_id)] = name
    missing = ids - names.keys()
    if missing:
        names.update(
            {
                str(uid): name or email
                for uid, name, email in User.objects.filter(id__in=missing).values_list(
                    "id", "name", "email"
                )
            }
        )
    return names


def _partner_names(partner_ids) -> dict[str, str]:
    from apps.partners.models import Partner

    ids = {p for p in partner_ids if p}
    if not ids:
        return {}
    return dict(Partner.objects.filter(id__in=ids).values_list("id", "name"))


__all__ = [
    "DELIVERED_STATUSES",
    "OPEN_STATUSES",
    "ProfileActivities",
    "ProfileActivityRow",
    "profile_activities",
]
