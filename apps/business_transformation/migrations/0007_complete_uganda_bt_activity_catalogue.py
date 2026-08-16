from django.db import migrations


ACTIVITIES = (
    ("BT_UG_BUSINESS_PLANNING_SUPPORT", "Business Planning Support", "financial_health", "school_visit"),
    ("BT_UG_EDTECH_LOAN_VERIFICATION", "EdTech Loan Verification", "financial_health", "school_visit"),
    ("BT_UG_FINANCIAL_HEALTH_FOLLOW_UP", "Financial Health Follow-Up", "financial_health", "school_visit"),
    ("BT_UG_GOVERNMENT_REQUIREMENTS_TRAINING", "Government Requirements Training", "government_requirement", "training"),
    ("BT_UG_SCHOOL_REGISTRATION_SUPPORT", "School Registration Support", "government_requirement", "school_visit"),
    ("BT_UG_TAXATION_SUPPORT", "Taxation Support", "government_requirement", "school_visit"),
    ("BT_UG_NSSF_SUPPORT", "NSSF Support", "government_requirement", "school_visit"),
    ("BT_UG_GOVERNMENT_REQUIREMENTS_FOLLOW_UP", "Government Requirements Follow-Up", "government_requirement", "school_visit"),
    ("BT_UG_MFI_MENTORSHIP", "MFI Mentorship Session", "financial_health", "school_visit"),
    ("BT_UG_MONTHLY_MFI_REVIEW", "Monthly MFI Review Meeting", "financial_health", "meeting"),
)


def seed_complete_catalogue(apps, schema_editor):
    Item = apps.get_model("activity_catalogue", "ActivityCatalogueItem")
    Mapping = apps.get_model("activity_catalogue", "ActivityInterventionMapping")
    Eligibility = apps.get_model("activity_catalogue", "ActivityEligibilityRule")
    for code, label, intervention, kind in ACTIVITIES:
        is_training = kind == "training"
        is_meeting = kind == "meeting"
        workflow_kind = (
            "in_school_training"
            if is_training
            else "cluster_meeting"
            if is_meeting
            else "school_visit"
        )
        activity_type = "training" if is_training else "admin" if is_meeting else "school_visit"
        delivery_method = (
            "in_school_training"
            if is_training
            else "cluster_meeting"
            if is_meeting
            else "school_visit"
        )
        item, _ = Item.objects.update_or_create(
            stable_code=code,
            defaults={
                "source_name": label,
                "display_name": label,
                "description": f"Governed Uganda Business Transformation activity: {label}.",
                "activity_type": activity_type,
                "delivery_method": delivery_method,
                "workflow_kind": workflow_kind,
                "target_audience": "School leaders and responsible staff",
                "status": "active",
                "staff_delivery_allowed": True,
                "partner_delivery_allowed": not is_meeting,
                "individual_school_allowed": not is_meeting,
                "cluster_delivery_allowed": is_training or is_meeting,
                "project_delivery_allowed": True,
                "requires_school": not is_meeting,
                "requires_current_ssa": code not in {
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
                "evidence_profile": "TRAINING_ATTENDANCE" if is_training else "SCHOOL_VISIT_FORM",
                "costing_profile": "IN_SCHOOL_TRAINING" if is_training else "STAFF_SCHOOL_VISIT",
                "support_objective": "BUSINESS_TRANSFORMATION",
                "follow_up_required": "FOLLOW_UP" not in code,
                "created_by": "migration",
                "updated_by": "migration",
            },
        )
        Mapping.objects.update_or_create(
            catalogue_item=item,
            intervention=intervention,
            mapping_mode="fixed",
            defaults={"priority": 10, "is_primary": True, "active": True},
        )
        Eligibility.objects.get_or_create(
            catalogue_item=item,
            defaults={
                "allowed_target_audiences": [item.target_audience],
                "counts_toward_entitlement": False,
            },
        )


def retire_complete_catalogue(apps, schema_editor):
    codes = [row[0] for row in ACTIVITIES]
    apps.get_model("activity_catalogue", "ActivityCatalogueItem").objects.filter(
        stable_code__in=codes
    ).update(status="retired")
    apps.get_model("activity_catalogue", "ActivityInterventionMapping").objects.filter(
        catalogue_item__stable_code__in=codes
    ).update(active=False)


class Migration(migrations.Migration):
    dependencies = [
        ("business_transformation", "0006_financialpracticeassessment_loanimpactassessment_and_more"),
        ("activity_catalogue", "0008_standard_in_school_training_no_participants"),
    ]

    operations = [migrations.RunPython(seed_complete_catalogue, retire_complete_catalogue)]
