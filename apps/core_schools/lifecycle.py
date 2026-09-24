"""Core lifecycle presentation, separate from the core-only service package."""

from collections import defaultdict

from django.db.models import Q

from apps.core.activity_types import TRAINING_TYPES, VISIT_TYPES
from apps.planning.visit_gate import PROGRAMME_SCHOOL_TYPES

CORE_LIFECYCLE_TYPES = ("core", *PROGRAMME_SCHOOL_TYPES)


def school_work(schools, fy):
    """School-specific ledger rows, including explicit cluster invitations.

    Reading these rows never creates package slots. A shared cluster session
    appears once per invited/attending school, even when it also has a direct
    school reference.
    """
    from apps.activities.models import Activity, ClusterActivityAttendance

    schools = list(schools)
    ids = {s.id for s in schools}
    work = defaultdict(list)
    if not ids:
        return work
    invitations = ClusterActivityAttendance.objects.filter(
        school_id__in=ids,
    ).filter(Q(invited=True) | Q(attended=True))
    invited = defaultdict(set)
    for activity_id, school_id in invitations.values_list("activity_id", "school_id"):
        invited[activity_id].add(school_id)
    activities = (
        Activity.objects.filter(
            Q(school_id__in=ids) | Q(id__in=invited),
            deleted_at__isnull=True,
            fy=str(fy),
            activity_type__in=VISIT_TYPES + TRAINING_TYPES,
        )
        .exclude(
            status__in=(
                "cancelled",
                "rejected",
                "deferred",
                "not_planned",
                "awaiting_owner_approval",
            )
        )
        .order_by("planned_date", "id")
        # The five columns the rows below read. A country's programme schools
        # carry thousands of activities, and loading every one of Activity's
        # ~120 columns (JSON snapshots included) was most of this read.
        .only("id", "school_id", "activity_type", "planned_date", "status")
    )
    for activity in activities:
        targets = set(invited[activity.id])
        if activity.school_id in ids:
            targets.add(activity.school_id)
        for school_id in targets:
            work[school_id].append(
                {
                    "id": activity.id,
                    "kind": "Visit"
                    if activity.activity_type in VISIT_TYPES
                    else "Training",
                    "name": activity.get_activity_type_display(),
                    "date": activity.planned_date,
                    "status": activity.get_status_display(),
                }
            )
    return work


def programme_rows(schools, fy, *, user=None, readonly=True):
    from apps.core.scoping import may_plan_school, resolve_user_scope
    from apps.planning.fy_policy import planning_horizon
    from apps.planning.school_planning_badges import SchoolPlanningBadgeService

    schools = list(schools)
    badges = SchoolPlanningBadgeService.get_for_schools(
        [s.id for s in schools], financial_year=planning_horizon(fy)
    )
    work = school_work(schools, fy)
    scope = resolve_user_scope(user) if user and not readonly else None
    return [
        {
            "id": s.id,
            "school_id": s.school_id,
            "name": s.name,
            "school_type": s.school_type,
            "district": getattr(s.district, "name", ""),
            "planning_badges": badges[s.id],
            "work": work[s.id],
            "can_schedule": bool(scope and may_plan_school(scope, s)),
        }
        for s in schools
    ]


def programme_sections(user, filters, *, lens="direct", params=None, per_page=15):
    """Independently paginated category tables; no package initialization."""
    from django.core.paginator import Paginator
    from apps.core.scoping import (
        direct_portfolio_schools,
        team_oversight_schools,
        resolve_user_scope,
    )
    from apps.schools.programme_schools import type_options

    scope = resolve_user_scope(user)
    qs = (
        team_oversight_schools(scope)
        if lens == "oversight"
        else direct_portfolio_schools(scope)
    )
    if qs is None:
        return []
    qs = qs.filter(deleted_at__isnull=True, school_type__in=PROGRAMME_SCHOOL_TYPES)
    query = filters.get("q")
    if query:
        qs = qs.filter(
            Q(name__icontains=query)
            | Q(school_id__icontains=query)
            | Q(district__name__icontains=query)
            | Q(account_owner_name_raw__icontains=query)
        )
    for key, field in (
        ("region", "region_id"),
        ("district", "district_id"),
        ("staff", "account_owner_id"),
        ("school_type_filter", "school_type"),
        ("ssa_status", "current_fy_ssa_status"),
    ):
        value = filters.get(key)
        if value and value != "All":
            qs = qs.filter(**{field: value})
    # Programme schools do not take partner assignments.
    if (
        filters.get("partner") not in (None, "", "All")
        or filters.get("partner_assigned") == "assigned"
    ):
        qs = qs.none()
    sections = []
    for kind, label in type_options():
        param = f"{kind}_page"
        page = Paginator(
            qs.filter(school_type=kind)
            .select_related("district")
            .order_by("name", "id"),
            per_page,
        ).get_page((params or {}).get(param))
        sections.append(
            {
                "kind": kind,
                "label": label,
                "page": page,
                "param": param,
                "rows": programme_rows(
                    page.object_list,
                    filters["fy"],
                    user=user,
                    readonly=lens == "oversight",
                ),
            }
        )
    return sections
