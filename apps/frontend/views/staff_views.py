"""
GROUP 1 — Core Operations Views
Staff Directory, Staff Profile, Today, Visits, Trainings, Evidence, Targets, My-Team, Notifications, Profile
"""

from apps.core.activity_types import COMPLETED_WORK_STATUSES
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.http import url_has_allowed_host_and_scheme

from apps.core.permissions import render_access_denied, require_page_permission
from apps.core.scoping import owner_ids
from django.db.models import Q, Count
from django.utils import timezone
from datetime import date, timedelta

from apps.accounts.models import User, StaffProfile
from apps.activities.models import Activity
from apps.notifications.models import Notification
from apps.core.fy import get_operational_fy
from apps.core.activity_types import TRAINING_TYPES, VISIT_TYPES


# ─── STAFF DIRECTORY ──────────────────────────────────────────────────────────


def _directory_may_see_email(user) -> bool:
    """Who may read a colleague's email address in the People Directory.

    `apps/core/rbac.py` annotates the RVP's staff grant as a "region
    staff-performance summary (no PII/email)", and `apps/hr/services.py`
    already strips email for exactly this set on the API roster — the HTML
    directory rendered it to everyone.
    """
    return getattr(user, "active_role", "") in {
        "Admin",
        "HumanResources",
        "CountryDirector",
        "Program Lead",
    }


def _directory_scope(user, qs):
    """Narrow the People Directory to the viewer's authority.

    The directory listed every active user in the deployment with no scope
    filter at all, so any Program Lead could enumerate every other PL's team
    and every country's staff. Mirrors `hr_views._profile_scope`, which already
    gets this right for the HR workspaces.
    """
    role = getattr(user, "active_role", "") or ""
    if role == "Admin":
        return qs
    from apps.core.scoping import resolve_user_scope

    if role == "Program Lead":
        scope = resolve_user_scope(user)
        team = set(scope.supervised_staff_ids or [])
        return qs.filter(Q(staff_profile__id__in=team) | Q(id=user.id))
    sp = getattr(user, "staff_profile", None)
    country = getattr(sp, "country", None)
    if not country:
        return qs.none()
    return qs.filter(staff_profile__country=country)


@require_page_permission("staff_directory")
def staff_directory_view(request):
    """Staff directory — all users in the system with role, district, and school count."""
    from django.core.paginator import Paginator
    from apps.targets.my_targets import _user_ids

    search = request.GET.get("q", "").strip()
    active_tab = request.GET.get("tab", "all")
    page_number = request.GET.get("page", 1)

    staff_qs = (
        User.objects.filter(
            status="active",
            deleted_at__isnull=True,
        )
        .prefetch_related("staff_profile")
        .order_by("name")
    )
    staff_qs = _directory_scope(request.user, staff_qs)
    show_email = _directory_may_see_email(request.user)

    if search:
        # Email is only searchable by someone allowed to see it — otherwise the
        # search box is an oracle that confirms an address without showing it.
        name_match = Q(name__icontains=search)
        staff_qs = staff_qs.filter(
            name_match | Q(email__icontains=search) if show_email else name_match
        )

    if active_tab == "cceo":
        staff_qs = staff_qs.filter(roles__contains=["CCEO"])
    elif active_tab == "pl":
        staff_qs = staff_qs.filter(roles__contains=["Program Lead"])
    elif active_tab == "admin":
        staff_qs = staff_qs.exclude(roles__contains=["CCEO"]).exclude(
            roles__contains=["Program Lead"]
        )

    # Was unbounded (loaded every active user with no LIMIT) with a 2-query
    # per-row N+1 (school_count + completed_visits) on top — paginate the
    # list itself so both the row count and the query count stay flat as
    # headcount grows.
    paginator = Paginator(staff_qs, 20)
    page_obj = paginator.get_page(page_number)
    pages_list = list(
        page_obj.paginator.get_elided_page_range(
            page_obj.number, on_each_side=2, on_ends=1
        )
    )

    staff_list = []

    # KPIs calculation across all active staff (not filtered by tab)
    all_staff_qs = User.objects.filter(
        status="active", deleted_at__isnull=True
    ).prefetch_related("staff_profile")
    total_active = all_staff_qs.count()
    pending_onboarding = 0
    high_risk_count = 0

    # StaffOnboardingState choices are only pending/active/suspended — "pending"
    # is the real state that represents "not yet onboarded".
    pending_onboarding = StaffProfile.objects.filter(onboarding_state="pending").count()

    # Average coverage gap: % of schools org-wide without a completed SSA for
    # the current FY (School.current_fy_ssa_status == "done" is the same
    # source of truth used by apps.clusters.services / apps.analytics.services).
    from apps.schools.models import School

    all_schools_count = School.objects.filter(deleted_at__isnull=True).count()
    schools_with_ssa = School.objects.filter(
        deleted_at__isnull=True, current_fy_ssa_status="done"
    ).count()
    average_coverage_gap = (
        round(100 - (schools_with_ssa / all_schools_count * 100), 1)
        if all_schools_count
        else 0.0
    )

    # High risk (overdue > 3) - let's count for all staff
    today = date.today()
    overdue_counts = (
        Activity.objects.filter(
            planned_date__lt=today,
            status__in=["scheduled", "in_progress", "completion_started"],
            deleted_at__isnull=True,
        )
        .values("responsible_staff_id")
        .annotate(overdue_count=Count("id"))
    )
    high_risk_count = sum(1 for item in overdue_counts if item["overdue_count"] > 3)

    # StaffProfile has no location_name — resolve primary_district_id → name in one query.
    from apps.geography.models import District

    page_staff = list(page_obj)

    _district_ids = {
        u.staff_profile.primary_district_id
        for u in page_staff
        if getattr(u, "staff_profile", None) and u.staff_profile.primary_district_id
    }
    district_names = (
        dict(District.objects.filter(id__in=_district_ids).values_list("id", "name"))
        if _district_ids
        else {}
    )

    # Batch school_count / completed_visits for the whole page in 2 queries
    # instead of 2 queries per staff member (was a confirmed N+1). Activity.
    # responsible_staff_id is a dual id-space field (StaffProfile CUID OR
    # raw User id) — _user_ids() covers both spaces per staff member and
    # every id maps back to the same canonical user, so summing counts
    # across a user's id-space entries can't double count a given activity
    # (each row has exactly one responsible_staff_id value).
    id_to_user = {}
    for u in page_staff:
        for i in _user_ids(u):
            id_to_user[i] = u
    all_ids = list(id_to_user.keys())

    school_ids_by_user = {u.id: set() for u in page_staff}
    if all_ids:
        for row in Activity.objects.filter(
            responsible_staff_id__in=all_ids,
            deleted_at__isnull=True,
            activity_type__in=VISIT_TYPES,
        ).values("responsible_staff_id", "school_id"):
            owner = id_to_user.get(row["responsible_staff_id"])
            if owner and row["school_id"]:
                school_ids_by_user[owner.id].add(row["school_id"])

    completed_visits_by_user = {u.id: 0 for u in page_staff}
    if all_ids:
        for row in (
            Activity.objects.filter(
                responsible_staff_id__in=all_ids,
                status__in=COMPLETED_WORK_STATUSES,
                activity_type__in=VISIT_TYPES,
                deleted_at__isnull=True,
            )
            .values("responsible_staff_id")
            .annotate(c=Count("id"))
        ):
            owner = id_to_user.get(row["responsible_staff_id"])
            if owner:
                completed_visits_by_user[owner.id] += row["c"]

    for u in page_staff:
        profile = getattr(u, "staff_profile", None)
        school_count = len(school_ids_by_user.get(u.id, ()))
        completed_visits = completed_visits_by_user.get(u.id, 0)

        staff_list.append(
            {
                "id": u.id,
                "name": u.name,
                "email": u.email,
                "roles": u.roles or [],
                "active_role": u.active_role,
                "district": district_names.get(profile.primary_district_id, "Unknown")
                if profile
                else "Unknown",
                "status": u.status,
                "profile_id": profile.id if profile else None,
                "onboarding_state": getattr(profile, "onboarding_state", "unknown")
                if profile
                else "no_profile",
                "school_count": school_count,
                "completed_visits": completed_visits,
                "initials": u.name[:2].upper() if u.name else "??",
            }
        )

    kpis = {
        "total_active": total_active,
        "pending_onboarding": pending_onboarding,
        "average_coverage_gap": average_coverage_gap,
        "high_risk": high_risk_count,
    }

    context = {
        "staff": staff_list,
        "total": total_active,
        "search": search,
        "active_tab": active_tab,
        "topbar_search": {
            "placeholder": "Search by name or email…",
            "value": search,
            "action": "/staff",
            "hidden": [{"name": "tab", "value": active_tab}],
        },
        "kpis": kpis,
        "page_obj": page_obj,
        "pages_list": pages_list,
    }
    return render(request, "pages/staff/index.html", context)


