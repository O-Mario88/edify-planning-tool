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


# ── Milestone auto-population (§2) ────────────────────────────────────────────
# Each metric priority carries a canonical BREAKDOWN, derived live from the same
# verified sources as live_progress. Only figures with a real source are
# emitted; where the form's example milestone has no canonical origin (e.g.
# "schools retained" needs prior-FY allocation history that does not exist yet)
# it is omitted rather than fabricated — the no-mock-data rule.


def _verified_owner_activities(staff, fy, types):
    """Verified, non-partner activities this employee personally executed."""
    from apps.activities.models import Activity

    return Activity.objects.filter(
        responsible_staff_id__in=_owner_ids_for(staff),
        activity_type__in=types,
        status__in=IA_VERIFIED_STATUSES,
        fy=fy,
        deleted_at__isnull=True,
    ).exclude(delivery_type="partner")


def _school_type_map(school_ids) -> dict:
    from apps.schools.models import School

    return dict(
        School.objects.filter(id__in=school_ids).values_list("id", "school_type")
    )


def milestone_metrics(priority) -> list[dict]:
    """The canonical milestone breakdown for one priority.

    Returns [{label, value, kind}] where kind is 'auto' (derived and
    uneditable), 'target' (the agreed denominator) or 'calc' (a percentage).
    Non-metric priorities (Capital, personal, values) return [] — their rows
    are mixed or manual and carry no auto figures.
    """
    key = priority.metric_key
    if not key:
        return []
    staff = priority.review.staff
    fy = priority.review.fy
    from apps.core.activity_types import TRAINING_TYPES, VISIT_TYPES
    from apps.ssa.models import SsaRecord

    school_ids = _assigned_school_ids(staff)
    types_of = _school_type_map(school_ids)

    def _pct(num, den):
        return round(100 * num / den) if den else None

    rows: list[dict] = []

    if key == "new_schools":
        from apps.schools.models import School

        owner = _owner_ids_for(staff)
        recruited = School.objects.filter(
            account_owner_id__in=owner,
            created_at__gte=_fy_start(fy),
            deleted_at__isnull=True,
        )
        rows.append(
            {
                "label": "New schools recruited",
                "value": recruited.count(),
                "kind": "auto",
            }
        )
        rows.append(
            {
                "label": "New Core Schools recruited",
                "value": recruited.filter(school_type="core").count(),
                "kind": "auto",
            }
        )
        # A school is "activated" once it has carried real verified work this
        # FY — a defensible operational definition, not a fabricated status.
        from apps.activities.models import Activity

        activated = (
            Activity.objects.filter(
                responsible_staff_id__in=owner,
                status__in=IA_VERIFIED_STATUSES,
                fy=fy,
                deleted_at__isnull=True,
                school_id__in=school_ids,
            )
            .values("school_id")
            .distinct()
            .count()
        )
        rows.append({"label": "Schools activated", "value": activated, "kind": "auto"})

    elif key == "partner_supported_schools":
        from apps.activities.models import Activity

        supported = (
            Activity.objects.filter(
                monitored_by_staff_id__in=_owner_ids_for(staff),
                delivery_type="partner",
                status__in=IA_VERIFIED_STATUSES,
                fy=fy,
                deleted_at__isnull=True,
            )
            .values("school_id")
            .distinct()
            .count()
        )
        rows.append(
            {
                "label": "Schools supported through managed partners",
                "value": supported,
                "kind": "auto",
            }
        )

    elif key == "direct_visits":
        acts = _verified_owner_activities(staff, fy, VISIT_TYPES)
        by_school = list(acts.values_list("school_id", flat=True))
        completed = len(by_school)
        core = sum(1 for s in by_school if types_of.get(s) == "core")
        client = sum(1 for s in by_school if types_of.get(s) == "client")
        from apps.activities.models import Activity

        partner_supervised = Activity.objects.filter(
            monitored_by_staff_id__in=_owner_ids_for(staff),
            activity_type__in=VISIT_TYPES,
            delivery_type="partner",
            status__in=IA_VERIFIED_STATUSES,
            fy=fy,
            deleted_at__isnull=True,
        ).count()
        rows += [
            {
                "label": "Direct Visit target",
                "value": priority.target_number,
                "kind": "target",
            },
            {"label": "Direct Visits completed", "value": completed, "kind": "auto"},
            {"label": "Core School Visits", "value": core, "kind": "auto"},
            {"label": "Client School Visits", "value": client, "kind": "auto"},
            {
                "label": "Partner Visits supervised",
                "value": partner_supervised,
                "kind": "auto",
            },
            {
                "label": "Visit completion",
                "value": _pct(completed, priority.target_number),
                "kind": "calc",
            },
        ]

    elif key == "trainings":
        acts = _verified_owner_activities(staff, fy, TRAINING_TYPES)
        agg = acts.values_list(
            "school_id", "activity_type", "teachers_attended", "leaders_attended"
        )
        completed = teachers = leaders = core = client = cluster = 0
        for sid, atype, t, ln in agg:
            completed += 1
            teachers += t or 0
            leaders += ln or 0
            if atype in ("cluster_training", "cluster_training_ssa_collection"):
                cluster += 1
            elif atype == "core_training" or types_of.get(sid) == "core":
                core += 1
            elif types_of.get(sid) == "client":
                client += 1
        rows += [
            {
                "label": "Trainings planned",
                "value": priority.target_number,
                "kind": "target",
            },
            {"label": "Trainings completed", "value": completed, "kind": "auto"},
            {"label": "Core trainings", "value": core, "kind": "auto"},
            {"label": "Client trainings", "value": client, "kind": "auto"},
            {"label": "Cluster trainings", "value": cluster, "kind": "auto"},
            {"label": "Teachers trained", "value": teachers, "kind": "auto"},
            {"label": "School leaders trained", "value": leaders, "kind": "auto"},
        ]

    elif key == "ssa_coverage":
        confirmed = SsaRecord.objects.filter(
            school_id__in=school_ids,
            fy=fy,
            verification_status="confirmed",
            deleted_at__isnull=True,
        )
        verified_schools = set(confirmed.values_list("school_id", flat=True))
        allocated = len(school_ids)
        done = len(verified_schools)
        core_done = sum(1 for s in verified_schools if types_of.get(s) == "core")
        rows += [
            {
                "label": "Schools allocated for SSA",
                "value": allocated,
                "kind": "target",
            },
            {"label": "Verified SSA completed", "value": done, "kind": "auto"},
            {"label": "SSA coverage", "value": _pct(done, allocated), "kind": "calc"},
            {"label": "Missing SSA", "value": max(0, allocated - done), "kind": "auto"},
            {"label": "Core Assessments", "value": core_done, "kind": "auto"},
        ]

    return rows


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


