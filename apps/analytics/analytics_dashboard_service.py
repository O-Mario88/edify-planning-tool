"""Analytics dashboard service — compile role-scoped, filter-aware metrics for the command center."""

from __future__ import annotations

import datetime
from collections import defaultdict
from django.db.models import Avg, Q, Sum
from django.utils import timezone

from apps.core.fy import get_operational_fy, get_quarter_for_date
from apps.core.enums import SsaIntervention
from apps.core.scoping import resolve_user_scope
from apps.schools.models import School
from apps.activities.models import Activity
from apps.ssa.models import SsaRecord, SsaScore
from apps.targets.models import TargetSetting
from apps.accounts.models import StaffProfile, StaffTargetProfile
from apps.geography.models import District, Region
from apps.clusters.models import Cluster

ACHIEVED_STATUSES = ("ia_verified", "closed", "accountant_confirmed")
VISIT_TYPES = (
    "school_visit",
    "follow_up_visit",
    "coaching_visit",
    "in_school_support",
    "core_visit",
)
TRAINING_TYPES = (
    "training",
    "school_improvement_training",
    "cluster_training",
    "core_training",
)
CLUSTER_MEETING_TYPE = "cluster_meeting"


class AnalyticsDashboardService:
    @staticmethod
    def get_analytics_data(principal, filters: dict) -> dict:
        # 1. Parse active filters
        fy = filters.get("fy") or get_operational_fy()
        # Default to the real current quarter (not a hardcoded guess) so the
        # dashboard opens on the period that actually has fresh data.
        quarter = filters.get("quarter") or get_quarter_for_date()
        region_id = filters.get("region")
        district_id = filters.get("district")
        cluster_id = filters.get("cluster")
        staff_id = filters.get("staff")
        partner_id = filters.get("partner")
        school_type = filters.get("school_type")
        activity_type = filters.get("activity_type")
        search_q = filters.get("q")

        # Resolve user data visibility scope
        scope = resolve_user_scope(principal)

        # `Activity.responsible_staff_id` stores the *User* id (see seed.py /
        # AuthPrincipal.user_id), not the StaffProfile id that
        # `resolve_user_scope` deals in for `staff_ids`/`supervised_staff_ids`.
        # Resolve the real User ids for "own + supervised team" once so every
        # activity filter below compares like-for-like ids.
        own_and_team_user_ids: list[str] = []
        if not scope.country_scope:
            profile_ids = [
                pid for pid in (*scope.staff_ids, *scope.supervised_staff_ids) if pid
            ]
            if profile_ids:
                own_and_team_user_ids = list(
                    StaffProfile.objects.filter(id__in=profile_ids).values_list(
                        "user_id", flat=True
                    )
                )

        # 2. Base Querysets
        schools_qs = School.objects.filter(deleted_at__isnull=True)
        activities_qs = Activity.objects.filter(deleted_at__isnull=True, fy=fy)
        ssa_qs = SsaRecord.objects.filter(
            deleted_at__isnull=True, fy=fy, verification_status="confirmed"
        )

        # Apply role-based visibility scoping. School/SSA scoping and
        # activity scoping are resolved independently — a CCEO/PL with real
        # logged activities but no formal StaffSchoolAssignment row (common
        # in this dataset) must still see their own work, not an all-empty
        # dashboard.
        if not scope.country_scope:
            if scope.school_ids:
                schools_qs = schools_qs.filter(id__in=scope.school_ids)
                ssa_qs = ssa_qs.filter(school_id__in=scope.school_ids)
            elif scope.region_ids:
                # Summary-only roles (e.g. Regional VP) are scoped by assigned
                # region(s) rather than an explicit school list.
                schools_qs = schools_qs.filter(region_id__in=scope.region_ids)
                ssa_qs = ssa_qs.filter(school__region_id__in=scope.region_ids)
            elif own_and_team_user_ids:
                # No formal school assignment on record — fall back to the
                # schools this staff member has actually logged activity
                # against, so their dashboard isn't empty by default.
                activity_school_ids = list(
                    Activity.objects.filter(
                        responsible_staff_id__in=own_and_team_user_ids,
                        deleted_at__isnull=True,
                    )
                    .values_list("school_id", flat=True)
                    .distinct()
                )
                schools_qs = schools_qs.filter(id__in=activity_school_ids)
                ssa_qs = ssa_qs.filter(school_id__in=activity_school_ids)
            else:
                schools_qs = schools_qs.none()
                ssa_qs = ssa_qs.none()

            if own_and_team_user_ids:
                activities_qs = activities_qs.filter(
                    Q(responsible_staff_id__in=own_and_team_user_ids)
                    | Q(assigned_partner_id__in=scope.partner_ids)
                )
            elif scope.region_ids:
                activities_qs = activities_qs.filter(
                    school__region_id__in=scope.region_ids
                )
            elif scope.partner_ids:
                activities_qs = activities_qs.filter(
                    assigned_partner_id__in=scope.partner_ids
                )
            else:
                activities_qs = activities_qs.none()

        # 3. Apply page filters to Querysets
        # Region
        if region_id:
            schools_qs = schools_qs.filter(region_id=region_id)
            activities_qs = activities_qs.filter(school__region_id=region_id)
            ssa_qs = ssa_qs.filter(school__region_id=region_id)
        # District
        if district_id:
            schools_qs = schools_qs.filter(district_id=district_id)
            activities_qs = activities_qs.filter(school__district_id=district_id)
            ssa_qs = ssa_qs.filter(school__district_id=district_id)
        # Cluster
        if cluster_id:
            schools_qs = schools_qs.filter(cluster_id=cluster_id)
            activities_qs = activities_qs.filter(school__cluster_id=cluster_id)
            ssa_qs = ssa_qs.filter(school__cluster_id=cluster_id)
        # Staff Owner — the filter dropdown submits a StaffProfile id (matches
        # School.account_owner_id), but Activity.responsible_staff_id stores
        # the User id, so resolve it before filtering activities.
        if staff_id:
            staff_user_id = (
                StaffProfile.objects.filter(id=staff_id)
                .values_list("user_id", flat=True)
                .first()
            )
            activities_qs = activities_qs.filter(
                responsible_staff_id=staff_user_id or "__no_match__"
            )
            schools_qs = schools_qs.filter(account_owner_id=staff_id)
            ssa_qs = ssa_qs.filter(school__account_owner_id=staff_id)
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
        # Search — "responsible_staff" is not a real relation on Activity
        # (responsible_staff_id is a plain CharField holding the User id), so
        # matching staff names resolves via a User id subquery instead of an
        # invalid `responsible_staff__user__name` lookup.
        if search_q:
            schools_qs = schools_qs.filter(
                Q(name__icontains=search_q) | Q(school_id__icontains=search_q)
            )
            from apps.accounts.models import User as _User

            matching_user_ids = _User.objects.filter(
                name__icontains=search_q
            ).values_list("id", flat=True)
            activities_qs = activities_qs.filter(
                Q(school__name__icontains=search_q)
                | Q(cluster__name__icontains=search_q)
                | Q(responsible_staff_id__in=matching_user_ids)
            )
            ssa_qs = ssa_qs.filter(school__name__icontains=search_q)

        # Quarter restriction for current period metrics (except cumulative
        # metrics — SSA Average below is intentionally FY-cumulative, not
        # quarter-restricted; see Card 9).
        curr_activities = activities_qs.filter(quarter=quarter)

        # Prior period matching
        prior_q = {"Q2": "Q1", "Q3": "Q2", "Q4": "Q3", "Q1": "Q4"}.get(quarter, "Q1")
        prior_activities = activities_qs.filter(quarter=prior_q)

        # 4. Calculate KPI Cards (Current vs Prior Q)
        kpi_data = {}

        # Helper to format trend text
        def get_trend(curr, prev, mode="pct"):
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
                    f"+{pct:.0f}% vs {prior_q}"
                    if pct >= 0
                    else f"{pct:.0f}% vs {prior_q}"
                )

        # Card 1: Target Achievement
        # Count achieved activities in quarter
        achieved_q = curr_activities.filter(
            status__in=ACHIEVED_STATUSES, evidence_status="accepted"
        ).count()
        achieved_prior = prior_activities.filter(
            status__in=ACHIEVED_STATUSES, evidence_status="accepted"
        ).count()

        # Targets sum
        targets_sum = (
            TargetSetting.objects.filter(fy=fy, is_active=True).aggregate(
                s=Sum("target_value")
            )["s"]
            or 0
        )
        if targets_sum == 0:
            # Fallback to StaffTargetProfiles
            targets_sum = StaffTargetProfile.objects.filter(fy=fy).aggregate(
                v=Sum("visits_target"), t=Sum("trainings_target")
            )
            targets_sum = (targets_sum["v"] or 0) + (targets_sum["t"] or 0)
        has_target_data = targets_sum > 0
        if targets_sum == 0:
            # No TargetSetting or StaffTargetProfile rows exist for this FY/scope
            # yet — fall back to the scheduled activity count so the ratio is
            # still meaningful, but flag it so the UI can be honest that no
            # formal target has been configured.
            targets_sum = activities_qs.count()

        # Target for this quarter is roughly 25% of annual targets
        q_target = max(1, round(targets_sum / 4)) if targets_sum else 0
        if q_target:
            achievement_pct = round((achieved_q / q_target) * 100)
            achievement_prior_pct = round((achieved_prior / q_target) * 100)
        else:
            achievement_pct = 0
            achievement_prior_pct = 0

        kpi_data["target_achievement"] = {
            "value": f"{achievement_pct}%" if q_target else "N/A",
            "trend": get_trend(achievement_pct, achievement_prior_pct, "pp")
            if q_target
            else "No target configured",
            "has_data": bool(q_target),
            "has_target_data": has_target_data,
            "class": "text-emerald-600"
            if achievement_pct >= 90
            else ("text-amber-600" if achievement_pct >= 70 else "text-rose-600"),
        }

        # Card 2: Teachers Trained
        teachers = (
            curr_activities.filter(status__in=ACHIEVED_STATUSES).aggregate(
                s=Sum("teachers_attended")
            )["s"]
            or 0
        )
        teachers_prior = (
            prior_activities.filter(status__in=ACHIEVED_STATUSES).aggregate(
                s=Sum("teachers_attended")
            )["s"]
            or 0
        )
        kpi_data["teachers_trained"] = {
            "value": f"{teachers:,}",
            "trend": get_trend(teachers, teachers_prior),
        }

        # Card 3: School Leaders Trained
        leaders = (
            curr_activities.filter(status__in=ACHIEVED_STATUSES).aggregate(
                s=Sum("leaders_attended")
            )["s"]
            or 0
        )
        leaders_prior = (
            prior_activities.filter(status__in=ACHIEVED_STATUSES).aggregate(
                s=Sum("leaders_attended")
            )["s"]
            or 0
        )
        kpi_data["leaders_trained"] = {
            "value": f"{leaders:,}",
            "trend": get_trend(leaders, leaders_prior),
        }

        # Card 4: Students Impacted (Sum enrollment of reached schools, distinct)
        reached_school_ids = (
            curr_activities.filter(status__in=ACHIEVED_STATUSES)
            .values_list("school_id", flat=True)
            .distinct()
        )
        students = (
            School.objects.filter(id__in=reached_school_ids).aggregate(
                s=Sum("enrollment")
            )["s"]
            or 0
        )

        reached_prior_school_ids = (
            prior_activities.filter(status__in=ACHIEVED_STATUSES)
            .values_list("school_id", flat=True)
            .distinct()
        )
        students_prior = (
            School.objects.filter(id__in=reached_prior_school_ids).aggregate(
                s=Sum("enrollment")
            )["s"]
            or 0
        )

        def format_large(val):
            if val >= 1_000_000:
                return f"{val / 1_000_000:.2f}M"
            if val >= 1_000:
                return f"{val / 1_000:.0f}K"
            return str(val)

        kpi_data["students_impacted"] = {
            "value": format_large(students),
            "trend": get_trend(students, students_prior),
        }

        # Card 5: Schools Impacted (Distinct)
        schools_imp = len(reached_school_ids)
        schools_imp_prior = len(reached_prior_school_ids)
        kpi_data["schools_impacted"] = {
            "value": f"{schools_imp:,}",
            "trend": get_trend(schools_imp, schools_imp_prior),
        }

        # Card 6: Districts Covered
        districts = (
            curr_activities.filter(
                status__in=ACHIEVED_STATUSES, school__district__isnull=False
            )
            .values_list("school__district_id", flat=True)
            .distinct()
            .count()
        )
        districts_prior = (
            prior_activities.filter(
                status__in=ACHIEVED_STATUSES, school__district__isnull=False
            )
            .values_list("school__district_id", flat=True)
            .distinct()
            .count()
        )
        kpi_data["districts_covered"] = {
            "value": str(districts),
            "trend": get_trend(districts, districts_prior),
        }

        # Card 7: Clusters Covered
        clusters = (
            curr_activities.filter(
                status__in=ACHIEVED_STATUSES, school__cluster_id__isnull=False
            )
            .values_list("school__cluster_id", flat=True)
            .distinct()
            .count()
        )
        clusters_prior = (
            prior_activities.filter(
                status__in=ACHIEVED_STATUSES, school__cluster_id__isnull=False
            )
            .values_list("school__cluster_id", flat=True)
            .distinct()
            .count()
        )
        kpi_data["clusters_covered"] = {
            "value": str(clusters),
            "trend": get_trend(clusters, clusters_prior),
        }

        # Card 8: Total Activities Completed
        completed = curr_activities.filter(
            status__in=ACHIEVED_STATUSES, evidence_status="accepted"
        ).count()
        completed_prior = prior_activities.filter(
            status__in=ACHIEVED_STATUSES, evidence_status="accepted"
        ).count()
        kpi_data["activities_completed"] = {
            "value": f"{completed:,}",
            "trend": get_trend(completed, completed_prior),
        }

        # Card 9: SSA Average — cumulative for the FY, not quarter-scoped.
        # SSA assessments aren't logged with quarterly cadence like regular
        # activities, so quarter-restricting this (as with curr_ssa) produced
        # a false "N/A — no confirmed SSA yet" even when confirmed SSA data
        # existed elsewhere in the same FY — directly contradicting the SSA
        # Performance by Intervention chart on the same page, which is (and
        # remains) FY-scoped. Uses the same FY-cumulative convention as that
        # chart and the Core/Champion SSA cards below.
        ssa_avg_raw = ssa_qs.aggregate(a=Avg("average_score"))["a"]
        ssa_prev_fy = str(int(fy) - 1)
        ssa_avg_prior_raw = SsaRecord.objects.filter(
            deleted_at__isnull=True,
            fy=ssa_prev_fy,
            verification_status="confirmed",
            school_id__in=schools_qs,
        ).aggregate(a=Avg("average_score"))["a"]
        ssa_avg = ssa_avg_raw or 0
        if ssa_avg_raw and ssa_avg_prior_raw:
            ssa_diff = ssa_avg_raw - ssa_avg_prior_raw
            ssa_trend_text = (
                f"+{ssa_diff:.2f} vs FY{ssa_prev_fy}"
                if ssa_diff >= 0
                else f"{ssa_diff:.2f} vs FY{ssa_prev_fy}"
            )
        elif ssa_avg_raw:
            ssa_trend_text = None
        else:
            ssa_trend_text = "No confirmed SSA yet"
        kpi_data["ssa_average"] = {
            "value": f"{ssa_avg:.2f}" if ssa_avg > 0 else "N/A",
            "has_data": ssa_avg > 0,
            "trend": ssa_trend_text,
        }

        # Construct unified KPI strip items. `_kpi_trend` only renders a
        # trend badge when the underlying figure is a real +/- comparison —
        # "No target configured" / "No confirmed SSA yet" style honesty
        # messages fall through to no trend badge at all.
        def _kpi_trend(trend_text):
            if not trend_text or not (
                trend_text.startswith("+") or trend_text.startswith("-")
            ):
                return None
            return {
                "direction": "up" if trend_text.startswith("+") else "down",
                "value": trend_text.split()[0],
            }

        kpi_strip_items = [
            {
                "label": "Overall Target Achievement",
                "code": "target_achievement",
                "value": kpi_data["target_achievement"]["value"],
                "raw_value": achievement_pct,
                "helper": "vs last period"
                if kpi_data["target_achievement"]["has_target_data"]
                else "no target set for this FY",
                "icon": "target",
                "variant": "success",
                "trend": _kpi_trend(kpi_data["target_achievement"]["trend"]),
            },
            {
                "label": "Teachers Trained",
                "code": "teachers_trained",
                "value": kpi_data["teachers_trained"]["value"],
                "raw_value": teachers,
                "helper": "attended",
                "icon": "users",
                "variant": "info",
                "trend": _kpi_trend(kpi_data["teachers_trained"]["trend"]),
            },
            {
                "label": "School Leaders Trained",
                "code": "leaders_trained",
                "value": kpi_data["leaders_trained"]["value"],
                "raw_value": leaders,
                "helper": "attended",
                "icon": "target",
                "variant": "warning",
                "trend": _kpi_trend(kpi_data["leaders_trained"]["trend"]),
            },
            {
                "label": "Students Impacted",
                "code": "students_impacted",
                "value": kpi_data["students_impacted"]["value"],
                "raw_value": students,
                "helper": "total reached",
                "icon": "users",
                "variant": "blue",
                "trend": _kpi_trend(kpi_data["students_impacted"]["trend"]),
            },
            {
                "label": "Schools Impacted",
                "code": "schools_impacted",
                "value": kpi_data["schools_impacted"]["value"],
                "raw_value": schools_imp,
                "helper": "total reached",
                "icon": "school",
                "variant": "primary",
                "trend": _kpi_trend(kpi_data["schools_impacted"]["trend"]),
            },
            {
                "label": "Districts Covered",
                "code": "districts_covered",
                "value": kpi_data["districts_covered"]["value"],
                "raw_value": districts,
                "helper": "covered",
                "icon": "school",
                "variant": "danger",
                "trend": _kpi_trend(kpi_data["districts_covered"]["trend"]),
            },
            {
                "label": "Clusters Covered",
                "code": "clusters_covered",
                "value": kpi_data["clusters_covered"]["value"],
                "raw_value": clusters,
                "helper": "reached",
                "icon": "school",
                "variant": "purple",
                "trend": _kpi_trend(kpi_data["clusters_covered"]["trend"]),
            },
            {
                "label": "Total Activities Completed",
                "code": "activities_completed",
                "value": kpi_data["activities_completed"]["value"],
                "raw_value": completed,
                "helper": "completed work",
                "icon": "check",
                "variant": "success",
                "trend": _kpi_trend(kpi_data["activities_completed"]["trend"]),
            },
            {
                "label": "SSA Average",
                "code": "ssa_average",
                "value": kpi_data["ssa_average"]["value"],
                "raw_value": float(ssa_avg) if ssa_avg > 0 else 0,
                "helper": "average score" if ssa_avg > 0 else "no confirmed SSA yet",
                "icon": "chart",
                "variant": "blue",
                "trend": _kpi_trend(kpi_data["ssa_average"]["trend"]),
            },
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

        for m in months_fy:
            # `planned_month` is legacy and unpopulated on real/seeded
            # records — `month` (derived from scheduled_date) is the field
            # actually written by scheduling, so it's what's real here.
            pl_cnt = activities_qs.filter(month=m).count()
            ach_cnt = activities_qs.filter(
                month=m, status__in=ACHIEVED_STATUSES
            ).count()
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
        ssa_interventions = [
            (code, label, None) for code, label in SsaIntervention.choices
        ]
        ssa_scores_list = []
        for code, label, _default in ssa_interventions:
            avg_score = SsaScore.objects.filter(
                ssa_record__school__in=schools_qs, ssa_record__fy=fy, intervention=code
            ).aggregate(a=Avg("score"))["a"]
            val = float(avg_score) if avg_score is not None else 0.0
            ssa_scores_list.append(
                {
                    "code": code,
                    "label": label,
                    "value": round(val, 2),
                    "pct": round(val / 6.0 * 100) if avg_score is not None else 0,
                }
            )

        # 7. Target Achievement by District
        districts_perf = []
        all_districts = District.objects.all().order_by("name")
        if not scope.country_scope:
            if scope.district_ids:
                all_districts = all_districts.filter(id__in=scope.district_ids)
            elif scope.region_ids:
                all_districts = all_districts.filter(region_id__in=scope.region_ids)
            else:
                all_districts = all_districts.none()

        for dist in all_districts[:8]:
            planned_d = activities_qs.filter(school__district=dist).count()
            achieved_d = activities_qs.filter(
                school__district=dist, status__in=ACHIEVED_STATUSES
            ).count()
            pct_d = round((achieved_d / planned_d * 100)) if planned_d > 0 else 0

            status_color = "text-emerald-600 bg-emerald-50 border-emerald-200"
            bar_color = "bg-emerald-500"
            if pct_d >= 80:
                status_color = "text-emerald-600 bg-emerald-50"
                bar_color = "bg-emerald-500"
            elif pct_d >= 60:
                status_color = "text-blue-600 bg-blue-50"
                bar_color = "bg-blue-500"
            elif pct_d >= 40:
                status_color = "text-amber-600 bg-amber-50"
                bar_color = "bg-amber-500"
            else:
                status_color = "text-rose-600 bg-rose-50"
                bar_color = "bg-rose-500"

            districts_perf.append(
                {
                    "name": dist.name,
                    "pct": pct_d,
                    "planned": planned_d,
                    "achieved": achieved_d,
                    "status_color": status_color,
                    "bar_color": bar_color,
                }
            )

        # 8. Regional Performance (Map or list representation)
        regional_perf = []
        regions_list = Region.objects.all().order_by("name")
        for reg in regions_list:
            reg_schools = schools_qs.filter(region=reg)
            reg_acts = activities_qs.filter(school__region=reg)

            reg_ssa = ssa_qs.filter(school__region=reg).aggregate(
                a=Avg("average_score")
            )["a"]
            reg_ach = reg_acts.filter(status__in=ACHIEVED_STATUSES).count()
            reg_pl = reg_acts.count()
            reg_pct = round((reg_ach / reg_pl * 100)) if reg_pl > 0 else 0

            regional_perf.append(
                {
                    "id": reg.id,
                    "name": reg.name,
                    "ssa_avg": round(reg_ssa, 2) if reg_ssa else 0,
                    "has_ssa": reg_ssa is not None,
                    "pct": reg_pct,
                    "schools_count": reg_schools.count(),
                    "completed": reg_ach,
                }
            )

        # 9. Cluster Performance (Top 10 ranked table)
        cluster_perf = []
        clusters_list = Cluster.objects.all().order_by("name")
        if not scope.country_scope:
            if scope.cluster_ids:
                clusters_list = clusters_list.filter(id__in=scope.cluster_ids)
            elif scope.region_ids:
                clusters_list = clusters_list.filter(region_id__in=scope.region_ids)
            else:
                clusters_list = clusters_list.none()
        top_clusters = list(clusters_list[:10])
        top_cluster_ids = [cl.id for cl in top_clusters]
        intervention_labels = dict(SsaIntervention.choices)

        # One aggregate query for every intervention average across all
        # top-ranked clusters, instead of N+1 lookups per cluster.
        score_rows = (
            SsaScore.objects.filter(
                ssa_record__school__cluster_id__in=top_cluster_ids,
                ssa_record__fy=fy,
                ssa_record__verification_status="confirmed",
            )
            .values("ssa_record__school__cluster_id", "intervention")
            .annotate(avg_score=Avg("score"))
        )
        cluster_intervention_avgs: dict[str, dict[str, float]] = defaultdict(dict)
        for row in score_rows:
            cluster_intervention_avgs[row["ssa_record__school__cluster_id"]][
                row["intervention"]
            ] = row["avg_score"]

        for i, cl in enumerate(top_clusters):
            cl_ssa = ssa_qs.filter(school__cluster_id=cl.id).aggregate(
                a=Avg("average_score")
            )["a"]
            cl_curr_acts = curr_activities.filter(school__cluster_id=cl.id)
            cl_prior_acts = prior_activities.filter(school__cluster_id=cl.id)
            cl_acts = activities_qs.filter(school__cluster_id=cl.id)

            train_cnt = cl_acts.filter(activity_type__in=TRAINING_TYPES).count()
            visit_cnt = cl_acts.filter(activity_type__in=VISIT_TYPES).count()

            intervention_avgs = cluster_intervention_avgs.get(cl.id, {})
            if intervention_avgs:
                best_code = max(intervention_avgs, key=intervention_avgs.get)
                worst_code = min(intervention_avgs, key=intervention_avgs.get)
                best_intervention = intervention_labels.get(best_code, best_code)
                worst_intervention = intervention_labels.get(worst_code, worst_code)
            else:
                best_intervention = "—"
                worst_intervention = "—"

            curr_planned = cl_curr_acts.count()
            prior_planned = cl_prior_acts.count()
            trend = None
            if curr_planned and prior_planned:
                curr_pct = (
                    cl_curr_acts.filter(status__in=ACHIEVED_STATUSES).count()
                    / curr_planned
                    * 100
                )
                prior_pct = (
                    cl_prior_acts.filter(status__in=ACHIEVED_STATUSES).count()
                    / prior_planned
                    * 100
                )
                trend = "up" if curr_pct >= prior_pct else "down"

            cluster_perf.append(
                {
                    "rank": i + 1,
                    "id": cl.id,
                    "name": cl.name,
                    "ssa_avg": f"{cl_ssa:.2f}" if cl_ssa else "—",
                    "best_intervention": best_intervention,
                    "worst_intervention": worst_intervention,
                    "trainings": train_cnt,
                    "visits": visit_cnt,
                    "trend": trend,
                }
            )

        # 10. Impact Summary
        # Schools Improved: count schools with delta > +0.05 compared to prior year
        # Compare SSA baseline scores
        improved_cnt = 0
        all_schools = schools_qs.values_list("id", flat=True)
        prev_fy = str(int(fy) - 1)
        for sid in all_schools:
            curr_score = SsaRecord.objects.filter(
                school_id=sid, fy=fy, verification_status="confirmed"
            ).aggregate(a=Avg("average_score"))["a"]
            prev_score = SsaRecord.objects.filter(
                school_id=sid, fy=prev_fy, verification_status="confirmed"
            ).aggregate(a=Avg("average_score"))["a"]
            if curr_score and prev_score and (curr_score - prev_score > 0.05):
                improved_cnt += 1

        impact_summary = {
            "teachers_trained": teachers,
            "leaders_trained": leaders,
            "students_impacted": students,
            "schools_improved": improved_cnt,
        }

        # 11. Activity Tracking Section
        activity_tracking = {
            "school_visits": curr_activities.filter(
                activity_type__in=VISIT_TYPES
            ).count(),
            "cluster_trainings": curr_activities.filter(
                activity_type__in=TRAINING_TYPES
            ).count(),
            "cluster_meetings": curr_activities.filter(
                activity_type=CLUSTER_MEETING_TYPE
            ).count(),
            "ssa_support": curr_activities.filter(activity_type="ssa_activity").count(),
            "partner_activities": curr_activities.filter(
                delivery_type="partner"
            ).count(),
            "project_activities": curr_activities.filter(
                activity_type="project_activity"
            ).count(),
        }

        # 12. Staff & Partner Performance — current vs prior quarter (the same
        # period window driving the rest of the dashboard's comparisons).
        staff_curr = curr_activities.filter(
            delivery_type="staff", status__in=ACHIEVED_STATUSES
        ).count()
        staff_prior = prior_activities.filter(
            delivery_type="staff", status__in=ACHIEVED_STATUSES
        ).count()
        partner_curr = curr_activities.filter(
            delivery_type="partner", status__in=ACHIEVED_STATUSES
        ).count()
        partner_prior = prior_activities.filter(
            delivery_type="partner", status__in=ACHIEVED_STATUSES
        ).count()

        staff_partner_chart = {
            "labels": [prior_q, quarter],
            "staff": [staff_prior, staff_curr],
            "partner": [partner_prior, partner_curr],
        }

        # Leaderboard table — ranked by activities completed this FY, scoped
        # to the same staff visibility as the rest of the dashboard. Staff
        # with zero scheduled work are excluded rather than credited with a
        # fabricated 100% achievement.
        staff_qs = StaffProfile.objects.filter(deleted_at__isnull=True).select_related(
            "user"
        )
        if not scope.country_scope:
            visible_staff_ids = set(scope.staff_ids) | set(scope.supervised_staff_ids)
            staff_qs = (
                staff_qs.filter(id__in=visible_staff_ids)
                if visible_staff_ids
                else staff_qs.none()
            )

        leaderboard = []
        for st in staff_qs:
            # Activity.responsible_staff_id stores the User id, not the
            # StaffProfile id — filter on st.user_id, not st.id.
            planned_cnt = activities_qs.filter(responsible_staff_id=st.user_id).count()
            if planned_cnt == 0:
                continue
            completed_cnt = activities_qs.filter(
                responsible_staff_id=st.user_id, status__in=ACHIEVED_STATUSES
            ).count()
            leaderboard.append(
                {
                    "name": st.user.name,
                    "role": st.title
                    or getattr(st.user, "active_role", None)
                    or "Staff",
                    "activities": completed_cnt,
                    "pct": round((completed_cnt / planned_cnt * 100)),
                }
            )
        leaderboard.sort(key=lambda row: row["activities"], reverse=True)
        leaderboard = leaderboard[:5]

        # 13. Core & Champion School Performance (scoped to the same school
        # set as the rest of the dashboard, not the whole country).
        core_school_ids = schools_qs.filter(school_type="core").values_list(
            "id", flat=True
        )
        champion_school_ids = schools_qs.filter(school_type="champion").values_list(
            "id", flat=True
        )
        prev_fy = str(int(fy) - 1)

        core_ssa_avg = SsaRecord.objects.filter(
            school_id__in=core_school_ids, fy=fy, verification_status="confirmed"
        ).aggregate(a=Avg("average_score"))["a"]
        core_ssa_prior = SsaRecord.objects.filter(
            school_id__in=core_school_ids,
            fy=prev_fy,
            verification_status="confirmed",
        ).aggregate(a=Avg("average_score"))["a"]

        champion_ssa_avg = SsaRecord.objects.filter(
            school_id__in=champion_school_ids,
            fy=fy,
            verification_status="confirmed",
        ).aggregate(a=Avg("average_score"))["a"]
        champion_ssa_prior = SsaRecord.objects.filter(
            school_id__in=champion_school_ids,
            fy=prev_fy,
            verification_status="confirmed",
        ).aggregate(a=Avg("average_score"))["a"]

        def _ssa_trend(curr, prev):
            if curr is None or prev is None:
                return None
            diff = curr - prev
            return (
                f"+{diff:.2f} vs FY{prev_fy}"
                if diff >= 0
                else f"{diff:.2f} vs FY{prev_fy}"
            )

        core_champion = {
            "core_count": core_school_ids.count(),
            "core_ssa": round(core_ssa_avg, 2) if core_ssa_avg is not None else None,
            "core_ssa_trend": _ssa_trend(core_ssa_avg, core_ssa_prior),
            "champion_count": champion_school_ids.count(),
            "champion_ssa": round(champion_ssa_avg, 2)
            if champion_ssa_avg is not None
            else None,
            "champion_ssa_trend": _ssa_trend(champion_ssa_avg, champion_ssa_prior),
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

        # Risk 4: High-risk districts (target achievement < 60%). Districts
        # with zero scheduled activity are excluded — "no visibility" is not
        # the same signal as "underperforming".
        high_risk_districts = sum(
            1 for dp in districts_perf if dp["planned"] > 0 and dp["pct"] < 60
        )

        # Risk 5: Clusters needing attention (SSA avg < 4.0; clusters with no
        # confirmed SSA yet are excluded rather than treated as failing)
        clusters_attn = 0
        for cp in cluster_perf:
            if cp["ssa_avg"] != "—" and float(cp["ssa_avg"]) < 4.0:
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
                "color": "bg-amber-50 border-amber-200 text-amber-700",
            },
            {
                "key": "not_trained",
                "label": "Schools not trained",
                "count": not_trained_count,
                "description": "No training this quarter.",
                "icon": "🎓",
                "color": "bg-blue-50 border-blue-200 text-blue-700",
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

        # Recommended focus — the real weakest SSA intervention and lowest-
        # achieving district in the current scope, used to replace any
        # generic/static "recommended strategy" copy with an honest pointer.
        scored_interventions = [s for s in ssa_scores_list if s["value"] > 0]
        weakest_intervention = (
            min(scored_interventions, key=lambda s: s["value"])
            if scored_interventions
            else None
        )
        districts_with_data = [d for d in districts_perf if d["planned"] > 0]
        weakest_district = (
            min(districts_with_data, key=lambda d: d["pct"])
            if districts_with_data
            else None
        )

        # ── ApexCharts option dicts (server-computed, per the design contract —
        # charts never compute data in JS; they only mount `data-apex-config`). ──
        performance_chart_has_data = any(planned_series) or any(achieved_series)
        performance_chart_options = {
            "chart": {
                "type": "line",
                "height": 260,
                "toolbar": {"show": False},
                "fontFamily": "inherit",
            },
            "series": [
                {"name": "Planned", "type": "column", "data": planned_series},
                {"name": "Achieved", "type": "column", "data": achieved_series},
                {"name": "Achievement %", "type": "line", "data": ach_pct_series},
            ],
            "stroke": {"width": [0, 0, 3], "curve": "smooth"},
            "colors": ["#94a3b8", "#3b82f6", "#10b981"],
            "plotOptions": {"bar": {"columnWidth": "55%", "borderRadius": 3}},
            "xaxis": {
                "categories": labels_months,
                "axisBorder": {"show": False},
                "axisTicks": {"show": False},
            },
            "yaxis": [
                {"title": {"text": "Activities"}},
                {"opposite": True, "max": 100, "title": {"text": "Achievement %"}},
            ],
            "grid": {"borderColor": "#f1f5f9"},
            "legend": {"position": "top", "horizontalAlign": "right"},
            "dataLabels": {"enabled": False},
            "tooltip": {"theme": "light"},
        }

        ssa_chart_has_data = any(item["value"] > 0 for item in ssa_scores_list)
        ssa_chart_options = {
            "chart": {
                "type": "bar",
                "height": 280,
                "toolbar": {"show": False},
                "fontFamily": "inherit",
            },
            "series": [
                {
                    "name": "Avg score (of 6.0)",
                    "data": [item["value"] for item in ssa_scores_list],
                }
            ],
            "xaxis": {
                "categories": [item["label"] for item in ssa_scores_list],
                "max": 6,
            },
            "plotOptions": {
                "bar": {"horizontal": True, "borderRadius": 3, "barHeight": "60%"}
            },
            "colors": ["#3b82f6"],
            "grid": {"borderColor": "#f1f5f9"},
            "dataLabels": {"enabled": True},
            "legend": {"show": False},
            "tooltip": {"theme": "light"},
        }

        regional_chart_has_data = any(
            r["pct"] or r["schools_count"] for r in regional_perf
        )
        regional_chart_options = {
            "chart": {
                "type": "bar",
                "height": 240,
                "toolbar": {"show": False},
                "fontFamily": "inherit",
            },
            "series": [
                {
                    "name": "Target achievement %",
                    "data": [r["pct"] for r in regional_perf],
                }
            ],
            "xaxis": {"categories": [r["name"] for r in regional_perf]},
            "plotOptions": {"bar": {"borderRadius": 4, "columnWidth": "45%"}},
            "colors": ["#0ea5a4"],
            "grid": {"borderColor": "#f1f5f9"},
            "dataLabels": {"enabled": False},
            "legend": {"show": False},
            "tooltip": {"theme": "light"},
        }

        staff_partner_has_data = any(staff_partner_chart["staff"]) or any(
            staff_partner_chart["partner"]
        )
        staff_partner_chart_options = {
            "chart": {
                "type": "bar",
                "height": 220,
                "toolbar": {"show": False},
                "fontFamily": "inherit",
            },
            "series": [
                {"name": "Staff (CCEO)", "data": staff_partner_chart["staff"]},
                {"name": "Partner", "data": staff_partner_chart["partner"]},
            ],
            "xaxis": {"categories": staff_partner_chart["labels"]},
            "plotOptions": {"bar": {"columnWidth": "45%", "borderRadius": 3}},
            "colors": ["#3b82f6", "#0ea5a4"],
            "grid": {"borderColor": "#f1f5f9"},
            "legend": {"position": "top", "horizontalAlign": "right"},
            "dataLabels": {"enabled": False},
            "tooltip": {"theme": "light"},
        }

        return {
            "filters": {
                "selected_fy": fy,
                "selected_quarter": quarter,
                "selected_region": region_id,
                "selected_district": district_id,
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
            "performance_chart_options": performance_chart_options,
            "performance_chart_has_data": performance_chart_has_data,
            "ssa_performance": ssa_scores_list,
            "ssa_chart_options": ssa_chart_options,
            "ssa_chart_has_data": ssa_chart_has_data,
            "target_by_district": districts_perf,
            "regional_performance": regional_perf,
            "regional_chart_options": regional_chart_options,
            "regional_chart_has_data": regional_chart_has_data,
            "cluster_performance": cluster_perf,
            "impact_summary": impact_summary,
            "activity_tracking": activity_tracking,
            "staff_partner_performance": {
                "chart": staff_partner_chart,
                "leaderboard": leaderboard,
            },
            "staff_partner_chart_options": staff_partner_chart_options,
            "staff_partner_has_data": staff_partner_has_data,
            "core_champion": core_champion,
            "donor_snapshot": donor_snapshot,
            "insights": insights,
            "weakest_intervention": weakest_intervention,
            "weakest_district": weakest_district,
            "total_staff_count": staff_qs.count(),
            "as_of_date": timezone.now().strftime("%B %d, %Y"),
        }
