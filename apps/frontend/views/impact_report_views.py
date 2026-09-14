"""Impact Reports: the register, one report, its releases and the school brief
(IA review, owner, 2026-09-13).

/ia/impact-reports/ lists the reports the reader may read
(apps.impact.reports.visible_reports) with registered tiles; a report opens on
its own page with the narrative, the recommendations, the evidence frozen at
submission, the releases and the audit history. Every write is a one-column
drawer or a button on that page that posts to the service, and a refusal the
service raises is the message the reader sees.

Who does what is decided by the service, never by what the page shows:
Impact Assessment writes and corrects; a second IA officer reviews (the
Country Director only where there is none); the reviewer releases to
leadership; the reviewer or the Country Director releases school briefs and
requests the donor version; an RVP covering the country approves it; the
Country Director answers the recommendations. The RVP reads aggregates only.

/impact-briefs/<release>/ is the school's brief, opened by its account owner
from the TeamAction that delivered it (page key "schools", which field staff
hold), by Impact Assessment and the Country Director of the report's country,
and by Admin; the account owner records there that it was shared.
"""

from __future__ import annotations

from urllib.parse import urlencode

from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from apps.core.pagination import paginate_rows
from apps.core.permissions import RolePermissionService, require_page_permission
from apps.frontend.views.hr_programme_views import SERVICE_ERRORS, _drawer, _field
from apps.impact import redaction
from apps.impact import reports as rp
from apps.impact.models import ReviewBasis

PAGE_URL = "/ia/impact-reports/"
REVIEW_BASIS_LABELS = dict(ReviewBasis.choices)
PAGE_SIZE = 20


def _cell(heading: str, text, *, primary=False, tone="") -> dict:
    return {
        "heading": heading,
        "text": "—" if text in (None, "") else str(text),
        "primary": primary,
        "tone": tone,
    }


def _page(request, param: str) -> int:
    try:
        return max(1, int(request.GET.get(param) or 1))
    except (TypeError, ValueError):
        return 1


def _report_url(report_id: str) -> str:
    return f"{PAGE_URL}{report_id}/"


def _back(request, fallback: str):
    from apps.frontend.views.coaching_views import safe_return_url

    return redirect(safe_return_url(request, fallback, drop=("open",)))


def _refused(request, exc, fallback: str):
    messages.error(request, str(getattr(exc, "detail", exc)))
    return _back(request, fallback)


def _visible(request, report_id):
    report = (
        rp.visible_reports(request.user)
        .select_related("project", "supersedes")
        .filter(id=report_id)
        .first()
    )
    if report is None:
        raise Http404("That impact report is not in your reach.")
    return report


def _day(value) -> str:
    if not value:
        return ""
    if hasattr(value, "tzinfo"):
        value = timezone.localtime(value)
        return f"{value:%-d %b %Y %H:%M}"
    return f"{value:%-d %b %Y}"


def _signed(value) -> str:
    if value in (None, ""):
        return ""
    if value == redaction.SUPPRESSED:
        return "Suppressed (fewer than 5 schools)"
    try:
        return f"{float(value):+.2f}"
    except (TypeError, ValueError):
        return str(value)


def _share(value) -> str:
    if value is None:
        return "Not measured"
    if value == redaction.SUPPRESSED:
        return "Suppressed (fewer than 5 schools)"
    return f"{value}%"


def _count(value) -> str:
    if value == redaction.SUPPRESSED:
        return "Suppressed (fewer than 5)"
    return "0" if value in (None, "") else str(value)


# ── The register ─────────────────────────────────────────────────────────────


@require_page_permission("impact_reports")
@require_http_methods(["GET"])
def register_page(request):
    from apps.core.fy import get_operational_fy

    status = request.GET.get("status") or ""
    if status not in rp.STATUS_LABELS:
        status = ""
    fy = request.GET.get("fy") or ""
    reports = rp.visible_reports(request.user)
    fy_values = sorted(
        {v for v in reports.values_list("fy", flat=True).distinct() if v}, reverse=True
    )
    if fy not in fy_values:
        fy = ""
    from apps.analytics.ia_collection import db_page

    page = db_page(
        rp.register(request.user, status=status, fy=fy),
        request.GET.get("register_page"),
        PAGE_SIZE,
    )
    entries = rp.decorate(request.user, page.pop("rows"))
    rows = []
    for entry in entries:
        r = entry["report"]
        status_text = entry["status_label"]
        if r.status == rp.RETURNED and r.review_note:
            status_text = f"{status_text}: {r.review_note[:120]}"
        label = "Open"
        if entry["can_review"]:
            label = "Review"
        elif entry["can_edit"]:
            label = "Continue draft"
        elif entry["can_release"]:
            label = "Release"
        rows.append(
            {
                "cells": [
                    _cell("Report", r.title, primary=True),
                    _cell("Period", entry["period"]),
                    _cell("Programmes", entry["programmes"]),
                    _cell("Version", r.version),
                    _cell("Author", entry["author"]),
                    _cell("Status", status_text, tone=entry["status_tone"]),
                    _cell("Updated", _day(r.updated_at)),
                ],
                "actions": [{"label": label, "url": _report_url(r.id)}],
            }
        )
    operational = get_operational_fy()
    filters = [
        {
            "name": "status",
            "label": "Status",
            "value": status,
            "blank": "Every status",
            "options": list(rp.STATUS_LABELS.items()),
        },
    ]
    if len(fy_values) > 1:
        filters.append(
            {
                "name": "fy",
                "label": "Financial year",
                "value": fy,
                "blank": "Every year",
                "options": [(v, f"FY{v}") for v in fy_values],
            }
        )
    may_author = rp.may_author(request.user)
    return render(
        request,
        "pages/ia/impact_reports.html",
        {
            "metrics": rp.register_tiles(request.user, operational),
            "filters": filters,
            "may_author": may_author,
            "summary_only": rp.is_summary_reader(request.user),
            "table": {
                "title": "Impact reports",
                "subtitle": "Newest activity first",
                "rows": rows,
                "has_actions": bool(rows),
                "pager": page,
                "param": "register_page",
                "empty_title": "No impact reports",
                "empty_body": (
                    "Start a report: set its period, write the methodology, findings and "
                    "limitations, and add recommendations. Submitting freezes the evidence."
                    if may_author
                    else "Reports written by Impact Assessment in your reach appear here."
                ),
            },
        },
    )


