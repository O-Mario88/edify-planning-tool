"""Publish the governed Uganda Business Transformation reference data."""

from datetime import date

from django.db import migrations


LOAN_PURPOSES = (
    ("EDTECH", "Education technology", True),
    ("INFRASTRUCTURE", "School infrastructure", False),
    ("WORKING_CAPITAL", "Working capital", False),
    ("SCHOOL_EQUIPMENT", "School equipment", False),
    ("COMPLIANCE", "Government compliance", False),
    ("OTHER", "Other approved school purpose", False),
)

COMPLIANCE_REQUIREMENTS = (
    (
        "SCHOOL_REGISTRATION",
        "School registration",
        "Current registration with the relevant Uganda education authority.",
        "Valid registration certificate or official confirmation.",
    ),
    (
        "OPERATING_LICENCE",
        "Operating licence",
        "Current local or education-sector licence required to operate.",
        "Valid operating licence and renewal evidence where applicable.",
    ),
    (
        "URA_TAX",
        "URA tax compliance",
        "Registration and filings required by the Uganda Revenue Authority.",
        "TIN and current tax-compliance evidence appropriate to the school.",
    ),
    (
        "NSSF",
        "NSSF compliance",
        "Employer registration and remittances where the statutory threshold applies.",
        "NSSF registration and recent remittance evidence, or documented non-applicability.",
    ),
)

CATALOGUE_ITEMS = (
    {
        "stable_code": "BT_UG_FINANCIAL_HEALTH_TRAINING",
        "display_name": "Financial Health Training",
        "activity_type": "training",
        "delivery_method": "in_school_training",
        "workflow_kind": "in_school_training",
        "intervention": "financial_health",
        "requires_current_ssa": True,
        "salesforce_record_type": "TRAINING",
        "salesforce_expected_prefix": "TS-",
        "evidence_profile": "TRAINING_ATTENDANCE",
        "costing_profile": "IN_SCHOOL_TRAINING",
        "target_audience": "School leaders and finance staff",
        "description": "Uganda school-level financial-health capability building.",
    },
    {
        "stable_code": "BT_UG_ACCOUNTANT_TRAINING",
        "display_name": "School Accountant Training",
        "activity_type": "training",
        "delivery_method": "in_school_training",
        "workflow_kind": "in_school_training",
        "intervention": "financial_health",
        "requires_current_ssa": True,
        "salesforce_record_type": "TRAINING",
        "salesforce_expected_prefix": "TS-",
        "evidence_profile": "TRAINING_ATTENDANCE",
        "costing_profile": "IN_SCHOOL_TRAINING",
        "target_audience": "School accountants and finance staff",
        "description": "Practical records, cash-flow, budgeting, and reporting support.",
    },
    {
        "stable_code": "BT_UG_GOVERNMENT_REQUIREMENTS_SUPPORT",
        "display_name": "Government Requirements Support Visit",
        "activity_type": "school_visit",
        "delivery_method": "school_visit",
        "workflow_kind": "school_visit",
        "intervention": "government_requirement",
        "requires_current_ssa": True,
        "salesforce_record_type": "VISIT",
        "salesforce_expected_prefix": "VS-",
        "evidence_profile": "SCHOOL_VISIT_FORM",
        "costing_profile": "STAFF_SCHOOL_VISIT",
        "target_audience": "School leaders and administrators",
        "description": "Structured Uganda compliance-gap review and follow-up.",
    },
    {
        "stable_code": "BT_UG_LOAN_READINESS_ASSESSMENT",
        "display_name": "Loan Readiness Assessment",
        "activity_type": "school_visit",
        "delivery_method": "school_visit",
        "workflow_kind": "school_visit",
        "intervention": "financial_health",
        "requires_current_ssa": True,
        "salesforce_record_type": "VISIT",
        "salesforce_expected_prefix": "VS-",
        "evidence_profile": "SCHOOL_VISIT_FORM",
        "costing_profile": "STAFF_SCHOOL_VISIT",
        "target_audience": "School owners and finance staff",
        "description": "Readiness review before an optional independent MFI referral.",
    },
    {
        "stable_code": "BT_UG_LOAN_USE_VERIFICATION",
        "display_name": "Loan-Use Verification Visit",
        "activity_type": "school_visit",
        "delivery_method": "school_visit",
        "workflow_kind": "school_visit",
        "intervention": "financial_health",
        "requires_current_ssa": False,
        "salesforce_record_type": "VISIT",
        "salesforce_expected_prefix": "VS-",
        "evidence_profile": "SCHOOL_VISIT_FORM",
        "costing_profile": "STAFF_SCHOOL_VISIT",
        "target_audience": "School owners and finance staff",
        "description": "Post-disbursement verification of the approved use of loan proceeds.",
    },
    {
        "stable_code": "BT_UG_LOAN_IMPACT_ASSESSMENT",
        "display_name": "Loan Impact Assessment",
        "activity_type": "school_visit",
        "delivery_method": "school_visit",
        "workflow_kind": "school_visit",
        "intervention": "financial_health",
        "requires_current_ssa": False,
        "salesforce_record_type": "VISIT",
        "salesforce_expected_prefix": "VS-",
        "evidence_profile": "SCHOOL_VISIT_FORM",
        "costing_profile": "STAFF_SCHOOL_VISIT",
        "target_audience": "School owners and finance staff",
        "description": "Follow-up assessment of school-level outcomes after financing.",
    },
)


