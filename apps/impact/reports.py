"""Impact reports: from IA's draft to what each audience receives
(IA review, owner, 2026-09-13).

The role description's fifth responsibility: prepare unbiased, evidence-based
impact reports that drive Country Director decisions and are communicated to
international donors and local partner schools. Before this, the "report"
was a CSV assembled in the browser from three textareas: nothing was kept,
nobody reviewed it, and the file carried every school, SSA and staff name to
whoever it was sent to.

Lifecycle (apps.impact.review decides who reviews):

  draft ──submit──▶ submitted ──approve──▶ reviewed ──release──▶ released
    │                  │  └──return──▶ returned                 (leadership)
    │                  └──withdraw──▶ withdrawn                      │
    │                                                                ├─ school briefs
    └── a correction of a submitted report is a NEW VERSION ─────────┴─ donor version

  - Impact Assessment writes reports; the author edits a draft, adds its
    recommendations (owner and due date) and submits it.
  - Submitting FREEZES the evidence the report rests on (`build_snapshot`):
    the project cohort in the report's period, portfolio-wide school change
    with evidence grades, evidence beyond the SSA, the collection position,
    the mapping versions, the verified loan impact conclusions and the
    approved findings — with a sha256 of it. Nothing typed by the browser
    enters the snapshot, and nothing changes it afterwards: a correction is a
    new version that supersedes the old once it is submitted (a returned
    report) or released (a reviewed or released one).
  - A second IA officer in the report's country reviews it; the Country
    Director acknowledges only where the country has no other officer. The
    author never reviews their own report.
  - Leadership release: the reviewer releases the reviewed report to country
    leadership; the Country Director is told and responds to each
    recommendation (accept, reject or defer with a reason, in progress, done).
  - School briefs: the reviewer or the Country Director releases a redacted
    brief per school (apps.impact.redaction); the school's account owner is
    handed a TeamAction to share it on a visit and records that it was shared
    and what the school said. IA never plans into another person's portfolio.
  - Donor version: the reviewer or the Country Director requests it; an RVP
    whose region covers the country approves or declines it. The approver is
    never the author, the reviewer or the requester. Donors receive
    aggregates only, with cells under five schools suppressed.

Reach: Impact Assessment and the Country Director read their country's
reports, Admin every country; an RVP reads reviewed and released reports of
the countries in their region, as aggregates (summary-only). Every transition
and every download writes an audit row against the report.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from datetime import date, timedelta

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.rbac import EdifyRole

from . import redaction
from .models import (
    ImpactReport,
    ImpactReportRecommendation,
    ImpactReportRelease,
    Programme,
    RecommendationStatus,
    ReleaseAudience,
    ReleaseStatus,
    ReportStatus,
)

IA = EdifyRole.IMPACT_ASSESSMENT.value
CD = EdifyRole.COUNTRY_DIRECTOR.value
RVP = EdifyRole.REGIONAL_VICE_PRESIDENT.value
ADMIN = EdifyRole.ADMIN.value

READER_ROLES = (IA, CD, RVP, ADMIN)

DRAFT = ReportStatus.DRAFT.value
SUBMITTED = ReportStatus.SUBMITTED.value
RETURNED = ReportStatus.RETURNED.value
REVIEWED = ReportStatus.REVIEWED.value
RELEASED = ReportStatus.RELEASED.value
WITHDRAWN = ReportStatus.WITHDRAWN.value
SUPERSEDED = ReportStatus.SUPERSEDED.value

#: What an RVP may read: a report someone other than its author has reviewed.
RVP_STATUSES = (REVIEWED, RELEASED, SUPERSEDED)

STATUS_LABELS = dict(ReportStatus.choices)
STATUS_TONES = {
    DRAFT: "neutral",
    SUBMITTED: "warning",
    RETURNED: "danger",
    REVIEWED: "info",
    RELEASED: "success",
    WITHDRAWN: "neutral",
    SUPERSEDED: "neutral",
}
PROGRAMME_LABELS = dict(Programme.choices)
AUDIENCE_LABELS = dict(ReleaseAudience.choices)
RELEASE_STATUS_LABELS = dict(ReleaseStatus.choices)
RELEASE_TONES = {
    ReleaseStatus.PENDING_APPROVAL.value: "warning",
    ReleaseStatus.APPROVED.value: "info",
    ReleaseStatus.RELEASED.value: "success",
    ReleaseStatus.REVOKED.value: "neutral",
}
RECOMMENDATION_LABELS = dict(RecommendationStatus.choices)
RECOMMENDATION_TONES = {
    RecommendationStatus.PROPOSED.value: "warning",
    RecommendationStatus.ACCEPTED.value: "info",
    RecommendationStatus.REJECTED.value: "neutral",
    RecommendationStatus.DEFERRED.value: "neutral",
    RecommendationStatus.IN_PROGRESS.value: "info",
    RecommendationStatus.DONE.value: "success",
}
#: The Country Director's answers to a recommendation. Rejecting or deferring
#: one says why.
RESPONSES = (
    (RecommendationStatus.ACCEPTED.value, "Accept"),
    (RecommendationStatus.IN_PROGRESS.value, "In progress"),
    (RecommendationStatus.DONE.value, "Done"),
    (RecommendationStatus.DEFERRED.value, "Defer (say why)"),
    (RecommendationStatus.REJECTED.value, "Reject (say why)"),
)
NEEDS_REASON = (
    RecommendationStatus.REJECTED.value,
    RecommendationStatus.DEFERRED.value,
)
#: Recommendations still owed action: overdue once past their due date.
OPEN_RECOMMENDATIONS = (
    RecommendationStatus.PROPOSED.value,
    RecommendationStatus.ACCEPTED.value,
    RecommendationStatus.IN_PROGRESS.value,
)

EVENT_REVIEW_REQUESTED = "ia.report.review_requested"
EVENT_REVIEW_DECIDED = "ia.report.review_decided"
EVENT_RELEASED = "ia.report.released"
EVENT_RECOMMENDATION_RESPONDED = "ia.report.recommendation_responded"
EVENT_DONOR_REQUESTED = "ia.report.donor_approval_requested"
EVENT_DONOR_DECIDED = "ia.report.donor_decided"
EVENT_SCHOOL_BRIEF = "ia.report.school_brief"

#: The TeamAction a school brief is delivered through.
BRIEF_ISSUE_TYPE = "impact_findings_share"
BRIEF_DUE_DAYS = 30

SNAPSHOT_SCHEMA = 1

#: Row keys a frozen snapshot keeps from the outcome workspace.
ROW_KEYS = (
    "assignment_id",
    "school_id",
    "school",
    "owner_id",
    "owner",
    "project_id",
    "project",
    "intervention_code",
    "intervention",
    "state",
    "status",
    "measured",
    "baseline",
    "follow_up",
    "delta",
    "baseline_date",
    "follow_up_date",
    "baseline_id",
    "follow_up_id",
    "mapping_version",
    "due",
    "action",
)


def _uid(principal) -> str:
    return str(getattr(principal, "id", "") or getattr(principal, "user_id", ""))


def _role(principal) -> str:
    return getattr(principal, "active_role", "") or ""


def _name(principal) -> str:
    return str(getattr(principal, "name", "") or "")


def _profile_country(principal) -> str:
    from apps.impact.review import _profile_country as country

    return country(principal)


def json_safe(value):
    """What JSONField stores: dates as ISO strings, Decimals as numbers."""
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder))


def snapshot_hash(snapshot: dict) -> str:
    from apps.core.audit_hash import stable_stringify

    return hashlib.sha256(stable_stringify(snapshot).encode("utf-8")).hexdigest()


# ── Reach ────────────────────────────────────────────────────────────────────


def reader_country(principal) -> str:
    """The country a reader is bound to: their analytics scope's country, else
    their staff profile's. Blank for Admin and a reader with no country on
    file, who read every country (owner rule, 2026-09-03)."""
    from apps.core.scoping import resolve_user_scope

    if _role(principal) == ADMIN:
        return ""
    scope = resolve_user_scope(principal)
    return (scope.country or _profile_country(principal) or "").strip()


def rvp_countries(principal) -> list[str] | None:
    """The countries an RVP's region covers; None for an RVP with no region
    on file, who oversees the whole deployment (apps.core.scoping)."""
    from apps.core.scoping import resolve_user_scope
    from apps.geography.models import Region

    scope = resolve_user_scope(principal)
    if not scope.rvp_region_scoped:
        return None
    return sorted(
        {
            c
            for c in Region.objects.filter(id__in=scope.region_ids).values_list(
                "country", flat=True
            )
            if c
        }
    )


def visible_reports(principal):
    """The impact reports `principal` may read."""
    role = _role(principal)
    qs = ImpactReport.objects.all()
    if role in (IA, CD):
        country = reader_country(principal)
        return qs.filter(country=country) if country else qs
    if role == ADMIN:
        return qs
    if role == RVP:
        qs = qs.filter(status__in=RVP_STATUSES)
        countries = rvp_countries(principal)
        return qs if countries is None else qs.filter(country__in=countries)
    return qs.none()


def is_summary_reader(principal) -> bool:
    """The RVP reads aggregates only — never school rows (apps.core.scoping)."""
    return _role(principal) == RVP


def may_author(principal) -> bool:
    return _role(principal) == IA


def _is_country_cd(principal, country: str) -> bool:
    return (
        _role(principal) == CD
        and bool(country)
        and _profile_country(principal) == country
    )


def _is_country_ia(principal, country: str) -> bool:
    return (
        _role(principal) == IA
        and bool(country)
        and _profile_country(principal) == country
    )


def _rvp_covers(principal, country: str) -> bool:
    if _role(principal) != RVP:
        return False
    countries = rvp_countries(principal)
    return countries is None or country in countries


def _audit(action: str, report, principal, payload: dict | None = None) -> None:
    from apps.audit.services import log as audit_log

    payload = dict(payload or {})
    note = payload.get("note")
    audit_log(
        action=action,
        subject_kind="ImpactReport",
        subject_id=str(report.id),
        actor_id=_uid(principal) or None,
        actor_role=_role(principal) or None,
        reason=str(note)[:500] if note else None,
        payload={
            "country": report.country,
            "version": report.version,
            "status": report.status,
            "snapshot_hash": report.snapshot_hash or None,
            **payload,
        },
    )


# ── Parsing ──────────────────────────────────────────────────────────────────


def _text(data, key, *, label, required=False, max_length=10000) -> str:
    value = str(data.get(key) or "").strip()
    if required and not value:
        raise BadRequest(f"{label} is required.")
    if len(value) > max_length:
        raise BadRequest(f"{label} must be {max_length} characters or fewer.")
    return value


def _date(data, key, *, label):
    raw = str(data.get(key) or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise BadRequest(f"{label} must be a date (YYYY-MM-DD).") from None


def fy_choices() -> list[str]:
    from apps.core.fy import fy_options

    return fy_options()


def _getlist(data, key) -> list[str]:
    if hasattr(data, "getlist"):
        return [str(v) for v in data.getlist(key)]
    value = data.get(key)
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return [str(value)] if value else []


def project_options(principal) -> list[tuple[str, str]]:
    """Special projects with enrolments in the author's scope."""
    from apps.core.scoping import resolve_user_scope, scoped_school_queryset
    from apps.projects.models import ProjectSchoolAssignment

    scope = resolve_user_scope(principal)
    schools = scoped_school_queryset(scope)
    if schools is None or scope.can_view_summary_only:
        return []
    return list(
        ProjectSchoolAssignment.objects.filter(
            school__in=schools, project__deleted_at__isnull=True
        )
        .order_by("project__name")
        .values_list("project_id", "project__name")
        .distinct()
    )


