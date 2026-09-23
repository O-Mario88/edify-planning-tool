from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import ProtectedError
from django.utils import timezone

from apps.core.exceptions import BadRequest, Forbidden
from apps.core.rbac import Permission

from .models import (
    MilestoneAllocationMethod,
    MilestoneDefinitionStatus,
    MilestoneMetricDefinition,
    MilestoneProgressCredit,
    PriorityMilestone,
    StrategicPriority,
    StrategicPriorityCycle,
    StrategicPriorityStatus,
)


@transaction.atomic
def _assert_priority_not_published(milestone) -> None:
    """2026-08-20 priorities audit G4: publication locks the master. A
    published priority's milestones must not be redefined, re-activated or
    re-weighted through the definition surfaces — later changes go through
    the amendment workflow, which records old value, new value, reason and
    actor."""
    from apps.core.exceptions import BadRequest as _BadRequest

    from .models import StrategicPriorityStatus

    priority = getattr(milestone, "priority", None)
    if priority is not None and priority.status == StrategicPriorityStatus.PUBLISHED:
        raise _BadRequest(
            "This priority is published and locked — changes to its "
            "milestones require an amendment, not a redefinition."
        )


#: The audit action a milestone definition writes; approval reads it back to
#: find who defined the milestone (IA review, 2026-09-13).
MILESTONE_DEFINED = "priorities.milestone.defined"
MILESTONE_APPROVED = "priorities.milestone.approved"


def _actor_id(principal) -> str:
    return str(
        getattr(principal, "id", None) or getattr(principal, "user_id", None) or ""
    )


def _definition_payload(metric) -> dict:
    if metric is None:
        return {}
    return {
        "metric_key": metric.metric_key,
        "canonical_label": metric.canonical_label,
        "canonical_service": metric.canonical_service,
        "numerator": metric.numerator_definition,
        "denominator": metric.denominator_definition,
        "date_basis": metric.date_basis,
        "counting_basis": metric.counting_basis,
        "quality_gate": metric.quality_gate,
    }


def defined_by(milestone) -> str:
    """Who last defined `milestone`, from its audit trail ("" when unknown —
    a seed or management command defines without a person)."""
    from apps.audit.models import AuditLog

    return (
        AuditLog.objects.filter(
            action=MILESTONE_DEFINED,
            subject_kind="PriorityMilestone",
            subject_id=str(milestone.pk),
        )
        .order_by("-created_at")
        .values_list("actor_id", flat=True)
        .first()
        or ""
    )


