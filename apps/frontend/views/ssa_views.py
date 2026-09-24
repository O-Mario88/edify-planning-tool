from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import Http404, HttpResponse, HttpResponseForbidden
from django.db.models import Count, Q
from apps.core.redirects import local_redirect
from apps.core.permissions import (
    has_permission,
    render_access_denied,
    require_page_permission,
)
from apps.core.rbac import Permission
from apps.core.scoping import resolve_user_scope, school_queryset
from apps.schools.models import SSAImportBatch, School
from apps.ssa import services as ssa_services
from apps.ssa.forms import ManualSsaEntryForm
from apps.ssa.models import SsaRecord
from apps.ssa.upload_service import upload_ssa_file, import_ssa_batch
from apps.core.exceptions import BadRequest
from apps.core.enums import VerificationStatus, SsaIntervention
from apps.core.metrics import DataState, MetricValue, render_kpi_item
from django.utils import timezone
import csv


@require_page_permission("ssa_performance")
def ssa_performance_view(request):
    """Unified, role-scoped SSA intelligence workspace."""
    from apps.analytics.decision_engine import ssa_performance_dashboard

    dashboard = ssa_performance_dashboard(request.user, request.GET.dict())
    kpis = dashboard["kpis"]
    ssa_kpi_items = [
        render_kpi_item(
            "ssa_schools_assessed",
            MetricValue.measured(kpis["assessed"]),
            helper=f"of {kpis['total_schools']} schools · {kpis['completion_rate']}%",
            tone="info",
        ),
        render_kpi_item(
            "ssa_completion_rate",
            MetricValue.ratio(kpis["assessed"], kpis["total_schools"]),
            helper=(
                f"{kpis['assessed']} confirmed this "
                f"{'financial year' if dashboard['filters']['is_full_year'] else 'quarter'}"
            ),
            tone="success",
        ),
        render_kpi_item(
            "ssa_districts_reporting",
            MetricValue.measured(kpis["reporting_districts"]),
            helper=f"of {kpis['total_districts']} in your scope",
            tone="info",
        ),
        render_kpi_item(
            "ssa_average_score",
            MetricValue.measured(kpis["average_score"])
            if kpis["average_score"] is not None
            else MetricValue.absent(DataState.NO_DATA),
            helper=(
                f"{kpis['average_delta']:+.2f} vs {kpis['comparison_label']}"
                if kpis["average_delta"] is not None
                else "No comparable prior period"
            ),
            tone="warning",
        ),
        render_kpi_item(
            "ssa_high_risk_schools",
            MetricValue.measured(kpis["high_risk"]),
            helper=f"{kpis['high_risk_pct']}% of assessed · below {dashboard['engine']['high_risk_score']}",
            tone="danger",
        ),
        render_kpi_item(
            "ssa_districts_below_target",
            MetricValue.measured(kpis["districts_below_target"]),
            helper=f"below {kpis['target']} average",
            tone="danger",
        ),
    ]
    breakdowns = dashboard.get("breakdowns") or {}
    context = {
        "dashboard": dashboard,
        # One tabbed card, three panels (the template's tab ids are literal so
        # the design-system scan can pair each tab with its panel).
        "breakdown_staff": breakdowns.get("staff", []),
        "breakdown_cluster": breakdowns.get("cluster", []),
        "breakdown_partner": breakdowns.get("partner", []),
        "ssa_kpi_items": ssa_kpi_items,
        "can_add_ssa": _may_upload_ssa(request),
    }
    # This section's own filter form swaps its workspace and nothing else. It
    # has to name its target: a tab click and a scope change are HX requests
    # too, and they ask for different shapes.
    if request.headers.get("HX-Target") == "ssa-performance-workspace":
        return render(request, "partials/ssa/performance_workspace.html", context)
    from apps.frontend.views.analytics_render import render_analytics_section

    return render_analytics_section(
        request,
        "partials/analytics/panels/ssa_performance.html",
        context,
        section_key="ssa",
        panel_title="SSA Performance",
        frame={
            "question": (
                "Which schools and interventions are furthest from the SSA "
                "standard, and where should support be concentrated?"
            ),
            "evidence": "Confirmed SSA assessments across eight interventions",
            "freshness": "Current filters and confirmed cycles",
            "confidence": "Coverage-qualified",
        },
    )


