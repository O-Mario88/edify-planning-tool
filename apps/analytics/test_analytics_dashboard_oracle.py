"""Oracle for the /analytics rebuild (AnalyticsDashboardService.get_analytics_data).

The 2026-09-24 performance change counts activities de-duplicated on the
primary key (`.values("id")`) instead of on every activity column, folds each
section's separate COUNT queries into one aggregate, and passes the school
scope to the per-school SSA averages as a subquery instead of a materialised
id list. `_frozen_get_analytics_data` below is a copy of the method
before that change (commit 4425605); every test asserts the live method
returns exactly what it returns, for country, country-with-staff-country,
team, personal, summary and empty scopes, with quarter, month, geography,
school-type, activity-type, partner, staff and search filters, over two
fiscal years of work and assessments.

One intended departure from commit 4425605 (2026-09-24, the grouped-count
correction): the frozen copy's four grouped activity counts (months,
districts, regions, clusters) now clear the ordering before grouping, as the
live method does. Before, a `.distinct()` scope (country, Programme Lead team,
staff filter) carried Activity's `-created_at` ordering into the SELECT and
the GROUP BY, so each count was split by creation time and only one slice
survived. The fixture used to create every activity under one frozen
`created_at`, which hid that; it now gives each activity its own. Nothing else
in the frozen copy changed, so the oracle still proves the performance change
altered no other figure. `test_analytics_grouped_counts.py` pins the true
counts directly.
"""

from __future__ import annotations

import datetime
from datetime import date

from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, Q, Sum
from django.test import TestCase
from django.utils import timezone
from freezegun import freeze_time

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
)
from apps.activities.models import Activity
from apps.analytics.analytics_dashboard_service import (
    ACHIEVED_STATUSES,
    CLUSTER_MEETING_TYPE,
    TRAINING_TYPES,
    VISIT_TYPES,
    AnalyticsDashboardService,
)
from apps.analytics.country_map_context import country_map_context
from apps.clusters.models import Cluster
from apps.core.enums import SsaIntervention
from apps.core.fy import fy_options, get_operational_fy
from apps.core.metrics import render_precomputed_metric_item
from apps.core.scoping import resolve_user_scope
from apps.geography.models import District, Region
from apps.partners.models import Partner
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore

# ── Frozen reference (pre-change implementation, commit 4425605) ────────────