def define_milestone(milestone, *, data: dict, principal):
    """Define a milestone's measure.

    IA review (2026-09-13): the definition is audited with its actor and the
    before/after of the shared metric definition — a metric key is shared, so
    redefining it for one milestone changes it for every milestone that uses
    the key, and the audit row names how many do. Approval reads the actor
    back: whoever defined a milestone does not approve it.
    """
    milestone = (
        PriorityMilestone.objects.select_for_update(of=("self",))
        .select_related("priority")
        .get(pk=milestone.pk)
    )
    _assert_priority_not_published(milestone)
    required = {
        "canonicalTitle": "Canonical title",
        "metricKey": "Metric key",
        "measurementType": "Measurement type",
        "targetValue": "Target",
        "targetUnit": "Unit",
        "dataSource": "Data source",
        "canonicalService": "Canonical service",
        "qualityGate": "Quality gate",
        "dueDate": "Due date",
    }
    missing = [label for key, label in required.items() if not data.get(key)]
    roles = data.get("responsibleRoles") or []
    if isinstance(roles, str):
        roles = [role.strip() for role in roles.split(",") if role.strip()]
    if not roles:
        missing.append("Responsible roles")
    if missing:
        raise BadRequest("Definition is incomplete: " + ", ".join(missing) + ".")
    try:
        target = Decimal(str(data["targetValue"]))
    except Exception as exc:
        raise BadRequest("Target must be numeric.") from exc
    if target <= 0:
        raise BadRequest("Target must be greater than zero.")
    denominator = (data.get("denominatorDefinition") or "").strip()
    from apps.hr.milestone_progress import RATE_MEASUREMENT_TYPES

    if data["measurementType"] in RATE_MEASUREMENT_TYPES and not denominator:
        raise BadRequest("Percentage and ratio milestones require a denominator.")

    before = _definition_payload(
        MilestoneMetricDefinition.objects.filter(
            metric_key=data["metricKey"].strip()
        ).first()
    )
    metric, _ = MilestoneMetricDefinition.objects.update_or_create(
        metric_key=data["metricKey"].strip(),
        defaults={
            "canonical_label": data["canonicalTitle"].strip(),
            "description": (data.get("metricDescription") or "").strip(),
            "source_models": data.get("sourceModels") or [data["dataSource"]],
            "canonical_service": data["canonicalService"].strip(),
            "numerator_definition": (data.get("numeratorDefinition") or "").strip(),
            "denominator_definition": denominator,
            "included_states": data.get("includedStates") or [],
            "excluded_states": data.get("excludedStates") or [],
            "date_basis": (data.get("dateBasis") or "").strip(),
            "financial_year_basis": (
                data.get("financialYearBasis") or "Operational FY"
            ).strip(),
            "counting_basis": (data.get("countingBasis") or "").strip(),
            "quality_gate": data["qualityGate"].strip(),
            "rounding_rule": (data.get("roundingRule") or "Whole units").strip(),
            "null_behavior": (data.get("nullBehavior") or "Zero").strip(),
            "provisional_behavior": (
                data.get("provisionalBehavior") or "Exclude"
            ).strip(),
            "verified_behavior": (data.get("verifiedBehavior") or "Include").strip(),
        },
    )
    milestone.title = data["canonicalTitle"].strip()
    milestone.measurement_type = data["measurementType"]
    milestone.progress_source = data["dataSource"]
    milestone.metric_definition = metric
    milestone.target_value = target
    milestone.target_unit = data["targetUnit"].strip()
    milestone.denominator_definition = denominator
    milestone.quality_gate = data["qualityGate"].strip()
    milestone.role_applicability = roles
    milestone.due_date = data["dueDate"]
    milestone.requires_definition = False
    milestone.definition_status = MilestoneDefinitionStatus.DEFINED
    milestone.active = False
    milestone.version += 1
    milestone.save()
    from apps.audit.services import log as audit_log

    audit_log(
        action=MILESTONE_DEFINED,
        subject_kind="PriorityMilestone",
        subject_id=str(milestone.pk),
        actor_id=_actor_id(principal) or None,
        actor_role=getattr(principal, "active_role", None),
        payload={
            "version": milestone.version,
            "before": before,
            "after": _definition_payload(metric),
            "shared_with_milestones": PriorityMilestone.objects.filter(
                metric_definition=metric
            )
            .exclude(pk=milestone.pk)
            .count(),
        },
    )
    return milestone


@transaction.atomic
def approve_milestone(milestone, *, principal):
    milestone = (
        PriorityMilestone.objects.select_for_update(of=("self",))
        .select_related("priority")
        .get(pk=milestone.pk)
    )
    _assert_priority_not_published(milestone)
    if (
        milestone.requires_definition
        or milestone.definition_status != MilestoneDefinitionStatus.DEFINED
        or not milestone.metric_definition_id
        or not milestone.target_value
        or not milestone.due_date
        or not milestone.role_applicability
    ):
        raise BadRequest("Only a complete, defined milestone may be approved.")
    approver = _actor_id(principal)
    definer = defined_by(milestone)
    if approver and definer and approver == definer:
        # The same separation as every other definition on the platform: the
        # person who decided how a milestone is measured is not the person
        # who approves that decision.
        raise Forbidden(
            "You defined this milestone, so someone else approves its definition."
        )
    milestone.definition_status = MilestoneDefinitionStatus.APPROVED
    milestone.active = True
    milestone.save(
        update_fields=[
            "definition_status",
            "active",
            "updated_at",
        ]
    )
    from apps.audit.services import log as audit_log

    audit_log(
        action=MILESTONE_APPROVED,
        subject_kind="PriorityMilestone",
        subject_id=str(milestone.pk),
        actor_id=approver or None,
        actor_role=getattr(principal, "active_role", None),
        payload={"version": milestone.version, "defined_by": definer},
    )
    return milestone