def _clean(principal, data) -> dict:
    fy = str(data.get("fy") or "").strip()
    if fy not in fy_choices():
        raise BadRequest("Choose the financial year the report covers.")
    period_start = _date(data, "period_start", label="Period start")
    period_end = _date(data, "period_end", label="Period end")
    if period_start and period_end and period_start > period_end:
        raise BadRequest("The period must start before it ends.")
    areas = [a for a in _getlist(data, "programme_areas") if a]
    unknown = [a for a in areas if a not in PROGRAMME_LABELS]
    if unknown:
        raise BadRequest("Choose programme areas from the list.")
    project_id = str(data.get("project") or "").strip()
    if project_id and project_id not in {p for p, _n in project_options(principal)}:
        raise BadRequest("Choose a special project with enrolments in your country.")
    return {
        "title": _text(data, "title", label="Title", required=True, max_length=200),
        "fy": fy,
        "period_start": period_start,
        "period_end": period_end,
        "programme_areas": sorted(set(areas), key=list(PROGRAMME_LABELS).index),
        "project_id": project_id or None,
        "methodology": _text(data, "methodology", label="Methodology"),
        "findings": _text(data, "findings", label="Findings"),
        "limitations": _text(data, "limitations", label="Limitations"),
    }


def period_bounds(report) -> tuple[date, date]:
    """The report's period: its own dates, else its financial year."""
    from apps.core.fy import get_fy_date_range

    fy = report.fy or ""
    start = report.period_start
    end = report.period_end
    if fy and (start is None or end is None):
        fy_start, fy_end = get_fy_date_range(fy)
        start = start or fy_start.date()
        end = end or (fy_end - timedelta(days=1)).date()
    return start, end


def period_label(report) -> str:
    start, end = period_bounds(report)
    if start and end:
        return f"{start:%-d %b %Y} – {end:%-d %b %Y}"
    return f"FY{report.fy}" if report.fy else "All recorded enrolments"


# ── The evidence snapshot ────────────────────────────────────────────────────


def rows_in_period(rows, start, end) -> tuple[list[dict], int]:
    """Enrolment rows whose evidence falls in the period: a measured row by
    its follow-up assessment, any other by its follow-up due date. Rows with
    neither date cannot be placed in a period; they are counted, not kept."""
    if not start and not end:
        return list(rows), 0
    kept, undated = [], 0
    for row in rows:
        raw = row.get("follow_up_date") if row.get("measured") else row.get("due")
        if not raw:
            undated += 1
            continue
        day = date.fromisoformat(str(raw)[:10])
        if (start is None or day >= start) and (end is None or day <= end):
            kept.append(row)
    return kept, undated


def summarise_rows(rows) -> dict:
    """The project cohort's counts over the rows kept, recounted so the
    period filter reaches every figure."""
    counts = Counter(row["state"] for row in rows)
    measured = [row for row in rows if row.get("measured")]
    n = len(measured)
    return {
        "total": len(rows),
        "unique_schools": len({row["school_id"] for row in rows}),
        "measured": n,
        "measured_schools": len({row["school_id"] for row in measured}),
        "unmeasured": len(rows) - n,
        "improved": counts["improved"],
        "improved_pct": round(100 * counts["improved"] / n) if n else None,
        "declined": counts["declined"],
        "declined_pct": round(100 * counts["declined"] / n) if n else None,
        "maintained": counts["maintained_strong"],
        "no_change": counts["no_change"],
        "baseline_missing": counts["baseline_missing"],
        "overdue": counts["overdue"],
        "due": counts["due"],
        "not_scheduled": counts["not_scheduled"],
    }


def _lending_evidence(principal, start, end) -> dict:
    from apps.business_transformation.lending_impact import scoped_impact_loans
    from apps.business_transformation.models import LoanImpactAssessment

    qs = LoanImpactAssessment.objects.filter(
        loan__in=scoped_impact_loans(principal), ia_status="verified"
    )
    if start:
        qs = qs.filter(ia_verified_at__date__gte=start)
    if end:
        qs = qs.filter(ia_verified_at__date__lte=end)
    rows = list(qs.order_by("id").values_list("id", "classification"))
    return {
        "verified_ids": [r[0] for r in rows],
        "by_classification": dict(Counter(r[1] for r in rows)),
    }


def _approved_findings(report, start, end) -> list[dict]:
    from apps.impact.models import FindingStatus, ImpactFinding

    qs = ImpactFinding.objects.filter(
        country=report.country, status=FindingStatus.APPROVED
    )
    if start:
        qs = qs.filter(reviewed_at__date__gte=start)
    if end:
        qs = qs.filter(reviewed_at__date__lte=end)
    if report.programme_areas:
        qs = qs.filter(programme__in=report.programme_areas)
    return [
        {
            "id": f.id,
            "programme": PROGRAMME_LABELS.get(f.programme, f.programme),
            "statement": f.statement,
            "limitations": f.limitations,
            "evidence": (f.metric_snapshot or {}).get("grade_label") or "",
            "reviewed_at": f.reviewed_at,
        }
        for f in qs.order_by("-reviewed_at")[:25]
    ]