# ─── STAFF PROFILE DETAIL ─────────────────────────────────────────────────────


@require_page_permission("staff")
def staff_profile_view(request, user_id):
    """Full staff 360° profile — activities, visits, evidence, SSA coverage."""
    member = get_object_or_404(User, id=user_id, deleted_at__isnull=True)
    # "Never trust the URL" — the same rule the team-targets drawer already
    # applies. Holding the page permission is not authority over an arbitrary
    # employee's 360 profile.
    if not _directory_scope(request.user, User.objects.filter(id=member.id)).exists():
        return render_access_denied(
            request, "You do not have access to this employee's profile."
        )
    fy = get_operational_fy()
    now = date.today()

    # Both id spaces. `responsible_staff_id` and `School.account_owner_id` each
    # hold a StaffProfile id or a User id depending on which path wrote the row,
    # so matching on one alone silently disowns most of a person's work — the
    # regression `owner_ids` exists to end.
    member_ids = owner_ids(member)

    # Activities this FY
    activities = (
        Activity.objects.filter(
            responsible_staff_id__in=member_ids,
            fy=fy,
            deleted_at__isnull=True,
        )
        .select_related("school", "cluster")
        .order_by("-planned_date")[:50]
    )

    completed = [a for a in activities if a.status in COMPLETED_WORK_STATUSES]
    overdue = [
        a
        for a in activities
        if a.planned_date
        and a.planned_date < now
        and a.status in ("scheduled", "in_progress", "completion_started")
    ]
    upcoming = [
        a
        for a in activities
        if a.planned_date and a.planned_date >= now and a.status == "scheduled"
    ]

    # Schools covered
    schools_covered = (
        Activity.objects.filter(
            responsible_staff_id__in=member_ids,
            status__in=COMPLETED_WORK_STATUSES,
            activity_type__in=["school_visit", "follow_up_visit", "coaching_visit"],
            deleted_at__isnull=True,
        )
        .values("school_id", "school__name")
        .distinct()
    )

    profile = getattr(member, "staff_profile", None)

    from apps.schools.models import School
    from apps.ssa.services import get_ssa_progress_by_fy

    assigned_schools = School.objects.filter(
        account_owner_id__in=member_ids, deleted_at__isnull=True
    )
    staff_progress = get_ssa_progress_by_fy(assigned_schools)

    context = {
        "member": member,
        "profile": profile,
        "activities": activities,
        "completed_count": len(completed),
        "overdue_count": len(overdue),
        "upcoming": upcoming[:5],
        "schools_covered": list(schools_covered)[:10],
        "initials": member.name[:2].upper() if member.name else "??",
        "staff_progress": staff_progress,
    }
    return render(request, "pages/staff/detail.html", context)


# ─── TODAY VIEW ───────────────────────────────────────────────────────────────