@transaction.atomic
def approve_cycle(cycle, *, principal):
    cycle = StrategicPriorityCycle.objects.select_for_update().get(pk=cycle.pk)
    if not cycle.priorities.exists():
        raise BadRequest("A priority cycle cannot be approved without priorities.")
    invalid_active = PriorityMilestone.objects.filter(
        priority__cycle=cycle,
        active=True,
    ).exclude(definition_status=MilestoneDefinitionStatus.APPROVED)
    if invalid_active.exists():
        raise BadRequest("Every active milestone must be approved.")
    cycle.status = "approved"
    cycle.approved_at = timezone.now()
    cycle.locked_at = timezone.now()
    cycle.updated_by = getattr(principal, "user_id", None)
    cycle.save(
        update_fields=[
            "status",
            "approved_at",
            "locked_at",
            "updated_by",
            "updated_at",
        ]
    )
    return cycle


# ─── Editing and removing priorities from the Priority Setting tab ──────────
#
# Owner (2026-09-14): "Priority setting is in CD but cannot be edited. Make
# sure the numbers/targets are editable from CD and IA only. The PL gets the
# number they need to distribute to their team members… CD and IA can edit or
# delete a priority in case they don't want to work on that specific priority
# this FY."
#
# The number lives on the milestone row (target, unit, Core/Client split,
# participants guidance, allocation method, due date, title); the priority
# group is its parent. Editing here changes the MASTER figure only — the
# allocations already distributed from it keep their figures until they are
# amended through request_amendment / approve_amendment, which is where the
# Program Lead's and the CCEO's numbers are governed.

MILESTONE_TARGETS_EDITED = "priorities.milestone.targets_edited"
MILESTONE_REMOVED = "priorities.milestone.removed"
PRIORITY_REMOVED = "priorities.priority.removed"

_CENT = Decimal("0.01")


def _assert_priority_editor(principal) -> None:
    """Who may edit a figure or remove a priority from the FY.

    Read from the permission matrix (strategicPriorities.edit — the Country
    Director, Impact Assessment and the RVP hold it; a Program Lead holds
    view and their own team allocation only), never from a role string. That
    is SEC-03's lesson, the one target_distribution._assert_master_editor
    applies: a hard-coded comparison here would be a second copy of the
    matrix to keep in step with the first.
    """
    from apps.core.permissions import has_permission

    if not has_permission(principal, Permission.STRATEGIC_PRIORITIES_EDIT.value):
        raise Forbidden(
            "Priority targets are set by the Country Director and Impact Assessment."
        )


def _text(value) -> str | None:
    return None if value is None else str(value)


def _decimal_or_none(data: dict, key: str, label: str) -> Decimal | None:
    raw = data.get(key)
    if raw in (None, ""):
        return None
    try:
        value = Decimal(str(raw).replace(",", "").strip()).quantize(_CENT)
    except (InvalidOperation, ValueError) as exc:
        raise BadRequest(f"{label} must be a number.") from exc
    if value < 0:
        raise BadRequest(f"{label} cannot be negative.")
    return value


def _int_or_none(data: dict, key: str, label: str) -> int | None:
    raw = data.get(key)
    if raw in (None, ""):
        return None
    try:
        value = int(str(raw).strip())
    except ValueError as exc:
        raise BadRequest(f"{label} must be a whole number.") from exc
    if value < 0:
        raise BadRequest(f"{label} cannot be negative.")
    return value


def _date_or_none(raw) -> date | None:
    if raw in (None, ""):
        return None
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw).strip())
    except ValueError as exc:
        raise BadRequest("Due date must be a date (YYYY-MM-DD).") from exc