# ── Drafting ─────────────────────────────────────────────────────────────────


def _report_fields(request, report=None, *, project="") -> list[dict]:
    from apps.core.fy import get_operational_fy

    def value(name, default=""):
        if report is None:
            return default
        raw = getattr(report, name)
        if name in ("period_start", "period_end"):
            return raw.isoformat() if raw else ""
        if name == "project":
            return report.project_id or ""
        return raw if raw is not None else ""

    projects = rp.project_options(request.user)
    fields = [
        _field("title", "Title", required=True, maxlength=200, value=value("title")),
        _field(
            "fy",
            "Financial year",
            type="select",
            required=True,
            options=[(o, f"FY{o}") for o in rp.fy_choices()],
            value=value("fy", get_operational_fy()),
            help="School change compares this year with the year before.",
        ),
        _field(
            "period_start",
            "Period start",
            type="date",
            value=value("period_start"),
            help="Leave both dates blank to report the whole financial year.",
        ),
        _field("period_end", "Period end", type="date", value=value("period_end")),
        _field(
            "programme_areas",
            "Programme areas",
            type="multiselect",
            options=list(rp.PROGRAMME_LABELS.items()),
            value=list(value("programme_areas", []) or []),
            rows=5,
            help="Approved findings of these programmes are cited in the evidence.",
        ),
    ]
    if projects:
        fields.append(
            _field(
                "project",
                "Special project cohort",
                type="select",
                blank="Every project enrolment in scope",
                options=projects,
                value=value("project", project),
            )
        )
    fields += [
        _field(
            "methodology",
            "Methodology",
            type="textarea",
            rows=4,
            maxlength=10000,
            value=value("methodology"),
            help="Which evidence, which comparison, which period — required to submit.",
        ),
        _field(
            "findings",
            "Findings",
            type="textarea",
            rows=6,
            maxlength=10000,
            value=value("findings"),
            help="What the evidence shows, including what cuts against it — required to submit.",
        ),
        _field(
            "limitations",
            "Limitations",
            type="textarea",
            rows=4,
            maxlength=10000,
            value=value("limitations"),
            help="What this evidence cannot show — required to submit.",
        ),
    ]
    return fields


@require_page_permission("impact_reports")
@require_http_methods(["GET"])
def report_new_drawer(request):
    if not rp.may_author(request.user):
        return _drawer(
            request,
            title="Start an impact report",
            subtitle="Impact Reports",
            empty="Only Impact Assessment writes impact reports.",
        )
    return _drawer(
        request,
        title="Start an impact report",
        subtitle="Draft · you add recommendations on the report page",
        action=f"{PAGE_URL}create",
        fields=_report_fields(request, project=request.GET.get("project") or ""),
        submit="Save draft",
        note="Nothing is frozen until you submit; a second officer reviews it before anyone reads it.",
    )


@require_page_permission("impact_reports")
@require_POST
def report_create(request):
    try:
        report = rp.create_report(request.user, request.POST)
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, PAGE_URL)
    messages.success(
        request, "Draft saved. Add recommendations, then submit it for review."
    )
    return redirect(_report_url(report.id))


@require_page_permission("impact_reports")
@require_http_methods(["GET"])
def report_edit_drawer(request, report_id):
    report = _visible(request, report_id)
    rights = rp.detail_rights(request.user, report)
    if not rights["can_edit"]:
        return _drawer(
            request,
            title="Edit impact report",
            subtitle=report.title,
            empty="Only the author edits a draft; a submitted report is corrected as a new version.",
        )
    return _drawer(
        request,
        title="Edit impact report",
        subtitle=f"Draft · version {report.version}",
        action=f"{_report_url(report.id)}update",
        fields=_report_fields(request, report),
        submit="Save draft",
    )


@require_page_permission("impact_reports")
@require_POST
def report_update(request, report_id):
    try:
        rp.update_report(request.user, report_id, request.POST)
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, _report_url(report_id))
    messages.success(request, "Draft saved.")
    return _back(request, _report_url(report_id))


@require_page_permission("impact_reports")
@require_POST
def report_submit(request, report_id):
    try:
        rp.submit_report(request.user, report_id)
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, _report_url(report_id))
    messages.success(
        request,
        "Submitted. The evidence is frozen and a second reviewer has been told.",
    )
    return redirect(_report_url(report_id))


@require_page_permission("impact_reports")
@require_POST
def report_withdraw(request, report_id):
    try:
        rp.withdraw_report(request.user, report_id, request.POST.get("note", ""))
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, _report_url(report_id))
    messages.success(request, "Report withdrawn.")
    return redirect(_report_url(report_id))


@require_page_permission("impact_reports")
@require_POST
def report_correct(request, report_id):
    try:
        revision = rp.start_correction(request.user, report_id)
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, _report_url(report_id))
    messages.success(
        request,
        f"Version {revision.version} started as a draft; the earlier version stands until it replaces it.",
    )
    return redirect(_report_url(revision.id))


# ── Recommendations ──────────────────────────────────────────────────────────