@require_page_permission("dashboard")
def today_view(request):
    """Today's command center — overdue, today, upcoming, and pending actions."""
    user = request.user
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)

    # Overdue activities (past due, not yet completed)
    overdue = (
        Activity.objects.filter(
            responsible_staff_id=user.id,
            planned_date__lt=today,
            status__in=["scheduled", "in_progress", "completion_started"],
            deleted_at__isnull=True,
        )
        .select_related("school", "cluster")
        .order_by("planned_date")
    )

    # Today's activities
    today_activities = (
        Activity.objects.filter(
            responsible_staff_id=user.id,
            planned_date=today,
            deleted_at__isnull=True,
        )
        .select_related("school", "cluster")
        .order_by("activity_type")
    )

    # This week remaining
    upcoming_week = (
        Activity.objects.filter(
            responsible_staff_id=user.id,
            planned_date__range=[today + timedelta(days=1), week_end],
            status="scheduled",
            deleted_at__isnull=True,
        )
        .select_related("school", "cluster")
        .order_by("planned_date")
    )

    # Evidence missing (completed but no evidence)
    evidence_gap = Activity.objects.filter(
        responsible_staff_id=user.id,
        status__in=COMPLETED_WORK_STATUSES,
        evidence__isnull=True,
        deleted_at__isnull=True,
    ).select_related("school")[:5]

    # Unread notifications
    notifications = Notification.objects.filter(
        recipient_id=user.id,
        status="unread",
    ).order_by("-created_at")[:5]

    context = {
        "overdue": overdue,
        "today_activities": today_activities,
        "upcoming_week": upcoming_week,
        "evidence_gap": evidence_gap,
        "notifications": notifications,
        "today": today,
        "week_start": week_start,
        "week_end": week_end,
    }
    return render(request, "pages/today/index.html", context)


# ─── VISITS LOG ───────────────────────────────────────────────────────────────


@require_page_permission("my_plan")
def visits_log_view(request):
    """All school visits for the current user — filterable by status."""
    user = request.user
    status_filter = request.GET.get("status", "")
    search = request.GET.get("q", "").strip()

    visits_qs = (
        Activity.objects.filter(
            responsible_staff_id=user.id,
            activity_type__in=VISIT_TYPES,
            deleted_at__isnull=True,
        )
        .select_related("school", "cluster")
        .order_by("-planned_date")
    )

    if status_filter:
        visits_qs = visits_qs.filter(status=status_filter)
    if search:
        visits_qs = visits_qs.filter(
            Q(school__name__icontains=search) | Q(cluster__name__icontains=search)
        )

    visits = list(visits_qs[:100])
    completed = sum(1 for v in visits if v.status in COMPLETED_WORK_STATUSES)
    pending = sum(
        1
        for v in visits
        if v.status in ("scheduled", "in_progress", "completion_started")
    )

    context = {
        "visits": visits,
        "total": len(visits),
        "completed": completed,
        "pending": pending,
        "status_filter": status_filter,
        "search": search,
    }
    return render(request, "pages/visits/index.html", context)


# ─── TRAININGS LOG ────────────────────────────────────────────────────────────


@require_page_permission("my_plan")
def trainings_log_view(request):
    """All group training sessions for the current user."""
    user = request.user
    status_filter = request.GET.get("status", "")
    search = request.GET.get("q", "").strip()

    # "group_training" and "teachers_training" are not real ActivityType
    # enum members (see apps.core.enums.ActivityType) so they never matched
    # anything -- only cluster_training activities ever showed up here. Use
    # the real training-type enum members instead.

    trainings_qs = (
        Activity.objects.filter(
            responsible_staff_id=user.id,
            activity_type__in=TRAINING_TYPES,
            deleted_at__isnull=True,
        )
        .select_related("school", "cluster")
        .order_by("-planned_date")
    )

    if status_filter:
        trainings_qs = trainings_qs.filter(status=status_filter)
    if search:
        trainings_qs = trainings_qs.filter(
            Q(school__name__icontains=search) | Q(cluster__name__icontains=search)
        )

    trainings = list(trainings_qs[:100])
    completed = sum(1 for t in trainings if t.status in COMPLETED_WORK_STATUSES)

    context = {
        "trainings": trainings,
        "total": len(trainings),
        "completed": completed,
        "status_filter": status_filter,
        "search": search,
    }
    return render(request, "pages/trainings/index.html", context)


# ─── EVIDENCE GALLERY ─────────────────────────────────────────────────────────


@require_page_permission("planning")
def evidence_gallery_view(request):
    """Legacy /evidence (no trailing slash) route.

    This used to render "pages/evidence/index.html" with its own bespoke
    context (evidence_list/pending_evidence/kind_filter/kinds), which doesn't
    match any variable the template actually uses (pending/sf_missing/
    submitted/returned/ia_pending/verified/partner_ev — see
    my_plan_views.evidence_center_view, the real owner of that template) so
    every tab rendered empty. Redirect to the working Evidence Center page
    instead of maintaining a second, incompatible implementation.
    """
    return redirect("/evidence/")


# ─── MY TARGETS ───────────────────────────────────────────────────────────────

# See trainings_log_view for why "group_training"/"teachers_training" are
# wrong -- kept in sync with the real ActivityType enum members.
_QUARTERS = ["Q1", "Q2", "Q3", "Q4"]


def _quarter_completed_counts(activity_types, fy, staff_ids):
    """Real per-quarter completed-activity counts for this FY, scoped to staff.
    Accepts one id or an iterable — Activity.responsible_staff_id is canonically
    a StaffProfile id but legacy rows key it by User.id, so pass both forms."""
    if isinstance(staff_ids, str):
        staff_ids = [staff_ids]
    rows = (
        Activity.objects.filter(
            responsible_staff_id__in=list(staff_ids),
            activity_type__in=activity_types,
            fy=fy,
            status__in=COMPLETED_WORK_STATUSES,
            deleted_at__isnull=True,
        )
        .values("quarter")
        .annotate(n=Count("id"))
    )
    counts = {q: 0 for q in _QUARTERS}
    for r in rows:
        if r["quarter"] in counts:
            counts[r["quarter"]] = r["n"]
    return counts


