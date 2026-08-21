import csv
import tempfile
from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity
from apps.activities.models import ActivityScheduleCostLine
from apps.analytics.activity_catalogue import activity_catalogue_metrics
from apps.budget.models import CostCatalogue, CostSetting
from apps.core.exceptions import BadRequest
from apps.core.enums import SsaIntervention
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.partners.models import Partner, PartnerAssignment
from apps.projects.models import Project, ProjectCategory
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore

from .models import (
    ActivityCatalogueItem,
    ActivityCatalogueReviewQueue,
    ActivityInterventionMapping,
    ActivityProjectMapping,
    CatalogueStatus,
    MappingMode,
)
from .importer import import_catalogue
from .seeding import seed_activity_catalogue
from .services import apply_catalogue_snapshot, transition_item
from .services import list_catalogue, recommend_activities


class CatalogueSeedContractTests(TestCase):
    def test_catalogue_analytics_has_a_stable_empty_result(self):
        self.assertEqual(activity_catalogue_metrics(), [])

    def test_seed_is_idempotent_and_complete(self):
        seed_activity_catalogue(actor_id="test")
        seed_activity_catalogue(actor_id="test")

        self.assertEqual(ActivityCatalogueItem.objects.count(), 60)
        self.assertEqual(
            ActivityCatalogueItem.objects.values("stable_code").distinct().count(),
            60,
        )
        # The programme's 28 named interventions plus sixteen Uganda Business
        # Transformation workflows plus four field-event titles (district
        # meeting, boot camp, workshop, conference). Standard field support is
        # counted separately because it is not a curriculum title.
        self.assertEqual(
            ActivityCatalogueItem.objects.filter(standard_support=False).count(),
            48,
        )
        self.assertEqual(
            ActivityCatalogueItem.objects.filter(standard_support=True).count(),
            12,
        )
        self.assertEqual(
            ActivityCatalogueItem.objects.filter(
                non_school_allowed=True, standard_support=False
            ).count(),
            33,
            "The general programme titles remain available for dated central "
            "budgeting — plus the Monthly MFI Review and the four field-event "
            "titles, venue work that belongs to no single school.",
        )
        # Standard support is school/cluster work. Planning it as a standalone
        # dated programme line at a venue would let "School Visit" be budgeted
        # centrally against no school at all.
        self.assertFalse(
            ActivityCatalogueItem.objects.filter(
                standard_support=True, non_school_allowed=True
            ).exists()
        )
        self.assertFalse(
            ActivityInterventionMapping.objects.filter(
                mapping_mode__in=[MappingMode.FIXED, MappingMode.MULTIPLE_ALLOWED],
                intervention__isnull=True,
                active=True,
            ).exists()
        )
        self.assertTrue(
            ActivityInterventionMapping.objects.filter(
                catalogue_item__stable_code="ASA_SSA_DATA_GATHERING",
                mapping_mode=MappingMode.SSA_COMPLETION_PREREQUISITE,
                intervention__isnull=True,
            ).exists()
        )
        self.assertTrue(
            ActivityInterventionMapping.objects.filter(
                catalogue_item__stable_code="PARTNER_MEETINGS_ADMIN",
                mapping_mode=MappingMode.ADMINISTRATIVE,
                intervention__isnull=True,
            ).exists()
        )

    def test_dry_run_rolls_back(self):
        item = ActivityCatalogueItem.objects.get(stable_code="EDTECH_FOUNDATIONS")
        item.source_name = "deliberately-corrupt-test-value"
        item.save(update_fields=["source_name", "updated_at"])
        seed_activity_catalogue(actor_id="test", dry_run=True)
        item.refresh_from_db()
        self.assertEqual(item.source_name, "deliberately-corrupt-test-value")

    def test_dynamic_and_non_intervention_mapping_contracts(self):
        self.assertTrue(
            ActivityInterventionMapping.objects.filter(
                catalogue_item__stable_code="CLIENT_SCHOOL_FOLLOWUP_VISIT",
                mapping_mode=MappingMode.INHERIT_FROM_SOURCE_ACTIVITY,
                intervention__isnull=True,
                catalogue_item__requires_source_activity=True,
            ).exists()
        )
        self.assertFalse(
            ActivityInterventionMapping.objects.filter(
                mapping_mode__in=[
                    MappingMode.ADMINISTRATIVE,
                    MappingMode.SSA_COMPLETION_PREREQUISITE,
                ],
                intervention__isnull=False,
            ).exists()
        )

    def test_inactive_and_retired_items_are_not_selectable_for_planning(self):
        item = ActivityCatalogueItem.objects.get(stable_code="EDTECH_FOUNDATIONS")
        item.status = CatalogueStatus.RETIRED
        item.save(update_fields=["status", "updated_at"])
        self.assertNotIn(item, list(list_catalogue()))