def _frozen_get_analytics_data(principal, filters: dict) -> dict:
    # 1. Parse active filters
    fy = filters.get("fy") or get_operational_fy()
    quarter = None if filters.get("month") else (filters.get("quarter") or None)
    region_id = filters.get("region")
    sub_region_id = filters.get("sub_region")
    district_id = filters.get("district")
    sub_county_id = filters.get("sub_county")
    cluster_id = filters.get("cluster")
    staff_id = filters.get("staff")
    partner_id = filters.get("partner")
    school_type = filters.get("school_type")
    activity_type = filters.get("activity_type")
    search_q = filters.get("q")

    # Resolve user data visibility scope
    scope = resolve_user_scope(principal)

    # 2. Base Querysets
    schools_qs = School.objects.filter(deleted_at__isnull=True)
    activities_qs = Activity.objects.filter(deleted_at__isnull=True, fy=fy)
    ssa_qs = SsaRecord.objects.filter(
        deleted_at__isnull=True, fy=fy, verification_status="confirmed"
    )

    # Apply role-based visibility scoping.
    # Summary-only roles (RVP) are an aggregate audience, not a portfolio
    # one: they get regional/deployment-wide totals rather than being
    # filtered down to their own (empty) school and staff assignments.
    # Filtering them like a field role emptied this page — the RVP's actual
    # "Analytics" sidebar link — for the role it exists to serve.
    if scope.can_view_summary_only:
        if scope.rvp_region_scoped:
            schools_qs = schools_qs.filter(region_id__in=scope.region_ids)
            ssa_qs = ssa_qs.filter(school__region_id__in=scope.region_ids)
            activities_qs = activities_qs.filter(school__region_id__in=scope.region_ids)
    elif scope.region_scope:
        # A Regional Programme Lead's analytics cover the countries they
        # oversee (apps.core.scoping._regional_reach). Without this branch
        # the role fell into the field path below, owned no school and no
        # activity, and every figure on the page read zero. Cluster work
        # with no school is placed by its cluster's district, as Team
        # Oversight places it.
        region_ids = scope.region_ids or []
        schools_qs = schools_qs.filter(region_id__in=region_ids)
        ssa_qs = ssa_qs.filter(school__region_id__in=region_ids)
        activities_qs = activities_qs.filter(
            Q(school__region_id__in=region_ids)
            | Q(cluster__district__region_id__in=region_ids)
        )
    elif not scope.country_scope:
        if scope.school_ids:
            schools_qs = schools_qs.filter(id__in=scope.school_ids)
            ssa_qs = ssa_qs.filter(school_id__in=scope.school_ids)
        else:
            schools_qs = schools_qs.none()
            ssa_qs = ssa_qs.none()

        if principal.active_role == "Program Lead" and getattr(
            principal, "staff_profile", None
        ):
            from apps.hr.contribution_scope import scope_activities

            activities_qs = scope_activities(
                activities_qs, staff=principal.staff_profile, include_team=True
            )
        elif scope.staff_ids:
            activities_qs = activities_qs.filter(
                Q(responsible_staff_id__in=scope.staff_ids)
                | Q(
                    delivery_type="partner",
                    monitored_by_staff_id__in=scope.staff_ids,
                )
            )
        elif scope.partner_ids:
            activities_qs = activities_qs.filter(
                assigned_partner_id__in=scope.partner_ids
            )
        else:
            activities_qs = activities_qs.none()

    if scope.country:
        from apps.core.scoping import school_country_q
        from apps.hr.contribution_scope import scope_activities

        # The shared boundary, not `region__country` written out again: it
        # also reaches the schools an upload could not place, and a page
        # that counts schools must count the same ones the directory lists.
        schools_qs = schools_qs.filter(school_country_q(scope))
        ssa_qs = ssa_qs.filter(school_country_q(scope, "school__"))
        activities_qs = scope_activities(activities_qs, country=scope.country)

    # 3. Apply page filters to Querysets
    # Region
    if region_id:
        schools_qs = schools_qs.filter(region_id=region_id)
        activities_qs = activities_qs.filter(school__region_id=region_id)
        ssa_qs = ssa_qs.filter(school__region_id=region_id)
    # Sub-Region
    #
    # Joined through the district, never through School.sub_region_id. That
    # column exists and is populated on no school at all, so filtering by it
    # would return an empty page that reads as "no data for this area"
    # rather than as a broken filter. This is the same route
    # apps/analytics/subregion_analytics.py and the SSA heatmap take.
    if sub_region_id:
        schools_qs = schools_qs.filter(district__sub_region_id=sub_region_id)
        activities_qs = activities_qs.filter(
            school__district__sub_region_id=sub_region_id
        )
        ssa_qs = ssa_qs.filter(school__district__sub_region_id=sub_region_id)
    # District
    if district_id:
        schools_qs = schools_qs.filter(district_id=district_id)
        activities_qs = activities_qs.filter(school__district_id=district_id)
        ssa_qs = ssa_qs.filter(school__district_id=district_id)
    # Sub-County
    #
    # School.sub_county is the assignment the map's subcounty_insight also
    # groups by, so a filtered page and the map agree about which schools
    # sit in a sub-county. Note the map draws sub-county BOUNDARIES for the
    # whole country from static GeoJSON — that is geometry, not assignment,
    # and it makes coverage look far higher than it is.
    if sub_county_id:
        schools_qs = schools_qs.filter(sub_county_id=sub_county_id)
        activities_qs = activities_qs.filter(school__sub_county_id=sub_county_id)
        ssa_qs = ssa_qs.filter(school__sub_county_id=sub_county_id)
    # Cluster
    if cluster_id:
        schools_qs = schools_qs.filter(cluster_id=cluster_id)
        activities_qs = activities_qs.filter(school__cluster_id=cluster_id)
        ssa_qs = ssa_qs.filter(school__cluster_id=cluster_id)
    # Staff filters use the same personal/team monitoring boundary as progress.
    chosen_staff = staff_id or filters.get("cceo") or filters.get("pl")
    if chosen_staff:
        from apps.accounts.models import StaffSchoolAssignment
        from apps.hr.contribution_scope import owner_ids, scope_activities

        chosen = StaffProfile.objects.filter(
            Q(id=chosen_staff) | Q(user_id=chosen_staff)
        ).first()
        if chosen:
            include_team = bool(
                filters.get("pl") and not (staff_id or filters.get("cceo"))
            )
            activities_qs = scope_activities(
                activities_qs, staff=chosen, include_team=include_team
            )
            ids = owner_ids(chosen, include_team)
            assigned = StaffSchoolAssignment.objects.filter(staff_id__in=ids).values(
                "school_id"
            )
            schools_qs = schools_qs.filter(
                Q(id__in=assigned) | Q(account_owner_id__in=ids)
            )
            ssa_qs = ssa_qs.filter(school_id__in=schools_qs.values("id"))
        else:
            activities_qs, schools_qs, ssa_qs = (
                activities_qs.none(),
                schools_qs.none(),
                ssa_qs.none(),
            )
    # Partner Owner
    if partner_id:
        activities_qs = activities_qs.filter(assigned_partner_id=partner_id)
        schools_qs = schools_qs.filter(partner_assignments__partner_id=partner_id)
        ssa_qs = ssa_qs.filter(school__partner_assignments__partner_id=partner_id)
    # School Type
    if school_type and school_type != "All":
        schools_qs = schools_qs.filter(school_type=school_type)
        activities_qs = activities_qs.filter(school__school_type=school_type)
        ssa_qs = ssa_qs.filter(school__school_type=school_type)
    # Activity Type
    if activity_type and activity_type != "All":
        activities_qs = activities_qs.filter(activity_type=activity_type)
    # Search
    if search_q:
        # Activity has no `responsible_staff` relation — the column is
        # responsible_staff_id, a CharField holding a StaffProfile id on
        # some rows and a User id on others. The traversal written here
        # raised FieldError, so every ?q= on this page was a hard 500. It
        # never surfaced because the page shipped without a search control
        # to type into, which is the only reason a crash this total could
        # sit in the query path unnoticed.
        #
        # Both id spaces are resolved and unioned, exactly as the IA queue
        # does, so a staff name matches whichever space the row was written
        # in rather than silently matching half of them.
        # Imported at call time rather than at module scope on purpose:
        # a `from ... import StaffProfile` inside this branch would make
        # StaffProfile a local for the whole function, and the untaken
        # branch would then leave it unbound where the module-level import
        # is used further down.
        from apps.accounts.models import User as _User

        staff_name_ids = set(
            StaffProfile.objects.filter(user__name__icontains=search_q).values_list(
                "id", flat=True
            )
        ) | set(
            _User.objects.filter(name__icontains=search_q).values_list("id", flat=True)
        )

        schools_qs = schools_qs.filter(
            Q(name__icontains=search_q) | Q(school_id__icontains=search_q)
        )
        activities_qs = activities_qs.filter(
            Q(school__name__icontains=search_q)
            | Q(cluster__name__icontains=search_q)
            | Q(responsible_staff_id__in=staff_name_ids)
        )
        ssa_qs = ssa_qs.filter(school__name__icontains=search_q)

    if filters.get("month"):
        from apps.hr.accountability import reporting_period

        _, period_start, period_end = reporting_period(fy, month=filters["month"])
        activities_qs = activities_qs.filter(
            planned_date__range=(period_start, period_end)
        )

    # Quarter restriction for current period metrics (except cumulative metrics)
    curr_activities = (
        activities_qs.filter(quarter=quarter) if quarter else activities_qs
    )
    curr_ssa = ssa_qs.filter(quarter=quarter) if quarter else ssa_qs

    # Prior period matching
    prior_q = {"Q2": "Q1", "Q3": "Q2", "Q4": "Q3", "Q1": "Q4"}.get(quarter, "Q1")
    prior_activities = activities_qs.filter(quarter=prior_q)
    prior_ssa = ssa_qs.filter(quarter=prior_q)

    # 4. Calculate KPI Cards (Current vs Prior Q)
    kpi_data = {}

    # Helper to format trend text
    def get_trend(curr, prev, mode="pct"):
        if not quarter or quarter == "Q1":
            return ""
        if prev == 0:
            return f"+{curr} vs {prior_q}" if curr > 0 else f"0 vs {prior_q}"
        if mode == "pp":
            diff = curr - prev
            return (
                f"+{diff:.0f}pp vs {prior_q}"
                if diff >= 0
                else f"{diff:.0f}pp vs {prior_q}"
            )
        else:
            pct = ((curr - prev) / prev) * 100
            return (
                f"+{pct:.0f}% vs {prior_q}" if pct >= 0 else f"{pct:.0f}% vs {prior_q}"
            )

    # Cards 1-3 and 6-8 all read the same two activity querysets. Compute
    # each period in one pass rather than issuing a separate COUNT/SUM per
    # card: the joins are all many-to-one (activity -> school), so there is
    # no row fan-out to distort the sums.
    _achieved = Q(status__in=ACHIEVED_STATUSES)
    _accepted = _achieved & Q(evidence_status="accepted")

    def activity_kpis(qs):
        return qs.aggregate(
            accepted=Count("id", filter=_accepted),
            teachers=Sum("teachers_attended", filter=_achieved),
            leaders=Sum("leaders_attended", filter=_achieved),
            districts=Count(
                "school__district_id",
                distinct=True,
                filter=_achieved & Q(school__district__isnull=False),
            ),
            clusters=Count(
                "school__cluster_id",
                distinct=True,
                filter=_achieved & Q(school__cluster_id__isnull=False),
            ),
        )

    curr_kpis = activity_kpis(curr_activities)
    prior_kpis = activity_kpis(prior_activities)

    # Score the approved allocation contract in its own units. Never sum
    # incompatible targets or invent equal quarterly phasing.
    from apps.hr.accountability import allocation_priorities

    contract = allocation_priorities(
        principal,
        fy,
        quarter=quarter,
        month=filters.get("month"),
        activity_ids=curr_activities.values("id"),
        include_plans=False,
    )
    # Geography and activity filters do not define an allocation boundary.
    # Withhold the score rather than divide a subset by a full-scope target.
    narrowed = any(
        filters.get(key) not in (None, "", "All")
        for key in (
            "region",
            "sub_region",
            "district",
            "sub_county",
            "cluster",
            "staff",
            "cceo",
            "pl",
            "partner",
            "school_type",
            "activity_type",
            "q",
        )
    )
    achievement_pct = None if narrowed else contract["pct"]
    kpi_data["target_achievement"] = {
        "value": f"{achievement_pct}%"
        if achievement_pct is not None
        else ("Scope target unavailable" if narrowed else "No Target Set"),
        "trend": "",
        "points": [],
        "class": "text-emerald-600"
        if achievement_pct is not None
        else "text-slate-500",
    }

    # Card 2: Teachers Trained
    teachers = curr_kpis["teachers"] or 0
    teachers_prior = prior_kpis["teachers"] or 0
    kpi_data["teachers_trained"] = {
        "value": f"{teachers:,}",
        "trend": get_trend(teachers, teachers_prior),
        "points": [],
    }

    # Card 3: School Leaders Trained
    leaders = curr_kpis["leaders"] or 0
    leaders_prior = prior_kpis["leaders"] or 0
    kpi_data["leaders_trained"] = {
        "value": f"{leaders:,}",
        "trend": get_trend(leaders, leaders_prior),
        "points": [],
    }

    # Card 4: Students Impacted is the current pupil enrollment of every
    # school in the caller's filtered directory scope. Enrollment is
    # school master data uploaded independently of activities, so gating
    # this metric on a completed activity made a populated directory read
    # as zero whenever the selected quarter had no verified work.
    scoped_school_ids = schools_qs.values("id")
    students = (
        School.objects.filter(id__in=scoped_school_ids).aggregate(s=Sum("enrollment"))[
            "s"
        ]
        or 0
    )

    # Schools Impacted remains an execution metric: a school only counts
    # here after completed/verified work in the selected quarter.
    reached_school_ids = (
        curr_activities.filter(status__in=ACHIEVED_STATUSES)
        .values_list("school_id", flat=True)
        .distinct()
    )
    reached_prior_school_ids = (
        prior_activities.filter(status__in=ACHIEVED_STATUSES)
        .values_list("school_id", flat=True)
        .distinct()
    )

    def format_large(val):
        if val >= 1_000_000:
            return f"{val / 1_000_000:.2f}M"
        if val >= 1_000:
            return f"{val / 1_000:.0f}K"
        return str(val)

    kpi_data["students_impacted"] = {
        "value": format_large(students),
        # The school table holds the latest enrollment, not a quarterly
        # enrollment snapshot, so showing a quarter-over-quarter arrow
        # here would fabricate a historical comparison.
        "trend": "",
        "points": [],
    }

    # Card 5: Schools Impacted (Distinct)
    schools_imp = len(reached_school_ids)
    schools_imp_prior = len(reached_prior_school_ids)
    kpi_data["schools_impacted"] = {
        "value": f"{schools_imp:,}",
        "trend": get_trend(schools_imp, schools_imp_prior),
        "points": [],
    }

    # Card 6: Districts Covered
    districts = curr_kpis["districts"]
    districts_prior = prior_kpis["districts"]
    kpi_data["districts_covered"] = {
        "value": str(districts),
        "trend": get_trend(districts, districts_prior),
        "points": [],
    }

    # Card 7: Clusters Covered
    clusters = curr_kpis["clusters"]
    clusters_prior = prior_kpis["clusters"]
    kpi_data["clusters_covered"] = {
        "value": str(clusters),
        "trend": get_trend(clusters, clusters_prior),
        "points": [],
    }

    # Card 8: Total Activities Completed
    # Same population as Card 1's numerator, so it reuses that count
    # rather than re-running an identical query.
    completed = curr_kpis["accepted"]
    completed_prior = prior_kpis["accepted"]
    kpi_data["activities_completed"] = {
        "value": f"{completed:,}",
        "trend": get_trend(completed, completed_prior),
        "points": [],
    }

    # Card 9: SSA Average
    ssa_avg = curr_ssa.aggregate(a=Avg("average_score"))["a"] or 0
    ssa_avg_prior = prior_ssa.aggregate(a=Avg("average_score"))["a"] or 0
    ssa_diff = ssa_avg - ssa_avg_prior
    kpi_data["ssa_average"] = {
        "value": f"{ssa_avg:.2f}" if ssa_avg > 0 else "\u2014",
        "trend": (
            f"{ssa_diff:+.2f} vs {prior_q}" if quarter and quarter != "Q1" else ""
        ),
        "points": [],
    }

    # Construct unified KPI strip items
    kpi_strip_items = [
        render_precomputed_metric_item(
            "analytics_analytics_dashboard_service_overall_target_achievement",
            kpi_data["target_achievement"]["value"],
            raw_value=achievement_pct,
            helper="approved allocation · verified"
            if achievement_pct is not None
            else (
                "no target for this filter scope"
                if narrowed
                else "no approved target configured"
            ),
            icon="target",
            variant="success" if achievement_pct is not None else "neutral",
            trend={
                "direction": (
                    "up" if "+" in kpi_data["target_achievement"]["trend"] else "down"
                )
                if kpi_data["target_achievement"]["trend"]
                else "neutral",
                "value": kpi_data["target_achievement"]["trend"].split()[0]
                if kpi_data["target_achievement"]["trend"]
                else "",
            },
        ),
        render_precomputed_metric_item(
            "analytics_analytics_dashboard_service_teachers_trained",
            kpi_data["teachers_trained"]["value"],
            raw_value=teachers,
            helper="attended",
            icon="users",
            variant="info",
            trend={
                "direction": "up"
                if "+" in kpi_data["teachers_trained"]["trend"]
                else "down",
                "value": kpi_data["teachers_trained"]["trend"].split()[0]
                if kpi_data["teachers_trained"]["trend"]
                else "",
            },
        ),
        render_precomputed_metric_item(
            "analytics_analytics_dashboard_service_school_leaders_trained",
            kpi_data["leaders_trained"]["value"],
            raw_value=leaders,
            helper="attended",
            icon="target",
            variant="warning",
            trend={
                "direction": "up"
                if "+" in kpi_data["leaders_trained"]["trend"]
                else "down",
                "value": kpi_data["leaders_trained"]["trend"].split()[0]
                if kpi_data["leaders_trained"]["trend"]
                else "",
            },
        ),
        render_precomputed_metric_item(
            "analytics_analytics_dashboard_service_students_impacted",
            kpi_data["students_impacted"]["value"],
            raw_value=students,
            helper="current enrollment",
            icon="users",
            variant="blue",
            trend={
                "direction": "up"
                if "+" in kpi_data["students_impacted"]["trend"]
                else "down",
                "value": kpi_data["students_impacted"]["trend"].split()[0]
                if kpi_data["students_impacted"]["trend"]
                else "",
            },
        ),
        render_precomputed_metric_item(
            "analytics_analytics_dashboard_service_schools_impacted",
            kpi_data["schools_impacted"]["value"],
            raw_value=schools_imp,
            helper="total reached",
            icon="school",
            variant="primary",
            trend={
                "direction": "up"
                if "+" in kpi_data["schools_impacted"]["trend"]
                else "down",
                "value": kpi_data["schools_impacted"]["trend"].split()[0]
                if kpi_data["schools_impacted"]["trend"]
                else "",
            },
        ),
        render_precomputed_metric_item(
            "analytics_analytics_dashboard_service_districts_covered",
            kpi_data["districts_covered"]["value"],
            raw_value=districts,
            helper="covered",
            icon="school",
            variant="danger",
            trend={
                "direction": "up"
                if "+" in kpi_data["districts_covered"]["trend"]
                else "down",
                "value": kpi_data["districts_covered"]["trend"].split()[0]
                if kpi_data["districts_covered"]["trend"]
                else "",
            },
        ),
        render_precomputed_metric_item(
            "analytics_analytics_dashboard_service_clusters_covered",
            kpi_data["clusters_covered"]["value"],
            raw_value=clusters,
            helper="reached",
            icon="school",
            variant="purple",
            trend={
                "direction": "up"
                if "+" in kpi_data["clusters_covered"]["trend"]
                else "down",
                "value": kpi_data["clusters_covered"]["trend"].split()[0]
                if kpi_data["clusters_covered"]["trend"]
                else "",
            },
        ),
        render_precomputed_metric_item(
            "analytics_analytics_dashboard_service_total_activities_completed",
            kpi_data["activities_completed"]["value"],
            raw_value=completed,
            helper="completed work",
            icon="check",
            variant="success",
            trend={
                "direction": "up"
                if "+" in kpi_data["activities_completed"]["trend"]
                else "down",
                "value": kpi_data["activities_completed"]["trend"].split()[0]
                if kpi_data["activities_completed"]["trend"]
                else "",
            },
        ),
        render_precomputed_metric_item(
            "analytics_analytics_dashboard_service_ssa_average",
            kpi_data["ssa_average"]["value"],
            raw_value=float(ssa_avg) if ssa_avg > 0 else None,
            helper="average score",
            icon="chart",
            variant="blue",
            trend={
                "direction": "up"
                if "+" in kpi_data["ssa_average"]["trend"]
                else "down",
                "value": kpi_data["ssa_average"]["trend"].split()[0]
                if kpi_data["ssa_average"]["trend"]
                else "",
            },
        ),
    ]

    # 5. Performance Overview Chart Series (Grouped months)
    # Months in fiscal year order: Oct, Nov, Dec, Jan, Feb, Mar, Apr, May, Jun, Jul, Aug, Sep
    months_fy = [10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9]
    labels_months = [
        "Oct",
        "Nov",
        "Dec",
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
    ]
    planned_series = []
    achieved_series = []
    ach_pct_series = []

    # One grouped query for all twelve months. Counting month-by-month cost
    # 24 round trips for data the database can group in a single pass.
    # Grouped-count correction (see the module docstring): the ordering is
    # cleared so the GROUP BY is the key alone. Applied to all four counts.
    month_counts = {
        row["planned_month"]: row
        for row in activities_qs.order_by()
        .values("planned_month")
        .annotate(
            planned=Count("id"),
            achieved=Count("id", filter=Q(status__in=ACHIEVED_STATUSES)),
        )
    }

    for m in months_fy:
        row = month_counts.get(m)
        pl_cnt = row["planned"] if row else 0
        ach_cnt = row["achieved"] if row else 0
        pct = round((ach_cnt / pl_cnt * 100)) if pl_cnt > 0 else 0

        planned_series.append(pl_cnt)
        achieved_series.append(ach_cnt)
        ach_pct_series.append(pct)

    chart_performance = {
        "labels": labels_months,
        "planned": planned_series,
        "achieved": achieved_series,
        "pct": ach_pct_series,
    }

    # 6. SSA Performance by Intervention Horizontal Bars
    # Driven by the canonical SsaIntervention enum so this never drifts.
    ssa_interventions = [(code, label, None) for code, label in SsaIntervention.choices]
    ssa_scores_list = []
    intervention_avgs = {
        row["intervention"]: row["avg"]
        for row in SsaScore.objects.filter(
            ssa_record__school__in=schools_qs, ssa_record__fy=fy
        )
        .values("intervention")
        .annotate(avg=Avg("score"))
    }
    for code, label, _default in ssa_interventions:
        avg_score = intervention_avgs.get(code)
        val = float(avg_score) if avg_score is not None else 0.0
        ssa_scores_list.append(
            {
                "code": code,
                "label": label,
                "value": round(val, 2),
                # SSA interventions are scored on the canonical 0-10
                # scale. Keep the visual bar on that same contract so a
                # 6.0 score reads as 60%, not as a full bar.
                "pct": round(val / 10.0 * 100) if avg_score is not None else 0,
            }
        )

    # 7. Target Achievement by District
    #
    # The overview used to take the first eight district names in
    # alphabetical order. That made the card a directory sample rather
    # than an analytical view: a district with a severe delivery gap could
    # disappear simply because its name started late in the alphabet.
    # Build the complete role- and filter-scoped set once, then group it by
    # the operational sub-region and rank the groups by attention needed.
    districts_perf = []
    scoped_districts = list(
        District.objects.filter(id__in=schools_qs.values("district_id"))
        .select_related("region", "sub_region")
        .distinct()
        .order_by("region__name", "sub_region__name", "name")
    )
    scoped_district_ids = [district.id for district in scoped_districts]
    district_counts = {
        row["school__district_id"]: row
        for row in activities_qs.filter(school__district_id__in=scoped_district_ids)
        .order_by()
        .values("school__district_id")
        .annotate(
            planned=Count("id"),
            achieved=Count("id", filter=Q(status__in=ACHIEVED_STATUSES)),
            # School reach (owner, 2026-09-05): distinct schools with planned
            # and with achieved work, in the same query as the activity counts.
            planned_schools=Count("school_id", distinct=True),
            achieved_schools=Count(
                "school_id", distinct=True, filter=Q(status__in=ACHIEVED_STATUSES)
            ),
        )
    }
    district_school_counts = {
        row["district_id"]: row["count"]
        for row in schools_qs.filter(district_id__in=scoped_district_ids)
        .values("district_id")
        .annotate(count=Count("id"))
    }

    for dist in scoped_districts:
        row = district_counts.get(dist.id)
        planned_d = row["planned"] if row else 0
        achieved_d = row["achieved"] if row else 0
        pct_d = round((achieved_d / planned_d * 100)) if planned_d > 0 else 0
        if planned_d == 0:
            status = "untracked"
            status_label = "No plan"
            sort_rank = 3
        elif pct_d >= 80:
            status = "on_track"
            status_label = "On track"
            sort_rank = 2
        elif pct_d >= 50:
            status = "watch"
            status_label = "Watch"
            sort_rank = 1
        else:
            status = "critical"
            status_label = "Critical"
            sort_rank = 0

        districts_perf.append(
            {
                "id": dist.id,
                "name": dist.name,
                "region": dist.region.name,
                "sub_region": (
                    dist.sub_region.name if dist.sub_region else "Other districts"
                ),
                "pct": pct_d,
                "gap": max(0, 100 - pct_d) if planned_d else None,
                "planned": planned_d,
                "achieved": achieved_d,
                "schools": district_school_counts.get(dist.id, 0),
                "schools_planned": row["planned_schools"] if row else 0,
                "schools_achieved": row["achieved_schools"] if row else 0,
                "schools_pct": (
                    round(
                        (row["achieved_schools"] if row else 0)
                        / district_school_counts[dist.id]
                        * 100
                    )
                    if district_school_counts.get(dist.id)
                    else 0
                ),
                "status": status,
                "status_label": status_label,
                "sort_rank": sort_rank,
            }
        )

    district_groups_by_key: dict[tuple[str, str], dict] = {}
    for district in districts_perf:
        key = (district["region"], district["sub_region"])
        group = district_groups_by_key.setdefault(
            key,
            {
                "region": district["region"],
                "name": district["sub_region"],
                "districts": [],
                "critical_count": 0,
                "watch_count": 0,
                "on_track_count": 0,
                "untracked_count": 0,
                "planned": 0,
                "achieved": 0,
                "schools": 0,
                "schools_planned": 0,
                "schools_achieved": 0,
            },
        )
        group["districts"].append(district)
        group[f"{district['status']}_count"] += 1
        group["planned"] += district["planned"]
        group["achieved"] += district["achieved"]
        group["schools"] += district["schools"]
        group["schools_planned"] += district["schools_planned"]
        group["schools_achieved"] += district["schools_achieved"]

    target_by_district_groups = list(district_groups_by_key.values())
    for group in target_by_district_groups:
        group["districts"].sort(
            key=lambda district: (
                district["sort_rank"],
                -(district["gap"] or 0),
                district["name"],
            )
        )
        group["pct"] = (
            round(group["achieved"] / group["planned"] * 100)
            if group["planned"]
            else None
        )
        group["gap"] = 100 - group["pct"] if group["pct"] is not None else None
        group["schools_pct"] = (
            round(group["schools_achieved"] / group["schools"] * 100)
            if group["schools"]
            else 0
        )

    target_by_district_groups.sort(
        key=lambda group: (
            -group["critical_count"],
            -group["watch_count"],
            -(group["gap"] or 0),
            group["region"],
            group["name"],
        )
    )
    # The card's filter buttons carry these, so a reader can tell "no
    # critical district in this scope" from "the filter did nothing" —
    # with two districts, both critical, the three filters showed the same
    # rows and the card read as broken (owner, 2026-09-05).
    target_by_district_summary = {
        "districts": len(districts_perf),
        "critical": sum(1 for d in districts_perf if d["status"] == "critical"),
        "attention": sum(
            1 for d in districts_perf if d["status"] in ("critical", "watch")
        ),
    }

    # 8. Regional Performance (Map or list representation)
    regional_perf = []
    regions_list = Region.objects.all().order_by("name")
    # Three grouped queries for the whole region table, rather than four
    # per region: this loop grows with the estate, so per-row queries here
    # were the one place the page's cost tracked geography growth.
    region_acts = {
        row["school__region_id"]: row
        for row in activities_qs.order_by()
        .values("school__region_id")
        .annotate(
            planned=Count("id"),
            achieved=Count("id", filter=Q(status__in=ACHIEVED_STATUSES)),
        )
    }
    region_ssa = {
        row["school__region_id"]: row["a"]
        for row in SsaRecord.objects.filter(fy=fy, verification_status="confirmed")
        .values("school__region_id")
        .annotate(a=Avg("average_score"))
    }
    region_schools = {
        row["region_id"]: row["n"]
        for row in schools_qs.values("region_id").annotate(n=Count("id"))
    }

    for reg in regions_list:
        acts = region_acts.get(reg.id)
        reg_ssa = region_ssa.get(reg.id)
        reg_ach = acts["achieved"] if acts else 0
        reg_pl = acts["planned"] if acts else 0
        reg_pct = round((reg_ach / reg_pl * 100)) if reg_pl > 0 else 0

        regional_perf.append(
            {
                "id": reg.id,
                "name": reg.name,
                "ssa_avg": round(reg_ssa, 2) if reg_ssa is not None else None,
                "pct": reg_pct,
                "schools_count": region_schools.get(reg.id, 0),
                "completed": reg_ach,
            }
        )

    # 9. Cluster Performance (Top 10 ranked table)
    intervention_labels = dict(SsaIntervention.choices)
    cluster_perf = []
    shown_clusters = list(Cluster.objects.all()[:10])
    shown_cluster_ids = [c.id for c in shown_clusters]
    prev_fy = str(int(fy) - 1)

    # Five grouped queries for the whole table instead of five per row.
    cluster_acts = {
        row["school__cluster_id"]: row
        for row in activities_qs.filter(school__cluster_id__in=shown_cluster_ids)
        .order_by()
        .values("school__cluster_id")
        .annotate(
            trainings=Count("id", filter=Q(activity_type__in=TRAINING_TYPES)),
            visits=Count("id", filter=Q(activity_type__in=VISIT_TYPES)),
        )
    }
    _cluster_ssa_rows = (
        SsaRecord.objects.filter(
            school__cluster_id__in=shown_cluster_ids,
            fy__in=[fy, prev_fy],
            verification_status="confirmed",
        )
        .values("school__cluster_id", "fy")
        .annotate(a=Avg("average_score"))
    )
    cluster_ssa = {
        (row["school__cluster_id"], row["fy"]): row["a"] for row in _cluster_ssa_rows
    }
    cluster_interventions: dict[str, list[dict]] = {}
    for row in (
        SsaScore.objects.filter(
            ssa_record__school__cluster_id__in=shown_cluster_ids,
            ssa_record__fy=fy,
        )
        .values("ssa_record__school__cluster_id", "intervention")
        .annotate(avg=Avg("score"))
    ):
        cluster_interventions.setdefault(
            row["ssa_record__school__cluster_id"], []
        ).append(row)

    for i, cl in enumerate(shown_clusters):
        cl_ssa = cluster_ssa.get((cl.id, fy))
        acts = cluster_acts.get(cl.id)

        train_cnt = acts["trainings"] if acts else 0
        visit_cnt = acts["visits"] if acts else 0

        # Real best/worst intervention, derived the same way as the SSA
        # Performance by Intervention section (SsaScore per-intervention averages).
        cl_intervention_scores = cluster_interventions.get(cl.id, [])
        if cl_intervention_scores:
            best_row = max(cl_intervention_scores, key=lambda r: r["avg"])
            worst_row = min(cl_intervention_scores, key=lambda r: r["avg"])
            best_intervention = intervention_labels.get(
                best_row["intervention"], best_row["intervention"]
            )
            worst_intervention = intervention_labels.get(
                worst_row["intervention"], worst_row["intervention"]
            )
        else:
            best_intervention = "—"
            worst_intervention = "—"

        # Real trend: compare this cluster's current-FY SSA average against
        # the prior FY (same comparison basis used for Impact Summary below).
        cl_ssa_prev = cluster_ssa.get((cl.id, prev_fy))
        if cl_ssa is not None and cl_ssa_prev is not None and cl_ssa != cl_ssa_prev:
            cl_trend = "up" if cl_ssa > cl_ssa_prev else "down"
        else:
            cl_trend = None

        cluster_perf.append(
            {
                "rank": i + 1,
                "id": cl.id,
                "name": cl.name,
                "ssa_avg": f"{cl_ssa:.2f}" if cl_ssa is not None else "—",
                "ssa_avg_raw": round(cl_ssa, 2) if cl_ssa is not None else None,
                "best_intervention": best_intervention,
                "worst_intervention": worst_intervention,
                "trainings": train_cnt,
                "visits": visit_cnt,
                "trend": cl_trend,
            }
        )

    # 10. Impact Summary
    # Schools Improved: count schools with delta > +0.05 compared to prior year.
    # Two grouped queries (per-school averages for each FY) instead of 2×N.
    all_school_ids = set(schools_qs.values_list("id", flat=True))
    prev_fy = str(int(fy) - 1)

    def _avg_by_school(target_fy):
        rows = (
            SsaRecord.objects.filter(
                school_id__in=all_school_ids,
                fy=target_fy,
                verification_status="confirmed",
            )
            .values("school_id")
            .annotate(a=Avg("average_score"))
        )
        return {r["school_id"]: r["a"] for r in rows}

    curr_by_school = _avg_by_school(fy)
    prev_by_school = _avg_by_school(prev_fy)
    improved_cnt = sum(
        1
        for sid, curr_score in curr_by_school.items()
        if curr_score
        and prev_by_school.get(sid)
        and (curr_score - prev_by_school[sid] > 0.05)
    )

    impact_summary = {
        "teachers_trained": teachers,
        "leaders_trained": leaders,
        "students_impacted": students,
        "schools_improved": improved_cnt,
    }

    # 11. Activity Tracking Section
    activity_tracking = {
        "school_visits": curr_activities.filter(activity_type__in=VISIT_TYPES).count(),
        "cluster_trainings": curr_activities.filter(
            activity_type__in=TRAINING_TYPES
        ).count(),
        "cluster_meetings": curr_activities.filter(
            activity_type=CLUSTER_MEETING_TYPE
        ).count(),
        "ssa_support": curr_activities.filter(activity_type="ssa_activity").count(),
        "partner_activities": curr_activities.filter(delivery_type="partner").count(),
        "project_activities": curr_activities.filter(
            activity_type="project_activity"
        ).count(),
    }

    # 12. Staff & Partner Performance
    # Group achievements by Quarter
    staff_q1 = activities_qs.filter(
        quarter="Q1", delivery_type="staff", status__in=ACHIEVED_STATUSES
    ).count()
    staff_q2 = activities_qs.filter(
        quarter="Q2", delivery_type="staff", status__in=ACHIEVED_STATUSES
    ).count()
    partner_q1 = activities_qs.filter(
        quarter="Q1", delivery_type="partner", status__in=ACHIEVED_STATUSES
    ).count()
    partner_q2 = activities_qs.filter(
        quarter="Q2", delivery_type="partner", status__in=ACHIEVED_STATUSES
    ).count()

    # Overall achievement rate (achieved / planned) per delivery channel —
    # this is the real figure the bar comparison in the template renders.
    staff_planned_total = activities_qs.filter(delivery_type="staff").count()
    staff_achieved_total = activities_qs.filter(
        delivery_type="staff", status__in=ACHIEVED_STATUSES
    ).count()
    staff_pct = (
        round(staff_achieved_total / staff_planned_total * 100)
        if staff_planned_total > 0
        else 0
    )

    partner_planned_total = activities_qs.filter(delivery_type="partner").count()
    partner_achieved_total = activities_qs.filter(
        delivery_type="partner", status__in=ACHIEVED_STATUSES
    ).count()
    partner_pct = (
        round(partner_achieved_total / partner_planned_total * 100)
        if partner_planned_total > 0
        else 0
    )

    staff_partner_chart = {
        "staff": [staff_q1, staff_q2],
        "partner": [partner_q1, partner_q2],
        "staff_pct": staff_pct,
        "partner_pct": partner_pct,
    }

    # Leaderboard table
    leaderboard = []
    active_staff = StaffProfile.objects.filter(deleted_at__isnull=True).select_related(
        "user"
    )
    for st in active_staff[:5]:
        completed_cnt = activities_qs.filter(
            responsible_staff_id=st.id, status__in=ACHIEVED_STATUSES
        ).count()
        planned_cnt = activities_qs.filter(responsible_staff_id=st.id).count()
        ach_pct = round((completed_cnt / planned_cnt * 100)) if planned_cnt > 0 else 0

        leaderboard.append(
            {
                "name": st.user.name,
                "role": st.title or "CCEO",
                "activities": completed_cnt,
                "pct": ach_pct,
            }
        )

    # 13. Core & Champion School Performance
    core_schools_count = schools_qs.filter(school_type="core").count()
    core_ssa_avg = SsaRecord.objects.filter(
        school__school_type="core", fy=fy, verification_status="confirmed"
    ).aggregate(a=Avg("average_score"))["a"]

    champion_schools_count = schools_qs.filter(school_type="champion").count()
    champion_ssa_avg = SsaRecord.objects.filter(
        school__school_type="champion", fy=fy, verification_status="confirmed"
    ).aggregate(a=Avg("average_score"))["a"]

    core_champion = {
        "core_count": core_schools_count,
        "core_ssa": round(core_ssa_avg, 2) if core_ssa_avg is not None else None,
        "champion_count": champion_schools_count,
        "champion_ssa": round(champion_ssa_avg, 2)
        if champion_ssa_avg is not None
        else None,
    }

    # 14. Donor reporting snapshot matches KPI values
    donor_snapshot = {
        "teachers_trained": teachers,
        "leaders_trained": leaders,
        "students_impacted": students,
        "districts_covered": districts,
        "schools_impacted": schools_imp,
    }

    # 15. Recent Insights / Recommended Actions Rail (Traced Risk items)
    # Risk 1: Schools without SSA
    no_ssa_count = schools_qs.filter(
        current_fy_ssa_status__in=["not_done", "scheduled"]
    ).count()
    # Risk 2: Schools not visited in last 60 days
    sixty_days_ago = timezone.now() - datetime.timedelta(days=60)
    visited_schools = (
        Activity.objects.filter(
            deleted_at__isnull=True,
            activity_type__in=VISIT_TYPES,
            status__in=ACHIEVED_STATUSES,
            scheduled_date__gte=sixty_days_ago,
        )
        .values_list("school_id", flat=True)
        .distinct()
    )
    not_visited_count = schools_qs.exclude(id__in=visited_schools).count()

    # Risk 3: Schools not trained this quarter
    trained_schools = (
        Activity.objects.filter(
            deleted_at__isnull=True,
            activity_type__in=TRAINING_TYPES,
            status__in=ACHIEVED_STATUSES,
            quarter=quarter,
        )
        .values_list("school_id", flat=True)
        .distinct()
    )
    not_trained_count = schools_qs.exclude(id__in=trained_schools).count()

    # Risk 4: High-risk districts (SSA avg < 4.0 and target achievement < 60%)
    high_risk_districts = 0
    for dp in districts_perf:
        if dp["pct"] < 60:
            high_risk_districts += 1

    # Risk 5: Clusters needing attention (SSA avg < 4.0)
    clusters_attn = 0
    for cp in cluster_perf:
        if cp["ssa_avg_raw"] is not None and cp["ssa_avg_raw"] < 4.0:
            clusters_attn += 1

    insights = [
        {
            "key": "no_ssa",
            "label": "Schools without SSA",
            "count": no_ssa_count,
            "description": "Require immediate attention.",
            "icon": "⚠️",
            "color": "bg-rose-50 border-rose-200 text-rose-700",
        },
        {
            "key": "not_visited",
            "label": "Schools not visited",
            "count": not_visited_count,
            "description": "No visit in the last 60+ days.",
            "icon": "🏫",
            "color": "bg-rose-50 border-rose-200 text-rose-700",
            "tone": "danger",
        },
        {
            "key": "not_trained",
            "label": "Schools not trained",
            "count": not_trained_count,
            "description": "No training this quarter.",
            "icon": "🎓",
            "color": "bg-rose-50 border-rose-200 text-rose-700",
            "tone": "danger",
        },
        {
            "key": "high_risk_districts",
            "label": "High-risk districts",
            "count": high_risk_districts,
            "description": "Low SSA & low target achievement.",
            "icon": "🚨",
            "color": "bg-rose-50 border-rose-200 text-rose-700",
        },
        {
            "key": "clusters_attention",
            "label": "Clusters needing attention",
            "count": clusters_attn,
            "description": "Below 4.0 SSA average.",
            "icon": "👥",
            "color": "bg-purple-50 border-purple-200 text-purple-700",
        },
    ]

    return {
        "distributed": contract if not narrowed else {"rows": [], "pct": None},
        "filters": {
            "selected_fy": fy,
            "fy_options": fy_options(),
            "selected_quarter": quarter,
            "selected_region": region_id,
            "selected_sub_region": sub_region_id,
            "selected_district": district_id,
            "selected_sub_county": sub_county_id,
            "selected_cluster": cluster_id,
            "selected_staff": staff_id,
            "selected_partner": partner_id,
            "selected_school_type": school_type,
            "selected_activity_type": activity_type,
            "search_q": search_q,
        },
        "kpis": kpi_data,
        "kpi_strip_items": kpi_strip_items,
        "performance_overview": chart_performance,
        "ssa_performance": ssa_scores_list,
        "target_by_district": districts_perf,
        "target_by_district_groups": target_by_district_groups,
        "target_by_district_summary": target_by_district_summary,
        "regional_performance": regional_perf,
        # The geography card is a shared country-level system view for
        # every authorized analytics role. Dashboard KPIs remain scoped;
        # map pins and hover facts deliberately do not inherit role or
        # ad-hoc dashboard filters.
        **country_map_context(fy),
        "cluster_performance": cluster_perf,
        "impact_summary": impact_summary,
        "activity_tracking": activity_tracking,
        "staff_partner_performance": {
            "chart": staff_partner_chart,
            "leaderboard": leaderboard,
        },
        "core_champion": core_champion,
        "donor_snapshot": donor_snapshot,
        "insights": insights,
        "total_staff_count": active_staff.count(),
        "as_of_date": timezone.now().strftime("%B %d, %Y"),
    }