def milestone_targets(milestone) -> dict:
    """The editable figures of a milestone, as the audit trail records them."""
    return {
        "title": milestone.title,
        "target_value": _text(milestone.target_value),
        "target_unit": milestone.target_unit,
        "core_target": _text(milestone.core_target),
        "client_target": _text(milestone.client_target),
        "participants_per_school": milestone.participants_per_school,
        "allocation_method": milestone.allocation_method,
        "due_date": milestone.due_date.isoformat() if milestone.due_date else None,
    }


def _require_reason(reason, *, what: str) -> str:
    reason = (reason or "").strip()
    if not reason:
        raise BadRequest(f"Say why {what}. The reason is recorded with the change.")
    return reason


@transaction.atomic
def edit_milestone_targets(milestone, *, data: dict, principal):
    """An editor changes a milestone's figures from the Priority Setting tab.

    Keys arrive as the form posts them (targetValue, coreTarget, clientTarget,
    participantsPerSchool, allocationMethod, targetUnit, dueDate, title,
    reason); only the keys present are applied, so a caller may change one
    figure without restating the rest.

    PUBLICATION (product decision, 2026-09-14): a published priority's
    milestone may still be edited by an editor — the owner asked for the
    numbers to be editable by the CD and IA, and publication is when the
    Program Leads start distributing them, which is exactly when a figure
    turns out to need correcting. What publication changes is the record: the
    edit must carry a non-empty ``reason``, which goes into the audit payload
    beside the before/after figures and the actor's role. The definition
    surfaces (define_milestone, approve_milestone) stay locked by
    _assert_priority_not_published — a metric is not a number.

    Editing the master figure never touches a MilestoneAllocation: those
    change only through the amendment workflow (request_amendment /
    approve_amendment), which records their own old value, new value, reason
    and approver. The audit row carries how many approved allocations were
    standing when the master moved, so the gap is visible.
    """
    _assert_priority_editor(principal)
    milestone = (
        PriorityMilestone.objects.select_for_update(of=("self",))
        .select_related("priority")
        .get(pk=milestone.pk)
    )
    before = milestone_targets(milestone)
    published = milestone.priority.status == StrategicPriorityStatus.PUBLISHED
    reason = (data.get("reason") or "").strip()
    if published and not reason:
        raise BadRequest(
            "This priority is published: say why the figure is changing. The "
            "reason is recorded against the change."
        )

    if "title" in data:
        title = (data.get("title") or "").strip()
        if not title:
            raise BadRequest("A milestone needs a title.")
        milestone.title = title[:255]
    if "targetValue" in data:
        milestone.target_value = _decimal_or_none(data, "targetValue", "Target")
    if "targetUnit" in data:
        milestone.target_unit = (data.get("targetUnit") or "").strip()[:64]
    if "coreTarget" in data:
        milestone.core_target = _decimal_or_none(data, "coreTarget", "Core target")
    if "clientTarget" in data:
        milestone.client_target = _decimal_or_none(
            data, "clientTarget", "Client target"
        )
    if "participantsPerSchool" in data:
        milestone.participants_per_school = _int_or_none(
            data, "participantsPerSchool", "Participants per school"
        )
    if "allocationMethod" in data:
        method = (data.get("allocationMethod") or "").strip()
        if method and method not in MilestoneAllocationMethod.values:
            raise BadRequest("Unknown allocation method.")
        milestone.allocation_method = method
    if "dueDate" in data:
        milestone.due_date = _date_or_none(data.get("dueDate"))

    scoreable = milestone.allocation_method != MilestoneAllocationMethod.NON_SCOREABLE
    if scoreable and (milestone.target_value is None or milestone.target_value <= 0):
        raise BadRequest(
            "Target must be greater than zero — or mark the milestone "
            "non-scoreable to keep it without a figure."
        )
    if milestone.core_target is not None or milestone.client_target is not None:
        split = (milestone.core_target or 0) + (milestone.client_target or 0)
        if milestone.target_value is not None and split > milestone.target_value:
            raise BadRequest(
                "Core and Client are shares of the target: together they "
                "cannot exceed it."
            )

    after = milestone_targets(milestone)
    changed = sorted(key for key in after if after[key] != before[key])
    if not changed:
        raise BadRequest("Nothing changed — the figures are as they were.")
    milestone.version += 1
    milestone.save()

    allocations = milestone.allocations.all()
    from apps.audit.services import log as audit_log

    audit_log(
        action=MILESTONE_TARGETS_EDITED,
        subject_kind="PriorityMilestone",
        subject_id=str(milestone.pk),
        actor_id=_actor_id(principal) or None,
        actor_role=getattr(principal, "active_role", None),
        payload={
            "version": milestone.version,
            "priority_id": milestone.priority_id,
            "priority_code": milestone.priority.code,
            "priority_status": milestone.priority.status,
            "fy": milestone.priority.fy,
            "code": milestone.code,
            "changed": changed,
            "before": before,
            "after": after,
            "reason": reason,
            "allocations": allocations.count(),
            "approved_allocations": allocations.filter(status="approved").count(),
        },
    )
    return milestone


