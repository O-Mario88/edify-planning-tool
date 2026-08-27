"""Governed dual-rate-card, activity cost-review, and strategic-reserve flows."""

from __future__ import annotations

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.audit.services import log as audit_log
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.permissions import RolePermissionService, has_permission
from apps.core.rbac import Permission

from .costing_service import calculate_dual
from .models import (
    ActivityCostReview,
    ActivityCostSnapshot,
    CostCatalogue,
    CostReviewReason,
    CostSetting,
    CountryStrategicActivityReserve,
    RateCardKind,
    RateCardStatus,
    ReserveActivationStatus,
    StrategicReserveActivation,
)
from .reference import CANONICAL_RATE_KEYS


def _user_id(principal) -> str:
    return str(getattr(principal, "user_id", None) or getattr(principal, "id", ""))


def _require(principal, permission: Permission, message: str) -> None:
    if not has_permission(principal, permission.value):
        raise Forbidden(message)


def _may_reference(principal) -> bool:
    return has_permission(principal, Permission.RATE_CARD_REFERENCE_VIEW.value)


def _card_dict(card: CostCatalogue, *, include_lines: bool) -> dict:
    data = {
        "id": card.id,
        "country": card.country,
        "fy": card.fy,
        "kind": card.kind,
        "kindLabel": card.get_kind_display(),
        "version": card.version,
        "status": card.status,
        "effectiveFrom": card.effective_from,
        "effectiveTo": card.effective_to,
        "currency": card.currency,
        "label": card.label,
        "publishedAt": card.published_at,
        "isProvisional": card.is_provisional,
        "configurationRequired": card.kind == RateCardKind.REFERENCE
        and not card.rates.exists(),
    }
    if include_lines:
        data["lines"] = [
            {
                "code": line.key,
                "label": line.label,
                "unit": line.unit,
                "amount": line.unit_cost,
                "approvedMinimum": line.approved_minimum,
                "geographicScope": line.geographic_scope,
                "costingProfileScope": line.costing_profile_scope,
            }
            for line in card.rates.filter(key__in=CANONICAL_RATE_KEYS).order_by("label")
        ]
    return data


def list_rate_cards(principal, *, fy: str | None = None) -> dict:
    _require(
        principal,
        Permission.RATE_CARD_OPERATIONAL_VIEW,
        "You do not have access to country rate cards.",
    )
    qs = (
        CostCatalogue.objects.all()
        .prefetch_related("rates")
        .order_by("kind", "-fy", "-version")
    )
    if fy:
        qs = qs.filter(fy=str(fy))
    if not _may_reference(principal):
        qs = qs.filter(kind=RateCardKind.OPERATIONAL)
    return {
        "rateCards": [_card_dict(card, include_lines=True) for card in qs],
        "referenceVisible": _may_reference(principal),
    }


def create_rate_card_version(principal, data: dict) -> dict:
    kind = data.get("kind", RateCardKind.OPERATIONAL)
    permission = (
        Permission.RATE_CARD_REFERENCE_MANAGE
        if kind == RateCardKind.REFERENCE
        else Permission.RATE_CARD_OPERATIONAL_MANAGE
    )
    _require(principal, permission, "You cannot create this rate-card type.")
    if kind not in RateCardKind.values:
        raise BadRequest("Unknown rate-card kind.")
    country = data.get("country") or "Uganda"
    currency = data.get("currency") or "UGX"
    if country == "Uganda" and currency != "UGX":
        raise BadRequest("Uganda activity rate cards must use UGX.")
    fy = str(data.get("fy") or "").strip()
    if not fy:
        raise BadRequest("fy is required.")
    source_id = data.get("sourceRateCardId")
    with transaction.atomic():
        latest = (
            CostCatalogue.objects.select_for_update()
            .filter(country=country, fy=fy, kind=kind)
            .order_by("-version")
            .first()
        )
        source = None
        if source_id:
            source = CostCatalogue.objects.filter(
                id=source_id, country=country, fy=fy, kind=kind
            ).first()
            if source is None:
                raise BadRequest("The source rate card is not in this country/FY/type.")
        card = CostCatalogue.objects.create(
            country=country,
            fy=fy,
            kind=kind,
            version=(latest.version + 1) if latest else 1,
            status=RateCardStatus.DRAFT,
            is_active=False,
            label=data.get("label"),
            effective_from=data.get("effectiveFrom") or None,
            effective_to=data.get("effectiveTo") or None,
            currency=currency,
            created_by=_user_id(principal),
            notes=data.get("notes"),
            is_provisional=bool(data.get("isProvisional", False)),
            source_note=data.get("sourceNote"),
            material_difference_threshold_bps=data.get(
                "materialDifferenceThresholdBps"
            ),
        )
        # Copying is explicit. A reference card is never seeded from the
        # operational card because the query above requires the same kind.
        if source:
            CostSetting.objects.bulk_create(
                [
                    CostSetting(
                        catalogue=card,
                        key=line.key,
                        label=line.label,
                        unit_cost=line.unit_cost,
                        fy=fy,
                        version=line.version,
                        unit=line.unit,
                        approved_minimum=line.approved_minimum,
                        geographic_scope=line.geographic_scope,
                        costing_profile_scope=line.costing_profile_scope,
                        created_by=_user_id(principal),
                    )
                    for line in source.rates.all()
                ]
            )
        audit_log(
            action="rate_card.version.created",
            subject_kind="CostCatalogue",
            subject_id=card.id,
            actor_id=_user_id(principal),
            actor_role=getattr(principal, "active_role", None),
            payload={"kind": kind, "fy": fy, "version": card.version},
            required=True,
        )
    return _card_dict(card, include_lines=True)


