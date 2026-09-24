from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponseForbidden
from django.contrib import messages
from django.utils import timezone
from datetime import timedelta

from django.db.models import (
    Avg,
    Case,
    DateTimeField,
    DurationField,
    ExpressionWrapper,
    F,
    IntegerField,
    Q,
    Value,
    When,
)
from django.db.models.functions import Coalesce

from apps.core.redirects import local_redirect
from apps.core.donut import build_gauge, build_rings
from apps.core.permissions import (
    RolePermissionService,
    ia_officer_staff_ids,
    require_page_permission,
)
from apps.core.rbac import Permission
from apps.core.scoping import activity_country_q, resolve_user_scope
from apps.audit.services import log as audit_log
from apps.activities.return_notes import COMMON_REASONS as COMMON_RETURN_REASONS
from apps.activities.models import (
    Activity,
    IAVerification,
    VerificationDecision,
    DuplicateActivity,
    VerificationHistory,
)
from apps.activities.ia_services import (
    IAVerificationService,
    DuplicateDetectionService,
    DuplicateReviewService,
    VerificationTimelineService,
    ActivityCertificationService,
    ActivityReturnService,
)
from apps.core.enums import ActivityStatus
from apps.core.exceptions import BadRequest
from apps.core.metrics import MetricValue, render_metric, render_strip
from apps.accounts.staff_matching import on_staff

QUEUE_PAGE_SIZE = 50


def _ia_reach_q(request) -> Q:
    """What this verifier may see: their country, and — for a Country
    Director standing in as the fallback verifier — only the work an Impact
    Assessment officer ran themselves."""
    from apps.core.permissions import has_permission

    scope = resolve_user_scope(request.user)
    q = activity_country_q(scope)
    if not has_permission(request.user, Permission.IA_VERIFY.value):
        q &= Q(responsible_staff_id__in=ia_officer_staff_ids(scope.country or None))
    return q


def _recent_fy_labels(count: int = 4) -> list[str]:
    """The FY labels a reviewer might plausibly filter to, newest first.

    Derived from the canonical FY helper rather than written into the
    template, so the list cannot drift from the values actually stored on
    Activity.fy.
    """
    from apps.core.fy import get_operational_fy

    current = int(get_operational_fy())
    return [str(current - offset) for offset in range(count)]


#: How long an activity may sit in the IA queue before it is late. One
#: constant, because the dashboard reports both a rate ("% verified within
#: SLA" for the week just gone) and a count ("how many are late right now"),
#: and those two numbers disagreeing would be worse than either being absent.
IA_VERIFICATION_SLA_HOURS = 24

#: The activity types the queue ranks first: core package delivery and the
#: baseline assessment visit, whose verification gates finance and outcomes.
IA_CRITICAL_ACTIVITY_TYPES = ("core_visit", "core_training", "baseline_ssa_visit")

#: Statuses of work that has been delivered and should carry a Salesforce ID.
#: Local on purpose, and NOT the platform's ACHIEVED_STATUSES: this asks "what
#: work has been done and is therefore reconcilable", which includes
#: `completed` work that has not yet reached IA and excludes
#: accountant_confirmed, a finance state IA does not act on.
IA_REVIEWABLE_STATUSES = ("completed", "ia_verified", "closed")


# ── What a verifier's pages count (IA review, owner, 2026-09-13) ─────────────
# Impact Assessment is country-bound, and nobody verifies their own work. Every
# count, list and roll-up on the queue and the dashboard is read through these
# helpers, so a number on a tile and the rows it drills into can never come from
# two different populations.


def _ia_scope(request):
    """The reader's resolved scope, once per request."""
    scope = getattr(request, "_ia_scope", None)
    if scope is None:
        scope = resolve_user_scope(request.user)
        request._ia_scope = scope
    return scope


def _ia_own_ids(request) -> list[str]:
    """Both ids the reader's own field work can be recorded against."""
    from apps.core.scoping import owner_ids

    return [str(i) for i in owner_ids(request.user) if i]


def _ia_school_scope(request):
    """The schools this reader's verification pages aggregate over: the
    country for a country-bound verifier or Country Director, the portfolio for
    an IA assistant, the deployment for Admin."""
    from apps.core.scoping import scoped_school_queryset
    from apps.schools.models import School

    return scoped_school_queryset(
        _ia_scope(request), School.objects.filter(deleted_at__isnull=True)
    )


def _ia_activities(request):
    """Every live activity inside this verifier's reach."""
    return Activity.objects.filter(deleted_at__isnull=True).filter(_ia_reach_q(request))


def _ia_staff_queue(request, activities=None):
    """Staff submissions waiting on this verifier: the queue's population.

    Partner submissions are not here: they arrive without a Salesforce ID and
    are verified — Salesforce entry included — in Partner Evidence, so listing
    one here too offered a second door that skipped that step. The reader's own
    field work is not here either: they may not verify it (a colleague does,
    or the Country Director as fallback verifier)."""
    base = activities if activities is not None else _ia_activities(request)
    queue = (
        base.filter(status=ActivityStatus.AWAITING_IA_VERIFICATION)
        .exclude(delivery_type="partner")
        .exclude(Q(salesforce_activity_id__isnull=True) | Q(salesforce_activity_id=""))
    )
    own = _ia_own_ids(request)
    if own:
        queue = queue.exclude(responsible_staff_id__in=own)
    return queue


def _ia_evidence_ready_q() -> Q:
    """An activity with at least one uploaded file that cleared quarantine."""
    from django.db.models import Exists, OuterRef

    from apps.evidence.models import EvidenceRecord

    return Q(
        Exists(
            EvidenceRecord.objects.filter(activity_id=OuterRef("pk"), quarantined=False)
        )
    )


def _ia_unmatched_ssa(request):
    """Imported SSA rows nobody could match, inside the reader's country (one
    definition, shared with the To-Do: apps.activities.ia_todos)."""
    from apps.activities.ia_todos import unmatched_ssa_for_scope

    return unmatched_ssa_for_scope(_ia_scope(request))


def _ia_uploads(request):
    """Upload batches placed in the reader's country by their uploader."""
    from apps.core.scoping import country_bound, country_user_ids
    from apps.schools.models import UploadBatch

    batches = UploadBatch.objects.all()
    scope = _ia_scope(request)
    if country_bound(scope):
        batches = batches.filter(uploaded_by__in=country_user_ids(scope))
    return batches


def _ia_staff_ids_named(value: str) -> set:
    """Staff profile and user ids whose person's name contains `value`.

    responsible_staff_id is a dual id-space field: it holds a StaffProfile id on
    some rows and a User id on others. Resolving names through only one of
    those spaces would quietly match half the queue and look like it worked,
    so both are resolved and unioned."""
    from apps.accounts.models import StaffProfile, User

    return set(
        StaffProfile.objects.filter(user__name__icontains=value).values_list(
            "id", flat=True
        )
    ) | set(User.objects.filter(name__icontains=value).values_list("id", flat=True))


#: The three drill-downs the dashboard's headline tiles open (IA review,
#: 2026-09-13). Each narrows the queue to exactly the population its tile
#: counted and shows itself as a removable chip; they used to be query
#: parameters the queue silently ignored.
IA_QUEUE_DRILLDOWNS = {
    "evidence": {"ready": "Evidence ready for review"},
    "age": {"overdue": "Waiting longer than 24 hours"},
    "sf_id": {"missing": "Delivered work with no Salesforce ID"},
}