def build_snapshot(principal, report) -> dict:
    """Everything the report rests on, computed by the server in the author's
    own scope at the moment of submission."""
    from apps.analytics.ia_collection import state_counts
    from apps.analytics.ia_workflow import (
        LIMITATION,
        _chosen_fy,
        _cohort_domains,
        outcome_workspace,
        portfolio_change,
    )
    from apps.impact.evidence_services import outcome_evidence

    start, end = period_bounds(report)
    workspace = outcome_workspace(principal, {"project": report.project_id or ""})
    rows, undated = rows_in_period(workspace["rows"], start, end)
    cohort = summarise_rows(rows)
    cohort["outside_period_undated"] = undated
    measured_rows = [row for row in rows if row.get("measured")]
    fy = report.fy
    _chosen, comparable = _chosen_fy({"fy": fy})
    portfolio = portfolio_change(principal, fy=fy) if fy in comparable else None
    mapping_versions = Counter(
        (row["intervention"], row["mapping_version"]) for row in rows
    )
    snapshot = {
        "schema": SNAPSHOT_SCHEMA,
        "report": {
            "id": report.id,
            "title": report.title,
            "version": report.version,
            "country": report.country,
            "fy": report.fy,
            "period_start": start,
            "period_end": end,
            "project_id": report.project_id or "",
            "project": report.project.name if report.project_id else "",
            "programme_areas": list(report.programme_areas or []),
            "programme_area_labels": [
                PROGRAMME_LABELS.get(a, a) for a in report.programme_areas or []
            ],
        },
        "generated_at": timezone.now(),
        "generated_by": {"id": _uid(principal), "role": _role(principal)},
        "people": [_name(principal)],
        "scope_label": workspace["scope_label"],
        "cohort": cohort,
        "domains": _cohort_domains(measured_rows),
        "rows": [{key: row.get(key) for key in ROW_KEYS} for row in rows],
        "portfolio": portfolio,
        "portfolio_note": ""
        if portfolio is not None
        else f"FY{fy} has no earlier year on the platform to compare with.",
        "evidence": outcome_evidence(principal, fy),
        "collection": state_counts(principal, fy=fy),
        "mapping_versions": [
            {"intervention": label, "mapping_version": version, "enrolments": n}
            for (label, version), n in sorted(
                mapping_versions.items(), key=lambda item: (item[0][0], item[0][1] or 0)
            )
        ],
        "lending": _lending_evidence(principal, start, end),
        "findings": _approved_findings(report, start, end),
        "limitation": LIMITATION,
    }
    return json_safe(snapshot)


# ── Writes ───────────────────────────────────────────────────────────────────


def _report_for_update(principal, report_id: str) -> ImpactReport:
    report = (
        visible_reports(principal)
        .select_for_update(of=("self",))
        .filter(id=report_id)
        .first()
    )
    if report is None:
        raise NotFoundError("That impact report is not in your country.")
    return report


def _own_report(principal, report_id: str) -> ImpactReport:
    if not may_author(principal):
        raise Forbidden("Only Impact Assessment writes impact reports.")
    report = _report_for_update(principal, report_id)
    if report.author_id != _uid(principal):
        raise Forbidden("Only the officer who wrote the report changes it.")
    return report


def _assert_draft(report) -> None:
    if report.status != DRAFT:
        raise BadRequest(
            f"This report is {STATUS_LABELS[report.status].lower()}; its evidence is "
            "frozen, so a correction is a new version."
        )


def create_report(principal, data) -> ImpactReport:
    """A draft report by an Impact Assessment officer, in their country."""
    if not may_author(principal):
        raise Forbidden("Only Impact Assessment writes impact reports.")
    country = _profile_country(principal)
    if not country:
        raise BadRequest(
            "Your staff profile has no country, so nobody can be named to review "
            "the report. Ask HR to record your country first."
        )
    fields = _clean(principal, data)
    with transaction.atomic():
        report = ImpactReport.objects.create(
            country=country,
            author_id=_uid(principal),
            author_role=_role(principal),
            status=DRAFT,
            **fields,
        )
        _audit("ia.report.started", report, principal)
    return report


def update_report(principal, report_id: str, data) -> ImpactReport:
    fields = _clean(principal, data)
    with transaction.atomic():
        report = _own_report(principal, report_id)
        _assert_draft(report)
        changed = [k for k, v in fields.items() if getattr(report, k) != v]
        for key, value in fields.items():
            setattr(report, key, value)
        report.save()
        _audit("ia.report.updated", report, principal, {"changed": changed})
    return report


def add_recommendation(principal, report_id: str, data) -> ImpactReportRecommendation:
    from apps.impact.findings import ACTION_OWNER_LABELS

    text = _text(data, "text", label="Recommendation", required=True, max_length=4000)
    owner_role = str(data.get("owner_role") or "").strip()
    if owner_role not in ACTION_OWNER_LABELS:
        raise BadRequest("Say who should act on the recommendation.")
    due_date = _date(data, "due_date", label="Due date")
    if due_date is None:
        raise BadRequest("Give the recommendation a due date.")
    with transaction.atomic():
        report = _own_report(principal, report_id)
        _assert_draft(report)
        recommendation = ImpactReportRecommendation.objects.create(
            report=report, text=text, owner_role=owner_role, due_date=due_date
        )
        _audit(
            "ia.report.recommendation_added",
            report,
            principal,
            {"recommendation_id": recommendation.id, "owner_role": owner_role},
        )
    return recommendation


def remove_recommendation(principal, report_id: str, recommendation_id: str) -> None:
    with transaction.atomic():
        report = _own_report(principal, report_id)
        _assert_draft(report)
        deleted, _ = ImpactReportRecommendation.objects.filter(
            report=report, id=recommendation_id
        ).delete()
        if not deleted:
            raise NotFoundError("That recommendation is not on this report.")
        _audit(
            "ia.report.recommendation_removed",
            report,
            principal,
            {"recommendation_id": recommendation_id},
        )


def _assert_submittable(report) -> None:
    for key, label in (
        ("methodology", "the methodology"),
        ("findings", "the findings"),
        ("limitations", "the limitations: what this evidence cannot show"),
    ):
        if not getattr(report, key).strip():
            raise BadRequest(f"State {label} before submitting.")


def submit_report(principal, report_id: str) -> ImpactReport:
    """Freeze the evidence and send the report for review."""
    with transaction.atomic():
        report = _own_report(principal, report_id)
        _assert_draft(report)
        _assert_submittable(report)
        snapshot = build_snapshot(principal, report)
        report.evidence_snapshot = snapshot
        report.snapshot_hash = snapshot_hash(snapshot)
        report.status = SUBMITTED
        report.submitted_at = timezone.now()
        report.save(
            update_fields=[
                "evidence_snapshot",
                "snapshot_hash",
                "status",
                "submitted_at",
                "updated_at",
            ]
        )
        superseded = _supersede_prior(
            report, principal, when_prior_in=(RETURNED, WITHDRAWN)
        )
        _audit(
            "ia.report.submitted",
            report,
            principal,
            {
                "rows": len(snapshot.get("rows") or []),
                "measured": (snapshot.get("cohort") or {}).get("measured"),
                "supersedes": superseded,
            },
        )
    _notify_reviewers(report)
    return report


def _supersede_prior(report, principal, *, when_prior_in) -> str | None:
    if not report.supersedes_id:
        return None
    prior = (
        ImpactReport.objects.select_for_update()
        .filter(id=report.supersedes_id, status__in=when_prior_in)
        .first()
    )
    if prior is None:
        return None
    prior.status = SUPERSEDED
    prior.save(update_fields=["status", "updated_at"])
    _audit("ia.report.superseded", prior, principal, {"superseded_by": report.id})
    return prior.id


def withdraw_report(principal, report_id: str, note: str = "") -> ImpactReport:
    with transaction.atomic():
        report = _own_report(principal, report_id)
        if report.status not in (DRAFT, SUBMITTED):
            raise BadRequest(
                f"This report is {STATUS_LABELS[report.status].lower()} and cannot be withdrawn."
            )
        report.status = WITHDRAWN
        report.save(update_fields=["status", "updated_at"])
        _audit("ia.report.withdrawn", report, principal, {"note": note or None})
    _resolve(EVENT_REVIEW_REQUESTED, report)
    return report


