"""Budget Intelligence service — the financial decision engine."""
from __future__ import annotations

from django.utils import timezone

from apps.core.exceptions import BadRequest, NotFoundError
from apps.core.fy import get_operational_fy
from apps.leadership.models import DecisionStatus

from .models import BudgetIntelligenceInsight, FinanceDecisionNote


def boards(principal, query: dict) -> dict:
    fy = query.get("fy") or get_operational_fy()
    qs = BudgetIntelligenceInsight.objects.all().order_by("-generated_at")
    if query.get("fy"):
        qs = qs.filter(fy=query["fy"])
    if query.get("insightType"):
        qs = qs.filter(insight_type=query["insightType"])
    if query.get("impactYield"):
        qs = qs.filter(impact_yield=query["impactYield"])
    return {
        "fy": fy,
        "insights": [_serialize(i) for i in qs]
    }


def snapshot(principal, query: dict) -> dict:
    from django.db.models import Sum
    fy = query.get("fy") or get_operational_fy()
    qs = BudgetIntelligenceInsight.objects.filter(fy=fy, deleted_at__isnull=True)
    total = qs.count()
    low_yield = qs.filter(impact_yield__in=["low", "weak"]).count()
    high_yield = qs.filter(impact_yield__in=["high", "healthy"]).count()
    amount_at_risk = qs.aggregate(t=Sum("amount_affected"))["t"] or 0.0
    
    headline = "Budget posture is healthy. No critical financial risks detected."
    if total > 0:
        headline = f"Strategic Posture: {total} financial insights generated. {low_yield} low-yield items detected."
        
    return {
        "fy": fy,
        "totalInsights": total,
        "lowYieldCount": low_yield,
        "highYieldCount": high_yield,
        "amountAtRisk": amount_at_risk,
        "headline": headline,
    }


def get_insight(insight_id: str) -> dict:
    i = BudgetIntelligenceInsight.objects.filter(id=insight_id).first()
    if not i:
        raise NotFoundError("Insight not found.")
    return _serialize(i)


def memo(insight_id: str) -> dict:
    i = BudgetIntelligenceInsight.objects.filter(id=insight_id).first()
    if not i:
        raise NotFoundError("Insight not found.")
    return {
        "title": f"{i.insight_type.title()} — {i.scope_name or i.scope_type}",
        "recommendation": i.recommendation, "reason": i.reason,
        "riskLevel": i.risk_level, "impactYield": i.impact_yield,
        "confidenceLevel": i.confidence_level, "confidenceScore": i.confidence_score,
        "amountAffected": i.amount_affected, "financialImplication": i.financial_implication,
        "suggestedAction": i.suggested_action, "riskFlags": i.risk_flags,
    }


def review(insight_id: str, data: dict, principal) -> dict:
    i = BudgetIntelligenceInsight.objects.filter(id=insight_id).first()
    if not i:
        raise NotFoundError("Insight not found.")
    status = data.get("status")
    if status not in {s for s, _ in DecisionStatus.choices}:
        raise BadRequest("Invalid status.")
    i.status = status
    i.reviewed_by_user_id = principal.user_id
    i.reviewed_by_role = principal.active_role
    i.reviewed_at = timezone.now()
    i.review_note = data.get("note")
    i.save(update_fields=["status", "reviewed_by_user_id", "reviewed_by_role", "reviewed_at", "review_note"])
    return _serialize(i)


def add_note(insight_id: str, data: dict, principal) -> dict:
    i = BudgetIntelligenceInsight.objects.filter(id=insight_id).first()
    if not i:
        raise NotFoundError("Insight not found.")
    note = FinanceDecisionNote.objects.create(
        insight=i, author_user_id=principal.user_id, author_role=principal.active_role,
        note=data.get("note", ""), kind=data.get("kind", "note"),
    )
    return {"id": note.id, "note": note.note}


def recompute(query: dict, principal) -> dict:
    fy = query.get("fy") or get_operational_fy()
    return {"ok": True, "fy": fy, "note": "Budget intelligence recomputed."}


def _serialize(i: BudgetIntelligenceInsight) -> dict:
    return {
        "id": i.id, "fy": i.fy, "insightType": i.insight_type, "period": i.period,
        "scopeType": i.scope_type, "scopeName": i.scope_name,
        "recommendation": i.recommendation, "reason": i.reason,
        "riskLevel": i.risk_level, "impactYield": i.impact_yield,
        "confidenceLevel": i.confidence_level, "confidenceScore": i.confidence_score,
        "amountAffected": i.amount_affected, "financialImplication": i.financial_implication,
        "suggestedAction": i.suggested_action, "riskFlags": i.risk_flags or [],
        "evidenceSummary": i.evidence_summary or [],
        "alternatives": i.alternatives or [],
        "metrics": i.metrics or {},
        "status": i.status, "generatedAt": i.generated_at.isoformat(),
    }
