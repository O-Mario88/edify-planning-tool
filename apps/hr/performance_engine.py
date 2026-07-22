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

EDIFY_VALUES = [
    "Christ like Service",
    "Devoted to Prayer",
    "Transformation through Relationships",
    "All things done with excellence & high Integrity",
    "Applaud entrepreneurial spirit",
    "Best Idea Wins",
]

DEFAULT_TEMPLATES = {
    # (layer, category, outcome, metric_key, weight) — the form's exact
    # hierarchy: Program Growth; Program Quality > School Visits / Training /
    # SSA / Capital; PD, Spiritual Formation and Values live in their own
    # sections, not as weighted priorities.
    "CCEO": [
        (
            "role",
            "Program Growth",
            "Recruit and activate new schools",
            "new_schools",
            15,
        ),
        (
            "role",
            "Program Quality — School Visits",
            "Complete all allocated direct school visits",
            "direct_visits",
            20,
        ),
        (
            "role",
            "Program Quality — Training",
            "Deliver the planned training programme",
            "trainings",
            20,
        ),
        (
            "role",
            "Program Quality — School Self Assessment",
            "Complete verified SSA for all assigned schools",
            "ssa_coverage",
            20,
        ),
        (
            "role",
            "Program Quality — Capital",
            "Share loan information promptly and track issues",
            None,
            10,
        ),
        (
            "role",
            "Program Growth",
            "Grow reach through supervised partner delivery",
            "partner_supported_schools",
            15,
        ),
    ],
    "Program Lead": [
        (
            "role",
            "Program Quality — School Visits",
            "Deliver own field execution",
            "direct_visits",
            25,
        ),
        (
            "role",
            "Program Quality — School Self Assessment",
            "Verified SSA coverage across the team",
            "ssa_coverage",
            25,
        ),
        (
            "role",
            "Program Quality — Training",
            "Team training delivery",
            "trainings",
            20,
        ),
        (
            "role",
            "Program Growth",
            "Partner delivery across supervised portfolios",
            "partner_supported_schools",
            15,
        ),
        (
            "org",
            "Program Quality",
            "Full, timely financial accountability",
            "accountability_quality",
            15,
        ),
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
        for i, (layer, category, outcome, metric, weight) in enumerate(
            template, start=1
        ):
            denom = denominators.get(metric)
            PerformancePriority.objects.create(
                review=review,
                sequence=i,
                priority_layer=layer,
                strategic_alignment=category,
                outcome_statement=outcome,
                metric_key=metric,
                weight=weight,
                target_number=denom,
                denominator_note=(
                    f"{denom} assigned schools" if denom == school_count else None
                ),
                target=f"100% of {denom}" if denom else "As agreed",
            )
        # The six named Edify Values, seeded as MANUAL commitment rows —
        # commitments and reflections only, no counts anywhere near them.
        from apps.hr.models import ValueCommitment

        for name in EDIFY_VALUES:
            ValueCommitment.objects.create(review=review, kind="value", value_name=name)
        ValueCommitment.objects.create(
            review=review,
            kind="spiritual",
            value_name="Spiritual Formation priority",
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


# ── HR-controlled conversation windows (§7) ─────────────────────────────────

_HR_ROLES = ("HumanResources", "Admin")


def _assert_hr(principal):
    if getattr(principal, "active_role", "") not in _HR_ROLES:
        raise Forbidden("Only HR controls the performance window.")


def activate_window(cycle, window: str, principal, deadline=None):
    """HR opens a quarter. Activation TAKES THE SNAPSHOTS — every agreed
    review is frozen at this moment, so the meeting's numbers cannot move
    while the conversation is underway."""
    _assert_hr(principal)
    valid = {w for w, _ in type(cycle).WINDOWS} - {"none"}
    if window not in valid:
        raise BadRequest(f"Unknown window '{window}'.")
    cycle.active_window = window
    cycle.window_opened_at = timezone.now()
    cycle.window_deadline = deadline
    cycle.save(
        update_fields=[
            "active_window",
            "window_opened_at",
            "window_deadline",
            "updated_at",
        ]
    )
    from apps.hr.models import PerformanceReview

    count = 0
    for review in PerformanceReview.objects.filter(
        fy=cycle.fy, review_type="annual_priorities"
    ):
        take_snapshot(review, window)
        count += 1
    try:
        from apps.audit.services import log as audit_log

        audit_log(
            action="hr.performance_window_activated",
            subject_kind="PerformanceCycle",
            subject_id=cycle.id,
            actor_id=principal.user_id,
            actor_role=principal.active_role,
            payload={"window": window, "snapshots": count},
        )
    except Exception:  # noqa: BLE001
        pass
    return count


def close_window(cycle, principal):
    _assert_hr(principal)
    cycle.active_window = "none"
    cycle.save(update_fields=["active_window", "updated_at"])


def take_snapshot(review, window: str):
    """Freeze the live figures for one review. Idempotent per window; an
    existing snapshot is never overwritten — that is the whole point."""
    from apps.hr.models import PerformanceSnapshot

    existing = PerformanceSnapshot.objects.filter(review=review, window=window).first()
    if existing:
        return existing
    rows = []
    for p in review.priorities.all():
        progress = live_progress(p)
        rows.append(
            {
                "sequence": p.sequence,
                "outcome": p.outcome_statement,
                "layer": p.priority_layer,
                "metric_key": p.metric_key,
                "target": p.target,
                "target_number": p.target_number,
                "actual": progress["actual"],
                "pct": progress["pct"],
                "weight": p.weight,
            }
        )
    return PerformanceSnapshot.objects.create(
        review=review, window=window, data={"priorities": rows}
    )


# ── Edit boundaries during an activated quarter (§8, §9) ────────────────────
# Verified totals are structurally uneditable — progress is DERIVED, there is
# no stored "actual" field for anyone to touch. These guards cover the human
# channels.


def _active_cycle_for(review):
    from apps.hr.models import PerformanceCycle

    return PerformanceCycle.objects.filter(fy=review.fy).first()


def _assert_window_open(review):
    cycle = _active_cycle_for(review)
    if not cycle or cycle.active_window == "none":
        raise Forbidden(
            "The performance form is locked outside an HR-activated window."
        )
    return cycle


def save_employee_input(priority, data: dict, principal):
    """The employee's own channels: reflection and their own rating. Never
    the manager's columns, never system results."""
    review = priority.review
    _assert_window_open(review)
    if review.staff.user_id != getattr(principal, "user_id", None):
        raise Forbidden("Only the employee writes their own reflection.")
    if "employee_reflection" in data:
        priority.employee_reflection = data["employee_reflection"]
    if "employee_rating" in data:
        priority.employee_rating = data["employee_rating"]
    priority.save(
        update_fields=["employee_reflection", "employee_rating", "updated_at"]
    )
    return priority


def save_manager_input(priority, data: dict, principal):
    """The manager's channels — comments, their rating, agreed actions —
    gated on the real reporting line."""
    from apps.accounts.models import StaffSupervisorAssignment

    review = priority.review
    _assert_window_open(review)
    is_supervisor = StaffSupervisorAssignment.objects.filter(
        supervisee=review.staff, supervisor__user_id=principal.user_id
    ).exists()
    if not (is_supervisor or getattr(principal, "active_role", "") in _HR_ROLES):
        raise Forbidden("Only the reporting line writes the manager columns.")
    for field in ("manager_assessment", "manager_rating", "agreed_action"):
        if field in data:
            setattr(priority, field, data[field])
    priority.save(
        update_fields=[
            "manager_assessment",
            "manager_rating",
            "agreed_action",
            "updated_at",
        ]
    )
    return priority


def quarterly_readiness(fy: str | None = None) -> dict:
    """The 7-days-before-quarter-end readiness check (§6).

    Returns the HR readiness picture and, when a quarter boundary is within
    seven days, notifies HR. Called by the scheduled job daily; safe to run
    any day — it only notifies inside the window, and the notification
    service deduplicates per condition.
    """

    from apps.core.fy import get_operational_fy, get_quarter_for_date

    from apps.hr.models import PerformanceCycle, PerformanceReview

    today = timezone.now().date()
    fy = fy or get_operational_fy()
    quarter_ends = {
        "Q1": (12, 31),
        "Q2": (3, 31),
        "Q3": (6, 30),
        "Q4": (9, 30),
    }
    q = get_quarter_for_date(today)
    m, d = quarter_ends[q]
    year = today.year if (m, d) >= (today.month, today.day) else today.year + 1
    end = today.replace(year=year, month=m, day=d)
    days_left = (end - today).days

    from apps.accounts.models import StaffProfile, StaffSupervisorAssignment

    staff = StaffProfile.objects.filter(
        deleted_at__isnull=True, onboarding_state="active"
    )
    with_agreement = set(
        PerformanceReview.objects.filter(
            fy=fy, review_type="annual_priorities"
        ).values_list("staff_id", flat=True)
    )
    missing_priorities = [s.id for s in staff if s.id not in with_agreement]
    supervised = set(
        StaffSupervisorAssignment.objects.filter(
            supervisee__deleted_at__isnull=True
        ).values_list("supervisee_id", flat=True)
    )
    missing_managers = [s.id for s in staff if s.id not in supervised]

    report = {
        "fy": fy,
        "quarter": q,
        "days_to_quarter_end": days_left,
        "staff_in_cycle": staff.count(),
        "missing_priorities": len(missing_priorities),
        "missing_managers": len(missing_managers),
        "cycle_open": PerformanceCycle.objects.filter(fy=fy).exists(),
    }
    if days_left == 7:
        try:
            from apps.accounts.models import User
            from apps.notifications.services import WorkflowNotificationService

            WorkflowNotificationService.trigger(
                event_type="performance_window_due",
                category="hr",
                priority="high",
                title=f"{q} performance conversations open in 7 days",
                body=(
                    f"{report['staff_in_cycle']} staff in cycle · "
                    f"{report['missing_priorities']} without approved priorities · "
                    f"{report['missing_managers']} without a manager. Review "
                    "readiness and activate the window."
                ),
                context_type="PerformanceCycle",
                context_id=fy,
                recipients=list(
                    User.objects.filter(
                        roles__contains=["HumanResources"], status="active"
                    )
                ),
            )
        except Exception:  # noqa: BLE001
            pass
    return report


def save_functional_manager_input(priority, data: dict, principal):
    """The third, separate voice — only the CONFIGURED functional manager."""
    review = priority.review
    _assert_window_open(review)
    if review.functional_manager_id != getattr(principal, "user_id", None):
        raise Forbidden("Only the configured functional manager writes this column.")
    if "functional_manager_rating" in data:
        priority.functional_manager_rating = data["functional_manager_rating"]
    priority.save(update_fields=["functional_manager_rating", "updated_at"])
    return priority


def flag_performance_support(review, reason: str, principal):
    """Route a concern through Performance Support — an INFORMAL recovery
    plan recommendation. Never a PIP, never automatic: this only records the
    recommendation for the manager-and-HR decision."""
    from apps.hr.models import PerformanceImprovementPlan, RecoveryPlanType

    if not (reason or "").strip():
        raise BadRequest("A support recommendation needs its reason recorded.")
    plan = PerformanceImprovementPlan.objects.create(
        staff=review.staff,
        plan_type=RecoveryPlanType.INFORMAL,
        status="draft",
        cause="capacity",
        action_plan=f"Performance support recommended: {reason}",
        start_date=timezone.now().date(),
        end_date=timezone.now().date(),
    )
    try:
        from apps.audit.services import log as audit_log

        audit_log(
            action="hr.performance_support_flagged",
            subject_kind="PerformanceReview",
            subject_id=review.id,
            actor_id=getattr(principal, "user_id", None),
            actor_role=getattr(principal, "active_role", None),
            payload={"reason": reason},
        )
    except Exception:  # noqa: BLE001
        pass
    return plan