def upsert_rate_card_line(principal, card_id: str, data: dict) -> dict:
    card = CostCatalogue.objects.filter(id=card_id).first()
    if card is None:
        raise NotFoundError("Rate card not found.")
    permission = (
        Permission.RATE_CARD_REFERENCE_MANAGE
        if card.kind == RateCardKind.REFERENCE
        else Permission.RATE_CARD_OPERATIONAL_MANAGE
    )
    _require(principal, permission, "You cannot edit this rate card.")
    if card.status not in (RateCardStatus.DRAFT, RateCardStatus.UNDER_REVIEW):
        raise BadRequest("Published, superseded, and retired rate cards are immutable.")
    key = data.get("code")
    if key not in CANONICAL_RATE_KEYS:
        raise BadRequest("The cost-component code is not governed by the catalogue.")
    try:
        amount = int(data.get("amount"))
    except (TypeError, ValueError):
        raise BadRequest("amount must be a whole UGX value.")
    if amount < 0:
        raise BadRequest("amount cannot be negative.")
    minimum = data.get("approvedMinimum")
    if minimum not in (None, ""):
        try:
            minimum = int(minimum)
        except (TypeError, ValueError):
            raise BadRequest("approvedMinimum must be a whole UGX value.")
        if minimum < 0:
            raise BadRequest("approvedMinimum cannot be negative.")
    else:
        minimum = None
    with transaction.atomic():
        line, _ = CostSetting.objects.update_or_create(
            catalogue=card,
            key=key,
            defaults={
                "label": data.get("label") or key.replace("_", " ").title(),
                "unit_cost": amount,
                "fy": card.fy,
                "unit": data.get("unit") or "unit",
                "approved_minimum": minimum,
                "geographic_scope": data.get("geographicScope") or None,
                "costing_profile_scope": data.get("costingProfileScope") or None,
                "created_by": _user_id(principal),
            },
        )
        audit_log(
            action="rate_card.line.saved",
            subject_kind="CostSetting",
            subject_id=line.id,
            actor_id=_user_id(principal),
            actor_role=getattr(principal, "active_role", None),
            payload={"rateCardId": card.id, "code": key, "amount": amount},
            required=True,
        )
    return _card_dict(card, include_lines=True)


