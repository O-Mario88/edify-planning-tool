from django.shortcuts import render, redirect, get_object_or_404
from apps.core.permissions import (
    require_page_permission,
    RolePermissionService,
    get_scoped_object_or_404,
)
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, HttpResponseForbidden
from django.utils import timezone

from apps.planning.services import schedule_school_visit, schedule_cluster_activity
from apps.budget.costing_service import preview as cost_preview
from apps.schools.models import School
from apps.clusters.models import Cluster
from apps.partners.models import Partner, PartnerAssignment
from apps.core.enums import (
    SsaIntervention,
    PlanningReadiness,
    SsaStatus,
    SchoolType,
    ClusterStatus,
)
from apps.core.fy import get_operational_fy, get_quarter_for_date, fy_options
from apps.geography.models import District, SubCounty
from apps.accounts.models import StaffProfile
from apps.planning.planning_service import PlanningDashboardService


@require_page_permission("planning")
def planning_dashboard_view(request):
    fy = get_operational_fy()

    # 1. Gather all filters from GET
    filters = {
        "fy": request.GET.get("fy", fy),
        "quarter": request.GET.get(
            "quarter", get_quarter_for_date(timezone.now().date())
        ),
        "district": request.GET.get("district", "All"),
        "sub_county": request.GET.get("sub_county", "All"),
        "staff": request.GET.get("staff", "All"),
        "school_type": request.GET.get("school_type", "All"),
        "planning_readiness": request.GET.get("planning_readiness", "All"),
        "ssa_status": request.GET.get("ssa_status", "All"),
        "cluster_status": request.GET.get("cluster_status", "All"),
        "partner": request.GET.get("partner", "All"),
        "q": request.GET.get("q", ""),
        "tab": request.GET.get("tab", "client"),
        "page": request.GET.get("page", 1),
        "per_page": request.GET.get("per_page", 10),
    }

    # CSV export of the currently filtered list (same pattern as /clusters).
    if request.GET.get("export", "").strip() == "csv":
        import csv
        from django.http import HttpResponse

        export_filters = dict(filters, page=1, per_page=5000)
        export_data = PlanningDashboardService.get_dashboard_data(
            request.user, export_filters
        )
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="planning_export.csv"'
        writer = csv.writer(response)
        writer.writerow(
            [
                "School ID",
                "Name",
                "District",
                "Type",
                "SSA Status",
                "Weakest Intervention",
                "Planning Readiness",
                "Recommended Action",
                "Owner",
            ]
        )
        for s in export_data["schools"]:
            writer.writerow(
                [
                    s["schoolId"],
                    s["name"],
                    s["district"],
                    s["schoolType"],
                    s["ssaStatus"],
                    s["weakestIntervention"],
                    s["planningReadiness"],
                    s["recommendedAction"],
                    s["ownerName"],
                ]
            )
        return response

    # 2. Query Dashboard data from Service
    data = PlanningDashboardService.get_dashboard_data(request.user, filters)

    # 3. Dropdowns options
    districts = District.objects.all().order_by("name")

    # Filter sub-counties by district if a district is selected
    if filters["district"] and filters["district"] != "All":
        sub_counties = SubCounty.objects.filter(
            district_id=filters["district"]
        ).order_by("name")
    else:
        sub_counties = SubCounty.objects.all().order_by("name")

    staff_members = (
        StaffProfile.objects.filter(deleted_at__isnull=True)
        .select_related("user")
        .order_by("user__name")
    )
    partners = Partner.objects.filter(
        deleted_at__isnull=True, active_status=True
    ).order_by("name")

    # Pagination pages list
    total_pages = data["total_pages"]
    from apps.core.pagination import make_pagination_window

    pages_list = make_pagination_window(int(filters["page"]), total_pages)

    showing_start = (
        (int(filters["page"]) - 1) * int(filters["per_page"]) + 1
        if data["total_count"] > 0
        else 0
    )
    showing_end = min(
        int(filters["page"]) * int(filters["per_page"]), data["total_count"]
    )

    # Query scheduled activities if tab is scheduled for FullCalendar.js representation
    scheduled_activities = []
    if filters["tab"] == "scheduled":
        from apps.activities.models import Activity

        scheduled_activities = Activity.objects.filter(
            deleted_at__isnull=True,
            status__in=[
                "planned",
                "scheduled",
                "partner_scheduled",
                "in_progress",
                "completed",
                "ia_verified",
            ],
            fy=fy,
        ).select_related("school")
        if request.user.active_role == "CCEO":
            scheduled_activities = scheduled_activities.filter(
                responsible_staff_id=request.user.id
            )

    # 4. Construct context
    context = {
        "schools": data["schools"],
        "clusters": data.get("clusters", []),
        "kpis": data["kpis"],
        "kpi_strip_items": data.get("kpi_strip_items", []),
        "cluster_planning": data["cluster_planning"],
        "core_summary": data["core_summary"],
        "total_count": data["total_count"],
        "scheduled_activities": scheduled_activities,
        # Options
        "districts": districts,
        "sub_counties": sub_counties,
        "staff_members": staff_members,
        "partners": partners,
        "fy_options": fy_options(),
        "quarter_options": ["Q1", "Q2", "Q3", "Q4"],
        "school_types": SchoolType.choices,
        "readiness_choices": PlanningReadiness.choices,
        "ssa_statuses": SsaStatus.choices,
        "cluster_statuses": ClusterStatus.choices,
        "interventions": SsaIntervention.choices,
        # Selected filters/states
        "selected_fy": filters["fy"],
        "selected_quarter": filters["quarter"],
        "selected_district": filters["district"],
        "selected_sub_county": filters["sub_county"],
        "selected_staff": filters["staff"],
        "selected_school_type": filters["school_type"],
        "selected_readiness": filters["planning_readiness"],
        "selected_ssa_status": filters["ssa_status"],
        "selected_cluster_status": filters["cluster_status"],
        "selected_partner": filters["partner"],
        "search_q": filters["q"],
        "active_tab": filters["tab"],
        # Pagination
        "page": int(filters["page"]),
        "per_page": int(filters["per_page"]),
        "total_pages": total_pages,
        "pages_list": pages_list,
        "showing_start": showing_start,
        "showing_end": showing_end,
        # Base Template choice for HTMX vs direct visits
        "base_template": "layouts/blank.html"
        if request.headers.get("HX-Request") == "true"
        and not request.headers.get("HX-Target")
        else "layouts/shell.html",
        "use_dark_sidebar": False,
        # Guards
        "can_schedule": RolePermissionService.can_schedule_activity(request.user),
        "can_assign_partner": RolePermissionService.can_assign_to_partner(request.user),
    }

    # If the target is only the school table
    if request.headers.get("HX-Target") == "schools-table-container":
        return render(request, "partials/planning/school_table.html", context)

    return render(request, "pages/planning/index.html", context)