def _cumulative_period_row(label, cumulative, target_at_period):
    """Build one 'Targets by Time Period' row using real cumulative achievement
    against a straight-line ramp of the annual target (same 25/50/75/100
    methodology already used by apps.targets.services.time_period)."""
    if target_at_period:
        pct = round(cumulative / target_at_period * 100)
    else:
        pct = 100 if cumulative else None

    if pct is None:
        status, status_class = (
            "No Target",
            "text-slate-400 bg-slate-50 border-slate-100",
        )
    elif pct >= 100:
        status, status_class = (
            "Ahead",
            "text-emerald-600 bg-emerald-50 border-emerald-100",
        )
    elif pct >= 90:
        status, status_class = (
            "On Track",
            "text-emerald-600 bg-emerald-50 border-emerald-100",
        )
    elif pct >= 50:
        status, status_class = "Behind", "text-amber-600 bg-amber-50 border-amber-100"
    else:
        status, status_class = "Critical", "text-rose-600 bg-rose-50 border-rose-100"

    return {
        "label": label,
        "target": target_at_period,
        "achieved": cumulative,
        "pct": pct,
        "status": status,
        "status_class": status_class,
    }


def _kpi_status(kpi):
    """Bucket a KPI into on_track / at_risk / off_track / no_target using real
    values only — no fabricated numbers."""
    if kpi.get("lower_is_better"):
        if kpi["value"] == 0:
            return "on_track"
        return "at_risk" if kpi["value"] <= 3 else "off_track"
    if not kpi.get("target"):
        return "no_target"
    pct = kpi["value"] / kpi["target"] * 100
    if pct >= 90:
        return "on_track"
    if pct >= 50:
        return "at_risk"
    return "off_track"


@require_page_permission("my_target")
def my_targets_view(request):
    """My Targets — the personal performance operating page.

    Monthly-first: the page always defaults to the real current month of the
    configured financial year; Q1–Q4 and FY Cumulative are derived rollups of
    validated workflow achievements. Strictly scoped to request.user."""
    from apps.targets.my_targets import MyTargetQueryService

    fy = (request.GET.get("fy") or "").strip() or None
    raw_month = (request.GET.get("month") or "").strip()
    month = (
        int(raw_month) if raw_month.isdigit() and 1 <= int(raw_month) <= 12 else None
    )

    data = MyTargetQueryService.get_page(request.user, fy=fy, month_of_fy=month)
    from apps.core.fy import fy_options

    context = {
        **data,
        "fy_options": fy_options(),
        "core_tracker_data": _build_core_tracker(request.user),
    }
    if request.headers.get("HX-Request") == "true":
        return render(request, "partials/targets/my_body.html", context)
    return render(request, "pages/targets/index.html", context)


@require_page_permission("my_target")
def my_targets_area_drawer_view(request):
    """Target-area detail drawer — every credit and every not-counted reason."""
    from apps.targets.my_targets import MyTargetQueryService
    from apps.core.fy import get_operational_fy

    area = (request.GET.get("area") or "").strip()
    fy = (request.GET.get("fy") or "").strip() or get_operational_fy()
    raw_month = (request.GET.get("month") or "").strip()
    month = int(raw_month) if raw_month.isdigit() else 1
    payload = MyTargetQueryService.area_drawer(request.user, area, fy, month)
    return render(
        request,
        "partials/targets/area_drawer.html",
        {**payload, "drawer_size": "lg", "fy": fy, "month": month},
    )


@require_page_permission("my_target")
def my_targets_export_view(request):
    """Role-scoped CSV export of the signed-in user's target results."""
    import csv

    from django.http import HttpResponse
    from django.utils import timezone as _tz

    from apps.core.fy import get_operational_fy
    from apps.targets.my_targets import MyTargetQueryService, TargetAchievementService

    fy = (request.GET.get("fy") or "").strip() or get_operational_fy()
    TargetAchievementService.rebuild(request.user, fy)
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="my_targets_{fy}.csv"'
    w = csv.writer(resp)
    w.writerow(
        [
            f"My Targets — {request.user.name}",
            f"FY {fy}",
            f"Generated {_tz.now():%Y-%m-%d %H:%M} by {request.user.email}",
        ]
    )
    for row in MyTargetQueryService.export_rows(request.user, fy):
        w.writerow(row)
    return resp


@require_page_permission("my_target")
def mscs_submit_view(request):
    """Submit a Most Significant Change Story (status → Submitted). Only an
    approved story counts toward the MSCS target."""
    if request.method != "POST":
        return redirect("/my-targets")
    from apps.schools.models import School
    from apps.targets.models import MostSignificantChangeStory

    title = (request.POST.get("title") or "").strip()
    narrative = (request.POST.get("narrative") or "").strip()
    story_date = (request.POST.get("story_date") or "").strip()
    school_id = (request.POST.get("school_id") or "").strip()
    if not (title and narrative and story_date):
        messages.error(request, "Title, story date and narrative are required.")
        return redirect("/my-targets")
    school = (
        School.objects.filter(
            Q(id=school_id) | Q(school_id=school_id), deleted_at__isnull=True
        ).first()
        if school_id
        else None
    )
    MostSignificantChangeStory.objects.create(
        user_id=request.user.id,
        school=school,
        title=title,
        narrative=narrative,
        story_date=story_date,
        status="submitted",
    )
    messages.success(request, "MSCS submitted for review — it counts once approved.")
    return redirect("/my-targets")


def _build_core_tracker(user):
    """Core School Tracker — the 4-visit + 4-training package per core school
    in the user's portfolio (kept from the previous My Targets iteration).

    visits_completed/trainings_completed are now maintained in lock-step with
    each slot's real, mirrored Activity status (see Activity.save() in
    apps.activities.models + core_schools.services.resync_plan_completion),
    so they're read directly rather than re-derived from slot status here."""
    from apps.accounts.models import StaffSchoolAssignment
    from apps.core_schools.models import CorePlan
    from apps.schools.models import School

    sp_id = getattr(user, "staff_profile_id", None)
    if not sp_id:
        return {"rows": [], "total": 0}
    school_cuids = list(
        StaffSchoolAssignment.objects.filter(staff_id=sp_id).values_list(
            "school_id", flat=True
        )
    )
    op_ids = dict(
        School.objects.filter(id__in=school_cuids).values_list("id", "school_id")
    )
    plans = list(
        CorePlan.objects.filter(school_id__in=list(op_ids.values())).order_by(
            "school_id"
        )
    )
    names = dict(
        School.objects.filter(school_id__in=[p.school_id for p in plans]).values_list(
            "school_id", "name"
        )
    )
    rows = []
    for plan in plans:
        v_done = min(plan.visits_completed or 0, 4)
        t_done = min(plan.trainings_completed or 0, 4)
        total_done = v_done + t_done
        if total_done >= 8:
            status, tone = "Complete", "success"
        elif plan.baseline_average is not None and total_done > 0:
            status, tone = "On Track", "info"
        elif plan.baseline_average is not None:
            status, tone = "Not Started", "neutral"
        else:
            status, tone = "Needs Baseline", "warning"
        rows.append(
            {
                "school": names.get(plan.school_id, plan.school_id),
                "baseline": plan.baseline_average,
                "visits_done": v_done,
                "trainings_done": t_done,
                "visit_dots": [i < v_done for i in range(4)],
                "training_dots": [i < t_done for i in range(4)],
                "pct": round(total_done / 8 * 100),
                "status": status,
                "tone": tone,
            }
        )
    rows.sort(key=lambda r: (-r["pct"], r["school"]))
    return {"rows": rows[:12], "total": len(rows)}


