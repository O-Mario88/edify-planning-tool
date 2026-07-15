from django.shortcuts import render, redirect, get_object_or_404
from apps.core.permissions import require_page_permission, RolePermissionService
from django.contrib import messages
from django.http import HttpResponse, HttpResponseForbidden
from django.utils import timezone
from datetime import date
from apps.audit.models import AuditLog
from apps.audit.services import log as audit_log

from apps.my_plan.services import get_frontend_context as get_my_plan
from apps.activities.services import (
    get_activity,
    reschedule as reschedule_activity,
    start_completion,
    complete as complete_activity,
    ia_confirm,
    ia_return,
    sf_kind,
)
from apps.activities.salesforce import is_valid_salesforce_id
from apps.evidence.services import (
    record_upload,
    evidence_records_for_activity,
    infer_kind_from_upload,
)
from apps.core.enums import SsaIntervention, ActivityStatus
from apps.pl_review.services import (
    queue as pl_queue,
    confirm as pl_confirm,
    return_activity as pl_return,
)
from apps.activities.models import Activity


def _forbid_staff_on_partner_activity(request, a):
    """Partner-owned activities are read-only for staff monitors.

    Returns an HttpResponseForbidden when the activity is partner-delivered
    and the requesting user has no partner scope covering the assigned
    partner (i.e. a staff/monitoring user). Returns None when the actor IS
    the assigned partner's user, or when the activity is staff-delivered —
    so partners keep full use of these endpoints via /partner/my-plan.
    """
    if a.delivery_type != "partner":
        return None
    from apps.core.scoping import resolve_user_scope

    scope = resolve_user_scope(request.user)
    if a.assigned_partner_id and a.assigned_partner_id in (scope.partner_ids or []):
        return None
    return HttpResponseForbidden("Partner-owned activity — staff can only monitor.")


@require_page_permission("my_plan")
def my_plan_view(request):
    """The planning dashboard main view."""
    query = {
        "fy": request.GET.get("fy"),
        "quarter": request.GET.get("quarter"),
        "month": request.GET.get("month"),
        "week": request.GET.get("week"),
        "district": request.GET.get("district"),
        "staff": request.GET.get("staff"),
        "activity_type": request.GET.get("activity_type"),
        "status": request.GET.get("status"),
        "period": request.GET.get("period", "week"),
    }

    context = get_my_plan(request.user, query)

    # CSV export of the currently filtered feed (same pattern as /clusters).
    if request.GET.get("export", "").strip() == "csv":
        import csv

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="my_plan_export.csv"'
        writer = csv.writer(response)
        writer.writerow(
            [
                "Activity ID",
                "Type",
                "School / Cluster",
                "District",
                "Planned Date",
                "Status",
                "Owner",
                "Budget (UGX)",
            ]
        )
        rows = (
            context.get("school_visits", [])
            + context.get("cluster_trainings", [])
            + context.get("cluster_meetings", [])
        )
        for a in rows:
            is_cluster = a["activity_type"].startswith("cluster")
            writer.writerow(
                [
                    a["id"],
                    a["activity_type_label"],
                    a["cluster_name"] if is_cluster else a["school_name"],
                    a["cluster_district"] if is_cluster else a["school_district"],
                    a["planned_date"] or "",
                    a["status_label"],
                    a.get("owner", ""),
                    a.get("budget_total", ""),
                ]
            )
        return response

    if request.headers.get("HX-Request") == "true":
        return render(request, "partials/my_plan/workspace.html", context)
    return render(request, "pages/my_plan/index.html", context)


@require_page_permission("my_plan")
def activity_detail_view(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)

    # Enforce record ownership/scope gating
    if not RolePermissionService.can_view_record(request.user, a):
        audit_log(
            action="unauthorized_record_access",
            subject_kind="Activity",
            subject_id=str(a.id),
            actor_id=str(request.user.id),
            actor_role=request.user.active_role,
            success=False,
            reason="User attempted to access activity detail outside their scoped schools/ownership.",
        )
        return HttpResponseForbidden(
            "Access Denied: You do not have permission to view this activity."
        )

    evidence_list = evidence_records_for_activity(activity_id, request.user)

    # Determine status details
    today = date.today()
    from apps.my_plan.services import get_activity_status_label_and_class

    status_label, status_class = get_activity_status_label_and_class(a, today)

    # Populate staff name
    from apps.accounts.models import User

    staff_name = "Unknown Staff"
    if a.responsible_staff_id:
        try:
            staff_name = User.objects.get(id=a.responsible_staff_id).name
        except User.DoesNotExist:
            pass

    context = {
        "act": a,
        "evidence_list": evidence_list,
        "status_label": status_label,
        "status_class": status_class,
        "responsible_staff_name": staff_name,
    }

    if request.headers.get("HX-Request") == "true":
        return render(request, "partials/my_plan/activity_detail_drawer.html", context)
    return render(request, "pages/my_plan/detail.html", context)


