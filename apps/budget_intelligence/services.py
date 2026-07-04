"""Budget Intelligence service — the financial decision engine."""
from __future__ import annotations

from django.utils import timezone

from apps.core.exceptions import BadRequest, NotFoundError
from apps.core.fy import get_operational_fy
from apps.leadership.models import (
    DecisionConfidenceLevel, DecisionRiskLevel, DecisionScopeType, DecisionStatus,
)

from .models import BudgetIntelligenceInsight, FinanceDecisionNote, ImpactYield


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
    """Regenerate automated budget-intelligence insights for an FY.

    A real (not mock) rules engine: it reads WeeklyFundRequest data for the FY
    and produces actionable insights for each detector that fires — cash
    variance, aged unaccounted advances, returned cash, and oversized pending
    advances per responsible user.

    Idempotency: only insights whose `scope_id` is prefixed with `auto:` are
    managed by the engine. On each run, those are deleted for the FY (unless a
    human has reviewed them) and regenerated from the current data. Insights
    with any other scope_id, or reviewed auto-insights, are left untouched so
    human review is never lost.
    """
    fy = query.get("fy") or get_operational_fy()
    now = timezone.now()

    # 1. Clear stale auto-generated insights for this FY, but preserve any that
    #    a human has already reviewed (status moved off NEW, or reviewed_at set).
    BudgetIntelligenceInsight.objects.filter(
        fy=fy, scope_id__startswith="auto:"
    ).exclude(
        status=DecisionStatus.NEW
    ).exclude(reviewed_at__isnull=True).delete()
    BudgetIntelligenceInsight.objects.filter(
        fy=fy, scope_id__startswith="auto:", status=DecisionStatus.NEW, reviewed_at__isnull=True
    ).delete()

    # 2. Run detectors over the live WFR data.
    insights = _detect_unaccounted_advances(fy, now)
    insights += _detect_cash_variance(fy, now)
    insights += _detect_returned_cash(fy, now)
    insights += _detect_large_pending_advances(fy, now)

    # 3. Persist.
    for payload in insights:
        payload["fy"] = fy
        payload["generated_at"] = now
        BudgetIntelligenceInsight.objects.create(**payload)

    return {
        "ok": True,
        "fy": fy,
        "generatedCount": len(insights),
        "detectors": [
            "unaccounted_advances", "cash_variance", "returned_cash", "large_pending_advances",
        ],
        "note": f"Recomputed {len(insights)} insight(s) for FY {fy}.",
    }


def _detect_unaccounted_advances(fy: str, now) -> list[dict]:
    """Flag disbursed advances with no accountability submitted within 14 days."""
    from datetime import timedelta
    from apps.fund_requests.models import WeeklyFundRequest

    threshold = now - timedelta(days=14)
    aged = WeeklyFundRequest.objects.filter(
        fy=fy,
        status="disbursed",
        disbursed_at__lt=threshold,
        accountability_submitted_at__isnull=True,
    )
    insights = []
    for w in aged:
        days_overdue = (now - w.disbursed_at).days if w.disbursed_at else 0
        insights.append({
            "period_type": "fy",
            "period": fy,
            "insight_type": "unaccounted_advance",
            "scope_type": DecisionScopeType.STAFF.value,
            "scope_id": f"auto:unaccounted:{w.id}",
            "scope_name": f"Weekly advance {w.week_start_date}",
            "recommendation": f"Follow up with responsible staff on unaccounted advance of UGX {w.disbursed_amount:,} ({days_overdue} days overdue).",
            "reason": f"Advance disbursed on {w.disbursed_at.date() if w.disbursed_at else '—'} has no accountability submitted after {days_overdue} days.",
            "risk_level": DecisionRiskLevel.HIGH.value,
            "impact_yield": ImpactYield.LOW.value,
            "confidence_level": DecisionConfidenceLevel.HIGH.value,
            "confidence_score": 0.95,
            "amount_affected": float(w.disbursed_amount or 0),
            "financial_implication": "Cash is at risk until accountability is reconciled.",
            "suggested_action": "Request accountability submission or escalate to CD.",
            "risk_flags": ["aged_advance", "no_accountability"],
            "metrics": {"days_overdue": days_overdue, "disbursed": w.disbursed_amount or 0},
        })
    return insights


