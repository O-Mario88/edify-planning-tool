from django.shortcuts import render, redirect, get_object_or_404
from apps.core.permissions import require_page_permission, RolePermissionService
from django.contrib import messages
from django.http import HttpResponse, HttpResponseForbidden
from django.utils import timezone
from django.core.paginator import Paginator
from django.db.models import Count, Q
from datetime import date
from apps.audit.models import AuditLog
from apps.audit.services import log as audit_log

from apps.my_plan.services import get_frontend_context as get_my_plan
from apps.activities.services import (
    get_activity,
    reschedule as reschedule_activity,
    start_completion,
    complete as complete_activity,
    submit_for_review,
    record_attendance,
    ia_confirm,
    ia_return,
    sf_kind,
)
from apps.activities.salesforce import (
    ENTRY_SOURCE_MANAGING_STAFF,
    ENTRY_SOURCE_STAFF_SELF,
    DuplicateSalesforceId,
    reserve_salesforce_id,
)
from apps.evidence.services import (
    record_upload,
    evidence_records_for_activity,
    infer_kind_from_upload,
)
from apps.core.enums import ActivityType, SsaIntervention
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
            staff_name = User.objects.get(
                Q(id=a.responsible_staff_id)
                | Q(staff_profile__id=a.responsible_staff_id)
            ).name
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
                f'<div class="p-4 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Error starting completion: {str(e)}</div>',
                status=400,
            )

    evidence_list = evidence_records_for_activity(activity_id, request.user)

    cluster_schools = []
    if a.cluster:
        from apps.schools.models import School

        cluster_schools = School.objects.filter(
            cluster_id=a.cluster_id, deleted_at__isnull=True
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
            '<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">No disbursed advance is awaiting accountability on this activity.</div>',
            status=400,
        )

    netsuite_code = request.POST.get("netsuite_code", "").strip()
    variance_note = request.POST.get("variance_note", "").strip()
    try:
        amount_spent = int(request.POST.get("amount_spent") or 0)
        amount_returned = int(request.POST.get("amount_returned") or 0)
    except ValueError:
        return HttpResponse(
            '<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Amounts must be whole UGX numbers.</div>',
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
                f'<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Receipt upload error: {str(e)}</div>',
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
            f'<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Error: {str(e)}</div>',
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
def confirm_reimbursement_receipt_action(request, activity_id):
    """The responsible employee confirms a disbursed reimbursement actually
    arrived — required before the reimbursement (and the accountability it
    settles) reaches its terminal financially-cleared state (mandate: no
    accountability closes without the employee's own receipt confirmation)."""
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        return HttpResponseForbidden(
            "Access Denied: You do not have permission to access this activity."
        )

    adv = (
        a.advance_requests.filter(status="reimbursement_disbursed")
        .order_by("-reimbursed_at")
        .first()
    )
    if request.method != "POST":
        return render(
            request,
            "partials/my_plan/confirm_reimbursement_receipt_drawer.html",
            {
                "act": get_activity(activity_id, request.user),
                "adv": adv,
                "drawer_size": "sm",
            },
        )

    if not adv:
        return HttpResponse(
            '<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">No disbursed reimbursement is awaiting receipt confirmation on this activity.</div>',
            status=400,
        )

    from apps.core.exceptions import BadRequest, Forbidden
    from apps.fund_requests import advance_service

    try:
        advance_service.confirm_reimbursement_receipt(
            adv.id,
            {"amount": request.POST.get("amount", adv.reimbursed_amount)},
            request.user,
        )
    except (BadRequest, Forbidden) as e:
        return HttpResponse(
            f'<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Error: {str(e)}</div>',
            status=400,
        )

    audit_log(
        action="reimbursement_receipt_confirmed",
        subject_kind="Activity",
        subject_id=str(a.id),
        actor_id=str(request.user.id),
        actor_role=request.user.active_role,
        success=True,
        payload={"advance_id": adv.id, "amount": adv.reimbursed_amount},
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

    # Rescheduling deliberately reuses the shared schedule drawer in its safe
    # edit mode. The existing activity remains the subject of the POST, so a
    # date change cannot accidentally create a second planned activity.
    subject_name = (
        a.school.name
        if a.school_id
        else a.cluster.name
        if a.cluster_id
        else "this activity"
    )
    activity_label = dict(ActivityType.choices).get(
        a.activity_type, a.activity_type.replace("_", " ").title()
    )
    assigning_staff_name = None
    if a.delivery_type == "partner":
        staff_id = a.monitored_by_staff_id
        if not staff_id:
            from apps.partners.models import PartnerAssignment

            assignment = None
            if a.cluster_id:
                assignment = PartnerAssignment.objects.filter(
                    cluster=a.cluster, partner_id=a.assigned_partner_id
                ).first()
            if not assignment and a.school_id:
                assignment = PartnerAssignment.objects.filter(
                    school=a.school, partner_id=a.assigned_partner_id
                ).first()
            if assignment:
                staff_id = assignment.assigning_staff_id
        if staff_id:
            from apps.accounts.models import User

            staff_user = User.objects.filter(
                Q(id=staff_id) | Q(staff_profile__id=staff_id)
            ).first()
            if staff_user:
                assigning_staff_name = staff_user.name
    context = {
        "reschedule_mode": True,
        "reschedule_activity": a,
        "reschedule_action_url": f"/my-plan/{a.id}/reschedule",
        "schedule_subject_name": subject_name,
        "recommended_activity_type": a.activity_type,
        "recommended_activity_label": activity_label,
        "assigning_staff_name": assigning_staff_name,
        "drawer_size": "md",
    }
    return render(request, "partials/planning/schedule_drawer.html", context)


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
                    f'<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Error: {str(e)}</div>',
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
                        f'<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Error starting completion: {str(e)}</div>',
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
                        f'<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Upload Error: {str(e)}</div>',
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
                                f'<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Error: {str(e)}</div>',
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
                            f'<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Error: Missing score for {enum_val.replace("_", " ").title()}</div>',
                            status=400,
                        )
                    try:
                        f_val = float(val)
                    except ValueError:
                        return HttpResponse(
                            f'<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Error: Score for {enum_val.replace("_", " ").title()} must be numeric</div>',
                            status=400,
                        )
                    if f_val < 0 or f_val > 10:
                        return HttpResponse(
                            f'<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Error: Score for {enum_val.replace("_", " ").title()} must be between 0 and 10</div>',
                            status=400,
                        )
                    scores_list.append({"intervention": enum_val, "score": f_val})

                from apps.ssa.services import upload as upload_ssa

                upload_ssa(
                    {
                        "schoolId": a.school.school_id,
                        "dateOfSsa": timezone.now().isoformat(),
                        "scores": scores_list,
                        "collectorType": "partner"
                        if a.delivery_type == "partner"
                        else "staff",
                        "collectedByPartnerId": a.assigned_partner_id,
                    },
                    request.user,
                )
                a.ssa_not_collected_reason = None
            else:
                reason = request.POST.get("ssa_not_collected_reason", "").strip()
                if not reason:
                    return HttpResponse(
                        '<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Error: Please select a reason why SSA was not collected.</div>',
                        status=400,
                    )
                a.ssa_not_collected_reason = reason
            a.save(update_fields=["ssa_not_collected_reason", "updated_at"])

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
                    f'<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Submission Error: {str(e)}</div>',
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
        try:
            start_completion(activity_id, {"notes": notes}, request.user)
        except Exception as exc:
            return HttpResponse(
                f'<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Start Error: {str(exc)}</div>',
                status=400,
            )

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
                    f'<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Error: {str(e)}</div>',
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
                '<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Error: SF ID cannot be blank.</div>',
                status=400,
            )

        if a.ia_verification_status == "confirmed":
            return HttpResponse(
                '<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Error: Salesforce ID is locked after IA confirmation. Ask IA to return the activity to make a correction.</div>',
                status=400,
            )

        kind = sf_kind(a.activity_type)
        entry_source = (
            ENTRY_SOURCE_MANAGING_STAFF
            if a.delivery_type == "partner"
            else ENTRY_SOURCE_STAFF_SELF
        )
        try:
            reserve_salesforce_id(
                activity=a,
                raw_value=salesforce_id,
                kind=kind,
                principal=request.user,
                entry_source=entry_source,
            )
        except DuplicateSalesforceId as e:
            return HttpResponse(
                f'<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">{str(e)}</div>',
                status=409,
            )
        except Exception as e:
            return HttpResponse(
                f'<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Error: {str(e)}</div>',
                status=400,
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
    has_evidence = a.evidence_status in {"uploaded", "accepted"}
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
        "in_school_training",
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
        try:
            submit_for_review(activity_id, request.user)
        except Exception as exc:
            return HttpResponse(
                f'<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Submission Error: {str(exc)}</div>',
                status=400,
            )

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
            cluster_id=a.cluster_id, deleted_at__isnull=True
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

        try:
            record_attendance(
                activity_id,
                {
                    "teachersAttended": teachers,
                    "leadersAttended": leaders,
                    "attendedSchoolIds": attended_schools,
                },
                request.user,
            )
        except Exception as exc:
            return HttpResponse(
                f'<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Attendance Error: {str(exc)}</div>',
                status=400,
            )

        if attendance_file:
            record_upload(
                principal=request.user,
                activity_id=activity_id,
                kind="attendance_form",
                file_obj=attendance_file,
            )

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
                        '<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Error: Score must be numeric</div>',
                        status=400,
                    )

        if has_scores:
            if len(scores_list) < 8:
                return HttpResponse(
                    '<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Error: All 8 scores must be provided if manual entry is selected.</div>',
                    status=400,
                )

            from apps.ssa.services import upload as upload_ssa

            upload_ssa(
                {
                    "schoolId": a.school.school_id,
                    "dateOfSsa": timezone.now().isoformat(),
                    "scores": scores_list,
                    "collectorType": "partner"
                    if a.delivery_type == "partner"
                    else "staff",
                    "collectedByPartnerId": a.assigned_partner_id,
                },
                request.user,
            )

        if ssa_file:
            record_upload(
                principal=request.user,
                activity_id=activity_id,
                kind="assessment_form",
                file_obj=ssa_file,
            )

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
    """Scoped, URL-addressable Evidence Center.

    The page previously loaded every Activity into Python and passed raw model
    objects into a table that expected dictionaries, producing blank actions.
    Filtering, counts and pagination now stay in SQL and every rendered action
    is an explicit, non-empty route.
    """
    from apps.accounts.models import StaffProfile
    from apps.core.scoping import resolve_user_scope
    from apps.partners.models import Partner

    scope = resolve_user_scope(request.user)
    activities = Activity.objects.filter(deleted_at__isnull=True)
    if scope.can_view_summary_only:
        activities = activities.none()
    elif not scope.country_scope:
        if scope.partner_ids:
            activities = activities.filter(assigned_partner_id__in=scope.partner_ids)
        elif scope.school_ids:
            staff_ids = [
                *scope.staff_ids,
                *scope.supervised_staff_ids,
                request.user.user_id,
            ]
            activities = activities.filter(
                Q(school_id__in=scope.school_ids)
                | Q(responsible_staff_id__in=[value for value in staff_ids if value])
            )
        else:
            staff_ids = [*scope.staff_ids, request.user.user_id]
            activities = activities.filter(
                responsible_staff_id__in=[value for value in staff_ids if value]
            )

    submitted_statuses = (
        "submitted_to_pl",
        "awaiting_ia_verification",
        "ia_verified",
        "accountant_confirmed",
    )
    returned_statuses = ("returned", "returned_by_pl", "returned_by_ia")
    tab_filters = {
        "pending": Q(status="completed", evidence_status="none"),
        "sf_missing": Q(evidence_status="uploaded")
        & (Q(salesforce_activity_id__isnull=True) | Q(salesforce_activity_id="")),
        "submitted": Q(status__in=submitted_statuses),
        "returned": Q(status__in=returned_statuses),
        "ia_pending": Q(
            status="awaiting_ia_verification", ia_verification_status="pending"
        ),
        "verified": Q(ia_verification_status="confirmed"),
        "partner_ev": Q(delivery_type="partner"),
    }
    tab_labels = {
        "pending": "Evidence Pending",
        "sf_missing": "SF ID Missing",
        "submitted": "Submitted",
        "returned": "Returned",
        "ia_pending": "IA Pending",
        "verified": "Verified",
        "partner_ev": "Partner Work",
    }
    active_tab = request.GET.get("tab", "pending")
    if active_tab not in tab_filters:
        active_tab = "pending"
    search_query = request.GET.get("q", "").strip()[:100]

    aggregate_fields = {
        f"{key}_count": Count("id", filter=condition)
        for key, condition in tab_filters.items()
    }
    count_values = activities.aggregate(**aggregate_fields)
    tabs = [
        {
            "key": key,
            "label": tab_labels[key],
            "count": count_values[f"{key}_count"],
        }
        for key in tab_filters
    ]

    filtered = activities.filter(tab_filters[active_tab])
    if search_query:
        filtered = filtered.filter(
            Q(school__name__icontains=search_query)
            | Q(school__school_id__icontains=search_query)
            | Q(cluster__name__icontains=search_query)
            | Q(salesforce_activity_id__icontains=search_query)
            | Q(activity_type__icontains=search_query)
        )
    page_obj = Paginator(
        filtered.select_related(
            "school",
            "school__district",
            "cluster",
            "cluster__district",
        ).order_by("-updated_at", "-id"),
        24,
    ).get_page(request.GET.get("page"))

    owner_ids = {
        value
        for activity in page_obj.object_list
        for value in (activity.responsible_staff_id, activity.assigned_partner_id)
        if value
    }
    owners = {
        profile.id: profile.user.name
        for profile in StaffProfile.objects.filter(id__in=owner_ids).select_related(
            "user"
        )
    }
    owners.update(
        {
            partner.id: partner.name
            for partner in Partner.objects.filter(id__in=owner_ids)
        }
    )

    rows = []
    for activity in page_obj.object_list:
        if active_tab == "pending":
            action = {
                "label": "Upload evidence",
                "url": f"/activities/{activity.id}/evidence",
                "drawer": True,
            }
        elif active_tab == "sf_missing":
            action = {
                "label": "Enter SF ID",
                "url": f"/activities/{activity.id}/salesforce-id",
                "drawer": True,
            }
        elif active_tab == "verified":
            action = {
                "label": "View evidence packet",
                "url": f"/activities/{activity.id}/evidence/detail",
                "drawer": False,
            }
        else:
            action = {
                "label": "View details",
                "url": f"/my-plan/{activity.id}",
                "drawer": False,
            }
        location = activity.school or activity.cluster
        district = ""
        if activity.school and activity.school.district:
            district = activity.school.district.name
        elif activity.cluster and activity.cluster.district:
            district = activity.cluster.district.name
        rows.append(
            {
                "id": activity.id,
                "activity_type": activity.get_activity_type_display(),
                "location": getattr(location, "name", "No location assigned"),
                "location_id": getattr(activity.school, "school_id", ""),
                "district": district,
                "owner": owners.get(
                    activity.assigned_partner_id
                    if activity.delivery_type == "partner"
                    else activity.responsible_staff_id,
                    "Unassigned",
                ),
                "delivery": activity.get_delivery_type_display(),
                "evidence": activity.get_evidence_status_display(),
                "verification": activity.get_ia_verification_status_display(),
                "status": activity.get_status_display(),
                "salesforce_id": activity.salesforce_activity_id,
                "updated_at": activity.updated_at,
                "action": action,
            }
        )

    context = {
        "active_tab": active_tab,
        "tabs": tabs,
        "rows": rows,
        "page_obj": page_obj,
        "search_query": search_query,
    }
    template = (
        "partials/evidence/workspace.html"
        if request.headers.get("HX-Request") == "true"
        else "pages/evidence/index.html"
    )
    return render(request, template, context)


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


@require_page_permission("my_plan")
def request_budget_amendment_action(request, activity_id):
    """POST: staff requests a date change for a finance-locked activity —
    the sanctioned Budget Amendment path the cost-snapshot lock points to."""
    from apps.budget.amendment_service import request_amendment

    if request.method == "POST":
        try:
            amendment = request_amendment(
                activity_id,
                {
                    "newDate": request.POST.get("new_date", "").strip(),
                    "reason": request.POST.get("reason", "").strip(),
                },
                request.user,
            )
            messages.success(
                request,
                f"Budget amendment submitted for review (move to {amendment.new_date}). "
                "The accountant will apply it without touching the locked cost snapshot.",
            )
        except Exception as exc:
            messages.error(request, f"Amendment request failed: {exc}")
    return redirect("/my-plan")