def _validate_rating(value):
    """A rating must be one of the five named options, or blank. Free text is
    refused so the three columns stay comparable across a cohort (§12)."""
    from apps.hr.models import PerformanceRating

    if value in (None, ""):
        return None
    if value not in PerformanceRating.values:
        raise BadRequest(f"'{value}' is not a valid performance rating.")
    return value


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
        priority.employee_rating = _validate_rating(data["employee_rating"])
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
    if "manager_assessment" in data:
        priority.manager_assessment = data["manager_assessment"]
    if "manager_rating" in data:
        priority.manager_rating = _validate_rating(data["manager_rating"])
    if "agreed_action" in data:
        priority.agreed_action = data["agreed_action"]
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
        priority.functional_manager_rating = _validate_rating(
            data["functional_manager_rating"]
        )
    priority.save(update_fields=["functional_manager_rating", "updated_at"])
    return priority


def save_value_reflection(commitment, data: dict, principal):
    """Values and Spiritual Formation are MANUAL and reflective (§2, §20).

    The employee writes their own commitment and reflection; the manager and
    functional manager write their observations. No column is ever derived
    from an activity count. Same window gate as the rest of the form.
    """
    from apps.accounts.models import StaffSupervisorAssignment

    review = commitment.review
    _assert_window_open(review)
    is_employee = review.staff.user_id == getattr(principal, "user_id", None)
    is_manager = StaffSupervisorAssignment.objects.filter(
        supervisee=review.staff, supervisor__user_id=principal.user_id
    ).exists()
    is_functional = review.functional_manager_id == getattr(principal, "user_id", None)
    is_hr = getattr(principal, "active_role", "") in _HR_ROLES

    fields = []
    if is_employee:
        for f in ("agreed_behaviour", "employee_reflection"):
            if f in data:
                setattr(commitment, f, data[f])
                fields.append(f)
    if is_manager or is_hr:
        if "manager_evidence" in data:
            commitment.manager_evidence = data["manager_evidence"]
            fields.append("manager_evidence")
    if is_functional:
        if "functional_manager_observation" in data:
            commitment.functional_manager_observation = data[
                "functional_manager_observation"
            ]
            fields.append("functional_manager_observation")
    if not fields:
        raise Forbidden("You have no writable column on this commitment.")
    commitment.save(update_fields=[*fields, "updated_at"])
    return commitment


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