@require_page_permission("my_team")
def my_team_view(request):
    """Program Lead team overview — all CCEOs under the PL with their activity stats."""
    from apps.accounts.models import StaffSupervisorAssignment

    user = request.user
    today = date.today()

    # Get the CCEOs supervised by this PL (StaffSupervisorAssignment is the
    # "team lens" source of truth — see team_targets_view for the same pattern).
    sp = getattr(user, "staff_profile", None)
    supervisee_ids = (
        list(
            StaffSupervisorAssignment.objects.filter(supervisor=sp).values_list(
                "supervisee_id", flat=True
            )
        )
        if sp
        else []
    )
    cceos = User.objects.filter(
        roles__contains=["CCEO"],
        status="active",
        deleted_at__isnull=True,
        staff_profile__id__in=supervisee_ids,
    ).order_by("name")

    team_data = []
    for cceo in cceos:
        # Both id spaces — the directory list already counts this way
        # (`_user_ids`), so matching on the User id alone here made the row and
        # its own drill-down disagree, and read as underperformance.
        cceo_ids = owner_ids(cceo)
        completed = Activity.objects.filter(
            responsible_staff_id__in=cceo_ids,
            status__in=COMPLETED_WORK_STATUSES,
            deleted_at__isnull=True,
        ).count()
        overdue = Activity.objects.filter(
            responsible_staff_id__in=cceo_ids,
            planned_date__lt=today,
            status__in=["scheduled", "in_progress", "completion_started"],
            deleted_at__isnull=True,
        ).count()
        evidence_gap = Activity.objects.filter(
            responsible_staff_id__in=cceo_ids,
            status__in=COMPLETED_WORK_STATUSES,
            evidence__isnull=True,
            deleted_at__isnull=True,
        ).count()
        team_data.append(
            {
                "id": cceo.id,
                "name": cceo.name,
                "email": cceo.email,
                "initials": cceo.name[:2].upper() if cceo.name else "??",
                "completed": completed,
                "overdue": overdue,
                "evidence_gap": evidence_gap,
                "risk": "high" if overdue > 3 else "medium" if overdue > 0 else "low",
            }
        )

    total_cceos = len(team_data)
    with_overdue = sum(1 for m in team_data if m["overdue"] > 0)
    all_caught_up = total_cceos - with_overdue

    kpi_strip_items = [
        {
            "label": "Total CCEOs",
            "value": str(total_cceos),
            "raw_value": total_cceos,
            "helper": "On your team",
            "icon": "users",
            "variant": "primary",
        },
        {
            "label": "With Overdue",
            "value": str(with_overdue),
            "raw_value": with_overdue,
            "helper": "CCEOs",
            "icon": "warning",
            "variant": "danger" if with_overdue > 0 else "success",
        },
        {
            "label": "All Caught Up",
            "value": str(all_caught_up),
            "raw_value": all_caught_up,
            "helper": "CCEOs",
            "icon": "check",
            "variant": "success",
        },
    ]

    context = {
        "team": team_data,
        "total": total_cceos,
        "kpi_strip_items": kpi_strip_items,
    }
    return render(request, "pages/my_team/index.html", context)


# ─── NOTIFICATIONS ────────────────────────────────────────────────────────────


@require_page_permission("dashboard")
def notifications_page_view(request):
    """General notifications center dashboard."""
    user = request.user

    # Handle bulk/single actions
    action = request.POST.get("action") or request.GET.get("action")
    if request.method == "POST":
        if action == "mark_all_read":
            Notification.objects.filter(recipient_id=user.id, status="unread").update(
                status="read", read_at=timezone.now()
            )
        elif action == "archive_all_read":
            Notification.objects.filter(recipient_id=user.id, status="read").update(
                status="archived"
            )
        elif action == "archive_single":
            notif_id = request.POST.get("notification_id")
            Notification.objects.filter(id=notif_id, recipient_id=user.id).update(
                status="archived"
            )

    # Filters
    selected_priority = request.GET.get("priority", "")
    selected_category = request.GET.get("category", "")
    selected_status = request.GET.get(
        "status", "all"
    )  # Default to show all except archived by default
    action_required_only = request.GET.get("action_required") == "true"
    q = request.GET.get("q", "")

    qs = Notification.objects.filter(recipient_id=user.id)

    # KPIs describe the same population the list does. `total` counted
    # archived rows while the default list excluded them, so the page could
    # read "412 total" above a hundred visible items. Resolved rows are
    # history, not work.
    live_qs = qs.exclude(Q(status="archived") | Q(resolved_at__isnull=False))
    kpis = {
        "total": live_qs.count(),
        "unread": live_qs.filter(status="unread").count(),
        "action_required": live_qs.filter(
            action_required=True, status="unread"
        ).count(),
        "critical": live_qs.filter(priority="urgent", status="unread").count(),
    }

    # Apply status filter
    if selected_status == "all":
        qs = live_qs
    else:
        qs = qs.filter(status=selected_status)

    if selected_priority:
        qs = qs.filter(priority=selected_priority)
    if selected_category:
        qs = qs.filter(category=selected_category)
    if action_required_only:
        qs = qs.filter(action_required=True)
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(body__icontains=q))

    notifications = qs.order_by("-created_at")[:100]

    # Get distinct categories
    categories = list(
        Notification.objects.filter(recipient_id=user.id)
        .values_list("category", flat=True)
        .distinct()
    )
    categories = [c for c in categories if c]

    context = {
        "notifications": notifications,
        "kpis": kpis,
        "selected_priority": selected_priority,
        "selected_category": selected_category,
        "selected_status": selected_status,
        "action_required_only": action_required_only,
        "q": q,
        "categories": categories,
    }
    return render(request, "pages/notifications/index.html", context)