@require_page_permission("impact_reports")
@require_http_methods(["GET"])
def recommendation_new_drawer(request, report_id):
    from apps.impact.findings import ACTION_OWNER_ROLES

    report = _visible(request, report_id)
    if not rp.detail_rights(request.user, report)["can_edit"]:
        return _drawer(
            request,
            title="Add a recommendation",
            subtitle=report.title,
            empty="Only the author adds recommendations, while the report is a draft.",
        )
    return _drawer(
        request,
        title="Add a recommendation",
        subtitle=report.title,
        action=f"{_report_url(report.id)}recommendations/create",
        fields=[
            _field(
                "text",
                "Recommendation",
                type="textarea",
                required=True,
                rows=4,
                maxlength=4000,
                help="What should change, in words the Country Director can decide on.",
            ),
            _field(
                "owner_role",
                "Who should act on it",
                type="select",
                required=True,
                options=list(ACTION_OWNER_ROLES),
            ),
            _field("due_date", "Due by", type="date", required=True),
        ],
        submit="Add recommendation",
    )


@require_page_permission("impact_reports")
@require_POST
def recommendation_create(request, report_id):
    try:
        rp.add_recommendation(request.user, report_id, request.POST)
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, _report_url(report_id))
    messages.success(request, "Recommendation added.")
    return _back(request, _report_url(report_id))


@require_page_permission("impact_reports")
@require_POST
def recommendation_remove(request, report_id, recommendation_id):
    try:
        rp.remove_recommendation(request.user, report_id, recommendation_id)
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, _report_url(report_id))
    messages.success(request, "Recommendation removed.")
    return redirect(_report_url(report_id) + "#recommendations")


@require_page_permission("impact_reports")
@require_http_methods(["GET"])
def recommendation_drawer(request, report_id, recommendation_id):
    from apps.impact.findings import ACTION_OWNER_LABELS

    report = _visible(request, report_id)
    recommendation = report.recommendations.filter(id=recommendation_id).first()
    if recommendation is None:
        raise Http404("That recommendation is not on this report.")
    facts = [
        {"label": "Recommendation", "value": recommendation.text},
        {
            "label": "For",
            "value": ACTION_OWNER_LABELS.get(
                recommendation.owner_role, recommendation.owner_role
            ),
        },
        {"label": "Due by", "value": _day(recommendation.due_date)},
        {
            "label": "Status",
            "value": rp.RECOMMENDATION_LABELS.get(
                recommendation.status, recommendation.status
            ),
        },
    ]
    if recommendation.response:
        facts.append({"label": "Response", "value": recommendation.response})
    if not rp.detail_rights(request.user, report)["can_respond"]:
        return _drawer(
            request,
            title="Recommendation",
            subtitle=report.title,
            facts=facts,
            empty="The country's Country Director responds once the report is released.",
        )
    return _drawer(
        request,
        title="Respond to the recommendation",
        subtitle=report.title,
        action=f"{_report_url(report.id)}recommendations/{recommendation.id}/respond",
        facts=facts,
        fields=[
            _field(
                "status",
                "Response",
                type="select",
                required=True,
                options=list(rp.RESPONSES),
                value=recommendation.status
                if recommendation.status != "proposed"
                else "accepted",
            ),
            _field(
                "response",
                "What you decided and why",
                type="textarea",
                rows=4,
                maxlength=4000,
                value=recommendation.response,
                help="Required when you reject or defer it; Impact Assessment reads it.",
            ),
        ],
        submit="Save response",
    )


@require_page_permission("impact_reports")
@require_POST
def recommendation_respond(request, report_id, recommendation_id):
    try:
        rp.respond_to_recommendation(
            request.user,
            recommendation_id,
            status=request.POST.get("status") or "",
            response=request.POST.get("response", ""),
        )
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, _report_url(report_id))
    messages.success(request, "Response recorded; Impact Assessment has been told.")
    return _back(request, _report_url(report_id) + "#recommendations")


# ── Review ───────────────────────────────────────────────────────────────────


@require_page_permission("impact_reports")
@require_http_methods(["GET"])
def review_drawer(request, report_id):
    report = _visible(request, report_id)
    if not rp.detail_rights(request.user, report)["can_review"]:
        note = "Only a second Impact Assessment officer in this country reviews it; the Country Director only where there is none."
        if report.author_id == str(request.user.id):
            note = "You wrote this, so a second reviewer has to review it."
        return _drawer(
            request, title="Review impact report", subtitle=report.title, empty=note
        )
    snapshot = report.evidence_snapshot or {}
    cohort = snapshot.get("cohort") or {}
    portfolio = snapshot.get("portfolio") or {}
    facts = [
        {"label": "Period", "value": rp.period_label(report)},
        {
            "label": "Evidence frozen",
            "value": f"{snapshot.get('generated_at', '')[:16].replace('T', ' ')} · sha256 {report.snapshot_hash[:16]}",
        },
        {
            "label": "Project cohort",
            "value": f"{cohort.get('measured', 0)} of {cohort.get('total', 0)} enrolments measured in {cohort.get('unique_schools', 0)} schools",
        },
        {
            "label": "School change",
            "value": (
                f"{portfolio.get('measured', 0)} of {portfolio.get('schools_in_scope', 0)} schools with paired confirmed SSAs · {(portfolio.get('grade') or {}).get('label', '')}"
                if portfolio
                else snapshot.get("portfolio_note", "")
            ),
        },
    ]
    return _drawer(
        request,
        title="Review impact report",
        subtitle=f"{report.title} · version {report.version}",
        action=f"{_report_url(report.id)}review/save",
        facts=facts,
        fields=[
            _field(
                "decision",
                "Decision",
                type="select",
                required=True,
                options=(
                    ("approve", "Approve: the evidence supports the report as written"),
                    ("return", "Return to the author to correct"),
                ),
                value="approve",
            ),
            _field(
                "note",
                "Review note",
                type="textarea",
                rows=4,
                maxlength=4000,
                help="Required when you return it; the author reads it.",
            ),
        ],
        submit="Save decision",
        note="Read the findings against the frozen evidence and the limitations on the report page before deciding.",
    )


