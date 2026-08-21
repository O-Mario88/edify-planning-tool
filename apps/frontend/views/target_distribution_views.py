"""Uganda Master Priority Plan — distribution workspaces.

Two surfaces over one engine (apps.hr.target_distribution):

- /target-distribution — the IA Uganda Target Distribution workspace (§12),
  where the CD confirms and publishes the master and IA distributes the
  annual targets to Program Leads under reconciliation.
- /target-distribution/team — the PL Team Target Distribution workspace
  (§13), scoped to the PL's approved IA allocation, their own portfolio and
  directly supervised CCEOs.

Both pages are plain-POST + redirect like the strategic-priorities surface;
every state change goes through the canonical services, never a model write.
"""

from functools import wraps

from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.core.permissions import has_permission, require_page_permission
from apps.core.rbac import EdifyRole, Permission


def _permission(permission):
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not getattr(request.user, "is_authenticated", False):
                return redirect("/login")
            if not has_permission(request.user, permission):
                return HttpResponseForbidden("Target distribution access denied.")
            return view(request, *args, **kwargs)

        # The production-readiness route scanner recognises guarded page views
        # by this attribute (the same contract require_page_permission uses).
        wrapped.has_permission_guard = True
        return wrapped

    return decorator


def _requested_fy(request) -> str:
    from apps.frontend.views.hr_views import _requested_fy as hr_requested_fy

    return hr_requested_fy(request)


def _is_cd(request) -> bool:
    return getattr(request.user, "active_role", "") in (
        EdifyRole.COUNTRY_DIRECTOR.value,
        EdifyRole.ADMIN.value,
    )


def _is_ia_distributor(request) -> bool:
    return getattr(request.user, "active_role", "") in (
        EdifyRole.IMPACT_ASSESSMENT.value,
        EdifyRole.ADMIN.value,
    )