def _get_sorted_drawer_notifications(user) -> list[Notification]:
    """Helper to get notifications for drawer sorted by Critical/Action-Required first, then latest."""
    notifs_qs = Notification.objects.filter(recipient_id=user.id).exclude(
        Q(status="archived") | Q(resolved_at__isnull=False)
    )
    notifs = list(notifs_qs)

    def sort_key(n):
        # Unread outranks priority. Sorting on priority first meant a READ
        # urgent row beat an UNREAD one — and since a job promotes anything
        # stale to urgent, the top of the drawer filled with old read items
        # while genuinely new work fell off the end of the twenty.
        unread = 0 if n.status == "unread" else 1
        ar_val = 0 if n.action_required and n.status == "unread" else 1
        p_val = {"urgent": 0, "high": 1, "normal": 2, "low": 3}.get(n.priority, 2)
        return (unread, ar_val, p_val, -n.created_at.timestamp())

    notifs.sort(key=sort_key)
    return notifs[:20]


@require_page_permission("dashboard")
def notification_drawer_view(request):
    """Notification drawer view — loaded via HTMX when clicking notification bell."""
    user = request.user
    notifs = _get_sorted_drawer_notifications(user)
    unread_count = (
        Notification.objects.filter(recipient_id=user.id, status="unread")
        .exclude(resolved_at__isnull=False)
        .count()
    )

    context = {
        "notifications": notifs,
        "unread_count": unread_count,
        "drawer_type": "center",
        "drawer_size": "sm",
    }
    return render(request, "partials/notifications/notification_drawer.html", context)


@require_page_permission("dashboard")
def mark_all_notifications_read(request):
    """Mark all unread notifications for the user as read."""
    if request.method == "POST":
        Notification.objects.filter(
            recipient_id=request.user.id, status="unread"
        ).update(
            status="read",
            read_at=timezone.now(),
        )
    if request.headers.get("HX-Request") == "true":
        user = request.user
        notifs = _get_sorted_drawer_notifications(user)
        return render(
            request,
            "partials/notifications/notification_drawer_list.html",
            {
                "notifications": notifs,
                "unread_count": 0,
            },
        )
    return redirect("/")