@require_page_permission("my_plan")
def complete_drawer_view(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        audit_log(
            action="unauthorized_record_access",
            subject_kind="Activity",
            subject_id=str(a.id),
            actor_id=str(request.user.id),
            actor_role=request.user.active_role,
            success=False,
            reason="User attempted to open activity completion drawer outside their scoped schools/ownership.",
        )
        return HttpResponseForbidden(
            "Access Denied: You do not have permission to access this activity drawer."
        )

    act = get_activity(activity_id, request.user)

    # Auto-start completion if in scheduling status to unlock files/codes
    if act.get("status") in (
        "scheduled",
        "in_progress",
        "assigned_to_partner",
        "partner_scheduled",
    ):
        forbidden = _forbid_staff_on_partner_activity(request, a)
        if forbidden:
            return forbidden
        try:
            start_completion(activity_id, principal=request.user)
            act = get_activity(activity_id, request.user)
        except Exception as e:
            return HttpResponse(
                f'<div class="p-4 bg-rose-50 text-rose-700 rounded-xl text-[12px] font-bold">Error starting completion: {str(e)}</div>',
                status=400,
            )

    evidence_list = evidence_records_for_activity(activity_id, request.user)

    cluster_schools = []
    if a.cluster:
        from apps.schools.models import School

        cluster_schools = School.objects.filter(
            cluster_assignments__cluster=a.cluster, deleted_at__isnull=True
        ).order_by("name")

    needs_netsuite_id = False
    disbursed_amount = None
    wfr_line = a.schedule_cost_lines.first()
    if wfr_line:
        adv = wfr_line.advance_requests.first()
        if adv and adv.status == "disbursed" and not adv.accountability_netsuite_id:
            needs_netsuite_id = True
            disbursed_amount = adv.disbursed_amount or adv.amount

    context = {
        "act": act,
        "evidence_list": evidence_list,
        "cluster_schools": cluster_schools,
        "interventions": SsaIntervention.choices,
        "drawer_size": "md",
        "needs_netsuite_id": needs_netsuite_id,
        "disbursed_amount": disbursed_amount,
    }
    return render(request, "partials/my_plan/complete_drawer.html", context)


@require_page_permission("my_plan")
def accountability_action(request, activity_id):
    """Submit accountability for a disbursed activity (GET drawer / POST submit).

    The responsible user declares actual spend, returned amount, a variance
    explanation when the numbers don't reconcile, uploads receipts, and enters
    the NetSuite Code — proof the expense entered NetSuite. Submission lands in
    ACCOUNTABILITY_PENDING for the Accountant's review; it never self-clears
    (advance_service.approve_accountability is the Accountant's action)."""
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        audit_log(
            action="unauthorized_record_access",
            subject_kind="Activity",
            subject_id=str(a.id),
            actor_id=str(request.user.id),
            actor_role=request.user.active_role,
            success=False,
            reason="User attempted the accountability drawer outside their scope.",
        )
        return HttpResponseForbidden(
            "Access Denied: You do not have permission to access this activity."
        )

    forbidden = _forbid_staff_on_partner_activity(request, a)
    if forbidden:
        return forbidden

    disbursed = list(
        a.advance_requests.filter(status="disbursed").select_related("budget_line")
    )
    total_disbursed = sum(
        (adv.disbursed_amount or adv.amount or 0) for adv in disbursed
    )

    if request.method != "POST":
        act = get_activity(activity_id, request.user)
        return render(
            request,
            "partials/my_plan/accountability_drawer.html",
            {
                "act": act,
                "disbursed_advances": disbursed,
                "total_disbursed": total_disbursed,
                "drawer_size": "md",
            },
        )

    if not disbursed:
        return HttpResponse(
            '<div class="p-3 bg-rose-50 text-rose-700 rounded-lg text-[12px] font-bold">No disbursed advance is awaiting accountability on this activity.</div>',
            status=400,
        )

    netsuite_code = request.POST.get("netsuite_code", "").strip()
    variance_note = request.POST.get("variance_note", "").strip()
    try:
        amount_spent = int(request.POST.get("amount_spent") or 0)
        amount_returned = int(request.POST.get("amount_returned") or 0)
    except ValueError:
        return HttpResponse(
            '<div class="p-3 bg-rose-50 text-rose-700 rounded-lg text-[12px] font-bold">Amounts must be whole UGX numbers.</div>',
            status=400,
        )

    receipt = request.FILES.get("receipt_file")
    if receipt:
        try:
            record_upload(
                principal=request.user,
                activity_id=activity_id,
                kind=infer_kind_from_upload(receipt),
                file_obj=receipt,
            )
        except Exception as e:
            return HttpResponse(
                f'<div class="p-3 bg-rose-50 text-rose-700 rounded-lg text-[12px] font-bold">Receipt upload error: {str(e)}</div>',
                status=400,
            )

    # One declared total, allocated per advance proportionally to what each
    # advance actually disbursed (remainder to the last so sums reconcile).
    from apps.fund_requests import advance_service

    try:
        spent_left, returned_left = amount_spent, amount_returned
        for i, adv in enumerate(disbursed):
            share = adv.disbursed_amount or adv.amount or 0
            if i == len(disbursed) - 1 or not total_disbursed:
                adv_spent, adv_returned = spent_left, returned_left
            else:
                adv_spent = round(amount_spent * share / total_disbursed)
                adv_returned = round(amount_returned * share / total_disbursed)
            spent_left -= adv_spent
            returned_left -= adv_returned
            advance_service.submit_accountability(
                adv.id,
                {
                    "netsuiteId": netsuite_code,
                    "amountSpent": adv_spent,
                    "amountReturned": adv_returned,
                    "varianceNote": variance_note,
                },
                request.user,
            )
    except Exception as e:
        return HttpResponse(
            f'<div class="p-3 bg-rose-50 text-rose-700 rounded-lg text-[12px] font-bold">Error: {str(e)}</div>',
            status=400,
        )

    audit_log(
        action="accountability_submitted",
        subject_kind="Activity",
        subject_id=str(a.id),
        actor_id=str(request.user.id),
        actor_role=request.user.active_role,
        success=True,
        payload={
            "netsuite_code": netsuite_code,
            "amount_spent": amount_spent,
            "amount_returned": amount_returned,
        },
    )
    response = HttpResponse("<script>window.location.reload();</script>")
    response["HX-Trigger"] = "close-drawer"
    return response


@require_page_permission("my_plan")
def reschedule_drawer_view(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        audit_log(
            action="unauthorized_record_access",
            subject_kind="Activity",
            subject_id=str(a.id),
            actor_id=str(request.user.id),
            actor_role=request.user.active_role,
            success=False,
            reason="User attempted to open activity reschedule drawer outside their scoped schools/ownership.",
        )
        return HttpResponseForbidden(
            "Access Denied: You do not have permission to access this activity drawer."
        )

    act = get_activity(activity_id, request.user)

    assigning_staff_name = None
    if a.delivery_type == "partner":
        staff_id = a.monitored_by_staff_id
        if not staff_id:
            from apps.partners.models import PartnerAssignment

            pa = None
            if a.cluster:
                pa = PartnerAssignment.objects.filter(
                    cluster=a.cluster, partner_id=a.assigned_partner_id
                ).first()
            if not pa and a.school:
                pa = PartnerAssignment.objects.filter(
                    school=a.school, partner_id=a.assigned_partner_id
                ).first()
            if pa:
                staff_id = pa.assigning_staff_id
        if staff_id:
            from apps.accounts.models import User

            staff_user = User.objects.filter(id=staff_id).first()
            if staff_user:
                assigning_staff_name = staff_user.name
                if not a.monitored_by_staff_id:
                    a.monitored_by_staff_id = staff_id
                    a.save(update_fields=["monitored_by_staff_id"])

    context = {
        "act": act,
        "assigning_staff_name": assigning_staff_name,
        "drawer_size": "md",
    }
    return render(request, "partials/my_plan/reschedule_drawer.html", context)


@require_page_permission("my_plan")
def reschedule_activity_action(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        audit_log(
            action="unauthorized_mutation_attempt",
            subject_kind="Activity",
            subject_id=str(a.id),
            actor_id=str(request.user.id),
            actor_role=request.user.active_role,
            success=False,
            reason="User attempted to reschedule an activity outside their scoped schools/ownership.",
        )
        return HttpResponseForbidden(
            "Access Denied: You do not have permission to reschedule this activity."
        )

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
            audit_log(
                action="reschedule_activity",
                subject_kind="Activity",
                subject_id=str(a.id),
                actor_id=str(request.user.id),
                actor_role=request.user.active_role,
                success=True,
                payload={"new_date": new_date_str, "reason": reason},
            )
            if request.headers.get("HX-Request") == "true":
                response = HttpResponse("<script>window.location.reload();</script>")
                response["HX-Trigger"] = "close-drawer"
                return response
            messages.success(request, "Activity rescheduled successfully.")
        except Exception as e:
            if request.headers.get("HX-Request") == "true":
                return HttpResponse(
                    f'<div class="p-3 bg-rose-50 text-rose-700 rounded-lg text-[12px] font-bold">Error: {str(e)}</div>',
                    status=400,
                )
            messages.error(request, f"Error: {e}")

    return redirect(f"/my-plan/{activity_id}")


@require_page_permission("my_plan")
def complete_activity_action(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(
        request.user, a
    ) or not RolePermissionService.can_upload_evidence(request.user, a):
        audit_log(
            action="unauthorized_mutation_attempt",
            subject_kind="Activity",
            subject_id=str(a.id),
            actor_id=str(request.user.id),
            actor_role=request.user.active_role,
            success=False,
            reason="User attempted to complete/upload evidence for an activity without proper authorization.",
        )
        return HttpResponseForbidden(
            "Access Denied: You are not authorized to complete this activity."
        )

    forbidden = _forbid_staff_on_partner_activity(request, a)
    if forbidden:
        return forbidden

    act = get_activity(activity_id, request.user)

    if request.method == "POST":
        # Handle start completion if still in scheduled status
        if act.get("status") in (
            "scheduled",
            "in_progress",
            "assigned_to_partner",
            "partner_scheduled",
        ):
            try:
                start_completion(activity_id, principal=request.user)
            except Exception as e:
                if request.headers.get("HX-Request") == "true":
                    return HttpResponse(
                        f'<div class="p-3 bg-rose-50 text-rose-700 rounded-lg text-[12px] font-bold">Error starting completion: {str(e)}</div>',
                        status=400,
                    )
                messages.error(request, f"Error starting completion: {e}")
                return redirect(f"/my-plan/{activity_id}")

        evidence_file = request.FILES.get("evidence_file")
        if evidence_file:
            try:
                record_upload(
                    principal=request.user,
                    activity_id=activity_id,
                    kind=infer_kind_from_upload(evidence_file),
                    file_obj=evidence_file,
                )
            except Exception as e:
                if request.headers.get("HX-Request") == "true":
                    return HttpResponse(
                        f'<div class="p-3 bg-rose-50 text-rose-700 rounded-lg text-[12px] font-bold">Upload Error: {str(e)}</div>',
                        status=400,
                    )
                messages.error(request, f"Upload error: {e}")
                return redirect(f"/my-plan/{activity_id}")

        salesforce_id = request.POST.get("salesforce_id", "").strip()
        teachers = request.POST.get("teachers_attended", 0)
        leaders = request.POST.get("leaders_attended", 0)
        other = request.POST.get("other_participants", 0)
        attended_school_ids = request.POST.getlist("attended_school_ids")

        netsuite_id = request.POST.get("netsuite_id", "").strip()
        if netsuite_id:
            wfr_line = a.schedule_cost_lines.first()
            if wfr_line:
                adv = wfr_line.advance_requests.first()
                if adv and adv.status == "disbursed":
                    # The responsible user SUBMITS accountability — this is not
                    # the closure step. It lands in ACCOUNTABILITY_PENDING; only
                    # the Accountant's approve_accountability() can close it to
                    # ACCOUNTED (see apps.fund_requests.advance_service). Do not
                    # write status/accountability_netsuite_id directly here —
                    # that would let staff self-certify their own accountability.
                    from apps.fund_requests import advance_service

                    try:
                        advance_service.submit_accountability(
                            adv.id,
                            {
                                "netsuiteId": netsuite_id,
                                "amountSpent": request.POST.get("amount_spent", 0),
                                "amountReturned": request.POST.get(
                                    "amount_returned", 0
                                ),
                                "varianceNote": request.POST.get("variance_note", ""),
                            },
                            request.user,
                        )
                    except Exception as e:
                        if request.headers.get("HX-Request") == "true":
                            return HttpResponse(
                                f'<div class="p-3 bg-rose-50 text-rose-700 rounded-lg text-[12px] font-bold">Error: {str(e)}</div>',
                                status=400,
                            )
                        messages.error(request, f"Error: {e}")
                        return redirect(f"/my-plan/{activity_id}")

        # Handle SSA collection expectations
        if a.ssa_collection_expected:
            ssa_collected = request.POST.get("ssa_collected")
            if ssa_collected == "yes":
                interventions_map = {
                    code: f"score_{code}" for code, _label in SsaIntervention.choices
                }

                scores_list = []
                for enum_val, field_name in interventions_map.items():
                    val = request.POST.get(field_name, "").strip()
                    if not val:
                        return HttpResponse(
                            f'<div class="p-3 bg-rose-50 text-rose-700 rounded-lg text-[12px] font-bold">Error: Missing score for {enum_val.replace("_", " ").title()}</div>',
                            status=400,
                        )
                    try:
                        f_val = float(val)
                    except ValueError:
                        return HttpResponse(
                            f'<div class="p-3 bg-rose-50 text-rose-700 rounded-lg text-[12px] font-bold">Error: Score for {enum_val.replace("_", " ").title()} must be numeric</div>',
                            status=400,
                        )
                    if f_val < 0 or f_val > 10:
                        return HttpResponse(
                            f'<div class="p-3 bg-rose-50 text-rose-700 rounded-lg text-[12px] font-bold">Error: Score for {enum_val.replace("_", " ").title()} must be between 0 and 10</div>',
                            status=400,
                        )
                    scores_list.append({"intervention": enum_val, "score": f_val})

                from apps.ssa.models import SsaRecord, SsaScore
                from apps.core.fy import get_operational_fy, get_quarter_for_date

                date_of_ssa = timezone.now()
                fy = get_operational_fy(date_of_ssa)
                quarter = get_quarter_for_date(date_of_ssa)
                avg_score = round(sum(s["score"] for s in scores_list) / 8, 1)

                rec = SsaRecord.objects.create(
                    school=a.school,
                    date_of_ssa=date_of_ssa,
                    fy=fy,
                    quarter=quarter,
                    average_score=avg_score,
                    uploaded_by=request.user.user_id,
                    collector_type="partner"
                    if a.delivery_type == "partner"
                    else "staff",
                    collected_by_user_id=request.user.user_id,
                    collected_by_partner_id=a.assigned_partner_id,
                    verification_status="pending",
                    verification_source="activity_collection",
                )

                SsaScore.objects.bulk_create(
                    [
                        SsaScore(
                            ssa_record=rec,
                            intervention=s["intervention"],
                            score=s["score"],
                        )
                        for s in scores_list
                    ]
                )
                a.ssa_not_collected_reason = None
            else:
                reason = request.POST.get("ssa_not_collected_reason", "").strip()
                if not reason:
                    return HttpResponse(
                        '<div class="p-3 bg-rose-50 text-rose-700 rounded-lg text-[12px] font-bold">Error: Please select a reason why SSA was not collected.</div>',
                        status=400,
                    )
                a.ssa_not_collected_reason = reason
            a.save()

        payload = {
            "salesforceId": salesforce_id,
            "teachersAttended": int(teachers) if teachers else 0,
            "leadersAttended": int(leaders) if leaders else 0,
            "otherParticipants": int(other) if other else 0,
            "attendedSchoolIds": attended_school_ids,
        }

        try:
            complete_activity(activity_id, payload, request.user)
            audit_log(
                action="complete_activity",
                subject_kind="Activity",
                subject_id=str(a.id),
                actor_id=str(request.user.id),
                actor_role=request.user.active_role,
                success=True,
                payload=payload,
            )
            if request.headers.get("HX-Request") == "true":
                response = HttpResponse("<script>window.location.reload();</script>")
                response["HX-Trigger"] = "close-drawer"
                return response
            messages.success(request, "Activity completion submitted successfully.")
        except Exception as e:
            if request.headers.get("HX-Request") == "true":
                return HttpResponse(
                    f'<div class="p-3 bg-rose-50 text-rose-700 rounded-lg text-[12px] font-bold">Submission Error: {str(e)}</div>',
                    status=400,
                )
            messages.error(request, f"Submission error: {e}")

    return redirect(f"/my-plan/{activity_id}")


@require_page_permission("planning")
def pl_queue_view(request):
    if request.user.active_role != "Program Lead":
        messages.error(request, "Access restricted to Program Leads.")
        return redirect("/dashboard")

    queue_list = pl_queue(request.user)
    context = {
        "queue": queue_list,
    }
    return render(request, "pages/my_plan/pl_queue.html", context)


@require_page_permission("planning")
def pl_confirm_action(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_review_activity(request.user, a):
        audit_log(
            action="unauthorized_mutation_attempt",
            subject_kind="Activity",
            subject_id=str(a.id),
            actor_id=str(request.user.id),
            actor_role=request.user.active_role,
            success=False,
            reason="Program Lead attempted to confirm activity completion outside their supervision.",
        )
        return HttpResponseForbidden(
            "Access Denied: You do not supervise the owner of this activity."
        )

    if request.method == "POST":
        try:
            pl_confirm(activity_id, request.user)
            audit_log(
                action="pl_approve_completion",
                subject_kind="Activity",
                subject_id=str(a.id),
                actor_id=str(request.user.id),
                actor_role=request.user.active_role,
                success=True,
            )
            messages.success(
                request, "Activity completion approved and routed to IA verification."
            )
        except Exception as e:
            messages.error(request, f"Error: {e}")

    return redirect("/pl/review-queue")


@require_page_permission("planning")
def pl_return_action(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_review_activity(request.user, a):
        audit_log(
            action="unauthorized_mutation_attempt",
            subject_kind="Activity",
            subject_id=str(a.id),
            actor_id=str(request.user.id),
            actor_role=request.user.active_role,
            success=False,
            reason="Program Lead attempted to return activity completion outside their supervision.",
        )
        return HttpResponseForbidden(
            "Access Denied: You do not supervise the owner of this activity."
        )

    if request.method == "POST":
        reason = request.POST.get("reason", "").strip()
        try:
            pl_return(activity_id, {"reason": reason}, request.user)
            audit_log(
                action="pl_return_completion",
                subject_kind="Activity",
                subject_id=str(a.id),
                actor_id=str(request.user.id),
                actor_role=request.user.active_role,
                success=True,
                payload={"reason": reason},
            )
            messages.success(request, "Activity returned to CCEO for corrections.")
        except Exception as e:
            messages.error(request, f"Error: {e}")

    return redirect("/pl/review-queue")


@require_page_permission("ia_verification_queue")
def ia_queue_view(request):
    # Query all activities awaiting IA verification
    activities = Activity.objects.filter(
        deleted_at__isnull=True, status="awaiting_ia_verification"
    ).order_by("-updated_at")
    from apps.activities.services import _serialize

    serialized_queue = [_serialize(a) for a in activities.select_related("school")]

    context = {
        "queue": serialized_queue,
    }
    return render(request, "pages/my_plan/ia_queue.html", context)


@require_page_permission("ia_verification_queue")
def ia_confirm_action(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_verify_ia(request.user, a):
        audit_log(
            action="unauthorized_mutation_attempt",
            subject_kind="Activity",
            subject_id=str(a.id),
            actor_id=str(request.user.id),
            actor_role=request.user.active_role,
            success=False,
            reason="User attempted to perform IA verification without IA permissions.",
        )
        return HttpResponseForbidden(
            "Access Denied: You are not authorized to verify activities."
        )

    if request.method == "POST":
        try:
            ia_confirm(activity_id, principal=request.user)
            audit_log(
                action="ia_verify_completion",
                subject_kind="Activity",
                subject_id=str(a.id),
                actor_id=str(request.user.id),
                actor_role=request.user.active_role,
                success=True,
            )
            messages.success(request, "Activity completion verified successfully.")
        except Exception as e:
            messages.error(request, f"Error verifying: {e}")

    return redirect("/ia/verification-queue")


@require_page_permission("ia_verification_queue")
def ia_return_action(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_verify_ia(request.user, a):
        audit_log(
            action="unauthorized_mutation_attempt",
            subject_kind="Activity",
            subject_id=str(a.id),
            actor_id=str(request.user.id),
            actor_role=request.user.active_role,
            success=False,
            reason="User attempted to perform IA return without IA permissions.",
        )
        return HttpResponseForbidden(
            "Access Denied: You are not authorized to return activities."
        )

    if request.method == "POST":
        reason = request.POST.get("reason", "").strip()
        try:
            ia_return(activity_id, {"reason": reason}, request.user)
            audit_log(
                action="ia_return_completion",
                subject_kind="Activity",
                subject_id=str(a.id),
                actor_id=str(request.user.id),
                actor_role=request.user.active_role,
                success=True,
                payload={"reason": reason},
            )
            messages.success(
                request, "Activity returned to CCEO/partner for correction."
            )
        except Exception as e:
            messages.error(request, f"Error returning: {e}")

    return redirect("/ia/verification-queue")


@require_page_permission("my_plan")
def start_activity_drawer_view(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        return HttpResponseForbidden("Access Denied.")

    context = {
        "act": a,
        "drawer_size": "sm",
    }
    return render(request, "partials/my_plan/start_drawer.html", context)


@require_page_permission("my_plan")
def start_activity_action(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        return HttpResponseForbidden("Access Denied.")

    forbidden = _forbid_staff_on_partner_activity(request, a)
    if forbidden:
        return forbidden

    if request.method == "POST":
        notes = request.POST.get("notes", "").strip()
        a.status = "in_progress"
        a.save(update_fields=["status", "updated_at"])

        audit_log(
            action="start_activity",
            subject_kind="Activity",
            subject_id=str(a.id),
            actor_id=str(request.user.id),
            actor_role=request.user.active_role,
            success=True,
            reason="Activity execution started",
            payload={"notes": notes},
        )

        if request.headers.get("HX-Request") == "true":
            response = HttpResponse("<script>window.location.reload();</script>")
            response["HX-Trigger"] = "close-drawer"
            return response

    return redirect(f"/my-plan/{activity_id}")


@require_page_permission("my_plan")
def complete_activity_drawer_view(request, activity_id):
    return complete_drawer_view(request, activity_id)


@require_page_permission("my_plan")
def evidence_upload_drawer_view(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        return HttpResponseForbidden("Access Denied.")

    evidence_list = evidence_records_for_activity(activity_id, request.user)
    context = {
        "act": a,
        "evidence_list": evidence_list,
        "drawer_size": "sm",
    }
    return render(request, "partials/my_plan/evidence_drawer.html", context)


@require_page_permission("my_plan")
def evidence_upload_action(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        return HttpResponseForbidden("Access Denied.")

    forbidden = _forbid_staff_on_partner_activity(request, a)
    if forbidden:
        return forbidden

    if request.method == "POST":
        evidence_file = request.FILES.get("evidence_file")
        if evidence_file:
            try:
                record_upload(
                    principal=request.user,
                    activity_id=activity_id,
                    kind=infer_kind_from_upload(evidence_file),
                    file_obj=evidence_file,
                )
                a.evidence_status = "uploaded"
                a.save(update_fields=["evidence_status", "updated_at"])

                audit_log(
                    action="upload_evidence",
                    subject_kind="Activity",
                    subject_id=str(a.id),
                    actor_id=str(request.user.id),
                    actor_role=request.user.active_role,
                    success=True,
                    reason="Evidence file uploaded",
                )
            except Exception as e:
                return HttpResponse(
                    f'<div class="p-3 bg-rose-50 text-rose-700 rounded-lg text-[12px] font-bold">Error: {str(e)}</div>',
                    status=400,
                )

        if request.headers.get("HX-Request") == "true":
            response = HttpResponse("<script>window.location.reload();</script>")
            response["HX-Trigger"] = "close-drawer"
            return response

    return redirect(f"/my-plan/{activity_id}")


@require_page_permission("my_plan")
def salesforce_id_drawer_view(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        return HttpResponseForbidden("Access Denied.")

    context = {
        "act": a,
        "drawer_size": "sm",
    }
    return render(request, "partials/my_plan/salesforce_id_drawer.html", context)


@require_page_permission("my_plan")
def salesforce_id_action(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        return HttpResponseForbidden("Access Denied.")

    forbidden = _forbid_staff_on_partner_activity(request, a)
    if forbidden:
        return forbidden

    if request.method == "POST":
        salesforce_id = request.POST.get("salesforce_id", "").strip()
        if not salesforce_id:
            return HttpResponse(
                '<div class="p-3 bg-rose-50 text-rose-700 rounded-lg text-[12px] font-bold">Error: SF ID cannot be blank.</div>',
                status=400,
            )

        if a.ia_verification_status == "confirmed":
            return HttpResponse(
                '<div class="p-3 bg-rose-50 text-rose-700 rounded-lg text-[12px] font-bold">Error: Salesforce ID is locked after IA confirmation. Ask IA to return the activity to make a correction.</div>',
                status=400,
            )

        kind = sf_kind(a.activity_type)
        if not is_valid_salesforce_id(salesforce_id, kind):
            prefix = "SV-" if kind == "visit" else "TS-"
            return HttpResponse(
                f'<div class="p-3 bg-rose-50 text-rose-700 rounded-lg text-[12px] font-bold">Error: Invalid Salesforce ID format. Expected a {prefix} prefixed ID.</div>',
                status=400,
            )

        a.salesforce_activity_id = salesforce_id
        a.save(update_fields=["salesforce_activity_id", "updated_at"])

        audit_log(
            action="enter_salesforce_id",
            subject_kind="Activity",
            subject_id=str(a.id),
            actor_id=str(request.user.id),
            actor_role=request.user.active_role,
            success=True,
            reason="Salesforce ID entered",
            payload={"salesforce_id": salesforce_id},
        )

        if request.headers.get("HX-Request") == "true":
            response = HttpResponse("<script>window.location.reload();</script>")
            response["HX-Trigger"] = "close-drawer"
            return response

    return redirect(f"/my-plan/{activity_id}")


@require_page_permission("my_plan")
def submit_for_review_drawer_view(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        return HttpResponseForbidden("Access Denied.")

    # Build Checklist
    has_evidence = a.evidence_status == "uploaded"
    has_sf_id = bool(a.salesforce_activity_id)

    ssa_required = a.activity_type in [
        "baseline_ssa_visit",
        "school_visit_ssa_collection",
        "partner_ssa_collection",
        "cluster_training_ssa_collection",
    ]
    has_ssa = False
    if ssa_required:
        if a.school and a.school.current_fy_ssa_status == "done":
            has_ssa = True

    has_participants = True
    if a.activity_type in [
        "training",
        "cluster_training",
        "cluster_meeting",
        "core_training",
    ]:
        has_participants = (a.teachers_attended or 0) + (a.leaders_attended or 0) > 0

    all_ready = (
        has_evidence
        and has_sf_id
        and (not ssa_required or has_ssa)
        and has_participants
    )

    context = {
        "act": a,
        "has_evidence": has_evidence,
        "has_sf_id": has_sf_id,
        "ssa_required": ssa_required,
        "has_ssa": has_ssa,
        "has_participants": has_participants,
        "all_ready": all_ready,
        "drawer_size": "sm",
    }
    return render(request, "partials/my_plan/submit_drawer.html", context)


@require_page_permission("my_plan")
def submit_for_review_action(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        return HttpResponseForbidden("Access Denied.")

    forbidden = _forbid_staff_on_partner_activity(request, a)
    if forbidden:
        return forbidden

    if request.method == "POST":
        # Route to the real ActivityStatus workflow state: a CCEO's completion
        # needs supervisory PL review first (-> pl_review_queue); everyone
        # else's goes straight to the IA verification queue. Mirrors the
        # identical routing in activities.services.complete().
        is_cceo = request.user.active_role == "CCEO"
        a.status = (
            ActivityStatus.SUBMITTED_TO_PL
            if is_cceo
            else ActivityStatus.AWAITING_IA_VERIFICATION
        )
        a.save(update_fields=["status", "updated_at"])

        audit_log(
            action="submit_for_review",
            subject_kind="Activity",
            subject_id=str(a.id),
            actor_id=str(request.user.id),
            actor_role=request.user.active_role,
            success=True,
            reason="Activity submitted for PL/IA review",
        )

        if request.headers.get("HX-Request") == "true":
            response = HttpResponse("<script>window.location.reload();</script>")
            response["HX-Trigger"] = "close-drawer"
            return response

    return redirect(f"/my-plan/{activity_id}")


@require_page_permission("my_plan")
def activity_timeline_drawer_view(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        return HttpResponseForbidden("Access Denied.")

    logs = AuditLog.objects.filter(
        subject_kind="Activity", subject_id=str(a.id)
    ).order_by("-created_at")
    context = {
        "act": a,
        "logs": logs,
        "drawer_size": "md",
    }
    return render(request, "partials/my_plan/timeline_drawer.html", context)


@require_page_permission("my_plan")
def evidence_packet_view(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        return HttpResponseForbidden("Access Denied.")

    evidence_list = evidence_records_for_activity(activity_id, request.user)
    logs = AuditLog.objects.filter(
        subject_kind="Activity", subject_id=str(a.id)
    ).order_by("-created_at")

    context = {
        "act": a,
        "evidence_list": evidence_list,
        "logs": logs,
    }
    return render(request, "pages/my_plan/evidence_packet.html", context)


@require_page_permission("my_plan")
def attendance_upload_drawer_view(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        return HttpResponseForbidden("Access Denied.")

    cluster_schools = []
    if a.cluster:
        from apps.schools.models import School

        cluster_schools = School.objects.filter(
            cluster_assignments__cluster=a.cluster, deleted_at__isnull=True
        ).order_by("name")

    context = {
        "act": a,
        "drawer_size": "sm",
        "cluster_schools": cluster_schools,
    }
    return render(request, "partials/my_plan/attendance_drawer.html", context)


@require_page_permission("my_plan")
def attendance_upload_action(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        return HttpResponseForbidden("Access Denied.")

    forbidden = _forbid_staff_on_partner_activity(request, a)
    if forbidden:
        return forbidden

    if request.method == "POST":
        teachers = request.POST.get("teachers_attended", 0)
        leaders = request.POST.get("leaders_attended", 0)
        attendance_file = request.FILES.get("attendance_file")
        notes = request.POST.get("notes", "").strip()
        attended_schools = request.POST.getlist("attended_schools")

        a.teachers_attended = int(teachers) if teachers else 0
        a.leaders_attended = int(leaders) if leaders else 0
        a.attended_school_ids = list(attended_schools)
        a.status = "completed"
        a.save(
            update_fields=[
                "teachers_attended",
                "leaders_attended",
                "attended_school_ids",
                "status",
                "updated_at",
            ]
        )

        if attendance_file:
            record_upload(
                principal=request.user,
                activity_id=activity_id,
                kind="attendance_form",
                file_obj=attendance_file,
            )
            a.evidence_status = "uploaded"
            a.save(update_fields=["evidence_status", "updated_at"])

        audit_log(
            action="upload_attendance",
            subject_kind="Activity",
            subject_id=str(a.id),
            actor_id=str(request.user.id),
            actor_role=request.user.active_role,
            success=True,
            reason="Attendance file and headcount uploaded",
            payload={"teachers": teachers, "leaders": leaders, "notes": notes},
        )

        if request.headers.get("HX-Request") == "true":
            response = HttpResponse("<script>window.location.reload();</script>")
            response["HX-Trigger"] = "close-drawer"
            return response

    return redirect(f"/my-plan/{activity_id}")


@require_page_permission("my_plan")
def ssa_evidence_upload_drawer_view(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        return HttpResponseForbidden("Access Denied.")

    context = {
        "act": a,
        "interventions": SsaIntervention.choices,
        "drawer_size": "sm",
    }
    return render(request, "partials/my_plan/ssa_upload_drawer.html", context)


@require_page_permission("my_plan")
def ssa_evidence_upload_action(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        return HttpResponseForbidden("Access Denied.")

    if request.method == "POST":
        ssa_file = request.FILES.get("ssa_file")
        notes = request.POST.get("notes", "").strip()

        # Parse scores if provided — derived from the canonical enum so the
        # field names always match the SsaScore.intervention choices.
        score_fields = [f"score_{code}" for code, _label in SsaIntervention.choices]
        scores_list = []
        has_scores = False

        for sf in score_fields:
            val = request.POST.get(sf, "").strip()
            if val:
                has_scores = True
                try:
                    scores_list.append(
                        {"intervention": sf.replace("score_", ""), "score": float(val)}
                    )
                except ValueError:
                    return HttpResponse(
                        '<div class="p-3 bg-rose-50 text-rose-700 rounded-lg text-[12px] font-bold">Error: Score must be numeric</div>',
                        status=400,
                    )

        if has_scores:
            if len(scores_list) < 8:
                return HttpResponse(
                    '<div class="p-3 bg-rose-50 text-rose-700 rounded-lg text-[12px] font-bold">Error: All 8 scores must be provided if manual entry is selected.</div>',
                    status=400,
                )

            from apps.ssa.models import SsaRecord, SsaScore
            from apps.core.fy import get_operational_fy, get_quarter_for_date
            from django.utils import timezone

            date_of_ssa = timezone.now()
            fy = get_operational_fy(date_of_ssa)
            quarter = get_quarter_for_date(date_of_ssa)
            avg_score = round(sum(s["score"] for s in scores_list) / 8, 1)

            rec = SsaRecord.objects.create(
                school=a.school,
                date_of_ssa=date_of_ssa,
                fy=fy,
                quarter=quarter,
                average_score=avg_score,
                uploaded_by=request.user.user_id,
                collector_type="partner" if a.delivery_type == "partner" else "staff",
                collected_by_user_id=request.user.user_id,
                collected_by_partner_id=a.assigned_partner_id,
                verification_status="pending",
                verification_source="activity_collection",
            )

            SsaScore.objects.bulk_create(
                [
                    SsaScore(
                        ssa_record=rec, intervention=s["intervention"], score=s["score"]
                    )
                    for s in scores_list
                ]
            )

        if ssa_file:
            record_upload(
                principal=request.user,
                activity_id=activity_id,
                kind="assessment_form",
                file_obj=ssa_file,
            )
            a.evidence_status = "uploaded"
            a.save(update_fields=["evidence_status", "updated_at"])

        audit_log(
            action="upload_ssa",
            subject_kind="Activity",
            subject_id=str(a.id),
            actor_id=str(request.user.id),
            actor_role=request.user.active_role,
            success=True,
            reason="SSA baseline scores or form uploaded",
            payload={"notes": notes},
        )

        if request.headers.get("HX-Request") == "true":
            response = HttpResponse("<script>window.location.reload();</script>")
            response["HX-Trigger"] = "close-drawer"
            return response

    return redirect(f"/my-plan/{activity_id}")


@require_page_permission("evidence_center")
def evidence_center_view(request):
    """Evidence Center showing tabs of different evidence/verification states."""
    activities = (
        Activity.objects.filter(deleted_at__isnull=True)
        .select_related("school")
        .order_by("-updated_at")
    )

    pending = [
        a for a in activities if a.status == "completed" and a.evidence_status == "none"
    ]
    sf_missing = [
        a
        for a in activities
        if a.evidence_status == "uploaded" and not a.salesforce_activity_id
    ]
    submitted = [
        a
        for a in activities
        if a.status
        in (
            "submitted_to_pl",
            "awaiting_ia_verification",
            "ia_verified",
            "accountant_confirmed",
        )
    ]
    returned = [
        a
        for a in activities
        if a.status in ("returned", "returned_by_pl", "returned_by_ia")
    ]
    ia_pending = [
        a
        for a in activities
        if a.status == "awaiting_ia_verification"
        and a.ia_verification_status == "pending"
    ]
    verified = [a for a in activities if a.ia_verification_status == "confirmed"]
    partner_ev = [a for a in activities if a.delivery_type == "partner"]

    context = {
        "pending": pending,
        "sf_missing": sf_missing,
        "submitted": submitted,
        "returned": returned,
        "ia_pending": ia_pending,
        "verified": verified,
        "partner_ev": partner_ev,
    }
    return render(request, "pages/evidence/index.html", context)


@require_page_permission("evidence_center")
def returned_evidence_view(request):
    """View specifically returned evidence items."""
    activities = (
        Activity.objects.filter(
            deleted_at__isnull=True,
            status__in=[
                "returned",
                "returned_by_pl",
                "returned_by_ia",
            ],
        )
        .select_related("school")
        .order_by("-updated_at")
    )
    context = {
        "returned_activities": activities,
    }
    return render(request, "pages/evidence/returned.html", context)


@require_page_permission("disbursements")
def accounts_activity_evidence_view(request, activity_id):
    """Read-only view of activity evidence for Accountants. Gated by the
    finance page permission — the previous "my_plan" gate excluded the
    Accountant role this page exists for. Object-level finance scoping
    (Accountant reaches only money-movement activities) is enforced inside
    evidence_records_for_activity."""
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    evidence_list = evidence_records_for_activity(activity_id, request.user)

    context = {
        "act": a,
        "evidence_list": evidence_list,
    }
    return render(request, "pages/accounts/activity_evidence.html", context)