@require_page_permission("target_distribution")
@_permission(Permission.STRATEGIC_PRIORITIES_VIEW.value)
def target_distribution_page(request):
    from apps.hr.models import PriorityImportBatch, StrategicPriorityCycle
    from apps.hr.target_distribution import country_distribution_workspace

    raw_fy = (request.GET.get("fy") or "").strip()
    if raw_fy:
        fy = _requested_fy(request)
    else:
        fy = StrategicPriorityCycle.objects.exclude(status="archived").order_by(
            "-financial_year"
        ).values_list("financial_year", flat=True).first() or _requested_fy(request)
    workspace = country_distribution_workspace(fy)
    selected = {
        # `q` arrives from the topbar search (the one search control, per the
        # consolidation contract); `carry_q` is the filter menu preserving the
        # current term across its own submissions — state, not a search box.
        "q": (request.GET.get("q") or request.GET.get("carry_q") or "").strip(),
        "tab": (request.GET.get("tab") or "all").strip(),
        "priority": (request.GET.get("priority") or "").strip(),
        "portfolio": (request.GET.get("portfolio") or "").strip(),
        "status": (request.GET.get("status") or "").strip(),
    }
    master_rows = []
    distribution_groups = []
    distribution_options = []
    for group in workspace["groups"]:
        group_has_field = False
        for row in group["milestones"]:
            row["priority"] = group["priority"]
            milestone = row["milestone"]
            if milestone.allocation_method == "field_cascade":
                group_has_field = True
                if workspace["published"] and not milestone.needs_confirmation:
                    distribution_options.append(row)
            if (
                selected["tab"] != "all"
                and milestone.allocation_method != selected["tab"]
            ):
                continue
            if selected["priority"] and group["priority"].code != selected["priority"]:
                continue
            if selected["portfolio"] == "core" and milestone.core_target is None:
                continue
            if selected["portfolio"] == "client" and milestone.client_target is None:
                continue
            if selected["status"]:
                status_key = row["displayStatus"].lower().replace(" ", "_")
                if status_key != selected["status"]:
                    continue
            if selected["q"]:
                haystack = " ".join(
                    (
                        group["priority"].title,
                        milestone.title,
                        milestone.source_text,
                        row["activityDisplay"],
                    )
                ).casefold()
                if selected["q"].casefold() not in haystack:
                    continue
            master_rows.append(row)
        if group_has_field:
            distribution_groups.append(group["priority"])
    paginator = Paginator(master_rows, 25)
    page_obj = paginator.get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    cycle_years = list(
        StrategicPriorityCycle.objects.order_by("-financial_year").values_list(
            "financial_year", flat=True
        )
    )
    if fy not in cycle_years:
        cycle_years.append(fy)
    next_distribution = next(
        (row for row in distribution_options if row["displayStatus"] != "Distributed"),
        distribution_options[0] if distribution_options else None,
    )
    next_confirmation = next(
        (
            row
            for group in workspace["groups"]
            for row in group["milestones"]
            if row["milestone"].needs_confirmation
        ),
        None,
    )
    active_filter_count = sum(
        bool(selected[key]) for key in ("q", "priority", "portfolio", "status")
    )
    can_import = has_permission(
        request.user, Permission.STRATEGIC_PRIORITIES_IMPORT.value
    )
    import_batches = []
    selected_import_batch = None
    if can_import:
        import_batches = list(
            PriorityImportBatch.objects.filter(fy=fy, country_id="Uganda")[:5]
        )
        selected_batch_id = (request.GET.get("import") or "").strip()
        if selected_batch_id:
            selected_import_batch = (
                PriorityImportBatch.objects.prefetch_related("rows")
                .filter(id=selected_batch_id, fy=fy, country_id="Uganda")
                .first()
            )
        elif import_batches:
            selected_import_batch = import_batches[0]
    return render(
        request,
        "pages/hr/target_distribution.html",
        {
            **workspace,
            "cycle_years": cycle_years,
            "is_cd": _is_cd(request),
            "can_distribute": _is_ia_distributor(request),
            "can_import": can_import,
            "import_batches": import_batches,
            "selected_import_batch": selected_import_batch,
            "today": timezone.localdate().isoformat(),
            # One search: the top bar binds this page's milestone search and
            # carries the active filters, per the consolidation contract.
            "topbar_search": {
                "placeholder": "Search milestones, activities…",
                "label": "Search master milestones and activities",
                "name": "q",
                "value": selected["q"],
                "action": "/target-distribution",
                "hidden": [
                    {"name": "fy", "value": fy},
                    {"name": "tab", "value": selected["tab"]},
                    {"name": "priority", "value": selected["priority"]},
                    {"name": "portfolio", "value": selected["portfolio"]},
                    {"name": "status", "value": selected["status"]},
                ],
            },
            "selected": selected,
            "page_obj": page_obj,
            "master_row_count": paginator.count,
            "page_query": query.urlencode(),
            "distribution_groups": distribution_groups,
            "distribution_options": distribution_options,
            "next_distribution": next_distribution,
            "next_confirmation": next_confirmation,
            "active_filter_count": active_filter_count,
        },
    )