@require_page_permission("ssa_performance")
def ssa_performance_export_view(request):
    """Export the exact confirmed, filtered school set shown by the dashboard."""
    from apps.analytics.decision_engine import ssa_performance_dashboard

    dashboard = ssa_performance_dashboard(
        request.user, request.GET.dict(), export_only=True
    )
    if not dashboard["scope"]["can_export"]:
        return HttpResponseForbidden("Your role cannot export SSA performance data.")

    # The export follows the page's period: the full financial year unless a
    # quarter was chosen, read by the same service call as the page.
    fy = dashboard["filters"]["fy"]
    period = (
        "full-year"
        if dashboard["filters"]["is_full_year"]
        else dashboard["filters"]["quarter"].lower()
    )
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        f'attachment; filename="ssa-performance-fy{fy}-{period}.csv"'
    )
    writer = csv.writer(response)
    writer.writerow(
        [
            "School ID",
            "School",
            "Region",
            "District",
            "Average score",
            "Lowest intervention",
            "Lowest score",
            "High risk",
        ]
    )
    for row in dashboard["export_rows"]:
        writer.writerow(
            [
                row["school_id"],
                row["school"],
                row["region"],
                row["district"],
                row["average"],
                row["lowest_intervention"],
                row["lowest_score"],
                row["high_risk"],
            ]
        )
    return response


@require_page_permission("ssa")
def ssa_template_download_view(request):
    """Download a CSV template with the correct SSA column headers + sample rows.

    Includes two sample rows: one for last FY (baseline) and one for current FY.
    The SSA Year column controls which FY each row targets:
      "last" or a year like "2025" → previous FY (baseline, upload once)
      "current" or a year like "2026" → current FY (requires baseline first)
    """
    if not _may_upload_ssa(request):
        return render_access_denied(request, UPLOAD_ONLY_MESSAGE)
    from apps.core.fy import get_operational_fy

    current_fy = get_operational_fy()
    prev_fy = str(int(current_fy) - 1)

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="ssa_upload_template.csv"'

    writer = csv.writer(response)
    # Header row
    headers = ["School ID", "Assessment Date", "SSA Year"]
    for _code, label in SsaIntervention.choices:
        headers.append(f"{label} (0-10)")
    writer.writerow(headers)

    # Sample row 1: last FY baseline
    sample_prev = ["SCH-0001", f"{prev_fy}-06-15", prev_fy]
    for _code, _label in SsaIntervention.choices:
        sample_prev.append("6.0")
    writer.writerow(sample_prev)

    # Sample row 2: current FY
    sample_curr = ["SCH-0001", f"{current_fy}-07-01", current_fy]
    for _code, _label in SsaIntervention.choices:
        sample_curr.append("7.5")
    writer.writerow(sample_curr)

    return response


#: What a reader without ssa.upload is told at every upload surface.
UPLOAD_ONLY_MESSAGE = (
    "Only Impact Assessment and administrators upload official SSA scores."
)


def _may_upload_ssa(request) -> bool:
    """Official SSA creation requires the SSA_UPLOAD permission, not just the
    page. The page key "ssa" is open to CD/RVP/PL/CCEO for READING, but a
    staff-collected upload is born verification_status="confirmed"
    (ssa/services.py) — so page access alone let four non-IA roles mint
    official confirmed SSA without IA ever touching it. The API sibling
    already enforces ssa.upload; the frontend must match it.
    """
    return has_permission(request.user, Permission.SSA_UPLOAD.value)


def _visible_batches(request):
    """The SSA import batches this reader may open.

    The preview and result pages took a batch id straight from the URL, so
    anyone holding the page key could read — and, through the preview's
    finalise form, reach — somebody else's import by guessing its id. Impact
    Assessment and Admin run the imports; anyone else who uploads sees their
    own (Programme Lead alignment, 2026-09-13). Impact Assessment reads the
    batches uploaded by staff in its own country, never another country's
    (IA review, 2026-09-13); Admin and an officer with no country on file keep
    the deployment.
    """
    from apps.core.rbac import EdifyRole
    from apps.core.scoping import person_country_q

    batches = SSAImportBatch.objects.all()
    role = request.user.active_role
    if role == EdifyRole.ADMIN.value:
        return batches
    if role == EdifyRole.IMPACT_ASSESSMENT.value:
        scope = resolve_user_scope(request.user)
        return batches.filter(
            person_country_q(scope, "uploaded_by") | Q(uploaded_by=request.user.user_id)
        )
    return batches.filter(uploaded_by=request.user.user_id)


