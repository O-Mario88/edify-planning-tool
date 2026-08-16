"""Uganda Business Transformation reference data.

The governed policies, loan purposes, compliance requirements, and the BT
activity catalogue arrived through data migrations (0002, 0003, 0007), which
a flushed database never replays. `ensure_business_transformation_reference`
runs on `post_migrate` — emitted after `flush` as well as after `migrate` —
so those rows come back the moment they are removed.

The data constants stay in the migrations that first published them; this
module imports them so the restore and the migration cannot drift apart. It
only ever creates what is missing — a purpose an administrator deactivated or
a catalogue item governance retired is their decision, and a deploy must not
quietly walk it back.
"""

from __future__ import annotations

from datetime import date
from importlib import import_module

POLICY_FYS = ("2025", "2026", "2027")


def _migration(name: str):
    return import_module(f"apps.business_transformation.migrations.{name}")


def ensure_business_transformation_reference() -> None:
    from apps.activity_catalogue.models import (
        ActivityCatalogueItem,
        ActivityCatalogueVersion,
        ActivityEligibilityRule,
        ActivityInterventionMapping,
    )

    from .models import (
        BusinessTransformationPolicy,
        ComplianceRequirement,
        LoanPurpose,
    )

    seed = _migration("0002_seed_uganda_reference_data")
    governed = _migration("0003_governed_uganda_loan_purposes")
    complete = _migration("0007_complete_uganda_bt_activity_catalogue")

    for fy in POLICY_FYS:
        BusinessTransformationPolicy.objects.get_or_create(
            country_code="UG",
            fy=fy,
            defaults={
                "financial_health_max_score": 5.5,
                "government_requirements_max_score": 5.5,
                "loan_use_verification_days": 60,
                "active": True,
                "created_by": "reference_data",
            },
        )

    for code, label, is_edtech in governed.GOVERNED_PURPOSES:
        LoanPurpose.objects.get_or_create(
            code=code,
            defaults={"label": label, "is_edtech": is_edtech, "active": True},
        )
    # The legacy purposes exist only so historical loans keep a valid
    # reference; migration 0003 deactivated them, so a restore recreates
    # them inactive.
    for code, label, is_edtech in seed.LOAN_PURPOSES:
        LoanPurpose.objects.get_or_create(
            code=code,
            defaults={"label": label, "is_edtech": is_edtech, "active": False},
        )

    for code, label, description, evidence in seed.COMPLIANCE_REQUIREMENTS:
        ComplianceRequirement.objects.get_or_create(
            country_code="UG",
            code=code,
            defaults={
                "label": label,
                "description": description,
                "evidence_description": evidence,
                "effective_from": date(2025, 10, 1),
                "active": True,
            },
        )

    def _wire(item, intervention: str, target_audience: str) -> None:
        ActivityInterventionMapping.objects.get_or_create(
            catalogue_item=item,
            intervention=intervention,
            mapping_mode="fixed",
            defaults={"priority": 10, "is_primary": True, "active": True},
        )
        ActivityEligibilityRule.objects.get_or_create(
            catalogue_item=item,
            defaults={
                "allowed_target_audiences": [target_audience],
                "counts_toward_entitlement": False,
            },
        )

    # The first wave (migration 0002): school-level financial-health and
    # compliance workflows, plus their version-1 snapshots.
    for definition in seed.CATALOGUE_ITEMS:
        stable_code = definition["stable_code"]
        intervention = definition["intervention"]
        defaults = {
            key: value
            for key, value in definition.items()
            if key not in {"stable_code", "intervention"}
        }
        defaults.update(
            {
                "source_name": defaults["display_name"],
                "status": "active",
                "staff_delivery_allowed": True,
                "partner_delivery_allowed": False,
                "certified_agency_delivery_allowed": False,
                "individual_school_allowed": True,
                "cluster_delivery_allowed": False,
                "project_delivery_allowed": True,
                "standard_support": False,
                "requires_school": True,
                "requires_cluster": False,
                "requires_project": False,
                "non_school_allowed": False,
                "multi_day_allowed": False,
                "requires_participant_counts": False,
                "participant_mode": "none",
                "salesforce_id_required": True,
                "ia_verification_required": True,
                "programme_category": "Business Transformation Uganda",
                "support_objective": "BUSINESS_TRANSFORMATION",
                "follow_up_required": stable_code
                in {
                    "BT_UG_FINANCIAL_HEALTH_TRAINING",
                    "BT_UG_GOVERNMENT_REQUIREMENTS_SUPPORT",
                },
                "override_reason_required": True,
                "created_by": "reference_data",
                "updated_by": "reference_data",
            }
        )
        item, _ = ActivityCatalogueItem.objects.get_or_create(
            stable_code=stable_code, defaults=defaults
        )
        _wire(item, intervention, defaults["target_audience"])
        ActivityCatalogueVersion.objects.get_or_create(
            catalogue_item=item,
            version=1,
            defaults={
                "snapshot": {
                    "stableCode": stable_code,
                    "displayName": defaults["display_name"],
                    "activityType": defaults["activity_type"],
                    "deliveryMethod": defaults["delivery_method"],
                    "workflowKind": defaults["workflow_kind"],
                    "targetAudience": defaults["target_audience"],
                    "salesforceRecordType": defaults["salesforce_record_type"],
                    "salesforceExpectedPrefix": defaults[
                        "salesforce_expected_prefix"
                    ],
                    "evidenceProfile": defaults["evidence_profile"],
                    "costingProfile": defaults["costing_profile"],
                    "supportObjective": "BUSINESS_TRANSFORMATION",
                    "standardSupport": False,
                    "participantMode": "none",
                    "mappingModes": ["fixed"],
                    "interventions": [intervention],
                },
                "change_reason": "Initial Uganda Business Transformation workflow.",
                "created_by": "reference_data",
            },
        )

    # The completion wave (migration 0007): the remaining governed BT
    # workflows, including the cluster training and the venue meeting.
    for code, label, intervention, kind in complete.ACTIVITIES:
        is_training = kind == "training"
        is_meeting = kind == "meeting"
        workflow_kind = (
            "in_school_training"
            if is_training
            else "cluster_meeting"
            if is_meeting
            else "school_visit"
        )
        activity_type = (
            "training" if is_training else "admin" if is_meeting else "school_visit"
        )
        target_audience = "School leaders and responsible staff"
        item, _ = ActivityCatalogueItem.objects.get_or_create(
            stable_code=code,
            defaults={
                "source_name": label,
                "display_name": label,
                "description": (
                    f"Governed Uganda Business Transformation activity: {label}."
                ),
                "activity_type": activity_type,
                "delivery_method": workflow_kind,
                "workflow_kind": workflow_kind,
                "target_audience": target_audience,
                "status": "active",
                "staff_delivery_allowed": True,
                "partner_delivery_allowed": not is_meeting,
                "individual_school_allowed": not is_meeting,
                "cluster_delivery_allowed": is_training or is_meeting,
                "project_delivery_allowed": True,
                "requires_school": not is_meeting,
                "requires_current_ssa": code
                not in {
                    "BT_UG_EDTECH_LOAN_VERIFICATION",
                    "BT_UG_MONTHLY_MFI_REVIEW",
                },
                "non_school_allowed": is_meeting,
                "requires_participant_counts": is_training,
                "participant_mode": "direct_total" if is_training else "none",
                "salesforce_id_required": True,
                "ia_verification_required": True,
                "programme_category": "Business Transformation Uganda",
                "salesforce_record_type": "TRAINING" if is_training else "VISIT",
                "salesforce_expected_prefix": "TS-" if is_training else "VS-",
                "evidence_profile": (
                    "TRAINING_ATTENDANCE" if is_training else "SCHOOL_VISIT_FORM"
                ),
                "costing_profile": (
                    "IN_SCHOOL_TRAINING" if is_training else "STAFF_SCHOOL_VISIT"
                ),
                "support_objective": "BUSINESS_TRANSFORMATION",
                "follow_up_required": "FOLLOW_UP" not in code,
                "created_by": "reference_data",
                "updated_by": "reference_data",
            },
        )
        _wire(item, intervention, target_audience)