@require_page_permission("planning")
def schedule_modal_view(request):
    if not RolePermissionService.can_schedule_activity(request.user):
        return HttpResponseForbidden(
            "Access Denied: You do not have permission to schedule activities."
        )

    cluster_id = request.GET.get("cluster_id")
    if cluster_id:
        cluster = get_scoped_object_or_404(Cluster, request.user, id=cluster_id)
        action = request.GET.get("action", "training")
        partners = Partner.objects.filter(
            deleted_at__isnull=True, active_status=True
        ).order_by("name")
        context = {
            "cluster": cluster,
            "action": action,
            "partners": partners,
            "interventions": SsaIntervention.choices,
            "drawer_size": "lg",
        }
        return render(
            request, "partials/planning/schedule_cluster_drawer.html", context
        )

    school_id = request.GET.get("school_id")
    school = get_scoped_object_or_404(
        School, request.user, Q(id=school_id) | Q(school_id=school_id)
    )

    # Resolve focus recommendations
    recommendations = []
    latest_ssa = (
        school.ssa_records.filter(deleted_at__isnull=True)
        .order_by("-date_of_ssa")
        .first()
    )
    if latest_ssa:
        scores = sorted(
            list(latest_ssa.scores.all().values("intervention", "score")),
            key=lambda s: s["score"],
        )
        for s in scores[:2]:
            code = s["intervention"]
            label = dict(SsaIntervention.choices).get(code, code)
            recommendations.append({"code": code, "label": label, "score": s["score"]})

    partners = Partner.objects.filter(
        deleted_at__isnull=True, active_status=True
    ).order_by("name")

    context = {
        "school": school,
        "recommendations": recommendations,
        "interventions": SsaIntervention.choices,
        "partners": partners,
        "drawer_size": "lg",
        # Optional project context — stamps the scheduled activity so it flows
        # into the Special Projects dashboard / analytics / My Plan.
        "project_id": request.GET.get("project_id", ""),
    }
    return render(request, "partials/planning/schedule_drawer.html", context)