@require_page_permission("ssa")
def ssa_manual_entry_view(request):
    """Create one authoritative SSA record without using a spreadsheet."""
    if not _may_upload_ssa(request):
        return render_access_denied(request, UPLOAD_ONLY_MESSAGE)

    scope = resolve_user_scope(request.user)
    scoped_schools = school_queryset(scope)
    if scoped_schools is None:
        scoped_schools = School.objects.none()
    else:
        scoped_schools = (
            scoped_schools.filter(deleted_at__isnull=True)
            .select_related("district")
            .order_by("school_id")
        )

    initial = {
        "school_id": request.GET.get("school_id", "").strip(),
        "date_of_ssa": timezone.localdate(),
    }
    form = ManualSsaEntryForm(
        request.POST or None,
        school_queryset=scoped_schools,
        initial=initial,
    )
    selected_school_id = (
        request.POST.get("school_id", "").strip() or initial["school_id"]
    )
    selected_schools = (
        scoped_schools.filter(school_id=selected_school_id)[:1]
        if selected_school_id
        else School.objects.none()
    )

    if request.method == "POST" and form.is_valid():
        collector_type = (
            "ia" if request.user.active_role == "ImpactAssessment" else "staff"
        )
        try:
            result = ssa_services.upload(
                form.to_service_payload(collector_type=collector_type),
                request.user,
            )
        except BadRequest as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(
                request,
                (
                    f"SSA score saved for {form.school.name}. "
                    f"FY {result['fy']} average: {result['averageScore']:.1f}. "
                    "It counts once a different verifier confirms it."
                ),
            )
            return local_redirect(f"/schools/{form.school.id}#ssa-timeline")

    return render(
        request,
        "pages/ssa/manual_entry.html",
        {
            "form": form,
            "score_fields": form.score_fields,
            "schools": selected_schools,
        },
    )


@require_page_permission("ssa")
def ssa_manual_school_options_view(request):
    """Return a small, role-scoped datalist window for manual SSA entry."""
    if not _may_upload_ssa(request):
        return HttpResponseForbidden()

    query = request.GET.get("school_id", "").strip()
    if len(query) < 2:
        schools = School.objects.none()
    else:
        scope = resolve_user_scope(request.user)
        schools = school_queryset(scope)
        if schools is None:
            schools = School.objects.none()
        else:
            schools = (
                schools.filter(deleted_at__isnull=True)
                .filter(Q(school_id__istartswith=query) | Q(name__icontains=query))
                .select_related("district")
                .order_by("school_id")[:25]
            )
    return render(
        request,
        "partials/ssa/manual_school_options.html",
        {"schools": schools},
    )


@require_page_permission("ssa")
def ssa_upload_center_view(request):
    # The page itself is the uploader's, not just its POST: page access to
    # "ssa" is a reading permission, and the upload centre has nothing to read.
    if not _may_upload_ssa(request):
        return render_access_denied(request, UPLOAD_ONLY_MESSAGE)
    if request.method == "POST":
        file = request.FILES.get("file")
        if not file:
            messages.error(request, "A file is required for upload.")
            return redirect("/ssa/upload/")

        try:
            result = upload_ssa_file(file, request.user)
            # Find the newly created batch
            batch = (
                _visible_batches(request)
                .filter(uploaded_by=request.user.user_id)
                .order_by("-created_at")
                .first()
            )
            if batch:
                return local_redirect(f"/ssa/upload/{batch.id}/result/")
            else:
                messages.error(request, result.get("message", "Error uploading file."))
        except Exception as e:
            messages.error(request, f"Upload error: {e}")

    return render(
        request,
        "pages/ssa/upload_center.html",
        {
            "intervention_choices": SsaIntervention.choices,
            "can_add_ssa": _may_upload_ssa(request),
        },
    )


