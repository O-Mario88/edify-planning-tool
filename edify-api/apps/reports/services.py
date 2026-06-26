"""Reports service — saved/generated reports."""
from __future__ import annotations

from apps.accounts.models import Report
from apps.core.fy import get_operational_fy
from apps.core.scoping import resolve_user_scope
from apps.schools.models import School


def list_reports(principal) -> list[dict]:
    return [_serialize(r) for r in Report.objects.all().order_by("-created_at")]


def get_one(report_id: str, principal) -> dict:
    from apps.core.exceptions import NotFoundError

    r = Report.objects.filter(id=report_id).first()
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
        "byType": {t: schools.filter(school_type=t).count() for t in ("client", "core", "champion")},
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