@require_page_permission("target_distribution")
@_permission(Permission.STRATEGIC_PRIORITIES_IMPORT.value)
def target_distribution_import(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required.")
    from apps.core.exceptions import BadRequest, Forbidden
    from apps.hr.priority_import import stage_priority_file

    fy = request.POST.get("fy") or _requested_fy(request)
    upload = request.FILES.get("priority_file")
    if upload is None:
        messages.error(request, "Choose a CSV or XLSX priority file.")
        return redirect(f"/target-distribution?fy={fy}")
    try:
        batch, created = stage_priority_file(file=upload, fy=fy, principal=request.user)
        if created:
            if batch.invalid_rows:
                messages.error(
                    request,
                    f"Upload staged with {batch.invalid_rows} blocked row(s). "
                    "Correct the source file and upload it again.",
                )
            else:
                messages.success(
                    request,
                    f"Validated {batch.total_rows} priority row(s). Review the "
                    "preview, then commit them as a draft master.",
                )
        else:
            messages.info(
                request, "This exact file was already staged; showing it now."
            )
        return redirect(f"/target-distribution?fy={fy}&import={batch.id}")
    except (BadRequest, Forbidden) as exc:
        messages.error(request, str(exc))
        return redirect(f"/target-distribution?fy={fy}")


@require_page_permission("target_distribution")
@_permission(Permission.STRATEGIC_PRIORITIES_IMPORT.value)
def target_distribution_import_commit(request, batch_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required.")
    from apps.core.exceptions import BadRequest, ConflictError, Forbidden
    from apps.hr.models import PriorityImportBatch
    from apps.hr.priority_import import commit_priority_batch

    batch = PriorityImportBatch.objects.filter(id=batch_id).first()
    if batch is None:
        return HttpResponseBadRequest("Choose a valid priority import.")
    try:
        commit_priority_batch(batch_id=batch_id, principal=request.user)
        messages.success(
            request,
            "Priority master committed as a draft. The Country Director can now "
            "confirm source figures and publish it for distribution.",
        )
    except (BadRequest, ConflictError, Forbidden) as exc:
        messages.error(request, str(exc))
    return redirect(f"/target-distribution?fy={batch.fy}&import={batch.id}")


@require_page_permission("target_distribution")
@_permission(Permission.STRATEGIC_PRIORITIES_IMPORT.value)
def target_distribution_import_template(request):
    from apps.hr.priority_import import csv_template

    response = HttpResponse(csv_template(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="edify-priority-import.csv"'
    return response


@require_page_permission("target_distribution")
@_permission(Permission.STRATEGIC_PRIORITIES_VIEW.value)
def target_distribution_form(request):
    """Lazy, database-backed IA → PL form for one master milestone."""

    if not _is_ia_distributor(request):
        return HttpResponseForbidden(
            "Impact Assessment distributes Uganda targets to Program Leads."
        )
    from apps.hr.models import PriorityMilestone
    from apps.hr.target_distribution import country_milestone_distribution_context

    milestone = (
        PriorityMilestone.objects.select_related("priority")
        .filter(
            id=request.GET.get("milestone"),
            priority__level="country",
            priority__country_id="Uganda",
        )
        .first()
    )
    if milestone is None:
        return HttpResponseBadRequest("Choose a valid Uganda master milestone.")
    if milestone.priority.status != "published" or milestone.needs_confirmation:
        return HttpResponseBadRequest(
            "This milestone must be confirmed and published before distribution."
        )
    context = country_milestone_distribution_context(milestone)
    return render(
        request,
        "partials/hr/target_distribution_form.html",
        {
            **context,
            "fy": milestone.priority.fy,
        },
    )


@require_page_permission("team_target_distribution")
@_permission(Permission.MILESTONES_ALLOCATE.value)
def team_distribution_page(request):
    from apps.hr.models import StrategicPriorityCycle
    from apps.hr.target_distribution import team_distribution_workspace

    raw_fy = (request.GET.get("fy") or "").strip()
    if raw_fy:
        fy = _requested_fy(request)
    else:
        fy = StrategicPriorityCycle.objects.exclude(status="archived").order_by(
            "-financial_year"
        ).values_list("financial_year", flat=True).first() or _requested_fy(request)
    workspace = team_distribution_workspace(fy, principal=request.user)
    cycle_years = list(
        StrategicPriorityCycle.objects.order_by("-financial_year").values_list(
            "financial_year", flat=True
        )
    )
    if fy not in cycle_years:
        cycle_years.append(fy)
    next_team_distribution = next(
        (row for row in workspace["rows"] if not row["allLocked"]),
        workspace["rows"][0] if workspace["rows"] else None,
    )
    return render(
        request,
        "pages/hr/team_target_distribution.html",
        {
            **workspace,
            "cycle_years": cycle_years,
            "today": timezone.localdate().isoformat(),
            "next_team_distribution": next_team_distribution,
        },
    )


def _quarters_from_post(request) -> dict:
    return {
        "Q1": request.POST.get("q1"),
        "Q2": request.POST.get("q2"),
        "Q3": request.POST.get("q3"),
        "Q4": request.POST.get("q4"),
    }


def _save_allocation_rows(request, milestone, *, scope, parent=None):
    """Apply the bulk allocation form: one input row per target-holder.

    Draft rows are editable and removable; approved rows are locked and only
    change through a formal amendment — a differing figure posted against one
    is refused loudly rather than silently applied.
    """

    from decimal import Decimal, InvalidOperation

    from apps.core.exceptions import BadRequest
    from apps.hr.milestone_allocations import create_allocation

    prefix = "target__"
    reason = (request.POST.get("reason") or "").strip() or (
        "Uganda master annual distribution."
    )
    # 2026-08-20 audit R2: RATE milestones carry each holder's eligible-
    # portfolio DENOMINATOR, or coverage math falls into the units÷rate
    # fallback. For a team scope the denominator is the supervised members'
    # combined portfolio; for an employee scope, their own portfolio.
    denominators: dict[str, int] = {}
    if milestone.measurement_type == "percentage":
        from apps.accounts.models import StaffSupervisorAssignment
        from apps.hr.target_distribution import _portfolio_counts

        holder_ids = [
            key[len(prefix) :] for key in request.POST if key.startswith(prefix)
        ]
        if scope == "team":
            for hid in holder_ids:
                members = list(
                    StaffSupervisorAssignment.objects.filter(
                        supervisor_id=hid
                    ).values_list("supervisee_id", flat=True)
                ) + [hid]
                counts = _portfolio_counts(members)
                denominators[hid] = sum(row.get("total", 0) for row in counts.values())
        else:
            counts = _portfolio_counts(holder_ids)
            denominators = {
                hid: counts.get(hid, {}).get("total", 0) for hid in holder_ids
            }
    saved, removed, locked = 0, 0, []
    for key in request.POST:
        if not key.startswith(prefix):
            continue
        holder_id = key[len(prefix) :]
        raw = (request.POST.get(key) or "").strip()
        raw_core = (request.POST.get(f"core__{holder_id}") or "").strip()
        raw_client = (request.POST.get(f"client__{holder_id}") or "").strip()
        live = milestone.allocations.exclude(status__in=("rejected", "superseded"))
        if scope == "team":
            existing = live.filter(allocated_to_type="team", team_id=holder_id).first()
        else:
            existing = live.filter(employee_id=holder_id, parent=parent).first()
        if not raw:
            if existing is not None and existing.status == "draft":
                existing.period_targets.all().delete()
                existing.delete()
                removed += 1
            elif existing is not None:
                locked.append(existing)
            continue
        try:
            value = Decimal(raw)
        except InvalidOperation as exc:
            raise BadRequest("Targets must be numeric.") from exc
        if existing is not None and existing.status == "approved":
            changed = value != existing.allocated_target
            if changed:
                locked.append(existing)
            continue
        if existing is not None:
            # 2026-08-20 audit G9: the bulk editor previously bypassed every
            # create_allocation validation — enforce the same arithmetic
            # rules on the update branch.
            if value <= 0:
                raise BadRequest("Allocated target must be greater than zero.")
            try:
                core_v = Decimal(raw_core) if raw_core else None
                client_v = Decimal(raw_client) if raw_client else None
            except InvalidOperation as exc:
                raise BadRequest("Core/Client splits must be numeric.") from exc
            if (core_v or 0) + (client_v or 0) > value:
                raise BadRequest("Core plus Client cannot exceed the allocated target.")
            if (
                milestone.measurement_type == "count"
                and value != value.to_integral_value()
            ):
                raise BadRequest("Count targets must be whole numbers.")
            existing.allocated_target = value
            existing.core_target = core_v
            existing.client_target = client_v
            existing.allocation_reason = reason
            if holder_id in denominators:
                existing.denominator = Decimal(denominators[holder_id])
            existing.save(
                update_fields=[
                    "allocated_target",
                    "denominator",
                    "core_target",
                    "client_target",
                    "allocation_reason",
                    "updated_at",
                ]
            )
            saved += 1
            continue
        data = {
            "allocatedToType": scope,
            "allocatedTarget": raw,
            "coreTarget": raw_core or None,
            "clientTarget": raw_client or None,
            "denominator": denominators.get(holder_id),
            "effectiveDate": timezone.localdate().isoformat(),
            "allocationReason": reason,
        }
        if scope == "team":
            data["teamId"] = holder_id
        else:
            data["employeeId"] = holder_id
            if parent is not None:
                data["parentId"] = parent.id
        create_allocation(milestone=milestone, data=data, principal=request.user)
        saved += 1
    if locked:
        messages.error(
            request,
            f"{len(locked)} approved allocation(s) were not changed — approved "
            "figures are locked; use a formal amendment.",
        )
    if saved or removed:
        messages.success(
            request,
            f"Saved {saved} allocation(s)"
            + (f", removed {removed} draft(s)" if removed else "")
            + ".",
        )


@require_page_permission("target_distribution")
@_permission(Permission.STRATEGIC_PRIORITIES_ALLOCATE.value)
def target_distribution_action(request):
    from apps.core.exceptions import BadRequest, Forbidden
    from apps.hr import target_distribution as engine
    from apps.hr.models import MilestoneAllocation, PriorityMilestone

    if request.method != "POST":
        return HttpResponseBadRequest("POST required.")
    fy = request.POST.get("fy") or _requested_fy(request)
    action = request.POST.get("action", "")
    try:
        if action == "confirm_milestone":
            if not _is_cd(request):
                raise BadRequest(
                    "Source figures are confirmed by the Country Director."
                )
            milestone = PriorityMilestone.objects.get(id=request.POST.get("milestone"))
            engine.confirm_milestone(
                milestone, data=request.POST.dict(), principal=request.user
            )
            messages.success(request, "Source figure confirmed.")
        elif action == "publish_master":
            activated = engine.publish_uganda_master(fy, principal=request.user)
            messages.success(
                request,
                f"Uganda master published and locked — {activated} milestones "
                "are now allocatable.",
            )
        elif action == "save_team_allocations":
            if not _is_ia_distributor(request):
                raise BadRequest(
                    "Impact Assessment distributes Uganda targets to Program Leads."
                )
            milestone = PriorityMilestone.objects.get(id=request.POST.get("milestone"))
            _save_allocation_rows(request, milestone, scope="team")
        elif action == "save_and_approve_team_distribution":
            if not _is_ia_distributor(request):
                raise BadRequest(
                    "Impact Assessment distributes Uganda targets to Program Leads."
                )
            milestone = PriorityMilestone.objects.get(id=request.POST.get("milestone"))
            _save_allocation_rows(request, milestone, scope="team")
            engine.approve_team_distribution(milestone, principal=request.user)
            messages.success(
                request,
                "Target distributed to Program Leads and locked at a zero balance.",
            )
        elif action == "approve_team_distribution":
            if not _is_ia_distributor(request):
                raise BadRequest(
                    "Impact Assessment distributes Uganda targets to Program Leads."
                )
            milestone = PriorityMilestone.objects.get(id=request.POST.get("milestone"))
            engine.approve_team_distribution(milestone, principal=request.user)
            messages.success(
                request,
                "Annual IA → Program Lead distribution approved and locked.",
            )
        elif action == "approve_quarters":
            allocation = MilestoneAllocation.objects.get(
                id=request.POST.get("allocation")
            )
            warnings = engine.approve_quarters(
                allocation,
                quarters=_quarters_from_post(request),
                principal=request.user,
            )
            messages.success(request, "Quarterly spread approved.")
            for warning in warnings:
                messages.error(request, f"Capacity warning — {warning}")
        elif action == "request_amendment":
            allocation = MilestoneAllocation.objects.get(
                id=request.POST.get("allocation")
            )
            kind = request.POST.get("kind") or "amendment"
            engine.request_amendment(
                allocation,
                kind=kind,
                reason=request.POST.get("reason") or "",
                new_target=request.POST.get("new_target"),
                new_quarters=_quarters_from_post(request)
                if kind == "reforecast"
                else None,
                principal=request.user,
            )
            messages.success(request, "Amendment recorded for approval.")
        elif action == "approve_amendment":
            from apps.hr.models import MilestoneAllocationAmendment

            amendment = MilestoneAllocationAmendment.objects.get(
                id=request.POST.get("amendment")
            )
            engine.approve_amendment(amendment, principal=request.user)
            messages.success(request, "Amendment approved and applied.")
        else:
            raise BadRequest("Unknown action.")
    except (BadRequest, Forbidden) as exc:
        messages.error(request, str(exc))
    return redirect(f"/target-distribution?fy={fy}")


@require_page_permission("team_target_distribution")
@_permission(Permission.MILESTONES_ALLOCATE.value)
def team_distribution_action(request):
    from apps.core.exceptions import BadRequest, Forbidden
    from apps.hr import target_distribution as engine
    from apps.hr.models import MilestoneAllocation

    if request.method != "POST":
        return HttpResponseBadRequest("POST required.")
    fy = request.POST.get("fy") or _requested_fy(request)
    action = request.POST.get("action", "")
    try:
        if action == "save_member_allocations":
            team_allocation = MilestoneAllocation.objects.get(
                id=request.POST.get("allocation")
            )
            _assert_own_team(request, team_allocation)
            _save_allocation_rows(
                request,
                team_allocation.milestone,
                scope="employee",
                parent=team_allocation,
            )
        elif action == "save_and_approve_member_distribution":
            team_allocation = MilestoneAllocation.objects.get(
                id=request.POST.get("allocation")
            )
            _assert_own_team(request, team_allocation)
            _save_allocation_rows(
                request,
                team_allocation.milestone,
                scope="employee",
                parent=team_allocation,
            )
            engine.approve_employee_distribution(
                team_allocation, principal=request.user
            )
            messages.success(
                request,
                "Received priority distributed within the team and locked at "
                "a zero balance.",
            )
        elif action == "approve_member_distribution":
            team_allocation = MilestoneAllocation.objects.get(
                id=request.POST.get("allocation")
            )
            engine.approve_employee_distribution(
                team_allocation, principal=request.user
            )
            messages.success(
                request,
                "Team distribution approved — targets are now locked "
                "and appear under each CCEO's priorities.",
            )
        elif action == "approve_quarters":
            allocation = MilestoneAllocation.objects.get(
                id=request.POST.get("allocation")
            )
            warnings = engine.approve_quarters(
                allocation,
                quarters=_quarters_from_post(request),
                principal=request.user,
            )
            messages.success(request, "Quarterly spread approved.")
            for warning in warnings:
                messages.error(request, f"Capacity warning — {warning}")
        else:
            raise BadRequest("Unknown action.")
    except (BadRequest, Forbidden) as exc:
        messages.error(request, str(exc))
    return redirect(f"/target-distribution/team?fy={fy}")


def _assert_own_team(request, team_allocation) -> None:
    from apps.core.exceptions import BadRequest

    role = getattr(request.user, "active_role", "")
    if role == EdifyRole.COUNTRY_PROGRAM_LEAD.value and str(
        team_allocation.team_id
    ) != str(getattr(request.user, "staff_profile_id", "")):
        raise BadRequest("Program Leads distribute only their own team target.")


@require_page_permission("priorities_master")
def priority_dashboard_redirect(request):
    """Send the retired Priority Dashboard path to the canonical Priorities page.

    Query parameters ride along so a bookmarked financial year or filter still
    lands where it meant to. The compatibility route declares the same page
    permission as its destination so authorization scanners and direct route
    access agree.
    """
    from django.shortcuts import redirect

    query = request.META.get("QUERY_STRING", "")
    return redirect(f"/priorities?{query}" if query else "/priorities")


@require_page_permission("priorities_master")
def priorities_master_page(request):
    """The Uganda Master Priority Plan, in the source's own four columns:
    Priorities · Milestones · Activities · Targets (§9 canonical content).

    Every role sees the same canonical rows. The TARGET column is
    role-scoped: CD, IA, RVP, HR and Admin read the country figure; a
    Program Lead or CCEO reads THEIR OWN approved allocation — a CCEO
    allocated 20 new schools sees 20 here, never the country's 1,000.
    """

    from decimal import Decimal

    from django.contrib.humanize.templatetags.humanize import intcomma

    from django.db import models

    from apps.core.fy import fy_options
    from apps.hr.models import (
        MilestoneActivityRule,
        MilestoneAllocation,
        MilestoneTargetComponent,
        StrategicPriority,
        StrategicPriorityCycle,
    )

    raw_fy = (request.GET.get("fy") or "").strip()
    if raw_fy:
        fy = _requested_fy(request)
    else:
        fy = StrategicPriorityCycle.objects.exclude(status="archived").order_by(
            "-financial_year"
        ).values_list("financial_year", flat=True).first() or _requested_fy(request)

    priorities = list(
        StrategicPriority.objects.filter(
            fy=fy, level="country", country_id="Uganda", cycle__isnull=False
        )
        .order_by("sequence")
        .prefetch_related("milestones")
    )
    milestone_ids = [m.id for p in priorities for m in p.milestones.all()]

    rules_by_milestone: dict[str, list[str]] = {}
    for rule in MilestoneActivityRule.objects.filter(
        milestone_id__in=milestone_ids, active=True
    ).select_related("catalogue_item"):
        label = rule.catalogue_item.display_name if rule.catalogue_item_id else ""
        if label:
            rules_by_milestone.setdefault(str(rule.milestone_id), []).append(label)

    components_by_milestone: dict[str, list] = {}
    for comp in MilestoneTargetComponent.objects.filter(
        milestone_id__in=milestone_ids
    ).order_by("sequence"):
        components_by_milestone.setdefault(str(comp.milestone_id), []).append(comp)

    # Role scoping: PL and CCEO read their own approved allocation.
    role = getattr(request.user, "active_role", "")
    scoped_roles = {"Program Lead", "CCEO", "ProjectCoordinator"}
    is_scoped_viewer = role in scoped_roles
    my_values: dict[str, Decimal] = {}
    my_status: dict[str, str] = {}
    if is_scoped_viewer:
        staff_id = getattr(request.user, "staff_profile_id", None)
        holder = (
            MilestoneAllocation.objects.filter(
                milestone_id__in=milestone_ids,
                status__in=("draft", "approved"),
            )
            .filter(
                models.Q(employee_id=staff_id)
                | models.Q(team_id=staff_id, allocated_to_type="team")
            )
            .select_related("milestone")
        )
        for allocation in holder:
            key = str(allocation.milestone_id)
            # An employee allocation outranks the team row for the same
            # milestone (a PL holds both once they self-allocate).
            if key in my_values and allocation.allocated_to_type == "team":
                continue
            my_values[key] = allocation.allocated_target
            my_status[key] = allocation.status

    def _fmt_number(value, unit=""):
        if value is None:
            return ""
        value = Decimal(value)
        text = (
            intcomma(int(value))
            if value == value.to_integral_value()
            else intcomma(value)
        )
        return f"{text} {unit}".strip() if unit not in ("", "percent") else text

    def _target_display(m):
        if m.recurrence_per_month:
            per = _fmt_number(m.recurrence_per_month)
            return f"{per} {m.target_unit or 'times'} per month"
        if m.measurement_type == "percentage" and m.target_value is not None:
            return f"{_fmt_number(m.target_value)}%"
        if m.measurement_type == "date":
            if m.due_date:
                return f"by {m.due_date.strftime('%-d %b %Y')}"
            return m.target_source_text or "—"
        if m.target_value is not None:
            return _fmt_number(m.target_value, m.target_unit or "")
        source_tail = (m.target_source_text or "").rsplit("—", 1)
        tail = source_tail[-1].strip() if len(source_tail) > 1 else ""
        if tail.upper() == "NA" or (m.source_text or "").rstrip().endswith("NA"):
            return "NA"
        if m.measurement_type in ("manual_assessment", "qualitative") and tail:
            return tail
        return "—"

    groups = []
    total_rows = 0
    for priority in priorities:
        rows = []
        for m in sorted(priority.milestones.all(), key=lambda x: x.source_order):
            key = str(m.id)
            mine = my_values.get(key)
            rows.append(
                {
                    "milestone": m,
                    "activities": rules_by_milestone.get(key, []),
                    "components": components_by_milestone.get(key, []),
                    "target_display": _target_display(m),
                    "my_value": (
                        _fmt_number(mine, m.target_unit or "")
                        if mine is not None
                        else None
                    ),
                    "my_is_draft": my_status.get(key) == "draft",
                    "is_percent": m.measurement_type == "percentage",
                }
            )
        total_rows += len(rows)
        groups.append({"priority": priority, "rows": rows})

    return render(
        request,
        "pages/hr/priorities_master.html",
        {
            "fy": fy,
            "groups": groups,
            "total_rows": total_rows,
            "is_scoped_viewer": is_scoped_viewer,
            "viewer_role": role,
            "fy_options": fy_options(),
            "use_dark_sidebar": True,
        },
    )