class CatalogueSnapshotTests(TestCase):
    def test_scheduled_activity_snapshot_does_not_change_with_master_data(self):
        item = ActivityCatalogueItem.objects.get(stable_code="PARTNER_MEETINGS_ADMIN")
        activity = Activity.objects.create(activity_type=item.workflow_kind)
        apply_catalogue_snapshot(activity, item=item)
        original = activity.activity_name_snapshot

        item.display_name = "Renamed administrative meeting"
        item.save(update_fields=["display_name", "updated_at"])
        activity.refresh_from_db()

        self.assertEqual(activity.activity_name_snapshot, original)
        self.assertNotEqual(activity.activity_name_snapshot, item.display_name)

    def test_follow_up_requires_a_source_activity(self):
        item = ActivityCatalogueItem.objects.get(
            stable_code="CLIENT_SCHOOL_FOLLOWUP_VISIT"
        )
        activity = Activity.objects.create(activity_type=item.workflow_kind)
        with self.assertRaises(BadRequest):
            apply_catalogue_snapshot(activity, item=item)

    def test_lifecycle_change_without_reason_is_atomic(self):
        item = ActivityCatalogueItem.objects.get(stable_code="EDTECH_FOUNDATIONS")
        with self.assertRaises(BadRequest):
            transition_item(
                item,
                status=CatalogueStatus.RETIRED,
                actor_id="test",
                reason="",
            )
        item.refresh_from_db()
        self.assertEqual(item.status, CatalogueStatus.ACTIVE)