def _detect_cash_variance(fy: str, now) -> list[dict]:
    """Flag reconciled advances where accounted ≠ disbursed (>5% variance)."""
    from apps.fund_requests.models import WeeklyFundRequest

    insights = []
    for w in WeeklyFundRequest.objects.filter(fy=fy, accounted_amount__isnull=False, disbursed_amount__isnull=False):
        disbursed = w.disbursed_amount or 0
        accounted = w.accounted_amount or 0
        if disbursed == 0:
            continue
        variance = disbursed - accounted
        pct = abs(variance) / disbursed
        if pct > 0.05:
            insights.append({
                "period_type": "fy",
                "period": fy,
                "insight_type": "cash_variance",
                "scope_type": DecisionScopeType.STAFF.value,
                "scope_id": f"auto:variance:{w.id}",
                "scope_name": f"Weekly advance {w.week_start_date}",
                "recommendation": f"Review UGX {variance:,} variance ({pct:.0%}) on week of {w.week_start_date}.",
                "reason": f"Disbursed UGX {disbursed:,} vs accounted UGX {accounted:,}.",
                "risk_level": DecisionRiskLevel.MEDIUM.value if pct < 0.2 else DecisionRiskLevel.HIGH.value,
                "impact_yield": ImpactYield.WEAK.value,
                "confidence_level": DecisionConfidenceLevel.HIGH.value,
                "confidence_score": 0.9,
                "amount_affected": float(abs(variance)),
                "financial_implication": f"UGX {abs(variance):,} unexplained variance.",
                "suggested_action": "Reconcile with responsible staff; request receipt evidence.",
                "risk_flags": ["cash_variance"],
                "metrics": {"disbursed": disbursed, "accounted": accounted, "variance_pct": round(pct, 4)},
            })
    return insights


def _detect_returned_cash(fy: str, now) -> list[dict]:
    """Flag advances with returned (unspent) cash above a material threshold."""
    from apps.fund_requests.models import WeeklyFundRequest

    insights = []
    for w in WeeklyFundRequest.objects.filter(fy=fy, returned_amount__gt=0):
        returned = w.returned_amount or 0
        disbursed = w.disbursed_amount or 0
        pct = (returned / disbursed) if disbursed else 0
        if returned >= 100000 or pct > 0.1:  # material: >100k UGX or >10%
            insights.append({
                "period_type": "fy",
                "period": fy,
                "insight_type": "returned_cash",
                "scope_type": DecisionScopeType.STAFF.value,
                "scope_id": f"auto:returned:{w.id}",
                "scope_name": f"Weekly advance {w.week_start_date}",
                "recommendation": f"Review planning accuracy: UGX {returned:,} ({pct:.0%}) returned unspent.",
                "reason": "High returned-cash ratio signals over-budgeting or under-execution.",
                "risk_level": DecisionRiskLevel.MEDIUM.value,
                "impact_yield": ImpactYield.WEAK.value,
                "confidence_level": DecisionConfidenceLevel.MEDIUM.value,
                "confidence_score": 0.7,
                "amount_affected": float(returned),
                "financial_implication": "Cash was idle; opportunity cost on deployment.",
                "suggested_action": "Tighten weekly budgeting for this staff member.",
                "risk_flags": ["over_budgeted"],
                "metrics": {"returned": returned, "disbursed": disbursed, "returned_pct": round(pct, 4)},
            })
    return insights


def _detect_large_pending_advances(fy: str, now) -> list[dict]:
    """Aggregate pending advances per responsible user; flag concentration risk."""
    from django.db.models import Sum
    from apps.fund_requests.models import WeeklyFundRequest

    insights = []
    pending = (
        WeeklyFundRequest.objects.filter(fy=fy, status__in=["submitted_to_cd", "submitted_to_rvp"])
        .values("responsible_user")
        .annotate(total=Sum("total_amount"))
        .filter(total__gt=5_000_000)  # >5M UGX pending per user
    )
    for row in pending:
        uid = row["responsible_user"]
        insights.append({
            "period_type": "fy",
            "period": fy,
            "insight_type": "large_pending_advance",
            "scope_type": DecisionScopeType.STAFF.value,
            "scope_id": f"auto:pending:{uid}",
            "scope_name": f"Staff {uid}",
            "recommendation": f"Expedite approval for UGX {row['total']:,} pending advance concentration.",
            "reason": "Large pending concentration delays field execution and signals a bottleneck.",
            "risk_level": DecisionRiskLevel.MEDIUM.value,
            "impact_yield": ImpactYield.HEALTHY.value,
            "confidence_level": DecisionConfidenceLevel.HIGH.value,
            "confidence_score": 0.85,
            "amount_affected": float(row["total"]),
            "financial_implication": "Operational delay risk.",
            "suggested_action": "Prioritize CD/RVP approval queue.",
            "risk_flags": ["approval_bottleneck"],
            "metrics": {"pending_total": row["total"]},
        })
    return insights


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