@require_page_permission("impact_reports")
@require_POST
def review_save(request, report_id):
    decision = request.POST.get("decision") or ""
    try:
        rp.review_report(
            request.user,
            report_id,
            decision=decision,
            note=request.POST.get("note", ""),
        )
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, _report_url(report_id))
    messages.success(
        request,
        "Report reviewed. Release it to country leadership when ready."
        if decision == "approve"
        else "Report returned to its author.",
    )
    return _back(request, _report_url(report_id))


# ── Releases ─────────────────────────────────────────────────────────────────


@require_page_permission("impact_reports")
@require_POST
def release_leadership(request, report_id):
    try:
        rp.release_to_leadership(request.user, report_id)
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, _report_url(report_id))
    messages.success(
        request, "Released to country leadership; the Country Director has been told."
    )
    return redirect(_report_url(report_id) + "#releases")


def _school_options(report) -> list[tuple[str, str]]:
    seen: dict[str, str] = {}
    for row in (report.evidence_snapshot or {}).get("rows") or []:
        if row.get("school_id") and row["school_id"] not in seen:
            seen[row["school_id"]] = row.get("school") or row["school_id"]
    return sorted(seen.items(), key=lambda item: item[1].lower())


@require_page_permission("impact_reports")
@require_http_methods(["GET"])
def schools_drawer(request, report_id):
    report = _visible(request, report_id)
    if not rp.detail_rights(request.user, report)["can_release_schools"]:
        return _drawer(
            request,
            title="Release school briefs",
            subtitle=report.title,
            empty="The report's reviewer or the Country Director releases school briefs, after the leadership release.",
        )
    released = set(
        report.releases.filter(audience="school").values_list("school_id", flat=True)
    )
    options = [
        (sid, name) for sid, name in _school_options(report) if sid not in released
    ]
    if not options:
        return _drawer(
            request,
            title="Release school briefs",
            subtitle=report.title,
            empty="Every school in the report's evidence already has its brief.",
        )
    return _drawer(
        request,
        title="Release school briefs",
        subtitle=report.title,
        action=f"{_report_url(report.id)}release/schools/save",
        fields=[
            _field(
                "schools",
                "Schools",
                type="multiselect",
                required=True,
                options=options,
                value=[sid for sid, _name in options],
                rows=min(10, max(4, len(options))),
                help="Each brief carries only that school's own results; no staff names or ids.",
            )
        ],
        submit="Release briefs",
        note="Each school's account owner receives an action to share the brief on a visit and record what the school said.",
    )


@require_page_permission("impact_reports")
@require_POST
def schools_release(request, report_id):
    try:
        result = rp.release_school_briefs(
            request.user, report_id, request.POST.getlist("schools")
        )
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, _report_url(report_id))
    released = len(result["released"])
    messages.success(
        request,
        f"{released} school brief{'s' if released != 1 else ''} released to account owners.",
    )
    for name, reason in result["skipped"][:10]:
        messages.warning(request, f"{name}: not released — {reason}.")
    return _back(request, _report_url(report_id) + "#releases")


@require_page_permission("impact_reports")
@require_http_methods(["GET"])
def donor_drawer(request, report_id):
    report = _visible(request, report_id)
    if not rp.detail_rights(request.user, report)["can_request_donor"]:
        return _drawer(
            request,
            title="Request the donor version",
            subtitle=report.title,
            empty="The report's reviewer or the Country Director requests the donor version, after the leadership release.",
        )
    preview = redaction.redact(
        rp.snapshot_with_people(report),
        redaction.DONOR,
        narrative=rp.narrative_of(report),
        recommendations=rp.recommendation_payload(report),
    )
    return _drawer(
        request,
        title="Request the donor version",
        subtitle=report.title,
        action=f"{_report_url(report.id)}release/donor/request",
        facts=_donor_facts(preview),
        fields=[
            _field(
                "note",
                "Note to the approving RVP",
                type="textarea",
                rows=3,
                maxlength=2000,
                help="Which donor or reporting round it is for.",
            )
        ],
        submit="Request RVP approval",
        note="Donors receive aggregates only; any figure resting on fewer than five schools is suppressed.",
    )


def _donor_facts(payload: dict) -> list[dict]:
    cohort = payload.get("cohort") or {}
    portfolio = payload.get("portfolio") or {}
    narrative = payload.get("narrative") or {}
    return [
        {
            "label": "Project cohort",
            "value": (
                f"{_count(cohort.get('measured'))} measured of {_count(cohort.get('enrolments'))} enrolments · "
                f"improved {_share(cohort.get('improved_pct'))} · declined {_share(cohort.get('declined_pct'))}"
            ),
        },
        {
            "label": "School change",
            "value": (
                f"{_count(portfolio.get('measured'))} of {_count(portfolio.get('schools_in_scope'))} schools measured · "
                f"improved {_share(portfolio.get('improved_pct'))} · {portfolio.get('evidence', '')}"
            )
            if portfolio
            else "Not measured",
        },
        {
            "label": "Findings (as donors read them)",
            "value": narrative.get("findings", ""),
        },
        {"label": "Limitations", "value": narrative.get("limitations", "")},
        {
            "label": "Suppressed cells",
            "value": str(payload.get("suppressed_cells", 0)),
        },
    ]


@require_page_permission("impact_reports")
@require_POST
def donor_request(request, report_id):
    try:
        rp.request_donor_release(request.user, report_id, request.POST.get("note", ""))
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, _report_url(report_id))
    messages.success(request, "Donor version requested; an RVP approves it.")
    return _back(request, _report_url(report_id) + "#releases")