class SsaLedRecommendationTests(TestCase):
    def setUp(self):
        region = Region.objects.create(name="Catalogue Test Region")
        district = District.objects.create(
            name="Catalogue Test District", region=region
        )
        self.school = School.objects.create(
            school_id="CAT-SSA-001",
            name="Catalogue SSA School",
            region=region,
            district=district,
        )

    def test_no_ssa_returns_only_completion_prerequisite(self):
        result = recommend_activities(school=self.school, limit=3)
        self.assertFalse(result["hasApplicableSsa"])
        codes = [
            row["stableCode"] for row in [*result["primary"], *result["otherEligible"]]
        ]
        self.assertEqual(codes, ["ASA_SSA_DATA_GATHERING"])
        self.assertLessEqual(len(result["primary"]), 3)

    def test_financial_health_need_maps_to_accounting_training(self):
        record = SsaRecord.objects.create(
            school=self.school,
            date_of_ssa=timezone.now(),
            fy="2027",
            quarter="Q2",
            average_score=8,
            verification_status="confirmed",
            uploaded_by="test",
        )
        for intervention, _label in SsaIntervention.choices:
            SsaScore.objects.create(
                ssa_record=record,
                intervention=intervention,
                score=1 if intervention == SsaIntervention.FINANCIAL_HEALTH else 9,
            )
        result = recommend_activities(school=self.school, limit=3)
        self.assertTrue(result["hasApplicableSsa"])
        codes = {
            row["stableCode"] for row in [*result["primary"], *result["otherEligible"]]
        }
        # This item is Cluster-only, so an individual-school scheduling
        # context correctly withholds it. The cluster context makes it eligible.
        self.school.cluster_id = "cluster-test"
        self.school.save(update_fields=["cluster_id", "updated_at"])
        from apps.clusters.models import Cluster

        cluster = Cluster.objects.create(
            id="cluster-test",
            name="Catalogue Test Cluster",
            region=self.school.region,
            district=self.school.district,
        )
        clustered = recommend_activities(school=self.school, cluster=cluster, limit=3)
        clustered_codes = {
            row["stableCode"]
            for row in [*clustered["primary"], *clustered["otherEligible"]]
        }
        self.assertNotIn("ACCOUNTING_FINANCIAL_MANAGEMENT", codes)
        self.assertIn("ACCOUNTING_FINANCIAL_MANAGEMENT", clustered_codes)

        # Since the Uganda Business Transformation catalogue landed, Financial
        # Health has governed school-visit responses of its own, so the
        # individual-school context answers the top need directly instead of
        # surfacing an unmet-need notice.
        self.assertTrue(
            {code for code in codes if code.startswith("BT_UG_")},
            "a BT financial-health response must be offered at school level",
        )
        self.assertIsNone(result["unmetPriority"])

        # In the cluster context the need IS answered, so the notice must go
        # quiet rather than warning about a need that is being addressed.
        self.assertIsNone(clustered["unmetPriority"])

    def test_a_follow_up_activity_does_not_count_as_addressing_a_need(self):
        """Dynamic follow-ups inherit the top need's label when no source
        activity exists. Counting that as coverage would silence the notice
        using an activity that does nothing about the need.

        Leadership is the needy intervention here because its governed
        responses (School Leadership, New School Orientation) remain
        cluster-only — Financial Health gained school-level BT responses,
        so it can no longer stage this scenario."""
        record = SsaRecord.objects.create(
            school=self.school,
            date_of_ssa=timezone.now(),
            fy="2027",
            quarter="Q2",
            average_score=8,
            verification_status="confirmed",
            uploaded_by="test",
        )
        for intervention, _label in SsaIntervention.choices:
            SsaScore.objects.create(
                ssa_record=record,
                intervention=intervention,
                score=1 if intervention == SsaIntervention.LEADERSHIP else 9,
            )

        result = recommend_activities(school=self.school, limit=3)

        inherited = [
            row
            for row in [*result["primary"], *result["otherEligible"]]
            if row.get("targetIntervention") == SsaIntervention.LEADERSHIP
        ]
        self.assertTrue(
            inherited, "a follow-up should still inherit the unresolved need's label"
        )
        self.assertIsNotNone(
            result["unmetPriority"],
            "but it must not be mistaken for a response to that need",
        )

    def _school_with_need(self, suffix, intervention, cluster):
        school = School.objects.create(
            school_id=f"CAT-MAP-{suffix}",
            name=f"Catalogue Mapping {suffix}",
            region=self.school.region,
            district=self.school.district,
        )
        school.cluster_id = cluster.id
        school.save(update_fields=["cluster_id", "updated_at"])
        record = SsaRecord.objects.create(
            school=school,
            date_of_ssa=timezone.now(),
            fy="2027",
            quarter="Q2",
            average_score=8,
            verification_status="confirmed",
            uploaded_by="test",
        )
        for code, _label in SsaIntervention.choices:
            SsaScore.objects.create(
                ssa_record=record,
                intervention=code,
                score=1 if code == intervention else 9,
            )
        return school

    def test_canonical_need_mappings_and_ranking_are_deterministic(self):
        from apps.clusters.models import Cluster

        cluster = Cluster.objects.create(
            name="Canonical Mapping Cluster",
            region=self.school.region,
            district=self.school.district,
        )
        cases = [
            (SsaIntervention.LEARNING_ENVIRONMENT, "LEARNING_ENVIRONMENT_TRAINING"),
            (SsaIntervention.LEADERSHIP, "SCHOOL_LEADERSHIP"),
            (SsaIntervention.FINANCIAL_HEALTH, "ACCOUNTING_FINANCIAL_MANAGEMENT"),
            (SsaIntervention.ENROLMENT, "FEES_ENROLMENT_MARKETING"),
            (
                SsaIntervention.GOVERNMENT_REQUIREMENT,
                "GOVERNMENT_STATUTORY_REQUIREMENTS",
            ),
            (SsaIntervention.EXPOSURE_TO_WORD_OF_GOD, "BIBLICAL_INTEGRATION"),
            (SsaIntervention.TEACHING_ENVIRONMENT, "TAM_I"),
            (SsaIntervention.CHRISTLIKE_BEHAVIOUR, "CLA_CHARACTER_DEVELOPMENT"),
        ]
        for index, (intervention, expected_code) in enumerate(cases):
            school = self._school_with_need(index, intervention, cluster)
            first = recommend_activities(school=school, cluster=cluster, limit=3)
            second = recommend_activities(school=school, cluster=cluster, limit=3)
            first_codes = [
                row["stableCode"]
                for row in [*first["primary"], *first["otherEligible"]]
            ]
            self.assertIn(expected_code, first_codes)
            self.assertEqual(first, second)
            self.assertLessEqual(len(first["primary"]), 3)

    def test_project_restriction_removes_unapproved_catalogue_items(self):
        from apps.clusters.models import Cluster

        cluster = Cluster.objects.create(
            name="Project Restriction Cluster",
            region=self.school.region,
            district=self.school.district,
        )
        school = self._school_with_need(
            "PROJECT", SsaIntervention.LEARNING_ENVIRONMENT, cluster
        )
        project = Project.objects.create(
            name="Restricted Project",
            category=ProjectCategory.PILOT,
            target_interventions=[SsaIntervention.LEARNING_ENVIRONMENT],
        )
        approved = ActivityCatalogueItem.objects.get(
            stable_code="LEARNING_ENVIRONMENT_TRAINING"
        )
        ActivityProjectMapping.objects.create(
            project=project,
            catalogue_item=approved,
        )
        result = recommend_activities(
            school=school,
            cluster=cluster,
            project=project,
            limit=3,
        )
        self.assertEqual(
            {
                row["stableCode"]
                for row in [*result["primary"], *result["otherEligible"]]
            },
            {"LEARNING_ENVIRONMENT_TRAINING"},
        )