@require_page_permission("dashboard")
def mark_notification_read(request, notif_id):
    """Mark a single notification as read."""
    Notification.objects.filter(id=notif_id, recipient_id=request.user.id).update(
        status="read",
        read_at=timezone.now(),
    )
    if request.method == "POST" and request.headers.get("HX-Request") == "true":
        user = request.user
        notifs = _get_sorted_drawer_notifications(user)
        unread_count = Notification.objects.filter(
            recipient_id=user.id, status="unread"
        ).count()
        return render(
            request,
            "partials/notifications/notification_drawer_list.html",
            {
                "notifications": notifs,
                "unread_count": unread_count,
            },
        )

    # Same-host only. This took the destination straight from the query string,
    # so `/notifications/<id>/read?redirect=https://evil.example.com` was a live
    # open redirect on an authenticated route — a phishing link that leaves from
    # the real Edify domain.
    redirect_to = request.GET.get("redirect") or request.POST.get("redirect") or "/"
    if not url_has_allowed_host_and_scheme(
        redirect_to,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        redirect_to = "/notifications"
    return redirect(redirect_to)


@require_page_permission("dashboard")
def notification_badge_view(request):
    """Return only the notification badge count HTML."""
    unread_count = Notification.objects.filter(
        recipient_id=request.user.id, status="unread"
    ).count()
    return render(
        request,
        "partials/notifications/notification_badge.html",
        {"unread_notifications_count": unread_count},
    )


# ─── USER PROFILE ─────────────────────────────────────────────────────────────


@require_page_permission("dashboard")
def profile_view(request):
    """User profile — role info, stats, recent activity."""
    user = request.user
    fy = get_operational_fy()

    profile = getattr(user, "staff_profile", None)

    # Activity stats
    total_activities = Activity.objects.filter(
        responsible_staff_id=user.id,
        deleted_at__isnull=True,
    ).count()
    completed = Activity.objects.filter(
        responsible_staff_id=user.id,
        status__in=COMPLETED_WORK_STATUSES,
        deleted_at__isnull=True,
    ).count()

    recent = (
        Activity.objects.filter(
            responsible_staff_id=user.id,
            deleted_at__isnull=True,
        )
        .select_related("school")
        .order_by("-updated_at")[:5]
    )

    context = {
        "member": user,
        "profile": profile,
        "fy": fy,
        "total_activities": total_activities,
        "completed": completed,
        "completion_rate": round(completed / total_activities * 100)
        if total_activities
        else 0,
        "recent": recent,
        "initials": user.name[:2].upper() if user.name else "??",
    }
    return render(request, "pages/profile/index.html", context)


@require_page_permission("team_targets")
def team_targets_view(request):
    """Team Targets — the Program Lead's supervision and recovery cockpit.

    Aggregates the validated My Targets performance of supervised CCEOs.
    Strictly PL-scoped (CD/Admin get a country oversight lens). The PL's own
    performance lives on My Targets, never here."""
    from apps.core.fy import fy_options
    from apps.targets.team_targets import PLTeamTargetsService

    fy = (request.GET.get("fy") or "").strip() or None
    raw_month = (request.GET.get("month") or "").strip()
    month = (
        int(raw_month) if raw_month.isdigit() and 1 <= int(raw_month) <= 12 else None
    )

    category = (request.GET.get("category") or "overall").strip()
    district = (request.GET.get("district") or "").strip()
    team_member = (request.GET.get("team_member") or "").strip()

    data = PLTeamTargetsService.get_page(
        request.user,
        fy=fy,
        month_of_fy=month,
        category=category,
        district=district,
        team_member=team_member,
    )
    context = {**data, "fy_options": fy_options()}
    if request.headers.get("HX-Request") == "true":
        return render(request, "partials/targets/team/workspace.html", context)
    return render(request, "pages/targets/team.html", context)


def _team_member_or_none(request, staff_user_id):
    """Backend scope guard: the referenced staff member must be in the
    logged-in supervisor's team. Never trust the URL."""
    from apps.targets.team_targets import supervised_users

    return next(
        (u for u in supervised_users(request.user) if u.id == staff_user_id), None
    )


@require_page_permission("team_targets")
def team_targets_staff_drawer_view(request):
    from django.http import HttpResponseForbidden
    from apps.targets.fy_calendar import FinancialYearCalendarService as Cal
    from apps.targets.my_targets import MyTargetQueryService, active_target_areas
    from apps.targets.team_targets import PLTeamTargetsService

    member_user = _team_member_or_none(
        request, (request.GET.get("staff") or "").strip()
    )
    if member_user is None:
        return HttpResponseForbidden("Not in your supervised team.")
    now = Cal.current()
    fy = (request.GET.get("fy") or "").strip() or now["fy"]
    raw_month = (request.GET.get("month") or "").strip()
    month = (
        int(raw_month)
        if raw_month.isdigit() and 1 <= int(raw_month) <= 12
        else (now["month_of_fy"] if fy == now["fy"] else 1)
    )
    areas = active_target_areas()
    m_start, m_end = Cal.month_range(fy, month)
    member = PLTeamTargetsService._member(
        member_user, areas, fy, month, now["today"], m_start, m_end, fy == now["fy"]
    )
    # Backfill the portfolio fields get_page normally adds for its members.
    from apps.accounts.models import StaffSchoolAssignment
    from apps.activities.models import Activity
    from apps.schools.models import School
    from apps.targets.my_targets import COMPLETED_STATUSES, _user_ids
    from apps.targets.team_targets import SF_REQUIRED_TYPES

    sp_id = getattr(member_user, "staff_profile_id", None)
    school_pks = (
        StaffSchoolAssignment.objects.filter(staff_id=sp_id).values_list(
            "school_id", flat=True
        )
        if sp_id
        else []
    )
    districts = sorted(
        {
            d
            for d in School.objects.filter(id__in=list(school_pks))
            .exclude(district__isnull=True)
            .values_list("district__name", flat=True)
        }
    )
    member["district_label"] = ", ".join(districts[:2]) or "—"
    done = Activity.objects.filter(
        responsible_staff_id__in=_user_ids(member_user),
        fy=fy,
        activity_type__in=SF_REQUIRED_TYPES,
        status__in=COMPLETED_STATUSES,
        deleted_at__isnull=True,
    ).exclude(delivery_type="partner")
    total = done.count()
    with_sf = (
        done.exclude(salesforce_activity_id__isnull=True)
        .exclude(salesforce_activity_id="")
        .count()
    )
    member["sf_compliance"] = round(with_sf / total * 100) if total else 100
    member["core_pct"] = None
    pipelines = {
        a.key: MyTargetQueryService._pipeline(member_user, a.key, fy, month)
        for a in areas
    }
    for pa in member["per_area"]:
        p = pipelines[pa["key"]]
        pa["scheduled"] = len(p["scheduled"])
        pa["pending_sf"] = len(p["pending_sf"])
        pa["ia_pending"] = len(p["ia_pending"])
        pa["returned"] = len(p["returned"])
        pa["provisional"] = len(p["provisional"])
    return render(
        request,
        "partials/targets/team/staff_drawer.html",
        {
            "m": member,
            "month_label": Cal.month_label(fy, month),
            "fy": fy,
            "month_of_fy": month,
            "areas": [{"key": a.key, "label": a.label} for a in areas],
        },
    )


@require_page_permission("team_targets")
def team_targets_matrix_view(request):
    from django.http import HttpResponseBadRequest
    from apps.targets.team_targets import PLTeamTargetsService

    fy = (request.GET.get("fy") or "").strip() or None
    area = (request.GET.get("area") or "").strip() or None
    month_raw = (request.GET.get("month") or "").strip()
    try:
        month = int(month_raw) if month_raw else None
    except ValueError:
        return HttpResponseBadRequest("Invalid month.")
    if month is not None and month not in range(1, 13):
        return HttpResponseBadRequest("Invalid month.")
    data = PLTeamTargetsService.matrix(
        request.user,
        fy=fy,
        month_of_fy=month,
        area=area,
    )
    if data["invalid_area"]:
        return HttpResponseBadRequest("Invalid target area.")
    # The reporting matrix is intentionally the only Team Targets drawer that
    # opens as a wide workspace. Its nineteen comparison columns fit without
    # forcing desktop users to discover off-screen performance data.
    data["drawer_size"] = "workspace"
    return render(request, "partials/targets/team/matrix_drawer.html", data)


@require_page_permission("team_targets")
def team_targets_day_view(request):
    from django.http import HttpResponseBadRequest
    from apps.targets.fy_calendar import FinancialYearCalendarService as Cal
    from apps.targets.team_targets import PLTeamTargetsService

    try:
        day = date.fromisoformat((request.GET.get("date") or "").strip())
    except ValueError:
        return HttpResponseBadRequest("Invalid date.")
    fy = (request.GET.get("fy") or "").strip() or Cal.current()["fy"]
    data = PLTeamTargetsService.day_detail(request.user, day, fy)
    return render(request, "partials/targets/team/day_drawer.html", data)


@require_page_permission("team_targets")
def team_targets_recovery_view(request):
    """Recovery approval queue: submitted catch-up plans + behind staff."""
    from apps.targets.fy_calendar import FinancialYearCalendarService as Cal
    from apps.targets.models import CatchUpPlan
    from apps.targets.team_targets import PLTeamTargetsService

    data = PLTeamTargetsService.get_page(request.user)
    plans = list(
        CatchUpPlan.objects.filter(pl_user_id=request.user.id)
        .exclude(status__in=["closed"])
        .select_related("area")
        .order_by("-created_at")[:30]
    )
    names = {m["user_id"]: m["name"] for m in data["members"]}
    for p in plans:
        p.staff_name = names.get(p.staff_user_id, "—")
        p.month_label = Cal.month_label(p.fy, p.month_of_fy)
    return render(
        request,
        "partials/targets/team/recovery_drawer.html",
        {
            "plans": plans,
            "recovery": data["recovery"],
            "fy": data["fy"],
            "month_of_fy": data["month_of_fy"],
            "areas": data["areas"],
        },
    )


@require_page_permission("team_targets")
def team_targets_sfid_backlog_view(request):
    """Completed activities missing Activity SF IDs across the team."""
    from apps.activities.models import Activity
    from apps.targets.my_targets import COMPLETED_STATUSES, _user_ids
    from apps.targets.fy_calendar import FinancialYearCalendarService as Cal
    from apps.targets.team_targets import SF_REQUIRED_TYPES, supervised_users

    team = supervised_users(request.user)
    ids, names = [], {}
    for u in team:
        for i in _user_ids(u):
            ids.append(i)
            names[i] = u.name
    fy = (request.GET.get("fy") or "").strip() or Cal.current()["fy"]
    acts = (
        Activity.objects.filter(
            responsible_staff_id__in=ids,
            fy=fy,
            deleted_at__isnull=True,
            activity_type__in=SF_REQUIRED_TYPES,
            status__in=COMPLETED_STATUSES,
        )
        .exclude(delivery_type="partner")
        .filter(Q(salesforce_activity_id__isnull=True) | Q(salesforce_activity_id=""))
        .select_related("school", "cluster")
        .order_by("planned_date")[:100]
        if ids
        else []
    )
    rows = [
        {
            "staff": names.get(a.responsible_staff_id, "—"),
            "what": a.get_activity_type_display(),
            "where": a.school.name
            if a.school_id
            else (a.cluster.name if a.cluster_id else "—"),
            "date": a.planned_date,
        }
        for a in acts
    ]
    return render(
        request, "partials/targets/team/sfid_drawer.html", {"rows": rows, "fy": fy}
    )


@require_page_permission("team_targets")
def team_targets_catchup_create_view(request):
    from django.http import HttpResponseBadRequest, HttpResponseForbidden
    from apps.targets.fy_calendar import FinancialYearCalendarService as Cal
    from apps.targets.team_targets import PLCatchUpPlanService

    if request.method != "POST":
        return HttpResponseBadRequest("POST required.")
    staff_user_id = (request.POST.get("staff_user_id") or "").strip()
    if _team_member_or_none(request, staff_user_id) is None:
        return HttpResponseForbidden("Not in your supervised team.")
    now = Cal.current()
    fy = (request.POST.get("fy") or "").strip() or now["fy"]
    raw_month = (request.POST.get("month") or "").strip()
    month = (
        int(raw_month)
        if raw_month.isdigit() and 1 <= int(raw_month) <= 12
        else now["month_of_fy"]
    )
    school_ids = [
        x.strip()
        for x in (request.POST.get("school_ids") or "").split(",")
        if x.strip()
    ]
    dates = [
        x.strip() for x in (request.POST.get("dates") or "").split(",") if x.strip()
    ]
    try:
        PLCatchUpPlanService.submit(
            request.user,
            staff_user_id=staff_user_id,
            area_key=(request.POST.get("area") or "school_visits").strip(),
            fy=fy,
            month_of_fy=month,
            count=request.POST.get("count") or len(school_ids) or 0,
            school_ids=school_ids,
            planned_dates=dates,
            note=request.POST.get("note") or "",
            partner_id=(request.POST.get("partner_id") or "").strip() or None,
        )
    except Exception as exc:  # noqa: BLE001
        return HttpResponseBadRequest(str(exc))
    messages.success(request, "Catch-up plan submitted for approval.")
    return redirect("/team-targets")


@require_page_permission("team_targets")
def team_targets_catchup_action_view(request, plan_id):
    from django.http import HttpResponseBadRequest, HttpResponseForbidden
    from apps.targets.models import CatchUpPlan
    from apps.targets.team_targets import PLCatchUpPlanService

    if request.method != "POST":
        return HttpResponseBadRequest("POST required.")
    plan = CatchUpPlan.objects.filter(id=plan_id).select_related("area").first()
    if plan is None or plan.pl_user_id != request.user.id:
        return HttpResponseForbidden("Not your catch-up plan.")
    action = (request.POST.get("action") or "").strip()
    if action == "approve":
        result = PLCatchUpPlanService.approve(plan, request.user)
        messages.success(
            request,
            f"Catch-up plan approved — {len(result['created'])} activit"
            f"{'y' if len(result['created']) == 1 else 'ies'} entered Planning.",
        )
    elif action == "return":
        PLCatchUpPlanService.return_plan(
            plan, request.user, request.POST.get("reason") or ""
        )
        messages.info(request, "Catch-up plan returned.")
    else:
        return HttpResponseBadRequest("Unknown action.")
    return redirect("/team-targets")


@require_page_permission("team_targets")
def team_targets_export_view(request):
    from django.http import HttpResponse
    from apps.targets.fy_calendar import FinancialYearCalendarService as Cal
    from apps.targets.team_targets import PLTeamTargetsService
    import csv

    fy = (request.GET.get("fy") or "").strip() or Cal.current()["fy"]
    raw_month = (request.GET.get("month") or "").strip()
    month = (
        int(raw_month) if raw_month.isdigit() and 1 <= int(raw_month) <= 12 else None
    )
    rows = PLTeamTargetsService.export_rows(
        request.user,
        fy=fy,
        month_of_fy=month,
        category=(request.GET.get("category") or "overall").strip(),
        district=(request.GET.get("district") or "").strip(),
        team_member=(request.GET.get("team_member") or "").strip(),
    )
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="team-targets-fy{fy}.csv"'
    writer = csv.writer(resp)
    writer.writerow(
        [
            f"Team Targets — FY {fy}",
            f"Generated {timezone.now():%d %b %Y %H:%M}",
            f"Supervisor: {request.user.name}",
        ]
    )
    for row in rows:
        writer.writerow(row)
    return resp