def _visible_release(request, report, release_id):
    release = report.releases.select_related("school").filter(id=release_id).first()
    if release is None:
        raise Http404("That release is not on this report.")
    if rp.is_summary_reader(request.user) and release.audience != "donor":
        raise Http404("That release is not in your reach.")
    return release


@require_page_permission("impact_reports")
@require_http_methods(["GET"])
def release_drawer(request, report_id, release_id):
    report = _visible(request, report_id)
    release = _visible_release(request, report, release_id)
    payload = release.rendered_payload or {}
    subtitle = f"{rp.AUDIENCE_LABELS.get(release.audience)} · {rp.RELEASE_STATUS_LABELS.get(release.status)}"
    if release.audience == "donor":
        facts = _donor_facts(payload)
        if release.revoked_reason:
            facts.append({"label": "Declined because", "value": release.revoked_reason})
        rights = rp.detail_rights(request.user, report)
        me = str(request.user.id)
        may_decide = (
            rights["may_decide_donor"]
            and release.status == "pending_approval"
            and me
            not in (report.author_id, report.reviewed_by_id, release.requested_by_id)
        )
        if may_decide:
            return _drawer(
                request,
                title="Approve the donor version",
                subtitle=subtitle,
                action=f"{_report_url(report.id)}releases/{release.id}/decide",
                facts=facts,
                fields=[
                    _field(
                        "decision",
                        "Decision",
                        type="select",
                        required=True,
                        options=(
                            ("approve", "Approve and release to donors"),
                            ("decline", "Decline (say why)"),
                        ),
                        value="approve",
                    ),
                    _field(
                        "note",
                        "Note",
                        type="textarea",
                        rows=3,
                        maxlength=2000,
                        help="Required when you decline; the requester reads it.",
                    ),
                ],
                submit="Save decision",
                note="Check that nothing in the words names a school or a person before approving.",
            )
        return _drawer(
            request,
            title="Donor version",
            subtitle=subtitle,
            facts=facts,
            empty="Read only.",
        )
    if release.audience == "school":
        facts = [
            {"label": "School", "value": (payload.get("school") or {}).get("name", "")},
            {
                "label": "Results",
                "value": "\n".join(
                    f"{r.get('area')}: {r.get('baseline') if r.get('baseline') is not None else 'Missing'} → "
                    f"{r.get('follow_up') if r.get('follow_up') is not None else 'Missing'} ({r.get('status')})"
                    for r in payload.get("results") or []
                ),
            },
        ]
        return _drawer(
            request,
            title="School brief",
            subtitle=subtitle,
            facts=facts,
            empty="The account owner shares it from the brief page.",
        )
    snapshot = payload.get("snapshot") or {}
    cohort = snapshot.get("cohort") or {}
    return _drawer(
        request,
        title="Leadership release",
        subtitle=subtitle,
        facts=[
            {"label": "Released", "value": _day(release.released_at)},
            {
                "label": "Project cohort",
                "value": f"{cohort.get('measured', 0)} of {cohort.get('total', 0)} enrolments measured",
            },
        ],
        empty="The whole report and its evidence, as released to the country's leadership.",
    )


@require_page_permission("impact_reports")
@require_POST
def release_decide(request, report_id, release_id):
    decision = request.POST.get("decision") or ""
    try:
        rp.decide_donor_release(
            request.user,
            release_id,
            decision=decision,
            note=request.POST.get("note", ""),
        )
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, _report_url(report_id))
    messages.success(
        request,
        "Donor version approved and released."
        if decision == "approve"
        else "Donor version declined.",
    )
    return _back(request, _report_url(report_id) + "#releases")


# ── Downloads ────────────────────────────────────────────────────────────────


def _csv_response(filename: str) -> HttpResponse:
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "no-store"
    return response


@require_page_permission("impact_reports")
@require_http_methods(["GET"])
def annex_download(request, report_id):
    """The frozen evidence annex: Impact Assessment, the Country Director and
    Admin, never the summary-only RVP."""
    report = _visible(request, report_id)
    rights = rp.detail_rights(request.user, report)
    if not rights["can_download_annex"] or not RolePermissionService.can_export(
        request.user, "impact_reports"
    ):
        raise Http404("The evidence annex is not available to you.")
    response = _csv_response(f"impact-report-{report.id}-v{report.version}-annex.csv")
    rp.write_csv(
        response,
        rp.annex_rows(
            report,
            generated_by=request.user.name,
            generated_role=request.user.active_role,
        ),
    )
    rp.audit_download(
        "ia.report.annex_downloaded",
        report,
        request.user,
        {"rows": len((report.evidence_snapshot or {}).get("rows") or [])},
    )
    return response


@require_page_permission("impact_reports")
@require_http_methods(["GET"])
def release_download(request, report_id, release_id):
    report = _visible(request, report_id)
    release = _visible_release(request, report, release_id)
    if release.status != "released" or not RolePermissionService.can_export(
        request.user, "impact_reports"
    ):
        raise Http404("Only a released version is downloaded.")
    if release.audience == "leadership":
        return redirect(f"{_report_url(report.id)}annex.csv")
    response = _csv_response(
        f"impact-report-{report.id}-v{report.version}-{release.audience}.csv"
    )
    rp.write_csv(response, rp.release_rows(release))
    rp.audit_download(
        "ia.report.release_downloaded",
        report,
        request.user,
        {"release_id": release.id, "audience": release.audience},
    )
    return response


# ── One report ───────────────────────────────────────────────────────────────