def review_report(
    principal, report_id: str, *, decision: str, note: str = ""
) -> ImpactReport:
    """Approve or return a submitted report — never by its author (a second
    IA officer in the country; the Country Director where there is none)."""
    from apps.impact.review import assert_can_review

    if decision not in ("approve", "return"):
        raise BadRequest("Choose approve or return.")
    note = (note or "").strip()
    if decision == "return" and not note:
        raise BadRequest("Say what the author needs to change.")
    with transaction.atomic():
        report = _report_for_update(principal, report_id)
        if report.status != SUBMITTED:
            raise BadRequest(
                f"This report is {STATUS_LABELS[report.status].lower()}, not awaiting review."
            )
        basis = assert_can_review(
            principal, author_id=report.author_id, country=report.country
        )
        report.status = REVIEWED if decision == "approve" else RETURNED
        report.reviewed_by_id = _uid(principal)
        report.reviewed_at = timezone.now()
        report.review_basis = basis
        report.review_note = note[:4000]
        report.save(
            update_fields=[
                "status",
                "reviewed_by_id",
                "reviewed_at",
                "review_basis",
                "review_note",
                "updated_at",
            ]
        )
        _audit(
            f"ia.report.{'reviewed' if decision == 'approve' else 'returned'}",
            report,
            principal,
            {"review_basis": basis, "note": note or None},
        )
    _resolve(EVENT_REVIEW_REQUESTED, report)
    _notify(
        EVENT_REVIEW_DECIDED,
        report,
        [report.author_id],
        title=(
            "Your impact report was reviewed"
            if decision == "approve"
            else "Your impact report was returned"
        ),
        body=note or report.title,
        priority="normal" if decision == "approve" else "high",
    )
    return report


def open_correction(report) -> ImpactReport | None:
    return (
        ImpactReport.objects.filter(
            supersedes_id=report.id, status__in=(DRAFT, SUBMITTED, RETURNED)
        )
        .order_by("-version")
        .first()
    )


def start_correction(principal, report_id: str) -> ImpactReport:
    """A new version carrying the same words and recommendations. The
    corrected report stands until the new version replaces it."""
    if not may_author(principal):
        raise Forbidden("Only Impact Assessment writes impact reports.")
    with transaction.atomic():
        report = _report_for_update(principal, report_id)
        if not _is_country_ia(principal, report.country):
            raise Forbidden(
                "Only an Impact Assessment officer in this country corrects it."
            )
        correctable = report.status in (RETURNED, REVIEWED, RELEASED) or (
            report.status == WITHDRAWN and report.submitted_at is not None
        )
        if not correctable:
            raise BadRequest(
                "Only a returned, reviewed, released or withdrawn report is corrected; "
                "edit a draft instead."
            )
        if open_correction(report) is not None:
            raise BadRequest("A correction of this report is already open.")
        revision = ImpactReport.objects.create(
            country=report.country,
            fy=report.fy,
            period_start=report.period_start,
            period_end=report.period_end,
            project_id=report.project_id,
            programme_areas=list(report.programme_areas or []),
            title=report.title,
            methodology=report.methodology,
            findings=report.findings,
            limitations=report.limitations,
            version=report.version + 1,
            supersedes=report,
            author_id=_uid(principal),
            author_role=_role(principal),
            status=DRAFT,
        )
        ImpactReportRecommendation.objects.bulk_create(
            [
                ImpactReportRecommendation(
                    report=revision,
                    text=r.text,
                    owner_role=r.owner_role,
                    due_date=r.due_date,
                )
                for r in report.recommendations.all()
            ]
        )
        _audit(
            "ia.report.correction_started",
            revision,
            principal,
            {"corrects": report.id, "corrects_version": report.version},
        )
    return revision


# ── Releases ─────────────────────────────────────────────────────────────────


def narrative_of(report) -> dict:
    return {
        "methodology": report.methodology,
        "findings": report.findings,
        "limitations": report.limitations,
    }


def recommendation_payload(report) -> list[dict]:
    from apps.impact.findings import ACTION_OWNER_LABELS

    return [
        {
            "id": r.id,
            "text": r.text,
            "owner_role": r.owner_role,
            "owner_label": ACTION_OWNER_LABELS.get(r.owner_role, r.owner_role),
            "due_date": r.due_date.isoformat() if r.due_date else "",
        }
        for r in report.recommendations.all().order_by("due_date", "created_at")
    ]


def snapshot_with_people(report) -> dict:
    """The frozen snapshot plus the author's and reviewer's names, so the
    redaction can scrub them from free text."""
    from apps.accounts.models import User

    snapshot = dict(report.evidence_snapshot or {})
    ids = [i for i in (report.author_id, report.reviewed_by_id) if i]
    people = list(snapshot.get("people") or [])
    people += list(User.objects.filter(id__in=ids).values_list("name", flat=True))
    snapshot["people"] = people
    return snapshot


def release_to_leadership(principal, report_id: str) -> ImpactReportRelease:
    """The reviewer releases the reviewed report to the country's leadership;
    the Country Director is told and responds to each recommendation."""
    now = timezone.now()
    with transaction.atomic():
        report = _report_for_update(principal, report_id)
        if report.status != REVIEWED:
            raise BadRequest("Only a reviewed report is released to leadership.")
        if report.reviewed_by_id != _uid(principal):
            raise Forbidden("The person who reviewed the report releases it.")
        payload = redaction.redact(
            report.evidence_snapshot or {},
            redaction.LEADERSHIP,
            narrative=narrative_of(report),
            recommendations=recommendation_payload(report),
        )
        release, _created = ImpactReportRelease.objects.update_or_create(
            report=report,
            audience=ReleaseAudience.LEADERSHIP,
            school=None,
            defaults={
                "redaction_profile": redaction.LEADERSHIP,
                "rendered_payload": json_safe(payload),
                "status": ReleaseStatus.RELEASED,
                "requested_by_id": _uid(principal),
                "approved_by_id": _uid(principal),
                "approved_at": now,
                "released_by_id": _uid(principal),
                "released_at": now,
                "revoked_reason": "",
            },
        )
        report.status = RELEASED
        report.save(update_fields=["status", "updated_at"])
        superseded = _supersede_prior(
            report, principal, when_prior_in=(REVIEWED, RELEASED)
        )
        _audit(
            "ia.report.released",
            report,
            principal,
            {
                "audience": redaction.LEADERSHIP,
                "release_id": release.id,
                "supersedes": superseded,
            },
        )
    from apps.notifications.services import role_recipients

    _notify(
        EVENT_RELEASED,
        report,
        [u.id for u in role_recipients(CD, country=report.country)],
        title=f"Impact report released: {report.title}",
        body=(
            f"{period_label(report)} · {report.recommendations.count()} "
            "recommendation(s) wait for your response."
        ),
        priority="high",
    )
    return release