@require_page_permission("ssa")
def ssa_upload_preview_view(request, batch_id):
    # The commit is the moment records are minted, and the preview is its
    # form — both halves take the upload gate, and the batch must be one this
    # reader may open.
    if not _may_upload_ssa(request):
        return render_access_denied(request, UPLOAD_ONLY_MESSAGE)
    batch = get_object_or_404(_visible_batches(request), id=batch_id)
    rows = batch.rows.all()

    if request.method == "POST":
        result = import_ssa_batch(batch, request.user)
        messages.success(
            request,
            f"Import finalized: {result['created']} records wait for verification, {result['unmatched']} unmatched rows queued.",
        )
        return local_redirect(f"/ssa/upload/{batch.id}/result/")

    ready_rows = rows.filter(status="ready")
    unmatched_rows = rows.filter(status="unmatched")
    blocked_rows = rows.filter(status="blocked")

    ready_count = ready_rows.count()
    unmatched_count = unmatched_rows.count()
    blocked_count = blocked_rows.count()

    context = {
        "batch": batch,
        "ready_rows": ready_rows,
        "unmatched_rows": unmatched_rows,
        "blocked_rows": blocked_rows,
        "ready_count": ready_count,
        "unmatched_count": unmatched_count,
        "blocked_count": blocked_count,
        "total_count": ready_count + unmatched_count + blocked_count,
    }
    return render(request, "pages/ssa/upload_preview.html", context)


@require_page_permission("ssa")
def ssa_upload_result_view(request, batch_id):
    """What an import did, row by row where it matters.

    The page used to show four counts and tell the reader to "review any
    unmatched or invalid rows below" with nothing below, then send them to the
    planning board, which Impact Assessment cannot plan into. It now lists the
    blocked rows with the reason each was refused, and links the collection
    worklist and the verification queue the imported records wait in.
    """
    from apps.analytics.ia_collection import db_page

    if not _may_upload_ssa(request):
        return render_access_denied(request, UPLOAD_ONLY_MESSAGE)
    batch = get_object_or_404(_visible_batches(request), id=batch_id)
    rows = batch.rows.all()
    counts = {
        row["status"]: row["n"]
        for row in rows.order_by().values("status").annotate(n=Count("id"))
    }
    blocked = db_page(
        rows.filter(status="blocked").order_by("row_number"),
        request.GET.get("blocked_page"),
    )
    blocked["rows"] = [
        {
            "row_number": row.row_number,
            "school_id": row.school_id or "—",
            "date": row.date_of_ssa or "—",
            "errors": "; ".join(row.validation_errors or []) or "Refused",
        }
        for row in blocked["rows"]
    ]
    created = counts.get("ready", 0)
    context = {
        "batch": batch,
        "processed": sum(counts.values()),
        "created": created,
        "unmatched": counts.get("unmatched", 0),
        "failed": counts.get("blocked", 0),
        # Imported records land pending until a verifier other than the
        # uploader confirms them (IA review, 2026-09-13).
        "pending_verification": created,
        "blocked": blocked,
    }
    return render(request, "pages/ssa/upload_result.html", context)


@require_page_permission("ia_upload_center")
def ssa_upload_history_view(request):
    """Every SSA import this reader may open, with what each one did.

    Upload history used to be the School upload history's global last fifty
    (`UploadBatch.objects.all()`), outside the Impact Assessment navigation.
    This lists SSAImportBatch rows in the reader's country, counted in one
    query, paged in the database, each opening its result page.
    """
    from apps.analytics.ia_collection import db_page

    if not _may_upload_ssa(request):
        return render_access_denied(request, UPLOAD_ONLY_MESSAGE)
    batches = _visible_batches(request).annotate(
        ready_n=Count("rows", filter=Q(rows__status="ready")),
        unmatched_n=Count("rows", filter=Q(rows__status="unmatched")),
        blocked_n=Count("rows", filter=Q(rows__status="blocked")),
    )
    has_blocked = request.GET.get("has_blocked") == "1"
    mine = request.GET.get("mine") == "1"
    if has_blocked:
        batches = batches.filter(blocked_n__gt=0)
    if mine:
        batches = batches.filter(uploaded_by=request.user.user_id)
    page = db_page(
        batches.order_by("-created_at", "-id"), request.GET.get("history_page")
    )
    from django.contrib.auth import get_user_model

    names = dict(
        get_user_model()
        .objects.filter(id__in={b.uploaded_by for b in page["rows"] if b.uploaded_by})
        .values_list("id", "name")
    )
    page["rows"] = [
        {
            "id": batch.id,
            "file_name": batch.file_name or "SSA import",
            "uploaded_by": names.get(batch.uploaded_by, "Unknown user"),
            "uploaded_on": timezone.localtime(batch.created_at),
            "status": (batch.status or "").replace("_", " ").capitalize(),
            "total": batch.total_rows or 0,
            "ready": batch.ready_n,
            "unmatched": batch.unmatched_n,
            "blocked": batch.blocked_n,
            "blocked_tone": "danger" if batch.blocked_n else "",
            "url": f"/ssa/upload/{batch.id}/result/",
        }
        for batch in page["rows"]
    ]
    return render(
        request,
        "pages/ssa/upload_history.html",
        {"pager": page, "has_blocked": has_blocked, "mine": mine},
    )