def publish_rate_card(principal, card_id: str) -> dict:
    with transaction.atomic():
        card = CostCatalogue.objects.select_for_update().filter(id=card_id).first()
        if card is None:
            raise NotFoundError("Rate card not found.")
        permission = (
            Permission.RATE_CARD_REFERENCE_MANAGE
            if card.kind == RateCardKind.REFERENCE
            else Permission.RATE_CARD_OPERATIONAL_MANAGE
        )
        _require(principal, permission, "You cannot publish this rate card.")
        if card.status not in (RateCardStatus.DRAFT, RateCardStatus.UNDER_REVIEW):
            raise BadRequest("Only a draft or reviewed rate card can be published.")
        if card.country == "Uganda" and card.currency != "UGX":
            raise BadRequest("Uganda activity rate cards must use UGX.")
        if not card.rates.exists():
            raise BadRequest("Add governed rates before publishing this rate card.")
        overlap = CostCatalogue.objects.filter(
            country=card.country,
            fy=card.fy,
            kind=card.kind,
            status=RateCardStatus.PUBLISHED,
            is_active=True,
        ).exclude(id=card.id)
        if card.effective_from:
            overlap = overlap.filter(
                Q(effective_to__isnull=True) | Q(effective_to__gte=card.effective_from)
            )
        if card.effective_to:
            overlap = overlap.filter(
                Q(effective_from__isnull=True)
                | Q(effective_from__lte=card.effective_to)
            )
        now = timezone.now()
        for prior in overlap.select_for_update():
            prior.status = RateCardStatus.SUPERSEDED
            prior.is_active = False
            prior.superseded_at = now
            prior.save(
                update_fields=["status", "is_active", "superseded_at", "updated_at"]
            )
        card.status = RateCardStatus.PUBLISHED
        card.is_active = True
        card.approved_by = _user_id(principal)
        card.published_by = _user_id(principal)
        card.published_at = now
        card.activated_at = now
        card.save(
            update_fields=[
                "status",
                "is_active",
                "approved_by",
                "published_by",
                "published_at",
                "activated_at",
                "updated_at",
            ]
        )
        audit_log(
            action="rate_card.version.published",
            subject_kind="CostCatalogue",
            subject_id=card.id,
            actor_id=_user_id(principal),
            actor_role=getattr(principal, "active_role", None),
            payload={"kind": card.kind, "fy": card.fy, "version": card.version},
            required=True,
        )
    return _card_dict(card, include_lines=True)


def request_cost_review(principal, activity_id: str, data: dict) -> dict:
    _require(
        principal,
        Permission.COST_AMENDMENT_REQUEST,
        "You cannot request an activity cost review.",
    )
    if "replacementTotal" in data or "proposedTotal" in data:
        raise BadRequest(
            "Provide changed operational inputs and evidence, not a replacement total."
        )
    from apps.activities.models import Activity

    activity = Activity.objects.filter(id=activity_id, deleted_at__isnull=True).first()
    if activity is None:
        raise NotFoundError("Activity not found.")
    if not RolePermissionService.can_view_record(principal, activity):
        raise Forbidden("This activity is outside your portfolio.")
    reason = data.get("reasonCode")
    if reason not in CostReviewReason.values:
        raise BadRequest("Select a governed cost-review reason.")
    explanation = str(data.get("explanation") or "").strip()
    if not explanation:
        raise BadRequest("Explain the operational change that needs review.")
    snapshot = ActivityCostSnapshot.objects.filter(
        activity=activity, is_current=True
    ).first()
    if snapshot is None:
        raise BadRequest("The activity does not yet have an operational cost.")
    if ActivityCostReview.objects.filter(
        activity=activity,
        status__in=("submitted", "under_review", "amendment_required"),
    ).exists():
        raise BadRequest("A cost review for this activity is already unresolved.")
    proposed_inputs = {
        **snapshot.calculation_inputs,
        **(data.get("changedInputs") or {}),
    }
    proposed = calculate_dual(proposed_inputs)["operational"]
    with transaction.atomic():
        review = ActivityCostReview.objects.create(
            activity=activity,
            snapshot=snapshot,
            reason_code=reason,
            explanation=explanation,
            evidence=data.get("evidence") or [],
            proposed_inputs=proposed_inputs,
            current_operational_cost=snapshot.operational_cost,
            proposed_operational_cost=int(proposed.amount),
            requested_by=_user_id(principal),
        )
        audit_log(
            action="activity.cost_review.requested",
            subject_kind="ActivityCostReview",
            subject_id=review.id,
            actor_id=_user_id(principal),
            actor_role=getattr(principal, "active_role", None),
            payload={
                "activityId": activity.id,
                "currentOperationalCost": snapshot.operational_cost,
                "proposedOperationalCost": int(proposed.amount),
                "reasonCode": reason,
            },
            required=True,
        )
    _notify_cost_review(activity, review)
    return {
        "id": review.id,
        "status": review.status,
        "currentOperationalCost": review.current_operational_cost,
        "proposedOperationalCost": review.proposed_operational_cost,
        "difference": int(review.proposed_operational_cost or 0)
        - int(review.current_operational_cost),
    }