def _recommendation_rows(report, rights) -> list[dict]:
    from apps.impact.findings import ACTION_OWNER_LABELS

    today = timezone.localdate()
    rows = []
    for r in report.recommendations.all().order_by("due_date", "created_at"):
        overdue = (
            report.status == rp.RELEASED
            and r.status in rp.OPEN_RECOMMENDATIONS
            and r.due_date
            and r.due_date < today
        )
        actions = []
        if rights["can_edit"]:
            actions.append(
                {
                    "label": "Remove",
                    "post": f"{_report_url(report.id)}recommendations/{r.id}/remove",
                }
            )
        elif rights["can_respond"]:
            actions.append(
                {
                    "label": "Respond" if r.status == "proposed" else "Update",
                    "drawer": f"{_report_url(report.id)}recommendations/{r.id}/",
                }
            )
        rows.append(
            {
                "cells": [
                    _cell("Recommendation", r.text, primary=True),
                    _cell("For", ACTION_OWNER_LABELS.get(r.owner_role, r.owner_role)),
                    _cell("Due by", _day(r.due_date), tone="danger" if overdue else ""),
                    _cell(
                        "Status",
                        rp.RECOMMENDATION_LABELS.get(r.status, r.status)
                        + (" · overdue" if overdue else ""),
                        tone="danger"
                        if overdue
                        else rp.RECOMMENDATION_TONES.get(r.status, "neutral"),
                    ),
                    _cell("Country Director's response", r.response),
                ],
                "actions": actions,
            }
        )
    return rows


def _evidence_tables(request, report, rights) -> dict:
    """The frozen evidence, as plain-text tables. The RVP reads the donor
    aggregates; everyone else the snapshot itself."""
    snapshot = report.evidence_snapshot or {}
    if not snapshot:
        return {}
    if rights["summary_only"]:
        donor = redaction.redact(
            rp.snapshot_with_people(report),
            redaction.DONOR,
            narrative=rp.narrative_of(report),
        )
        cohort = donor["cohort"]
        portfolio = donor["portfolio"]
        summary = [
            ("Project enrolments", _count(cohort["enrolments"])),
            ("Measured enrolments", _count(cohort["measured"])),
            ("Improved (share of measured)", _share(cohort["improved_pct"])),
            ("Declined (share of measured)", _share(cohort["declined_pct"])),
            ("Schools in scope", _count(portfolio.get("schools_in_scope"))),
            ("Schools with paired confirmed SSAs", _count(portfolio.get("measured"))),
            ("Suppressed cells", str(donor["suppressed_cells"])),
        ]
        change_rows = [
            {
                "cells": [
                    _cell("Outcome area / domain", row["name"], primary=True),
                    _cell("Schools measured", _count(row["measured"])),
                    _cell("Improved", _share(row["improved_pct"])),
                    _cell("Declined", _share(row["declined_pct"])),
                    _cell("Median change", _signed(row["median_change"])),
                    _cell("Evidence", row["evidence"]),
                ],
                "actions": [],
            }
            for row in portfolio.get("rows") or []
        ]
        return {
            "summary": summary,
            "change": _table(
                request,
                "change_page",
                "School change (aggregates)",
                change_rows,
                "Not measured",
                "No school has two comparable confirmed SSAs.",
            ),
            "schools": None,
        }
    cohort = snapshot.get("cohort") or {}
    portfolio = snapshot.get("portfolio") or {}
    evidence = snapshot.get("evidence") or {}
    lending = snapshot.get("lending") or {}
    summary = [
        (
            "Project enrolments in the period",
            f"{cohort.get('total', 0)} in {cohort.get('unique_schools', 0)} schools",
        ),
        (
            "Measured enrolments",
            f"{cohort.get('measured', 0)} ({cohort.get('measured_schools', 0)} schools)",
        ),
        (
            "Improved / declined (share of measured)",
            f"{_share(cohort.get('improved_pct'))} / {_share(cohort.get('declined_pct'))}",
        ),
        (
            "Missing a baseline / overdue follow-up",
            f"{cohort.get('baseline_missing', 0)} / {cohort.get('overdue', 0)}",
        ),
        (
            "Enrolments with no date to place in the period",
            str(cohort.get("outside_period_undated", 0)),
        ),
        (
            "School change across the portfolio",
            (
                f"{portfolio.get('measured', 0)} of {portfolio.get('schools_in_scope', 0)} schools, FY{portfolio.get('prev_fy')} → FY{portfolio.get('fy')} · {(portfolio.get('grade') or {}).get('label', '')} · {portfolio.get('rule_label', '')}"
                if portfolio
                else snapshot.get("portfolio_note", "")
            ),
        ),
        (
            "Student learning results",
            f"{(evidence.get('learning') or {}).get('comparisons', 0)} class comparisons in {(evidence.get('learning') or {}).get('schools', 0)} schools · {((evidence.get('learning') or {}).get('grade') or {}).get('label', '')}",
        ),
        (
            "Discipleship practice",
            f"{(evidence.get('discipleship') or {}).get('schools', 0)} schools with confirmed records · {(evidence.get('discipleship') or {}).get('stories_approved', 0)} approved change stories",
        ),
        (
            "EdTech rollout",
            f"{(evidence.get('edtech') or {}).get('deployments', 0)} confirmed deployments · {_share((evidence.get('edtech') or {}).get('functional_pct'))} of checked units working",
        ),
        (
            "Verified loan impact conclusions",
            str(len(lending.get("verified_ids") or [])),
        ),
        ("Approved findings cited", str(len(snapshot.get("findings") or []))),
        (
            "Mapping versions",
            ", ".join(
                f"{m.get('intervention')} v{m.get('mapping_version')} ({m.get('enrolments')})"
                for m in snapshot.get("mapping_versions") or []
            )
            or "No enrolments",
        ),
        (
            "Evidence frozen",
            f"{str(snapshot.get('generated_at', ''))[:16].replace('T', ' ')} · sha256 {report.snapshot_hash}",
        ),
    ]
    change_rows = [
        {
            "cells": [
                _cell("Outcome area / domain", row.get("name"), primary=True),
                _cell("Schools measured", row.get("n") or "Not measured"),
                _cell(
                    "Improved", _share(row.get("improved_pct")) if row.get("n") else "—"
                ),
                _cell(
                    "Declined", _share(row.get("declined_pct")) if row.get("n") else "—"
                ),
                _cell(
                    "Median change",
                    "n too small"
                    if row.get("withheld")
                    else _signed(row.get("median_change")) or "Not measured",
                ),
                _cell(
                    "Evidence",
                    (row.get("grade") or {}).get("label", "Insufficient evidence"),
                ),
            ],
            "actions": [],
        }
        for row in portfolio.get("rows") or []
    ]
    school_rows = [
        {
            "cells": [
                _cell("School", row.get("school"), primary=True),
                _cell("Project", row.get("project")),
                _cell("Domain", row.get("intervention")),
                _cell(
                    "SSA scores",
                    f"{row.get('baseline') if row.get('baseline') is not None else 'Missing'} → {row.get('follow_up') if row.get('follow_up') is not None else 'Missing'}",
                ),
                _cell(
                    "Evidence", row.get("status"), tone=_state_tone(row.get("state"))
                ),
                _cell(
                    "Follow-up",
                    row.get("follow_up_date") or row.get("due") or "Not scheduled",
                ),
                _cell(
                    "Mapping",
                    f"v{row.get('mapping_version')}"
                    if row.get("mapping_version")
                    else "",
                ),
            ],
            "actions": [],
        }
        for row in snapshot.get("rows") or []
    ]
    findings_rows = [
        {
            "cells": [
                _cell("Approved finding", f.get("statement"), primary=True),
                _cell("Programme", f.get("programme")),
                _cell("Evidence", f.get("evidence")),
                _cell("Limitations", f.get("limitations")),
            ],
            "actions": [],
        }
        for f in snapshot.get("findings") or []
    ]
    return {
        "summary": summary,
        "change": _table(
            request,
            "change_page",
            "School change by outcome area (frozen)",
            change_rows,
            "Not measured",
            "No school had two comparable confirmed SSAs when the report was submitted.",
        ),
        "schools": _table(
            request,
            "schools_page",
            "Project enrolments (frozen)",
            school_rows,
            "No project enrolments",
            "The period and project chosen held no enrolments.",
        ),
        "findings": _table(
            request,
            "findings_page",
            "Approved findings cited",
            findings_rows,
            "No approved findings",
            "No finding of these programmes was approved in the period.",
        ),
        "limitation": snapshot.get("limitation", ""),
    }