def release_school_briefs(principal, report_id: str, school_ids) -> dict:
    """One redacted brief per school, each handed to the school's account
    owner as a TeamAction to share on a visit. Returns what was released and
    what could not be (no account owner, already released)."""
    from apps.accounts.models import StaffProfile
    from apps.planning.action_models import ActionPriority, ActionState, TeamAction
    from apps.schools.models import School

    wanted = [str(s) for s in school_ids if s]
    if not wanted:
        raise BadRequest("Choose at least one school.")
    today = timezone.localdate()
    released, skipped = [], []
    with transaction.atomic():
        report = _report_for_update(principal, report_id)
        if report.status != RELEASED:
            raise BadRequest(
                "School briefs follow the leadership release; release the report first."
            )
        if not (
            report.reviewed_by_id == _uid(principal)
            or _is_country_cd(principal, report.country)
        ):
            raise Forbidden(
                "The report's reviewer or the Country Director releases school briefs."
            )
        snapshot = snapshot_with_people(report)
        in_report = {row["school_id"] for row in snapshot.get("rows") or []}
        outside = [s for s in wanted if s not in in_report]
        if outside:
            raise BadRequest("Choose schools the report's evidence covers.")
        schools = {
            s.id: s
            for s in School.objects.filter(id__in=wanted, deleted_at__isnull=True)
        }
        existing = set(
            ImpactReportRelease.objects.filter(
                report=report, audience=ReleaseAudience.SCHOOL, school_id__in=wanted
            ).values_list("school_id", flat=True)
        )
        owners = {
            p.id: p
            for p in StaffProfile.objects.filter(
                id__in={
                    s.account_owner_id for s in schools.values() if s.account_owner_id
                },
                deleted_at__isnull=True,
            ).select_related("user")
        }
        narrative = narrative_of(report)
        for school_id in wanted:
            school = schools.get(school_id)
            if school is None:
                continue
            if school_id in existing:
                skipped.append((school.name, "already released"))
                continue
            owner = owners.get(school.account_owner_id or "")
            if owner is None or not owner.user_id or not owner.user.is_active:
                skipped.append((school.name, "no active account owner to share it"))
                continue
            payload = redaction.redact(
                snapshot,
                redaction.SCHOOL,
                narrative=narrative,
                school_id=school_id,
                school_name=school.name,
            )
            release = ImpactReportRelease.objects.create(
                report=report,
                audience=ReleaseAudience.SCHOOL,
                school=school,
                redaction_profile=redaction.SCHOOL,
                rendered_payload=json_safe(payload),
                status=ReleaseStatus.RELEASED,
                requested_by_id=_uid(principal),
                approved_by_id=_uid(principal),
                approved_at=timezone.now(),
                released_by_id=_uid(principal),
                released_at=timezone.now(),
            )
            action = TeamAction.objects.create(
                condition_key=brief_condition_key(release.id),
                issue_type=BRIEF_ISSUE_TYPE,
                severity="normal",
                school_id=school.id,
                fy=report.fy or "",
                sender_id=_uid(principal),
                sender_role=_role(principal),
                recipient_id=owner.user_id,
                recipient_role=getattr(owner.user, "active_role", "") or "",
                requested_action="Share impact findings with the school",
                workflow_route=brief_url(release.id),
                message=(
                    f"{report.title} ({period_label(report)}): share the school's "
                    "brief on your next visit and record what the school said."
                ),
                priority=ActionPriority.NORMAL,
                due_date=today + timedelta(days=BRIEF_DUE_DAYS),
                state=ActionState.OPEN,
                detected_at=timezone.now(),
            )
            _audit(
                "ia.report.released",
                report,
                principal,
                {
                    "audience": redaction.SCHOOL,
                    "release_id": release.id,
                    "school_id": school.id,
                    "team_action_id": action.id,
                },
            )
            released.append((release, owner.user_id, school.name))
    for release, recipient, school_name in released:
        _notify(
            EVENT_SCHOOL_BRIEF,
            report,
            [recipient],
            title=f"Share impact findings with {school_name}",
            body="Impact Assessment's brief for the school is ready to share on your next visit.",
            context_type="ImpactReportRelease",
            context_id=release.id,
        )
    return {"released": [r[0] for r in released], "skipped": skipped}


def brief_condition_key(release_id: str) -> str:
    return f"impact_brief:{release_id}"


def brief_url(release_id: str) -> str:
    return f"/impact-briefs/{release_id}/"


def request_donor_release(
    principal, report_id: str, note: str = ""
) -> ImpactReportRelease:
    """The reviewer or the Country Director asks for the donor version; an
    RVP approves it."""
    from apps.notifications.services import role_recipients

    with transaction.atomic():
        report = _report_for_update(principal, report_id)
        if report.status != RELEASED:
            raise BadRequest(
                "A donor version follows the leadership release; release the report first."
            )
        if not (
            report.reviewed_by_id == _uid(principal)
            or _is_country_cd(principal, report.country)
        ):
            raise Forbidden(
                "The report's reviewer or the Country Director requests the donor version."
            )
        release = (
            ImpactReportRelease.objects.select_for_update()
            .filter(report=report, audience=ReleaseAudience.DONOR, school__isnull=True)
            .first()
        )
        if release is not None and release.status != ReleaseStatus.REVOKED:
            raise BadRequest(
                f"The donor version is already {RELEASE_STATUS_LABELS[release.status].lower()}."
            )
        payload = json_safe(
            redaction.redact(
                snapshot_with_people(report),
                redaction.DONOR,
                narrative=narrative_of(report),
                recommendations=recommendation_payload(report),
            )
        )
        fields = {
            "redaction_profile": redaction.DONOR,
            "rendered_payload": payload,
            "status": ReleaseStatus.PENDING_APPROVAL,
            "requested_by_id": _uid(principal),
            "approved_by_id": None,
            "approved_at": None,
            "released_by_id": None,
            "released_at": None,
            "revoked_reason": "",
        }
        if release is None:
            release = ImpactReportRelease.objects.create(
                report=report, audience=ReleaseAudience.DONOR, school=None, **fields
            )
        else:
            for key, value in fields.items():
                setattr(release, key, value)
            release.save()
        _audit(
            "ia.report.donor_requested",
            report,
            principal,
            {"release_id": release.id, "note": note or None},
        )
    candidates = [
        u
        for u in role_recipients(RVP)
        if str(u.id) not in (report.author_id, report.reviewed_by_id, _uid(principal))
    ]
    covering = _rvps_covering(candidates, report.country)
    _notify(
        EVENT_DONOR_REQUESTED,
        report,
        covering,
        title=f"Donor version to approve: {report.title}",
        body=note or f"{report.country} · {period_label(report)}",
        priority="high",
    )
    return release


def _rvps_covering(users, country: str) -> list[str]:
    """RVPs whose region covers `country`, or who have no region on file. A
    handful of people, so each one's reach is resolved as an RVP."""
    out = []
    for user in users:
        user.active_role = RVP  # in memory only: read their RVP reach
        if _rvp_covers(user, country):
            out.append(str(user.id))
    return out


def decide_donor_release(
    principal, release_id: str, *, decision: str, note: str = ""
) -> ImpactReportRelease:
    """An RVP covering the country approves (releases) or declines the donor
    version. Two keys: never the author, the reviewer or the requester."""
    if decision not in ("approve", "decline"):
        raise BadRequest("Choose approve or decline.")
    note = (note or "").strip()
    if decision == "decline" and not note:
        raise BadRequest("Say why the donor version is declined.")
    if _role(principal) != RVP:
        raise Forbidden("A Regional Vice President approves donor versions.")
    with transaction.atomic():
        release = (
            ImpactReportRelease.objects.select_for_update(of=("self",))
            .select_related("report")
            .filter(
                id=release_id,
                audience=ReleaseAudience.DONOR,
                report__in=visible_reports(principal),
            )
            .first()
        )
        if release is None:
            raise NotFoundError("That donor version is not in your region.")
        report = release.report
        if not _rvp_covers(principal, report.country):
            raise NotFoundError("That donor version is not in your region.")
        if release.status != ReleaseStatus.PENDING_APPROVAL:
            raise BadRequest(
                f"This donor version is {RELEASE_STATUS_LABELS[release.status].lower()}, "
                "not awaiting approval."
            )
        me = _uid(principal)
        if me in (report.author_id, report.reviewed_by_id, release.requested_by_id):
            raise Forbidden(
                "The donor version is approved by someone who did not write, review "
                "or request it."
            )
        now = timezone.now()
        if decision == "approve":
            release.status = ReleaseStatus.RELEASED
            release.approved_by_id = me
            release.approved_at = now
            release.released_by_id = me
            release.released_at = now
        else:
            release.status = ReleaseStatus.REVOKED
            release.revoked_reason = note[:4000]
        release.save()
        _audit(
            "ia.report.donor_released"
            if decision == "approve"
            else "ia.report.donor_declined",
            report,
            principal,
            {"release_id": release.id, "note": note or None},
        )
    _resolve(EVENT_DONOR_REQUESTED, report)
    _notify(
        EVENT_DONOR_DECIDED,
        report,
        [release.requested_by_id, report.author_id],
        title=(
            f"Donor version released: {report.title}"
            if decision == "approve"
            else f"Donor version declined: {report.title}"
        ),
        body=note or period_label(report),
        priority="normal" if decision == "approve" else "high",
    )
    return release


def respond_to_recommendation(
    principal, recommendation_id: str, *, status: str, response: str = ""
) -> ImpactReportRecommendation:
    """The Country Director answers a released report's recommendation."""
    response = (response or "").strip()
    if status not in dict(RESPONSES):
        raise BadRequest("Choose a response from the list.")
    if status in NEEDS_REASON and not response:
        raise BadRequest("Say why the recommendation is rejected or deferred.")
    if len(response) > 4000:
        raise BadRequest("The response must be 4000 characters or fewer.")
    with transaction.atomic():
        recommendation = (
            ImpactReportRecommendation.objects.select_for_update(of=("self",))
            .select_related("report")
            .filter(id=recommendation_id, report__in=visible_reports(principal))
            .first()
        )
        if recommendation is None:
            raise NotFoundError("That recommendation is not in your country.")
        report = recommendation.report
        if not _is_country_cd(principal, report.country):
            raise Forbidden(
                "The country's Country Director responds to recommendations."
            )
        if report.status != RELEASED:
            raise BadRequest(
                "Recommendations are answered once the report is released."
            )
        recommendation.status = status
        recommendation.response = response
        recommendation.responded_by_id = _uid(principal)
        recommendation.responded_at = timezone.now()
        recommendation.save()
        _audit(
            "ia.report.recommendation_responded",
            report,
            principal,
            {
                "recommendation_id": recommendation.id,
                "response_status": status,
                "note": response or None,
            },
        )
    _notify(
        EVENT_RECOMMENDATION_RESPONDED,
        report,
        [report.author_id],
        title=f"Recommendation {RECOMMENDATION_LABELS[status].lower()}: {report.title}",
        body=response or recommendation.text[:300],
    )
    return recommendation


