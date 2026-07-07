from django.shortcuts import render, redirect
from django.db.models import Q, Avg, Count, Sum
from django.utils import timezone
from datetime import date as date_type, timedelta

from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.schools.models import School
from apps.clusters.models import Cluster
from apps.fund_requests.models import WeeklyFundRequest
from apps.ssa.models import SsaRecord, SsaScore
from apps.accounts.models import User, StaffProfile, StaffSupervisorAssignment
from apps.command_center import services as cc_services
from apps.core.permissions import require_page_permission
from apps.core.enums import SsaIntervention
from apps.command_center.dashboard_service import DashboardMetricsService


@require_page_permission("dashboard")
def dashboard_view(request):
    user = request.user
    role = user.active_role

    # Fetch common alerts and todays items
    alerts_list = cc_services.alerts(user)
    alerts_summary = cc_services.alerts_summary(user)
    today_context = cc_services.today(user)

    # Fetch unified dashboard metrics from the service
    metrics = DashboardMetricsService.get_dashboard_metrics(user)

    # Get user avatar initials
    names = user.name.split()
    avatar_initials = "".join([n[0].upper() for n in names[:2]]) if names else "US"

    if role == "Accountant":
        return redirect("/accounts")

    if role == "ImpactAssessment":
        return redirect("/ia/dashboard/")

    if role == "CountryDirector":
        from apps.core.fy import get_operational_fy
        from apps.geography.models import District, Region
        from apps.budget.models import CostCatalogue, CostSetting

        fy = get_operational_fy()
        today = timezone.now().date()

        # Activity status buckets (used across all CD queries).
        ACHIEVED = ["completed", "closed"]
        PLANNED = [
            "planned",
            "scheduled",
            "in_progress",
            "completion_started",
            "evidence_uploaded",
            "evidence_accepted",
            "salesforce_id_required",
            "submitted_to_pl",
            "returned_by_pl",
            "awaiting_ia_verification",
            "rescheduled",
        ]
        VERIFIED = ["ia_verified"]
        VISIT_TYPES = [
            "school_visit",
            "follow_up_visit",
            "coaching_visit",
            "baseline_ssa_visit",
            "school_visit_ssa_collection",
            "core_visit",
            "core_assessment_visit",
        ]
        TRAINING_TYPES = [
            "training",
            "school_improvement_training",
            "cluster_training",
            "cluster_training_ssa_collection",
            "core_training",
        ]

        # ── KPI strip ────────────────────────────────────────────────────────
        total_schools = School.objects.filter(deleted_at__isnull=True).count()
        completed_visits = Activity.objects.filter(
            status="completed",
            activity_type__in=VISIT_TYPES,
            deleted_at__isnull=True,
            fy=fy,
        ).count()
        planned_visits = Activity.objects.filter(
            status__in=PLANNED,
            activity_type__in=VISIT_TYPES,
            deleted_at__isnull=True,
            fy=fy,
        ).count()
        verified_visits = Activity.objects.filter(
            status__in=VERIFIED,
            deleted_at__isnull=True,
            fy=fy,
        ).count()
        avg_national_ssa = (
            (
                SsaRecord.objects.filter(deleted_at__isnull=True, fy=fy).aggregate(
                    a=Avg("average_score")
                )["a"]
            )
            or 0.0
        )

        # ── Fund requests & budget ───────────────────────────────────────────
        pending_wfrs = list(
            WeeklyFundRequest.objects.filter(status="submitted_to_cd").order_by(
                "-week_start_date"
            )
        )
        _wfr_user_ids = [w.responsible_user for w in pending_wfrs]
        _wfr_users = {u.id: u for u in User.objects.filter(id__in=_wfr_user_ids)}
        for w in pending_wfrs:
            w.requester = _wfr_users.get(w.responsible_user)
            w.total_budget = w.total_amount

        total_approved = (
            WeeklyFundRequest.objects.filter(
                fy=fy,
                status__in=[
                    "approved_by_cd",
                    "sent_to_accountant",
                    "disbursed",
                    "accounted",
                    "accountability_pending",
                ],
            ).aggregate(s=Sum("total_amount"))["s"]
            or 0
        )
        total_requested = (
            WeeklyFundRequest.objects.filter(
                fy=fy,
                status__in=["submitted_to_cd", "submitted_to_pl", "approved_by_pl"],
            ).aggregate(s=Sum("total_amount"))["s"]
            or 0
        )
        total_disbursed = (
            WeeklyFundRequest.objects.filter(fy=fy).aggregate(
                s=Sum("disbursed_amount")
            )["s"]
            or 0
        )
        budget_planned_total = (
            ActivityScheduleCostLine.objects.filter(
                activity__fy=fy, activity__deleted_at__isnull=True
            ).aggregate(s=Sum("amount"))["s"]
            or 0
        )

        budget_summary = {
            "total_approved": total_approved,
            "total_requested": total_requested,
            "total_disbursed": total_disbursed,
            "planned_total": budget_planned_total,
            "utilization_pct": round(total_disbursed / budget_planned_total * 100, 1)
            if budget_planned_total
            else 0,
        }

        active_catalogue = CostCatalogue.objects.filter(fy=fy, is_active=True).first()
        cost_items = (
            list(CostSetting.objects.filter(catalogue=active_catalogue).order_by("key"))
            if active_catalogue
            else []
        )

        # ── District risk table (existing real query, kept) ──────────────────
        districts = (
            District.objects.annotate(
                total=Count("schools", filter=Q(schools__deleted_at__isnull=True)),
                missing_ssa=Count(
                    "schools",
                    filter=Q(schools__deleted_at__isnull=True)
                    & ~Q(schools__current_fy_ssa_status="done"),
                ),
                avg_ssa=Avg(
                    "schools__ssa_records__average_score",
                    filter=Q(schools__deleted_at__isnull=True)
                    & Q(schools__ssa_records__deleted_at__isnull=True),
                ),
            )
            .filter(total__gt=0)
            .order_by("-missing_ssa")[:8]
        )
        district_risks = [
            {
                "district": d.name,
                "total": d.total,
                "missing_ssa": d.missing_ssa,
                "avg_ssa": round(d.avg_ssa or 0.0, 2),
            }
            for d in districts
        ]

        # ── Regional performance (real Region annotations) ───────────────────
        regions_qs = Region.objects.annotate(
            school_count=Count("schools", filter=Q(schools__deleted_at__isnull=True)),
            planned=Count(
                "schools__activities",
                filter=Q(schools__deleted_at__isnull=True)
                & Q(schools__activities__deleted_at__isnull=True)
                & Q(schools__activities__fy=fy)
                & Q(schools__activities__status__in=PLANNED),
            ),
            completed=Count(
                "schools__activities",
                filter=Q(schools__deleted_at__isnull=True)
                & Q(schools__activities__deleted_at__isnull=True)
                & Q(schools__activities__fy=fy)
                & Q(schools__activities__status__in=ACHIEVED),
            ),
            avg_ssa=Avg(
                "schools__ssa_records__average_score",
                filter=Q(schools__deleted_at__isnull=True)
                & Q(schools__ssa_records__deleted_at__isnull=True)
                & Q(schools__ssa_records__fy=fy),
            ),
        ).filter(school_count__gt=0)
        regions_list = []
        for r in regions_qs:
            denom = r.planned + r.completed
            rate = round(r.completed / denom * 100) if denom else 0
            if rate >= 80:
                color = "bg-emerald-500"
            elif rate >= 60:
                color = "bg-amber-500"
            else:
                color = "bg-rose-500"
            regions_list.append(
                {
                    "name": r.name,
                    "rate": rate,
                    "color": color,
                    "school_count": r.school_count,
                    "avg_ssa": round(r.avg_ssa or 0.0, 2),
                }
            )
        regions_list.sort(key=lambda x: x["rate"], reverse=True)

        # ── Country Program Leads performance (real supervised-team data) ───
        leads_performance = []
        for pl in User.objects.filter(
            roles__contains=["Program Lead"], deleted_at__isnull=True
        ):
            sp = getattr(pl, "staff_profile", None)
            supervisee_sp_ids = (
                list(
                    StaffSupervisorAssignment.objects.filter(supervisor=sp).values_list(
                        "supervisee_id", flat=True
                    )
                )
                if sp
                else []
            )
            supervisee_user_ids = list(
                StaffProfile.objects.filter(id__in=supervisee_sp_ids).values_list(
                    "user_id", flat=True
                )
            )
            # Region: derive from supervised CCEOs' schools
            region_name = "—"
            if supervisee_sp_ids:
                _sch = (
                    School.objects.filter(account_owner_id__in=supervisee_sp_ids)
                    .select_related("region")
                    .first()
                )
                if _sch and _sch.region:
                    region_name = _sch.region.name
            planned = Activity.objects.filter(
                responsible_staff_id__in=supervisee_user_ids,
                status__in=PLANNED,
                deleted_at__isnull=True,
                fy=fy,
            ).count()
            completed = Activity.objects.filter(
                responsible_staff_id__in=supervisee_user_ids,
                status__in=ACHIEVED,
                deleted_at__isnull=True,
                fy=fy,
            ).count()
            verified = Activity.objects.filter(
                responsible_staff_id__in=supervisee_user_ids,
                status__in=VERIFIED,
                deleted_at__isnull=True,
                fy=fy,
            ).count()
            sf_pending = Activity.objects.filter(
                responsible_staff_id__in=supervisee_user_ids,
                salesforce_activity_id__isnull=True,
                status__in=ACHIEVED + VERIFIED,
                deleted_at__isnull=True,
                fy=fy,
            ).count()
            backlog = Activity.objects.filter(
                responsible_staff_id__in=supervisee_user_ids,
                planned_date__lt=today,
                status__in=PLANNED,
                deleted_at__isnull=True,
            ).count()
            denom = planned + completed
            target_pct = round(completed / denom * 100) if denom else 0
            if denom == 0:
                status, status_class = "No Data", "bg-slate-100 text-slate-500"
            elif target_pct >= 80:
                status, status_class = "On Track", "bg-emerald-50 text-emerald-700"
            elif target_pct >= 60:
                status, status_class = "Watch", "bg-amber-50 text-amber-700"
            else:
                status, status_class = "High Risk", "bg-rose-50 text-rose-700"
            leads_performance.append(
                {
                    "name": pl.name,
                    "region": region_name,
                    "staff": len(supervisee_sp_ids),
                    "planned": planned,
                    "verified": verified,
                    "sf_pending": sf_pending,
                    "backlog": backlog,
                    "target_pct": target_pct,
                    "status": status,
                    "status_class": status_class,
                }
            )
        high_risk_count = sum(
            1 for lead in leads_performance if lead["status"] == "High Risk"
        )

        # ── SSA Intervention Heat Matrix (region × 8 interventions) ──────────
        [code for code, _label in SsaIntervention.choices]
        heat_qs = (
            SsaScore.objects.filter(
                ssa_record__deleted_at__isnull=True,
                ssa_record__school__deleted_at__isnull=True,
                ssa_record__fy=fy,
            )
            .values("ssa_record__school__region__name", "intervention")
            .annotate(avg=Avg("score"))
        )
        # Pivot into region rows × intervention columns
        _heat_map = {}
        for row in heat_qs:
            rname = row["ssa_record__school__region__name"] or "Unknown"
            _heat_map.setdefault(rname, {})[row["intervention"]] = (
                round(row["avg"], 1) if row["avg"] is not None else None
            )
        ssa_heat_rows = []
        for rname, scores in _heat_map.items():
            rrow = {"name": rname, "scores": scores}
            ssa_heat_rows.append(rrow)

        # ── Fund Approval & Finance Snapshot (by region, from cost lines) ────
        fin_qs = (
            ActivityScheduleCostLine.objects.filter(
                activity__fy=fy, activity__deleted_at__isnull=True, school__isnull=False
            )
            .values("school__region__name")
            .annotate(total=Sum("amount"), count=Count("id", distinct=True))
        )
        finance_snapshot_pending = [
            {
                "region": r["school__region__name"] or "Unknown",
                "requested": r["total"] or 0,
                "activities": r["count"],
            }
            for r in fin_qs.order_by("-total")[:6]
        ]

        # ── Priority Schools (flagged issues, real queries) ──────────────────
        visited_school_ids = set(
            Activity.objects.filter(
                activity_type__in=VISIT_TYPES,
                fy=fy,
                deleted_at__isnull=True,
                school__isnull=False,
            ).values_list("school_id", flat=True)
        )
        trained_school_ids = set(
            Activity.objects.filter(
                activity_type__in=TRAINING_TYPES,
                fy=fy,
                deleted_at__isnull=True,
                school__isnull=False,
            ).values_list("school_id", flat=True)
        )
        weak_ssa_school_ids = set(
            SsaRecord.objects.filter(
                deleted_at__isnull=True, fy=fy, average_score__lt=5.0
            ).values_list("school_id", flat=True)
        )
        priority_schools = []
        for s in School.objects.filter(deleted_at__isnull=True).select_related(
            "region"
        ):
            flags = []
            if s.id not in visited_school_ids:
                flags.append("No Visit")
            if s.id not in trained_school_ids:
                flags.append("No Training")
            if s.id in weak_ssa_school_ids:
                flags.append("SSA Weakness")
            if not flags:
                continue
            if len(flags) >= 2:
                risk, risk_class = "High", "bg-rose-50 text-rose-700"
            else:
                risk, risk_class = "Medium", "bg-amber-50 text-amber-700"
            priority_schools.append(
                {
                    "name": s.name,
                    "region": s.region.name if s.region_id else "—",
                    "issue": ", ".join(flags),
                    "risk": risk,
                    "risk_class": risk_class,
                    "school_id": s.school_id,
                }
            )
            if len(priority_schools) >= 10:
                break

        # ── Performance chart data (monthly planned vs completed vs verified) ─
        chart_labels, chart_planned, chart_completed, chart_verified = [], [], [], []
        for m in range(1, 13):
            chart_labels.append(date_type(2026, m, 1).strftime("%b"))
            chart_planned.append(
                Activity.objects.filter(
                    fy=fy, planned_month=m, status__in=PLANNED, deleted_at__isnull=True
                ).count()
            )
            chart_completed.append(
                Activity.objects.filter(
                    fy=fy, planned_month=m, status__in=ACHIEVED, deleted_at__isnull=True
                ).count()
            )
            chart_verified.append(
                Activity.objects.filter(
                    fy=fy, planned_month=m, status__in=VERIFIED, deleted_at__isnull=True
                ).count()
            )

        # SF backlog count (activities completed but missing SF id)
        sf_backlog = Activity.objects.filter(
            status__in=ACHIEVED,
            salesforce_activity_id__isnull=True,
            deleted_at__isnull=True,
            fy=fy,
        ).count()

        # National achievement rate
        total_planned_nat = sum(chart_planned)
        total_completed_nat = sum(chart_completed)
        national_achievement = (
            round(total_completed_nat / (total_planned_nat + total_completed_nat) * 100)
            if (total_planned_nat + total_completed_nat)
            else 0
        )

        context = {
            "alerts": alerts_list,
            "alerts_summary": alerts_summary,
            "today_context": today_context,
            "role": role,
            "user_name": user.name,
            "avatar_initials": avatar_initials,
            "use_dark_sidebar": False,
            "fy": fy,
            # KPIs
            "total_schools": total_schools,
            "completed_visits": completed_visits,
            "planned_visits": planned_visits,
            "verified_visits": verified_visits,
            "avg_national_ssa": round(avg_national_ssa, 2),
            "national_achievement": national_achievement,
            "sf_backlog": sf_backlog,
            "high_risk_count": high_risk_count,
            # Funds & budget
            "pending_funds": pending_wfrs,
            "budget_summary": budget_summary,
            "active_catalogue": active_catalogue,
            "cost_items": cost_items,
            "finance_snapshot_pending": finance_snapshot_pending,
            # Tables
            "district_risks": district_risks,
            "regions_list": regions_list,
            "leads_performance": leads_performance,
            "ssa_heat_rows": ssa_heat_rows,
            "intervention_choices": SsaIntervention.choices,
            "priority_schools": priority_schools,
            # Chart
            "chart_labels": chart_labels,
            "chart_planned": chart_planned,
            "chart_completed": chart_completed,
            "chart_verified": chart_verified,
        }
        return render(request, "pages/dashboards/cd.html", context)

    elif role == "Program Lead":
        # Country Program Lead dashboard — operational oversight of the field
        # chain (CCEOs → PL). PL reviews activities and approves fund requests
        # escalated by CCEOs, and watches cluster SSA health and CCEO workload.
        today = timezone.now().date()

        # Activities submitted by CCEOs awaiting PL review. Attach the
        # responsible staff user (Activity stores only responsible_staff_id).
        pending_reviews = list(
            Activity.objects.filter(
                status="submitted_to_pl",
                deleted_at__isnull=True,
            )
            .select_related("school", "cluster")
            .order_by("-updated_at")[:10]
        )
        _act_user_ids = [
            a.responsible_staff_id for a in pending_reviews if a.responsible_staff_id
        ]
        _act_users = {u.id: u for u in User.objects.filter(id__in=_act_user_ids)}
        for a in pending_reviews:
            a.responsible_staff = _act_users.get(a.responsible_staff_id)

        # Weekly fund requests awaiting PL approval. Attach the requester user
        # and a display-friendly total_budget, matching how the CD branch
        # prepares these for the template.
        pending_funds = list(
            WeeklyFundRequest.objects.filter(
                status="submitted_to_pl",
            ).order_by("-week_start_date")[:10]
        )
        _wfr_user_ids = [
            wfr.responsible_user for wfr in pending_funds if wfr.responsible_user
        ]
        _wfr_users = {u.id: u for u in User.objects.filter(id__in=_wfr_user_ids)}
        for wfr in pending_funds:
            wfr.requester = _wfr_users.get(wfr.responsible_user)
            wfr.total_budget = wfr.total_amount

        # CCEOs with overdue activities (mirrors the HR workload pattern).
        cceos = User.objects.filter(roles__contains=["CCEO"], deleted_at__isnull=True)
        cceos_overdue = []
        for c in cceos:
            overdue = Activity.objects.filter(
                responsible_staff_id=c.id,
                planned_date__lt=today,
                status__in=["scheduled", "started", "in_progress"],
                deleted_at__isnull=True,
            ).count()
            if overdue > 0:
                cceos_overdue.append(
                    {
                        "name": c.name,
                        "overdue_count": overdue,
                    }
                )
        cceos_overdue.sort(key=lambda x: x["overdue_count"], reverse=True)
        cceos_overdue = cceos_overdue[:6]

        # Clusters with weak average SSA across their schools.
        weak_clusters = []
        for clus in Cluster.objects.filter(deleted_at__isnull=True).select_related(
            "region", "district"
        ):
            avg = SsaRecord.objects.filter(
                school__cluster_assignments__cluster=clus,
                deleted_at__isnull=True,
            ).aggregate(Avg("average_score"))["average_score__avg"]
            if avg is not None and avg < 5.0:
                weak_clusters.append(
                    {
                        "id": clus.id,
                        "name": clus.name,
                        "region": clus.region.name if clus.region_id else "—",
                        "district": clus.district.name if clus.district_id else "—",
                        "avg_ssa": round(avg, 2),
                    }
                )
        weak_clusters.sort(key=lambda x: x["avg_ssa"])
        weak_clusters = weak_clusters[:6]

        context = {
            "alerts": alerts_list,
            "alerts_summary": alerts_summary,
            "today_context": today_context,
            "role": role,
            "user_name": user.name,
            "avatar_initials": avatar_initials,
            "pending_reviews": pending_reviews,
            "pending_funds": pending_funds,
            "cceos_overdue": cceos_overdue,
            "weak_clusters": weak_clusters,
        }
        return render(request, "pages/dashboards/pl.html", context)

    elif role == "RegionalVicePresident":
        from apps.geography.models import Region

        total_schools = School.objects.filter(deleted_at__isnull=True).count()
        schools_missing_ssa = (
            School.objects.filter(deleted_at__isnull=True)
            .exclude(current_fy_ssa_status="done")
            .count()
        )

        pending_wfrs = WeeklyFundRequest.objects.filter(
            status__in=["submitted_to_cd", "approved_by_pl"]
        ).count()

        total_requested = (
            WeeklyFundRequest.objects.filter(
                status__in=["submitted_to_cd", "submitted_to_pl", "approved_by_pl"]
            ).aggregate(Sum("total_amount"))["total_amount__sum"]
            or 0
        )

        total_approved = (
            WeeklyFundRequest.objects.filter(
                status__in=[
                    "approved_by_cd",
                    "sent_to_accountant",
                    "disbursed",
                    "accounted",
                ]
            ).aggregate(Sum("total_amount"))["total_amount__sum"]
            or 0
        )

        regions_summary = []
        regions = Region.objects.annotate(
            school_count=Count(
                "districts__schools",
                filter=Q(districts__schools__deleted_at__isnull=True),
            ),
            missing_ssa=Count(
                "districts__schools",
                filter=Q(districts__schools__deleted_at__isnull=True)
                & ~Q(districts__schools__current_fy_ssa_status="done"),
            ),
        ).filter(school_count__gt=0)
        for r in regions:
            regions_summary.append(
                {
                    "name": r.name,
                    "school_count": r.school_count,
                    "missing_ssa": r.missing_ssa,
                }
            )

        context = {
            "alerts": alerts_list,
            "alerts_summary": alerts_summary,
            "role": role,
            "user_name": user.name,
            "avatar_initials": avatar_initials,
            "total_schools": total_schools,
            "schools_missing_ssa": schools_missing_ssa,
            "pending_reviews": pending_wfrs,
            "total_requested": total_requested,
            "total_approved": total_approved,
            "regions_summary": regions_summary,
        }
        return render(request, "pages/dashboards/rvp.html", context)

    elif role == "HumanResources":
        from apps.debriefs.models import DailyDebrief
        from apps.accounts.models import Leave

        today = timezone.now().date()
        overdue_count = Activity.objects.filter(
            planned_date__lt=today,
            status__in=["scheduled", "started"],
            deleted_at__isnull=True,
        ).count()

        debrief_count = DailyDebrief.objects.filter(
            deleted_at__isnull=True, created_at__date=today
        ).count()

        pending_leaves = Leave.objects.filter(status="pending").count()

        # Overdue per CCEO count
        cceos = User.objects.filter(roles__contains=["CCEO"], deleted_at__isnull=True)
        workload_alerts = []
        for c in cceos:
            c_overdue = Activity.objects.filter(
                responsible_staff_id=c.id,
                planned_date__lt=today,
                status__in=["scheduled", "started"],
                deleted_at__isnull=True,
            ).count()
            if c_overdue > 3:
                workload_alerts.append(
                    {"staff_name": c.name, "overdue_count": c_overdue}
                )

        context = {
            "alerts": alerts_list,
            "alerts_summary": alerts_summary,
            "role": role,
            "user_name": user.name,
            "avatar_initials": avatar_initials,
            "overdue_count": overdue_count,
            "debrief_count": debrief_count,
            "pending_leaves": pending_leaves,
            "workload_alerts": workload_alerts[:5],
        }
        return render(request, "pages/dashboards/hr.html", context)

    elif role == "CCEO":
        # CCEO Field Officer Dashboard Context
        today = timezone.now().date()

        # Fetch actual user tasks
        cc_activities = Activity.objects.filter(
            responsible_staff_id=user.id, deleted_at__isnull=True
        )

        completed_cnt = cc_activities.filter(status="completed").count()
        in_progress_cnt = cc_activities.filter(status="in_progress").count()
        planned_cnt = cc_activities.filter(status__in=["scheduled", "planned"]).count()
        overdue_cnt = (
            cc_activities.filter(planned_date__lt=today)
            .exclude(status__in=["completed", "closed"])
            .count()
        )

        total_tasks = completed_cnt + in_progress_cnt + planned_cnt + overdue_cnt

        # Today's agenda built from the user's real scheduled activities,
        # partitioned into morning / afternoon / evening by scheduled time.
        def _agenda_item(act):
            atype = act.activity_type or ""
            if "training" in atype:
                icon = "📚"
            elif "meeting" in atype:
                icon = "👥"
            elif "ssa" in atype:
                icon = "📋"
            else:
                icon = "🏫"
            if act.status == "completed":
                status, status_class = (
                    "Completed",
                    "bg-emerald-50 text-emerald-700 border-emerald-200",
                )
            elif act.status in ("started", "in_progress"):
                status, status_class = (
                    "In Progress",
                    "bg-amber-50 text-amber-700 border-amber-200",
                )
            elif (
                act.planned_date
                and act.planned_date.date() < today
                and act.status not in ("completed", "closed")
            ):
                status, status_class = (
                    "Overdue",
                    "bg-rose-50 text-rose-700 border-rose-200",
                )
            else:
                status, status_class = (
                    "Planned",
                    "bg-slate-50 text-slate-500 border-slate-200",
                )
            school_name = (
                act.school.name
                if act.school
                else (act.cluster.name if act.cluster else "—")
            )
            district = (
                act.school.district.name if act.school and act.school.district else ""
            )
            location = f"{school_name}" + (
                f" &bull; {district} District" if district else ""
            )
            return {
                "title": f"{act.activity_type.replace('_', ' ').title()} — {school_name}",
                "location": location,
                "status": status,
                "status_class": status_class,
                "icon": icon,
                "sf": bool(act.salesforce_activity_id),
            }

        todays_qs = (
            cc_activities.filter(scheduled_date__date=today)
            .select_related("school", "school__district", "cluster")
            .order_by("scheduled_date")
        )
        agenda_morning, agenda_afternoon, agenda_evening = [], [], []
        for act in todays_qs:
            hour = (
                timezone.localtime(act.scheduled_date).hour if act.scheduled_date else 9
            )
            if hour < 12:
                agenda_morning.append(_agenda_item(act))
            elif hour < 17:
                agenda_afternoon.append(_agenda_item(act))
            else:
                agenda_evening.append(_agenda_item(act))

        # Next 7 days (excluding today)
        upcoming_week = []
        week_qs = (
            cc_activities.filter(
                scheduled_date__date__gt=today,
                scheduled_date__date__lte=today + timedelta(days=7),
            )
            .select_related("school", "school__district", "cluster")
            .order_by("scheduled_date")[:5]
        )
        for act in week_qs:
            atype = act.activity_type or ""
            if "training" in atype:
                icon, type_class = "📚", "bg-emerald-50 text-emerald-600"
            elif "meeting" in atype:
                icon, type_class = "👥", "bg-violet-50 text-violet-600"
            else:
                icon, type_class = "🏫", "bg-blue-50 text-blue-600"
            school_name = (
                act.school.name
                if act.school
                else (act.cluster.name if act.cluster else "—")
            )
            district = (
                act.school.district.name if act.school and act.school.district else "—"
            )
            upcoming_week.append(
                {
                    "day": act.scheduled_date.strftime("%a, %b %d")
                    if act.scheduled_date
                    else "—",
                    "title": f"{act.activity_type.replace('_', ' ').title()} — {school_name}",
                    "desc": f"{district} District" if district != "—" else "—",
                    "icon": icon,
                    "type_class": type_class,
                }
            )

        # Real pending fund-request confirmations for this user
        pending_approvals = []
        for w in WeeklyFundRequest.objects.filter(
            responsible_user=user.id, status="pending_responsible_confirmation"
        ).order_by("-week_start_date")[:3]:
            pending_approvals.append(
                {
                    "title": f"Fund Request — Week of {w.week_start_date.strftime('%d %b')}",
                    "desc": f"UGX {w.total_amount:,} &bull; {w.lines.count()} item{'s' if w.lines.count() != 1 else ''}",
                    "status": "Awaiting",
                }
            )

        context = {
            "alerts": alerts_list,
            "alerts_summary": alerts_summary,
            "role": role,
            "user_name": user.name,
            "avatar_initials": avatar_initials,
            "kpis": {
                "completed": completed_cnt,
                "in_progress": in_progress_cnt,
                "planned": planned_cnt,
                "overdue": overdue_cnt,
                "total": total_tasks,
            },
            "agenda_morning": agenda_morning,
            "agenda_afternoon": agenda_afternoon,
            "agenda_evening": agenda_evening,
            "agenda_total": len(agenda_morning)
            + len(agenda_afternoon)
            + len(agenda_evening),
            "upcoming_week": upcoming_week,
            "pending_approvals": pending_approvals,
        }
        return render(request, "pages/dashboards/cceo.html", context)

    elif role == "ProjectCoordinator":
        # ProjectCoordinator Special Projects Dashboard — live project portfolio
        import json as _json
        from apps.projects.models import Project

        today = timezone.now().date()
        portfolio = []
        for proj in Project.objects.filter(deleted_at__isnull=True).prefetch_related(
            "partner_assignments__partner"
        ):
            proj_acts = Activity.objects.filter(
                deleted_at__isnull=True, project_id=proj.id
            )
            n_total = proj_acts.count()
            n_done = proj_acts.filter(
                status__in=["completed", "ia_verified", "closed"]
            ).count()
            pct = round(n_done / n_total * 100) if n_total else 0
            partners = [
                pa.partner.name for pa in proj.partner_assignments.all() if pa.partner
            ]
            if pct >= 70 or n_total == 0:
                status, health_class = (
                    "Active",
                    "text-emerald-600 bg-emerald-50 border-emerald-100",
                )
            elif pct >= 40:
                status, health_class = (
                    "At Risk",
                    "text-amber-600 bg-amber-50 border-amber-100",
                )
            else:
                status, health_class = (
                    "Behind",
                    "text-rose-600 bg-rose-50 border-rose-100",
                )
            portfolio.append(
                {
                    "name": proj.name,
                    "type": proj.get_category_display(),
                    "partner": ", ".join(partners) if partners else "—",
                    "schools": proj.school_assignments.count(),
                    "activities": n_total,
                    "completed": n_done,
                    "pct": pct,
                    "status": status if n_total else "Not Started",
                    "health": f"{pct}%",
                    "health_class": health_class,
                    "metric": "Activities Completed",
                }
            )

        project_names = {
            pr.id: pr.name for pr in Project.objects.filter(deleted_at__isnull=True)
        }
        milestones = []
        for act in (
            Activity.objects.filter(
                deleted_at__isnull=True, scheduled_date__date__gte=today
            )
            .exclude(project_id__isnull=True)
            .exclude(project_id="")
            .select_related("school")
            .order_by("scheduled_date")[:6]
        ):
            milestones.append(
                {
                    "month": act.scheduled_date.strftime("%b").upper(),
                    "day": act.scheduled_date.strftime("%d"),
                    "title": act.activity_type.replace("_", " ").title(),
                    "desc": project_names.get(act.project_id, "—"),
                    "time": act.scheduled_date.strftime("%I:%M %p"),
                    "info": act.school.name if act.school else "—",
                }
            )

        # Projects needing attention: behind schedule or no scheduled work
        attention = []
        for row in portfolio:
            if row["status"] in ("Behind", "At Risk"):
                attention.append(
                    {
                        "project": row["name"],
                        "issue": f"Only {row['completed']} of {row['activities']} scheduled activities completed",
                        "risk": row["status"],
                        "date": today.strftime("%b %d, %Y"),
                        "risk_class": "text-rose-700 bg-rose-50 border-rose-150"
                        if row["status"] == "Behind"
                        else "text-amber-700 bg-amber-50 border-amber-150",
                    }
                )
            elif row["activities"] == 0:
                attention.append(
                    {
                        "project": row["name"],
                        "issue": "No activities scheduled yet",
                        "risk": "Not Started",
                        "date": today.strftime("%b %d, %Y"),
                        "risk_class": "text-slate-600 bg-slate-50 border-slate-200",
                    }
                )

        sp_kpis = {
            "total": len(portfolio),
            "active": sum(1 for row in portfolio if row["activities"] > 0),
            "schools": sum(row["schools"] for row in portfolio),
            "partners": sum(1 for row in portfolio if row["partner"] != "—"),
            "activities": sum(row["activities"] for row in portfolio),
            "completed": sum(row["completed"] for row in portfolio),
        }

        context = {
            "alerts": alerts_list,
            "alerts_summary": alerts_summary,
            "role": role,
            "user_name": user.name,
            "avatar_initials": avatar_initials,
            "sp_kpis": sp_kpis,
            "portfolio_json": _json.dumps(portfolio),
            "attention_json": _json.dumps(attention),
            "milestones_json": _json.dumps(milestones),
        }
        return render(request, "pages/dashboards/special_projects.html", context)

    context = {
        "alerts": alerts_list,
        "alerts_summary": alerts_summary,
        "today_context": today_context,
        "role": role,
        "user_name": user.name,
        "avatar_initials": avatar_initials,
        # Computed metrics
        "kpis": metrics["kpis"],
        "kpi_strip_items": metrics.get("kpi_strip_items", []),
        "signals": metrics["signals"],
        "priorities": metrics["priorities"],
        "weekly_progress": metrics["weekly_progress"],
        "best_interventions": metrics["best_interventions"],
        "weakest_interventions": metrics["weakest_interventions"],
        "team_targets": metrics["team_targets"],
        "priority_schools": metrics["priority_schools"],
        "cluster_performance": metrics["cluster_performance"],
        "support_overview": metrics["support_overview"],
        "budget_snapshot": metrics["budget_snapshot"],
        "execution_summary": metrics["execution_summary"],
        "upcoming_today": metrics["upcoming_today"],
        "use_dark_sidebar": False,
    }

    return render(request, "pages/dashboards/main.html", context)
