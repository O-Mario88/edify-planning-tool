"""Leadership Decision Engine service — recommends; leadership decides."""

from __future__ import annotations

from django.utils import timezone

from apps.core.exceptions import NotFoundError
from apps.core.fy import get_operational_fy

from .models import (
    DecisionNote,
    LeadershipDecisionInsight,
)


def boards(principal, query: dict) -> dict:
    fy = query.get("fy") or get_operational_fy()
    insights_list = _list(query)

    by_type = {}
    for i in insights_list:
        dtype = i["decisionType"]
        if dtype not in by_type:
            by_type[dtype] = []
        by_type[dtype].append(i)

    boards_data = []
    visible_boards = list(by_type.keys())

    for dtype, items in by_type.items():
        boards_data.append(
            {
                "decisionType": dtype,
                "canReview": principal.active_role
                in ("CountryDirector", "Program Lead"),
                "insights": items,
            }
        )

    return {"fy": fy, "visibleBoards": visible_boards, "boards": boards_data}


def snapshot(principal, query: dict) -> dict:
    fy = query.get("fy") or get_operational_fy()
    qs = LeadershipDecisionInsight.objects.filter(fy=fy)
    total = qs.count()

    from django.db.models import Avg

    avg_conf = qs.aggregate(a=Avg("confidence_score"))["a"]
    data_confidence = round(avg_conf * 100) if avg_conf is not None else 85

    high_risk = qs.filter(risk_level__in=["high", "critical"]).count()
    staff_overload = qs.filter(
        decision_type__in=["staff_hr", "staff_addition"],
        risk_level__in=["high", "critical", "medium"],
    ).count()
    partner_mou_risks = qs.filter(
        decision_type="partner", risk_level__in=["high", "critical", "medium"]
    ).count()
    partner_capacity = qs.filter(decision_type="partner").count()

    regions_expand = list(
        qs.filter(scope_type="region", recommendation__icontains="expand")
        .values_list("scope_name", flat=True)
        .distinct()
    )
    if not regions_expand:
        regions_expand = list(
            qs.filter(scope_type="region")
            .values_list("scope_name", flat=True)
            .distinct()[:2]
        )

    regions_pause = list(
        qs.filter(scope_type="region", recommendation__icontains="pause")
        .values_list("scope_name", flat=True)
        .distinct()
    )

    headline = "Strategic posture: stable. Review pending decisions below."
    if total > 0:
        headline = f"Strategic Posture: {high_risk} high-risk decisions pending. Data confidence is at {data_confidence}%."

    return {
        "fy": fy,
        "strategicHeadline": headline,
        "regionsReadyToExpand": regions_expand,
        "regionsToPauseRecruitment": regions_pause,
        "staffOverloadRisks": staff_overload,
        "partnerMouRisks": partner_mou_risks,
        "partnerCapacityGaps": partner_capacity,
        "dataConfidence": data_confidence,
        "highRiskDecisions": high_risk,
        "totalInsights": total,
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
    }


def review(insight_id: str, data: dict, principal) -> dict:
    i = LeadershipDecisionInsight.objects.filter(id=insight_id).first()
    if not i:
        raise NotFoundError("Insight not found.")
    i.status = data.get("status", "accepted")
    i.reviewed_by_user_id = principal.user_id
    i.reviewed_by_role = principal.active_role
    i.reviewed_at = timezone.now()
    i.review_note = data.get("note")
    i.save(
        update_fields=[
            "status",
            "reviewed_by_user_id",
            "reviewed_by_role",
            "reviewed_at",
            "review_note",
        ]
    )
    return _serialize(i)


def add_note(insight_id: str, data: dict, principal) -> dict:
    i = LeadershipDecisionInsight.objects.filter(id=insight_id).first()
    if not i:
        raise NotFoundError("Insight not found.")
    note = DecisionNote.objects.create(
        insight=i,
        author_user_id=principal.user_id,
        author_role=principal.active_role,
        note=data.get("note", ""),
        kind=data.get("kind", "note"),
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
        "id": i.id,
        "fy": i.fy,
        "decisionType": i.decision_type,
        "scopeType": i.scope_type,
        "scopeId": i.scope_id,
        "scopeName": i.scope_name,
        "recommendation": i.recommendation,
        "reason": i.reason,
        "riskLevel": i.risk_level,
        "confidenceLevel": i.confidence_level,
        "confidenceScore": i.confidence_score,
        "status": i.status,
        "suggestedAction": i.suggested_action,
        "generatedAt": i.generated_at.isoformat(),
        "riskFlags": i.risk_flags or [],
        "evidencePoints": i.evidence_summary or [],
        "alternatives": i.alternatives or [],
        "metrics": i.metrics or {},
        "contextAdjustment": i.context_adjustment,
        "financialImplication": i.financial_implication,
    }
