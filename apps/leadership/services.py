"""Leadership Decision Engine service — recommends; leadership decides."""

from __future__ import annotations

from django.utils import timezone

from apps.core.exceptions import NotFoundError
from apps.core.fy import get_operational_fy, get_quarter_for_date

from .models import (
    DecisionConfidenceLevel,
    DecisionNote,
    DecisionRiskLevel,
    DecisionScopeType,
    DecisionStatus,
    DecisionType,
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
    """Regenerate automated leadership-decision insights for an FY.

    A real (not mock) rules engine: it reads live School/staff/SSA/Activity/
    Partner/HR data and produces one insight per (decision_type, scope) where
    a detector's threshold fires — recruitment coverage gaps, staff capacity
    overload, partner performance risk, staff HR risk, and regional SSA
    momentum. Mirrors apps.budget_intelligence.services.recompute()'s
    idempotency contract exactly:

    Idempotency: only insights whose `scope_id` is prefixed with `auto:` are
    managed by the engine. On each run, unreviewed auto-insights for the FY
    are deleted and regenerated from current data. Reviewed auto-insights (or
    any insight a human created directly, without the `auto:` prefix) are
    left untouched so human review is never lost.
    """
    fy = query.get("fy") or get_operational_fy()
    now = timezone.now()

    # Only unreviewed auto-insights are safe to blanket-delete and regenerate.
    LeadershipDecisionInsight.objects.filter(
        fy=fy, scope_id__startswith="auto:", status=DecisionStatus.NEW
    ).filter(reviewed_at__isnull=True).delete()

    # Reviewed auto-insights are never deleted above -- but a detector would
    # otherwise recreate a duplicate row for the same scope_id on every run.
    # Skip regenerating any scope a human has already reviewed instead.
    reviewed_scope_ids = set(
        LeadershipDecisionInsight.objects.filter(fy=fy, scope_id__startswith="auto:")
        .exclude(status=DecisionStatus.NEW)
        .values_list("scope_id", flat=True)
    )

    insights = _detect_recruitment_gaps(fy, now)
    insights += _detect_staff_capacity_overload(fy, now)
    insights += _detect_partner_performance(fy, now)
    insights += _detect_staff_hr_risk(fy, now)
    insights += _detect_regional_investment(fy, now)
    insights = [i for i in insights if i["scope_id"] not in reviewed_scope_ids]

    for payload in insights:
        payload["fy"] = fy
        payload["generated_at"] = now
        payload.setdefault("quarter", get_quarter_for_date(now))
        LeadershipDecisionInsight.objects.create(**payload)

    return {
        "ok": True,
        "fy": fy,
        "generatedCount": len(insights),
        "detectors": [
            "recruitment_gaps",
            "staff_capacity_overload",
            "partner_performance",
            "staff_hr_risk",
            "regional_investment",
        ],
        "note": f"Recomputed {len(insights)} insight(s) for FY {fy}.",
    }


def _detect_recruitment_gaps(fy: str, now) -> list[dict]:
    """Flag districts with a material share of schools lacking a matched
    staff owner -- a direct recruitment/coverage-gap signal."""
    from django.db.models import Count, Q

    from apps.schools.models import School

    insights = []
    rows = (
        School.objects.filter(deleted_at__isnull=True, district__isnull=False)
        .values("district_id", "district__name")
        .annotate(
            total=Count("id"),
            unmatched=Count("id", filter=~Q(account_owner_status="matched")),
        )
        .filter(total__gte=5)
    )
    for row in rows:
        total = row["total"]
        unmatched = row["unmatched"]
        pct = unmatched / total if total else 0
        if unmatched >= 3 and pct > 0.3:
            risk = (
                DecisionRiskLevel.HIGH.value
                if pct > 0.6
                else DecisionRiskLevel.MEDIUM.value
            )
            insights.append(
                {
                    "decision_type": DecisionType.RECRUITMENT.value,
                    "scope_type": DecisionScopeType.DISTRICT.value,
                    "scope_id": f"auto:r:{row['district_id']}",
                    "scope_name": row["district__name"],
                    "recommendation": (
                        f"Recruit or reassign staff coverage for {row['district__name']} -- "
                        f"{unmatched} of {total} schools ({pct:.0%}) have no matched staff owner."
                    ),
                    "reason": (
                        f"{unmatched}/{total} schools in this district have no matched "
                        "account_owner, meaning no staff member is planning support for them."
                    ),
                    "risk_level": risk,
                    "confidence_level": DecisionConfidenceLevel.HIGH.value,
                    "confidence_score": 0.9,
                    "suggested_action": "Recruit new staff for this district or reassign existing staff portfolios.",
                    "risk_flags": ["coverage_gap"],
                    "metrics": {
                        "total_schools": total,
                        "unmatched_schools": unmatched,
                        "unmatched_pct": round(pct, 4),
                    },
                }
            )
    return insights


def _detect_staff_capacity_overload(fy: str, now) -> list[dict]:
    """Flag individual staff carrying more schools than their set direct-
    support capacity -- signals a need to add staff to share the load."""
    from django.db.models import Count

    from apps.accounts.models import (
        StaffProfile,
        StaffSchoolAssignment,
        StaffSupportCapacity,
    )

    insights = []
    caps = {
        c.staff_id: c.max_direct_schools_supported
        for c in StaffSupportCapacity.objects.filter(fy=fy)
    }
    counts = dict(
        StaffSchoolAssignment.objects.values_list("staff_id")
        .annotate(n=Count("id"))
        .values_list("staff_id", "n")
    )
    for staff_id, assigned in counts.items():
        cap = caps.get(staff_id, 10)  # platform default per apps.assignment
        if cap and assigned > cap:
            profile = (
                StaffProfile.objects.filter(id=staff_id).select_related("user").first()
            )
            name = profile.user.name if profile and profile.user_id else staff_id
            overload = assigned - cap
            insights.append(
                {
                    "decision_type": DecisionType.STAFF_ADDITION.value,
                    "scope_type": DecisionScopeType.STAFF.value,
                    "scope_id": f"auto:o:{staff_id}",
                    "scope_name": name,
                    "recommendation": (
                        f"Add supporting staff for {name}'s portfolio -- carrying {assigned} "
                        f"schools against a capacity of {cap} ({overload} over)."
                    ),
                    "reason": f"{assigned} assigned schools exceeds the {cap}-school direct-support capacity set for FY {fy}.",
                    "risk_level": DecisionRiskLevel.HIGH.value
                    if overload > cap * 0.5
                    else DecisionRiskLevel.MEDIUM.value,
                    "confidence_level": DecisionConfidenceLevel.HIGH.value,
                    "confidence_score": 0.9,
                    "suggested_action": "Add a staff member to this portfolio or route new schools to partners.",
                    "risk_flags": ["capacity_overload"],
                    "metrics": {
                        "assigned_schools": assigned,
                        "capacity": cap,
                        "overload": overload,
                    },
                }
            )
    return insights


def _detect_partner_performance(fy: str, now) -> list[dict]:
    """Flag partners with a high IA-return rate (risk) or a strong,
    zero-return completion record (expansion opportunity)."""
    from django.db.models import Count, Q

    from apps.activities.models import Activity
    from apps.partners.models import Partner

    insights = []
    rows = (
        Activity.objects.filter(
            fy=fy, assigned_partner_id__isnull=False, deleted_at__isnull=True
        )
        .values("assigned_partner_id")
        .annotate(
            total=Count("id"),
            returned=Count("id", filter=Q(ia_verification_status="returned")),
            verified=Count("id", filter=Q(ia_verification_status="confirmed")),
        )
        .filter(total__gte=4)
    )
    partner_names = dict(Partner.objects.values_list("id", "name"))
    for row in rows:
        pid = row["assigned_partner_id"]
        total, returned, verified = row["total"], row["returned"], row["verified"]
        return_rate = returned / total if total else 0
        name = partner_names.get(pid, pid)
        if return_rate > 0.25:
            insights.append(
                {
                    "decision_type": DecisionType.PARTNER.value,
                    "scope_type": DecisionScopeType.PARTNER.value,
                    "scope_id": f"auto:pr:{pid}",
                    "scope_name": name,
                    "recommendation": f"Review partnership with {name} -- {returned} of {total} activities ({return_rate:.0%}) returned by IA this FY.",
                    "reason": f"IA return rate of {return_rate:.0%} on {total} activities indicates a quality or training gap.",
                    "risk_level": DecisionRiskLevel.HIGH.value
                    if return_rate > 0.4
                    else DecisionRiskLevel.MEDIUM.value,
                    "confidence_level": DecisionConfidenceLevel.HIGH.value
                    if total >= 8
                    else DecisionConfidenceLevel.MEDIUM.value,
                    "confidence_score": 0.85 if total >= 8 else 0.65,
                    "suggested_action": "Schedule a partner retraining session or place the MOU under review.",
                    "risk_flags": ["high_return_rate"],
                    "metrics": {
                        "total": total,
                        "returned": returned,
                        "return_rate": round(return_rate, 4),
                    },
                }
            )
        elif total >= 6 and returned == 0 and verified / total > 0.8:
            insights.append(
                {
                    "decision_type": DecisionType.PARTNER.value,
                    "scope_type": DecisionScopeType.PARTNER.value,
                    "scope_id": f"auto:po:{pid}",
                    "scope_name": name,
                    "recommendation": f"Consider expanding {name}'s coverage -- {verified} of {total} activities IA-verified this FY with zero returns.",
                    "reason": "Sustained zero-return, high-verification performance signals capacity for a larger portfolio.",
                    "risk_level": DecisionRiskLevel.LOW.value,
                    "confidence_level": DecisionConfidenceLevel.MEDIUM.value,
                    "confidence_score": 0.7,
                    "suggested_action": "Discuss expanded coverage districts with this partner at the next MOU review.",
                    "risk_flags": ["expansion_candidate"],
                    "metrics": {"total": total, "verified": verified},
                }
            )
    return insights


def _detect_staff_hr_risk(fy: str, now) -> list[dict]:
    """Flag staff with an active/escalated PIP (per-staff, named) and, at
    country scope, an aggregate count of open high/critical employee-
    relations cases. EmployeeRelationsCase intentionally has no
    subject-employee field (apps.hr.models.EmployeeRelationsCase docstring:
    "Confidential employee relations concern logging" -- only a case_owner
    who handles it) -- naming an individual from it would be both a
    confidentiality breach and a data-model error, so that signal stays a
    country-level count instead."""
    from apps.hr.models import EmployeeRelationsCase, PerformanceImprovementPlan

    insights = []
    for pip in PerformanceImprovementPlan.objects.filter(
        status__in=["Active", "Escalated"]
    ).select_related("staff__user"):
        profile = pip.staff
        name = profile.user.name if profile and profile.user_id else pip.staff_id
        insights.append(
            {
                "decision_type": DecisionType.STAFF_HR.value,
                "scope_type": DecisionScopeType.STAFF.value,
                "scope_id": f"auto:hp:{pip.staff_id}",
                "scope_name": name,
                "recommendation": f"HR leadership review needed for {name}: active performance-improvement plan ({pip.cause}).",
                "reason": f"Performance-improvement plan is {pip.status.lower()} with cause '{pip.cause}'.",
                "risk_level": DecisionRiskLevel.CRITICAL.value
                if pip.status == "Escalated"
                else DecisionRiskLevel.HIGH.value,
                "confidence_level": DecisionConfidenceLevel.HIGH.value,
                "confidence_score": 0.9,
                "suggested_action": "HR to review PIP status and confirm a resolution timeline with the supervisor.",
                "risk_flags": ["active_pip"],
                "metrics": {"status": pip.status},
            }
        )

    open_cases = EmployeeRelationsCase.objects.filter(
        severity__in=["high", "critical"]
    ).exclude(status__in=["Resolved", "Closed"])
    case_count = open_cases.count()
    if case_count > 0:
        critical_count = open_cases.filter(severity="critical").count()
        insights.append(
            {
                "decision_type": DecisionType.STAFF_HR.value,
                "scope_type": DecisionScopeType.COUNTRY.value,
                "scope_id": "auto:hr_cases_open",
                "scope_name": "Employee Relations",
                "recommendation": f"{case_count} open high/critical employee-relations case(s) need HR leadership attention.",
                "reason": "Employee-relations cases are confidentially logged without a named subject; only the aggregate count is surfaced here.",
                "risk_level": DecisionRiskLevel.CRITICAL.value
                if critical_count
                else DecisionRiskLevel.HIGH.value,
                "confidence_level": DecisionConfidenceLevel.HIGH.value,
                "confidence_score": 0.95,
                "suggested_action": "HR Director to review the Employee Relations case log directly.",
                "risk_flags": ["open_relations_cases"],
                "metrics": {"open_cases": case_count, "critical_cases": critical_count},
            }
        )
    return insights


def _detect_regional_investment(fy: str, now) -> list[dict]:
    """Flag regions with strong SSA momentum (expansion opportunity) or
    weak/declining SSA (needs support before further investment)."""
    from django.db.models import Avg

    from apps.geography.models import Region
    from apps.ssa.models import SsaRecord

    insights = []
    try:
        prev_fy = str(int(fy) - 1)
    except ValueError:
        return insights

    for region in Region.objects.all():
        current = SsaRecord.objects.filter(
            school__region=region,
            fy=fy,
            deleted_at__isnull=True,
            average_score__isnull=False,
        ).aggregate(a=Avg("average_score"))["a"]
        previous = SsaRecord.objects.filter(
            school__region=region,
            fy=prev_fy,
            deleted_at__isnull=True,
            average_score__isnull=False,
        ).aggregate(a=Avg("average_score"))["a"]
        if current is None:
            continue
        delta = (current - previous) if previous is not None else None

        if delta is not None and delta >= 0.5 and current >= 6.5:
            insights.append(
                {
                    "decision_type": DecisionType.REGIONAL_INVESTMENT.value,
                    "scope_type": DecisionScopeType.REGION.value,
                    "scope_id": f"auto:re:{region.id}",
                    "scope_name": region.name,
                    "recommendation": f"Consider increased investment in {region.name} -- SSA average rose {delta:+.1f} to {current:.1f} this FY.",
                    "reason": f"FY{fy} average SSA {current:.1f} vs FY{prev_fy} {previous:.1f} shows sustained improvement.",
                    "risk_level": DecisionRiskLevel.LOW.value,
                    "confidence_level": DecisionConfidenceLevel.MEDIUM.value,
                    "confidence_score": 0.75,
                    "suggested_action": "Evaluate this region for additional core-school slots or partner capacity.",
                    "risk_flags": ["positive_momentum"],
                    "metrics": {
                        "current_avg": round(current, 2),
                        "previous_avg": round(previous, 2),
                        "delta": round(delta, 2),
                    },
                }
            )
        elif current < 5.5 or (delta is not None and delta <= -0.5):
            insights.append(
                {
                    "decision_type": DecisionType.REGIONAL_INVESTMENT.value,
                    "scope_type": DecisionScopeType.REGION.value,
                    "scope_id": f"auto:rs:{region.id}",
                    "scope_name": region.name,
                    "recommendation": f"Hold further investment in {region.name} pending support -- SSA average is {current:.1f}"
                    + (
                        f" ({delta:+.1f} vs last FY)."
                        if delta is not None
                        else " (no prior-FY baseline)."
                    ),
                    "reason": "Weak or declining SSA average signals the region needs targeted support before scaling investment.",
                    "risk_level": DecisionRiskLevel.HIGH.value
                    if current < 4.5
                    else DecisionRiskLevel.MEDIUM.value,
                    "confidence_level": DecisionConfidenceLevel.MEDIUM.value
                    if previous is not None
                    else DecisionConfidenceLevel.LOW.value,
                    "confidence_score": 0.7 if previous is not None else 0.5,
                    "suggested_action": "Prioritize this region for CD/PL follow-up before approving new investment.",
                    "risk_flags": ["weak_ssa"],
                    "metrics": {
                        "current_avg": round(current, 2),
                        "previous_avg": round(previous, 2)
                        if previous is not None
                        else None,
                    },
                }
            )
    return insights


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