#: The two lists the verification queue shows.
QUEUE_STATUSES = {
    "pending": "Waiting for verification",
    "returned": "Returned for correction",
}
QUEUE_URL = "/ssa/verification/"


def _collector_label(record, names) -> str:
    who = names.get(record.collected_by_user_id or record.uploaded_by, "")
    kind = {"ia": "Impact Assessment", "partner": "Partner", "staff": "Staff"}.get(
        record.collector_type, (record.collector_type or "").title()
    )
    return f"{who} ({kind})" if who else kind


def _source_label(record) -> str:
    from apps.ssa import services as svc

    return {
        svc.SOURCE_STAFF_KEYED: "Keyed on a visit"
        if record.source_activity_id
        else "Keyed by staff",
        svc.SOURCE_IA_KEYED: "Keyed by Impact Assessment",
        svc.SOURCE_FILE_IMPORT: "File import",
        svc.SOURCE_PARTNER: "Partner submission",
    }.get(record.verification_source or "", "Recorded")


@require_page_permission("ssa")
def ssa_verification_queue_view(request):
    """SSA records waiting for a verifier other than their collector.

    Everyone with the page reads the records in their reach — the country for
    country roles, the portfolio for field roles; the queue used to narrow
    portfolio roles only, so Impact Assessment and the Country Director saw
    every country's assessments. Only a verifier acts, and only on records
    `apps.ssa.services.verifiable_records` offers them: never scores they
    collected or uploaded, and for the Country Director only scores Impact
    Assessment collected (IA review, owner, 2026-09-13).
    """
    from apps.analytics.ia_collection import db_page
    from apps.core.exceptions import Forbidden
    from apps.core.scoping import owner_ids
    from apps.ssa.services import (
        readable_records,
        return_record,
        verifiable_records,
        verify_record,
    )

    if request.method == "POST":
        # Confirming an SSA is the QA control the scoring, targets and impact
        # stack rests on. Everyone else with the page reads the queue; a role
        # that verifies nothing is refused before any record is looked up.
        if not (
            has_permission(request.user, Permission.IA_VERIFY.value)
            or request.user.active_role == "CountryDirector"
        ):
            return render_access_denied(
                request,
                "Only Impact Assessment may confirm or return an SSA record.",
            )
        record_id = request.POST.get("record_id")
        action = request.POST.get("action")
        # Re-derive from the reader's own records: taking the id straight from
        # POST would let a caller act on a record the list never showed them.
        rec = (
            readable_records(request.user)
            .select_related("school")
            .filter(id=record_id)
            .first()
        )
        if rec is None:
            raise Http404("SSA record not found.")
        # The transition itself lives in apps.ssa.services: the authority
        # check, the readiness recompute and the audit row belong to it, not
        # to whichever page happens to be rendering the queue.
        try:
            if action == "verify":
                verify_record(rec, request.user)
                messages.success(
                    request,
                    f"SSA for '{rec.school.name}' has been successfully verified.",
                )
            elif action == "return":
                return_record(rec, request.user, request.POST.get("reason", ""))
                messages.warning(
                    request,
                    f"SSA for '{rec.school.name}' returned for correction; "
                    "the collector has been told why.",
                )
        except Forbidden as exc:
            return render_access_denied(request, str(exc))
        except BadRequest as exc:
            messages.error(request, str(getattr(exc, "detail", exc)))
        from apps.frontend.views.hr_programme_views import _back

        return _back(request, QUEUE_URL)

    status = request.GET.get("status", "")
    status = status if status in QUEUE_STATUSES else "pending"
    mine = request.GET.get("mine") == "1"
    own = [str(i) for i in owner_ids(request.user) if i]
    readable = readable_records(request.user)
    decidable = verifiable_records(request.user)
    records = readable.filter(verification_status=status)
    if mine:
        records = (
            records.filter(collected_by_user_id__in=own) if own else records.none()
        )
    page = db_page(
        records.select_related(
            "school", "school__district", "source_activity"
        ).order_by("-date_of_ssa", "id"),
        request.GET.get("records_page"),
    )
    page_records = page["rows"]
    decidable_ids = set(
        decidable.filter(id__in=[r.id for r in page_records]).values_list(
            "id", flat=True
        )
    )
    from django.contrib.auth import get_user_model

    names = dict(
        get_user_model()
        .objects.filter(
            id__in={
                value
                for r in page_records
                for value in (
                    r.collected_by_user_id,
                    r.uploaded_by,
                    r.returned_by_user_id,
                )
                if value
            }
        )
        .values_list("id", "name")
    )
    rows = []
    for record in page_records:
        is_own = bool(
            own and {record.collected_by_user_id, record.uploaded_by} & set(own)
        )
        can_decide = record.id in decidable_ids and status == "pending"
        if status == "returned":
            state = f"Returned by {names.get(record.returned_by_user_id, 'a verifier')}: {record.return_reason or 'no reason recorded'}"
            tone = "danger"
        elif can_decide:
            state, tone = "Awaiting your verification", "warning"
        elif is_own:
            state, tone = "Your scores: a different verifier confirms them", "neutral"
        else:
            state, tone = "Awaiting a verifier", "neutral"
        visit_url = ""
        visit = record.source_activity
        if visit is not None:
            # The door the reader decides the visit through: a verifier opens
            # staff work in its review workspace and partner work in Partner
            # Evidence; the collector opens their own plan.
            if request.user.active_role in ("ImpactAssessment", "CountryDirector"):
                visit_url = (
                    f"/ia/partner-evidence/{visit.id}/"
                    if visit.delivery_type == "partner"
                    else f"/ia/verification/{visit.id}/"
                )
            else:
                visit_url = f"/my-plan/{visit.id}"
        rows.append(
            {
                "id": record.id,
                "school": record.school.name,
                "school_id": record.school.school_id,
                "school_url": f"/schools/{record.school_id}#ssa-timeline",
                "district": getattr(record.school.district, "name", "") or "—",
                "collector": _collector_label(record, names),
                "source": _source_label(record),
                "date": timezone.localtime(record.date_of_ssa).date()
                if record.date_of_ssa
                else None,
                "average": record.average_score,
                "state": state,
                "tone": tone,
                "can_decide": can_decide,
                "visit_url": visit_url,
            }
        )
    context = {
        "rows": rows,
        "pager": page,
        "status": status,
        "status_label": QUEUE_STATUSES[status],
        "mine": mine,
        "counts": {
            "pending": readable.filter(verification_status="pending").count(),
            "returned": readable.filter(verification_status="returned").count(),
            "decidable": decidable.count(),
        },
        # Kept for templates and tests that ask whether the reader may verify
        # anything at all.
        "can_verify": has_permission(request.user, Permission.IA_VERIFY.value)
        or request.user.active_role == "CountryDirector",
        "total_pending": page["total"] if status == "pending" else None,
    }
    return render(request, "pages/ssa/verification_queue.html", context)


