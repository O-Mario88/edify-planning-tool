"""The performance cycle, as a workflow rather than a register.

Before this, a review was one flat row — `(staff, period, review_type, status,
due_date, rating, score, manager_feedback)` — whose status vocabulary lived in
a `#` comment. There were no annual priorities at all, so the outcomes a
manager and employee agreed in January were unrecoverable in December, and the
year-end assessment was unfalsifiable. The employee could not even open the
page: `performance_reviews` is granted to HR, PL, CD and Admin, and CCEO — the
role being reviewed — was absent.

Two principles are load-bearing here:

  1. **The four evidence channels stay separate.** System evidence is
     computed and never typed; the employee's reflection is theirs; the
     manager's assessment is the manager's; calibration is a cohort decision.
     Collapsing them is how an opinion becomes indistinguishable from a
     measurement.

  2. **System evidence comes from the validated ledger**, not from an activity
     count. `targets.my_targets.weighted_period_pct` credits only work that is
     IA-verified AND Salesforce-ID'd, weights each area, and excludes partner
     delivery from staff credit. `workload_context` travels with it so a
     shortfall is read against the portfolio that produced it — a CCEO with 44
     schools is not the same case as one with 12.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import BadRequest, Forbidden
from apps.hr.models import (
    PerformancePriority,
    PerformancePriorityMilestone,
    PerformanceReview,
    PriorityStatus,
    ReviewStage,
    ReviewType,
)

_HR_ROLES = {"HumanResources", "Admin"}
_CALIBRATION_ROLES = {"HumanResources", "CountryDirector", "Admin"}

#: Roughly five outcome-based priorities per employee.
MAX_PRIORITIES = 8


def _role(principal) -> str:
    return getattr(principal, "active_role", "") or ""


def _staff_id(principal) -> str | None:
    return getattr(principal, "staff_profile_id", None)


def _is_owner(review, principal) -> bool:
    return bool(_staff_id(principal)) and review.staff_id == _staff_id(principal)


def _is_manager_of(review, principal) -> bool:
    """The supervisor of record, or anyone actively covering for them."""
    from apps.accounts.models import StaffSupervisorAssignment

    uid = getattr(principal, "user_id", None)
    if review.manager_id and _staff_id(principal) == review.manager_id:
        return True
    return StaffSupervisorAssignment.objects.filter(
        supervisee_id=review.staff_id, supervisor__user_id=uid
    ).exists()


def _assert_not_self(review, principal, action: str) -> None:
    """Nobody assesses, calibrates or closes their own review.

    The old code had no self-approval predicate at all — not because it was
    safe, but because no approval action existed to protect. The platform's
    proven pattern is copied from `professional_development.approval_service`.
    """
    if _is_owner(review, principal):
        raise Forbidden(f"You cannot {action} your own performance review.")


def _audit(action: str, review, principal, payload=None) -> None:
    from apps.audit.services import log as audit_log

    audit_log(
        action=action,
        subject_kind="performance_review",
        subject_id=review.id,
        actor_id=getattr(principal, "user_id", None),
        actor_role=_role(principal),
        payload={
            "staffId": review.staff_id,
            "period": review.period,
            "stage": review.stage,
            **(payload or {}),
        },
    )


# ── Visibility ───────────────────────────────────────────────────────────────


def visible_reviews(principal):
    """Reviews this person may see: their own, their team's, or their country's."""
    qs = PerformanceReview.objects.select_related("staff__user")
    role = _role(principal)
    if role == "Admin":
        return qs
    own = _staff_id(principal)
    if role in _HR_ROLES or role == "CountryDirector":
        country = getattr(getattr(principal, "staff_profile", None), "country", None)
        return qs.filter(staff__country=country) if country else qs.none()
    from apps.core.scoping import resolve_user_scope

    scope = resolve_user_scope(principal)
    team = list(scope.supervised_staff_ids or [])
    if own:
        team.append(own)
    return qs.filter(staff_id__in=team) if team else qs.none()


def get_for_actor(review_id: str, principal) -> PerformanceReview:
    review = visible_reviews(principal).filter(id=review_id).first()
    if not review:
        raise Forbidden("You do not have access to this performance review.")
    return review


# ── Cycle ────────────────────────────────────────────────────────────────────


@transaction.atomic
def open_cycle(staff_profile, principal, *, fy: str, due_date, review_type=None):
    """Open an annual priorities cycle for one employee."""
    if _role(principal) not in _HR_ROLES and not _is_manager_of(
        type("R", (), {"staff_id": staff_profile.id, "manager_id": None})(), principal
    ):
        raise Forbidden("Only HR or the employee's manager may open a review cycle.")

    from apps.accounts.models import StaffSupervisorAssignment

    link = (
        StaffSupervisorAssignment.objects.filter(supervisee=staff_profile)
        .select_related("supervisor")
        .first()
    )

    review, created = PerformanceReview.objects.get_or_create(
        staff=staff_profile,
        period=fy,
        review_type=review_type or ReviewType.ANNUAL_PRIORITIES,
        defaults={
            "fy": fy,
            "due_date": due_date,
            "stage": ReviewStage.PRIORITIES_DRAFT,
            "status": "Priorities drafting",
            "manager": link.supervisor if link else None,
        },
    )
    if created:
        _audit("hr.review_cycle_opened", review, principal)
    return review


@transaction.atomic
def set_priorities(review_id: str, principal, priorities: list[dict]):
    """The employee drafts their own outcome-based priorities.

    Weights must total 100 — a weighted assessment whose weights do not sum
    is not a weighted assessment.
    """
    review = get_for_actor(review_id, principal)
    if not (_is_owner(review, principal) or _role(principal) in _HR_ROLES):
        raise Forbidden("Only the employee may draft their own priorities.")
    if review.stage not in (
        ReviewStage.PRIORITIES_DRAFT,
        ReviewStage.PRIORITIES_MANAGER_REVIEW,
    ):
        raise BadRequest("Priorities can no longer be edited at this stage.")
    if not priorities:
        raise BadRequest("At least one priority is required.")
    if len(priorities) > MAX_PRIORITIES:
        raise BadRequest(f"No more than {MAX_PRIORITIES} priorities.")

    total_weight = sum(int(p.get("weight") or 0) for p in priorities)
    if total_weight != 100:
        raise BadRequest(f"Priority weights must total 100 (currently {total_weight}).")

    review.priorities.all().delete()
    for i, p in enumerate(priorities, start=1):
        outcome = (p.get("outcome_statement") or "").strip()
        if not outcome:
            raise BadRequest("Every priority needs an outcome statement.")
        priority = PerformancePriority.objects.create(
            review=review,
            sequence=i,
            outcome_statement=outcome,
            strategic_alignment=p.get("strategic_alignment") or "",
            measures_of_success=p.get("measures_of_success") or "",
            baseline=p.get("baseline") or "",
            target=p.get("target") or "",
            weight=int(p.get("weight") or 0),
            support_needed=p.get("support_needed") or "",
        )
        for m in p.get("milestones") or []:
            PerformancePriorityMilestone.objects.create(
                priority=priority,
                description=(m.get("description") or "").strip()[:512],
                due_date=m.get("due_date") or None,
            )

    review.stage = ReviewStage.PRIORITIES_MANAGER_REVIEW
    review.status = "Manager review pending"
    review.save(update_fields=["stage", "status", "updated_at"])
    _audit("hr.priorities_submitted", review, principal, {"count": len(priorities)})
    return review


@transaction.atomic
def agree_priorities(review_id: str, principal, *, note: str = ""):
    """The manager agrees the priorities. Never the employee themselves."""
    review = get_for_actor(review_id, principal)
    _assert_not_self(review, principal, "agree priorities on")
    if not (_is_manager_of(review, principal) or _role(principal) in _HR_ROLES):
        raise Forbidden("Only the employee's manager or HR may agree priorities.")
    if review.stage != ReviewStage.PRIORITIES_MANAGER_REVIEW:
        raise BadRequest("These priorities are not awaiting manager review.")
    review.stage = ReviewStage.PRIORITIES_AGREED
    review.status = "Priorities agreed"
    review.save(update_fields=["stage", "status", "updated_at"])
    _audit("hr.priorities_agreed", review, principal, {"note": note})
    return review


# ── The four channels ────────────────────────────────────────────────────────


def build_system_evidence(review: PerformanceReview) -> dict:
    """Compute the system channel from the validated ledger.

    Deliberately NOT from `pl_analytics_service`, whose own header warns it
    uses broad completion statuses rather than the verified ledger and must
    not carry the achievement label.
    """
    evidence: dict = {"generated_at": timezone.now().isoformat()}
    try:
        from apps.targets.my_targets import MyTargetQueryService

        payload = MyTargetQueryService.get_page(
            review.staff.user, review.fy or review.period
        )
        # The last overall cell is the full-year weighted figure — the same
        # number the employee sees on their own My Targets page, so the review
        # cannot quote a different one.
        cells = payload.get("overall_cells") or []
        evidence["validated_achievement_pct"] = cells[-1]["pct"] if cells else None
        evidence["period_cards"] = [
            {"label": c.get("label"), "pct": c.get("pct")}
            for c in (payload.get("period_cards") or [])
        ]
        evidence["source"] = (
            "targets.my_targets — weighted, IA-verified and Salesforce-ID'd only"
        )
    except Exception as exc:  # noqa: BLE001 - evidence is best-effort
        evidence["validated_achievement_pct"] = None
        evidence["source_error"] = str(exc)[:200]

    try:
        from apps.targets.performance import workload_context

        evidence["workload"] = workload_context(review.staff.id)
    except Exception:  # noqa: BLE001
        evidence["workload"] = None
    return evidence


@transaction.atomic
def refresh_system_evidence(review_id: str, principal) -> PerformanceReview:
    review = get_for_actor(review_id, principal)
    evidence = build_system_evidence(review)
    review.system_evidence = evidence
    review.system_score = evidence.get("validated_achievement_pct")
    review.system_evidence_generated_at = timezone.now()
    # Keep the legacy fields the existing dashboards read in step, so the two
    # cannot drift into two different numbers for one person.
    if review.system_score is not None:
        review.score = float(review.system_score)
    review.save(
        update_fields=[
            "system_evidence",
            "system_score",
            "system_evidence_generated_at",
            "score",
            "updated_at",
        ]
    )
    return review


@transaction.atomic
def submit_reflection(review_id: str, principal, *, reflection: str, per_priority=None):
    """The employee's own words. Only they may write them."""
    review = get_for_actor(review_id, principal)
    if not _is_owner(review, principal):
        raise Forbidden("Only the employee may write their own reflection.")
    if not (reflection or "").strip():
        raise BadRequest("A reflection is required.")
    review.employee_reflection = reflection
    review.employee_reflection_at = timezone.now()
    review.stage = ReviewStage.MANAGER_ASSESSMENT
    review.status = "Manager assessment pending"
    review.save(
        update_fields=[
            "employee_reflection",
            "employee_reflection_at",
            "stage",
            "status",
            "updated_at",
        ]
    )
    for pid, text in (per_priority or {}).items():
        review.priorities.filter(id=pid).update(employee_reflection=text)
    _audit("hr.review_reflection_submitted", review, principal)
    return review