def decide_cost_review(principal, review_id: str, data: dict) -> dict:
    """Approve governed inputs or reject them; reviewers cannot enter totals."""
    _require(
        principal,
        Permission.COST_AMENDMENT_APPROVE,
        "You cannot decide activity cost reviews.",
    )
    decision = str(data.get("decision") or "").strip().lower()
    if decision not in ("approve", "reject"):
        raise BadRequest("decision must be approve or reject.")
    note = str(data.get("note") or "").strip()
    if decision == "reject" and not note:
        raise BadRequest("A rejection note is required.")

    from apps.budget.costing_service import apply_to_activity

    with transaction.atomic():
        review = (
            ActivityCostReview.objects.select_for_update()
            .select_related("activity", "snapshot")
            .filter(id=review_id)
            .first()
        )
        if review is None:
            raise NotFoundError("Activity cost review not found.")
        if review.status not in ("submitted", "under_review"):
            raise BadRequest("This cost review has already been resolved.")
        if review.requested_by == _user_id(principal):
            raise BadRequest("You cannot decide your own cost review.")

        if decision == "reject":
            review.status = "rejected"
            review.reviewed_by = _user_id(principal)
            review.review_note = note
            review.save(
                update_fields=["status", "reviewed_by", "review_note", "updated_at"]
            )
            audit_log(
                action="activity.cost_review.rejected",
                subject_kind="ActivityCostReview",
                subject_id=review.id,
                actor_id=_user_id(principal),
                actor_role=getattr(principal, "active_role", None),
                payload={"activityId": review.activity_id, "reason": note},
                required=True,
            )
            return {"id": review.id, "status": review.status}

        result = calculate_dual(review.proposed_inputs)
        if result["viability"] == "configuration_missing":
            raise BadRequest("The proposed inputs cannot be costed completely.")
        if result["viability"] == "below_approved_minimum":
            raise BadRequest("The proposed cost is below a governed approved minimum.")

        try:
            apply_to_activity(
                review.activity,
                {
                    **review.proposed_inputs,
                    "recalculationReason": (
                        f"Approved cost review {review.id}: {review.explanation}"
                    ),
                },
                responsible_user_id=_user_id(principal),
            )
        except BadRequest as exc:
            # Frozen funding is immutable. Hold the current payable lines and
            # route the proposed figure into the explicit amendment queue.
            finance_lock_markers = (
                "disbursed or accounted advance",
                "advance is already confirmed",
                "weekly fund request",
                "monthly fund request",
            )
            if not any(marker in str(exc).lower() for marker in finance_lock_markers):
                raise
            current = (
                ActivityCostSnapshot.objects.select_for_update()
                .filter(activity=review.activity, is_current=True)
                .first()
            )
            if current:
                current.cost_status = "amendment_required"
                current.save(update_fields=["cost_status", "updated_at"])
            review.status = "amendment_required"
            review.reviewed_by = _user_id(principal)
            review.review_note = note or str(exc)
            review.save(
                update_fields=["status", "reviewed_by", "review_note", "updated_at"]
            )
            audit_log(
                action="activity.cost_amendment.required",
                subject_kind="ActivityCostReview",
                subject_id=review.id,
                actor_id=_user_id(principal),
                actor_role=getattr(principal, "active_role", None),
                payload={
                    "activityId": review.activity_id,
                    "currentOperationalCost": review.current_operational_cost,
                    "proposedOperationalCost": review.proposed_operational_cost,
                    "reason": str(exc),
                },
                required=True,
            )
            return {
                "id": review.id,
                "status": review.status,
                "amendmentRequired": True,
            }

        review.status = "approved"
        review.reviewed_by = _user_id(principal)
        review.review_note = note
        review.save(
            update_fields=["status", "reviewed_by", "review_note", "updated_at"]
        )
        current = ActivityCostSnapshot.objects.filter(
            activity=review.activity, is_current=True
        ).first()
        audit_log(
            action="activity.cost_review.approved",
            subject_kind="ActivityCostReview",
            subject_id=review.id,
            actor_id=_user_id(principal),
            actor_role=getattr(principal, "active_role", None),
            payload={
                "activityId": review.activity_id,
                "previousOperationalCost": review.current_operational_cost,
                "newOperationalCost": current.operational_cost if current else None,
                "rateCardVersion": (
                    current.operational_rate_card.version
                    if current and current.operational_rate_card_id
                    else None
                ),
            },
            required=True,
        )
    return {
        "id": review.id,
        "status": review.status,
        "operationalCost": current.operational_cost if current else None,
        "amendmentRequired": False,
    }