def _state_tone(state) -> str:
    from apps.analytics.ia_workflow import STATE_TONES

    return STATE_TONES.get(state or "", "neutral")


def _table(request, param, title, rows, empty_title, empty_body) -> dict:
    page = paginate_rows(rows, page=_page(request, param), page_size=PAGE_SIZE)
    return {
        "title": title,
        "subtitle": "",
        "rows": page.pop("rows"),
        "has_actions": any(row["actions"] for row in rows),
        "pager": page,
        "param": param,
        "empty_title": empty_title,
        "empty_body": empty_body,
    }


def _release_rows(request, report, rights) -> list[dict]:
    me = str(request.user.id)
    rows = []
    for entry in rp.releases_for(report):
        r = entry["release"]
        if rights["summary_only"] and r.audience != "donor":
            continue
        actions = [
            {"label": "View", "drawer": f"{_report_url(report.id)}releases/{r.id}/"}
        ]
        if (
            r.audience == "donor"
            and r.status == "pending_approval"
            and rights["may_decide_donor"]
            and me not in (report.author_id, report.reviewed_by_id, r.requested_by_id)
        ):
            actions = [
                {
                    "label": "Approve or decline",
                    "drawer": f"{_report_url(report.id)}releases/{r.id}/",
                }
            ]
        if r.status == "released" and r.audience != "school":
            actions.append(
                {
                    "label": "Download",
                    "url": f"{_report_url(report.id)}releases/{r.id}/download",
                }
            )
        if r.audience == "school" and not rights["summary_only"]:
            actions.append({"label": "Open brief", "url": rp.brief_url(r.id)})
        detail = entry["shared"]
        if r.audience == "donor" and r.revoked_reason:
            detail = f"Declined: {r.revoked_reason}"
        rows.append(
            {
                "cells": [
                    _cell("Audience", entry["audience_label"], primary=True),
                    _cell("School", r.school.name if r.school_id else ""),
                    _cell("Status", entry["status_label"], tone=entry["status_tone"]),
                    _cell("Requested by", entry["requested_by"]),
                    _cell("Released by", entry["released_by"]),
                    _cell("Released", _day(r.released_at)),
                    _cell("Follow-through", detail),
                ],
                "actions": actions,
            }
        )
    return rows


def _history_rows(report) -> list[dict]:
    return [
        {
            "cells": [
                _cell("When", _day(row["created_at"]), primary=True),
                _cell("What", row["label"]),
                _cell("Who", f"{row['actor']} ({row['actor_role'] or 'system'})"),
                _cell("Note", row["reason"] or ""),
            ],
            "actions": [],
        }
        for row in rp.history(report)
    ]