def brief_for(principal, release_id: str):
    """(release, team action, may_record) for a school brief the principal may
    open: its account owner (the action's recipient), Impact Assessment or
    the Country Director of the report's country, or Admin."""
    from apps.planning.action_models import TeamAction

    release = (
        ImpactReportRelease.objects.select_related("report", "school")
        .filter(id=release_id, audience=ReleaseAudience.SCHOOL)
        .first()
    )
    if release is None:
        return None, None, False
    action = (
        TeamAction.objects.filter(condition_key=brief_condition_key(release.id))
        .order_by("-created_at")
        .first()
    )
    me = _uid(principal)
    country = release.report.country
    recipient = action is not None and action.recipient_id == me
    allowed = (
        recipient
        or _role(principal) == ADMIN
        or (_role(principal) in (IA, CD) and _profile_country(principal) == country)
    )
    if not allowed:
        return None, None, False
    from apps.planning.action_models import ACTIVE_STATES

    return release, action, recipient and action.state in ACTIVE_STATES


def record_brief_shared(principal, release_id: str, data) -> None:
    """The account owner records that the brief was shared and what the
    school said; the TeamAction closes with that as its reason."""
    from apps.activities.models import Activity
    from apps.planning.action_service import ActionError, resolve_manually

    release, action, may_record = brief_for(principal, release_id)
    if release is None:
        raise NotFoundError("That school brief is not yours to open.")
    if not may_record:
        raise Forbidden("The school's account owner records that the brief was shared.")
    shared_on = _date(data, "shared_on", label="Date shared")
    if shared_on is None:
        raise BadRequest("Say when the findings were shared.")
    if shared_on > timezone.localdate():
        raise BadRequest("The date shared cannot be in the future.")
    response = _text(
        data,
        "school_response",
        label="What the school said",
        required=True,
        max_length=2000,
    )
    visit_id = str(data.get("visit") or "").strip()
    if (
        visit_id
        and not Activity.objects.filter(
            id=visit_id, school_id=release.school_id, deleted_at__isnull=True
        ).exists()
    ):
        raise BadRequest("Choose a visit to this school.")
    reason = f"Findings shared on {shared_on.isoformat()}"
    if visit_id:
        reason += f" during visit {visit_id}"
    reason += f". School response: {response}"
    try:
        resolve_manually(action, principal, reason)
    except ActionError as exc:
        raise BadRequest(str(exc)) from None
    _audit(
        "ia.report.school_brief_shared",
        release.report,
        principal,
        {
            "release_id": release.id,
            "school_id": release.school_id,
            "shared_on": shared_on.isoformat(),
            "visit_id": visit_id or None,
            "team_action_id": action.id,
        },
    )
    _resolve(EVENT_SCHOOL_BRIEF, release, context_type="ImpactReportRelease")


# ── Notifications ────────────────────────────────────────────────────────────


def reviewer_ids(report) -> list[str]:
    """Who reviews: the country's other IA officers, else its Country Director."""
    from apps.impact.review import ia_officer_ids
    from apps.notifications.services import role_recipients

    officers = [
        str(i) for i in ia_officer_ids(report.country) if str(i) != report.author_id
    ]
    if officers:
        return officers
    return [str(u.id) for u in role_recipients(CD, country=report.country)]


def _notify(
    event_type,
    report,
    recipients,
    *,
    title,
    body,
    priority="normal",
    context_type="ImpactReport",
    context_id=None,
) -> None:
    try:
        from apps.notifications.services import WorkflowNotificationService

        recipients = [r for r in dict.fromkeys(recipients) if r]
        if not recipients:
            return
        WorkflowNotificationService.trigger(
            event_type=event_type,
            category="ia",
            priority=priority,
            title=title[:200],
            body=str(body or "")[:500],
            context_type=context_type,
            context_id=str(context_id or report.id),
            recipients=recipients,
        )
    except Exception:  # noqa: BLE001 - a notice never undoes the transition
        pass


def _notify_reviewers(report) -> None:
    _notify(
        EVENT_REVIEW_REQUESTED,
        report,
        reviewer_ids(report),
        title=f"Impact report to review: {report.title}",
        body=f"{report.country} · {period_label(report)} · version {report.version}",
    )


def _resolve(event_type, record, *, context_type="ImpactReport") -> None:
    try:
        from apps.notifications.services import resolve_condition

        resolve_condition(event_type, context_type, str(record.id))
    except Exception:  # noqa: BLE001 - housekeeping only
        pass


# ── Reads ────────────────────────────────────────────────────────────────────


def register(principal, *, status: str = "", fy: str = ""):
    qs = visible_reports(principal)
    if status in STATUS_LABELS:
        qs = qs.filter(status=status)
    if fy:
        qs = qs.filter(fy=fy)
    return qs.select_related("project").order_by("-updated_at", "-created_at")


def decorate(principal, reports) -> list[dict]:
    """Register rows in bulk: names in one query; the review right costs one
    officer lookup per country, cached here."""
    from apps.accounts.models import User
    from apps.impact.review import ia_officer_ids

    reports = list(reports)
    ids = {r.author_id for r in reports} | {
        r.reviewed_by_id for r in reports if r.reviewed_by_id
    }
    names = (
        dict(User.objects.filter(id__in=ids).values_list("id", "name")) if ids else {}
    )
    me = _uid(principal)
    role = _role(principal)
    my_country = _profile_country(principal) if role in (IA, CD) else ""
    officers: dict[str, list[str]] = {}

    def can_review(report) -> bool:
        if report.status != SUBMITTED or report.author_id == me:
            return False
        if my_country != report.country:
            return False
        if role == IA:
            return True
        if role == CD:
            if report.country not in officers:
                officers[report.country] = [
                    str(i) for i in ia_officer_ids(report.country)
                ]
            return not [i for i in officers[report.country] if i != report.author_id]
        return False

    out = []
    for r in reports:
        mine = r.author_id == me and role == IA
        out.append(
            {
                "report": r,
                "author": names.get(r.author_id, "Unknown"),
                "reviewer": names.get(r.reviewed_by_id, "") if r.reviewed_by_id else "",
                "status_label": STATUS_LABELS.get(r.status, r.status),
                "status_tone": STATUS_TONES.get(r.status, "neutral"),
                "period": period_label(r),
                "programmes": ", ".join(
                    PROGRAMME_LABELS.get(a, a) for a in r.programme_areas or []
                )
                or "Across programmes",
                "is_mine": mine,
                "can_edit": mine and r.status == DRAFT,
                "can_review": can_review(r),
                "can_release": r.status == REVIEWED and r.reviewed_by_id == me,
            }
        )
    return out


def counts(principal, fy: str) -> dict:
    """The register's tile counts: three queries."""
    reports = visible_reports(principal)
    out = reports.aggregate(
        submitted=Count("id", filter=Q(status=SUBMITTED)),
        returned=Count("id", filter=Q(status=RETURNED)),
        drafts=Count("id", filter=Q(status=DRAFT)),
        released_this_year=Count("id", filter=Q(status=RELEASED, fy=fy)),
    )
    today = timezone.localdate()
    out.update(
        ImpactReportRecommendation.objects.filter(
            report__in=reports, report__status=RELEASED
        ).aggregate(
            awaiting_response=Count(
                "id", filter=Q(status=RecommendationStatus.PROPOSED)
            ),
            overdue=Count(
                "id", filter=Q(status__in=OPEN_RECOMMENDATIONS, due_date__lt=today)
            ),
        )
    )
    out["donor_pending"] = ImpactReportRelease.objects.filter(
        report__in=reports,
        audience=ReleaseAudience.DONOR,
        status=ReleaseStatus.PENDING_APPROVAL,
    ).count()
    return out