def _notify_cost_review(activity, review) -> None:
    from apps.accounts.models import StaffProfile, User
    from apps.notifications.services import WorkflowNotificationService

    recipients = User.objects.filter(active_role="CountryDirector", is_active=True)
    owner = StaffProfile.objects.filter(id=activity.responsible_staff_id).first()
    if owner:
        from apps.accounts.models import StaffSupervisorAssignment

        supervisor_ids = StaffSupervisorAssignment.objects.filter(
            supervisee=owner
        ).values_list("supervisor__user_id", flat=True)
        recipients = User.objects.filter(
            Q(id__in=supervisor_ids) | Q(active_role="CountryDirector"), is_active=True
        )
    WorkflowNotificationService.trigger(
        event_type="activity_cost_review_requested",
        category="budget",
        priority="high",
        title="Activity cost review requested",
        body=f"Review the operational cost inputs for {activity.activity_name_snapshot or activity.activity_type}.",
        context_type="activity_cost_review",
        context_id=review.id,
        recipients=recipients,
    )


def reserve_summary(principal, *, fy: str | None = None) -> dict:
    _require(
        principal,
        Permission.STRATEGIC_RESERVE_VIEW,
        "Strategic reserve balances are restricted to authorized management roles.",
    )
    qs = CountryStrategicActivityReserve.objects.prefetch_related("activations")
    if fy:
        qs = qs.filter(fy=str(fy))
    return {
        "reserves": [
            {
                "id": reserve.id,
                "country": reserve.country,
                "fy": reserve.fy,
                "periodKey": reserve.period_key,
                "openingReserve": reserve.opening_reserve,
                "approvedAdditions": reserve.approved_additions,
                "clearedSavingsTransferred": reserve.cleared_savings_transferred,
                "amountCommitted": reserve.amount_committed,
                "amountDisbursed": reserve.amount_disbursed,
                "amountReturned": reserve.amount_returned,
                "availableBalance": reserve.available_balance,
                "status": reserve.status,
            }
            for reserve in qs.order_by("-fy", "period_key")
        ]
    }


def request_reserve_activation(principal, reserve_id: str, data: dict) -> dict:
    _require(
        principal,
        Permission.STRATEGIC_RESERVE_MANAGE,
        "Only the Country Director may initiate strategic reserve funding.",
    )
    from apps.activities.models import Activity

    try:
        requested_amount = int(data.get("requestedAmount"))
    except (TypeError, ValueError):
        raise BadRequest("requestedAmount must be a whole UGX value.")
    if requested_amount <= 0:
        raise BadRequest("requestedAmount must be greater than zero.")
    required = (
        "activityId",
        "reasonNormalFundingInsufficient",
        "expectedOutcome",
        "requiredImplementationDate",
        "alternativeConsidered",
    )
    if any(not data.get(key) for key in required):
        raise BadRequest("Complete every reserve activation justification field.")
    with transaction.atomic():
        reserve = (
            CountryStrategicActivityReserve.objects.select_for_update()
            .filter(id=reserve_id)
            .first()
        )
        if reserve is None:
            raise NotFoundError("Strategic reserve not found.")
        if reserve.status != "approved":
            raise BadRequest("Only an approved strategic reserve may be activated.")
        activity = Activity.objects.filter(id=data["activityId"]).first()
        if activity is None:
            raise NotFoundError("Activity not found.")
        if StrategicReserveActivation.objects.filter(
            reserve=reserve,
            activity=activity,
            status__in=(
                ReserveActivationStatus.AWAITING_CD,
                ReserveActivationStatus.AWAITING_RVP,
                ReserveActivationStatus.APPROVED,
                ReserveActivationStatus.DISBURSEMENT_PENDING,
                ReserveActivationStatus.DISBURSED,
            ),
        ).exists():
            raise BadRequest(
                "This activity already has an unresolved reserve activation."
            )
        if requested_amount > reserve.available_balance:
            raise BadRequest(
                "The requested amount exceeds the available reserve balance."
            )
        before = reserve.available_balance
        activation = StrategicReserveActivation.objects.create(
            reserve=reserve,
            activity=activity,
            reason_normal_funding_insufficient=data["reasonNormalFundingInsufficient"],
            operational_cost=activity.est_cost_cents,
            requested_amount=requested_amount,
            expected_outcome=data["expectedOutcome"],
            required_implementation_date=data["requiredImplementationDate"],
            alternative_considered=data["alternativeConsidered"],
            balance_before=before,
            balance_after=before - requested_amount,
            requested_by=_user_id(principal),
            status=ReserveActivationStatus.AWAITING_RVP,
            cd_approved_by=_user_id(principal),
        )
        audit_log(
            action="strategic_reserve.activation.requested",
            subject_kind="StrategicReserveActivation",
            subject_id=activation.id,
            actor_id=_user_id(principal),
            actor_role=getattr(principal, "active_role", None),
            payload={
                "activityId": activity.id,
                "requestedAmount": requested_amount,
                "balanceBefore": before,
                "balanceAfter": before - requested_amount,
            },
            required=True,
        )
    return {"id": activation.id, "status": activation.status}