# ── Targets sync (§5: no separate manual target entry) ──────────────────────

# Priority metric → canonical TargetArea key. Only metrics that ARE official
# target areas map; partner management, new schools and accountability
# quality are performance priorities without a personal target area, and
# inventing one for them would create the second target system the mandate
# forbids.
_METRIC_TO_AREA = {
    "direct_visits": "school_visits",
    "cluster_meetings": "cluster_meetings",
    "trainings": "cluster_trainings",
    "ssa_coverage": "ssa_completed",
}

# Default quarterly phasing (§12). Configurable per cycle later; stated here
# so the split is visible rather than implied by an even division.
DEFAULT_PHASING = {1: 0.20, 2: 0.30, 3: 0.30, 4: 0.20}


def _phased_split(annual: int) -> list[int]:
    """Split an annual target into twelve months by the approved phasing,
    preserving the total exactly (largest-remainder apportionment)."""
    shares = [DEFAULT_PHASING[(m - 1) // 3 + 1] / 3.0 for m in range(1, 13)]
    raw = [annual * s for s in shares]
    base = [int(r) for r in raw]
    remainder = annual - sum(base)
    # Hand the leftover units to the months with the largest fractional part.
    order = sorted(range(12), key=lambda i: raw[i] - base[i], reverse=True)
    for i in order[: max(0, remainder)]:
        base[i] += 1
    return base


def sync_targets_from_agreement(review, principal=None) -> int:
    """On approval, populate My Targets from the agreed priorities.

    ONE ledger: this writes MonthlyPersonalTarget, the same rows My Targets
    and Team Targets already read. It does not create a parallel store, and
    it never touches achievement — only the commitment. Idempotent via the
    model's unique constraint on (user, area, fy, month).
    """
    from apps.targets.models import MonthlyPersonalTarget, TargetArea

    user_id = review.staff.user_id
    if not user_id:
        return 0
    areas = {a.key: a for a in TargetArea.objects.filter(active=True)}
    written = 0
    with transaction.atomic():
        for p in review.priorities.all():
            area_key = _METRIC_TO_AREA.get(p.metric_key or "")
            if not area_key or area_key not in areas:
                continue
            annual = p.target_number or 0
            if annual <= 0:
                continue
            # Spread the annual commitment across the FY's twelve months
            # using the approved quarterly phasing, so an employee is
            # measured against what was expected BY the review date.
            #
            # Distributed by largest remainder, NOT by rounding each month
            # independently: a four-visit annual target rounds to zero in
            # every month on its own and the whole commitment disappears.
            # The twelve months must sum to exactly the annual number.
            monthly = _phased_split(annual)
            for month_of_fy, value in enumerate(monthly, start=1):
                MonthlyPersonalTarget.objects.update_or_create(
                    user_id=user_id,
                    area=areas[area_key],
                    fy=review.fy,
                    month_of_fy=month_of_fy,
                    defaults={"target": value},
                )
                written += 1
    try:
        from apps.audit.services import log as audit_log

        audit_log(
            action="hr.targets_synced_from_agreement",
            subject_kind="PerformanceReview",
            subject_id=review.id,
            actor_id=getattr(principal, "user_id", None),
            actor_role=getattr(principal, "active_role", None),
            payload={"rows": written},
        )
    except Exception:  # noqa: BLE001
        pass
    return written


def approve_agreement(review, principal):
    """Lock the agreement and populate targets — the §7 transition."""
    _assert_hr(principal)
    review.stage = "priorities_agreed"
    review.save(update_fields=["stage", "updated_at"])
    return sync_targets_from_agreement(review, principal)


# ── HR return / reopen (§7: every reopen carries a reason and an audit row) ──


def return_for_correction(review, reason: str, principal):
    """HR sends a conversation back. Never silent: the reason is required and
    the transition is audited."""
    _assert_hr(principal)
    if not (reason or "").strip():
        raise BadRequest("Returning a conversation requires a reason.")
    review.stage = "manager_assessment"
    review.save(update_fields=["stage", "updated_at"])
    _audit_review(review, "hr.performance_returned", principal, {"reason": reason})
    return review


def reopen_conversation(review, window: str, reason: str, principal):
    """Reopen a signed-off conversation.

    The SNAPSHOT IS NOT REGENERATED — reopening lets people correct their
    words, not the numbers the conversation was held against. A new snapshot
    would silently rewrite history, which §10 forbids.
    """
    _assert_hr(principal)
    if not (reason or "").strip():
        raise BadRequest("Reopening a conversation requires a reason.")
    from apps.hr.models import PerformanceSnapshot

    snap = PerformanceSnapshot.objects.filter(review=review, window=window).first()
    if snap is None:
        raise BadRequest("There is no signed conversation for that window.")
    snap.signed_off_at = None
    snap.signed_off_by = None
    snap.save(update_fields=["signed_off_at", "signed_off_by", "updated_at"])
    _audit_review(
        review,
        "hr.performance_reopened",
        principal,
        {"window": window, "reason": reason},
    )
    return snap


def sign_off(review, window: str, principal):
    """Lock the snapshot permanently."""
    from apps.hr.models import PerformanceSnapshot

    snap = PerformanceSnapshot.objects.filter(review=review, window=window).first()
    if snap is None:
        raise BadRequest("No snapshot exists for that window.")
    if snap.signed_off_at:
        return snap
    snap.signed_off_at = timezone.now()
    snap.signed_off_by_id = getattr(principal, "user_id", None)
    snap.save(update_fields=["signed_off_at", "signed_off_by", "updated_at"])
    _audit_review(review, "hr.performance_signed_off", principal, {"window": window})
    return snap


def _audit_review(review, action: str, principal, payload: dict) -> None:
    try:
        from apps.audit.services import log as audit_log

        audit_log(
            action=action,
            subject_kind="PerformanceReview",
            subject_id=review.id,
            actor_id=getattr(principal, "user_id", None),
            actor_role=getattr(principal, "active_role", None),
            payload=payload,
        )
    except Exception:  # noqa: BLE001
        pass


# ── Document generation from the LOCKED snapshot (§14/§17) ─────────────────


def conversation_document(review, window: str, principal) -> dict:
    """The conversation record, rendered from the snapshot — never from live
    data. Returns the context a printable document is built from; the caller
    renders it to HTML (browser-printable to PDF). DOCX is deliberately not
    generated here: no document library is installed, and adding a dependency
    silently is worse than saying so.

    Access is permission- and scope-checked by the caller's view; every
    download writes an audit row.
    """
    from apps.hr.models import PerformanceSnapshot

    snap = PerformanceSnapshot.objects.filter(review=review, window=window).first()
    if snap is None:
        raise BadRequest("No snapshot exists for that conversation.")
    _audit_review(
        review,
        "hr.performance_document_downloaded",
        principal,
        {"window": window, "snapshot_id": snap.id},
    )
    return {
        "review": review,
        "staff": review.staff,
        "window": window,
        "snapshot": snap,
        "priorities": snap.data.get("priorities", []),
        "taken_at": snap.taken_at,
        "signed_off_at": snap.signed_off_at,
        "values": list(review.value_commitments.filter(kind="value")),
        "spiritual": list(review.value_commitments.filter(kind="spiritual")),
        "development": development_rows(review),
    }


# ── Year-end calibration chain (§14) ────────────────────────────────────────
# The overall rating and signatures are applied only AFTER SLT review. This is
# an ordered state machine, not prose: a final rating cannot be confirmed
# before calibration, and the record cannot archive before the employee
# acknowledges it (§20 — no final rating bypasses the calibration workflow).

_LEADERSHIP_ROLES = ("CountryDirector", "RegionalVicePresident", "Admin")


def submit_for_calibration(review, principal):
    """HR quality review passed → the record is ready for SLT calibration."""
    _assert_hr(principal)
    review.stage = "ready_for_slt_calibration"
    review.save(update_fields=["stage", "updated_at"])
    _audit_review(review, "hr.performance_ready_for_calibration", principal, {})
    return review


def calibrate(review, result, note, principal):
    """SLT calibration outcome, facilitated by HR. Only once ready."""
    _assert_hr(principal)
    if review.stage != "ready_for_slt_calibration":
        raise BadRequest("Calibration can only run once HR quality review is complete.")
    review.calibration_result = result
    review.calibration_note = note or ""
    review.calibrated_by_id = getattr(principal, "user_id", None)
    review.calibrated_at = timezone.now()
    review.stage = "slt_calibrated"
    review.save(
        update_fields=[
            "calibration_result",
            "calibration_note",
            "calibrated_by",
            "calibrated_at",
            "stage",
            "updated_at",
        ]
    )
    _audit_review(review, "hr.performance_calibrated", principal, {"result": result})
    return review


def confirm_final_rating(review, rating, principal):
    """Set the overall rating — ONLY after SLT calibration (§20)."""
    _assert_hr(principal)
    if review.stage != "slt_calibrated":
        raise Forbidden("A final rating cannot be confirmed before SLT calibration.")
    review.rating = _validate_rating(rating)
    review.stage = "final_rating_confirmed"
    review.save(update_fields=["rating", "stage", "updated_at"])
    _audit_review(
        review, "hr.performance_final_rating_confirmed", principal, {"rating": rating}
    )
    return review


def acknowledge_review(review, principal):
    """The employee acknowledges the confirmed final rating."""
    if review.staff.user_id != getattr(principal, "user_id", None):
        raise Forbidden("Only the employee acknowledges their own review.")
    if review.stage != "final_rating_confirmed":
        raise BadRequest("There is no confirmed final rating to acknowledge yet.")
    review.acknowledged_at = timezone.now()
    review.stage = "employee_acknowledged"
    review.save(update_fields=["acknowledged_at", "stage", "updated_at"])
    _audit_review(review, "hr.performance_acknowledged", principal, {})
    return review


def archive_review(review, principal):
    """Sign and archive — only after the employee has acknowledged."""
    _assert_hr(principal)
    if review.stage != "employee_acknowledged":
        raise BadRequest(
            "A review is archived only after the employee acknowledges it."
        )
    review.stage = "signed_and_archived"
    review.closed_at = timezone.now()
    review.save(update_fields=["stage", "closed_at", "updated_at"])
    _audit_review(review, "hr.performance_archived", principal, {})
    return review


# ── Formal PIP (§15) — never automatic ──────────────────────────────────────


def recommend_pip(staff, reason, principal, cause="capacity", start=None):
    """RECOMMEND a formal PIP. A manager or HR records the recommendation; it
    creates a DRAFT plan only. Nothing here activates anything, and no score
    ever reaches this function on its own (§15, §20)."""
    from apps.hr.models import PerformanceImprovementPlan, RecoveryPlanType

    if not (reason or "").strip():
        raise BadRequest("A PIP recommendation needs its reason recorded.")
    today = timezone.now().date()
    plan = PerformanceImprovementPlan.objects.create(
        staff=staff,
        plan_type=RecoveryPlanType.FORMAL,
        status="draft",
        cause=cause,
        cause_evidence=reason,
        action_plan="(to be agreed at activation)",
        start_date=start or today,
        end_date=start or today,
        recommended_by_id=getattr(principal, "user_id", None),
    )
    _audit_pip(plan, "hr.pip_recommended", principal, {"reason": reason})
    return plan


def activate_pip(plan, principal, action_plan=None):
    """HR AUTHORIZES a formal PIP and lays out the 30/60/90-day milestones.
    Activation is a deliberate authorized decision, recorded as such."""
    from datetime import timedelta

    from apps.hr.models import RecoveryMilestone, RecoveryPlanType

    _assert_hr(principal)
    if plan.plan_type != RecoveryPlanType.FORMAL:
        raise BadRequest("Only a formal plan is activated as a PIP.")
    if plan.status != "draft":
        raise BadRequest("Only a draft PIP can be activated.")
    plan.status = "active"
    plan.authorized_by_id = getattr(principal, "user_id", None)
    plan.authorized_at = timezone.now()
    if action_plan:
        plan.action_plan = action_plan
    plan.end_date = plan.start_date + timedelta(days=90)
    plan.save(
        update_fields=[
            "status",
            "authorized_by",
            "authorized_at",
            "action_plan",
            "end_date",
            "updated_at",
        ]
    )
    for days, label in (
        (30, "30-day review"),
        (60, "60-day review"),
        (90, "90-day review"),
    ):
        RecoveryMilestone.objects.create(
            plan=plan,
            description=label,
            due_date=plan.start_date + timedelta(days=days),
        )
    _audit_pip(plan, "hr.pip_activated", principal, {})
    return plan


def pip_outcome(plan, outcome, note, principal):
    """complete / extend / escalate — an HR decision, never a score outcome."""
    _assert_hr(principal)
    valid = {"completed", "extended", "escalated"}
    if outcome not in valid:
        raise BadRequest(f"PIP outcome must be one of {sorted(valid)}.")
    plan.status = outcome
    plan.outcome = outcome
    plan.outcome_note = note or ""
    if outcome in ("completed", "escalated"):
        plan.closed_at = timezone.now()
    if outcome == "escalated":
        from apps.hr.models import EmployeeRelationsCase

        case = EmployeeRelationsCase.objects.create(
            subject_staff=plan.staff,
            country=plan.staff.country or "Uganda",
            case_type="conduct",
            description=note or "Escalated from a formal PIP.",
            raised_by_id=getattr(principal, "user_id", None),
        )
        plan.escalated_case = case
    plan.save(
        update_fields=[
            "status",
            "outcome",
            "outcome_note",
            "closed_at",
            "escalated_case",
            "updated_at",
        ]
    )
    _audit_pip(plan, "hr.pip_outcome", principal, {"outcome": outcome})
    return plan


def _audit_pip(plan, action, principal, payload):
    try:
        from apps.audit.services import log as audit_log

        audit_log(
            action=action,
            subject_kind="PerformanceImprovementPlan",
            subject_id=plan.id,
            actor_id=getattr(principal, "user_id", None),
            actor_role=getattr(principal, "active_role", None),
            payload=payload,
        )
    except Exception:  # noqa: BLE001
        pass


# ── Separation (§15) — a restricted, due-process HR workflow ─────────────────


def open_separation(staff, data: dict, principal):
    """HR opens the separation workflow. Never automatic; the reason is
    required and the subject employee will get to respond before any
    approval."""
    _assert_hr(principal)
    from apps.hr.models import SeparationConversation

    reason = (data.get("reason") or "").strip()
    if not reason:
        raise BadRequest("A separation must record its reason.")
    sep = SeparationConversation.objects.create(
        subject_staff=staff,
        country=staff.country or "Uganda",
        reason=reason,
        evidence=data.get("evidence"),
        policy_basis=data.get("policy_basis"),
        manager_recommendation=data.get("manager_recommendation"),
        recommended_by_id=data.get("recommended_by_id"),
        opened_by_id=getattr(principal, "user_id", None),
        stage=SeparationConversation.Stage.AWAITING_EMPLOYEE_RESPONSE,
    )
    _audit_separation(sep, "hr.separation_opened", principal, {})
    return sep


def record_separation_response(sep, text, principal):
    """The subject employee's own response — the due-process step that must
    precede any HR review."""
    if sep.subject_staff.user_id != getattr(principal, "user_id", None):
        raise Forbidden("Only the employee records their own response.")
    from apps.hr.models import SeparationConversation

    sep.employee_response = text
    sep.employee_responded_at = timezone.now()
    sep.stage = SeparationConversation.Stage.HR_REVIEW
    sep.save(
        update_fields=[
            "employee_response",
            "employee_responded_at",
            "stage",
            "updated_at",
        ]
    )
    _audit_separation(sep, "hr.separation_employee_responded", principal, {})
    return sep


def hr_review_separation(sep, note, principal):
    _assert_hr(principal)
    from apps.hr.models import SeparationConversation

    sep.hr_review_note = note or ""
    sep.hr_reviewed_by_id = getattr(principal, "user_id", None)
    sep.hr_reviewed_at = timezone.now()
    sep.stage = SeparationConversation.Stage.AWAITING_LEADERSHIP_APPROVAL
    sep.save(
        update_fields=[
            "hr_review_note",
            "hr_reviewed_by",
            "hr_reviewed_at",
            "stage",
            "updated_at",
        ]
    )
    _audit_separation(sep, "hr.separation_hr_reviewed", principal, {})
    return sep


def approve_separation(sep, principal):
    """Authorized leadership approval. The approver may NOT be the person who
    opened or recommended the separation (§15 — separation of duties)."""
    from apps.hr.models import SeparationConversation

    if getattr(principal, "active_role", "") not in _LEADERSHIP_ROLES:
        raise Forbidden("Only authorized leadership may approve a separation.")
    uid = getattr(principal, "user_id", None)
    if uid and uid in (sep.recommended_by_id, sep.opened_by_id):
        raise Forbidden(
            "Whoever opened or recommended a separation may not approve it."
        )
    if sep.stage != SeparationConversation.Stage.AWAITING_LEADERSHIP_APPROVAL:
        raise BadRequest("HR review must complete before leadership approval.")
    sep.approved_by_id = uid
    sep.approved_at = timezone.now()
    sep.stage = SeparationConversation.Stage.APPROVED
    sep.save(update_fields=["approved_by", "approved_at", "stage", "updated_at"])
    _audit_separation(sep, "hr.separation_approved", principal, {})
    return sep


def decline_separation(sep, note, principal):
    """HR or leadership declines. Recorded, not deleted."""
    from apps.hr.models import SeparationConversation

    role = getattr(principal, "active_role", "")
    if role not in _HR_ROLES and role not in _LEADERSHIP_ROLES:
        raise Forbidden("Only HR or leadership may decline a separation.")
    sep.outcome_note = note or ""
    sep.stage = SeparationConversation.Stage.DECLINED
    sep.save(update_fields=["outcome_note", "stage", "updated_at"])
    _audit_separation(sep, "hr.separation_declined", principal, {})
    return sep


def _audit_separation(sep, action, principal, payload):
    try:
        from apps.audit.services import log as audit_log

        audit_log(
            action=action,
            subject_kind="SeparationConversation",
            subject_id=sep.id,
            actor_id=getattr(principal, "user_id", None),
            actor_role=getattr(principal, "active_role", None),
            payload=payload,
        )
    except Exception:  # noqa: BLE001
        pass