def detail_rights(principal, report) -> dict:
    """What `principal` may do on one report (the detail page)."""
    from apps.impact.review import reviewer_basis

    me = _uid(principal)
    role = _role(principal)
    author = report.author_id == me and role == IA
    reviewer = report.reviewed_by_id == me
    country_cd = _is_country_cd(principal, report.country)
    correctable = report.status in (RETURNED, REVIEWED, RELEASED) or (
        report.status == WITHDRAWN and report.submitted_at is not None
    )
    return {
        "is_author": author,
        "can_edit": author and report.status == DRAFT,
        "can_withdraw": author and report.status in (DRAFT, SUBMITTED),
        "can_review": report.status == SUBMITTED
        and bool(
            reviewer_basis(
                principal, author_id=report.author_id, country=report.country
            )
        ),
        "can_correct": correctable
        and _is_country_ia(principal, report.country)
        and open_correction(report) is None,
        "can_release_leadership": report.status == REVIEWED and reviewer,
        "can_release_schools": report.status == RELEASED and (reviewer or country_cd),
        "can_request_donor": report.status == RELEASED and (reviewer or country_cd),
        "can_respond": report.status == RELEASED and country_cd,
        "can_download_annex": report.status != DRAFT
        and not is_summary_reader(principal)
        and role in (IA, CD, ADMIN),
        "summary_only": is_summary_reader(principal),
        "may_decide_donor": role == RVP and _rvp_covers(principal, report.country),
    }


def history(report) -> list[dict]:
    """The report's audit trail, newest first, with names in one query."""
    from apps.accounts.models import User
    from apps.audit.models import AuditLog

    rows = list(
        AuditLog.objects.filter(subject_kind="ImpactReport", subject_id=report.id)
        .order_by("-created_at")
        .values("action", "actor_id", "actor_role", "created_at", "reason", "payload")[
            :50
        ]
    )
    names = dict(
        User.objects.filter(
            id__in={r["actor_id"] for r in rows if r["actor_id"]}
        ).values_list("id", "name")
    )
    for row in rows:
        row["actor"] = names.get(row["actor_id"], "System")
        row["label"] = ACTION_LABELS.get(row["action"], row["action"])
        payload = row.get("payload") or {}
        if payload.get("audience"):
            row["label"] += (
                f" · {AUDIENCE_LABELS.get(payload['audience'], payload['audience'])}"
            )
    return rows


ACTION_LABELS = {
    "ia.report.started": "Draft started",
    "ia.report.updated": "Draft edited",
    "ia.report.recommendation_added": "Recommendation added",
    "ia.report.recommendation_removed": "Recommendation removed",
    "ia.report.submitted": "Submitted for review (evidence frozen)",
    "ia.report.withdrawn": "Withdrawn",
    "ia.report.reviewed": "Reviewed",
    "ia.report.returned": "Returned to the author",
    "ia.report.correction_started": "Correction started as a new version",
    "ia.report.superseded": "Superseded by a newer version",
    "ia.report.released": "Released",
    "ia.report.donor_requested": "Donor version requested",
    "ia.report.donor_released": "Donor version approved and released",
    "ia.report.donor_declined": "Donor version declined",
    "ia.report.recommendation_responded": "Country Director responded to a recommendation",
    "ia.report.school_brief_shared": "School brief shared with the school",
    "ia.report.annex_downloaded": "Evidence annex downloaded",
    "ia.report.release_downloaded": "Released version downloaded",
}


def releases_for(report) -> list[dict]:
    """The report's releases with their brief actions: three queries."""
    from apps.accounts.models import User
    from apps.planning.action_models import TeamAction

    releases = list(
        report.releases.select_related("school").order_by("audience", "created_at")
    )
    actions = {
        a.condition_key: a
        for a in TeamAction.objects.filter(
            condition_key__in=[brief_condition_key(r.id) for r in releases]
        ).order_by("created_at")
    }
    ids = {
        i
        for r in releases
        for i in (r.requested_by_id, r.approved_by_id, r.released_by_id)
        if i
    } | {a.recipient_id for a in actions.values()}
    names = (
        dict(User.objects.filter(id__in=ids).values_list("id", "name")) if ids else {}
    )
    out = []
    for r in releases:
        action = actions.get(brief_condition_key(r.id))
        shared = ""
        if action is not None:
            if action.state == "resolved":
                shared = action.manual_resolution_reason
            else:
                shared = f"Waiting for {names.get(action.recipient_id, 'the account owner')} to share it"
        out.append(
            {
                "release": r,
                "audience_label": AUDIENCE_LABELS.get(r.audience, r.audience),
                "status_label": RELEASE_STATUS_LABELS.get(r.status, r.status),
                "status_tone": RELEASE_TONES.get(r.status, "neutral"),
                "requested_by": names.get(r.requested_by_id, ""),
                "approved_by": names.get(r.approved_by_id, ""),
                "released_by": names.get(r.released_by_id, ""),
                "shared": shared,
            }
        )
    return out


# ── Downloads ────────────────────────────────────────────────────────────────


def csv_value(value):
    """A spreadsheet-safe cell: text that a spreadsheet would read as a
    formula gets a leading apostrophe; numbers stay numbers."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (int, float)):
        return value
    text = str(value)
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(
        ("\t", "\r", "\n")
    ):
        return "'" + text
    return text


def write_csv(response, rows) -> None:
    writer = csv.writer(response)
    for row in rows:
        writer.writerow([csv_value(v) for v in row])


def annex_rows(report, *, generated_by: str, generated_role: str) -> list[list]:
    """The evidence annex of a submitted report: the frozen snapshot, never
    live data, with who generated the file and the snapshot's hash."""
    snapshot = report.evidence_snapshot or {}
    cohort = snapshot.get("cohort") or {}
    portfolio = snapshot.get("portfolio") or {}
    rows: list[list] = [
        ["Impact Assessment evidence annex", f"Version {report.version}"],
        ["Report", report.title],
        ["Status", STATUS_LABELS.get(report.status, report.status)],
        ["Country", report.country],
        ["Period", period_label(report)],
        ["Evidence frozen at", snapshot.get("generated_at", "")],
        ["Snapshot sha256", report.snapshot_hash],
        ["Generated by", generated_by],
        ["Generated by role", generated_role],
        ["Generated at", timezone.now().isoformat()],
        ["Counting unit", "Project-school enrolments, not unique schools"],
        ["Limitation", snapshot.get("limitation", "")],
        [],
        ["Project cohort", "Value"],
    ]
    rows += [[key, cohort.get(key)] for key in cohort]
    if portfolio:
        rows += [
            [],
            [
                f"School change FY{portfolio.get('prev_fy')} to FY{portfolio.get('fy')}",
                "Schools measured",
                "Improved %",
                "Declined %",
                "Median change",
                "Evidence",
            ],
        ]
        rows += [
            [
                row.get("name"),
                row.get("n"),
                row.get("improved_pct"),
                row.get("declined_pct"),
                row.get("median_change"),
                (row.get("grade") or {}).get("label", ""),
            ]
            for row in portfolio.get("rows") or []
        ]
    rows += [[], ["Mapping version", "SSA domain", "Enrolments"]]
    rows += [
        [m.get("mapping_version"), m.get("intervention"), m.get("enrolments")]
        for m in snapshot.get("mapping_versions") or []
    ]
    rows += [
        [],
        [
            "Verified loan impact conclusions",
            len((snapshot.get("lending") or {}).get("verified_ids") or []),
        ],
    ]
    rows += [
        ["Loan conclusion id", ref]
        for ref in (snapshot.get("lending") or {}).get("verified_ids") or []
    ]
    rows += [[], list(ROW_KEYS)]
    rows += [[row.get(key) for key in ROW_KEYS] for row in snapshot.get("rows") or []]
    return rows


def release_rows(release) -> list[list]:
    """A donor or school version flattened to Section / Measure / Value rows.
    The leadership version is the whole snapshot: its file is the annex."""
    payload = release.rendered_payload or {}
    rows: list[list] = [
        ["Impact report", AUDIENCE_LABELS.get(release.audience, release.audience)],
        ["Released at", release.released_at.isoformat() if release.released_at else ""],
        ["Report version", release.report.version],
        ["Snapshot sha256", release.report.snapshot_hash],
        [],
        ["Section", "Measure", "Value"],
    ]

    def walk(section, value):
        if isinstance(value, dict):
            for key, inner in value.items():
                walk(f"{section}.{key}" if section else key, inner)
        elif isinstance(value, list):
            for index, inner in enumerate(value, start=1):
                walk(f"{section}[{index}]", inner)
        else:
            head, _, measure = section.rpartition(".")
            rows.append([head or section, measure or section, value])

    walk("", payload)
    return rows


