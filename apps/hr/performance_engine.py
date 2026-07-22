"""The Performance Priority & Conversation Engine.

The Word document becomes an output; the agreement becomes the source of
truth. Design rules, from the mandate and the platform's own invariants:

* Progress is DERIVED LIVE on read — the To-Do pattern. An activity that
  closes updates every priority the moment anyone looks, with no sync job to
  lag and no typed numbers to drift. Only VERIFIED work counts
  (IA_VERIFIED_STATUSES; confirmed SSA).
* No percentage without a denominator: numeric targets are built from the
  employee's real portfolio (assigned schools, entitlements, core slots),
  and the denominator is stored beside the target.
* Partner-supported schools are a SEPARATE metric that adds weight through a
  Partner Management priority — never direct-execution credit.
* Development rows merge the PD workflow automatically with the employee's
  manual additions. Values and amendments are manual by mandate.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import BadRequest, Forbidden
from apps.targets.my_targets import IA_VERIFIED_STATUSES


# ── Canonical metric registry ────────────────────────────────────────────────
# metric_key → (label, how progress is derived). Every measurable priority
# must name one of these; a target with no canonical metric is refused.
METRIC_KEYS = {
    "ssa_coverage": "Verified SSA coverage of assigned schools",
    "direct_visits": "Verified direct school visits",
    "trainings": "Verified trainings delivered",
    "cluster_meetings": "Verified cluster meetings",
    "core_slots": "Core package slots completed",
    "partner_supported_schools": "Schools supported through managed partners",
    "new_schools": "New schools recruited",
    "accountability_quality": "Accountabilities cleared without return",
}


def _assigned_school_ids(staff) -> list[str]:
    from apps.accounts.models import StaffSchoolAssignment

    return list(
        StaffSchoolAssignment.objects.filter(staff=staff).values_list(
            "school_id", flat=True
        )
    )


def _owner_ids_for(staff) -> list[str]:
    ids = [staff.id]
    if staff.user_id:
        ids.append(staff.user_id)
    return ids


def live_progress(priority) -> dict:
    """Derive a priority's live numerator/denominator from canonical sources.

    Returns {"actual": int, "target": int|None, "pct": int|None,
    "source": str}. Non-metric (personal/values) priorities return actual
    None — they are conversational by mandate.
    """
    key = priority.metric_key
    staff = priority.review.staff
    fy = priority.review.fy
    if not key:
        return {"actual": None, "target": None, "pct": None, "source": "manual"}

    from apps.activities.models import Activity
    from apps.ssa.models import SsaRecord

    owner = _owner_ids_for(staff)
    school_ids = _assigned_school_ids(staff)
    actual = 0

    if key == "ssa_coverage":
        actual = (
            SsaRecord.objects.filter(
                school_id__in=school_ids,
                fy=fy,
                verification_status="confirmed",
                deleted_at__isnull=True,
            )
            .values("school_id")
            .distinct()
            .count()
        )
    elif key == "direct_visits":
        # Direct execution only — partner-delivered work NEVER counts here.
        actual = (
            Activity.objects.filter(
                responsible_staff_id__in=owner,
                activity_type__in=["school_visit", "core_visit"],
                status__in=IA_VERIFIED_STATUSES,
                fy=fy,
                deleted_at__isnull=True,
            )
            .exclude(delivery_type="partner")
            .count()
        )
    elif key == "trainings":
        actual = (
            Activity.objects.filter(
                responsible_staff_id__in=owner,
                activity_type__in=[
                    "training",
                    "in_school_training",
                    "school_improvement_training",
                    "core_training",
                    "cluster_training",
                ],
                status__in=IA_VERIFIED_STATUSES,
                fy=fy,
                deleted_at__isnull=True,
            )
            .exclude(delivery_type="partner")
            .count()
        )
    elif key == "cluster_meetings":
        actual = Activity.objects.filter(
            responsible_staff_id__in=owner,
            activity_type="cluster_meeting",
            status__in=IA_VERIFIED_STATUSES,
            fy=fy,
            deleted_at__isnull=True,
        ).count()
    elif key == "core_slots":
        from apps.core_schools.models import CoreActivitySlot

        actual = CoreActivitySlot.objects.filter(
            core_plan__fy=fy,
            core_plan__school_id__in=list(_school_operational_ids(school_ids)),
            status="Completed",
        ).count()
    elif key == "partner_supported_schools":
        # The mandate's weighting rule: schools reached through partners the
        # employee supervises ADD to their performance — as partner
        # management, never as direct execution.
        actual = (
            Activity.objects.filter(
                monitored_by_staff_id__in=owner,
                delivery_type="partner",
                status__in=IA_VERIFIED_STATUSES,
                fy=fy,
                deleted_at__isnull=True,
            )
            .values("school_id")
            .distinct()
            .count()
        )
    elif key == "new_schools":
        from apps.schools.models import School

        actual = School.objects.filter(
            account_owner_id__in=owner,
            created_at__gte=_fy_start(fy),
            deleted_at__isnull=True,
        ).count()
    elif key == "accountability_quality":
        from apps.fund_requests.models import AdvanceRequest

        cleared = AdvanceRequest.objects.filter(
            responsible_user_id__in=owner, status="accounted", fy=fy
        ).count()
        returned = AdvanceRequest.objects.filter(
            responsible_user_id__in=owner,
            status__in=["accountability_returned", "returned"],
            fy=fy,
        ).count()
        total = cleared + returned
        actual = round(100 * cleared / total) if total else 0

    target = priority.target_number
    pct = round(100 * actual / target) if target else None
    return {
        "actual": actual,
        "target": target,
        "pct": pct,
        "source": METRIC_KEYS.get(key, key),
    }


def _school_operational_ids(school_pks) -> list[str]:
    from apps.schools.models import School

    return list(
        School.objects.filter(id__in=school_pks).values_list("school_id", flat=True)
    )


def _fy_start(fy: str):
    from datetime import date

    return date(int(fy) - 1, 10, 1)


# ── Draft agreement builder ──────────────────────────────────────────────────

DEFAULT_TEMPLATES = {
    "CCEO": [
        ("role", "Complete verified SSA for all assigned schools", "ssa_coverage", 30),
        ("role", "Complete all allocated direct school visits", "direct_visits", 20),
        ("role", "Deliver the planned training programme", "trainings", 20),
        (
            "role",
            "Grow reach through supervised partner delivery",
            "partner_supported_schools",
            15,
        ),
        ("org", "Full, timely financial accountability", "accountability_quality", 15),
    ],
    "Program Lead": [
        ("role", "Deliver own field execution", "direct_visits", 25),
        ("role", "Verified SSA coverage across the team", "ssa_coverage", 25),
        ("role", "Team training delivery", "trainings", 20),
        (
            "role",
            "Partner delivery across supervised portfolios",
            "partner_supported_schools",
            15,
        ),
        ("org", "Full, timely financial accountability", "accountability_quality", 15),
    ],
}


def build_draft_agreement(staff, cycle, principal) -> "object":
    """Generate the draft Priority Agreement from role template + portfolio.

    Denominators come from the REAL portfolio at build time — assigned
    schools for SSA, the same count for the annual visit entitlement — so
    '100%' always renders with its divisor. Idempotent per (staff, fy).
    """
    from apps.hr.models import (
        PerformancePriority,
        PerformanceReview,
        ReviewType,
        RolePriorityTemplate,
    )

    existing = PerformanceReview.objects.filter(
        staff=staff, fy=cycle.fy, review_type=ReviewType.ANNUAL_PRIORITIES
    ).first()
    if existing:
        return existing

    role = staff.user.active_role if staff.user_id else ""
    rows = list(RolePriorityTemplate.objects.filter(role=role).order_by("sequence"))
    template = (
        [
            (r.priority_layer, r.outcome_statement, r.metric_key, r.default_weight)
            for r in rows
        ]
        if rows
        else DEFAULT_TEMPLATES.get(role, DEFAULT_TEMPLATES["CCEO"])
    )

    school_count = len(_assigned_school_ids(staff))
    denominators = {
        "ssa_coverage": school_count,
        "direct_visits": school_count,  # one visit entitlement per school/FY
        "trainings": school_count,  # one training entitlement per school/FY
        "partner_supported_schools": None,  # open-ended: growth, not a cap
        "accountability_quality": 100,
        "cluster_meetings": None,
        "core_slots": None,
        "new_schools": None,
    }

    with transaction.atomic():
        review = PerformanceReview.objects.create(
            staff=staff,
            fy=cycle.fy,
            review_type=ReviewType.ANNUAL_PRIORITIES,
            period=f"FY{cycle.fy}",
            due_date=_fy_start(str(int(cycle.fy) + 1)),
        )
        for i, (layer, outcome, metric, weight) in enumerate(template, start=1):
            denom = denominators.get(metric)
            PerformancePriority.objects.create(
                review=review,
                sequence=i,
                priority_layer=layer,
                outcome_statement=outcome,
                metric_key=metric,
                weight=weight,
                target_number=denom,
                denominator_note=(
                    f"{denom} assigned schools" if denom == school_count else None
                ),
                target=f"100% of {denom}" if denom else "As agreed",
            )
    try:
        from apps.audit.services import log as audit_log

        audit_log(
            action="hr.performance_agreement_drafted",
            subject_kind="PerformanceReview",
            subject_id=review.id,
            actor_id=getattr(principal, "user_id", None),
            actor_role=getattr(principal, "active_role", None),
        )
    except Exception:  # noqa: BLE001
        pass
    return review


# ── Development merge (PD workflow + manual) ────────────────────────────────


def development_rows(review) -> list[dict]:
    """PD-workflow rows appear automatically; manual items append. The PD
    side is read-only here — its lifecycle stays in the PD app."""
    rows = []
    try:
        from apps.professional_development.models import (
            ProfessionalDevelopmentRequest,
        )

        for r in ProfessionalDevelopmentRequest.objects.filter(
            staff_id=review.staff_id
        ).order_by("created_at"):
            rows.append(
                {
                    "source": "pd_workflow",
                    "description": r.course_name,
                    "status": r.status,
                    "editable": False,
                }
            )
    except Exception:  # noqa: BLE001 - PD app shape must never break reviews
        pass
    for item in review.development_items.all():
        rows.append(
            {
                "source": "manual",
                "description": item.description,
                "status": item.progress_note or "",
                "editable": True,
            }
        )
    return rows


# ── Manual amendment (mandate: never silent) ────────────────────────────────


def request_amendment(priority, data: dict, principal):
    from apps.hr.models import PriorityAmendment

    reason = (data.get("reason") or "").strip()
    if not reason:
        raise BadRequest("An amendment needs its reason recorded.")
    return PriorityAmendment.objects.create(
        priority=priority,
        requested_by_id=getattr(principal, "user_id", None),
        reason=reason,
        changed_target=data.get("changed_target"),
        changed_target_number=data.get("changed_target_number"),
        effective_date=data.get("effective_date"),
    )


def approve_amendment(amendment, principal):
    """Manager approval applies the change forward — snapshots stay as they
    were, and the approver may not be the requester."""
    if amendment.requested_by_id == getattr(principal, "user_id", None):
        raise Forbidden("You cannot approve your own amendment.")
    with transaction.atomic():
        amendment.status = "approved"
        amendment.approved_by_id = principal.user_id
        amendment.approved_at = timezone.now()
        amendment.save(
            update_fields=["status", "approved_by_id", "approved_at", "updated_at"]
        )
        p = amendment.priority
        if amendment.changed_target:
            p.target = amendment.changed_target
        if amendment.changed_target_number is not None:
            p.target_number = amendment.changed_target_number
        p.save(update_fields=["target", "target_number", "updated_at"])
    try:
        from apps.audit.services import log as audit_log

        audit_log(
            action="hr.priority_amended",
            subject_kind="PerformancePriority",
            subject_id=amendment.priority_id,
            actor_id=principal.user_id,
            actor_role=getattr(principal, "active_role", None),
            payload={"reason": amendment.reason},
        )
    except Exception:  # noqa: BLE001
        pass
    return amendment