@require_page_permission("ssa")
def ssa_return_drawer_view(request, record_id):
    """One-column drawer: the reason a verifier returns an SSA record."""
    from apps.frontend.views.hr_programme_views import _drawer, _field
    from apps.ssa.services import verifiable_records

    record = (
        verifiable_records(request.user)
        .select_related("school")
        .filter(id=record_id)
        .first()
    )
    if record is None:
        return _drawer(
            request,
            title="Return SSA",
            subtitle="Not available",
            empty=(
                "This SSA is not waiting for your verification: it was decided "
                "already, it is outside your country, or you collected it."
            ),
        )
    when = timezone.localtime(record.date_of_ssa).date() if record.date_of_ssa else None
    return _drawer(
        request,
        title="Return SSA for correction",
        subtitle=record.school.name,
        action=QUEUE_URL,
        facts=[
            {
                "label": "School",
                "value": f"{record.school.name} ({record.school.school_id})",
            },
            {"label": "Assessment date", "value": f"{when:%-d %b %Y}" if when else "—"},
            {"label": "Average score", "value": record.average_score},
            {"label": "How it arrived", "value": _source_label(record)},
        ],
        fields=[
            _field("record_id", "", type="hidden", value=record.id),
            _field("action", "", type="hidden", value="return"),
            _field(
                "reason",
                "What needs correcting",
                type="textarea",
                required=True,
                rows=4,
                maxlength=2000,
                help="The collector is notified with this reason.",
            ),
        ],
        submit="Return SSA",
        note="A returned SSA counts nowhere until it is re-keyed and confirmed.",
        note_tone="warning",
    )


