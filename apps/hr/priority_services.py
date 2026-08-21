from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import BadRequest

from .models import (
    MilestoneDefinitionStatus,
    MilestoneMetricDefinition,
    PriorityMilestone,
    StrategicPriorityCycle,
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


def define_milestone(milestone, *, data: dict, principal):
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
    if data["measurementType"] in {"percentage", "ratio"} and not denominator:
        raise BadRequest("Percentage and ratio milestones require a denominator.")

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
    milestone.definition_status = MilestoneDefinitionStatus.APPROVED
    milestone.active = True
    milestone.save(
        update_fields=[
            "definition_status",
            "active",
            "updated_at",
        ]
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
