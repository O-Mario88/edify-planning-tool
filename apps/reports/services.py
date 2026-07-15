"""Reports service — saved/generated reports."""

from __future__ import annotations

from apps.accounts.models import Report
from apps.core.fy import get_operational_fy
from apps.core.scoping import resolve_user_scope
from apps.schools.models import School


def _scoped_reports(principal):
    """A report has no stored school/team scope of its own (only a coarse
    "country"/"scoped" label plus its generator's summary_json) — so the only
    honest scoping rule available is: country-scope roles (CD/RVP/Admin) see
    every report, everyone else sees only the reports they personally
    generated. Without this, list_reports()/get_one() returned every report
    ever generated to any role holding analytics.view — which is nearly every
    role in the app (CCEO, PL, IA, Accountant, PC included) — leaking other
    teams'/other roles' report contents country-wide."""
    scope = resolve_user_scope(principal)
    qs = Report.objects.all()
    if not scope.country_scope:
        qs = qs.filter(created_by_user_id=principal.user_id)
    return qs


def list_reports(principal) -> list[dict]:
    return [_serialize(r) for r in _scoped_reports(principal).order_by("-created_at")]


def get_one(report_id: str, principal) -> dict:
    from apps.core.exceptions import NotFoundError

    r = _scoped_reports(principal).filter(id=report_id).first()
    if not r:
        raise NotFoundError("Report not found.")
    return _serialize(r)


def generate(data: dict, principal) -> dict:
    report_type = data.get("type", "program_summary")
    fy = data.get("fy") or get_operational_fy()
    scope = resolve_user_scope(principal)
    schools = School.objects.filter(deleted_at__isnull=True)
    if not scope.country_scope and scope.school_ids:
        schools = schools.filter(id__in=scope.school_ids)
    summary = {
        "fy": fy,
        "schoolsTotal": schools.count(),
        "coreSchools": schools.filter(school_type="core").count(),
        "ssaDone": schools.filter(current_fy_ssa_status="done").count(),
        "byType": {
            t: schools.filter(school_type=t).count()
            for t in ("client", "core", "champion")
        },
    }
    r = Report.objects.create(
        title=f"{report_type} — FY{fy}",
        type=report_type,
        fy=fy,
        scope="country" if scope.country_scope else "scoped",
        created_by_user_id=principal.user_id,
        summary_json=summary,
    )
    return _serialize(r)


def _serialize(r: Report) -> dict:
    return {
        "id": r.id,
        "title": r.title,
        "type": r.type,
        "fy": r.fy,
        "scope": r.scope,
        "summaryJson": r.summary_json,
        "createdAt": r.created_at.isoformat(),
    }