class CatalogueImportAndBackfillTests(TestCase):
    def test_csv_preview_commit_and_stable_code_upsert(self):
        fields = [
            "Stable Code",
            "Activity Name",
            "Activity Type",
            "Delivery Method",
            "Intervention Mapping",
            "Mapping Mode",
            "Target Audience",
            "Staff Delivery",
            "Partner Delivery",
            "Costing Profile",
            "Evidence Profile",
            "Salesforce Record Type",
            "Status",
        ]
        row = {
            "Stable Code": "TEST_APPROVED_ACTIVITY",
            "Activity Name": "Test Approved Activity",
            "Activity Type": "Training",
            "Delivery Method": "In-school Training",
            "Intervention Mapping": "Learning Environment",
            "Mapping Mode": "Fixed",
            "Target Audience": "School staff",
            "Staff Delivery": "Yes",
            "Partner Delivery": "Yes",
            "Costing Profile": "IN_SCHOOL_TRAINING",
            "Evidence Profile": "TRAINING_ATTENDANCE",
            "Salesforce Record Type": "TRAINING",
            "Status": "Active",
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", newline="", encoding="utf-8"
        ) as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerow(row)
            stream.flush()
            preview = import_catalogue(stream.name, actor_id="test", commit=False)
            self.assertTrue(preview["valid"])
            self.assertFalse(
                ActivityCatalogueItem.objects.filter(
                    stable_code="TEST_APPROVED_ACTIVITY"
                ).exists()
            )
            committed = import_catalogue(stream.name, actor_id="test", commit=True)
            import_catalogue(stream.name, actor_id="test", commit=True)
        self.assertTrue(committed["committed"])
        self.assertEqual(
            ActivityCatalogueItem.objects.filter(
                stable_code="TEST_APPROVED_ACTIVITY"
            ).count(),
            1,
        )

    def test_ambiguous_legacy_activity_enters_review_queue(self):
        # A bare "Training" is genuinely ambiguous: youth camps, leadership
        # camps, conference camps and the ECE project all cost that workflow
        # kind, and no standard-support item claims it. Nothing may guess.
        activity = Activity.objects.create(activity_type="training")
        call_command("backfill_activity_catalogue")
        self.assertTrue(
            ActivityCatalogueReviewQueue.objects.filter(
                source_model="activities.Activity",
                source_record_id=activity.id,
                status="needs_review",
            ).exists()
        )

    def test_legacy_standard_visit_now_resolves_instead_of_queueing(self):
        """The other half of the same rule.

        A plain school visit used to reach the review queue for the reason
        ordinary support could not be scheduled at all: no Catalogue item
        costed ``school_visit``, so there was nothing to match it to. With the
        standard-support item present it resolves deterministically, and a
        human is not asked to adjudicate the most ordinary activity Edify
        performs.
        """
        activity = Activity.objects.create(activity_type="school_visit")
        call_command("backfill_activity_catalogue")
        activity.refresh_from_db()
        self.assertIsNotNone(activity.catalogue_item_id)
        self.assertEqual(activity.catalogue_item.stable_code, "STANDARD_SCHOOL_VISIT")
        self.assertFalse(
            ActivityCatalogueReviewQueue.objects.filter(
                source_model="activities.Activity",
                source_record_id=activity.id,
            ).exists()
        )


