from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Avg, Count, Sum
from django.utils import timezone
from datetime import datetime, timedelta

from apps.activities.models import Activity
from apps.schools.models import School
from apps.clusters.models import Cluster
from apps.fund_requests.models import FundRequest, WeeklyFundRequest
from apps.activities.models import ActivityScheduleCostLine
from apps.ssa.models import SsaRecord
from apps.accounts.models import User
from apps.command_center import services as cc_services

@login_required(login_url="/login")
def dashboard_view(request):
    user = request.user
    role = user.active_role
    
    # Common alerts
    alerts_list = cc_services.alerts(user)
    alerts_summary = cc_services.alerts_summary(user)
    today_context = cc_services.today(user)
    
    context = {
        "alerts": alerts_list,
        "alerts_summary": alerts_summary,
        "today_context": today_context,
        "role": role,
    }

    if role == "CCEO":
        return render_cceo_dashboard(request, context)
    elif role == "CountryProgramLead":
        return render_pl_dashboard(request, context)
    elif role == "CountryDirector":
        return render_cd_dashboard(request, context)
    elif role == "ProgramAccountant":
        return render_accountant_dashboard(request, context)
    else:
        # Fallback general dashboard
        return render(request, "pages/dashboards/general.html", context)

def render_cceo_dashboard(request, context):
    user = request.user
    now = timezone.now().date()
    
    # 1. Today's and this week's visits
    start_week = now - timedelta(days=now.weekday())
    end_week = start_week + timedelta(days=6)
    
    week_activities = Activity.objects.filter(
        responsible_staff_id=user.id,
        planned_date__range=[start_week, end_week],
        deleted_at__isnull=True
    ).order_by("planned_date")
    
    # 2. Overdue activities
    overdue_activities = Activity.objects.filter(
        responsible_staff_id=user.id,
        planned_date__lt=now,
        status__in=["scheduled", "started"],
        deleted_at__isnull=True
    ).order_by("planned_date")
    
    # 3. Schools needing SSA (SSA not done yet)
    from apps.core.scoping import resolve_user_scope
    scope = resolve_user_scope(user)
    
    schools_no_ssa = School.objects.filter(
        id__in=scope.school_ids,
        deleted_at__isnull=True
    ).exclude(current_fy_ssa_status="done")
    
    # 4. Evidence pending
    evidence_pending = Activity.objects.filter(
        responsible_staff_id=user.id,
        status="completed",
        evidence__isnull=True,
        deleted_at__isnull=True
    )
    
    # 5. Pending advance confirmation
    from apps.fund_requests.models import AdvanceRequest, AdvanceRequestStatus
    pending_advances = AdvanceRequest.objects.filter(
        status=AdvanceRequestStatus.PENDING_RESPONSIBLE_CONFIRMATION,
        responsible_user_id=user.id
    )

    context.update({
        "week_activities": week_activities,
        "overdue_activities": overdue_activities,
        "schools_no_ssa": schools_no_ssa,
        "evidence_pending": evidence_pending,
        "pending_advances": pending_advances,
    })
    return render(request, "pages/dashboards/cceo.html", context)

def render_pl_dashboard(request, context):
    user = request.user
    
    # 1. Activities pending PL review
    pending_reviews = Activity.objects.filter(
        status="pending_pl_review",
        deleted_at__isnull=True
    ).select_related("school", "cluster").order_by("planned_date")
    
    # 2. CCEOs needing support (CCEOs with most overdue activities)
    cceos_overdue = User.objects.filter(
        roles__contains=["CCEO"],
        status="active"
    ).annotate(
        overdue_count=Count(
            "activities", 
            filter=Q(
                activities__planned_date__lt=timezone.now().date(),
                activities__status__in=["scheduled", "started"],
                activities__deleted_at__isnull=True
            )
        )
    ).filter(overdue_count__gt=0).order_by("-overdue_count")

    # 3. Clusters with weak SSA
    from apps.core.fy import get_operational_fy
    fy = get_operational_fy()
    weak_clusters = Cluster.objects.annotate(
        avg_ssa=Avg("schools__ssa_records__average_score", filter=Q(schools__ssa_records__fy=fy, schools__ssa_records__deleted_at__isnull=True))
    ).filter(avg_ssa__lt=5.5).order_by("avg_ssa")
    
    # 4. Fund requests waiting approval
    pending_funds = WeeklyFundRequest.objects.filter(
        status="pending_pl_approval"
    ).order_by("-week_start_date")

    context.update({
        "pending_reviews": pending_reviews,
        "cceos_overdue": cceos_overdue,
        "weak_clusters": weak_clusters,
        "pending_funds": pending_funds,
    })
    return render(request, "pages/dashboards/pl.html", context)

def render_cd_dashboard(request, context):
    # 1. Country performance metrics
    total_schools = School.objects.filter(deleted_at__isnull=True).count()
    completed_visits = Activity.objects.filter(activity_type="school_visit", status="completed", deleted_at__isnull=True).count()
    from apps.core.fy import get_operational_fy
    fy = get_operational_fy()
    avg_national_ssa = SsaRecord.objects.filter(fy=fy, deleted_at__isnull=True).aggregate(Avg("average_score"))["average_score__avg"] or 0
    
    # 2. District risk summary
    district_risks = School.objects.filter(deleted_at__isnull=True).values("district__name").annotate(
        avg_ssa=Avg("ssa_records__average_score", filter=Q(ssa_records__fy=fy, ssa_records__deleted_at__isnull=True)),
        total=Count("id", distinct=True),
        missing_ssa=Count("id", filter=~Q(current_fy_ssa_status="done"), distinct=True)
    ).order_by("avg_ssa")
    
    # 3. Budget exposure
    budget_summary = WeeklyFundRequest.objects.aggregate(
        total_requested=Sum("total_amount", filter=Q(status="pending_cd_approval")),
        total_disbursed=Sum("disbursed_amount", filter=Q(status="disbursed")),
        total_approved=Sum("total_amount", filter=Q(status__in=["pending_disbursement", "disbursed"]))
    )
    
    # 4. Pending approvals
    pending_funds = WeeklyFundRequest.objects.filter(
        status="pending_cd_approval"
    ).order_by("-week_start_date")

    context.update({
        "total_schools": total_schools,
        "completed_visits": completed_visits,
        "avg_national_ssa": round(avg_national_ssa, 2),
        "district_risks": district_risks,
        "budget_summary": budget_summary,
        "pending_funds": pending_funds,
    })
    return render(request, "pages/dashboards/cd.html", context)

def render_accountant_dashboard(request, context):
    # 1. Ready for disbursement (approved but not yet disbursed)
    ready_disburse = WeeklyFundRequest.objects.filter(
        status="pending_disbursement"
    ).order_by("-week_start_date")
    
    # 2. Pending CCEO / responsible confirmation
    pending_confirms = WeeklyFundRequest.objects.filter(
        status="pending_responsible_confirmation"
    ).order_by("-week_start_date")
    
    # 3. Accountability overdue (completed activities without verified evidence after 5 days)
    five_days_ago = timezone.now().date() - timedelta(days=5)
    overdue_accountabilities = Activity.objects.filter(
        status="completed",
        planned_date__lt=five_days_ago,
        evidence__isnull=True,
        deleted_at__isnull=True
    ).select_related("school").order_by("planned_date")
    
    context.update({
        "ready_disburse": ready_disburse,
        "pending_confirms": pending_confirms,
        "overdue_accountabilities": overdue_accountabilities,
    })
    return render(request, "pages/dashboards/accountant.html", context)
