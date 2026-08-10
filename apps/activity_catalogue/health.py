"""Operational integrity checks for the governed Activity Catalogue."""

from django.db.models import Count, Exists, F, OuterRef, Q
from django.utils import timezone

from apps.activities.models import Activity

from .models import (
    ActivityCatalogueItem,
    ActivityCatalogueReviewQueue,
    ActivityInterventionMapping,
    ActivityProjectMapping,
    CatalogueStatus,
    MappingMode,
)
from .seed_data import CATALOGUE_ITEMS


def catalogue_health() -> dict:
    active = ActivityCatalogueItem.objects.filter(status=CatalogueStatus.ACTIVE)
    missing_stable_code = ActivityCatalogueItem.objects.filter(
        Q(stable_code="") | Q(stable_code__isnull=True)
    )
    duplicate_stable_code = (
        ActivityCatalogueItem.objects.values("stable_code")
        .annotate(total=Count("id"))
        .filter(total__gt=1)
    )
    invalid_active_shape = active.filter(
        Q(activity_type="")
        | Q(delivery_method="")
        | Q(evidence_profile="")
        | Q(salesforce_record_type="")
        | Q(costing_profile="")
    )
    missing_mapping = active.annotate(
        live_mappings=Count(
            "intervention_mappings",
            filter=Q(intervention_mappings__active=True),
        )
    ).filter(live_mappings=0)
    bad_fixed = active.filter(
        intervention_mappings__active=True,
        intervention_mappings__mapping_mode__in=[
            MappingMode.FIXED,
            MappingMode.MULTIPLE_ALLOWED,
        ],
        intervention_mappings__intervention__isnull=True,
    ).distinct()
    dynamic_without_source_requirement = active.filter(
        intervention_mappings__active=True,
        intervention_mappings__mapping_mode=MappingMode.INHERIT_FROM_SOURCE_ACTIVITY,
        requires_source_activity=False,
    ).distinct()
    invalid_prerequisite_mapping = active.filter(
        intervention_mappings__active=True,
        intervention_mappings__mapping_mode=MappingMode.SSA_COMPLETION_PREREQUISITE,
        intervention_mappings__intervention__isnull=False,
    ).distinct()
    unsnapshotted = Activity.objects.filter(
        catalogue_item__isnull=False,
    ).filter(
        Q(catalogue_version__isnull=True)
        | Q(activity_name_snapshot="")
        | Q(evidence_profile_snapshot="")
        | Q(costing_profile_snapshot="")
    )
    legacy = Activity.objects.filter(
        catalogue_item__isnull=True,
        deleted_at__isnull=True,
    )
    review = ActivityCatalogueReviewQueue.objects.filter(status="needs_review")
    followup_without_source = Activity.objects.filter(
        catalogue_item__intervention_mappings__mapping_mode=MappingMode.INHERIT_FROM_SOURCE_ACTIVITY,
        catalogue_item__intervention_mappings__active=True,
        follow_up_of_activity__isnull=True,
    ).distinct()
    approved_project_rule = ActivityProjectMapping.objects.filter(
        catalogue_item_id=OuterRef("catalogue_item_id"),
        project_id=OuterRef("project_id"),
        active=True,
    )
    project_unapproved = (
        Activity.objects.filter(
            catalogue_item__isnull=False,
            project_id__isnull=False,
        )
        .annotate(approved_project=Exists(approved_project_rule))
        .filter(approved_project=False)
    )
    partner_disallowed = Activity.objects.filter(
        catalogue_item__isnull=False,
        delivery_type="partner",
        catalogue_item__partner_delivery_allowed=False,
    )
    staff_disallowed = Activity.objects.filter(
        catalogue_item__isnull=False,
        delivery_type="staff",
        catalogue_item__staff_delivery_allowed=False,
    )
    matching_intervention = ActivityInterventionMapping.objects.filter(
        catalogue_item_id=OuterRef("catalogue_item_id"),
        active=True,
        mapping_mode__in=[MappingMode.FIXED, MappingMode.MULTIPLE_ALLOWED],
        intervention=OuterRef("focus_intervention"),
    )
    inconsistent_intervention = (
        Activity.objects.filter(
            catalogue_item__intervention_mappings__mapping_mode__in=[
                MappingMode.FIXED,
                MappingMode.MULTIPLE_ALLOWED,
            ],
            catalogue_item__intervention_mappings__active=True,
        )
        .annotate(mapping_matches=Exists(matching_intervention))
        .filter(mapping_matches=False)
        .distinct()
    )
    from apps.partners.models import PartnerAssignment

    partner_assignment_review = ActivityCatalogueReviewQueue.objects.filter(
        source_model="partners.PartnerAssignment",
        source_record_id=OuterRef("id"),
        status="needs_review",
    )
    missing_partner_assignment = PartnerAssignment.objects.filter(
        assignment_mode="specific_activity",
        catalogue_item__isnull=True,
    )
    unqueued_partner_assignment = missing_partner_assignment.annotate(
        queued_for_review=Exists(partner_assignment_review)
    ).filter(queued_for_review=False)
    partner_assignment_disallowed = PartnerAssignment.objects.filter(
        catalogue_item__partner_delivery_allowed=False
    )
    invalid_partner_choice = (
        PartnerAssignment.objects.filter(
            assignment_mode="intervention_choice",
        )
        .annotate(approved_choices=Count("allowed_catalogue_items"))
        .filter(approved_choices=0)
    )
    partner_wrong_rate = (
        Activity.objects.filter(
            catalogue_item__isnull=False,
            delivery_type="partner",
            schedule_cost_lines__isnull=False,
        )
        .exclude(schedule_cost_lines__cost_setting_key__icontains="partner")
        .distinct()
    )
    staff_wrong_rate = (
        Activity.objects.filter(
            catalogue_item__isnull=False,
            delivery_type="staff",
            schedule_cost_lines__cost_setting_key__icontains="partner",
        )
        .exclude(
            # This is the governed rate for a staff-owned administrative meeting
            # with partners. "partner" describes the meeting/cost profile, not
            # the executor or funding path.
            catalogue_item__costing_profile="ADMIN_PARTNER_MEETING"
        )
        .distinct()
    )
    missing_cost_provenance = (
        Activity.objects.filter(
            catalogue_item__isnull=False,
            schedule_cost_lines__isnull=False,
        )
        .filter(
            Q(schedule_cost_lines__activity_catalogue_item_id__isnull=True)
            | ~Q(schedule_cost_lines__activity_catalogue_item_id=F("catalogue_item_id"))
            | Q(schedule_cost_lines__activity_catalogue_version__isnull=True)
            | Q(schedule_cost_lines__costing_profile__isnull=True)
        )
        .distinct()
    )
    admin_in_ssa_impact = Activity.objects.filter(
        catalogue_item__activity_type="admin",
    ).filter(
        Q(source_ssa__isnull=False)
        | (Q(focus_intervention__isnull=False) & ~Q(focus_intervention=""))
    )
    retired_used_for_new_planning = Activity.objects.filter(
        catalogue_item__status__in=[
            CatalogueStatus.INACTIVE,
            CatalogueStatus.RETIRED,
        ],
        created_at__gte=F("catalogue_item__updated_at"),
    )
    governed_codes = {row["stable_code"] for row in CATALOGUE_ITEMS}
    present_codes = set(
        ActivityCatalogueItem.objects.filter(
            stable_code__in=governed_codes
        ).values_list("stable_code", flat=True)
    )
    checks = [
        {
            "key": "catalogue_stable_code_required",
            "label": "Catalogue items without a stable code",
            "status": "pass" if not missing_stable_code.exists() else "fail",
            "count": missing_stable_code.count(),
        },
        {
            "key": "catalogue_stable_code_unique",
            "label": "Duplicate Catalogue stable codes",
            "status": "pass" if not duplicate_stable_code.exists() else "fail",
            "count": duplicate_stable_code.count(),
        },
        {
            "key": "catalogue_active_items",
            "label": "Complete governed 28-item Catalogue seed",
            "status": "pass" if present_codes == governed_codes else "fail",
            "count": len(present_codes),
        },
        {
            "key": "catalogue_active_shape",
            "label": "Active items missing type, delivery, evidence, Salesforce or costing metadata",
            "status": "pass" if not invalid_active_shape.exists() else "fail",
            "count": invalid_active_shape.count(),
        },
        {
            "key": "catalogue_missing_mapping",
            "label": "Active items missing an intervention classification",
            "status": "pass" if not missing_mapping.exists() else "fail",
            "count": missing_mapping.count(),
        },
        {
            "key": "catalogue_invalid_fixed_mapping",
            "label": "Fixed mappings without an approved intervention",
            "status": "pass" if not bad_fixed.exists() else "fail",
            "count": bad_fixed.count(),
        },
        {
            "key": "catalogue_dynamic_source_rule",
            "label": "Dynamic follow-up items not requiring a source Activity",
            "status": (
                "pass" if not dynamic_without_source_requirement.exists() else "fail"
            ),
            "count": dynamic_without_source_requirement.count(),
        },
        {
            "key": "catalogue_ssa_completion_shape",
            "label": "SSA Completion item incorrectly mapped as an intervention",
            "status": ("pass" if not invalid_prerequisite_mapping.exists() else "fail"),
            "count": invalid_prerequisite_mapping.count(),
        },
        {
            "key": "catalogue_snapshot_integrity",
            "label": "Catalogue Activities missing immutable snapshots",
            "status": "pass" if not unsnapshotted.exists() else "fail",
            "count": unsnapshotted.count(),
        },
        {
            "key": "catalogue_legacy_backfill",
            "label": "Legacy Activities awaiting Catalogue backfill",
            "status": "pass" if not legacy.exists() else "warn",
            "count": legacy.count(),
        },
        {
            "key": "catalogue_review_queue",
            "label": "Ambiguous Catalogue mappings awaiting review",
            "status": "pass" if not review.exists() else "warn",
            "count": review.count(),
        },
        {
            "key": "catalogue_followup_lineage",
            "label": "Dynamic follow-up missing source Activity",
            "status": "pass" if not followup_without_source.exists() else "fail",
            "count": followup_without_source.count(),
        },
        {
            "key": "catalogue_project_approval",
            "label": "Project Activity using an unapproved Catalogue item",
            "status": "pass" if not project_unapproved.exists() else "fail",
            "count": project_unapproved.count(),
        },
        {
            "key": "catalogue_partner_delivery",
            "label": "Partner Activity using a Partner-disallowed item",
            "status": "pass" if not partner_disallowed.exists() else "fail",
            "count": partner_disallowed.count(),
        },
        {
            "key": "catalogue_staff_delivery",
            "label": "Staff Activity using a staff-disallowed item",
            "status": "pass" if not staff_disallowed.exists() else "fail",
            "count": staff_disallowed.count(),
        },
        {
            "key": "catalogue_intervention_consistency",
            "label": "Activity intervention inconsistent with its fixed mapping",
            "status": ("pass" if not inconsistent_intervention.exists() else "fail"),
            "count": inconsistent_intervention.count(),
        },
        {
            "key": "catalogue_partner_assignment",
            "label": "Partner Assignment missing Catalogue reference without review",
            "status": ("pass" if not unqueued_partner_assignment.exists() else "fail"),
            "count": unqueued_partner_assignment.count(),
        },
        {
            "key": "catalogue_partner_assignment_review",
            "label": "Legacy Partner Assignment awaiting governed mapping review",
            "status": ("pass" if not missing_partner_assignment.exists() else "warn"),
            "count": missing_partner_assignment.count(),
        },
        {
            "key": "catalogue_partner_assignment_permission",
            "label": "Partner Assignment using a Partner-disallowed Catalogue item",
            "status": (
                "pass" if not partner_assignment_disallowed.exists() else "fail"
            ),
            "count": partner_assignment_disallowed.count(),
        },
        {
            "key": "catalogue_partner_choice_set",
            "label": "Partner intervention-choice Assignment without approved choices",
            "status": "pass" if not invalid_partner_choice.exists() else "fail",
            "count": invalid_partner_choice.count(),
        },
        {
            "key": "catalogue_partner_cost_rate",
            "label": "Partner Activity using a non-Partner cost rate",
            "status": "pass" if not partner_wrong_rate.exists() else "fail",
            "count": partner_wrong_rate.count(),
        },
        {
            "key": "catalogue_staff_cost_rate",
            "label": "Staff Activity using a Partner cost rate",
            "status": "pass" if not staff_wrong_rate.exists() else "fail",
            "count": staff_wrong_rate.count(),
        },
        {
            "key": "catalogue_cost_provenance",
            "label": "Cost line missing Activity Catalogue provenance",
            "status": "pass" if not missing_cost_provenance.exists() else "fail",
            "count": missing_cost_provenance.count(),
        },
        {
            "key": "catalogue_admin_ssa_impact",
            "label": "Administrative Activity incorrectly carrying SSA impact",
            "status": "pass" if not admin_in_ssa_impact.exists() else "fail",
            "count": admin_in_ssa_impact.count(),
        },
        {
            "key": "catalogue_retired_new_planning",
            "label": "Inactive or retired item used for new Planning",
            "status": (
                "pass" if not retired_used_for_new_planning.exists() else "fail"
            ),
            "count": retired_used_for_new_planning.count(),
        },
    ]
    detected_at = timezone.now().isoformat()
    for check in checks:
        check.update(
            {
                "severity": (
                    "critical"
                    if check["status"] == "fail"
                    else "warning"
                    if check["status"] == "warn"
                    else "none"
                ),
                "expected": "0 unresolved issues",
                "actual": check["count"],
                "owner": (
                    "Country Director / Catalogue Administrator"
                    if check["status"] != "pass"
                    else None
                ),
                "directCorrectionAction": (
                    "/settings/activity-catalogue/"
                    if check["status"] != "pass"
                    else None
                ),
                "detectedAt": detected_at,
                "resolutionStatus": (
                    "open" if check["status"] != "pass" else "resolved"
                ),
                "auditHistory": "Audit Log",
            }
        )
    return {
        "healthy": all(check["status"] != "fail" for check in checks),
        "checks": checks,
    }