def milestone_dependants(milestone) -> list[str]:
    """What stops a milestone leaving the FY, in the words the editor reads.

    Allocations and period targets PROTECT the milestone at the database, and
    a progress credit PROTECTS the activity rule the milestone would cascade
    away — but "ProtectedError" is not a sentence. Each is named so the editor
    knows what to withdraw first.
    """
    reasons = []
    allocations = milestone.allocations.count()
    if allocations:
        reasons.append(
            f"{allocations} allocation{'s' if allocations != 1 else ''} already "
            "distributed"
        )
    periods = milestone.period_targets.count()
    if periods:
        reasons.append(f"{periods} phased period target{'s' if periods != 1 else ''}")
    credits = MilestoneProgressCredit.objects.filter(rule__milestone=milestone).count()
    if credits:
        reasons.append(f"{credits} progress credit{'s' if credits != 1 else ''}")
    return reasons


def _assert_milestone_removable(milestone) -> None:
    reasons = milestone_dependants(milestone)
    if reasons:
        raise BadRequest(
            f"{milestone.title} has {', '.join(reasons)}. Withdraw them first — "
            "a milestone with distributed targets cannot be removed from the FY."
        )


def _milestone_snapshot(milestone) -> dict:
    priority = milestone.priority
    return {
        "milestone_id": str(milestone.pk),
        "code": milestone.code,
        "title": milestone.title,
        "fy": priority.fy,
        "level": priority.level,
        "country_id": priority.country_id,
        "priority_id": str(priority.pk),
        "priority_code": priority.code,
        "priority_title": priority.title,
        "priority_status": priority.status,
        "source_text": milestone.source_text,
        "measurement_type": milestone.measurement_type,
        "definition_status": milestone.definition_status,
        "metric_key": getattr(milestone.metric_definition, "metric_key", None),
        "version": milestone.version,
        "targets": milestone_targets(milestone),
    }


def _priority_snapshot(priority, milestones) -> dict:
    return {
        "priority_id": str(priority.pk),
        "code": priority.code,
        "title": priority.title,
        "fy": priority.fy,
        "level": priority.level,
        "country_id": priority.country_id,
        "status": priority.status,
        "cycle_id": priority.cycle_id,
        "version": priority.version,
        "strategic_purpose": priority.strategic_purpose,
        "weight_min": priority.weight_min,
        "weight_max": priority.weight_max,
        "milestones": [
            {
                "milestone_id": str(m.pk),
                "code": m.code,
                "title": m.title,
                "targets": milestone_targets(m),
            }
            for m in milestones
        ],
        "role_rules": [
            {
                "role": rule.role,
                "accountability": rule.accountability,
                "metric_key": rule.metric_key,
                "default_weight": rule.default_weight,
            }
            for rule in priority.role_rules.all()
        ],
    }


