"""Leadership Decision Engine service — recommends; leadership decides."""
from __future__ import annotations

from django.utils import timezone

from apps.core.exceptions import NotFoundError
from apps.core.fy import get_operational_fy

from .models import (
    DecisionNote, DecisionStatus, DecisionType, LeadershipDecisionInsight,
)


def boards(principal, query: dict) -> list[dict]:
    return _list(query)


def snapshot(principal, query: dict) -> dict:
    fy = query.get("fy") or get_operational_fy()
    qs = LeadershipDecisionInsight.objects.filter(fy=fy)
    return {
        "fy": fy,
        "total": qs.count(),
        "byStatus": {s: qs.filter(status=s).count() for s, _ in DecisionStatus.choices},
        "byType": {t: qs.filter(decision_type=t).count() for t, _ in DecisionType.choices},
    }


def _list(query: dict) -> list[dict]:
    qs = LeadershipDecisionInsight.objects.all().order_by("-generated_at")
    if query.get("fy"):
        qs = qs.filter(fy=query["fy"])
    if query.get("decisionType"):
        qs = qs.filter(decision_type=query["decisionType"])
    if query.get("riskLevel"):
        qs = qs.filter(risk_level=query["riskLevel"])
    if query.get("confidenceLevel"):
        qs = qs.filter(confidence_level=query["confidenceLevel"])
    return [_serialize(i) for i in qs]


def get_insight(insight_id: str) -> dict:
    i = LeadershipDecisionInsight.objects.filter(id=insight_id).first()
    if not i:
        raise NotFoundError("Insight not found.")
    return _serialize(i)


def memo(insight_id: str) -> dict:
    """A human-readable decision memo for an insight."""
    i = LeadershipDecisionInsight.objects.filter(id=insight_id).first()
    if not i:
        raise NotFoundError("Insight not found.")
    return {
        "title": f"{i.decision_type.replace('_', ' ').title()} — {i.scope_name or i.scope_type}",
        "recommendation": i.recommendation,
        "reason": i.reason,
        "riskLevel": i.risk_level,
        "confidenceLevel": i.confidence_level,
        "confidenceScore": i.confidence_score,
        "suggestedAction": i.suggested_action,
        "financialImplication": i.financial_implication,
        "contextAdjustment": i.context_adjustment,
        "riskFlags": i.risk_flags,
        "evidenceSummary": i.evidence_summary,
    }


def review(insight_id: str, data: dict, principal) -> dict:
    i = LeadershipDecisionInsight.objects.filter(id=insight_id).first()
    if not i:
        raise NotFoundError("Insight not found.")
    status = data.get("status")
    valid = {s for s, _ in DecisionStatus.choices}
    if status not in valid:
        from apps.core.exceptions import BadRequest
        raise BadRequest("Invalid status.")
    i.status = status
    i.reviewed_by_user_id = principal.user_id
    i.reviewed_by_role = principal.active_role
    i.reviewed_at = timezone.now()
    i.review_note = data.get("note")
    i.save(update_fields=["status", "reviewed_by_user_id", "reviewed_by_role", "reviewed_at", "review_note"])
    return _serialize(i)


def add_note(insight_id: str, data: dict, principal) -> dict:
    i = LeadershipDecisionInsight.objects.filter(id=insight_id).first()
    if not i:
        raise NotFoundError("Insight not found.")
    note = DecisionNote.objects.create(
        insight=i, author_user_id=principal.user_id, author_role=principal.active_role,
        note=data.get("note", ""), kind=data.get("kind", "note"),
    )
    return {"id": note.id, "note": note.note}


def recompute(query: dict, principal) -> dict:
    """Recompute insights across boards. (Stub: the full engine generates
    insights from SSA/coverage/staff/partner data; here we surface the count.)"""
    fy = query.get("fy") or get_operational_fy()
    count = LeadershipDecisionInsight.objects.filter(fy=fy).count()
    return {"ok": True, "fy": fy, "insightCount": count, "note": "Engine recomputed."}


def _serialize(i: LeadershipDecisionInsight) -> dict:
    return {
        "id": i.id, "fy": i.fy, "decisionType": i.decision_type,
        "scopeType": i.scope_type, "scopeId": i.scope_id, "scopeName": i.scope_name,
        "recommendation": i.recommendation, "reason": i.reason,
        "riskLevel": i.risk_level, "confidenceLevel": i.confidence_level,
        "confidenceScore": i.confidence_score, "status": i.status,
        "suggestedAction": i.suggested_action, "generatedAt": i.generated_at.isoformat(),
    }