def approve_reserve_activation(principal, activation_id: str) -> dict:
    _require(
        principal,
        Permission.STRATEGIC_RESERVE_APPROVE,
        "Only the RVP may approve strategic reserve activation.",
    )
    with transaction.atomic():
        activation = (
            StrategicReserveActivation.objects.select_for_update()
            .select_related("reserve")
            .filter(id=activation_id)
            .first()
        )
        if activation is None:
            raise NotFoundError("Strategic reserve activation not found.")
        if activation.status != ReserveActivationStatus.AWAITING_RVP:
            raise BadRequest("This reserve activation is not awaiting RVP approval.")
        reserve = CountryStrategicActivityReserve.objects.select_for_update().get(
            id=activation.reserve_id
        )
        if activation.requested_amount > reserve.available_balance:
            raise BadRequest(
                "The reserve balance changed and can no longer cover this request."
            )
        reserve.amount_committed += activation.requested_amount
        reserve.save(update_fields=["amount_committed", "updated_at"])
        activation.status = ReserveActivationStatus.APPROVED
        activation.rvp_approved_by = _user_id(principal)
        activation.balance_before = (
            reserve.available_balance + activation.requested_amount
        )
        activation.balance_after = reserve.available_balance
        activation.save(
            update_fields=[
                "status",
                "rvp_approved_by",
                "balance_before",
                "balance_after",
                "updated_at",
            ]
        )
        snapshot = (
            ActivityCostSnapshot.objects.select_for_update()
            .filter(activity=activation.activity, is_current=True)
            .first()
        )
        if snapshot:
            # The reserve is a funding source, not a second activity cost.
            # The authorized ceiling therefore remains the operational cost;
            # no duplicate payable line is minted.
            snapshot.approved_operating_limit = snapshot.operational_cost
            snapshot.cost_status = "approved"
            snapshot.approved_by = _user_id(principal)
            snapshot.approved_at = timezone.now()
            snapshot.save(
                update_fields=[
                    "approved_operating_limit",
                    "cost_status",
                    "approved_by",
                    "approved_at",
                    "updated_at",
                ]
            )
        audit_log(
            action="strategic_reserve.activation.approved",
            subject_kind="StrategicReserveActivation",
            subject_id=activation.id,
            actor_id=_user_id(principal),
            actor_role=getattr(principal, "active_role", None),
            payload={
                "requestedAmount": activation.requested_amount,
                "balanceAfter": reserve.available_balance,
            },
            required=True,
        )
    return {"id": activation.id, "status": activation.status}


__all__ = [
    "list_rate_cards",
    "create_rate_card_version",
    "upsert_rate_card_line",
    "publish_rate_card",
    "request_cost_review",
    "decide_cost_review",
    "reserve_summary",
    "request_reserve_activation",
    "approve_reserve_activation",
]