@require_page_permission("planning")
def schedule_action_view(request):
    if not RolePermissionService.can_schedule_activity(request.user):
        return HttpResponseForbidden(
            "Access Denied: You do not have permission to schedule activities."
        )

    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    activity_type = request.POST.get("activity_type", "school_visit")
    school_id = request.POST.get("school_id")
    cluster_id = request.POST.get("cluster_id")
    scheduled_date = request.POST.get("scheduled_date")
    focus_intervention = request.POST.get("focus_intervention")
    purpose_type = request.POST.get("purpose_type", "focus_intervention")
    purpose_text = (
        request.POST.get("activity_goal")
        or request.POST.get("activity_purpose_text")
        or ""
    ).strip()
    expected_outcome = request.POST.get("expected_outcome", "").strip()
    expected_participants = request.POST.get("expected_participants", "").strip()
    delivery_type = request.POST.get("delivery_type", "staff")
    partner_id = request.POST.get("assigned_partner_id", "").strip()
    project_id = request.POST.get("project_id", "").strip()

    from datetime import date

    # Build payload
    is_ssa_expected = request.POST.get(
        "ssa_collection_expected"
    ) == "yes" or activity_type in [
        "baseline_ssa_visit",
        "school_visit_ssa_collection",
        "cluster_training_ssa_collection",
        "cluster_meeting_ssa_review",
        "partner_ssa_collection",
        "core_assessment_visit",
    ]
    payload = {
        "activityType": activity_type,
        "scheduledDate": scheduled_date,
        "activityPurposeText": purpose_text,
        "expectedOutcome": expected_outcome,
        "deliveryType": delivery_type,
        "ssaCollectionExpected": is_ssa_expected,
    }

    if scheduled_date:
        try:
            dt = date.fromisoformat(scheduled_date)
            payload["plannedMonth"] = dt.month
            payload["plannedWeek"] = min(5, (dt.day - 1) // 7 + 1)
        except ValueError:
            pass

    if school_id:
        payload["schoolId"] = school_id
    if cluster_id:
        payload["clusterId"] = cluster_id
    if focus_intervention:
        payload["focusIntervention"] = focus_intervention
        payload["purposeIntervention"] = focus_intervention
    if purpose_type:
        payload["purposeType"] = purpose_type
    if expected_participants:
        payload["expectedParticipants"] = int(expected_participants)
    if partner_id:
        payload["assignedPartnerId"] = partner_id
    if project_id:
        payload["projectId"] = project_id

    from apps.daily_visit_batches.exceptions import ReasonRequiredError

    try:
        if (
            activity_type == "school_visit"
            and delivery_type == "staff"
            and school_id
            and not project_id
        ):
            # Staff-conducted school visits route through DailyVisitBatchService
            # so this day's transport/lunch(/accommodation/dinner) cost pool is
            # shared with any other schools already scheduled for this staff
            # member on the same date, rather than costed for this school alone.
            from apps.daily_visit_batches.services import schedule_visits

            schedule_visits(
                school_ids=[school_id],
                scheduled_date=date.fromisoformat(scheduled_date),
                activity_common_fields=payload,
                reason=request.POST.get("reason", "").strip() or None,
                principal=request.user,
            )
            messages.success(request, "School visit scheduled successfully.")
        elif activity_type in [
            "school_visit",
            "baseline_ssa_visit",
            "school_visit_ssa_collection",
        ]:
            schedule_school_visit(payload, request.user)
            messages.success(request, "School visit scheduled successfully.")
        else:
            schedule_cluster_activity(payload, request.user)
            messages.success(request, "Cluster activity scheduled successfully.")
        # Redirect to My Plan and close drawer via client headers.
        # APPEND_SLASH is off and "/my-plan" has no trailing-slash route, so a
        # redirect to "/my-plan/" 404s — the activity saves but the user lands
        # on an error page and never sees confirmation.
        response = HttpResponse('<script>window.location.href = "/my-plan";</script>')
        response["HX-Trigger"] = "close-drawer"
        return response
    except ReasonRequiredError as e:
        return render(
            request,
            "partials/planning/reason_required_notice.html",
            {"message": str(e)},
            status=400,
        )
    except Exception as e:
        return HttpResponse(
            f'<div class="p-3 bg-rose-50 text-rose-700 rounded-lg text-[12px] font-bold">Error: {str(e)}</div>',
            status=400,
        )


@require_page_permission("planning")
def assign_partner_modal_view(request):
    if not RolePermissionService.can_assign_to_partner(request.user):
        return HttpResponseForbidden(
            "Access Denied: You do not have permission to assign to partner."
        )

    school_id = request.GET.get("school_id")
    cluster_id = request.GET.get("cluster_id")

    school = None
    cluster = None
    if school_id:
        school = get_scoped_object_or_404(
            School, request.user, Q(id=school_id) | Q(school_id=school_id)
        )
    if cluster_id:
        cluster = get_scoped_object_or_404(Cluster, request.user, id=cluster_id)

    partners = Partner.objects.filter(
        deleted_at__isnull=True, active_status=True
    ).order_by("name")

    context = {
        "school": school,
        "cluster": cluster,
        "partners": partners,
        "interventions": SsaIntervention.choices,
        "drawer_size": "md",
        "drawer_type": "center",
        # Optional project context — stamps the partner activity for the loop.
        "project_id": request.GET.get("project_id", ""),
    }
    return render(request, "partials/planning/assign_partner_drawer.html", context)


@require_page_permission("planning")
def assign_partner_action_view(request):
    if not RolePermissionService.can_assign_to_partner(request.user):
        return HttpResponseForbidden(
            "Access Denied: You do not have permission to assign to partner."
        )

    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    school_id = request.POST.get("school_id")
    cluster_id = request.POST.get("cluster_id")
    partner_id = request.POST.get("partner_id")
    activity_type = request.POST.get("activity_type", "school_visit")
    focus_intervention = request.POST.get("focus_intervention") or None
    purpose = request.POST.get("purpose", "").strip()
    notes = request.POST.get("notes", "").strip() or None
    project_id = request.POST.get("project_id", "").strip() or None

    from datetime import date as _date

    expected_date_raw = request.POST.get("expected_date", "").strip()
    expected_date = None
    if expected_date_raw:
        try:
            expected_date = _date.fromisoformat(expected_date_raw)
        except ValueError:
            pass

    try:
        partner = get_object_or_404(Partner, id=partner_id)

        from apps.activities.models import Activity
        from apps.activities.services import create as create_activity

        monitored_by_staff_id = request.user.user_id or request.user.id

        def _finalize(pa, *, school=None, cluster=None, act_type, extra_fields=None):
            """Convert a freshly-created PartnerAssignment into a properly
            validated + costed Activity via activities.services.create() —
            the SAME funnel every other scheduling path goes through
            (SSA-justification check, structured-purpose validation, the
            assert_schedulable() cost-catalogue gate), instead of writing
            the Activity via raw ORM. Only runs once a target date is
            already known — partner_schedule() (used by Core Schools) is
            what later lazily creates the Activity for a still-unscheduled
            PartnerAssignment once a date IS picked (e.g. the partner's own
            self-schedule endpoint), so no un-costed activity is ever
            persisted either way."""
            if not expected_date:
                return
            data = {
                "activityType": act_type,
                "deliveryType": "partner",
                "assignedPartnerId": partner.id,
                "focusIntervention": focus_intervention,
                "activityPurposeText": pa.purpose,
                "scheduledDate": expected_date_raw,
            }
            if school is not None:
                data["schoolId"] = school.school_id
            if cluster is not None:
                data["clusterId"] = cluster.id
            if extra_fields:
                data.update(extra_fields)
            result = create_activity(data, principal=request.user)
            # create() stamps monitored_by_staff_id from the StaffProfile CUID
            # convention (matches My Plan's own scoping) — override to the
            # raw User id this view/PartnerAssignment.assigning_staff_id and
            # the reschedule-drawer's assigning-staff lookup already use, so
            # both stay consistent for this handoff.
            Activity.objects.filter(id=result["id"]).update(
                monitored_by_staff_id=monitored_by_staff_id
            )
            # Keep the PartnerAssignment in sync with the Activity it now
            # owns instead of leaving it stuck at pending_scheduling.
            pa.status = "partner_scheduled"
            pa.scheduled_date = expected_date
            pa.save(update_fields=["status", "scheduled_date", "updated_at"])

        # Idempotency guard: a double-click or a retried htmx POST must not
        # create a second PartnerAssignment (and, worse, a second costed
        # Activity + budget line) for the same handoff. A near-identical row
        # created moments ago by the same staff member is treated as the
        # same submission, not a new one.
        DEDUP_WINDOW = timezone.timedelta(seconds=15)

        def _recent_duplicate(*, school=None, cluster=None, act_type):
            qs = PartnerAssignment.objects.filter(
                partner=partner,
                assigning_staff_id=monitored_by_staff_id,
                expected_activity_type=act_type,
                created_at__gte=timezone.now() - DEDUP_WINDOW,
            )
            qs = (
                qs.filter(school=school)
                if school is not None
                else qs.filter(cluster=cluster)
            )
            return qs.order_by("-created_at").first()

        if school_id:
            school = get_scoped_object_or_404(
                School, request.user, Q(id=school_id) | Q(school_id=school_id)
            )
            assignment_purpose = purpose or f"Assigned for {activity_type}"
            normalized_type = (
                activity_type
                if activity_type
                in ["school_visit", "follow_up_visit", "coaching_visit"]
                else "school_visit"
            )
            dup = _recent_duplicate(school=school, act_type=normalized_type)
            if dup:
                response = HttpResponse("<script>window.location.reload();</script>")
                response["HX-Trigger"] = "close-drawer"
                return response
            with transaction.atomic():
                pa = PartnerAssignment.objects.create(
                    school=school,
                    partner=partner,
                    assigning_staff_id=monitored_by_staff_id,
                    purpose=assignment_purpose,
                    focus_intervention=focus_intervention,
                    expected_activity_type=normalized_type,
                    scheduled_date=expected_date,
                    notes=notes,
                    status="pending_scheduling",
                )
                _finalize(
                    pa,
                    school=school,
                    act_type=normalized_type,
                    extra_fields={"projectId": project_id} if project_id else None,
                )
                # Update status
                school.current_fy_ssa_status = "partner_assigned"
                school.planning_readiness = "limited"
                school.save(
                    update_fields=[
                        "current_fy_ssa_status",
                        "planning_readiness",
                        "updated_at",
                    ]
                )

        if cluster_id:
            cluster = get_scoped_object_or_404(Cluster, request.user, id=cluster_id)
            assignment_purpose = purpose or f"Cluster assignment: {cluster.name}"
            act_type = (
                "cluster_meeting" if activity_type == "meeting" else "cluster_training"
            )
            dup = _recent_duplicate(cluster=cluster, act_type=act_type)
            if dup:
                response = HttpResponse("<script>window.location.reload();</script>")
                response["HX-Trigger"] = "close-drawer"
                return response
            with transaction.atomic():
                # Create PartnerAssignment for cluster
                pa = PartnerAssignment.objects.create(
                    cluster=cluster,
                    partner=partner,
                    assigning_staff_id=monitored_by_staff_id,
                    purpose=assignment_purpose,
                    focus_intervention=focus_intervention,
                    expected_activity_type=act_type,
                    scheduled_date=expected_date,
                    notes=notes,
                    status="pending_scheduling",
                )
                _finalize(pa, cluster=cluster, act_type=act_type)

                # Assign all schools in the cluster
                for school in School.objects.filter(
                    cluster_assignments__cluster=cluster, deleted_at__isnull=True
                ):
                    PartnerAssignment.objects.create(
                        school=school,
                        partner=partner,
                        assigning_staff_id=monitored_by_staff_id,
                        purpose=assignment_purpose,
                        focus_intervention=focus_intervention,
                        expected_activity_type=activity_type,
                        scheduled_date=expected_date,
                        notes=notes,
                        status="pending_scheduling",
                    )
                    school.current_fy_ssa_status = "partner_assigned"
                    school.planning_readiness = "limited"
                    school.save(
                        update_fields=[
                            "current_fy_ssa_status",
                            "planning_readiness",
                            "updated_at",
                        ]
                    )

        # Return refresh trigger and close drawer
        response = HttpResponse("<script>window.location.reload();</script>")
        response["HX-Trigger"] = "close-drawer"
        return response
    except Exception as e:
        return HttpResponse(
            f'<div class="p-3 bg-rose-50 text-rose-700 rounded-lg text-[12px] font-bold">Error: {str(e)}</div>',
            status=400,
        )


@require_page_permission("planning")
def planning_intelligence_view(request):
    school_id = request.GET.get("school_id")
    if not school_id:
        return HttpResponse(
            '<p class="text-slate-400 text-[11.5px] font-bold py-6 text-center">Select a school to view planning intelligence.</p>'
        )

    school = School.objects.filter(Q(id=school_id) | Q(school_id=school_id)).first()
    if not school:
        return HttpResponse(
            '<p class="text-rose-500 text-[11.5px] font-bold py-6 text-center">School not found.</p>'
        )

    # Fetch latest SSA date
    latest_ssa = (
        school.ssa_records.filter(deleted_at__isnull=True)
        .order_by("-date_of_ssa")
        .first()
    )
    last_ssa_date = latest_ssa.date_of_ssa.strftime("%d %b %Y") if latest_ssa else "—"

    # Weakest area
    weakest_area = "—"
    if latest_ssa:
        scores = sorted(
            list(latest_ssa.scores.all().values("intervention", "score")),
            key=lambda s: s["score"],
        )
        if scores:
            weakest_area = dict(SsaIntervention.choices).get(
                scores[0]["intervention"], scores[0]["intervention"]
            )

    # Assigned staff
    assigned_staff = "—"
    if school.account_owner_id:
        owner_profile = (
            StaffProfile.objects.filter(user_id=school.account_owner_id)
            .select_related("user")
            .first()
        )
        if owner_profile:
            assigned_staff = owner_profile.user.name

    # recommended step
    recommended_step = "Schedule visit"
    recommended_desc = "SSA is complete and the school is ready for planning."

    if school.current_fy_ssa_status != "done":
        recommended_step = "Upload SSA before planning"
        recommended_desc = "SSA has not been recorded for this FY yet."
    elif not school.cluster_id:
        recommended_step = "Assign school to cluster"
        recommended_desc = "School must be grouped in a cluster first."
    elif not school.account_owner_id:
        recommended_step = "Match staff profile"
        recommended_desc = "Staff matching is required for accountability."

    # Cluster name
    cluster_name = "—"
    if school.cluster_id:
        c_obj = Cluster.objects.filter(id=school.cluster_id).first()
        if c_obj:
            cluster_name = c_obj.name

    context = {
        "school": school,
        "last_ssa_date": last_ssa_date,
        "weakest_intervention": weakest_area,
        "assigned_staff": assigned_staff,
        "recommended_step": recommended_step,
        "recommended_desc": recommended_desc,
        "cluster_name": cluster_name,
    }
    return render(request, "partials/planning/right_panel.html", context)


@require_page_permission("planning")
def bulk_action_view(request):
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    action = request.POST.get("action")
    school_ids = request.POST.getlist("school_ids")

    if not school_ids:
        return HttpResponse("No schools selected", status=400)

    schools = School.objects.filter(school_id__in=school_ids)

    if action == "export":
        # CSV Export simple response
        import csv

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = (
            'attachment; filename="bulk_planning_export.csv"'
        )
        writer = csv.writer(response)
        writer.writerow(
            ["School ID", "Name", "District", "Cluster", "Planning Readiness"]
        )
        for s in schools:
            writer.writerow(
                [
                    s.school_id,
                    s.name,
                    s.district.name,
                    s.cluster_id or "—",
                    s.planning_readiness,
                ]
            )
        return response

    elif action == "partner":
        # Bulk Assign Partner
        if not RolePermissionService.can_assign_to_partner(request.user):
            return HttpResponseForbidden(
                "Access Denied: You do not have permission to assign to partner."
            )

        partner_id = request.POST.get("partner_id")
        if not partner_id:
            return HttpResponse(
                '<div class="p-3 bg-rose-50 text-rose-700 rounded-lg text-[12px] font-bold">Select a partner before confirming.</div>',
                status=400,
            )
        partner = get_object_or_404(Partner, id=partner_id)

        from datetime import date as _date

        from apps.activities.models import Activity
        from apps.activities.services import create as create_activity

        bulk_date_raw = request.POST.get("scheduled_date", "").strip()
        bulk_date = None
        if bulk_date_raw:
            try:
                bulk_date = _date.fromisoformat(bulk_date_raw)
            except ValueError:
                pass

        monitored_by_staff_id = request.user.user_id or request.user.id
        dedup_window = timezone.timedelta(seconds=15)

        for s in schools:
            if PartnerAssignment.objects.filter(
                school=s,
                partner=partner,
                assigning_staff_id=monitored_by_staff_id,
                expected_activity_type="school_visit",
                created_at__gte=timezone.now() - dedup_window,
            ).exists():
                continue
            with transaction.atomic():
                pa = PartnerAssignment.objects.create(
                    school=s,
                    partner=partner,
                    assigning_staff_id=monitored_by_staff_id,
                    purpose="Bulk Partner Assignment",
                    expected_activity_type="school_visit",
                    scheduled_date=bulk_date,
                    notes="Bulk Partner Assignment",
                    status="pending_scheduling",
                )
                # Same funnel as the single-item assign action
                # (activities.services.create — the SSA-justification,
                # structured-purpose, and assert_schedulable cost-catalogue
                # gates every other creation path goes through): create the
                # Activity immediately, atomically, with a real cost
                # snapshot, when a date is already known, so this handoff is
                # visible on both the partner's My Plan feed and the
                # assigning staff's Partner Monitoring bucket. No bulk date
                # collected yet? Correctly defer Activity creation to
                # schedule-time — apps.activities.services.partner_schedule
                # (used by Core Schools) is what lazily creates it off this
                # same PartnerAssignment once a date IS picked — instead of
                # ever persisting an un-costed activity.
                if bulk_date:
                    result = create_activity(
                        {
                            "activityType": "school_visit",
                            "schoolId": s.school_id,
                            "deliveryType": "partner",
                            "assignedPartnerId": partner.id,
                            "activityPurposeText": pa.purpose,
                            "scheduledDate": bulk_date_raw,
                        },
                        principal=request.user,
                    )
                    Activity.objects.filter(id=result["id"]).update(
                        monitored_by_staff_id=monitored_by_staff_id
                    )
                    pa.status = "partner_scheduled"
                    pa.scheduled_date = bulk_date
                    pa.save(update_fields=["status", "scheduled_date", "updated_at"])
                s.current_fy_ssa_status = "partner_assigned"
                s.planning_readiness = "limited"
                s.save(
                    update_fields=[
                        "current_fy_ssa_status",
                        "planning_readiness",
                        "updated_at",
                    ]
                )

        return HttpResponse("<script>window.location.reload();</script>")

    elif action == "schedule":
        # Bulk schedule staff-conducted school visits for one day — routes
        # through DailyVisitBatchService so the day's transport/lunch(/
        # accommodation/dinner) cost pool is shared and split across every
        # school selected here, not costed per school in isolation.
        if not RolePermissionService.can_schedule_activity(request.user):
            return HttpResponseForbidden(
                "Access Denied: You do not have permission to schedule activities."
            )

        from datetime import date as _date

        scheduled_date_raw = request.POST.get("scheduled_date", "").strip()
        reason = request.POST.get("reason", "").strip() or None
        if not scheduled_date_raw:
            return HttpResponse(
                '<div class="p-3 bg-rose-50 text-rose-700 rounded-lg text-[12px] font-bold">Scheduled date is required.</div>',
                status=400,
            )
        try:
            scheduled_date = _date.fromisoformat(scheduled_date_raw)
        except ValueError:
            return HttpResponse(
                '<div class="p-3 bg-rose-50 text-rose-700 rounded-lg text-[12px] font-bold">Invalid date.</div>',
                status=400,
            )

        from apps.core.exceptions import BadRequest
        from apps.daily_visit_batches.exceptions import ReasonRequiredError
        from apps.daily_visit_batches.services import schedule_visits

        try:
            schedule_visits(
                school_ids=school_ids,
                scheduled_date=scheduled_date,
                activity_common_fields={
                    "activityType": "school_visit",
                    "activityPurposeText": request.POST.get(
                        "activity_goal", "Bulk-scheduled visit"
                    ),
                    "focusIntervention": request.POST.get("focus_intervention") or None,
                    "deliveryType": "staff",
                },
                reason=reason,
                principal=request.user,
            )
            response = HttpResponse(
                '<script>window.location.href = "/my-plan";</script>'
            )
            response["HX-Trigger"] = "close-drawer"
            return response
        except ReasonRequiredError as e:
            return render(
                request,
                "partials/planning/reason_required_notice.html",
                {
                    "message": str(e),
                    "school_ids": school_ids,
                    "scheduled_date": scheduled_date_raw,
                },
                status=400,
            )
        except BadRequest as e:
            return HttpResponse(
                f'<div class="p-3 bg-rose-50 text-rose-700 rounded-lg text-[12px] font-bold">Error: {e}</div>',
                status=400,
            )

    return HttpResponse("Action processed", status=200)


@require_page_permission("planning")
def schedule_activity_form_view(request):
    action = request.GET.get("action", "visit")  # visit, training, meeting
    school_id = request.GET.get("school", "")
    cluster_id = request.GET.get("cluster", "")

    # Populate lookups
    schools = School.objects.filter(deleted_at__isnull=True).order_by("name")
    clusters = Cluster.objects.filter(deleted_at__isnull=True).order_by("name")
    partners = Partner.objects.filter(
        deleted_at__isnull=True, active_status=True
    ).order_by("name")

    selected_school = (
        School.objects.filter(Q(id=school_id) | Q(school_id=school_id)).first()
        if school_id
        else None
    )
    selected_cluster = (
        Cluster.objects.filter(id=cluster_id).first() if cluster_id else None
    )

    # Resolve focus recommendations if school chosen
    recommendations = []
    if selected_school:
        latest_ssa = (
            selected_school.ssa_records.filter(deleted_at__isnull=True)
            .order_by("-date_of_ssa")
            .first()
        )
        if latest_ssa:
            scores = sorted(
                list(latest_ssa.scores.all().values("intervention", "score")),
                key=lambda s: s["score"],
            )
            for s in scores[:2]:
                code = s["intervention"]
                label = dict(SsaIntervention.choices).get(code, code)
                recommendations.append(
                    {"code": code, "label": label, "score": s["score"]}
                )

    if request.method == "POST":
        if not RolePermissionService.can_schedule_activity(request.user):
            return HttpResponseForbidden(
                "Access Denied: You do not have permission to schedule activities."
            )

        activity_type = request.POST.get("activity_type", "")
        school_id_str = request.POST.get("school_id", "").strip()
        cluster_id_str = request.POST.get("cluster_id", "").strip()
        scheduled_date = request.POST.get("scheduled_date", "")
        focus_intervention = request.POST.get("focus_intervention", "")
        purpose_type = request.POST.get("purpose_type", "focus_intervention")
        purpose_text = request.POST.get("activity_purpose_text", "").strip()
        expected_outcome = request.POST.get("expected_outcome", "").strip()
        expected_participants = request.POST.get("expected_participants", "").strip()
        delivery_type = request.POST.get("delivery_type", "staff")
        partner_id = request.POST.get("assigned_partner_id", "").strip()

        from datetime import date

        # Build payload
        payload = {
            "activityType": activity_type,
            "scheduledDate": scheduled_date,
            "activityPurposeText": purpose_text,
            "expectedOutcome": expected_outcome,
            "deliveryType": delivery_type,
        }

        if scheduled_date:
            try:
                dt = date.fromisoformat(scheduled_date)
                payload["plannedMonth"] = dt.month
                payload["plannedWeek"] = min(5, (dt.day - 1) // 7 + 1)
            except ValueError:
                pass

        if school_id_str:
            payload["schoolId"] = school_id_str
        if cluster_id_str:
            payload["clusterId"] = cluster_id_str
        if focus_intervention:
            payload["focusIntervention"] = focus_intervention
            payload["purposeIntervention"] = focus_intervention
        if purpose_type:
            payload["purposeType"] = purpose_type
        if expected_participants:
            payload["expectedParticipants"] = int(expected_participants)
        if partner_id:
            payload["assignedPartnerId"] = partner_id

        try:
            if activity_type == "school_visit":
                schedule_school_visit(payload, request.user)
                messages.success(request, "School visit scheduled successfully.")
            else:
                schedule_cluster_activity(payload, request.user)
                messages.success(request, "Cluster activity scheduled successfully.")
            return redirect("/planning")
        except Exception as e:
            messages.error(request, f"Error: {e}")
            # fallthrough to re-render form with error message

    context = {
        "action": action,
        "schools": schools,
        "clusters": clusters,
        "partners": partners,
        "selected_school": selected_school,
        "selected_cluster": selected_cluster,
        "recommendations": recommendations,
        "interventions": SsaIntervention.choices,
    }
    return render(request, "pages/planning/schedule.html", context)


@require_page_permission("planning")
def cost_preview_partial(request):
    activity_type = request.POST.get("activity_type", "").strip()
    scheduled_date = request.POST.get("scheduled_date", "").strip()
    school_id = request.POST.get("school_id", "").strip()
    cluster_id = request.POST.get("cluster_id", "").strip()
    expected_participants = request.POST.get("expected_participants", "").strip()
    delivery_type = request.POST.get("delivery_type", "staff").strip()
    partner_id = request.POST.get("assigned_partner_id", "").strip()

    payload = {
        "activityType": activity_type,
        "plannedDate": scheduled_date,
        "deliveryType": delivery_type,
    }
    if school_id:
        # Resolve human school ID
        sch = School.objects.filter(Q(id=school_id) | Q(school_id=school_id)).first()
        if sch:
            payload["schoolId"] = sch.school_id
    if cluster_id:
        payload["clusterId"] = cluster_id
    if expected_participants:
        try:
            payload["expectedParticipants"] = int(expected_participants)
        except ValueError:
            pass
    if partner_id:
        payload["assignedPartnerId"] = partner_id

    try:
        preview_data = cost_preview(payload)
        context = {
            "preview": preview_data,
            "success": True,
        }
    except Exception as e:
        context = {
            "error_msg": str(e),
            "success": False,
        }

    return render(request, "partials/cost_preview.html", context)


@require_page_permission("planning")
def route_preview_view(request):
    """Live Route Intelligence preview for the scheduling drawer/popover.

    Read-only: same math as the persisted DailyVisitRouteBatch (location
    hierarchy → grouping → working-day feasibility → quality score → CD-target
    check → recommendations) but nothing is scheduled or persisted. Accepts
    `school_ids` (bulk popover) or `school_id` (single-visit drawer)."""
    if not RolePermissionService.can_schedule_activity(request.user):
        return HttpResponseForbidden("Access Denied")

    from apps.routes.engine import PlanningRoutePreviewService

    params = request.POST if request.method == "POST" else request.GET
    school_ids = [s for s in params.getlist("school_ids") if s.strip()]
    single = (params.get("school_id") or "").strip()
    if single and single not in school_ids:
        school_ids.append(single)
    if not school_ids:
        return render(
            request, "partials/planning/route_preview.html", {"preview": None}
        )

    from datetime import date as _date

    visit_date = None
    raw_date = (params.get("scheduled_date") or "").strip()
    if raw_date:
        try:
            visit_date = _date.fromisoformat(raw_date)
        except ValueError:
            visit_date = None

    preview = PlanningRoutePreviewService.preview(
        school_ids=school_ids,
        responsible_user=request.user.user_id,
        visit_date=visit_date,
    )
    return render(request, "partials/planning/route_preview.html", {"preview": preview})
