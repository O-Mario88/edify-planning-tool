"""Seed the Uganda Master Priority Plan from the normalized source data.

Creates the COUNTRY-level translation of each FY2027 regional priority group
(parent link preserved, so the cascade walks back to the RVP direction) and
one milestone per confirmed Uganda figure, carrying the Core/Client split,
participants-per-school guidance, allocation method and confirmation flags.

Everything lands in DRAFT: the CD reviews the flagged rows in the Target
Distribution workspace, confirms each figure, then publishes and locks the
master (§14). Idempotent reruns repair draft source-owned fields, but never
rewrite a published master. Published figures and activation state change only
through the governed amendment workflow.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction

from apps.activity_catalogue.models import (
    ActivityCatalogueItem,
    ActivityCatalogueReviewQueue,
)
from apps.core.exceptions import BadRequest

from .models import (
    MilestoneActivityRule,
    MilestoneTargetComponent,
    MilestoneDefinitionStatus,
    MilestoneMetricDefinition,
    MilestoneType,
    PriorityMilestone,
    StrategicPriority,
    StrategicPriorityCycle,
    StrategicPriorityLevel,
    StrategicPriorityStatus,
)
from .uganda_master_seed import NON_SCOREABLE, SOURCE_DOCUMENT, UGANDA_MASTER

UGANDA = "Uganda"


def _metric_definitions() -> dict[str, MilestoneMetricDefinition]:
    """The metric vocabulary the Uganda master binds to — reusing the three
    regional definitions and adding the coverage/participants/manual ones the
    country figures need."""

    existing = {
        definition.metric_key: definition
        for definition in MilestoneMetricDefinition.objects.filter(
            metric_key__in=[
                "verified_activity_catalogue_progress",
                "verified_new_school_onboarding",
                "verified_new_core_school_onboarding",
            ]
        )
    }
    coverage, _ = MilestoneMetricDefinition.objects.update_or_create(
        metric_key="uganda_portfolio_coverage",
        defaults={
            "canonical_label": "Verified portfolio coverage",
            "description": (
                "Unique schools reached by qualifying verified activities, as a "
                "share of the holder's eligible portfolio."
            ),
            "source_models": ["activities.Activity", "schools.School"],
            "canonical_service": "apps.hr.milestone_progress.refresh_period_targets",
            "numerator_definition": "Unique schools with a qualifying IA-verified activity.",
            "denominator_definition": "Eligible portfolio schools (allocation denominator).",
            "included_states": ["ia_verified", "accountant_confirmed", "closed"],
            "excluded_states": ["cancelled", "rejected", "deferred"],
            "date_basis": "Activity planned_date",
            "financial_year_basis": "Activity fy",
            "counting_basis": "PERCENT_OF_ELIGIBLE_SCHOOLS",
            "quality_gate": "IA verified",
            "rounding_rule": "Whole schools; percentage to 1dp",
            "null_behavior": "Zero, never fabricated",
            "provisional_behavior": "Exclude from official coverage",
            "verified_behavior": "Include",
        },
    )
    participants, _ = MilestoneMetricDefinition.objects.update_or_create(
        metric_key="uganda_verified_participants",
        defaults={
            "canonical_label": "Verified training participants",
            "description": "Attended participants on IA-verified trainings.",
            "source_models": ["activities.Activity"],
            "canonical_service": "apps.hr.milestone_progress.refresh_period_targets",
            "numerator_definition": (
                "Sum of verified attended participants (teachers/leaders) on "
                "qualifying activities."
            ),
            "denominator_definition": "Approved allocation target.",
            "included_states": ["ia_verified", "accountant_confirmed", "closed"],
            "excluded_states": ["cancelled", "rejected", "deferred"],
            "date_basis": "Activity planned_date",
            "financial_year_basis": "Activity fy",
            "counting_basis": "TEACHERS_TRAINED",
            "quality_gate": "IA verified attendance",
            "rounding_rule": "Whole participants",
            "null_behavior": "Zero, never fabricated",
            "provisional_behavior": "Exclude — planned attendance never counts",
            "verified_behavior": "Include",
        },
    )
    manual, _ = MilestoneMetricDefinition.objects.update_or_create(
        metric_key="uganda_country_office_record",
        defaults={
            "canonical_label": "Country office verified record",
            "description": (
                "Country-owned commitments (board meetings, compliance, MFI "
                "work) evidenced by country office records; no automated "
                "source yet, so actuals stay at zero until one is defined — "
                "never fabricated."
            ),
            "source_models": [],
            "canonical_service": "",
            "numerator_definition": "Verified country office records.",
            "denominator_definition": "Confirmed Uganda target.",
            "included_states": [],
            "excluded_states": [],
            "date_basis": "Record date",
            "financial_year_basis": "Operational FY",
            "counting_basis": "MANUAL_RECORD",
            "quality_gate": "CD/IA review",
            "rounding_rule": "Whole units",
            "null_behavior": "Zero, never fabricated",
            "provisional_behavior": "Exclude",
            "verified_behavior": "Include",
        },
    )
    return {
        "activity": existing.get("verified_activity_catalogue_progress"),
        "school": existing.get("verified_new_school_onboarding"),
        "core_school": existing.get("verified_new_core_school_onboarding"),
        "coverage": coverage,
        "participants": participants,
        "manual": manual,
    }


@transaction.atomic
def seed_uganda_master(*, fy: str = "2027", actor_id="system", dry_run=False) -> dict:
    cycle = StrategicPriorityCycle.objects.filter(financial_year=fy).first()
    if cycle is None:
        raise BadRequest(
            f"No FY{fy} strategic cycle exists — seed the regional priorities "
            "first (seed_fy2027_priorities)."
        )
    regional_by_code = {
        priority.code: priority
        for priority in StrategicPriority.objects.filter(
            cycle=cycle, level=StrategicPriorityLevel.REGIONAL
        )
    }
    metrics = _metric_definitions()
    report = {
        "priorities": 0,
        "milestones": 0,
        "needsConfirmation": 0,
        "nonScoreable": 0,
        "rules": 0,
        "queuedMappings": 0,
        "skippedPublished": 0,
    }
    for sequence, (group_code, rows) in enumerate(UGANDA_MASTER.items(), 1):
        regional = regional_by_code.get(group_code)
        # 2026-08-20 priorities audit G3/A3: the milestone loop below already
        # skips published priorities, but this header write did NOT — a
        # reseed rewrote a PUBLISHED priority's title/cycle/parent/source
        # fields. A published header is part of the locked master.
        _published = StrategicPriority.objects.filter(
            fy=fy,
            level=StrategicPriorityLevel.COUNTRY,
            code=group_code,
            country_id=UGANDA,
            status=StrategicPriorityStatus.PUBLISHED,
        ).first()
        if _published is not None:
            # Keep the locked header untouched; the row loop below already
            # handles milestone-level skipping for published priorities.
            priority = _published
            report["skippedPublished"] += 1
        else:
            priority, _ = StrategicPriority.objects.update_or_create(
                fy=fy,
                level=StrategicPriorityLevel.COUNTRY,
                code=group_code,
                country_id=UGANDA,
                defaults={
                    "cycle": cycle,
                    "parent": regional,
                    "title": (regional.title if regional else group_code.title()),
                    "source_title": regional.title if regional else group_code,
                    "source_document": SOURCE_DOCUMENT,
                    "source_reference": f"uganda-priority-{sequence}",
                    "strategic_purpose": (
                        "Uganda's confirmed contribution to the regional priority "
                        f"“{regional.title if regional else group_code}”."
                    ),
                    "expected_result": (
                        "Confirmed Uganda targets distributed IA → PL → CCEO and "
                        "delivered through verified activities."
                    ),
                    "author_id": actor_id,
                    "sequence": sequence,
                },
            )
        report["priorities"] += 1
        for source_order, row in enumerate(rows, 1):
            scoreable = (
                row["method"] != NON_SCOREABLE
                and row["target"] is not None
                and row.get("metric")
            )
            metric = metrics.get(row["metric"]) if row.get("metric") else None
            needs_confirmation = bool(row.get("confirm"))
            # Publication is the governance lock. A deployment or manual seed
            # rerun must never put an approved milestone back into the
            # inactive/defined state or replace a CD-confirmed figure with the
            # original source-file default. Newly introduced source rows also
            # wait for the next master cycle instead of appearing silently in
            # an already-published plan.
            if priority.status == StrategicPriorityStatus.PUBLISHED:
                milestone = PriorityMilestone.objects.filter(
                    priority=priority, code=row["code"]
                ).first()
                report["skippedPublished"] += 1
                if milestone is not None:
                    report["milestones"] += 1
                continue
            # 2026-08-20 audit: a HUMAN-touched row survives a reseed even
            # before publication. confirm_milestone/define_milestone bump
            # `version` past 1 — a CD confirmation or redefinition must not
            # be replaced by the source-file default on the next deploy.
            _touched = PriorityMilestone.objects.filter(
                priority=priority, code=row["code"], version__gt=1
            ).first()
            if _touched is not None:
                milestone = _touched
                report["milestones"] += 1
                report["skippedPublished"] += 1
                continue
            milestone, _ = PriorityMilestone.objects.update_or_create(
                priority=priority,
                code=row["code"],
                defaults={
                    "title": row["title"],
                    "source_text": row["source_text"],
                    "description": row.get("note", ""),
                    "milestone_type": MilestoneType.OUTPUT,
                    "measurement_type": row["measurement"],
                    "progress_source": (
                        metric.metric_key if metric else "NEEDS_DEFINITION"
                    ),
                    "metric_definition": metric if scoreable else None,
                    "target_value": (
                        Decimal(str(row["target"]))
                        if row["target"] is not None
                        else None
                    ),
                    "target_unit": row["unit"],
                    "target_source_text": row["source_text"],
                    "core_target": (
                        Decimal(str(row["core"]))
                        if row.get("core") is not None
                        else None
                    ),
                    "client_target": (
                        Decimal(str(row["client"]))
                        if row.get("client") is not None
                        else None
                    ),
                    "participants_per_school": row.get("pps"),
                    "recurrence_per_month": (
                        Decimal(str(row["recurrence_per_month"]))
                        if row.get("recurrence_per_month") is not None
                        else None
                    ),
                    "due_date": row.get("due_date"),
                    "allocation_method": row["method"],
                    "responsible_role": row.get("role", ""),
                    "cap_at_100": bool(row.get("cap_100")),
                    "needs_confirmation": needs_confirmation,
                    "confirmation_note": row.get("confirm", "") or "",
                    "denominator_definition": (
                        "Eligible portfolio schools"
                        if row["measurement"] == "percentage"
                        else ""
                    ),
                    "quality_gate": "IA verified" if scoreable else "",
                    "role_applicability": ([row["role"]] if row.get("role") else []),
                    "country_applicability": [UGANDA],
                    "requires_definition": not scoreable,
                    "definition_status": (
                        MilestoneDefinitionStatus.DEFINED
                        if scoreable
                        else MilestoneDefinitionStatus.NEEDS_DEFINITION
                    ),
                    "active": False,
                    "source_order": source_order,
                },
            )
            for _ci, _comp in enumerate(row.get("components") or [], 1):
                MilestoneTargetComponent.objects.update_or_create(
                    milestone=milestone,
                    code=_comp["code"],
                    defaults={
                        "label": _comp["label"],
                        "target_value": Decimal(str(_comp["value"])),
                        "target_unit": _comp.get("unit", ""),
                        "sequence": _ci,
                        "needs_confirmation": bool(_comp.get("confirm")),
                        "confirmation_note": _comp.get("confirm", "") or "",
                    },
                )
            report["milestones"] += 1
            if needs_confirmation:
                report["needsConfirmation"] += 1
            if row["method"] == NON_SCOREABLE:
                report["nonScoreable"] += 1
            for stable_code, overrides in row.get("catalogue", []):
                item = ActivityCatalogueItem.objects.filter(
                    stable_code=stable_code
                ).first()
                if item is None:
                    ActivityCatalogueReviewQueue.objects.get_or_create(
                        review_kind="missing_activity_catalogue_mapping",
                        source_model="hr.PriorityMilestone",
                        source_record_id=milestone.id,
                        defaults={
                            "source_value": row["source_text"],
                            "candidate_codes": [stable_code],
                        },
                    )
                    report["queuedMappings"] += 1
                    continue
                MilestoneActivityRule.objects.update_or_create(
                    milestone=milestone,
                    catalogue_item=item,
                    project=None,
                    defaults={
                        "counting_basis": row.get("basis", "VERIFIED_ACTIVITIES"),
                        "required_executor_type": overrides.get("executor", ""),
                        "school_type": overrides.get("school_type", ""),
                        "minimum_completion_state": "ia_verified",
                        "weight": 1,
                        "active": True,
                    },
                )
                report["rules"] += 1
    # The country master supersedes nothing regional — both stay visible; the
    # regional rows remain the RVP contract above the Uganda plan.
    StrategicPriority.objects.filter(
        fy=fy, level=StrategicPriorityLevel.COUNTRY, country_id=UGANDA
    ).exclude(status=StrategicPriorityStatus.PUBLISHED).update(
        status=StrategicPriorityStatus.DRAFT
    )
    if dry_run:
        transaction.set_rollback(True)
    return report
