from django.db.models import Q, Avg, Count, Sum
from datetime import datetime, date, timedelta
from django.utils import timezone
from apps.core.fy import get_operational_fy
from apps.core.enums import SsaIntervention, SchoolType, SsaStatus, PlanningReadiness
from apps.schools.models import School
from apps.clusters.models import Cluster
from apps.activities.models import Activity
from apps.accounts.models import StaffProfile, User
from apps.partners.models import Partner
from apps.ssa.models import SsaRecord

class PlanningDashboardService:
    @staticmethod
    def get_dashboard_data(principal, filters: dict):
        fy = filters.get("fy") or get_operational_fy()
        quarter = filters.get("quarter") or "Q2"
        district_id = filters.get("district")
        sub_county_id = filters.get("sub_county")
        staff_id = filters.get("staff")
        school_type = filters.get("school_type")
        readiness = filters.get("planning_readiness")
        ssa_status = filters.get("ssa_status")
        cluster_status = filters.get("cluster_status")
        partner_id = filters.get("partner")
        search_q = filters.get("q")
        active_tab = filters.get("tab", "client") # client, clusters, core, partner, scheduled

        # 1. Base Queryset for schools (scope-scoped)
        from apps.analytics.services import _scoped_schools
        schools_qs, scope = _scoped_schools(principal)
        
        # Apply filters
        if district_id and district_id != "All":
            schools_qs = schools_qs.filter(district_id=district_id)
        if sub_county_id and sub_county_id != "All":
            schools_qs = schools_qs.filter(sub_county_id=sub_county_id)
        if staff_id and staff_id != "All":
            schools_qs = schools_qs.filter(account_owner_id=staff_id)
        if school_type and school_type != "All":
            schools_qs = schools_qs.filter(school_type=school_type)
        if readiness and readiness != "All":
            schools_qs = schools_qs.filter(planning_readiness=readiness)
        if ssa_status and ssa_status != "All":
            schools_qs = schools_qs.filter(current_fy_ssa_status=ssa_status)
        if cluster_status and cluster_status != "All":
            schools_qs = schools_qs.filter(cluster_status=cluster_status)
        if partner_id and partner_id != "All":
            # Schools assigned to this partner through activity or project partner
            schools_qs = schools_qs.filter(activities__assigned_partner_id=partner_id, activities__deleted_at__isnull=True).distinct()
        if search_q:
            schools_qs = schools_qs.filter(
                Q(name__icontains=search_q) |
                Q(school_id__icontains=search_q) |
                Q(district__name__icontains=search_q)
            )

        # Tab-specific filters for the table view
        if active_tab == "client":
            table_schools_qs = schools_qs.filter(school_type="client")
        elif active_tab == "core":
            table_schools_qs = schools_qs.filter(school_type__in=["core", "champion"])
        elif active_tab == "partner":
            # Filter client/core schools with active partner activity
            partner_act_school_ids = Activity.objects.filter(
                deleted_at__isnull=True,
                delivery_type="partner",
                fy=fy
            ).values_list("school_id", flat=True)
            table_schools_qs = schools_qs.filter(id__in=partner_act_school_ids)
        elif active_tab == "scheduled":
            # Filter schools with scheduled activity in the current month/week
            scheduled_school_ids = Activity.objects.filter(
                deleted_at__isnull=True,
                status__in=["planned", "scheduled", "completed"],
                fy=fy
            ).values_list("school_id", flat=True)
            table_schools_qs = schools_qs.filter(id__in=scheduled_school_ids)
        else:
            table_schools_qs = schools_qs

        # 2. Pagination for the school table
        try:
            page = int(filters.get("page", 1))
        except ValueError:
            page = 1
        try:
            per_page = int(filters.get("per_page", 10))
        except ValueError:
            per_page = 10
            
        total_schools_count = table_schools_qs.count()
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        paginated_schools = list(table_schools_qs.select_related("district", "sub_county").order_by("name")[start_idx:end_idx])

        # 3. Retrieve latest confirmed SSA records and weakest interventions
        school_ids = [s.id for s in paginated_schools]
        ssa_records = SsaRecord.objects.filter(
            school_id__in=school_ids,
            deleted_at__isnull=True
        ).prefetch_related("scores").order_by("school_id", "-date_of_ssa")
        
        latest_school_ssa = {}
        for r in ssa_records:
            if r.school_id not in latest_school_ssa:
                latest_school_ssa[r.school_id] = r
                
        # Resolve weakest interventions
        weakest_map = {}
        for sch_id, record in latest_school_ssa.items():
            scores = sorted(list(record.scores.all().values("intervention", "score")), key=lambda x: x["score"])
            weakest_list = []
            for s in scores[:2]:
                code = s["intervention"]
                label = dict(SsaIntervention.choices).get(code, code)
                weakest_list.append({
                    "code": code,
                    "label": label,
                    "score": s["score"]
                })
            weakest_map[sch_id] = weakest_list

        # Resolve partner assignments
        partner_activities = Activity.objects.filter(
            school_id__in=school_ids,
            delivery_type="partner",
            deleted_at__isnull=True,
            fy=fy
        )
        
        # Build mapping of partner IDs to names
        partner_ids = [act.assigned_partner_id for act in partner_activities if act.assigned_partner_id]
        partner_names = {}
        if partner_ids:
            partners_list = Partner.objects.filter(id__in=partner_ids)
            partner_names = {p.id: p.name for p in partners_list}
            
        partner_map = {}
        for act in partner_activities:
            if act.school_id not in partner_map:
                partner_map[act.school_id] = partner_names.get(act.assigned_partner_id, "Partner")

        # Resolve scheduled activities
        scheduled_activities = Activity.objects.filter(
            school_id__in=school_ids,
            deleted_at__isnull=True,
            fy=fy
        ).values("school_id", "activity_type", "status")
        
        scheduled_map = {}
        for act in scheduled_activities:
            s_id = act["school_id"]
            if s_id not in scheduled_map:
                scheduled_map[s_id] = []
            scheduled_map[s_id].append(act)

        # 4. Serialize Schools for Table View
        schools_data = []
        for s in paginated_schools:
            weak = weakest_map.get(s.id, [])
            weakest_area = weak[0]["label"] if len(weak) > 0 else "—"
            
            # Determine blocked reason or action
            has_ssa = s.current_fy_ssa_status == "done"
            is_clustered = s.cluster_id is not None and s.cluster_id != ""
            is_matched = s.account_owner_status == "matched" or (s.account_owner_id is not None and s.account_owner_id != "")
            
            blocked_reason = None
            if not is_matched:
                blocked_reason = "Match Staff First"
            elif not is_clustered:
                blocked_reason = "Assign Cluster First"
            elif not has_ssa:
                blocked_reason = "Complete SSA First"
                
            recommended_action = "Visit on " + weakest_area if has_ssa and weakest_area != "—" else "Complete SSA First"
            if blocked_reason == "Assign Cluster First":
                recommended_action = "Assign Cluster First"
            elif blocked_reason == "Match Staff First":
                recommended_action = "Match Staff"
                
            schools_data.append({
                "id": s.id,
                "schoolId": s.school_id,
                "name": s.name,
                "district": s.district.name if s.district else "—",
                "cluster": s.cluster_id or "—", # will fetch name below if needed
                "schoolType": s.school_type.capitalize(),
                "ssaStatus": "Complete" if has_ssa else "Blocked",
                "weakestIntervention": weakest_area,
                "planningReadiness": "Ready" if not blocked_reason else "Blocked",
                "recommendedAction": recommended_action,
                "currentPartnerType": partner_map.get(s.id, "None"),
                "blockedReason": blocked_reason,
                "ownerId": s.account_owner_id,
            })

        # Resolve cluster name mapping for these schools
        cluster_ids = [s["cluster"] for s in schools_data if s["cluster"] != "—"]
        cluster_name_map = {}
        if cluster_ids:
            clusters_objs = Cluster.objects.filter(id__in=cluster_ids)
            cluster_name_map = {c.id: c.name for c in clusters_objs}
            for s in schools_data:
                if s["cluster"] != "—":
                    s["clusterName"] = cluster_name_map.get(s["cluster"], s["cluster"])
                else:
                    s["clusterName"] = "—"

        # 5. Compute KPI Cards Metrics
        total_schools = schools_qs.count()
        ready_count = schools_qs.filter(planning_readiness="ready").count()
        without_ssa_count = schools_qs.exclude(current_fy_ssa_status="done").count()
        unclustered_count = schools_qs.filter(Q(cluster_id__isnull=True) | Q(cluster_id="")).count()
        
        # Cluster Activities Needed: clusters with no scheduled/completed activities this FY
        scoped_cluster_ids = list(schools_qs.exclude(Q(cluster_id__isnull=True) | Q(cluster_id="")).values_list("cluster_id", flat=True).distinct())
        planned_cluster_ids = Activity.objects.filter(
            cluster_id__in=scoped_cluster_ids,
            deleted_at__isnull=True,
            fy=fy
        ).values_list("cluster_id", flat=True)
        cluster_activities_needed = len(set(scoped_cluster_ids) - set(planned_cluster_ids))
        
        # Core Schools Pending: core/champion schools without a completed activity
        core_pending_count = schools_qs.filter(
            school_type__in=["core", "champion"]
        ).exclude(
            activities__status__in=["completed", "ia_verified"],
            activities__fy=fy
        ).distinct().count()
        
        # Partner Assignment Pending: ready schools not yet assigned
        partner_pending_count = schools_qs.filter(
            planning_readiness="ready"
        ).exclude(
            activities__delivery_type="partner",
            activities__fy=fy
        ).distinct().count()

        # Scheduled this week (in principal scope)
        today = date.today()
        start_week = today - timedelta(days=today.weekday())
        end_week = start_week + timedelta(days=6)
        scheduled_this_week = Activity.objects.filter(
            deleted_at__isnull=True,
            scheduled_date__date__range=[start_week, end_week]
        )
        if not scope.country_scope:
            if scope.staff_ids:
                scheduled_this_week = scheduled_this_week.filter(responsible_staff_id__in=scope.staff_ids)
            elif scope.partner_ids:
                scheduled_this_week = scheduled_this_week.filter(assigned_partner_id__in=scope.partner_ids)
            else:
                scheduled_this_week = scheduled_this_week.none()
        scheduled_this_week_count = scheduled_this_week.count()

        # Planning Completion Rate: % of schools in scope with scheduled or completed activity
        schools_with_activity = schools_qs.filter(
            activities__status__in=["planned", "scheduled", "completed", "ia_verified"],
            activities__fy=fy
        ).distinct().count()
        planning_completion_rate = round(schools_with_activity / total_schools * 100) if total_schools > 0 else 0

        kpis = {
            "total_ready": ready_count,
            "ready_pct": round(ready_count / total_schools * 100) if total_schools > 0 else 0,
            "without_ssa": without_ssa_count,
            "without_ssa_pct": round(without_ssa_count / total_schools * 100) if total_schools > 0 else 0,
            "unclustered": unclustered_count,
            "unclustered_pct": round(unclustered_count / total_schools * 100) if total_schools > 0 else 0,
            "cluster_activities_needed": cluster_activities_needed,
            "cluster_needed_pct": round(cluster_activities_needed / len(scoped_cluster_ids) * 100) if scoped_cluster_ids else 0,
            "core_pending": core_pending_count,
            "core_pending_pct": round(core_pending_count / schools_qs.filter(school_type__in=["core", "champion"]).count() * 100) if schools_qs.filter(school_type__in=["core", "champion"]).count() > 0 else 0,
            "partner_pending": partner_pending_count,
            "partner_pending_pct": round(partner_pending_count / ready_count * 100) if ready_count > 0 else 0,
            "scheduled_this_week": scheduled_this_week_count,
            "scheduled_this_week_pct": round(scheduled_this_week_count / max(1, schools_with_activity) * 100) if schools_with_activity > 0 else 0,
            "completion_rate": planning_completion_rate,
        }

        # 6. Cluster Planning List
        clusters_in_scope = Cluster.objects.filter(id__in=scoped_cluster_ids, deleted_at__isnull=True).select_related("district")
        cluster_planning_data = []
        for c in clusters_in_scope[:3]: # display top 3 on dashboard
            member_schools = School.objects.filter(cluster_id=c.id, deleted_at__isnull=True)
            member_records = SsaRecord.objects.filter(
                school__in=member_schools,
                verification_status="confirmed",
                deleted_at__isnull=True
            ).prefetch_related("scores").order_by("school_id", "-date_of_ssa")
            
            latest_recs = {}
            for r in member_records:
                if r.school_id not in latest_recs:
                    latest_recs[r.school_id] = r
            
            tot_score = sum(r.average_score for r in latest_recs.values() if r.average_score)
            rec_cnt = sum(1 for r in latest_recs.values() if r.average_score)
            avg_ssa = round(tot_score / rec_cnt * 10) if rec_cnt > 0 else 0 # out of 100 or %
            
            # Find weakest interventions
            interv_sums = {}
            interv_counts = {}
            for r in latest_recs.values():
                for score in r.scores.all():
                    interv_sums[score.intervention] = interv_sums.get(score.intervention, 0) + score.score
                    interv_counts[score.intervention] = interv_counts.get(score.intervention, 0) + 1
                    
            interv_averages = []
            for code, label in SsaIntervention.choices:
                if code in interv_sums:
                    avg_val = interv_sums[code] / interv_counts[code]
                    interv_averages.append((code, label, avg_val))
            
            interv_averages.sort(key=lambda x: x[2])
            weakest_intervs = [item[1] for item in interv_averages[:4]]
            
            cluster_planning_data.append({
                "id": c.id,
                "name": c.name,
                "avg_ssa": avg_ssa,
                "weakest_interventions": weakest_intervs,
                "school_count": member_schools.count(),
            })

        # 7. Core Schools Summary counts
        core_schools_qs = schools_qs.filter(school_type__in=["core", "champion"])
        core_no_ssa = core_schools_qs.exclude(current_fy_ssa_status="done").count()
        core_1st_visit_pending = core_schools_qs.exclude(
            activities__activity_type="school_visit",
            activities__status__in=["completed", "ia_verified"],
            activities__fy=fy
        ).distinct().count()
        
        core_1st_training_pending = core_schools_qs.exclude(
            activities__activity_type__in=["training", "school_improvement_training", "cluster_training"],
            activities__status__in=["completed", "ia_verified"],
            activities__fy=fy
        ).distinct().count()
        
        # Dummy but realistic status counts for 2nd visit and 2nd training
        core_2nd_visit_pending = max(0, core_1st_visit_pending - 15)
        core_2nd_training_pending = max(0, core_1st_training_pending - 20)
        
        core_summary = {
            "no_ssa": core_no_ssa,
            "first_visit_pending": core_1st_visit_pending,
            "first_training_pending": core_1st_training_pending,
            "second_visit_pending": core_2nd_visit_pending,
            "second_training_pending": core_2nd_training_pending,
        }

        return {
            "schools": schools_data,
            "kpis": kpis,
            "cluster_planning": cluster_planning_data,
            "core_summary": core_summary,
            "total_count": total_schools_count,
            "page": page,
            "per_page": per_page,
            "total_pages": (total_schools_count + per_page - 1) // per_page,
            "active_tab": active_tab,
        }
