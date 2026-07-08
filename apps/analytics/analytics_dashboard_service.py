"""Analytics dashboard service — compile role-scoped, filter-aware metrics for the command center."""
from __future__ import annotations

import datetime
from django.db.models import Avg, Q, Sum
from django.utils import timezone

from apps.core.fy import get_operational_fy
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
VISIT_TYPES = ("school_visit", "follow_up_visit", "coaching_visit", "in_school_support", "core_visit")
TRAINING_TYPES = ("training", "school_improvement_training", "cluster_training", "core_training")
CLUSTER_MEETING_TYPE = "cluster_meeting"

class AnalyticsDashboardService:
    @staticmethod
    def get_analytics_data(principal, filters: dict) -> dict:
        # 1. Parse active filters
        fy = filters.get("fy") or get_operational_fy()
        quarter = filters.get("quarter") or "Q2"
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
        
        # 2. Base Querysets
        schools_qs = School.objects.filter(deleted_at__isnull=True)
        activities_qs = Activity.objects.filter(deleted_at__isnull=True, fy=fy)
        ssa_qs = SsaRecord.objects.filter(deleted_at__isnull=True, fy=fy, verification_status="confirmed")
        
        # Apply role-based visibility scoping
        if not scope.country_scope:
            if scope.school_ids:
                schools_qs = schools_qs.filter(id__in=scope.school_ids)
                ssa_qs = ssa_qs.filter(school_id__in=scope.school_ids)
            else:
                schools_qs = schools_qs.none()
                ssa_qs = ssa_qs.none()
                
            if scope.staff_ids:
                activities_qs = activities_qs.filter(
                    Q(responsible_staff_id__in=scope.staff_ids) | Q(assigned_partner_id__in=scope.staff_ids)
                )
            elif scope.partner_ids:
                activities_qs = activities_qs.filter(assigned_partner_id__in=scope.partner_ids)
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
        # Staff Owner
        if staff_id:
            activities_qs = activities_qs.filter(responsible_staff_id=staff_id)
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
        # Search
        if search_q:
            schools_qs = schools_qs.filter(Q(name__icontains=search_q) | Q(school_id__icontains=search_q))
            activities_qs = activities_qs.filter(
                Q(school__name__icontains=search_q) | 
                Q(cluster__name__icontains=search_q) | 
                Q(responsible_staff__user__name__icontains=search_q)
            )
            ssa_qs = ssa_qs.filter(school__name__icontains=search_q)
            
        # Quarter restriction for current period metrics (except cumulative metrics)
        curr_activities = activities_qs.filter(quarter=quarter)
        curr_ssa = ssa_qs.filter(quarter=quarter)
        
        # Prior period matching
        prior_q = {"Q2": "Q1", "Q3": "Q2", "Q4": "Q3", "Q1": "Q4"}.get(quarter, "Q1")
        prior_activities = activities_qs.filter(quarter=prior_q)
        prior_ssa = ssa_qs.filter(quarter=prior_q)
        
        # 4. Calculate KPI Cards (Current vs Prior Q)
        kpi_data = {}
        
        # Helper to format trend text
        def get_trend(curr, prev, mode="pct"):
            if prev == 0:
                return f"+{curr} vs {prior_q}" if curr > 0 else f"0 vs {prior_q}"
            if mode == "pp":
                diff = curr - prev
                return f"+{diff:.0f}pp vs {prior_q}" if diff >= 0 else f"{diff:.0f}pp vs {prior_q}"
            else:
                pct = ((curr - prev) / prev) * 100
                return f"+{pct:.0f}% vs {prior_q}" if pct >= 0 else f"{pct:.0f}% vs {prior_q}"
                
        # Card 1: Target Achievement
        # Count achieved activities in quarter
        achieved_q = curr_activities.filter(status__in=ACHIEVED_STATUSES, evidence_status="accepted").count()
        achieved_prior = prior_activities.filter(status__in=ACHIEVED_STATUSES, evidence_status="accepted").count()
        
        # Targets sum
        targets_sum = TargetSetting.objects.filter(fy=fy, is_active=True).aggregate(s=Sum("target_value"))["s"] or 0
        if targets_sum == 0:
            # Fallback to StaffTargetProfiles
            targets_sum = StaffTargetProfile.objects.filter(fy=fy).aggregate(
                v=Sum("visits_target"), t=Sum("trainings_target")
            )
            targets_sum = (targets_sum["v"] or 0) + (targets_sum["t"] or 0)
        if targets_sum == 0:
            # High-level fallback to planned count (a genuine zero renders as zero)
            targets_sum = activities_qs.count()
            
        # Target for this quarter is roughly 25% of annual targets
        q_target = max(1, round(targets_sum / 4))
        achievement_pct = round((achieved_q / q_target) * 100)
        achievement_prior_pct = round((achieved_prior / q_target) * 100)
        
        kpi_data["target_achievement"] = {
            "value": f"{achievement_pct}%",
            "trend": get_trend(achievement_pct, achievement_prior_pct, "pp"),
            "points": [],
            "class": "text-emerald-600" if achievement_pct >= 90 else ("text-amber-600" if achievement_pct >= 70 else "text-rose-600")
        }
        
        # Card 2: Teachers Trained
        teachers = curr_activities.filter(status__in=ACHIEVED_STATUSES).aggregate(s=Sum("teachers_attended"))["s"] or 0
        teachers_prior = prior_activities.filter(status__in=ACHIEVED_STATUSES).aggregate(s=Sum("teachers_attended"))["s"] or 0
        kpi_data["teachers_trained"] = {
            "value": f"{teachers:,}",
            "trend": get_trend(teachers, teachers_prior),
            "points": [],
        }
        
        # Card 3: School Leaders Trained
        leaders = curr_activities.filter(status__in=ACHIEVED_STATUSES).aggregate(s=Sum("leaders_attended"))["s"] or 0
        leaders_prior = prior_activities.filter(status__in=ACHIEVED_STATUSES).aggregate(s=Sum("leaders_attended"))["s"] or 0
        kpi_data["leaders_trained"] = {
            "value": f"{leaders:,}",
            "trend": get_trend(leaders, leaders_prior),
            "points": [],
        }
        
        # Card 4: Students Impacted (Sum enrollment of reached schools, distinct)
        reached_school_ids = curr_activities.filter(status__in=ACHIEVED_STATUSES).values_list("school_id", flat=True).distinct()
        students = School.objects.filter(id__in=reached_school_ids).aggregate(s=Sum("enrollment"))["s"] or 0
        
        reached_prior_school_ids = prior_activities.filter(status__in=ACHIEVED_STATUSES).values_list("school_id", flat=True).distinct()
        students_prior = School.objects.filter(id__in=reached_prior_school_ids).aggregate(s=Sum("enrollment"))["s"] or 0
        
        def format_large(val):
            if val >= 1_000_000:
                return f"{val / 1_000_000:.2f}M"
            if val >= 1_000:
                return f"{val / 1_000:.0f}K"
            return str(val)
            
        kpi_data["students_impacted"] = {
            "value": format_large(students),
            "trend": get_trend(students, students_prior),
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
        districts = curr_activities.filter(status__in=ACHIEVED_STATUSES, school__district__isnull=False).values_list("school__district_id", flat=True).distinct().count()
        districts_prior = prior_activities.filter(status__in=ACHIEVED_STATUSES, school__district__isnull=False).values_list("school__district_id", flat=True).distinct().count()
        kpi_data["districts_covered"] = {
            "value": str(districts),
            "trend": get_trend(districts, districts_prior),
            "points": [],
        }
        
        # Card 7: Clusters Covered
        clusters = curr_activities.filter(status__in=ACHIEVED_STATUSES, school__cluster_id__isnull=False).values_list("school__cluster_id", flat=True).distinct().count()
        clusters_prior = prior_activities.filter(status__in=ACHIEVED_STATUSES, school__cluster_id__isnull=False).values_list("school__cluster_id", flat=True).distinct().count()
        kpi_data["clusters_covered"] = {
            "value": str(clusters),
            "trend": get_trend(clusters, clusters_prior),
            "points": [],
        }
        
        # Card 8: Total Activities Completed
        completed = curr_activities.filter(status__in=ACHIEVED_STATUSES, evidence_status="accepted").count()
        completed_prior = prior_activities.filter(status__in=ACHIEVED_STATUSES, evidence_status="accepted").count()
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
            "trend": f"+{ssa_diff:.2f} vs {prior_q}" if ssa_diff >= 0 else f"{ssa_diff:.2f} vs {prior_q}",
            "points": [],
        }

        # Construct unified KPI strip items
        kpi_strip_items = [
            {
                "label": "Overall Target Achievement",
                "value": kpi_data["target_achievement"]["value"],
                "raw_value": achievement_pct,
                "helper": "vs last period",
                "icon": "target",
                "variant": "success",
                "trend": {
                    "direction": "up" if "+" in kpi_data["target_achievement"]["trend"] else "down",
                    "value": kpi_data["target_achievement"]["trend"].split()[0] if kpi_data["target_achievement"]["trend"] else ""
                }
            },
            {
                "label": "Teachers Trained",
                "value": kpi_data["teachers_trained"]["value"],
                "raw_value": teachers,
                "helper": "attended",
                "icon": "users",
                "variant": "info",
                "trend": {
                    "direction": "up" if "+" in kpi_data["teachers_trained"]["trend"] else "down",
                    "value": kpi_data["teachers_trained"]["trend"].split()[0] if kpi_data["teachers_trained"]["trend"] else ""
                }
            },
            {
                "label": "School Leaders Trained",
                "value": kpi_data["leaders_trained"]["value"],
                "raw_value": leaders,
                "helper": "attended",
                "icon": "target",
                "variant": "warning",
                "trend": {
                    "direction": "up" if "+" in kpi_data["leaders_trained"]["trend"] else "down",
                    "value": kpi_data["leaders_trained"]["trend"].split()[0] if kpi_data["leaders_trained"]["trend"] else ""
                }
            },
            {
                "label": "Students Impacted",
                "value": kpi_data["students_impacted"]["value"],
                "raw_value": students,
                "helper": "total reached",
                "icon": "users",
                "variant": "blue",
                "trend": {
                    "direction": "up" if "+" in kpi_data["students_impacted"]["trend"] else "down",
                    "value": kpi_data["students_impacted"]["trend"].split()[0] if kpi_data["students_impacted"]["trend"] else ""
                }
            },
            {
                "label": "Schools Impacted",
                "value": kpi_data["schools_impacted"]["value"],
                "raw_value": schools_imp,
                "helper": "total reached",
                "icon": "school",
                "variant": "primary",
                "trend": {
                    "direction": "up" if "+" in kpi_data["schools_impacted"]["trend"] else "down",
                    "value": kpi_data["schools_impacted"]["trend"].split()[0] if kpi_data["schools_impacted"]["trend"] else ""
                }
            },
            {
                "label": "Districts Covered",
                "value": kpi_data["districts_covered"]["value"],
                "raw_value": districts,
                "helper": "covered",
                "icon": "school",
                "variant": "danger",
                "trend": {
                    "direction": "up" if "+" in kpi_data["districts_covered"]["trend"] else "down",
                    "value": kpi_data["districts_covered"]["trend"].split()[0] if kpi_data["districts_covered"]["trend"] else ""
                }
            },
            {
                "label": "Clusters Covered",
                "value": kpi_data["clusters_covered"]["value"],
                "raw_value": clusters,
                "helper": "reached",
                "icon": "school",
                "variant": "purple",
                "trend": {
                    "direction": "up" if "+" in kpi_data["clusters_covered"]["trend"] else "down",
                    "value": kpi_data["clusters_covered"]["trend"].split()[0] if kpi_data["clusters_covered"]["trend"] else ""
                }
            },
            {
                "label": "Total Activities Completed",
                "value": kpi_data["activities_completed"]["value"],
                "raw_value": completed,
                "helper": "completed work",
                "icon": "check",
                "variant": "success",
                "trend": {
                    "direction": "up" if "+" in kpi_data["activities_completed"]["trend"] else "down",
                    "value": kpi_data["activities_completed"]["trend"].split()[0] if kpi_data["activities_completed"]["trend"] else ""
                }
            },
            {
                "label": "SSA Average",
                "value": kpi_data["ssa_average"]["value"],
                "raw_value": float(ssa_avg) if ssa_avg > 0 else None,
                "helper": "average score",
                "icon": "chart",
                "variant": "blue",
                "trend": {
                    "direction": "up" if "+" in kpi_data["ssa_average"]["trend"] else "down",
                    "value": kpi_data["ssa_average"]["trend"].split()[0] if kpi_data["ssa_average"]["trend"] else ""
                }
            }
        ]
        
        # 5. Performance Overview Chart Series (Grouped months)
        # Months in fiscal year order: Oct, Nov, Dec, Jan, Feb, Mar, Apr, May, Jun, Jul, Aug, Sep
        months_fy = [10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9]
        labels_months = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep"]
        planned_series = []
        achieved_series = []
        ach_pct_series = []
        
        for m in months_fy:
            pl_cnt = activities_qs.filter(planned_month=m).count()
            ach_cnt = activities_qs.filter(planned_month=m, status__in=ACHIEVED_STATUSES).count()
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
            ssa_scores_list.append({
                "code": code,
                "label": label,
                "value": round(val, 2),
                "pct": round(val / 6.0 * 100) if avg_score is not None else 0,
            })
            
        # 7. Target Achievement by District
        districts_perf = []
        all_districts = District.objects.all().order_by("name")
        if not scope.country_scope and scope.district_ids:
            all_districts = all_districts.filter(id__in=scope.district_ids)
            
        for dist in all_districts[:8]:
            planned_d = activities_qs.filter(school__district=dist).count()
            achieved_d = activities_qs.filter(school__district=dist, status__in=ACHIEVED_STATUSES).count()
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
                
            districts_perf.append({
                "name": dist.name,
                "pct": pct_d,
                "planned": planned_d,
                "achieved": achieved_d,
                "status_color": status_color,
                "bar_color": bar_color,
            })
            
        # 8. Regional Performance (Map or list representation)
        regional_perf = []
        regions_list = Region.objects.all().order_by("name")
        for reg in regions_list:
            reg_schools = schools_qs.filter(region=reg)
            reg_acts = activities_qs.filter(school__region=reg)
            
            reg_ssa = SsaRecord.objects.filter(school__region=reg, fy=fy, verification_status="confirmed").aggregate(a=Avg("average_score"))["a"]
            reg_ach = reg_acts.filter(status__in=ACHIEVED_STATUSES).count()
            reg_pl = reg_acts.count()
            reg_pct = round((reg_ach / reg_pl * 100)) if reg_pl > 0 else 0
            
            regional_perf.append({
                "id": reg.id,
                "name": reg.name,
                "ssa_avg": round(reg_ssa, 2) if reg_ssa is not None else None,
                "pct": reg_pct,
                "schools_count": reg_schools.count(),
                "completed": reg_ach,
            })
            
        # 9. Cluster Performance (Top 10 ranked table)
        intervention_labels = dict(SsaIntervention.choices)
        cluster_perf = []
        clusters_list = Cluster.objects.all()
        for i, cl in enumerate(clusters_list[:10]):
            cl_schools = School.objects.filter(cluster_id=cl.id)
            cl_ssa = SsaRecord.objects.filter(school__cluster_id=cl.id, fy=fy, verification_status="confirmed").aggregate(a=Avg("average_score"))["a"]
            cl_acts = activities_qs.filter(school__cluster_id=cl.id)

            train_cnt = cl_acts.filter(activity_type__in=TRAINING_TYPES).count()
            visit_cnt = cl_acts.filter(activity_type__in=VISIT_TYPES).count()

            # Real best/worst intervention, derived the same way as the SSA
            # Performance by Intervention section (SsaScore per-intervention averages).
            cl_intervention_scores = list(
                SsaScore.objects.filter(ssa_record__school__cluster_id=cl.id, ssa_record__fy=fy)
                .values("intervention")
                .annotate(avg=Avg("score"))
            )
            if cl_intervention_scores:
                best_row = max(cl_intervention_scores, key=lambda r: r["avg"])
                worst_row = min(cl_intervention_scores, key=lambda r: r["avg"])
                best_intervention = intervention_labels.get(best_row["intervention"], best_row["intervention"])
                worst_intervention = intervention_labels.get(worst_row["intervention"], worst_row["intervention"])
            else:
                best_intervention = "—"
                worst_intervention = "—"

            # Real trend: compare this cluster's current-FY SSA average against
            # the prior FY (same comparison basis used for Impact Summary below).
            prev_fy = str(int(fy) - 1)
            cl_ssa_prev = SsaRecord.objects.filter(
                school__cluster_id=cl.id, fy=prev_fy, verification_status="confirmed"
            ).aggregate(a=Avg("average_score"))["a"]
            if cl_ssa is not None and cl_ssa_prev is not None and cl_ssa != cl_ssa_prev:
                cl_trend = "up" if cl_ssa > cl_ssa_prev else "down"
            else:
                cl_trend = None

            cluster_perf.append({
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
            })
            
        # 10. Impact Summary
        # Schools Improved: count schools with delta > +0.05 compared to prior year
        # Compare SSA baseline scores
        improved_cnt = 0
        all_schools = schools_qs.values_list("id", flat=True)
        for sid in all_schools:
            curr_score = SsaRecord.objects.filter(school_id=sid, fy=fy, verification_status="confirmed").aggregate(a=Avg("average_score"))["a"]
            prev_fy = str(int(fy) - 1)
            prev_score = SsaRecord.objects.filter(school_id=sid, fy=prev_fy, verification_status="confirmed").aggregate(a=Avg("average_score"))["a"]
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
            "school_visits": curr_activities.filter(activity_type__in=VISIT_TYPES).count(),
            "cluster_trainings": curr_activities.filter(activity_type__in=TRAINING_TYPES).count(),
            "cluster_meetings": curr_activities.filter(activity_type=CLUSTER_MEETING_TYPE).count(),
            "ssa_support": curr_activities.filter(activity_type="ssa_activity").count(),
            "partner_activities": curr_activities.filter(delivery_type="partner").count(),
            "project_activities": curr_activities.filter(activity_type="project_activity").count(),
        }
        
        # 12. Staff & Partner Performance
        # Group achievements by Quarter
        staff_q1 = activities_qs.filter(quarter="Q1", delivery_type="staff", status__in=ACHIEVED_STATUSES).count()
        staff_q2 = activities_qs.filter(quarter="Q2", delivery_type="staff", status__in=ACHIEVED_STATUSES).count()
        partner_q1 = activities_qs.filter(quarter="Q1", delivery_type="partner", status__in=ACHIEVED_STATUSES).count()
        partner_q2 = activities_qs.filter(quarter="Q2", delivery_type="partner", status__in=ACHIEVED_STATUSES).count()
        
        # Overall achievement rate (achieved / planned) per delivery channel —
        # this is the real figure the bar comparison in the template renders.
        staff_planned_total = activities_qs.filter(delivery_type="staff").count()
        staff_achieved_total = activities_qs.filter(delivery_type="staff", status__in=ACHIEVED_STATUSES).count()
        staff_pct = round(staff_achieved_total / staff_planned_total * 100) if staff_planned_total > 0 else 0

        partner_planned_total = activities_qs.filter(delivery_type="partner").count()
        partner_achieved_total = activities_qs.filter(delivery_type="partner", status__in=ACHIEVED_STATUSES).count()
        partner_pct = round(partner_achieved_total / partner_planned_total * 100) if partner_planned_total > 0 else 0

        staff_partner_chart = {
            "staff": [staff_q1, staff_q2],
            "partner": [partner_q1, partner_q2],
            "staff_pct": staff_pct,
            "partner_pct": partner_pct,
        }
        
        # Leaderboard table
        leaderboard = []
        active_staff = StaffProfile.objects.filter(deleted_at__isnull=True).select_related("user")
        for st in active_staff[:5]:
            completed_cnt = activities_qs.filter(responsible_staff_id=st.id, status__in=ACHIEVED_STATUSES).count()
            planned_cnt = activities_qs.filter(responsible_staff_id=st.id).count()
            ach_pct = round((completed_cnt / planned_cnt * 100)) if planned_cnt > 0 else 0
            
            leaderboard.append({
                "name": st.user.name,
                "role": st.title or "CCEO",
                "activities": completed_cnt,
                "pct": ach_pct,
            })
            
        # 13. Core & Champion School Performance
        core_schools_count = schools_qs.filter(school_type="core").count()
        core_ssa_avg = SsaRecord.objects.filter(school__school_type="core", fy=fy, verification_status="confirmed").aggregate(a=Avg("average_score"))["a"]

        champion_schools_count = schools_qs.filter(school_type="champion").count()
        champion_ssa_avg = SsaRecord.objects.filter(school__school_type="champion", fy=fy, verification_status="confirmed").aggregate(a=Avg("average_score"))["a"]

        core_champion = {
            "core_count": core_schools_count,
            "core_ssa": round(core_ssa_avg, 2) if core_ssa_avg is not None else None,
            "champion_count": champion_schools_count,
            "champion_ssa": round(champion_ssa_avg, 2) if champion_ssa_avg is not None else None,
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
        no_ssa_count = schools_qs.filter(current_fy_ssa_status__in=["not_done", "scheduled"]).count()
        # Risk 2: Schools not visited in last 60 days
        sixty_days_ago = timezone.now() - datetime.timedelta(days=60)
        visited_schools = Activity.objects.filter(
            deleted_at__isnull=True, activity_type__in=VISIT_TYPES, 
            status__in=ACHIEVED_STATUSES, scheduled_date__gte=sixty_days_ago
        ).values_list("school_id", flat=True).distinct()
        not_visited_count = schools_qs.exclude(id__in=visited_schools).count()
        
        # Risk 3: Schools not trained this quarter
        trained_schools = Activity.objects.filter(
            deleted_at__isnull=True, activity_type__in=TRAINING_TYPES, 
            status__in=ACHIEVED_STATUSES, quarter=quarter
        ).values_list("school_id", flat=True).distinct()
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
            }
        ]
        
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
            "ssa_performance": ssa_scores_list,
            "target_by_district": districts_perf,
            "regional_performance": regional_perf,
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
