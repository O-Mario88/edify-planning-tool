from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from datetime import date

from apps.my_plan.services import get as get_my_plan
from apps.activities.services import (
    get_activity,
    reschedule as reschedule_activity,
    start_completion,
    complete as complete_activity,
    ia_confirm
)
from apps.evidence.services import (
    record_upload,
    list_for_activity
)
from apps.pl_review.services import (
    queue as pl_queue,
    confirm as pl_confirm,
    return_activity as pl_return
)
from apps.activities.models import Activity
from apps.core.fy import get_operational_fy, get_quarter_for_date

@login_required(login_url="/login")
def my_plan_view(request):
    fy = get_operational_fy()
    period = request.GET.get("period", "month")
    
    # Defaults
    today = date.today()
    month = request.GET.get("month", today.month)
    week = request.GET.get("week", "")
    quarter = request.GET.get("quarter", get_quarter_for_date())

    query = {
        "fy": fy,
        "period": period,
    }
    if month:
        query["month"] = int(month)
    if week:
        query["week"] = int(week)
    if quarter:
        query["quarter"] = quarter

    feed = get_my_plan(request.user, query)
    
    # Generate pagination or options collections
    months = [{"val": m, "label": date(2000, m, 1).strftime("%B")} for m in range(1, 13)]
    quarters = ["Q1", "Q2", "Q3", "Q4"]
    weeks = [1, 2, 3, 4, 5]

    context = {
        "feed": feed,
        "period": period,
        "selected_month": int(month) if month else None,
        "selected_week": int(week) if week else None,
        "selected_quarter": quarter,
        "months": months,
        "quarters": quarters,
        "weeks": weeks,
    }
    return render(request, "pages/my_plan/index.html", context)

@login_required(login_url="/login")
def activity_detail_view(request, activity_id):
    act = get_activity(activity_id, request.user)
    evidence_list = list_for_activity(activity_id, request.user)
    context = {
        "act": act,
        "evidence_list": evidence_list,
    }
    return render(request, "pages/my_plan/detail.html", context)

@login_required(login_url="/login")
def reschedule_activity_action(request, activity_id):
    if request.method == "POST":
        new_date_str = request.POST.get("scheduled_date", "").strip()
        reason = request.POST.get("reason", "").strip()
        
        payload = {
            "scheduledDate": new_date_str,
            "reason": reason,
        }
        if new_date_str:
            try:
                dt = date.fromisoformat(new_date_str)
                payload["plannedMonth"] = dt.month
                payload["plannedWeek"] = min(5, (dt.day - 1) // 7 + 1)
            except ValueError:
                pass

        try:
            reschedule_activity(activity_id, payload, request.user)
            messages.success(request, "Activity rescheduled successfully.")
        except Exception as e:
            messages.error(request, f"Error: {e}")
            
    return redirect(f"/my-plan/{activity_id}")

@login_required(login_url="/login")
def complete_activity_action(request, activity_id):
    act = get_activity(activity_id, request.user)
    
    if request.method == "POST":
        # Handle start completion if still in scheduled status
        if act.get("status") in ("scheduled", "in_progress", "assigned_to_partner", "partner_scheduled"):
            try:
                start_completion(activity_id, principal=request.user)
            except Exception as e:
                messages.error(request, f"Error starting completion: {e}")
                return redirect(f"/my-plan/{activity_id}")

        evidence_file = request.FILES.get("evidence_file")
        if evidence_file:
            try:
                record_upload(principal=request.user, activity_id=activity_id, kind="photo", file_obj=evidence_file)
                messages.success(request, "Evidence file uploaded successfully.")
            except Exception as e:
                messages.error(request, f"Upload error: {e}")
            return redirect(f"/my-plan/{activity_id}")

        salesforce_id = request.POST.get("salesforce_id", "").strip()
        teachers = request.POST.get("teachers_attended", 0)
        leaders = request.POST.get("leaders_attended", 0)
        other = request.POST.get("other_participants", 0)

        payload = {
            "salesforceId": salesforce_id,
            "teachersAttended": int(teachers) if teachers else 0,
            "leadersAttended": int(leaders) if leaders else 0,
            "otherParticipants": int(other) if other else 0,
        }

        try:
            complete_activity(activity_id, payload, request.user)
            messages.success(request, "Activity completion submitted successfully.")
        except Exception as e:
            messages.error(request, f"Submission error: {e}")

    return redirect(f"/my-plan/{activity_id}")

@login_required(login_url="/login")
def pl_queue_view(request):
    if request.user.active_role != "CountryProgramLead":
        messages.error(request, "Access restricted to Program Leads.")
        return redirect("/dashboard")
    
    queue_list = pl_queue(request.user)
    context = {
        "queue": queue_list,
    }
    return render(request, "pages/my_plan/pl_queue.html", context)

@login_required(login_url="/login")
def pl_confirm_action(request, activity_id):
    if request.user.active_role != "CountryProgramLead":
        messages.error(request, "Access restricted to Program Leads.")
        return redirect("/dashboard")
        
    if request.method == "POST":
        try:
            pl_confirm(activity_id, request.user)
            messages.success(request, "Activity completion approved and routed to IA verification.")
        except Exception as e:
            messages.error(request, f"Error: {e}")
            
    return redirect("/pl/review-queue")

@login_required(login_url="/login")
def pl_return_action(request, activity_id):
    if request.user.active_role != "CountryProgramLead":
        messages.error(request, "Access restricted to Program Leads.")
        return redirect("/dashboard")

    if request.method == "POST":
        reason = request.POST.get("reason", "").strip()
        try:
            pl_return(activity_id, {"reason": reason}, request.user)
            messages.success(request, "Activity returned to CCEO for corrections.")
        except Exception as e:
            messages.error(request, f"Error: {e}")
            
    return redirect("/pl/review-queue")

@login_required(login_url="/login")
def ia_queue_view(request):
    if request.user.active_role != "ImpactAssessment":
        messages.error(request, "Access restricted to Impact Assessment.")
        return redirect("/dashboard")
        
    # Query all activities awaiting IA verification
    activities = Activity.objects.filter(deleted_at__isnull=True, status="awaiting_ia_verification").order_by("-updated_at")
    from apps.activities.services import _serialize
    serialized_queue = [_serialize(a) for a in activities.select_related("school")]

    context = {
        "queue": serialized_queue,
    }
    return render(request, "pages/my_plan/ia_queue.html", context)

@login_required(login_url="/login")
def ia_confirm_action(request, activity_id):
    if request.user.active_role != "ImpactAssessment":
        messages.error(request, "Access restricted to Impact Assessment.")
        return redirect("/dashboard")
        
    if request.method == "POST":
        try:
            ia_confirm(activity_id, principal=request.user)
            messages.success(request, "Activity completion verified successfully.")
        except Exception as e:
            messages.error(request, f"Error verifying: {e}")
            
    return redirect("/ia/verification-queue")