@require_page_permission("ia_dashboard")
def ia_collection_ask_owner_action(request, school_pk):
    """Ask a school's owner to collect its SSA (IA review, owner, 2026-09-13).

    Impact Assessment never plans into a CCEO or Programme Lead portfolio. It
    sends the owner the `no_ssa` TeamAction instead — the same record a
    Programme Lead's "Send" creates, deduplicated by condition, notified,
    threaded and audited by `apps.planning.action_service.send_action` — and
    the action closes itself when a confirmed SSA for this financial year
    exists. Only Impact Assessment sends; the Country Director reads the
    worklist.
    """
    from apps.core.fy import get_operational_fy
    from apps.core.rbac import EdifyRole
    from apps.frontend.views.hr_programme_views import _back
    from apps.analytics.ia_collection import collection_schools
    from apps.planning.action_service import ActionError, send_action
    from apps.planning.urgent_attention import condition_key

    fallback = "/ia/dashboard/?view=collection"
    if request.method != "POST":
        return local_redirect(fallback)
    if request.user.active_role != EdifyRole.IMPACT_ASSESSMENT.value:
        return render_access_denied(
            request, "Only Impact Assessment asks a school's owner to collect an SSA."
        )
    school = collection_schools(request.user).filter(id=school_pk).first()
    if school is None:
        raise Http404("School not found in your country.")
    fy = get_operational_fy()
    if SsaRecord.objects.filter(
        school=school,
        fy=fy,
        verification_status=VerificationStatus.CONFIRMED.value,
        deleted_at__isnull=True,
    ).exists():
        messages.info(request, f"{school.name} already has a confirmed SSA for FY{fy}.")
        return _back(request, fallback)
    issue = {
        "key": "no_ssa",
        "label": "No SSA",
        "severity": "critical",
        "detail": "Current verified SSA is required before intervention performance "
        "can be determined.",
        "condition_key": condition_key(school.id, "no_ssa", fy),
    }
    # The owner the worklist names: the school's account owner, in the
    # StaffProfile space (apps.clusters.eligibility); `send_action` falls back
    # to the portfolio assignment when no account owner is matched.
    from apps.accounts.models import StaffProfile
    from apps.clusters.eligibility import portfolio_owner_profile_id

    owner_id = portfolio_owner_profile_id(school)
    recipient = (
        StaffProfile.objects.select_related("user").filter(id=owner_id).first()
        if owner_id
        else None
    )
    try:
        action = send_action(
            sender=request.user,
            school=school,
            issue=issue,
            fy=fy,
            recipient_staff=recipient,
            note=(request.POST.get("note") or "").strip()
            or "Impact Assessment asks for this school's SSA to be collected.",
        )
    except ActionError as exc:
        messages.error(request, str(exc))
        return _back(request, fallback)
    from apps.planning.action_service import _name_of

    messages.success(
        request,
        f"Asked {_name_of(action.recipient_id)} to collect the SSA for {school.name}. "
        "The request closes itself when a confirmed SSA lands.",
    )
    return _back(request, fallback)