@require_page_permission("impact_reports")
@require_http_methods(["GET"])
def report_detail(request, report_id):
    from apps.accounts.models import User

    report = _visible(request, report_id)
    rights = rp.detail_rights(request.user, report)
    people = dict(
        User.objects.filter(
            id__in=[i for i in (report.author_id, report.reviewed_by_id) if i]
        ).values_list("id", "name")
    )
    successor = (
        rp.visible_reports(request.user)
        .filter(supersedes_id=report.id)
        .order_by("-version")
        .values("id", "version", "status")
        .first()
    )
    facts = [
        ("Country", report.country),
        ("Period", rp.period_label(report)),
        ("Financial year", f"FY{report.fy}" if report.fy else ""),
        (
            "Special project",
            report.project.name
            if report.project_id
            else "Every project enrolment in scope",
        ),
        (
            "Programme areas",
            ", ".join(
                rp.PROGRAMME_LABELS.get(a, a) for a in report.programme_areas or []
            )
            or "Across programmes",
        ),
        ("Author", people.get(report.author_id, "")),
        ("Submitted", _day(report.submitted_at)),
        (
            "Reviewed by",
            f"{people.get(report.reviewed_by_id, '')} · {REVIEW_BASIS_LABELS.get(report.review_basis, '')} · {_day(report.reviewed_at)}"
            if report.reviewed_by_id
            else "",
        ),
    ]
    release_rows = _release_rows(request, report, rights)
    recommendation_rows = _recommendation_rows(report, rights)
    narrative = rp.narrative_of(report)
    title = report.title
    if rights["summary_only"] and report.evidence_snapshot:
        # The RVP reads the words as donors would: no school or staff names.
        donor = redaction.redact(
            rp.snapshot_with_people(report), redaction.DONOR, narrative=narrative
        )
        narrative, title = donor["narrative"], donor["report"]["title"]
    return render(
        request,
        "pages/ia/impact_reports_detail.html",
        {
            "report": report,
            "title": title,
            "narrative": narrative,
            "rights": rights,
            "status_label": rp.STATUS_LABELS.get(report.status, report.status),
            "status_tone": rp.STATUS_TONES.get(report.status, "neutral"),
            "facts": [f for f in facts if f[1]],
            "successor": successor,
            "evidence": _evidence_tables(request, report, rights),
            "recommendations": {
                "title": "Recommendations",
                "subtitle": "Each with the role that acts and a due date; the Country Director responds once released",
                "rows": recommendation_rows,
                "has_actions": any(r["actions"] for r in recommendation_rows),
                "pager": paginate_rows(recommendation_rows, page=1, page_size=100),
                "param": "recommendations_page",
                "empty_title": "No recommendations",
                "empty_body": "Add what should change, who acts and by when."
                if rights["can_edit"]
                else "This report makes no recommendations.",
            },
            "releases": _table(
                request,
                "releases_page",
                "Releases",
                release_rows,
                "Not released",
                "A reviewed report is released to country leadership first, then school briefs and the donor version.",
            ),
            "history": None
            if rights["summary_only"]
            else _table(
                request,
                "history_page",
                "History",
                _history_rows(report),
                "No history",
                "Transitions and downloads are recorded here.",
            ),
            "live_annex_query": urlencode(
                {
                    "project": report.project_id or "",
                    "fy": report.fy,
                    "period_start": report.period_start.isoformat()
                    if report.period_start
                    else "",
                    "period_end": report.period_end.isoformat()
                    if report.period_end
                    else "",
                }
            ),
            "can_export": RolePermissionService.can_export(
                request.user, "impact_reports"
            ),
        },
    )


# ── The school's brief ───────────────────────────────────────────────────────


def _owner_visits(request, release) -> list[tuple[str, str]]:
    from apps.activities.models import Activity

    staff_id = getattr(request.user, "staff_profile_id", None)
    if not staff_id:
        return []
    visits = (
        Activity.objects.filter(
            school_id=release.school_id,
            responsible_staff_id=staff_id,
            deleted_at__isnull=True,
            planned_date__gte=(release.released_at or timezone.now()).date(),
        )
        .order_by("-planned_date")
        .values_list("id", "activity_type", "planned_date")[:20]
    )
    return [
        (vid, f"{kind.replace('_', ' ').capitalize()} · {planned:%-d %b %Y}")
        for vid, kind, planned in visits
    ]


@require_page_permission("schools")
@require_http_methods(["GET"])
def brief_page(request, release_id):
    release, action, may_record = rp.brief_for(request.user, release_id)
    if release is None:
        raise Http404("That school brief is not yours to open.")
    payload = release.rendered_payload or {}
    results = [
        {
            "cells": [
                _cell("Area", r.get("area"), primary=True),
                _cell("Programme", r.get("programme")),
                _cell(
                    "Before",
                    r.get("baseline")
                    if r.get("baseline") is not None
                    else "Not assessed",
                ),
                _cell(
                    "After",
                    r.get("follow_up")
                    if r.get("follow_up") is not None
                    else "Not assessed",
                ),
                _cell("Change", _signed(r.get("change")) or "Not measured"),
                _cell("Status", r.get("status")),
            ],
            "actions": [],
        }
        for r in payload.get("results") or []
    ]
    return render(
        request,
        "pages/ia/impact_reports_brief.html",
        {
            "release": release,
            "payload": payload,
            "action": action,
            "may_record": may_record,
            "visits": _owner_visits(request, release) if may_record else [],
            "results": _table(
                request,
                "results_page",
                "The school's results",
                results,
                "No results",
                "The report held no before-and-after assessment for this school.",
            ),
            "today": timezone.localdate().isoformat(),
        },
    )


@require_page_permission("schools")
@require_POST
def brief_shared(request, release_id):
    try:
        rp.record_brief_shared(request.user, release_id, request.POST)
    except SERVICE_ERRORS as exc:
        messages.error(request, str(getattr(exc, "detail", exc)))
        return redirect(rp.brief_url(release_id))
    messages.success(request, "Recorded: the findings were shared with the school.")
    return redirect(rp.brief_url(release_id))
