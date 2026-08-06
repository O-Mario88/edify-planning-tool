import json

from django.core.management.base import BaseCommand
from django.db import models, transaction
from django.utils import timezone

from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.partners.models import PartnerAssignment
from apps.activity_catalogue.models import (
    ActivityCatalogueAlias,
    ActivityCatalogueItem,
    ActivityCatalogueReviewQueue,
)
from apps.activity_catalogue.seeding import normalize_alias
from apps.activity_catalogue.services import apply_catalogue_snapshot


class Command(BaseCommand):
    help = "Deterministically backfill historical Activity catalogue references."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--batch-size", type=int, default=500)

    @transaction.atomic
    def handle(self, *args, **options):
        report = {
            "activitiesScanned": 0,
            "referencedActivitiesRepaired": 0,
            "costLinesProvenanceStamped": 0,
            "partnerAssignmentsScanned": 0,
            "exactMatches": 0,
            "deterministicNormalizedMatches": 0,
            "deterministicSignatureMatches": 0,
            "ambiguousMatches": 0,
            "unmatchedActivities": 0,
            "unmatchedPartnerAssignments": 0,
            "backfilled": 0,
            "partnerAssignmentsBackfilled": 0,
            "skipped": 0,
            "errors": 0,
        }
        aliases = {}
        for alias in ActivityCatalogueAlias.objects.select_related("catalogue_item"):
            aliases.setdefault(alias.normalized_alias, []).append(alias.catalogue_item)
        costed_activities = (
            Activity.objects.filter(
                catalogue_item__isnull=False,
                schedule_cost_lines__isnull=False,
            )
            .select_related("catalogue_item")
            .distinct()
        )
        for activity in costed_activities.iterator(chunk_size=options["batch_size"]):
            stamped = (
                ActivityScheduleCostLine.objects.filter(
                    activity=activity,
                )
                .filter(
                    models.Q(activity_catalogue_item_id__isnull=True)
                    | ~models.Q(activity_catalogue_item_id=activity.catalogue_item_id)
                    | models.Q(activity_catalogue_version__isnull=True)
                    | models.Q(costing_profile__isnull=True)
                )
                .update(
                    activity_catalogue_item_id=activity.catalogue_item_id,
                    activity_catalogue_version=activity.catalogue_version,
                    costing_profile=activity.costing_profile_snapshot,
                )
            )
            report["costLinesProvenanceStamped"] += stamped
        referenced = (
            Activity.objects.filter(catalogue_item__isnull=False)
            .filter(
                models.Q(catalogue_version__isnull=True)
                | models.Q(activity_name_snapshot__isnull=True)
                | models.Q(activity_name_snapshot="")
                | models.Q(evidence_profile_snapshot__isnull=True)
                | models.Q(evidence_profile_snapshot="")
                | models.Q(costing_profile_snapshot__isnull=True)
                | models.Q(costing_profile_snapshot="")
            )
            .select_related("catalogue_item", "source_ssa", "follow_up_of_activity")
        )
        for activity in referenced.iterator(chunk_size=options["batch_size"]):
            report["activitiesScanned"] += 1
            try:
                apply_catalogue_snapshot(
                    activity,
                    item=activity.catalogue_item,
                    source_ssa=activity.source_ssa,
                    requested_intervention=activity.focus_intervention,
                    source_activity=activity.follow_up_of_activity,
                    recommendation_reason=(
                        activity.recommendation_reason
                        or "Historical referenced Catalogue snapshot repair."
                    ),
                    override_reason=activity.override_reason or "Historical repair",
                    recommendation_source=activity.recommendation_source,
                )
                report["referencedActivitiesRepaired"] += 1
            except Exception:
                report["errors"] += 1
                ActivityCatalogueReviewQueue.objects.get_or_create(
                    review_kind="referenced_snapshot_repair_error",
                    source_model="activities.Activity",
                    source_record_id=activity.id,
                    defaults={
                        "source_value": activity.catalogue_item.stable_code,
                        "candidate_codes": [activity.catalogue_item.stable_code],
                    },
                )
        qs = Activity.objects.filter(
            catalogue_item__isnull=True, deleted_at__isnull=True
        ).iterator(chunk_size=options["batch_size"])
        for activity in qs:
            report["activitiesScanned"] += 1
            source_value = (
                activity.activity_name_snapshot
                or activity.activity_purpose_text
                or activity.get_activity_type_display()
            )
            candidates = aliases.get(normalize_alias(source_value), [])
            match_basis = "normalized_alias"
            if not candidates:
                signature = ActivityCatalogueItem.objects.filter(
                    workflow_kind=activity.activity_type
                )
                if activity.activity_type_snapshot:
                    signature = signature.filter(
                        activity_type=activity.activity_type_snapshot
                    )
                if activity.delivery_method_snapshot:
                    signature = signature.filter(
                        delivery_method=activity.delivery_method_snapshot
                    )
                if activity.focus_intervention:
                    signature = signature.filter(
                        intervention_mappings__active=True,
                        intervention_mappings__intervention=activity.focus_intervention,
                    )
                if activity.project_id:
                    signature = signature.filter(
                        project_mappings__project_id=activity.project_id,
                        project_mappings__active=True,
                    )
                candidates = list(signature.distinct()[:2])
                match_basis = "catalogue_signature"
            if len(candidates) != 1:
                kind = "ambiguous_activity" if candidates else "unmatched_activity"
                key = "ambiguousMatches" if candidates else "unmatchedActivities"
                report[key] += 1
                ActivityCatalogueReviewQueue.objects.get_or_create(
                    review_kind=kind,
                    source_model="activities.Activity",
                    source_record_id=activity.id,
                    defaults={
                        "source_value": source_value,
                        "candidate_codes": [c.stable_code for c in candidates],
                    },
                )
                continue
            item = candidates[0]
            if match_basis == "normalized_alias":
                report["deterministicNormalizedMatches"] += 1
            else:
                report["deterministicSignatureMatches"] += 1
            try:
                historical_name = activity.activity_name_snapshot
                historical_evidence = activity.evidence_profile_snapshot
                apply_catalogue_snapshot(
                    activity,
                    item=item,
                    requested_intervention=activity.focus_intervention,
                    recommendation_reason="Historical deterministic catalogue backfill.",
                    source_activity=activity.follow_up_of_activity,
                    override_reason="Historical backfill",
                )
                preserved_fields = []
                if historical_name:
                    activity.activity_name_snapshot = historical_name
                    preserved_fields.append("activity_name_snapshot")
                if historical_evidence:
                    activity.evidence_profile_snapshot = historical_evidence
                    preserved_fields.append("evidence_profile_snapshot")
                if preserved_fields:
                    activity.save(update_fields=[*preserved_fields, "updated_at"])
                report["backfilled"] += 1
                ActivityCatalogueReviewQueue.objects.filter(
                    source_model="activities.Activity",
                    source_record_id=activity.id,
                    status="needs_review",
                ).update(
                    status="resolved",
                    resolution_note=(f"Resolved deterministically by {match_basis}."),
                    resolved_by="system-backfill",
                    resolved_at=timezone.now(),
                )
            except Exception:
                report["errors"] += 1
                ActivityCatalogueReviewQueue.objects.get_or_create(
                    review_kind="backfill_error",
                    source_model="activities.Activity",
                    source_record_id=activity.id,
                    defaults={
                        "source_value": source_value,
                        "candidate_codes": [item.stable_code],
                    },
                )
        partner_assignments = PartnerAssignment.objects.filter(
            catalogue_item__isnull=True
        ).iterator(chunk_size=options["batch_size"])
        for assignment in partner_assignments:
            report["partnerAssignmentsScanned"] += 1
            snapshot_name = (
                assignment.catalogue_snapshot.get("displayName")
                if isinstance(assignment.catalogue_snapshot, dict)
                else ""
            )
            source_value = (
                snapshot_name
                or assignment.purpose
                or assignment.expected_activity_type
                or assignment.support_type
                or ""
            )
            candidates = aliases.get(normalize_alias(source_value), [])
            if len(candidates) != 1:
                kind = (
                    "ambiguous_partner_assignment"
                    if candidates
                    else "unmatched_partner_assignment"
                )
                if candidates:
                    report["ambiguousMatches"] += 1
                else:
                    report["unmatchedPartnerAssignments"] += 1
                ActivityCatalogueReviewQueue.objects.get_or_create(
                    review_kind=kind,
                    source_model="partners.PartnerAssignment",
                    source_record_id=assignment.id,
                    defaults={
                        "source_value": source_value,
                        "candidate_codes": [c.stable_code for c in candidates],
                    },
                )
                continue
            item = candidates[0]
            if not item.partner_delivery_allowed:
                report["errors"] += 1
                ActivityCatalogueReviewQueue.objects.get_or_create(
                    review_kind="partner_delivery_not_allowed",
                    source_model="partners.PartnerAssignment",
                    source_record_id=assignment.id,
                    defaults={
                        "source_value": source_value,
                        "candidate_codes": [item.stable_code],
                    },
                )
                continue
            assignment.catalogue_item = item
            assignment.assignment_mode = "specific_activity"
            assignment.catalogue_snapshot = item.snapshot()
            assignment.expected_activity_type = item.workflow_kind
            assignment.save(
                update_fields=[
                    "catalogue_item",
                    "assignment_mode",
                    "catalogue_snapshot",
                    "expected_activity_type",
                    "updated_at",
                ]
            )
            report["deterministicNormalizedMatches"] += 1
            report["partnerAssignmentsBackfilled"] += 1
        if options["dry_run"]:
            transaction.set_rollback(True)
        report["dryRun"] = options["dry_run"]
        self.stdout.write(json.dumps(report, indent=2, sort_keys=True))