def audit_download(action: str, report, principal, payload: dict | None = None) -> None:
    _audit(action, report, principal, payload)


# ── The dashboard's Reports view ─────────────────────────────────────────────


def _metric(label, value, helper, tone="info", **extra):
    from apps.core.metrics import render_precomputed_metric_for_source

    return render_precomputed_metric_for_source(
        "apps.impact.reports:_metric", label, value, helper=helper, tone=tone, **extra
    )


def register_tiles(principal, fy: str, c: dict | None = None) -> list[dict]:
    """The register's and the dashboard Reports view's tiles."""
    c = c or counts(principal, fy)
    return [
        _metric(
            "Impact Reports Awaiting Review",
            c["submitted"],
            "reviewed by someone other than the author",
            "warning" if c["submitted"] else "info",
            drilldown_url="/ia/impact-reports/?status=submitted",
        ),
        _metric(
            "Impact Reports Returned for Correction",
            c["returned"],
            "a correction is a new version",
            "danger" if c["returned"] else "info",
            drilldown_url="/ia/impact-reports/?status=returned",
        ),
        _metric(
            "Impact Reports Released This Year",
            c["released_this_year"],
            f"FY{fy}, released to country leadership",
            drilldown_url=f"/ia/impact-reports/?status=released&fy={fy}",
        ),
        _metric(
            "Report Recommendations Awaiting a Response",
            c["awaiting_response"],
            f"{c['overdue']} overdue" if c["overdue"] else "from released reports",
            "warning" if c["awaiting_response"] or c["overdue"] else "info",
        ),
        _metric(
            "Donor Versions Awaiting RVP Approval",
            c["donor_pending"],
            "approved by an RVP, never the requester",
            "warning" if c["donor_pending"] else "info",
        ),
    ]


def dashboard_reports_context(request) -> dict:
    """The IA dashboard's Reports view (apps.frontend.views.ia_views
    IA_REPORTS_CONTEXT_BUILDER): tiles, the latest reports and the live
    evidence annex's period options."""
    from apps.core.fy import get_operational_fy

    principal = request.user
    fy = get_operational_fy()
    reports = decorate(principal, register(principal)[:8])
    return {
        "ia_reports": {
            "fy": fy,
            "tiles": register_tiles(principal, fy),
            "rows": reports,
            "may_author": may_author(principal),
            "fy_options": fy_choices(),
        }
    }


# ── The Country Director's dashboard section and export ─────────────────────


def cd_impact_findings(principal) -> dict:
    """Country Director dashboard "Impact findings": the latest leadership
    release, reports waiting for the CD's acknowledgement, and recommendations
    awaiting a response or overdue. Five queries at most."""
    from apps.impact.review import ia_officer_ids

    country = reader_country(principal)
    today = timezone.localdate()
    reports = visible_reports(principal)
    latest = (
        ImpactReportRelease.objects.filter(
            report__in=reports,
            audience=ReleaseAudience.LEADERSHIP,
            status=ReleaseStatus.RELEASED,
        )
        .select_related("report")
        .order_by("-released_at")
        .first()
    )
    latest_out = None
    if latest is not None:
        cohort = ((latest.rendered_payload or {}).get("snapshot") or {}).get(
            "cohort"
        ) or {}
        portfolio = ((latest.rendered_payload or {}).get("snapshot") or {}).get(
            "portfolio"
        ) or {}
        latest_out = {
            "report_id": latest.report_id,
            "title": latest.report.title,
            "version": latest.report.version,
            "period": period_label(latest.report),
            "released_at": latest.released_at,
            "measured": cohort.get("measured"),
            "total": cohort.get("total"),
            "portfolio_measured": portfolio.get("measured"),
            "portfolio_in_scope": portfolio.get("schools_in_scope"),
            "superseded": latest.report.status == SUPERSEDED,
        }
    submitted = list(reports.filter(status=SUBMITTED).values("id", "author_id"))
    officers = (
        [str(i) for i in ia_officer_ids(country)] if submitted and country else []
    )
    awaiting_ack = [
        r for r in submitted if not [i for i in officers if i != r["author_id"]]
    ]
    recommendations = list(
        ImpactReportRecommendation.objects.filter(
            report__in=reports, report__status=RELEASED
        )
        .filter(
            Q(status=RecommendationStatus.PROPOSED)
            | Q(status__in=OPEN_RECOMMENDATIONS, due_date__lt=today)
        )
        .select_related("report")
        .order_by("due_date", "created_at")[:50]
    )
    awaiting = [r for r in recommendations if r.status == RecommendationStatus.PROPOSED]
    overdue = [r for r in recommendations if r.due_date and r.due_date < today]
    from apps.impact.findings import ACTION_OWNER_LABELS

    rows = [
        {
            "report_id": r.report_id,
            "report": r.report.title,
            "text": r.text,
            "owner": ACTION_OWNER_LABELS.get(r.owner_role, r.owner_role),
            "due": r.due_date,
            "overdue": bool(r.due_date and r.due_date < today),
            "status_label": RECOMMENDATION_LABELS.get(r.status, r.status),
            "status_tone": "danger"
            if r.due_date and r.due_date < today
            else RECOMMENDATION_TONES.get(r.status, "neutral"),
        }
        for r in recommendations[:5]
    ]
    return {
        "latest": latest_out,
        "awaiting_ack": len(awaiting_ack),
        "awaiting_ack_url": (
            f"/ia/impact-reports/{awaiting_ack[0]['id']}/"
            if len(awaiting_ack) == 1
            else "/ia/impact-reports/?status=submitted"
        ),
        "awaiting_response": len(awaiting),
        "overdue": len(overdue),
        "rows": rows,
        "tiles": [
            _metric(
                "Latest Released Impact Report",
                latest_out["period"] if latest_out else "None released",
                (
                    f"{latest_out['measured']} of {latest_out['total']} enrolments measured"
                    if latest_out and latest_out["total"]
                    else "released to country leadership"
                ),
                "info" if latest_out else "neutral",
                drilldown_url=(
                    f"/ia/impact-reports/{latest_out['report_id']}/"
                    if latest_out
                    else ""
                ),
            ),
            _metric(
                "Impact Reports Awaiting Your Acknowledgement",
                len(awaiting_ack),
                "the country has no second IA officer to review them",
                "warning" if awaiting_ack else "info",
            ),
            _metric(
                "Recommendations Awaiting Your Response",
                len(awaiting),
                "from released impact reports",
                "warning" if awaiting else "info",
            ),
            _metric(
                "Report Recommendations Overdue",
                len(overdue),
                "past their due date and not done",
                "danger" if overdue else "info",
            ),
        ],
    }


IMPACT_EXPORT_HEADER = ["Section", "Measure", "Value", "Basis"]


def impact_export_rows(principal) -> list[list]:
    """The Country Director's "impact" export: the latest leadership release's
    frozen snapshot, so the board file matches what was reviewed."""
    release = (
        ImpactReportRelease.objects.filter(
            report__in=visible_reports(principal),
            audience=ReleaseAudience.LEADERSHIP,
            status=ReleaseStatus.RELEASED,
        )
        .select_related("report")
        .order_by("-released_at")
        .first()
    )
    if release is None:
        country = reader_country(principal) or "your country"
        return [
            ["Report", "Released impact report", f"None released for {country}", ""]
        ]
    report = release.report
    payload = release.rendered_payload or {}
    snapshot = payload.get("snapshot") or {}
    basis = f"Frozen at submission, sha256 {report.snapshot_hash[:12]}"
    rows = [
        ["Report", "Title", report.title, f"Version {report.version}"],
        ["Report", "Period", period_label(report), report.country],
        [
            "Report",
            "Released at",
            release.released_at.date().isoformat() if release.released_at else "",
            "Released to country leadership",
        ],
    ]
    for key, value in (snapshot.get("cohort") or {}).items():
        rows.append(["Project cohort", key, value, basis])
    portfolio = snapshot.get("portfolio") or {}
    for row in portfolio.get("rows") or []:
        rows.append(
            [
                "School change",
                row.get("name"),
                row.get("n"),
                f"schools measured · {(row.get('grade') or {}).get('label', '')}",
            ]
        )
    for rec in payload.get("recommendations") or []:
        rows.append(
            [
                "Recommendation",
                rec.get("owner_label"),
                rec.get("text"),
                rec.get("due_date"),
            ]
        )
    return [[csv_value(v) for v in row] for row in rows]