def business_transformation_reference_is_complete() -> bool:
    """Read-only counterpart to ``ensure_business_transformation_reference``."""
    from apps.activity_catalogue.models import ActivityCatalogueItem

    from .models import (
        BusinessTransformationPolicy,
        ComplianceRequirement,
        LoanPurpose,
    )

    seed = _migration("0002_seed_uganda_reference_data")
    governed = _migration("0003_governed_uganda_loan_purposes")
    complete = _migration("0007_complete_uganda_bt_activity_catalogue")

    expected_codes = {row["stable_code"] for row in seed.CATALOGUE_ITEMS} | {
        row[0] for row in complete.ACTIVITIES
    }
    present = set(
        ActivityCatalogueItem.objects.filter(
            stable_code__in=expected_codes
        ).values_list("stable_code", flat=True)
    )
    if present != expected_codes:
        return False
    if (
        BusinessTransformationPolicy.objects.filter(
            country_code="UG", fy__in=POLICY_FYS
        ).count()
        < len(POLICY_FYS)
    ):
        return False
    purpose_codes = {row[0] for row in governed.GOVERNED_PURPOSES} | {
        row[0] for row in seed.LOAN_PURPOSES
    }
    if (
        LoanPurpose.objects.filter(code__in=purpose_codes).count()
        < len(purpose_codes)
    ):
        return False
    return (
        ComplianceRequirement.objects.filter(
            country_code="UG",
            code__in=[row[0] for row in seed.COMPLIANCE_REQUIREMENTS],
        ).count()
        == len(seed.COMPLIANCE_REQUIREMENTS)
    )