def publish_uganda_reference_data(apps, schema_editor):
    Policy = apps.get_model("business_transformation", "BusinessTransformationPolicy")
    Purpose = apps.get_model("business_transformation", "LoanPurpose")
    Compliance = apps.get_model("business_transformation", "ComplianceRequirement")
    Item = apps.get_model("activity_catalogue", "ActivityCatalogueItem")
    Mapping = apps.get_model("activity_catalogue", "ActivityInterventionMapping")
    Eligibility = apps.get_model("activity_catalogue", "ActivityEligibilityRule")
    Version = apps.get_model("activity_catalogue", "ActivityCatalogueVersion")

    for fy in ("2025", "2026", "2027"):
        Policy.objects.update_or_create(
            country_code="UG",
            fy=fy,
            defaults={
                "financial_health_max_score": 5.5,
                "government_requirements_max_score": 5.5,
                "loan_use_verification_days": 60,
                "active": True,
                "created_by": "migration",
            },
        )

    for code, label, is_edtech in LOAN_PURPOSES:
        Purpose.objects.update_or_create(
            code=code,
            defaults={"label": label, "is_edtech": is_edtech, "active": True},
        )

    for code, label, description, evidence in COMPLIANCE_REQUIREMENTS:
        Compliance.objects.update_or_create(
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

    for definition in CATALOGUE_ITEMS:
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
                "created_by": "migration",
                "updated_by": "migration",
            }
        )
        item, _ = Item.objects.update_or_create(
            stable_code=stable_code, defaults=defaults
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
                "allowed_target_audiences": [defaults["target_audience"]],
                "counts_toward_entitlement": False,
            },
        )
        Version.objects.get_or_create(
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
                    "salesforceExpectedPrefix": defaults["salesforce_expected_prefix"],
                    "evidenceProfile": defaults["evidence_profile"],
                    "costingProfile": defaults["costing_profile"],
                    "supportObjective": "BUSINESS_TRANSFORMATION",
                    "standardSupport": False,
                    "participantMode": "none",
                    "mappingModes": ["fixed"],
                    "interventions": [intervention],
                },
                "change_reason": "Initial Uganda Business Transformation workflow.",
                "created_by": "migration",
            },
        )


def unpublish_uganda_reference_data(apps, schema_editor):
    Item = apps.get_model("activity_catalogue", "ActivityCatalogueItem")
    Item.objects.filter(
        stable_code__in=[row["stable_code"] for row in CATALOGUE_ITEMS]
    ).update(status="retired")
    apps.get_model("activity_catalogue", "ActivityInterventionMapping").objects.filter(
        catalogue_item__stable_code__in=[row["stable_code"] for row in CATALOGUE_ITEMS]
    ).update(active=False)
    apps.get_model("business_transformation", "ComplianceRequirement").objects.filter(
        country_code="UG", code__in=[row[0] for row in COMPLIANCE_REQUIREMENTS]
    ).update(active=False)
    apps.get_model("business_transformation", "LoanPurpose").objects.filter(
        code__in=[row[0] for row in LOAN_PURPOSES]
    ).update(active=False)
    apps.get_model(
        "business_transformation", "BusinessTransformationPolicy"
    ).objects.filter(country_code="UG", fy__in=("2025", "2026", "2027")).update(
        active=False
    )


class Migration(migrations.Migration):
    dependencies = [
        ("business_transformation", "0001_initial"),
        ("activity_catalogue", "0008_standard_in_school_training_no_participants"),
    ]

    operations = [
        migrations.RunPython(
            publish_uganda_reference_data, unpublish_uganda_reference_data
        )
    ]