@require_page_permission("ia_verification_queue")
def ia_verification_queue_view(request):
    """Central queue of activities waiting for verification.

    Defense-in-depth (2026-07-15 preventive-verification mandate §11): the
    no-SF-ID exclusion keeps STAFF submissions honest — their path into
    "awaiting_ia_verification" requires a Salesforce ID at complete().
    PARTNER submissions deliberately arrive WITHOUT one (IA enters it at
    Confirm Salesforce Entry, §12) — they live in their own queue at
    /ia/partner-evidence/ and are excluded here by delivery type as well.

    Bounded to the verifier's country and never listing their own field work
    (IA review, 2026-09-13; see _ia_staff_queue). `?sf_id=missing` is the one
    drill-down that changes the population: delivered work still missing its
    Salesforce ID, which by construction can never be waiting in the queue."""
    overdue_before = timezone.now() - timedelta(hours=IA_VERIFICATION_SLA_HOURS)
    reach = _ia_activities(request)

    drilldowns = {
        key: request.GET.get(key)
        for key, options in IA_QUEUE_DRILLDOWNS.items()
        if request.GET.get(key) in options
    }
    missing_sf_mode = drilldowns.get("sf_id") == "missing"
    if missing_sf_mode:
        population = reach.filter(status__in=IA_REVIEWABLE_STATUSES).filter(
            Q(salesforce_activity_id__isnull=True) | Q(salesforce_activity_id="")
        )
    else:
        population = _ia_staff_queue(request, reach)
    if drilldowns.get("age") == "overdue":
        population = population.filter(submitted_to_ia_at__lte=overdue_before)
    if drilldowns.get("evidence") == "ready":
        population = population.filter(_ia_evidence_ready_q())

    activities = population.annotate(
        # The queue is operational, not chronological decoration:
        # critical Core/SSA work first, then SLA breaches, then the oldest
        # submission. These ranks are explicit so database ordering and
        # the risk label shown to IA cannot drift apart.
        ia_risk_rank=Case(
            When(activity_type__in=IA_CRITICAL_ACTIVITY_TYPES, then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        ),
        ia_overdue_rank=Case(
            When(submitted_to_ia_at__lte=overdue_before, then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        ),
        ia_submitted_at=Coalesce(
            "submitted_to_ia_at", "updated_at", output_field=DateTimeField()
        ),
    ).order_by("ia_risk_rank", "ia_overdue_rank", "ia_submitted_at", "id")

    # ── KPI Strip Calculation ────────────────────────────────────────────────
    # NOTE: the three counts that describe the QUEUE (waiting, SSA pending,
    # high priority) are computed after filtering — see below. They used to be
    # computed here, before the filters were even read, so the district/staff/
    # type controls changed the table and never touched the headline above it.
    # The throughput figures below read the verifier's reach, not the
    # deployment: another country's verifications are not this desk's day.
    reach_ids = reach.values("id")
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    verified_today = VerificationHistory.objects.filter(
        verified_at__gte=today_start, activity_id__in=reach_ids
    ).count()

    returned_today = VerificationDecision.objects.filter(
        decision="RETURN",
        decided_at__gte=today_start,
        verification__activity_id__in=reach_ids,
    ).count()

    # Verification SLA is measured from the immutable IA-queue entry time,
    # never from Activity.updated_at (which changes during review). Limit the
    # operational headline to the latest 30 days while keeping each history
    # row available for the long-range audit view.
    sla_history = VerificationHistory.objects.filter(
        verified_at__gte=timezone.now() - timedelta(days=30),
        activity__submitted_to_ia_at__isnull=False,
        activity_id__in=reach_ids,
    )
    turnaround = ExpressionWrapper(
        F("verified_at") - F("activity__submitted_to_ia_at"),
        output_field=DurationField(),
    )
    average_duration = sla_history.aggregate(value=Avg(turnaround))["value"]
    avg_hours = (
        round(average_duration.total_seconds() / 3600, 1)
        if average_duration is not None
        else None
    )
    sla_total = sla_history.count()
    sla_compliant_count = sla_history.filter(
        verified_at__lte=F("activity__submitted_to_ia_at")
        + timedelta(hours=IA_VERIFICATION_SLA_HOURS)
    ).count()
    sla_compliance = (
        round((sla_compliant_count / sla_total) * 100, 1) if sla_total else None
    )

    duplicate_risks = (
        DuplicateActivity.objects.filter(status="potential", activity_id__in=reach_ids)
        .values("activity_id")
        .distinct()
        .count()
    )

    # ── Filtering ────────────────────────────────────────────────────────────
    fy_filter = request.GET.get("fy")
    quarter_filter = request.GET.get("quarter")
    month_filter = request.GET.get("month")
    region_filter = request.GET.get("region")
    district_filter = (request.GET.get("district") or "").strip()
    cluster_filter = request.GET.get("cluster")
    school_filter = request.GET.get("school")
    staff_filter = (request.GET.get("staff") or "").strip()
    partner_filter = request.GET.get("partner")
    type_filter = request.GET.get("activity_type")
    project_filter = request.GET.get("project")
    core_school_filter = request.GET.get("core_school")
    status_filter = request.GET.get("status")

    filtered_qs = activities

    if fy_filter:
        filtered_qs = filtered_qs.filter(fy=fy_filter)
    if quarter_filter:
        filtered_qs = filtered_qs.filter(quarter=quarter_filter)
    if month_filter:
        # Activity stores planned_month (int), not "month".
        try:
            filtered_qs = filtered_qs.filter(planned_month=int(month_filter))
        except (TypeError, ValueError):
            pass
    if region_filter:
        filtered_qs = filtered_qs.filter(school__region_id=region_filter)
    if district_filter:
        # The control is a text box ("Kampala, Masaka…"), so a district is
        # matched by name as well as by id: filtering the id column on a typed
        # name emptied the queue without saying why (filter contract).
        filtered_qs = filtered_qs.filter(
            Q(school__district_id=district_filter)
            | Q(school__district__name__icontains=district_filter)
            | Q(event_district__name__icontains=district_filter)
        )
    if cluster_filter:
        filtered_qs = filtered_qs.filter(cluster_id=cluster_filter)
    if school_filter:
        filtered_qs = filtered_qs.filter(school_id=school_filter)
    if staff_filter:
        # Also a text box ("Filter by CCEO name…"): the name resolves to both
        # id spaces responsible_staff_id may hold, and an exact id still works.
        filtered_qs = filtered_qs.filter(
            responsible_staff_id__in=_ia_staff_ids_named(staff_filter) | {staff_filter}
        )
    if partner_filter:
        filtered_qs = filtered_qs.filter(assigned_partner_id=partner_filter)
    if type_filter:
        filtered_qs = filtered_qs.filter(activity_type=type_filter)
    if project_filter:
        filtered_qs = filtered_qs.filter(project_id=project_filter)
    if core_school_filter == "true":
        filtered_qs = filtered_qs.filter(school__school_type="core")
    if status_filter:
        filtered_qs = filtered_qs.filter(status=status_filter)

    # Free-text search over the queue, applied after every filter above so it
    # only ever narrows. The queue had twelve dropdowns and no way to type, yet
    # the thing an IA reviewer is usually handed is a single identifier — a
    # Salesforce ID from an email, or a school name from a phone call — and
    # neither could be typed anywhere on the page.
    #
    # The Salesforce ID is the reason this matters most: every row in this
    # queue is guaranteed to have one (see _ia_staff_queue), so it is the one
    # value that always identifies a record exactly.
    search_q = (request.GET.get("q") or "").strip()
    if search_q:
        filtered_qs = filtered_qs.filter(
            Q(school__name__icontains=search_q)
            | Q(school__school_id__icontains=search_q)
            | Q(salesforce_activity_id__icontains=search_q)
            | Q(school__district__name__icontains=search_q)
            | Q(responsible_staff_id__in=_ia_staff_ids_named(search_q))
        )

    # The queue KPIs, on the population the table below actually shows.
    waiting_count = filtered_qs.count()
    ssa_pending = filtered_qs.filter(ssa_collection_expected=True).count()
    high_priority = filtered_qs.filter(
        activity_type__in=IA_CRITICAL_ACTIVITY_TYPES
    ).count()

    # Serialize for template table
    from apps.activities.services import _serialize
    from django.core.paginator import Paginator

    try:
        page_number = int(request.GET.get("page", 1))
    except (TypeError, ValueError):
        page_number = 1
    paginator = Paginator(
        filtered_qs.select_related("school", "cluster"), QUEUE_PAGE_SIZE
    )
    page_obj = paginator.get_page(page_number)
    page_activities = list(page_obj.object_list)

    # Batch-fetch evidence/SSA existence for the CURRENT PAGE only, instead
    # of one `.exists()` query per activity per field (was unbounded: 2
    # queries x every row in the queue, not just the page being rendered).
    from apps.evidence.models import EvidenceRecord
    from apps.ssa.models import SsaRecord

    page_activity_ids = [a.id for a in page_activities]
    page_school_ids = [a.school_id for a in page_activities if a.school_id]
    activities_with_evidence = set(
        EvidenceRecord.objects.filter(
            activity_id__in=page_activity_ids, quarantined=False
        )
        .values_list("activity_id", flat=True)
        .distinct()
    )
    schools_with_ssa = set(
        SsaRecord.objects.filter(school_id__in=page_school_ids, deleted_at__isnull=True)
        .values_list("school_id", flat=True)
        .distinct()
    )

    serialized_queue = []
    now = timezone.now()
    for a in page_activities:
        data = _serialize(a)
        # Add quick checks recommendation
        data["has_evidence"] = a.id in activities_with_evidence
        data["has_sf_id"] = bool(a.salesforce_activity_id)
        data["has_ssa"] = bool(a.school_id) and a.school_id in schools_with_ssa
        data["is_high_priority"] = a.activity_type in IA_CRITICAL_ACTIVITY_TYPES
        submitted_at = a.submitted_to_ia_at or a.updated_at
        age_hours = max(0, int((now - submitted_at).total_seconds() // 3600))
        is_overdue = age_hours >= IA_VERIFICATION_SLA_HOURS
        if missing_sf_mode:
            salesforce_status = "Missing"
            next_action = "No Salesforce ID — the responsible officer records it"
        else:
            salesforce_status = "Confirm ID"
            next_action = (
                "Evidence ready — verify Salesforce ID"
                if data["has_evidence"]
                else "Evidence missing — return to staff"
            )
        data.update(
            {
                "submitted_at": submitted_at,
                "age_hours": age_hours,
                "age_label": (
                    f"{age_hours // 24}d {age_hours % 24}h"
                    if age_hours >= 24
                    else f"{age_hours}h"
                ),
                "is_overdue": is_overdue,
                "risk_label": (
                    "Critical"
                    if data["is_high_priority"]
                    else "High"
                    if is_overdue
                    else "Standard"
                ),
                "evidence_status": (
                    "Ready for review" if data["has_evidence"] else "Evidence missing"
                ),
                "salesforce_status": salesforce_status,
                "next_action_status": next_action,
            }
        )
        serialized_queue.append(data)

    # People, not identifiers: the queue printed the responsible person's
    # raw staff id.
    from apps.activities.verification_analytics import _partner_names, _staff_names

    _queue_names = _staff_names({d.get("responsibleStaffId") for d in serialized_queue})
    _queue_partners = _partner_names(
        {d.get("assignedPartnerId") for d in serialized_queue}
    )
    for d in serialized_queue:
        d["responsibleStaffName"] = _queue_names.get(
            d.get("responsibleStaffId"), d.get("responsibleStaffId") or "Unassigned"
        )
        d["assignedPartnerName"] = _queue_partners.get(d.get("assignedPartnerId"), "")

    # Each active drill-down as a chip, with the URL that removes it and keeps
    # everything else the reader chose.
    drilldown_chips = []
    for key, value in drilldowns.items():
        remaining = request.GET.copy()
        remaining.pop(key, None)
        remaining.pop("page", None)
        query = remaining.urlencode()
        drilldown_chips.append(
            {
                "key": key,
                "value": value,
                "label": IA_QUEUE_DRILLDOWNS[key][value],
                "clear_url": "/ia/verification/" + (f"?{query}" if query else ""),
            }
        )

    context = {
        "queue": serialized_queue,
        "page_obj": page_obj,
        "drilldowns": drilldown_chips,
        "missing_sf_mode": missing_sf_mode,
        # The queue offered twelve dropdowns and nowhere to type. A reviewer is
        # usually handed one identifier — a Salesforce ID, a school name — and
        # had to translate it into filter selections to find the row.
        "topbar_search": {
            "placeholder": "Search verification queue…",
            "label": "Search the queue by school, School ID, Salesforce ID or owner",
            "name": "q",
            "value": search_q,
            "hx_get": "/ia/verification/",
            "hx_target": "#queue-table-container",
            "hx_trigger": "keyup changed delay:250ms, search",
            "hx_include": "#filters-form",
        },
        "kpis": {
            "waiting": waiting_count,
            "verified_today": verified_today,
            "returned_today": returned_today,
            "avg_time": f"{avg_hours:g}h" if avg_hours is not None else "—",
            "sla_compliance": sla_compliance,
            "sla_sample_size": sla_total,
            "ssa_pending": ssa_pending,
            "duplicate_risks": duplicate_risks,
            "high_priority": high_priority,
        },
        "filters": {
            "fy": fy_filter,
            "quarter": quarter_filter,
            "district": district_filter,
            "cluster": cluster_filter,
            "staff": staff_filter,
            "partner": partner_filter,
            "activity_type": type_filter,
            "core_school": core_school_filter,
        },
        # The template used to hard-code FY24/FY25/FY26. `Activity.fy` holds a
        # four-digit year ("2026" — see apps.core.fy.get_operational_fy), so
        # every one of those options filtered on a value no row has ever had
        # and silently emptied the queue. Options come from the FY helper now.
        "fy_options": _recent_fy_labels(),
        "filters_active": any(
            (
                fy_filter,
                quarter_filter,
                district_filter,
                staff_filter,
                type_filter,
                core_school_filter,
                search_q,
                drilldowns,
            )
        ),
    }

    if request.headers.get("HX-Request") == "true":
        return render(request, "pages/ia/partials/queue_table.html", context)

    return render(request, "pages/ia/verification_queue.html", context)


@require_page_permission("ia_review_workspace")
def ia_review_workspace_view(request, activity_id):
    """Premium workspace for verifying a single activity."""
    a = get_object_or_404(
        Activity.objects.filter(_ia_reach_q(request)),
        id=activity_id,
        deleted_at__isnull=True,
    )
    # Partner work is reviewed on the partner evidence page, which carries the
    # Salesforce confirmation step this workspace does not (IA review,
    # 2026-09-13).
    if a.delivery_type == "partner":
        return redirect(f"/ia/partner-evidence/{a.id}/")

    # Resolve checks
    checks = IAVerificationService.get_verification_checks(a)

    # Run duplicate checks
    dups = DuplicateDetectionService.detect_duplicates(a)

    # Fetch evidence records
    from apps.evidence.models import EvidenceRecord

    evidence_list = EvidenceRecord.objects.filter(activity_id=a.id, quarantined=False)

    # Show the actual confirmed SSA values for this activity's school/FY. The
    # previous workspace displayed four invented scores whenever the generic
    # "SSA uploaded" check was true, which could mislead an IA decision.
    ssa_scores = []
    if a.school_id:
        from apps.core.enums import SsaIntervention
        from apps.ssa.models import SsaRecord

        ssa_record = (
            SsaRecord.objects.filter(
                school_id=a.school_id,
                fy=a.fy,
                verification_status="confirmed",
                deleted_at__isnull=True,
            )
            .prefetch_related("scores")
            .order_by("-date_of_ssa")
            .first()
        )
        if ssa_record:
            labels = dict(SsaIntervention.choices)
            ssa_scores = [
                {
                    "label": labels.get(score.intervention, score.intervention),
                    "value": score.score,
                }
                for score in ssa_record.scores.all().order_by("intervention")
            ]

    # Fetch timeline
    timeline = VerificationTimelineService.get_timeline(a)

    # Fetch comments
    verification = IAVerification.objects.filter(activity=a).first()
    comments = verification.comments.all() if verification else []

    # Fetch cluster schools for school-level attendance list verification
    cluster_schools = []
    if a.cluster:
        from apps.schools.models import School

        cluster_schools = list(
            School.objects.filter(
                cluster_id=a.cluster_id, deleted_at__isnull=True
            ).order_by("name")
        )

    from apps.activities.verification_analytics import _partner_names, _staff_names

    _ws_names = _staff_names({a.responsible_staff_id})
    _ws_partners = _partner_names({a.assigned_partner_id})
    context = {
        "act": a,
        "owner_name": _ws_names.get(
            a.responsible_staff_id, a.responsible_staff_id or "Unassigned"
        ),
        "partner_name": _ws_partners.get(a.assigned_partner_id, ""),
        "checks": checks,
        "duplicates": dups,
        "evidence_list": evidence_list,
        "timeline": timeline,
        "comments": comments,
        "cluster_schools": cluster_schools,
        "ssa_scores": ssa_scores,
        # The most common reasons first, the owner's own example at the top
        # (2026-09-24: "the participants are not entered" in Salesforce).
        "open_return": request.GET.get("return") == "1",
        "suggested_reasons": list(
            dict.fromkeys([*COMMON_RETURN_REASONS, *LEGACY_IA_REASONS])
        ),
    }
    return render(request, "pages/ia/review_workspace.html", context)


#: The workspace's original return categories, kept so verification analytics
#: keep counting the same strings (apps.activities.verification_analytics).
LEGACY_IA_REASONS = (
    "Evidence missing",
    "Evidence unclear",
    "Attendance invalid",
    "Attendance missing",
    "SSA missing",
    "SSA incomplete",
    "Wrong School",
    "Wrong Cluster",
    "Wrong Intervention",
    "Wrong Activity Type",
    "Wrong Activity Date",
    "Duplicate Activity",
    "Activity SF ID missing",
    "Activity SF ID invalid",
    "Poor Data Quality",
    "Other",
)


@require_page_permission("ia_review_workspace")
def ia_verify_action(request, activity_id):
    """POST to approve and certify the activity."""
    a = get_object_or_404(
        Activity.objects.filter(_ia_reach_q(request)),
        id=activity_id,
        deleted_at__isnull=True,
    )
    if a.delivery_type == "partner":
        return redirect(f"/ia/partner-evidence/{a.id}/")

    if not RolePermissionService.can_verify_ia(request.user, a):
        return HttpResponseForbidden("Access Denied: Unauthorized role.")

    if request.method == "POST":
        checklist_data = {
            "evidence_exists": request.POST.get("evidence_exists") == "on",
            "attendance_valid": request.POST.get("attendance_valid") == "on",
            "ssa_uploaded": request.POST.get("ssa_uploaded") == "on",
            "correct_school": request.POST.get("correct_school") == "on",
            "correct_cluster": request.POST.get("correct_cluster") == "on",
            "correct_intervention": request.POST.get("correct_intervention") == "on",
            "sf_id_entered": request.POST.get("sf_id_entered") == "on",
            "duplicate_check_passed": request.POST.get("duplicate_check_passed")
            == "on",
            "analytics_ready": request.POST.get("analytics_ready") == "on",
        }

        try:
            ActivityCertificationService.certify_activity(
                a, checklist_data, request.user.user_id
            )

            audit_log(
                action="ia_verify_completion",
                subject_kind="Activity",
                subject_id=str(a.id),
                actor_id=str(request.user.id),
                actor_role=request.user.active_role,
                success=True,
                payload=checklist_data,
            )
            messages.success(
                request,
                f"Activity at {a.school.name if a.school else 'Cluster'} certified successfully!",
            )
        except Exception as e:
            messages.error(request, f"Verification failed: {e}")

    return redirect("/ia/verification/")


@require_page_permission("ia_review_workspace")
def ia_return_action(request, activity_id):
    """POST to return activity for correction."""
    a = get_object_or_404(
        Activity.objects.filter(_ia_reach_q(request)),
        id=activity_id,
        deleted_at__isnull=True,
    )
    if a.delivery_type == "partner":
        return redirect(f"/ia/partner-evidence/{a.id}/")

    if not RolePermissionService.can_verify_ia(request.user, a):
        return HttpResponseForbidden("Access Denied: Unauthorized role.")

    if request.method == "POST":
        reasons = request.POST.getlist("reasons")
        comment = request.POST.get("comment", "").strip()

        if not reasons:
            messages.error(request, "Please select at least one return reason.")
            return local_redirect(f"/ia/verification/{activity_id}/?return=1")
        if not comment:
            # The service refuses it too; saying so here keeps the reviewer
            # on the activity with the panel open rather than on the queue.
            messages.error(
                request,
                "Say why you are returning it, so the officer knows what to fix.",
            )
            return local_redirect(f"/ia/verification/{activity_id}/?return=1")

        try:
            ActivityReturnService.return_activity(
                a, reasons, comment, request.user.user_id
            )

            audit_log(
                action="ia_return_completion",
                subject_kind="Activity",
                subject_id=str(a.id),
                actor_id=str(request.user.id),
                actor_role=request.user.active_role,
                success=True,
                payload={"reasons": reasons, "comment": comment},
            )
            messages.success(
                request, "Activity returned to owner's plan for correction."
            )
        except Exception as e:
            messages.error(request, f"Return failed: {e}")

    return redirect("/ia/verification/")


@require_page_permission("ia_returned")
def ia_returned_view(request):
    """History of everything IA has returned."""
    returned_activities = (
        Activity.objects.filter(
            deleted_at__isnull=True, status=ActivityStatus.RETURNED_BY_IA
        )
        .filter(_ia_reach_q(request))
        .order_by("-updated_at")
    )

    from apps.activities.verification_analytics import _staff_names

    _returned_names = _staff_names(
        set(returned_activities.values_list("responsible_staff_id", flat=True))
    )
    serialized_returned = []
    for a in returned_activities.select_related("school", "ia_verification"):
        reasons = []
        if hasattr(a, "ia_verification") and a.ia_verification:
            reasons = [rr.reason for rr in a.ia_verification.returned_reasons.all()]

        # Resubmitted is true if a CCEO edited and sent back (or if status moved away from returned_by_ia)
        # Since we filter by status=RETURNED_BY_IA, it is currently NOT resubmitted.
        serialized_returned.append(
            {
                "id": a.id,
                "activity_type_label": a.get_activity_type_display(),
                "school_id": a.school_id,
                "school_name": a.school.name if a.school else "Cluster",
                "responsible_staff_name": _returned_names.get(
                    a.responsible_staff_id, a.responsible_staff_id or "Unassigned"
                ),
                "reasons": ", ".join(reasons) or "None Specified",
                "date_returned": a.updated_at,
                "status_label": a.get_status_display(),
                "resubmitted": False,
            }
        )

    context = {"returned": serialized_returned}
    return render(request, "pages/ia/returned_activities.html", context)


@require_page_permission("ia_history")
def ia_history_view(request):
    """Everything IA has verified."""
    from apps.activities.verification_analytics import (
        _names,
        _partner_names,
        _staff_names,
    )

    entries = list(
        VerificationHistory.objects.filter(
            activity__in=Activity.objects.filter(_ia_reach_q(request)).values("id")
        )
        .order_by("-verified_at")
        .select_related("activity", "activity__school", "activity__cluster")
    )
    # The ledger printed raw staff, partner and verifier ids. People, not
    # identifiers, is what an auditor reads.
    staff = _staff_names({e.activity.responsible_staff_id for e in entries})
    partners = _partner_names({e.activity.assigned_partner_id for e in entries})
    verifiers = _names({e.verified_by for e in entries})
    history = [
        {
            "id": e.activity.id,
            "activity_type": e.activity.get_activity_type_display(),
            "school_id": e.activity.school_id,
            "school": e.activity.school.name
            if e.activity.school_id
            else "Cluster-wide",
            "cluster": e.activity.cluster.name if e.activity.cluster_id else "",
            "partner": partners.get(e.activity.assigned_partner_id, "")
            if e.activity.assigned_partner_id
            else "",
            "staff": staff.get(
                e.activity.responsible_staff_id,
                e.activity.responsible_staff_id or "Unassigned",
            ),
            "verified_by": verifiers.get(e.verified_by, e.verified_by),
            "verified_at": e.verified_at,
            "analytics_included": e.analytics_included,
        }
        for e in entries
    ]
    context = {"history": history}
    return render(request, "pages/ia/verification_history.html", context)


@require_page_permission("ia_duplicates")
def ia_duplicates_view(request):
    """Duplicate review queue dashboard."""
    duplicates = DuplicateActivity.objects.filter(
        status="potential",
        activity__in=Activity.objects.filter(_ia_reach_q(request)).values("id"),
    ).select_related(
        "activity", "activity__school", "duplicate_of", "duplicate_of__school"
    )

    from apps.activities.verification_analytics import _staff_names

    duplicates = list(duplicates)
    owner_names = _staff_names(
        {d.activity.responsible_staff_id for d in duplicates}
        | {d.duplicate_of.responsible_staff_id for d in duplicates}
    )
    for d in duplicates:
        d.activity.owner_name = owner_names.get(
            d.activity.responsible_staff_id,
            d.activity.responsible_staff_id or "Unassigned",
        )
        d.duplicate_of.owner_name = owner_names.get(
            d.duplicate_of.responsible_staff_id,
            d.duplicate_of.responsible_staff_id or "Unassigned",
        )
    context = {"duplicates": duplicates}
    return render(request, "pages/ia/duplicate_review.html", context)


@require_page_permission("ia_duplicates")
def ia_duplicate_action(request, duplicate_id):
    """Handles actions on potential duplicates: merge, ignore, return, flag."""
    action = request.POST.get("action")

    if action in {"ignore", "flag", "return"}:
        try:
            DuplicateReviewService.decide(duplicate_id, action, request.user)
        except BadRequest as exc:
            messages.error(request, str(exc.detail))
            return redirect("/ia/duplicates/")
    if action == "ignore":
        messages.success(request, "Duplicate flag ignored.")
    elif action == "flag":
        messages.success(request, "Activity flagged for investigation.")
    elif action == "return":
        messages.success(request, "Activity returned and duplicate flag resolved.")

    return redirect("/ia/duplicates/")


def _ia_week_window():
    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=now.weekday())  # Monday
    week_end = week_start + timedelta(days=6)
    return now, today_start, week_start, week_end


def _ia_header_context(request) -> dict:
    """The fixed part of the IA dashboard: header, KPI strip and phone queue.

    One strip, the same on every view and after every tab swap (owner rule:
    the header, KPI strip and attention band never move). It used to render
    only when the page was first loaded on Map or Operations, so a tab press
    left the verification strip beside the Outcomes tiles, or took it away.
    Six registry tiles, one per question the verification desk answers each
    morning; each drills into a queue that shows exactly what it counted.
    """
    from django.db.models import Count
    from django.utils.timesince import timesince

    from apps.accounts.models import StaffProfile, User

    now, _today_start, week_start, week_end = _ia_week_window()
    overdue_before = now - timedelta(hours=IA_VERIFICATION_SLA_HOURS)
    activities = _ia_activities(request)
    queue = _ia_staff_queue(request, activities)

    queue_counts = queue.aggregate(
        waiting=Count("id"),
        overdue=Count(
            "id",
            filter=Q(
                submitted_to_ia_at__isnull=False,
                submitted_to_ia_at__lte=overdue_before,
            ),
        ),
        evidence_ready=Count("id", filter=_ia_evidence_ready_q()),
    )
    ledger_counts = activities.aggregate(
        missing_sf=Count(
            "id",
            filter=Q(status__in=IA_REVIEWABLE_STATUSES)
            & (Q(salesforce_activity_id__isnull=True) | Q(salesforce_activity_id="")),
        ),
        returned_open=Count("id", filter=Q(status=ActivityStatus.RETURNED_BY_IA)),
    )
    unmatched_ssa_cnt = _ia_unmatched_ssa(request).count()

    # ── The oldest waiting records (the phone's queue and primary action) ───
    queue_activities = list(
        queue.select_related("school", "school__district").order_by(
            F("submitted_to_ia_at").asc(nulls_last=True), "updated_at"
        )[:6]
    )
    staff_ids = {
        a.responsible_staff_id for a in queue_activities if a.responsible_staff_id
    }
    user_names = (
        dict(User.objects.filter(id__in=staff_ids).values_list("id", "name"))
        if staff_ids
        else {}
    )
    staff_profile_names = (
        dict(
            StaffProfile.objects.filter(id__in=staff_ids).values_list(
                "id", "user__name"
            )
        )
        if staff_ids
        else {}
    )
    staff_names = {**user_names, **staff_profile_names}
    queue_items = []
    for activity in queue_activities:
        submitted_at = activity.submitted_to_ia_at or activity.updated_at
        age_hours = (now - submitted_at).total_seconds() / 3600
        queue_items.append(
            {
                "id": str(activity.id),
                "record_id": str(activity.id)[-8:].upper(),
                "review_url": f"/ia/verification/{activity.id}/",
                "school_id": activity.school_id,
                "school": activity.school.name if activity.school else "Cluster-wide",
                "district": (
                    activity.school.district.name
                    if activity.school and activity.school.district_id
                    else "No district"
                ),
                "activity_type": activity.get_activity_type_display(),
                "submitted_by": staff_names.get(
                    activity.responsible_staff_id,
                    activity.responsible_staff_id or "Unassigned",
                ),
                "submission_date": timezone.localtime(submitted_at).strftime(
                    "%d %b %Y, %I:%M %p"
                ),
                "submitted_relative": f"{timesince(submitted_at, now)} ago",
                "is_overdue": age_hours > IA_VERIFICATION_SLA_HOURS,
            }
        )

    last_batch = _ia_uploads(request).order_by("-created_at").first()

    kpi_strip_items = render_strip(
        [
            render_metric(
                "ia_awaiting_verification",
                MetricValue.measured(queue_counts["waiting"]),
                drilldown_url="/ia/verification/",
            ),
            render_metric(
                "ia_evidence_ready_for_review",
                MetricValue.measured(queue_counts["evidence_ready"]),
                drilldown_url="/ia/verification/?evidence=ready",
            ),
            render_metric(
                "ia_salesforce_verification_pending",
                MetricValue.measured(ledger_counts["missing_sf"]),
                drilldown_url="/ia/verification/?sf_id=missing",
            ),
            render_metric(
                "ia_returned_for_correction",
                MetricValue.measured(ledger_counts["returned_open"]),
                drilldown_url="/ia/returned/",
            ),
            render_metric(
                "ia_unmatched_ssa_records",
                MetricValue.measured(unmatched_ssa_cnt),
                drilldown_url="/ssa/unmatched",
            ),
            render_metric(
                "ia_verification_overdue",
                MetricValue.measured(queue_counts["overdue"]),
                drilldown_url="/ia/verification/?age=overdue",
            ),
        ]
    )
    date_range = (
        f"{week_start.strftime('%b')} {week_start.day} – "
        f"{week_end.strftime('%b')} {week_end.day}, {week_end.year}"
    )
    return {
        "kpi_strip_items": kpi_strip_items,
        "kpis": {
            "waiting": queue_counts["waiting"],
            "overdue": queue_counts["overdue"],
            "evidence_ready": queue_counts["evidence_ready"],
            "sf_queue": ledger_counts["missing_sf"],
            "returned_open": ledger_counts["returned_open"],
            "unmatched_ssa": unmatched_ssa_cnt,
        },
        "date_range": date_range,
        "queue_items": queue_items,
        "upload_status": {
            "last_upload": last_batch.created_at if last_batch else None,
        },
        "mobile_primary_action": {
            "label": "Review oldest record"
            if queue_items
            else "Open verification queue",
            "url": queue_items[0]["review_url"] if queue_items else "/ia/verification/",
        },
        "ia_mobile_status": f"{queue_counts['waiting']} waiting",
    }


def _ia_districts(request):
    """The districts this reader monitors: the country's, the portfolio's
    for an IA assistant, every one for Admin."""
    from apps.core.scoping import country_bound
    from apps.geography.models import District

    scope = _ia_scope(request)
    districts = District.objects.all()
    if country_bound(scope):
        return districts.filter(region__country=scope.country)
    if not scope.country_scope:
        return districts.filter(id__in=_ia_school_scope(request).values("district_id"))
    return districts


def _ia_regions(request):
    from apps.core.scoping import country_bound
    from apps.geography.models import Region

    scope = _ia_scope(request)
    regions = Region.objects.all()
    if country_bound(scope):
        return regions.filter(country=scope.country)
    if not scope.country_scope:
        return regions.filter(id__in=_ia_school_scope(request).values("region_id"))
    return regions


IA_ROLLUP_METRICS = ("planned", "achieved", "verified", "waiting", "returned")


def _ia_rollup_counts(values_queryset):
    from django.db.models import Count

    from apps.targets.performance import ACHIEVED_STATUSES

    return values_queryset.annotate(
        planned=Count("id"),
        achieved=Count("id", filter=Q(status__in=ACHIEVED_STATUSES)),
        verified=Count("id", filter=Q(ia_verification_status="confirmed")),
        waiting=Count("id", filter=Q(status=ActivityStatus.AWAITING_IA_VERIFICATION)),
        returned=Count("id", filter=Q(status=ActivityStatus.RETURNED_BY_IA)),
    )


def _ia_activity_rollup(queryset, geography_field):
    return {
        row[geography_field]: row
        for row in _ia_rollup_counts(
            queryset.exclude(**{f"{geography_field}__isnull": True}).values(
                geography_field
            )
        )
    }


def _ia_activity_rollup_pair(queryset, district_field, region_field):
    """`_ia_activity_rollup` by a district field and by a region field, from
    one GROUP BY over both: the counts are sums, so adding up the (district,
    region) groups gives every district's and every region's exactly. One
    scan of the reach where there were two."""
    by_district: dict = {}
    by_region: dict = {}
    for row in _ia_rollup_counts(queryset.values(district_field, region_field)):
        for field, rollup in ((district_field, by_district), (region_field, by_region)):
            key = row[field]
            if key is None:
                continue
            totals = rollup.setdefault(
                key, {field: key, **dict.fromkeys(IA_ROLLUP_METRICS, 0)}
            )
            for metric in IA_ROLLUP_METRICS:
                totals[metric] += row[metric]
    return by_district, by_region


def _ia_merge_rollups(*rollups):
    merged = {"planned": 0, "achieved": 0, "verified": 0, "waiting": 0, "returned": 0}
    for rollup in rollups:
        if not rollup:
            continue
        for key in merged:
            merged[key] += rollup.get(key, 0)
    merged["rate"] = (
        round(merged["achieved"] / merged["planned"] * 100) if merged["planned"] else 0
    )
    return merged


def _ia_performance_activities(request):
    """This FY's live plans in reach: the base of every roll-up below."""
    from apps.core.fy import get_operational_fy

    return (
        _ia_activities(request)
        .filter(fy=get_operational_fy())
        .exclude(status__in=("cancelled", "rejected", "deferred"))
    )


def _ia_school_reach_sets(request, performance_qs):
    """School reach (owner, 2026-09-05): active schools per district, and the
    schools with planned and achieved work per district and per owner.

    Two queries serve every row on the page: the active schools in scope with
    their district, and the year's activities with owner, school, district and
    status; everything else is set arithmetic, so the query count stays a
    constant."""
    from apps.schools.lifecycle_service import active_schools
    from apps.targets.performance import ACHIEVED_STATUSES

    active_school_ids = set()
    schools_by_district: dict = {}
    for school_id, district_id in active_schools(_ia_school_scope(request)).values_list(
        "id", "district_id"
    ):
        active_school_ids.add(school_id)
        if district_id:
            schools_by_district[district_id] = (
                schools_by_district.get(district_id, 0) + 1
            )
    planned_by_district: dict = {}
    achieved_by_district: dict = {}
    planned_by_owner: dict = {}
    achieved_by_owner: dict = {}
    # Unordered: these become sets read by key, and sorting the year's
    # activities by the model's default -created_at was a quarter of the query.
    for owner_id, school_id, district_id, status in (
        performance_qs.exclude(school_id__isnull=True)
        .order_by()
        .values_list(
            "responsible_staff_id", "school_id", "school__district_id", "status"
        )
    ):
        planned_by_owner.setdefault(owner_id, set()).add(school_id)
        if district_id:
            planned_by_district.setdefault(district_id, set()).add(school_id)
        if status in ACHIEVED_STATUSES:
            achieved_by_owner.setdefault(owner_id, set()).add(school_id)
            if district_id:
                achieved_by_district.setdefault(district_id, set()).add(school_id)
    return {
        "active_school_ids": active_school_ids,
        "schools_by_district": schools_by_district,
        "planned_by_district": planned_by_district,
        "achieved_by_district": achieved_by_district,
        "planned_by_owner": planned_by_owner,
        "achieved_by_owner": achieved_by_owner,
    }


def _ia_reach_from_sets(assigned, planned, achieved):
    return {
        "schools": len(assigned),
        "schools_planned": len(planned),
        "schools_achieved": len(achieved),
        "schools_pct": round(len(achieved) / len(assigned) * 100) if assigned else 0,
    }


def _ia_merge_school_reach(rows):
    schools = sum(row["schools"] for row in rows)
    achieved = sum(row["schools_achieved"] for row in rows)
    return {
        "schools": schools,
        "schools_planned": sum(row["schools_planned"] for row in rows),
        "schools_achieved": achieved,
        "schools_pct": round(achieved / schools * 100) if schools else 0,
    }


def _ia_geography_context(request, performance_qs=None, reach_sets=None) -> dict:
    """Regional performance and district monitoring, bounded to the reader's
    country: the Map view's tables and the Verification Quality tab's cards.

    These are completion/verification facts from the Activity ledger, not a
    separate reporting store. Programme activities without a school inherit
    geography through event_district, so central work is not lost from the
    regional and district views.
    """
    if performance_qs is None:
        performance_qs = _ia_performance_activities(request)
    if reach_sets is None:
        reach_sets = _ia_school_reach_sets(request, performance_qs)

    school_district_rollup, school_region_rollup = _ia_activity_rollup_pair(
        performance_qs, "school__district_id", "school__region_id"
    )
    event_district_rollup = _ia_activity_rollup(performance_qs, "event_district_id")

    def _school_reach(district_id):
        schools = reach_sets["schools_by_district"].get(district_id, 0)
        achieved = len(reach_sets["achieved_by_district"].get(district_id, set()))
        return {
            "schools": schools,
            "schools_planned": len(
                reach_sets["planned_by_district"].get(district_id, set())
            ),
            "schools_achieved": achieved,
            "schools_pct": round(achieved / schools * 100) if schools else 0,
        }

    district_performance = []
    # Districts fold under their sub-region, the way clusters fold under the
    # person who holds them: one row per sub-region carrying the roll-up,
    # opened into its districts (owner, 2026-09-05). A district with no
    # sub-region sits under "Other districts" in its region rather than
    # vanishing.
    district_groups_by_key: dict = {}
    for district in (
        _ia_districts(request)
        .select_related("region", "sub_region")
        .order_by("region__name", "sub_region__name", "name")
    ):
        metrics = _ia_merge_rollups(
            school_district_rollup.get(district.id),
            event_district_rollup.get(district.id),
        )
        row = {
            "name": district.name,
            "region": district.region.name,
            "sub_region": district.sub_region.name if district.sub_region else None,
            **metrics,
            **_school_reach(district.id),
        }
        district_performance.append(row)
        key = (district.region.name, row["sub_region"] or "")
        group = district_groups_by_key.setdefault(
            key,
            {
                "key": f"{district.region_id}-{district.sub_region_id or 'other'}",
                "name": row["sub_region"] or "Other districts",
                "region": district.region.name,
                "districts": [],
            },
        )
        group["districts"].append(row)
    district_groups = []
    for group in district_groups_by_key.values():
        group.update(_ia_merge_rollups(*group["districts"]))
        group.update(_ia_merge_school_reach(group["districts"]))
        group["count"] = len(group["districts"])
        district_groups.append(group)

    event_region_rollup = _ia_activity_rollup(
        performance_qs, "event_district__region_id"
    )
    region_performance = [
        {
            "name": region.name,
            **_ia_merge_rollups(
                school_region_rollup.get(region.id), event_region_rollup.get(region.id)
            ),
        }
        for region in _ia_regions(request).order_by("name")
    ]
    return {
        "district_performance": district_performance,
        "district_groups": district_groups,
        "region_performance": region_performance,
    }


def _ia_operations_context(request, header: dict) -> dict:
    """The verification operations beneath the fixed header: the queue, open
    queues, exceptions, activity flow, CCEO and Programme Lead performance,
    quality, coverage and SSA review — every figure bounded to the reader's
    country (IA review, 2026-09-13), where they used to read the deployment."""
    from django.db.models import Avg, Count
    from django.db.models.functions import TruncWeek
    from django.utils.timesince import timesince

    from apps.accounts.models import (
        StaffProfile,
        StaffSchoolAssignment,
        StaffSupervisorAssignment,
        User,
    )
    from apps.core.enums import EvidenceKind, SsaIntervention
    from apps.core.fy import get_operational_fy
    from apps.core.rbac import EdifyRole
    from apps.debriefs.rollup_service import field_debrief_intelligence_summary
    from apps.evidence.models import EvidenceRecord
    from apps.partners.models import Partner
    from apps.ssa.models import SsaRecord, SsaScore

    now, today_start, week_start, _week_end = _ia_week_window()
    fy = get_operational_fy()
    scope = _ia_scope(request)

    activities = _ia_activities(request)
    reach_ids = activities.values("id")
    waiting_qs = _ia_staff_queue(request, activities)
    schools = _ia_school_scope(request)
    kpis = header["kpis"]
    waiting_cnt = kpis["waiting"]
    missing_sf_id = kpis["sf_queue"]
    returned_open = kpis["returned_open"]

    history = VerificationHistory.objects.filter(activity_id__in=reach_ids)
    decisions = VerificationDecision.objects.filter(
        verification__activity_id__in=reach_ids
    )
    verified_today = history.filter(verified_at__gte=today_start).count()
    verified_week = history.filter(verified_at__gte=week_start).count()

    # Verification SLA is measured from the moment an activity enters the IA
    # queue to its recorded verification.  Keep the query bounded to the
    # current and previous week so the dashboard remains constant-cost while
    # still providing an honest week-over-week comparison.
    previous_week_start = week_start - timedelta(days=7)
    sla_rows = history.filter(
        verified_at__gte=previous_week_start,
        verified_at__lte=now,
        activity__submitted_to_ia_at__isnull=False,
    ).values_list("verified_at", "activity__submitted_to_ia_at")
    current_sla_durations = []
    previous_sla_durations = []
    for verified_at, submitted_at in sla_rows:
        duration_hours = (verified_at - submitted_at).total_seconds() / 3600
        if verified_at >= week_start:
            current_sla_durations.append(duration_hours)
        else:
            previous_sla_durations.append(duration_hours)

    def _sla_percentage(durations):
        if not durations:
            return None
        return round(
            sum(duration <= IA_VERIFICATION_SLA_HOURS for duration in durations)
            / len(durations)
            * 100,
            1,
        )

    current_sla_pct = _sla_percentage(current_sla_durations)
    previous_sla_pct = _sla_percentage(previous_sla_durations)
    sla_delta = (
        round(current_sla_pct - previous_sla_pct, 1)
        if current_sla_pct is not None and previous_sla_pct is not None
        else None
    )
    verification_sla = {
        "pct": current_sla_pct,
        "sample_size": len(current_sla_durations),
        "previous_pct": previous_sla_pct,
        "delta": sla_delta,
    }
    verification_sla["gauge"] = (
        build_gauge(
            current_sla_pct,
            label="Within SLA",
            color="var(--edify-success)",
        )
        if current_sla_pct is not None
        else None
    )
    returned_today = decisions.filter(
        decision="RETURN", decided_at__gte=today_start
    ).count()
    returned_open_school_cnt = (
        activities.filter(status=ActivityStatus.RETURNED_BY_IA)
        .exclude(school_id__isnull=True)
        .values("school_id")
        .distinct()
        .count()
    )
    duplicate_risk_cnt = DuplicateActivity.objects.filter(
        status="potential", activity_id__in=reach_ids
    ).count()

    # ── Awaiting Follow-up (Grid Row 5) — real return→correction cycle time,
    # pairing each RETURN decision with the next APPROVE on the same
    # verification (a second RETURN before that APPROVE starts a new cycle).
    decision_rows = list(
        decisions.filter(decision__in=("RETURN", "APPROVE"))
        .order_by("verification_id", "decided_at")
        .values("verification_id", "decision", "decided_at")
    )
    decisions_by_verification = {}
    for row in decision_rows:
        decisions_by_verification.setdefault(row["verification_id"], []).append(row)
    resolution_days = []
    for rows in decisions_by_verification.values():
        pending_return_at = None
        for row in rows:
            if row["decision"] == "RETURN":
                pending_return_at = row["decided_at"]
            elif row["decision"] == "APPROVE" and pending_return_at:
                resolution_days.append(
                    (row["decided_at"] - pending_return_at).total_seconds() / 86400
                )
                pending_return_at = None
    avg_resolution_days = (
        round(sum(resolution_days) / len(resolution_days), 1)
        if resolution_days
        else None
    )

    # ── School-derived KPIs, one aggregate over the schools in scope ────────
    school_facts = schools.aggregate(
        total=Count("id"),
        ssa_done=Count("id", filter=Q(current_fy_ssa_status="done")),
        ssa_scheduled=Count(
            "id", filter=Q(current_fy_ssa_status__in=["scheduled", "partner_assigned"])
        ),
        duplicates=Count(
            "id", filter=Q(duplicate_status__in=["potential", "confirmed"])
        ),
        not_clean=Count("id", filter=~Q(data_quality_status="Clean")),
        quality_avg=Avg("data_quality_score"),
    )
    school_total = school_facts["total"]
    ssa_done_cnt = school_facts["ssa_done"]
    ssa_scheduled_cnt = school_facts["ssa_scheduled"]
    ssa_not_done_cnt = school_total - ssa_done_cnt - ssa_scheduled_cnt
    ssa_coverage = round(ssa_done_cnt / school_total * 100, 1) if school_total else 0.0
    quality_avg = school_facts["quality_avg"]
    quality_pct = round(quality_avg) if quality_avg is not None else 0
    dup_school_cnt = school_facts["duplicates"]

    ssa_records = SsaRecord.objects.filter(deleted_at__isnull=True, school__in=schools)
    evidence = EvidenceRecord.objects.filter(
        quarantined=False, activity_id__in=reach_ids
    )
    # Each table is read once: today's SSA uploads ride on the review donut's
    # aggregate, and the evidence waiting for review is the sum of the
    # per-kind panel's "uploaded" counts. Same rows, same figures.
    ssa_record_facts = ssa_records.aggregate(
        total=Count("id"),
        confirmed=Count("id", filter=Q(verification_status="confirmed")),
        pending=Count("id", filter=Q(verification_status="pending")),
        created_today=Count("id", filter=Q(created_at__gte=today_start)),
    )
    evidence_by_kind = list(
        evidence.values("kind")
        .annotate(
            submitted=Count("id"),
            verified=Count("id", filter=Q(status="accepted")),
            returned=Count("id", filter=Q(status="returned")),
            rejected=Count("id", filter=Q(status="rejected")),
            uploaded=Count("id", filter=Q(status="uploaded")),
        )
        .order_by("-submitted")
    )
    evidence_pending = sum(row["uploaded"] for row in evidence_by_kind)
    uploads_today = (
        ssa_record_facts["created_today"]
        + EvidenceRecord.objects.filter(
            created_at__gte=today_start, activity_id__in=reach_ids
        ).count()
    )

    # ── District SSA completion stats (shared by exceptions + leaderboard) ──
    district_stats = list(
        _ia_districts(request)
        .annotate(
            total=Count("schools", filter=Q(schools__in=schools)),
            done=Count(
                "schools",
                filter=Q(schools__in=schools, schools__current_fy_ssa_status="done"),
            ),
        )
        .filter(total__gt=0)
    )
    districts_below_target = sum(1 for d in district_stats if d.done / d.total < 0.5)

    # ── Alerts / Exceptions (only real, non-zero conditions) ────────────────
    overdue_returns = activities.filter(
        status=ActivityStatus.RETURNED_BY_IA, updated_at__lt=now - timedelta(days=7)
    ).count()
    failed_uploads = (
        _ia_uploads(request).filter(status__in=["failed", "rejected"]).count()
    )
    exceptions = [
        e
        for e in [
            {
                "count": missing_sf_id,
                "text": "completed/verified activities missing Salesforce IDs",
                "severity": "error",
                "href": "/ia/verification/?sf_id=missing",
            },
            {
                "count": duplicate_risk_cnt,
                "text": "activities flagged as potential duplicates",
                "severity": "warning",
                "href": "/ia/duplicates/",
            },
            {
                "count": dup_school_cnt,
                "text": "schools flagged as potential duplicates",
                "severity": "warning",
                "href": "/data-quality/duplicates",
            },
            {
                # SSA Performance, reached from IA's workspace strip; the
                # generic Analytics hub is not an Impact Assessment door.
                "count": districts_below_target,
                "text": "districts below 50% SSA completion",
                "severity": "info",
                "href": "/ssa",
            },
            {
                "count": overdue_returns,
                "text": "activities returned for correction over 7 days ago",
                "severity": "warning",
                "href": "/ia/returned/",
            },
            {
                "count": failed_uploads,
                "text": "bulk uploads failed validation",
                "severity": "error",
                "href": "/uploads?tab=imports",
            },
        ]
        if e["count"] > 0
    ]

    # ── Data Quality & Compliance panel ─────────────────────────────────────
    dq_metrics = [
        {"label": "Schools Missing SSA", "value": school_total - ssa_done_cnt},
        {
            "label": "Duplicate Records Detected",
            "value": duplicate_risk_cnt + dup_school_cnt,
        },
        {"label": "Schools with Missing Fields", "value": school_facts["not_clean"]},
        {"label": "Activities Missing Salesforce IDs", "value": missing_sf_id},
    ]

    # ── SSA monitoring: lowest-performing interventions (0–10 score scale) ──
    # Confirmed-only (an unverified upload must not rank interventions), and
    # scoped strictly to the selected FY. There used to be a silent
    # all-time fallback here when the current FY had no rows, which
    # presented historical scores under a current-FY heading with nothing
    # telling the reader the period had changed — better to show an honest
    # empty state.
    score_rows = SsaScore.objects.filter(
        ssa_record__deleted_at__isnull=True,
        ssa_record__fy=fy,
        ssa_record__verification_status="confirmed",
        ssa_record__school__in=schools,
    )
    intervention_labels = dict(SsaIntervention.choices)
    lowest_performing = [
        {
            "name": intervention_labels.get(r["intervention"], r["intervention"]),
            "rate": round(r["avg"] / 10 * 100),
        }
        for r in score_rows.values("intervention")
        .annotate(avg=Avg("score"))
        .order_by("avg")[:5]
    ]

    # ── District SSA completion leaderboard (min 5 schools) ─────────────────
    leaderboard_dc = sorted(
        (
            {"name": d.name, "rate": round(d.done / d.total * 100)}
            for d in district_stats
            if d.total >= 5
        ),
        key=lambda item: -item["rate"],
    )[:5]

    # ── SSA donuts: school coverage + record review status ──────────────────
    from apps.core.metrics import percentage_or_zero as _pct

    ssa_overview = {
        "total": school_total,
        "done": ssa_done_cnt,
        "done_pct": _pct(ssa_done_cnt, school_total),
        "scheduled": ssa_scheduled_cnt,
        "scheduled_pct": _pct(ssa_scheduled_cnt, school_total),
        "not_done": ssa_not_done_cnt,
        "not_done_pct": _pct(ssa_not_done_cnt, school_total),
    }
    ssa_overview["scheduled_offset"] = -ssa_overview["done_pct"]
    ssa_overview["not_done_offset"] = -(
        ssa_overview["done_pct"] + ssa_overview["scheduled_pct"]
    )
    # Concentric rings: each state a share of the schools in scope, with "not
    # done" carried too — the gap is the point of this chart.
    ssa_overview["rings"] = build_rings(
        [
            {
                "key": "done",
                "label": "SSA done",
                "value": ssa_done_cnt,
                "color": "var(--edify-success)",
            },
            {
                "key": "scheduled",
                "label": "Scheduled",
                "value": ssa_scheduled_cnt,
                "color": "var(--edify-warning)",
            },
            {
                "key": "not_done",
                "label": "Not done",
                "value": ssa_not_done_cnt,
                "color": "var(--edify-danger)",
            },
        ],
        share_of=school_total or None,
    )

    ssa_rec_total = ssa_record_facts["total"]
    ssa_rec_confirmed = ssa_record_facts["confirmed"]
    ssa_rec_pending = ssa_record_facts["pending"]
    ssa_rec_other = ssa_rec_total - ssa_rec_confirmed - ssa_rec_pending
    ssa_review = {
        "total": ssa_rec_total,
        "confirmed": ssa_rec_confirmed,
        "confirmed_pct": _pct(ssa_rec_confirmed, ssa_rec_total),
        "pending": ssa_rec_pending,
        "pending_pct": _pct(ssa_rec_pending, ssa_rec_total),
        "other": ssa_rec_other,
        "other_pct": _pct(ssa_rec_other, ssa_rec_total),
    }
    ssa_review["rings"] = build_rings(
        [
            {
                "key": "confirmed",
                "label": "Confirmed",
                "value": ssa_rec_confirmed,
                "color": "var(--edify-chart-teal)",
            },
            {
                "key": "pending",
                "label": "Pending",
                "value": ssa_rec_pending,
                "color": "var(--edify-warning)",
            },
            {
                "key": "other",
                "label": "Returned / flagged",
                "value": ssa_rec_other,
                "color": "var(--edify-danger)",
            },
        ],
        share_of=ssa_rec_total or None,
    )

    # ── Evidence review panel (grouped by kind, split by review status) ─────
    kind_labels = dict(EvidenceKind.choices)
    evidence_metrics = [
        {
            "category": kind_labels.get(row["kind"], row["kind"]),
            "submitted": row["submitted"],
            "verified": row["verified"],
            "returned": row["returned"],
            "rejected": row["rejected"],
        }
        for row in evidence_by_kind
    ]
    evidence_totals = {
        "submitted": sum(m["submitted"] for m in evidence_metrics),
        "verified": sum(m["verified"] for m in evidence_metrics),
        "returned": sum(m["returned"] for m in evidence_metrics),
        "rejected": sum(m["rejected"] for m in evidence_metrics),
    }

    # ── Recent activity feed (verifications + returns, merged by time) ──────
    def _activity_detail(a):
        school = a.school.name if a.school else "Cluster"
        district = a.school.district.name if a.school and a.school.district_id else ""
        return f"{school}, {district}" if district else school

    events = []
    for vh in history.select_related(
        "activity", "activity__school", "activity__school__district"
    ).order_by("-verified_at")[:5]:
        events.append(
            {
                "title": f"{vh.activity.get_activity_type_display()} verified",
                "detail": _activity_detail(vh.activity),
                "ts": vh.verified_at,
            }
        )
    for vd in (
        decisions.filter(decision="RETURN")
        .select_related(
            "verification__activity",
            "verification__activity__school",
            "verification__activity__school__district",
        )
        .order_by("-decided_at")[:5]
    ):
        events.append(
            {
                "title": f"{vd.verification.activity.get_activity_type_display()} returned for correction",
                "detail": _activity_detail(vd.verification.activity),
                "ts": vd.decided_at,
            }
        )
    events.sort(key=lambda e: e["ts"], reverse=True)
    recent_activities = [
        {
            "title": e["title"],
            "detail": e["detail"],
            "time": f"{timesince(e['ts'])} ago",
        }
        for e in events[:5]
    ]

    # ── Field monitoring leaderboards ───────────────────────────────────────
    pending_rows = list(
        waiting_qs.exclude(responsible_staff_id__isnull=True)
        .exclude(responsible_staff_id="")
        .values("responsible_staff_id")
        .annotate(c=Count("id"))
        .order_by("-c")[:5]
    )
    verifier_rows = list(
        history.filter(verified_at__gte=week_start)
        .values("verified_by")
        .annotate(c=Count("id"))
        .order_by("-c")[:5]
    )
    fm_user_ids = {r["responsible_staff_id"] for r in pending_rows} | {
        r["verified_by"] for r in verifier_rows
    }
    fm_names = (
        dict(User.objects.filter(id__in=fm_user_ids).values_list("id", "name"))
        if fm_user_ids
        else {}
    )

    # Partner submissions wait in their own queue, so they are read from the
    # reach directly rather than from the staff queue above.
    partner_rows = list(
        activities.filter(
            status=ActivityStatus.AWAITING_IA_VERIFICATION, delivery_type="partner"
        )
        .exclude(assigned_partner_id__isnull=True)
        .exclude(assigned_partner_id="")
        .values("assigned_partner_id")
        .annotate(c=Count("id"))
        .order_by("-c")[:5]
    )
    partner_names = (
        dict(
            Partner.objects.filter(
                id__in=[r["assigned_partner_id"] for r in partner_rows]
            ).values_list("id", "name")
        )
        if partner_rows
        else {}
    )

    field_monitoring = {
        "highest_pending": [
            {
                "name": fm_names.get(
                    r["responsible_staff_id"], r["responsible_staff_id"]
                ),
                "count": r["c"],
            }
            for r in pending_rows
        ],
        "partner_submissions": [
            {
                "name": partner_names.get(
                    r["assigned_partner_id"], r["assigned_partner_id"]
                ),
                "count": r["c"],
            }
            for r in partner_rows
        ],
        "top_verifiers": [
            {"name": fm_names.get(r["verified_by"], r["verified_by"]), "count": r["c"]}
            for r in verifier_rows
        ],
    }

    # ── IA country oversight: every CCEO and PL in the country ──────────────
    performance_qs = _ia_performance_activities(request)
    reach_sets = _ia_school_reach_sets(request, performance_qs)

    # Activity.responsible_staff_id deliberately accepts either StaffProfile
    # or User ids for compatibility. Aggregate once, then resolve both id
    # spaces in memory so the roster remains constant-query at any team size.
    owner_rollup = _ia_activity_rollup(performance_qs, "responsible_staff_id")
    from apps.core.scoping import country_bound

    roster = on_staff(StaffProfile.objects)
    if country_bound(scope):
        roster = roster.filter(country=scope.country)
    active_staff_roster = list(
        # on_staff, not is_active: a pending-invite CCEO created by a school upload already holds their portfolio.
        roster.select_related("user").order_by("user__name")
    )
    monitored_staff = [
        staff
        for staff in active_staff_roster
        if {EdifyRole.CCEO.value, EdifyRole.COUNTRY_PROGRAM_LEAD.value}.intersection(
            set(staff.user.roles or []) | {staff.user.active_role}
        )
    ]
    staff_by_id = {staff.id: staff for staff in active_staff_roster}
    team_ids_by_pl = {}
    pl_by_supervisee: dict = {}
    for supervisor_id, supervisee_id in StaffSupervisorAssignment.objects.filter(
        supervisor_id__in=[
            staff.id
            for staff in monitored_staff
            if EdifyRole.COUNTRY_PROGRAM_LEAD.value
            in (set(staff.user.roles or []) | {staff.user.active_role})
        ]
    ).values_list("supervisor_id", "supervisee_id"):
        supervisee = staff_by_id.get(supervisee_id)
        if supervisee:
            team_ids_by_pl.setdefault(supervisor_id, set()).update(
                {supervisee.id, supervisee.user_id}
            )
            pl_by_supervisee.setdefault(supervisee.id, supervisor_id)

    # School reach per leader (owner, 2026-09-05): the schools in a CCEO's
    # portfolio, how many of them have planned and achieved work this year,
    # and the share. A Program Lead's figures are the team's, consolidated as
    # SETS — a school two CCEOs both touched is one school reached, and the
    # portfolio is the union of the team's portfolios plus the lead's own.
    assigned_schools_by_staff: dict = {}
    for staff_id, school_id in StaffSchoolAssignment.objects.filter(
        staff_id__in=[staff.id for staff in monitored_staff]
    ).values_list("staff_id", "school_id"):
        if school_id in reach_sets["active_school_ids"]:
            assigned_schools_by_staff.setdefault(staff_id, set()).add(school_id)
    leadership_performance = []
    school_sets_by_staff: dict = {}
    for staff in monitored_staff:
        roles = set(staff.user.roles or []) | {staff.user.active_role}
        is_pl = EdifyRole.COUNTRY_PROGRAM_LEAD.value in roles
        owner_ids = (
            team_ids_by_pl.get(staff.id, set()) | {staff.id, staff.user_id}
            if is_pl
            else {staff.id, staff.user_id}
        )
        metrics = _ia_merge_rollups(
            *(owner_rollup.get(owner_id) for owner_id in owner_ids)
        )
        # Portfolio holders are StaffProfile ids; activity owners may be either
        # id space, so reach is read across both.
        portfolio_ids = {staff.id} | (
            {oid for oid in owner_ids if oid in assigned_schools_by_staff}
            if is_pl
            else set()
        )
        sets = (
            set().union(
                *(assigned_schools_by_staff.get(sid, set()) for sid in portfolio_ids)
            ),
            set().union(
                *(reach_sets["planned_by_owner"].get(oid, set()) for oid in owner_ids)
            ),
            set().union(
                *(reach_sets["achieved_by_owner"].get(oid, set()) for oid in owner_ids)
            ),
        )
        school_sets_by_staff[staff.id] = sets
        leadership_performance.append(
            {
                "staff_id": staff.id,
                "name": staff.user.name,
                "role": "Program Lead" if is_pl else "CCEO",
                "scope": "Team portfolio" if is_pl else "Owned activities",
                "supervisor_id": None if is_pl else pl_by_supervisee.get(staff.id),
                **metrics,
                **_ia_reach_from_sets(*sets),
            }
        )
    leadership_performance.sort(
        key=lambda row: (row["role"] != "Program Lead", row["name"].casefold())
    )

    # CCEOs fold under the Program Lead who supervises them, the way clusters
    # fold under the person who holds them: the Program Lead's row is the
    # header, carrying the team portfolio, opened into the team (owner,
    # 2026-09-05). A CCEO nobody supervises sits under "No Program Lead".
    leaders_by_id = {
        row["staff_id"]: row
        for row in leadership_performance
        if row["role"] == "Program Lead"
    }
    leadership_groups = [
        {**row, "key": row["staff_id"], "members": []} for row in leaders_by_id.values()
    ]
    unsupervised = {
        "key": "unsupervised",
        "name": "No Program Lead",
        "role": None,
        "scope": "CCEOs without a supervisor",
        "members": [],
    }
    for row in leadership_performance:
        if row["role"] != "CCEO":
            continue
        home = next(
            (
                group
                for group in leadership_groups
                if group["key"] == row["supervisor_id"]
            ),
            None,
        )
        (home or unsupervised)["members"].append(row)
    if unsupervised["members"]:
        unsupervised.update(_ia_merge_rollups(*unsupervised["members"]))
        member_sets = [
            school_sets_by_staff[m["staff_id"]] for m in unsupervised["members"]
        ]
        unsupervised.update(
            _ia_reach_from_sets(
                *(set().union(*(sets[i] for sets in member_sets)) for i in range(3))
            )
        )
        leadership_groups.append(unsupervised)
    for group in leadership_groups:
        group["count"] = len(group["members"])

    # Eight-week planned-versus-IA-verified line chart, drawn by the chart
    # system from these weekly values (2026-09-05), with text/table
    # equivalents retained for accessibility and zero-JavaScript rendering.
    trend_start = week_start - timedelta(weeks=7)
    planned_by_week = {
        row["week_bucket"].date()
        if hasattr(row["week_bucket"], "date")
        else row["week_bucket"]: row["count"]
        for row in performance_qs.filter(planned_date__gte=trend_start.date())
        .annotate(week_bucket=TruncWeek("planned_date"))
        .values("week_bucket")
        .annotate(count=Count("id"))
    }
    verified_by_week = {
        row["week_bucket"].date()
        if hasattr(row["week_bucket"], "date")
        else row["week_bucket"]: row["count"]
        for row in history.filter(verified_at__gte=trend_start)
        .annotate(week_bucket=TruncWeek("verified_at"))
        .values("week_bucket")
        .annotate(count=Count("id"))
    }
    weekly_values = []
    for offset in range(8):
        start = (trend_start + timedelta(weeks=offset)).date()
        weekly_values.append(
            {
                "label": start.strftime("%d %b"),
                "planned": planned_by_week.get(start, 0),
                "verified": verified_by_week.get(start, 0),
            }
        )
    trend_max = max(
        [1]
        + [row["planned"] for row in weekly_values]
        + [row["verified"] for row in weekly_values]
    )
    activity_trend = {"weeks": weekly_values, "max": trend_max}

    return {
        "fy": fy,
        "kpis": {
            **kpis,
            "waiting": waiting_cnt,
            "verified_today": verified_today,
            "verified_week": verified_week,
            "returned_today": returned_today,
            "returned_open": returned_open,
            "duplicate_risk": duplicate_risk_cnt,
            "ssa_coverage": f"{ssa_coverage}%",
            "quality": f"{quality_pct}%",
            "quality_pct": quality_pct,
            "uploads_today": uploads_today,
            "sf_queue": missing_sf_id,
            "ssa_pending_review": ssa_rec_pending,
            "evidence_pending": evidence_pending,
        },
        "exceptions": exceptions,
        "dq_metrics": dq_metrics,
        "lowest_performing": lowest_performing,
        "leaderboard_dc": leaderboard_dc,
        "ssa_overview": ssa_overview,
        "ssa_review": ssa_review,
        "evidence_metrics": evidence_metrics,
        "evidence_totals": evidence_totals,
        "recent_activities": recent_activities,
        "field_monitoring": field_monitoring,
        "leadership_performance": leadership_performance,
        "leadership_groups": leadership_groups,
        "activity_trend": activity_trend,
        "upload_status": {**header["upload_status"], "failed": failed_uploads},
        "returned_open_school_cnt": returned_open_school_cnt,
        "avg_resolution_days": avg_resolution_days,
        "verification_sla": verification_sla,
        "field_debrief_intel": field_debrief_intelligence_summary(request.user),
        # Carried for the operations roll-ups below the queue and the
        # Verification Quality tab's geography cards.
        "_performance_qs": performance_qs,
        "_reach_sets": reach_sets,
    }


def _ia_dashboard_context(request) -> dict:
    """Everything the IA dashboard shows, computed live, for the Analytics
    workspace's Verification Quality tab (owner, 2026-09-05): the fixed header
    context, the operations and the geography cards together.

    /ia/dashboard/ itself builds only the part each view renders
    (IA_DASHBOARD_VIEW_BUILDERS below).
    """
    context = _ia_header_context(request)
    operations = _ia_operations_context(request, context)
    performance_qs = operations.pop("_performance_qs")
    reach_sets = operations.pop("_reach_sets")
    context.update(operations)
    context.update(_ia_geography_context(request, performance_qs, reach_sets))
    return context


# ── The IA dashboard's views (IA review, owner, 2026-09-13) ──────────────────
# The dashboard opens on Outcomes (owner decision, 2026-09-13), with Map one
# tab away. Each view builds only what it renders on top of the fixed header:
# Outcomes, Collection and Impact reports read the outcome workspace and never
# the verification operations; Map reads the country map and the geography
# roll-ups; Operations reads the verification operations. The static
# Framework and Programme learning tabs are gone — their destinations are real
# pages (/ia/framework/, /ia/learning/) — and an old ?view= value for either
# falls back to the default.
IA_DASHBOARD_DEFAULT_VIEW = "outcomes"
IA_DASHBOARD_TABS = (
    ("outcomes", "Outcomes", "School change and the strength of its evidence"),
    (
        "today",
        "Today",
        "The next SSA to verify and every decision waiting on you",
    ),
    ("collection", "Collection", "Schools whose assessment evidence needs collecting"),
    ("reports", "Impact reports", "Prepare traceable findings and recommendations"),
    ("map", "Map", "The country map with regional performance and district monitoring"),
    (
        "operations",
        "Operations",
        "Verification queue, performance, quality and coverage",
    ),
)
#: The partial the Reports view renders. Reporting & Accountability (IA-R)
#: provides it; until it exists the outcome workspace's draft report renders.
IA_REPORTS_VIEW_TEMPLATE = "partials/ia/reports_view.html"
#: An optional context builder for the Reports view, "module:function" with
#: the signature fn(request) -> dict, provided by the impact report lifecycle.
IA_REPORTS_CONTEXT_BUILDER = "apps.impact.reports:dashboard_reports_context"


def _ia_outcome_workspace_context(request, *, collection: bool = False) -> dict:
    from django.core.paginator import Paginator

    from apps.analytics.ia_workflow import outcome_workspace

    workspace = outcome_workspace(request.user, request.GET)
    rows = workspace["rows"]
    gap = request.GET.get("gap", "")
    if collection:
        rows = [row for row in rows if not row["measured"]]
        if gap:
            rows = [row for row in rows if row["state"] == gap]
    return {
        "ia_outcomes": workspace,
        "ia_evidence_page": Paginator(rows, 25).get_page(request.GET.get("page")),
        "ia_gap": gap,
        "ia_can_export": RolePermissionService.can_export(request.user, "ia_dashboard"),
        "ia_view_template": "partials/ia/outcomes.html",
    }


def _ia_outcomes_view(request, header: dict) -> dict:
    return _ia_outcome_workspace_context(request)


def _ia_collection_view(request, header: dict) -> dict:
    """The collection worklist over every operationally active school in
    scope (apps.analytics.ia_collection), beside the project enrolments'
    missing baselines and follow-ups the outcome workspace lists."""
    from apps.analytics.ia_collection import collection_worklist

    context = _ia_outcome_workspace_context(request, collection=True)
    context["ia_collection"] = collection_worklist(request.user, request.GET)
    return context


def _ia_reports_view(request, header: dict) -> dict:
    from importlib import import_module

    from django.template import TemplateDoesNotExist
    from django.template.loader import select_template

    context = _ia_outcome_workspace_context(request)
    module_name, _, attr = IA_REPORTS_CONTEXT_BUILDER.partition(":")
    try:
        builder = getattr(import_module(module_name), attr, None)
    except ModuleNotFoundError as exc:
        # Only the absence of the report module itself is expected; a module
        # that exists and fails to import is a defect and must surface.
        if exc.name != module_name:
            raise
        builder = None
    if builder is not None:
        context.update(builder(request) or {})
    try:
        context["ia_view_template"] = select_template(
            [IA_REPORTS_VIEW_TEMPLATE]
        ).template.name
    except TemplateDoesNotExist:
        pass
    return context


def _ia_map_view(request, header: dict) -> dict:
    from apps.analytics.country_map_context import country_map_context
    from apps.core.fy import get_operational_fy

    context = dict(country_map_context(get_operational_fy()))
    context.update(_ia_geography_context(request))
    return context


def _ia_operations_view(request, header: dict) -> dict:
    context = _ia_operations_context(request, header)
    context.pop("_performance_qs")
    context.pop("_reach_sets")
    return context


def _ia_today_view(request, header: dict) -> dict:
    # The panel fetches the workbench from /today/panel once the dashboard has
    # painted (apps.frontend.views.today_views.today_panel).
    return {}


IA_DASHBOARD_VIEW_BUILDERS = {
    "outcomes": _ia_outcomes_view,
    "today": _ia_today_view,
    "collection": _ia_collection_view,
    "reports": _ia_reports_view,
    "map": _ia_map_view,
    "operations": _ia_operations_view,
}


@require_page_permission("ia_dashboard")
def ia_dashboard_view(request):
    """Impact Assessment's home: school outcomes first, the work one tab away."""
    from apps.frontend.views.dashboard_view_state import (
        dashboard_view_tabs,
        remember_dashboard_view,
        resolve_dashboard_view,
    )

    dashboard_view, view_explicit = resolve_dashboard_view(
        request,
        role_key="ia",
        default=IA_DASHBOARD_DEFAULT_VIEW,
        allowed=tuple(IA_DASHBOARD_VIEW_BUILDERS),
    )
    context = _ia_header_context(request)
    context.update(IA_DASHBOARD_VIEW_BUILDERS[dashboard_view](request, context))
    context["ia_dashboard_tabs"] = True
    context["dashboard_view"] = dashboard_view
    context["dashboard_tabs"] = dashboard_view_tabs(
        request,
        active=dashboard_view,
        panel_id="ia-dashboard-view",
        view_template="partials/ia/view.html",
        tabs=list(IA_DASHBOARD_TABS),
        base_url="/ia/dashboard/",
        keep=("project",),
    )
    if request.headers.get("HX-Target") == "ia-dashboard-view-shell":
        response = render(
            request,
            "partials/dashboards/_view_tabs.html",
            {**context, "dashboard_tabs_inner": True},
        )
    else:
        response = render(request, "pages/ia/analytics_dashboard.html", context)
    if view_explicit:
        remember_dashboard_view(response, role_key="ia", view=dashboard_view)
    return response


@require_page_permission("ia_dashboard")
def verification_quality_section_view(request):
    """Verification Quality as a tab of the one Analytics page."""

    context = _ia_dashboard_context(request)
    from apps.frontend.views.analytics_render import render_analytics_section

    return render_analytics_section(
        request,
        "partials/analytics/panels/verification_quality.html",
        context,
        section_key="verification_quality",
        panel_title="Verification Quality",
        frame={
            "question": (
                "What must Impact Assessment verify next, where is quality risk "
                "accumulating, and what is blocking trusted reporting?"
            ),
            "evidence": "Verification queues, evidence quality and SSA coverage",
            "freshness": context["date_range"],
            "confidence": "Verification-controlled",
        },
    )


#: The notification categories Impact Assessment's own notices travel under.
IA_NOTIFICATION_CATEGORIES = ("verification", "ia", "ssa")


@require_page_permission("ia_notifications")
def ia_notifications_view(request):
    """Realtime notifications audit feed page."""
    from apps.notifications.models import Notification

    # Addressed to THIS user. Selecting by title substring across the whole
    # table returned notifications belonging to every other user — and
    # `icontains="IA"` matches any title merely containing those letters,
    # including free-text field-debrief titles that can carry restricted
    # incident detail.
    #
    # Verification notices reach IA under three categories — "verification"
    # (submissions, the morning digest), "ssa" and "ia" (returns) — and the
    # page read only "ia", so it was always empty for the people it is named
    # for (IA review, 2026-09-13). Each notice opens its own record.
    alerts = Notification.objects.filter(
        recipient_id=request.user.id, category__in=IA_NOTIFICATION_CATEGORIES
    ).order_by("-created_at")[:50]

    context = {"alerts": alerts}
    return render(request, "pages/ia/notifications.html", context)


@require_page_permission("ia_compare")
def ia_compare_view(request):
    """Compares planned vs actual activity fields and attached evidence side-by-side."""
    activity_id = request.GET.get("activity_id")
    a = None
    timeline = []
    evidence_list = []
    ssa_record = None

    waiting_list = (
        Activity.objects.filter(
            _ia_reach_q(request),
            deleted_at__isnull=True,
            status="awaiting_ia_verification",
        )
        .select_related("school", "cluster")
        .order_by("created_at", "id")
    )
    # Choose from the same authorised queue as the selector, not another
    # country's first record (which made an otherwise valid page return 404).
    if not activity_id:
        first_waiting = waiting_list.first()
        if first_waiting:
            activity_id = first_waiting.id

    if activity_id:
        a = get_object_or_404(
            Activity.objects.filter(_ia_reach_q(request)),
            id=activity_id,
            deleted_at__isnull=True,
        )
        timeline = VerificationTimelineService.get_timeline(a)
        from apps.evidence.models import EvidenceRecord

        evidence_list = EvidenceRecord.objects.filter(
            activity_id=a.id, quarantined=False
        )

        if a.school:
            from apps.ssa.models import SsaRecord

            ssa_record = (
                SsaRecord.objects.filter(school=a.school, deleted_at__isnull=True)
                .order_by("-date_of_ssa")
                .first()
            )

    context = {
        "act": a,
        "timeline": timeline,
        "evidence_list": evidence_list,
        "ssa_record": ssa_record,
        "waiting_list": waiting_list,
        "selected_activity_id": activity_id,
    }
    return render(request, "pages/ia/compare_evidence.html", context)


@require_page_permission("activity_timeline")
def activity_timeline_view(request, activity_id):
    """Visual walkthrough step-by-step history log for auditing."""
    a = get_object_or_404(
        Activity.objects.filter(_ia_reach_q(request)),
        id=activity_id,
        deleted_at__isnull=True,
    )
    timeline = VerificationTimelineService.get_timeline(a)

    context = {"act": a, "timeline": timeline}
    return render(request, "pages/ia/activity_timeline.html", context)


# ── §10–12 Partner Evidence & Salesforce Confirmation ────────────────────────
# Partner evidence comes DIRECTLY to IA. This is the dedicated queue: review
# each submission against its plan, then Return (correction) or Complete
# (Confirm Salesforce Entry). Completing records the Salesforce ID and opens
# payment eligibility — it never marks the partner paid.


def _partner_queue_row(a, partner_names, partner_users, today):
    from apps.evidence.requirements import required_kinds_for_activity

    needed = required_kinds_for_activity(a)
    have = {e.kind for e in a.evidence.all() if not e.quarantined}
    if needed:
        met = sum(1 for k in needed if k in have)
        evidence_label = f"{met}/{len(needed)} required"
        evidence_complete = met == len(needed)
    else:
        evidence_label = f"{len(have)} file(s)"
        evidence_complete = bool(have)
    submitted = a.submitted_to_ia_at.date() if a.submitted_to_ia_at else None
    age_days = (today - submitted).days if submitted else None
    return {
        "a": a,
        "where": a.school.name
        if a.school_id
        else (a.cluster.name if a.cluster_id else "Field work"),
        "partner_name": partner_names.get(a.assigned_partner_id, "—"),
        "partner_officer": partner_users.get(a.assigned_partner_id, ""),
        "evidence_label": evidence_label,
        "evidence_complete": evidence_complete,
        "submitted": submitted,
        "age_days": age_days,
    }


@require_page_permission("ia_partner_evidence")
def ia_partner_evidence_queue_view(request):
    """§10.1 the queue: partner work awaiting IA verification."""
    from apps.partners.models import Partner

    qs = (
        Activity.objects.filter(
            delivery_type="partner",
            status="awaiting_ia_verification",
            deleted_at__isnull=True,
        )
        .filter(_ia_reach_q(request))
        .select_related("school", "school__district", "cluster")
        .prefetch_related("evidence")
        .order_by("submitted_to_ia_at")
    )
    total = qs.count()
    activities = list(qs[:QUEUE_PAGE_SIZE])
    partner_ids = {a.assigned_partner_id for a in activities if a.assigned_partner_id}
    partners = Partner.objects.filter(id__in=partner_ids).select_related("user")
    partner_names = {p.id: p.name for p in partners}
    partner_users = {p.id: (p.user.name if p.user_id else "") for p in partners}
    today = timezone.localdate()
    rows = [
        _partner_queue_row(a, partner_names, partner_users, today) for a in activities
    ]
    return render(
        request,
        "pages/ia/partner_evidence_queue.html",
        {"rows": rows, "total": total, "shown": len(rows)},
    )


def _own_ia_partner_activity(request, activity_id):
    # Country-bound like the staff queue (IA review, 2026-09-13): a partner
    # activity in another country is not found, for reads and decisions alike.
    return get_object_or_404(
        Activity.objects.filter(
            activity_country_q(resolve_user_scope(request.user))
        ).select_related("school", "school__district", "cluster"),
        id=activity_id,
        delivery_type="partner",
        deleted_at__isnull=True,
    )


@require_page_permission("ia_partner_evidence")
def ia_partner_review_view(request, activity_id):
    """§10.2 the review page: plan vs actual, evidence, history — and the two
    workflow decisions, Return and Complete."""
    from apps.partners.models import Partner, PartnerAssignment
    from apps.evidence.models import EvidenceRecord
    from apps.evidence.requirements import checklist

    a = _own_ia_partner_activity(request, activity_id)
    partner = (
        Partner.objects.filter(id=a.assigned_partner_id).select_related("user").first()
    )
    assignment = (
        PartnerAssignment.objects.filter(scheduled_activity_id=a.id)
        .select_related("source_ssa", "catalogue_item")
        .first()
    )
    evidence = list(
        EvidenceRecord.objects.filter(activity_id=a.id, quarantined=False).order_by(
            "-created_at"
        )
    )
    history = list(
        VerificationHistory.objects.filter(activity_id=a.id).order_by("-created_at")[
            :20
        ]
    )
    can_decide = a.status == "awaiting_ia_verification"
    from apps.activities.services import is_partner_ssa_support_activity

    return render(
        request,
        "pages/ia/partner_review.html",
        {
            "a": a,
            "partner": partner,
            "assignment": assignment,
            "evidence": evidence,
            "evidence_checklist": checklist(a),
            "history": history,
            "can_decide": can_decide,
            "is_partner_ssa_support": is_partner_ssa_support_activity(a),
            "back_url": "/ia/partner-evidence/",
        },
    )


@require_page_permission("ia_partner_evidence")
def ia_partner_return_drawer(request, activity_id):
    a = _own_ia_partner_activity(request, activity_id)
    return render(
        request,
        "partials/ia/partner_return_drawer.html",
        {"a": a, "drawer_size": "md"},
    )


@require_page_permission("ia_partner_evidence")
def ia_partner_return_action(request, activity_id):
    if request.method != "POST":
        return HttpResponseForbidden("POST required")
    a = _own_ia_partner_activity(request, activity_id)
    try:
        from apps.activities.services import ia_return

        ia_return(
            a.id,
            {
                "reason": request.POST.get("reason", ""),
                "correctionFields": request.POST.get("correction_fields", ""),
                "instruction": request.POST.get("instruction", ""),
                "deadline": request.POST.get("deadline", ""),
            },
            request.user,
        )
    except Exception as exc:
        from apps.core.htmx_errors import error_fragment

        return error_fragment(exc, status=400)
    from django.http import HttpResponse

    response = HttpResponse(
        '<script>window.location.href="/ia/partner-evidence/";</script>'
    )
    response["HX-Trigger"] = "close-drawer"
    return response


@require_page_permission("ia_partner_evidence")
def ia_partner_complete_drawer(request, activity_id):
    """§12 Confirm Salesforce Entry — read-only summary + the required ID."""
    from apps.evidence.models import EvidenceRecord

    a = _own_ia_partner_activity(request, activity_id)
    from apps.activities.services import is_partner_ssa_support_activity

    if is_partner_ssa_support_activity(a):
        from apps.frontend.views.my_plan_views import (
            partner_ssa_completion_drawer_view,
        )

        return partner_ssa_completion_drawer_view(request, activity_id)
    evidence_count = EvidenceRecord.objects.filter(
        activity_id=a.id, quarantined=False
    ).count()
    return render(
        request,
        "partials/ia/partner_complete_drawer.html",
        {
            "a": a,
            "evidence_count": evidence_count,
            "today": timezone.localdate(),
            "drawer_size": "md",
        },
    )


@require_page_permission("ia_partner_evidence")
def ia_partner_complete_action(request, activity_id):
    if request.method != "POST":
        return HttpResponseForbidden("POST required")
    a = _own_ia_partner_activity(request, activity_id)
    from apps.activities.services import is_partner_ssa_support_activity

    if is_partner_ssa_support_activity(a):
        from apps.frontend.views.my_plan_views import partner_ssa_completion_action

        return partner_ssa_completion_action(request, activity_id)
    try:
        from apps.activities.services import ia_confirm

        ia_confirm(
            a.id,
            {
                "salesforceId": request.POST.get("salesforce_id", ""),
                "verificationNote": request.POST.get("verification_note", ""),
            },
            request.user,
        )
    except Exception as exc:
        from apps.core.htmx_errors import error_fragment

        return error_fragment(exc, status=400)
    from django.http import HttpResponse

    response = HttpResponse(
        '<script>window.location.href="/ia/partner-evidence/";</script>'
    )
    response["HX-Trigger"] = "close-drawer"
    return response


# ── Verification analytics, sample checks and attribution (2026-09-03) ───────
@require_page_permission("ia_verification_analytics")
def ia_verification_analytics_view(request):
    """Verification quality as a pattern: return reasons, who submits weak
    evidence, verifier turnaround, and how certifications survive a sample."""
    from apps.activities.verification_analytics import verification_analytics

    raw = (request.GET.get("window") or "").strip()
    window = int(raw) if raw.isdigit() and int(raw) in (30, 90, 180, 365) else 90
    data = verification_analytics(request.user, window_days=window)
    rate = data["return_rate"]
    context = {
        **data,
        "window_options": (30, 90, 180, 365),
        "return_rate_label": f"{rate}%",
        "return_rate_tone": "danger"
        if rate > 25
        else "warning"
        if rate > 10
        else "success",
    }
    return render(request, "pages/ia/verification_analytics.html", context)


@require_page_permission("ia_verification_analytics")
def ia_verification_analytics_export_view(request):
    """The decisions behind the analytics, as CSV, for the same window."""
    import csv

    from django.http import HttpResponse

    from apps.activities.verification_analytics import (
        EXPORT_HEADER,
        export_rows,
        verification_analytics,
    )
    from apps.core.permissions import RolePermissionService, render_access_denied

    if not RolePermissionService.can_export(request.user, request.path):
        return render_access_denied(request, "Your role does not include data export.")
    raw = (request.GET.get("window") or "").strip()
    window = int(raw) if raw.isdigit() and int(raw) in (30, 90, 180, 365) else 90
    data = verification_analytics(request.user, window_days=window)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        f'attachment; filename="verification-decisions-{window}d.csv"'
    )
    writer = csv.writer(response)
    writer.writerow(EXPORT_HEADER)
    for row in export_rows(data):
        writer.writerow(row)
    return response


@require_page_permission("ia_samples")
def ia_samples_view(request):
    """Sample checks: a second look at a share of verified work.

    Activities and confirmed SSA records (IA review, 2026-09-13), in the
    reader's country, paged in the database. Each row says what the sample is,
    who certified it, and what the grader can do: confirm, dispute, ask for a
    field back-check (an owner-approved visit request), or — for a disputed
    activity — resolve the dispute once it is corrected.
    """
    from apps.accounts.models import User
    from apps.activities.ia_models import VerificationHistory
    from apps.activities.verification_sampling import (
        SUBJECT_SSA,
        grading_flags,
        sample_school,
        sample_share_pct,
        samples_for,
    )
    from apps.analytics.ia_collection import db_page

    samples = samples_for(request.user)
    status = request.GET.get("status", "")
    if status in ("pending", "confirmed", "disputed"):
        samples = samples.filter(status=status)
    else:
        status = ""
    subject = request.GET.get("subject", "")
    if subject in ("activity", "ssa_record"):
        samples = samples.filter(subject_type=subject)
    else:
        subject = ""
    page = db_page(samples, request.GET.get("samples_page"))
    page_samples = page["rows"]
    user_ids = {s.original_verifier for s in page_samples} | {
        s.checked_by for s in page_samples if s.checked_by
    }
    names = dict(User.objects.filter(id__in=user_ids).values_list("id", "name"))
    excluded = set(
        VerificationHistory.objects.filter(
            activity_id__in=[s.activity_id for s in page_samples if s.activity_id],
            analytics_included=False,
        ).values_list("activity_id", flat=True)
    )
    refusals = grading_flags(request.user, page_samples)
    rows = []
    for smp in page_samples:
        is_ssa = smp.subject_type == SUBJECT_SSA and smp.ssa_record_id
        school = sample_school(smp)
        if is_ssa:
            record = smp.ssa_record
            when = (
                timezone.localtime(record.date_of_ssa).date()
                if record.date_of_ssa
                else None
            )
            subject_label = "Confirmed SSA" + (
                f" dated {when:%-d %b %Y}" if when else ""
            )
            record_url = f"/schools/{record.school_id}#ssa-timeline"
        else:
            subject_label = (
                smp.activity.get_activity_type_display() if smp.activity else "Activity"
            )
            record_url = (
                f"/ia/verification/{smp.activity_id}/" if smp.activity_id else ""
            )
        refusal = refusals.get(smp.id, "")
        may_grade = not refusal
        if smp.status == "pending":
            outcome, tone = "Pending", "warning"
        elif smp.status == "confirmed":
            outcome, tone = "Confirmed", "success"
        elif is_ssa:
            outcome, tone = "Disputed · SSA returned to its collector", "danger"
        elif smp.activity_id in excluded:
            outcome, tone = (
                "Disputed · excluded from analytics until resolved",
                "danger",
            )
        else:
            outcome, tone = "Disputed · resolved", "neutral"
        rows.append(
            {
                "id": smp.id,
                "school_id": school.id if school else "",
                "school": school.name if school else "Cluster-wide",
                "school_code": getattr(school, "school_id", "") if school else "",
                "subject": subject_label,
                "record_url": record_url,
                "method": smp.get_method_display(),
                "method_key": smp.method,
                "original_verifier": names.get(
                    smp.original_verifier, smp.original_verifier
                ),
                "is_own": str(smp.original_verifier) == str(request.user.user_id),
                "sampled_at": smp.sampled_at,
                "status": outcome,
                "status_key": smp.status,
                "tone": tone,
                "outcome_note": smp.outcome_note,
                "checked_by": names.get(smp.checked_by, "") if smp.checked_by else "",
                "checked_at": smp.checked_at,
                "may_grade": may_grade and smp.status == "pending",
                "refusal": refusal,
                "may_field_check": may_grade
                and smp.status == "pending"
                and bool(school),
                "may_resolve": may_grade
                and smp.status == "disputed"
                and not is_ssa
                and smp.activity_id in excluded,
            }
        )
    visit_school = (request.GET.get("visit") or "").strip()
    context = {
        "samples": rows,
        "pager": page,
        "status": status,
        "subject": subject,
        "pending_count": samples_for(request.user).filter(status="pending").count(),
        "share_pct": sample_share_pct(),
        "can_draw": getattr(request.user, "active_role", "")
        in (
            "ImpactAssessment",
            "CountryDirector",
            "Admin",
        ),
        # A field back-check just asked for: open the schedule drawer, which
        # files an owner-approved visit request for that school.
        "visit_school": visit_school
        if visit_school and any(r["school_code"] == visit_school for r in rows)
        else "",
    }
    return render(request, "pages/ia/verification_samples.html", context)


@require_page_permission("ia_samples")
def ia_sample_outcome_action(request, sample_id):
    from apps.activities.verification_sampling import record_outcome
    from apps.core.exceptions import Forbidden as _Forbidden

    if request.method != "POST":
        return local_redirect("/ia/samples/")
    try:
        sample = record_outcome(
            sample_id,
            request.POST.get("status", ""),
            request.POST.get("note", ""),
            request.user,
        )
        audit_log(
            action="verification_sample_graded",
            subject_kind="VerificationSample",
            subject_id=str(sample.id),
            actor_id=str(request.user.id),
            actor_role=request.user.active_role,
            success=True,
            payload={
                "status": sample.status,
                "note": sample.outcome_note,
                "subject": sample.subject_type,
            },
        )
        if sample.status == "disputed":
            messages.success(
                request,
                "Sample recorded as disputed. "
                + (
                    "The SSA was returned to its collector."
                    if sample.subject_type == "ssa_record"
                    else "The activity is excluded from analytics until the dispute is resolved."
                ),
            )
        else:
            messages.success(
                request, f"Sample recorded as {sample.get_status_display().lower()}."
            )
    except (BadRequest, _Forbidden) as exc:
        messages.error(request, str(exc))
    return local_redirect("/ia/samples/")


@require_page_permission("ia_samples")
def ia_sample_resolve_action(request, sample_id):
    """Put a corrected, disputed activity back into analytics."""
    from apps.activities.verification_sampling import resolve_dispute
    from apps.core.exceptions import Forbidden as _Forbidden

    if request.method != "POST":
        return local_redirect("/ia/samples/")
    try:
        resolve_dispute(sample_id, request.POST.get("note", ""), request.user)
        messages.success(request, "Dispute resolved; the activity counts again.")
    except (BadRequest, _Forbidden) as exc:
        messages.error(request, str(exc))
    return local_redirect("/ia/samples/?status=disputed")


@require_page_permission("ia_samples")
def ia_sample_field_check_action(request, sample_id):
    """Ask for a field back-check: mark the sample, then open the schedule
    drawer for its school, which files an owner-approved visit request."""
    from urllib.parse import urlencode

    from apps.activities.verification_sampling import request_field_check, sample_school
    from apps.core.exceptions import Forbidden as _Forbidden

    if request.method != "POST":
        return local_redirect("/ia/samples/")
    try:
        sample = request_field_check(sample_id, request.user)
    except (BadRequest, _Forbidden) as exc:
        messages.error(request, str(exc))
        return local_redirect("/ia/samples/")
    school = sample_school(sample)
    messages.info(
        request,
        f"Request the back-check visit to {school.name}: the school's owner approves it.",
    )
    return local_redirect(
        "/ia/samples/?" + urlencode({"status": "pending", "visit": school.school_id})
    )


@require_page_permission("ia_samples")
def ia_sample_draw_action(request):
    """Draw this week's sample now rather than waiting for Monday — for the
    reader's own country (IA review, 2026-09-13)."""
    from apps.activities.verification_sampling import draw_samples
    from apps.core.scoping import country_bound

    if request.method != "POST":
        return local_redirect("/ia/samples/")
    scope = resolve_user_scope(request.user)
    created = draw_samples(
        days=7,
        actor=request.user.user_id,
        country=scope.country if country_bound(scope) else None,
    )
    messages.success(
        request,
        f"{created} record{'' if created == 1 else 's'} drawn for a second look."
        if created
        else "Nothing new to draw: last week's verifications are already sampled.",
    )
    return local_redirect("/ia/samples/")


@require_page_permission("ia_attribution")
def ia_attribution_view(request):
    """The attribution page merged into Programme Learning (IA review,
    2026-09-13): its separate maths disagreed with /impact and it made no
    association caveat. Bookmarks and the Country Director's access land on
    the Training tab, which carries intervention contribution with the
    caveat; the financial year travels with them."""
    from urllib.parse import urlencode

    params = {"view": "training"}
    fy = (request.GET.get("fy") or "").strip()
    if fy:
        params["fy"] = fy
    return local_redirect(f"/ia/learning/?{urlencode(params)}")