@transaction.atomic
def submit_assessment(
    review_id: str, principal, *, assessment: str, rating: str = "", per_priority=None
):
    """The manager's judgement, kept separate from the computed evidence."""
    review = get_for_actor(review_id, principal)
    _assert_not_self(review, principal, "assess")
    if not (_is_manager_of(review, principal) or _role(principal) in _HR_ROLES):
        raise Forbidden("Only the employee's manager or HR may assess this review.")
    if not (assessment or "").strip():
        raise BadRequest("An assessment is required.")
    review.manager_feedback = assessment
    review.manager_rating = rating or None
    review.rating = rating or review.rating
    review.manager_assessed_at = timezone.now()
    review.stage = ReviewStage.CALIBRATION
    review.status = "Calibration pending"
    review.save()
    for pid, data in (per_priority or {}).items():
        review.priorities.filter(id=pid).update(
            manager_assessment=data.get("assessment", ""),
            status=data.get("status", PriorityStatus.NOT_ASSESSED),
            current_result=data.get("current_result", ""),
        )
    _audit("hr.review_assessed", review, principal, {"rating": rating})
    return review


@transaction.atomic
def calibrate(review_id: str, principal, *, result: str, note: str = ""):
    """A cohort decision, recorded as its own channel."""
    review = get_for_actor(review_id, principal)
    _assert_not_self(review, principal, "calibrate")
    if _role(principal) not in _CALIBRATION_ROLES:
        raise Forbidden("Only HR or the Country Director may calibrate.")
    if review.stage != ReviewStage.CALIBRATION:
        raise BadRequest("This review is not awaiting calibration.")
    review.calibration_result = result
    review.calibration_note = note
    review.calibrated_by_id = getattr(principal, "user_id", None)
    review.calibrated_at = timezone.now()
    review.stage = ReviewStage.AWAITING_ACKNOWLEDGEMENT
    review.status = "Awaiting acknowledgement"
    review.save()
    _audit("hr.review_calibrated", review, principal, {"result": result})
    return review


@transaction.atomic
def acknowledge(review_id: str, principal):
    """The employee acknowledges. Only they can, and it is the last step.

    Note the inversion this closes: previously "no self-approval" held only
    because no approval existed. Here the ONE action reserved to the employee
    is the acknowledgement — and every assessing action is closed to them.
    """
    review = get_for_actor(review_id, principal)
    if not _is_owner(review, principal):
        raise Forbidden("Only the employee may acknowledge their own review.")
    if review.stage != ReviewStage.AWAITING_ACKNOWLEDGEMENT:
        raise BadRequest("This review is not awaiting acknowledgement.")
    review.acknowledged_at = timezone.now()
    review.stage = ReviewStage.CLOSED
    review.status = "Closed"
    review.closed_at = timezone.now()
    review.save()
    _audit("hr.review_acknowledged", review, principal)
    return review