class PartnerCatalogueWorkflowTests(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Partner Catalogue Region")
        self.district = District.objects.create(
            name="Partner Catalogue District",
            region=self.region,
            district_type="primary",
        )
        self.school = School.objects.create(
            school_id="CAT-PARTNER-001",
            name="Partner Catalogue School",
            region=self.region,
            district=self.district,
        )
        self.user = User.objects.create_user(
            email="catalogue-cd@example.test",
            name="Catalogue CD",
            roles=[EdifyRole.COUNTRY_DIRECTOR.value],
            active_role=EdifyRole.COUNTRY_DIRECTOR.value,
            password="test-password",
            is_active=True,
        )
        self.staff = StaffProfile.objects.create(
            user=self.user, title="CD", country="Uganda"
        )
        self.partner = Partner.objects.create(
            name="Catalogue Partner",
            active_status=True,
        )
        self.item = ActivityCatalogueItem.objects.get(
            stable_code="ASA_SSA_DATA_GATHERING"
        )

    def _assign(self):
        from apps.planning.services import assign_school_visit_to_partner

        return assign_school_visit_to_partner(
            {
                "schoolId": self.school.school_id,
                "assignedPartnerId": self.partner.id,
                "catalogueItemId": self.item.id,
            },
            self.user,
        )

    def test_assignment_stores_catalogue_and_creates_no_activity_or_cost(self):
        result = self._assign()
        assignment = PartnerAssignment.objects.get(id=result["id"])
        self.assertEqual(assignment.catalogue_item, self.item)
        self.assertEqual(
            assignment.catalogue_snapshot["stableCode"], self.item.stable_code
        )
        self.assertEqual(Activity.objects.count(), 0)
        self.assertEqual(ActivityScheduleCostLine.objects.count(), 0)

    def test_partner_schedule_creates_one_snapshot_and_partner_cost(self):
        result = self._assign()
        scheduled_date = timezone.localdate() + timedelta(days=7)
        while scheduled_date.weekday() >= 5:
            scheduled_date += timedelta(days=1)
        fy = get_operational_fy(scheduled_date)
        CostCatalogue.objects.filter(fy=fy, is_active=True).update(is_active=False)
        catalogue = CostCatalogue.objects.create(
            country="Uganda",
            fy=fy,
            version=91,
            is_active=True,
            label="Partner workflow test",
        )
        CostSetting.objects.update_or_create(
            key="partner_visit_lump_sum",
            defaults={
                "label": "Partner visit rate",
                "unit_cost": 125000,
                "fy": fy,
                "catalogue": catalogue,
            },
        )
        from apps.partners.services import schedule_activity

        activity_payload = schedule_activity(
            result["id"],
            {
                "scheduledDate": scheduled_date.isoformat(),
                "catalogueItemId": self.item.id,
                "requireCatalogue": True,
            },
            self.user,
        )
        activity = Activity.objects.get(id=activity_payload["id"])
        self.assertEqual(activity.catalogue_item, self.item)
        self.assertEqual(activity.activity_name_snapshot, self.item.display_name)
        self.assertEqual(Activity.objects.count(), 1)
        line = activity.schedule_cost_lines.get()
        self.assertEqual(line.cost_setting_key, "partner_visit_lump_sum")
        self.assertEqual(line.amount, 125000)
        self.assertEqual(line.activity_catalogue_item_id, self.item.id)
        with self.assertRaises(BadRequest):
            schedule_activity(
                result["id"],
                {
                    "scheduledDate": scheduled_date.isoformat(),
                    "catalogueItemId": self.item.id,
                    "requireCatalogue": True,
                },
                self.user,
            )
        self.assertEqual(Activity.objects.count(), 1)