# ── Fixtures and assertions ──────────────────────────────────────────────────

User = get_user_model()
FY = "2026"


@freeze_time("2026-07-15 10:00:00+03:00")
class AnalyticsDashboardOracleTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        home = Region.objects.create(name="Oracle Central")
        away = Region.objects.create(name="Oracle West")
        cls.d1 = District.objects.create(
            name="Oracle D1", region=home, district_type="primary"
        )
        d2 = District.objects.create(
            name="Oracle D2", region=away, district_type="primary"
        )
        c1 = Cluster.objects.create(
            name="Oracle Cluster 1", region=home, district=cls.d1
        )
        c2 = Cluster.objects.create(
            name="Oracle Cluster 2", region=home, district=cls.d1
        )

        def school(code, **extra):
            return School.objects.create(school_id=code, name=f"Oracle {code}", **extra)

        s1 = school(
            "AN-1",
            region=home,
            district=cls.d1,
            cluster_id=c1.id,
            school_type="core",
            enrollment=300,
        )
        s2 = school(
            "AN-2",
            region=home,
            district=cls.d1,
            cluster_id=c2.id,
            school_type="champion",
            enrollment=200,
        )
        s3 = school("AN-3", region=away, district=d2, enrollment=150)
        s4 = school("AN-4", enrollment=90)  # unplaced: no region or district
        s5 = school("AN-5", region=home, district=cls.d1, enrollment=999)
        School.objects.filter(id=s5.id).update(deleted_at=timezone.now())
        cls.partner = Partner.objects.create(name="Oracle Partner")

        def staff(email, role, country=""):
            user = User.objects.create_user(
                email=email,
                name=email.split("@")[0].title(),
                roles=[role],
                active_role=role,
                password="x",
                is_active=True,
            )
            return user, StaffProfile.objects.create(
                user=user, title=role, country=country
            )

        cls.cd, _ = staff("an-cd@t.org", "CountryDirector", country="Uganda")
        cls.accountant, _ = staff("an-acct@t.org", "Accountant")
        cls.rvp, _ = staff("an-rvp@t.org", "RegionalVicePresident")
        cls.pl, pl_sp = staff("an-pl@t.org", "Program Lead", country="Uganda")
        cls.c1, c1_sp = staff("an-c1@t.org", "CCEO", country="Uganda")
        cls.c2, c2_sp = staff("an-c2@t.org", "CCEO")
        cls.idle, _ = staff("an-idle@t.org", "CCEO")
        cls.c1_sp = c1_sp
        for supervisee in (c1_sp, c2_sp):
            StaffSupervisorAssignment.objects.create(
                supervisor=pl_sp, supervisee=supervisee
            )
        for sp, schools in ((c1_sp, (s1, s2, s4)), (c2_sp, (s3,))):
            for s in schools:
                StaffSchoolAssignment.objects.create(staff=sp, school_id=s.id)

        quarter_of = {
            10: "Q1",
            11: "Q1",
            12: "Q1",
            1: "Q2",
            2: "Q2",
            3: "Q2",
            4: "Q3",
            5: "Q3",
            6: "Q3",
            7: "Q4",
            8: "Q4",
            9: "Q4",
        }

        # Each activity is created at its own moment, as real work is. Under
        # the class's frozen clock they would all share one `created_at`, and
        # a grouped count that splits on the creation time would agree with
        # a correct one by accident.
        created = iter(range(1, 1000))

        def act(sp, planned, atype="school_visit", status="ia_verified", **extra):
            activity = Activity.objects.create(
                activity_type=atype,
                delivery_type=extra.pop("delivery_type", "staff"),
                status=status,
                responsible_staff_id=sp.id,
                fy=extra.pop("fy", FY),
                quarter=quarter_of[planned.month],
                planned_date=planned,
                planned_month=planned.month,
                scheduled_date=timezone.make_aware(
                    timezone.datetime(planned.year, planned.month, planned.day, 9)
                ),
                **extra,
            )
            Activity.objects.filter(id=activity.id).update(
                created_at=timezone.now() - datetime.timedelta(hours=next(created))
            )
            return activity

        act(
            c1_sp,
            date(2025, 10, 8),
            school=s1,
            evidence_status="accepted",
            teachers_attended=12,
            leaders_attended=3,
        )
        act(
            c1_sp,
            date(2025, 11, 12),
            "cluster_training",
            school=s1,
            evidence_status="accepted",
            teachers_attended=30,
            leaders_attended=4,
        )
        act(c1_sp, date(2026, 1, 20), "cluster_meeting", "scheduled", cluster=c1)
        act(c1_sp, date(2026, 2, 3), school=s2, evidence_status="pending")
        act(
            c1_sp,
            date(2026, 4, 9),
            school=s2,
            evidence_status="accepted",
            teachers_attended=5,
        )
        act(c1_sp, date(2026, 4, 21), "ssa_activity", school=s1)
        act(c1_sp, date(2026, 5, 6), "project_activity", "scheduled", school=s4)
        act(c1_sp, date(2026, 6, 9), school=s4, evidence_status="accepted")
        act(c1_sp, date(2026, 7, 2), school=s1, status="completed")
        act(
            c2_sp,
            date(2026, 4, 14),
            school=s3,
            evidence_status="accepted",
            leaders_attended=2,
        )
        act(
            c2_sp,
            date(2026, 5, 19),
            "cluster_training",
            "ia_verified",
            school=s3,
            teachers_attended=8,
        )
        act(c2_sp, date(2026, 7, 7), school=s3, status="scheduled")
        # Partner work, monitored by an officer; one on the deleted school.
        act(
            c1_sp,
            date(2026, 4, 16),
            school=s2,
            delivery_type="partner",
            monitored_by_staff_id=c1_sp.id,
            assigned_partner_id=cls.partner.id,
            evidence_status="accepted",
        )
        act(
            c2_sp,
            date(2026, 1, 13),
            school=s5,
            delivery_type="partner",
            monitored_by_staff_id=c2_sp.id,
            status="scheduled",
        )
        # Last year's work and deleted work never count.
        act(c1_sp, date(2025, 4, 9), school=s1, fy="2025")
        gone = act(c1_sp, date(2026, 4, 10), school=s1)
        Activity.objects.filter(id=gone.id).update(deleted_at=timezone.now())

        def ssa(s, fy, quarter, score, day, status="confirmed"):
            record = SsaRecord.objects.create(
                school=s,
                fy=fy,
                quarter=quarter,
                date_of_ssa=timezone.make_aware(timezone.datetime(*day, 10)),
                average_score=score,
                verification_status=status,
            )
            for i, (code, _label) in enumerate(SsaIntervention.choices):
                SsaScore.objects.create(
                    ssa_record=record, intervention=code, score=score + i / 10
                )

        ssa(s1, "2025", "Q2", 4.2, (2025, 2, 3))
        # Three assessments averaged for one school: the order they are summed in must not matter.
        ssa(s1, "2026", "Q1", 4.4, (2025, 11, 3))
        ssa(s1, "2026", "Q2", 4.7, (2026, 2, 3))
        ssa(s1, "2026", "Q3", 5.1, (2026, 5, 4))
        ssa(s2, "2025", "Q3", 6.0, (2025, 5, 3))
        ssa(s2, "2026", "Q3", 5.2, (2026, 5, 5))
        ssa(s3, "2026", "Q3", 3.1, (2026, 4, 30))
        ssa(s3, "2025", "Q3", 3.05, (2025, 4, 30))  # +0.05 exactly: not "improved"
        ssa(s4, "2026", "Q4", 7.0, (2026, 7, 1), status="pending")

    def assertSameAsFrozen(self, principal, **filters):
        filters = {"fy": FY, **filters}
        with self.subTest(principal=principal.email, **filters):
            self.assertEqual(
                AnalyticsDashboardService.get_analytics_data(principal, filters),
                _frozen_get_analytics_data(principal, filters),
            )

    def test_every_scope(self):
        for principal in (
            self.cd,
            self.accountant,
            self.rvp,
            self.pl,
            self.c1,
            self.idle,
        ):
            self.assertSameAsFrozen(principal)
            self.assertSameAsFrozen(principal, quarter="Q3")

    def test_periods(self):
        for filters in (
            {"quarter": "Q1"},
            {"quarter": "Q4"},
            {"month": "4"},
            {"month": "4", "quarter": "Q3"},
            {"fy": "2025"},
            {"fy": "2031"},
        ):
            self.assertSameAsFrozen(self.cd, **filters)
            self.assertSameAsFrozen(self.pl, **filters)

    def test_filters(self):
        for filters in (
            {"district": self.d1.id},
            {"region": self.d1.region_id},
            {"cluster": School.objects.get(school_id="AN-1").cluster_id},
            {"school_type": "core"},
            {"school_type": "All"},
            {"activity_type": "school_visit"},
            {"partner": self.partner.id},
            {"staff": self.c1_sp.id},
            {"pl": self.pl.id},
            {"staff": "no-such-staff"},
            {"q": "AN-1"},
            {"q": "An-C1"},
        ):
            self.assertSameAsFrozen(self.cd, quarter="Q3", **filters)
            self.assertSameAsFrozen(self.accountant, **filters)

    def test_fixture_exercises_the_edges(self):
        data = AnalyticsDashboardService.get_analytics_data(
            self.cd, {"fy": FY, "quarter": "Q3"}
        )
        self.assertGreater(sum(data["activity_tracking"].values()), 0)
        self.assertGreater(data["impact_summary"]["schools_improved"], 0)
        chart = data["staff_partner_performance"]["chart"]
        self.assertGreater(chart["staff_pct"], 0)
        self.assertGreater(chart["partner_pct"], 0)
