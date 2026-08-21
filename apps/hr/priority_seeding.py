from __future__ import annotations

from decimal import Decimal

from django.db import transaction

from apps.activity_catalogue.models import (
    ActivityCatalogueItem,
    ActivityCatalogueReviewQueue,
)

from .models import (
    MilestoneActivityRule,
    MilestoneDefinitionStatus,
    MilestoneMetricDefinition,
    MilestoneType,
    PriorityMilestone,
    StrategicPriority,
    StrategicPriorityCycle,
    StrategicPriorityLevel,
    StrategicPriorityStatus,
)
from .priority_seed import ACTIVITY_MAPPINGS, PRIORITIES, ROLE_APPLICABILITY


@transaction.atomic
def seed_fy2027_priorities(*, actor_id="system", dry_run=False):
    # Create-only (audit G3): re-running must never reset an approved or
    # locked cycle back to draft.
    cycle = StrategicPriorityCycle.objects.filter(financial_year="2027").first()
    if cycle is None:
        cycle = StrategicPriorityCycle.objects.create(
            financial_year="2027",
            title="FY2027 RVP Strategic Priorities",
            scope_type="regional",
            status="draft",
            version=1,
            created_by=actor_id,
            updated_by=actor_id,
        )
    activity_metric, _ = MilestoneMetricDefinition.objects.update_or_create(
        metric_key="verified_activity_catalogue_progress",
        defaults={
            "canonical_label": "Verified Activity Catalogue progress",
            "description": "One deduplicated credit per qualifying canonical Activity.",
            "source_models": ["activities.Activity"],
            "canonical_service": "apps.hr.milestone_progress.record_activity_progress",
            "numerator_definition": "Qualifying IA-verified canonical Activities under explicit milestone rules.",
            "denominator_definition": "Approved allocation target.",
            "included_states": ["ia_verified", "accountant_confirmed", "closed"],
            "excluded_states": ["cancelled", "rejected", "deferred"],
            "date_basis": "Activity planned_date",
            "financial_year_basis": "Activity fy",
            "counting_basis": "Explicit MilestoneActivityRule",
            "quality_gate": "IA verified",
            "rounding_rule": "Whole credits",
            "null_behavior": "Zero, never fabricated",
            "provisional_behavior": "Label provisional; exclude from official score",
            "verified_behavior": "Include in official progress",
        },
    )
    school_metric, _ = MilestoneMetricDefinition.objects.update_or_create(
        metric_key="verified_new_school_onboarding",
        defaults={
            "canonical_label": "Verified new School onboarding",
            "description": "Unique Schools first activated in the measurement FY.",
            "source_models": ["schools.School"],
            "canonical_service": "apps.analytics.school_growth",
            "numerator_definition": "Unique verified School directory records first activated in the FY.",
            "denominator_definition": "Approved country or regional allocation.",
            "included_states": ["active"],
            "excluded_states": ["deleted", "duplicate"],
            "date_basis": "School activation/onboarding date",
            "financial_year_basis": "Activation date FY",
            "counting_basis": "DISTINCT_SCHOOLS",
            "quality_gate": "Verified School Directory record",
            "rounding_rule": "Whole unique Schools",
            "null_behavior": "Zero",
            "provisional_behavior": "Exclude",
            "verified_behavior": "Include",
        },
    )
    core_school_metric, _ = MilestoneMetricDefinition.objects.update_or_create(
        metric_key="verified_new_core_school_onboarding",
        defaults={
            "canonical_label": "Verified new Core School onboarding",
            "description": "Unique Schools first activated as Core in the measurement FY.",
            "source_models": ["schools.School", "core_schools.CorePlan"],
            "canonical_service": "apps.analytics.school_growth",
            "numerator_definition": "Unique verified Schools activated into the Core programme in the FY.",
            "denominator_definition": "Approved country or regional allocation.",
            "included_states": ["active"],
            "excluded_states": ["deleted", "duplicate"],
            "date_basis": "Core activation date",
            "financial_year_basis": "Activation date FY",
            "counting_basis": "DISTINCT_CORE_SCHOOLS",
            "quality_gate": "Verified Core programme record",
            "rounding_rule": "Whole unique Schools",
            "null_behavior": "Zero",
            "provisional_behavior": "Exclude",
            "verified_behavior": "Include",
        },
    )
    report = {"priorities": 0, "milestones": 0, "needsDefinition": 0, "rules": 0}
    for priority_order, (code, title, milestones) in enumerate(PRIORITIES, 1):
        # 2026-08-20 priorities audit G3: this runs from the reference-data
        # registry on EVERY post_migrate. `status` in the defaults was
        # UN-PUBLISHING a published RVP priority on every deploy — exactly
        # what the registry contract ("only ever create what is missing —
        # never update or delete") forbids. Existing rows are now left
        # exactly as they are; only genuinely missing rows are created.
        priority = StrategicPriority.objects.filter(
            fy="2027",
            level=StrategicPriorityLevel.REGIONAL,
            code=code,
            country_id=None,
        ).first()
        if priority is None:
            priority = StrategicPriority.objects.create(
                fy="2027",
                level=StrategicPriorityLevel.REGIONAL,
                code=code,
                country_id=None,
                cycle=cycle,
                title=title,
                source_title=title,
                source_document="2027 priorities to be set by RVP.docx",
                source_reference=f"priority-{priority_order}",
                strategic_purpose=title,
                expected_result="Defined through approved milestone metrics and allocations.",
                status=StrategicPriorityStatus.DRAFT,
                author_id=actor_id,
                sequence=priority_order,
                version=1,
            )
        report["priorities"] += 1
        for source_order, raw in enumerate(milestones, 1):
            milestone_code, source_text, target_value, source_kind = raw
            defined = target_value is not None and source_kind != "needs_definition"
            # Same create-only contract as the priority above (audit G3):
            # a defined/approved/confirmed milestone must survive deploys.
            _existing = PriorityMilestone.objects.filter(
                priority=priority, code=milestone_code
            ).first()
            if _existing is not None:
                milestone = _existing
                report["milestones"] += 1
                continue
            milestone, _ = PriorityMilestone.objects.update_or_create(
                priority=priority,
                code=milestone_code,
                defaults={
                    "title": source_text.split(" — ")[0],
                    "source_text": source_text,
                    "description": "",
                    "milestone_type": (
                        MilestoneType.OUTCOME
                        if code == "PROGRAM_GROWTH_AND_EXPANSION"
                        else MilestoneType.OUTPUT
                    ),
                    "measurement_type": "count" if defined else "manual_assessment",
                    "progress_source": (
                        "SCHOOL_DIRECTORY"
                        if milestone_code == "NEW_SCHOOLS"
                        else "CORE_SCHOOL"
                        if milestone_code == "NEW_CORE_SCHOOLS"
                        else "NEEDS_DEFINITION"
                    ),
                    "metric_definition": (
                        school_metric
                        if milestone_code == "NEW_SCHOOLS" and defined
                        else core_school_metric
                        if milestone_code == "NEW_CORE_SCHOOLS" and defined
                        else activity_metric
                        if defined
                        else None
                    ),
                    "target_value": (
                        Decimal(target_value) if target_value is not None else None
                    ),
                    "target_unit": (
                        source_kind if source_kind != "needs_definition" else ""
                    ),
                    "target_source_text": source_text,
                    "denominator_definition": "",
                    "quality_gate": "Verified source record" if defined else "",
                    "role_applicability": ROLE_APPLICABILITY[code],
                    "requires_definition": not defined,
                    "definition_status": (
                        MilestoneDefinitionStatus.DEFINED
                        if defined
                        else MilestoneDefinitionStatus.NEEDS_DEFINITION
                    ),
                    "active": False,
                    "version": 1,
                    "source_order": source_order,
                },
            )
            report["milestones"] += 1
            if not defined:
                report["needsDefinition"] += 1
            mapped_codes = ACTIVITY_MAPPINGS.get(milestone_code, [])
            for stable_code in mapped_codes:
                item = ActivityCatalogueItem.objects.filter(
                    stable_code=stable_code
                ).first()
                if item is None:
                    ActivityCatalogueReviewQueue.objects.get_or_create(
                        review_kind="missing_activity_catalogue_mapping",
                        source_model="hr.PriorityMilestone",
                        source_record_id=milestone.id,
                        defaults={
                            "source_value": source_text,
                            "candidate_codes": [stable_code],
                        },
                    )
                    continue
                MilestoneActivityRule.objects.get_or_create(
                    milestone=milestone,
                    catalogue_item=item,
                    project=None,
                    defaults={
                        "counting_basis": "UNIQUE_SCHOOLS_SUPPORTED",
                        "target_intervention": (
                            item.intervention_mappings.filter(
                                active=True, intervention__isnull=False
                            )
                            .values_list("intervention", flat=True)
                            .first()
                            or ""
                        ),
                        "minimum_completion_state": "ia_verified",
                        "weight": 1,
                        "active": True,
                    },
                )
                report["rules"] += 1

            if milestone_code in {"IDE", "DC_TRAINING"}:
                ActivityCatalogueReviewQueue.objects.get_or_create(
                    review_kind="missing_activity_catalogue_mapping",
                    source_model="hr.PriorityMilestone",
                    source_record_id=milestone.id,
                    defaults={"source_value": source_text, "candidate_codes": []},
                )
    if dry_run:
        transaction.set_rollback(True)
    return report