def _log_removal(
    action: str, *, subject_kind: str, subject_id: str, principal, payload
):
    from apps.audit.services import log as audit_log

    audit_log(
        action=action,
        subject_kind=subject_kind,
        subject_id=subject_id,
        actor_id=_actor_id(principal) or None,
        actor_role=getattr(principal, "active_role", None),
        payload=payload,
    )


@transaction.atomic
def remove_milestone(milestone, *, principal, reason: str) -> dict:
    """Take one milestone out of the FY for good.

    Hard-deleted, because a milestone nobody will work on this year is not a
    record to keep scoring against — but only when nothing depends on it. An
    allocation, a phased period target or a credited progress row means a
    Program Lead or a CCEO already holds a number from it, and that number is
    withdrawn through its own workflow first. Components and activity rules
    cascade away with the row; the audit row keeps the snapshot.
    """
    _assert_priority_editor(principal)
    reason = _require_reason(reason, what="this milestone is leaving the FY")
    milestone = (
        PriorityMilestone.objects.select_for_update(of=("self",))
        .select_related("priority", "metric_definition")
        .get(pk=milestone.pk)
    )
    _assert_milestone_removable(milestone)
    snapshot = _milestone_snapshot(milestone)
    try:
        milestone.delete()
    except ProtectedError as exc:
        raise BadRequest(
            f"{snapshot['title']} is still referenced by other records and "
            "cannot be removed from the FY yet."
        ) from exc
    _log_removal(
        MILESTONE_REMOVED,
        subject_kind="PriorityMilestone",
        subject_id=snapshot["milestone_id"],
        principal=principal,
        payload={**snapshot, "reason": reason},
    )
    return snapshot


@transaction.atomic
def remove_priority(priority, *, principal, reason: str) -> dict:
    """Take a whole priority group — and every milestone under it — out of
    the FY, when the CD and IA will not work on it this year.

    Every milestone must be removable on its own terms (see remove_milestone);
    one distributed figure keeps the whole group. Milestones and role rules
    cascade from the priority at the database, so they are snapshotted
    FIRST, and one audit row is written per removed object: each milestone,
    then the priority with its milestone codes and titles.
    """
    _assert_priority_editor(principal)
    reason = _require_reason(reason, what="this priority is leaving the FY")
    priority = StrategicPriority.objects.select_for_update(of=("self",)).get(
        pk=priority.pk
    )
    # The model orders by source_order alone, and milestones added by hand
    # share its default, so the audit payload listed them in whatever order
    # the database returned. Creation order breaks the tie.
    milestones = list(
        priority.milestones.select_related("priority", "metric_definition").order_by(
            "source_order", "created_at", "id"
        )
    )
    blocked = []
    for milestone in milestones:
        dependants = milestone_dependants(milestone)
        if dependants:
            blocked.append(f"{milestone.title} ({', '.join(dependants)})")
    if blocked:
        raise BadRequest(
            f"{priority.title} cannot be removed from FY{priority.fy}: "
            + "; ".join(blocked)
            + ". Withdraw those first — a priority with distributed targets "
            "stays in the FY."
        )
    snapshot = _priority_snapshot(priority, milestones)
    milestone_snapshots = [_milestone_snapshot(m) for m in milestones]
    try:
        priority.delete()
    except ProtectedError as exc:
        raise BadRequest(
            f"{snapshot['title']} is still referenced by other records and "
            "cannot be removed from the FY yet."
        ) from exc
    for row in milestone_snapshots:
        _log_removal(
            MILESTONE_REMOVED,
            subject_kind="PriorityMilestone",
            subject_id=row["milestone_id"],
            principal=principal,
            payload={
                **row,
                "reason": reason,
                "removed_with_priority": snapshot["priority_id"],
            },
        )
    _log_removal(
        PRIORITY_REMOVED,
        subject_kind="StrategicPriority",
        subject_id=snapshot["priority_id"],
        principal=principal,
        payload={**snapshot, "reason": reason},
    )
    return snapshot
