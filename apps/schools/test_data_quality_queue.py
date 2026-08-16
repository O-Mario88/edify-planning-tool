"""Phase 1b: durable, self-closing data-quality queues under test.

Pins the reconciliation contract (persisting issues keep their rows AND
their assigned_to; cleared conditions resolve with a timestamp; identity is
condition_key and can never duplicate), the new coordinates detector, the
duplicate proposer's respect for human decisions, the capacity rule's
parity with the assignment drawer, and the System Health surface.
"""

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupportCapacity,
    User,
)
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region
from apps.routes.models import SchoolGeoPoint
from apps.schools.data_quality import (
    detect_duplicate_candidates,
    over_capacity_staff,
    reconcile_issues,
    scan_all,
)
from apps.schools.models import (
    DataQualityIssue,
    School,
    SchoolDuplicateCandidate,
    dq_condition_key,
)


class QueueFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="DQ Region")
        cls.district = District.objects.create(name="DQ District", region=cls.region)

    def _school(self, name, **overrides):
        defaults = dict(
            school_id=f"DQ-{name}",
            name=name,
            region=self.region,
            district=self.district,
            school_type="client",
        )
        defaults.update(overrides)
        return School.objects.create(**defaults)


class ReconciliationTests(QueueFixture):
    def test_a_persisting_issue_keeps_its_row_and_its_owner(self):
        school = self._school("Keep Owner School")
        issue = DataQualityIssue.objects.get(
            school=school, issue_type="no_cluster", status="open"
        )
        issue.assigned_to = "ia-user-1"
        issue.save(update_fields=["assigned_to", "updated_at"])
        original_id = issue.id

        # The old regeneration deleted every open row on every save.
        school.save()

        issue = DataQualityIssue.objects.get(
            school=school, issue_type="no_cluster", status="open"
        )
        self.assertEqual(issue.id, original_id)
        self.assertEqual(issue.assigned_to, "ia-user-1")

    def test_a_cleared_condition_resolves_with_a_timestamp(self):
        school = self._school("Phone Fix School")
        self.assertTrue(
            DataQualityIssue.objects.filter(
                school=school, issue_type="missing_phone", status="open"
            ).exists()
        )
        school.school_phone = "0700000000"
        school.save()
        resolved = DataQualityIssue.objects.get(
            school=school, issue_type="missing_phone"
        )
        self.assertEqual(resolved.status, "resolved")
        self.assertIsNotNone(resolved.resolved_at)

    def test_a_persisting_condition_reopens_its_resolved_row_with_its_owner(self):
        from django.utils import timezone as tz

        school = self._school("Reopen School")
        issue = DataQualityIssue.objects.get(
            school=school, issue_type="no_cluster", status="open"
        )
        issue.assigned_to = "ia-owner-2"
        issue.status = "resolved"
        issue.resolved_at = tz.now()
        issue.save(update_fields=["assigned_to", "status", "resolved_at", "updated_at"])
        # The condition still holds — the next reconcile must reopen THAT
        # row, keeping its owner, never spawn an anonymous duplicate.
        reconcile_issues([school])
        rows = DataQualityIssue.objects.filter(school=school, issue_type="no_cluster")
        self.assertEqual(rows.count(), 1)
        row = rows.get()
        self.assertEqual(row.status, "open")
        self.assertEqual(row.assigned_to, "ia-owner-2")
        self.assertIsNone(row.resolved_at)

    def test_reconciliation_never_duplicates_an_open_condition(self):
        school = self._school("Idempotent School")
        reconcile_issues([school])
        reconcile_issues([school])
        keys = list(
            DataQualityIssue.objects.filter(school=school, status="open").values_list(
                "condition_key", flat=True
            )
        )
        self.assertEqual(len(keys), len(set(keys)))
        self.assertIn(dq_condition_key(school.id, "no_cluster"), keys)


class CoordinatesQueueTests(QueueFixture):
    def test_a_school_without_location_is_queued(self):
        school = self._school("Nowhere School")
        self.assertTrue(
            DataQualityIssue.objects.filter(
                school=school, issue_type="no_coordinates", status="open"
            ).exists()
        )

    def test_directory_coordinates_clear_the_queue(self):
        school = self._school("Located School", latitude=0.31, longitude=32.58)
        self.assertFalse(
            DataQualityIssue.objects.filter(
                school=school, issue_type="no_coordinates", status="open"
            ).exists()
        )

    def test_a_geo_point_override_counts_as_a_location(self):
        school = self._school("Geo Override School")
        SchoolGeoPoint.objects.create(
            school_id=school.id, latitude=0.31, longitude=32.58, source="manual"
        )
        school.save()
        self.assertFalse(
            DataQualityIssue.objects.filter(
                school=school, issue_type="no_coordinates", status="open"
            ).exists()
        )


class DuplicateDetectionTests(QueueFixture):
    def test_similar_names_in_one_district_propose_a_pair(self):
        first = self._school("Bright Future Primary School")
        second = self._school("Bright Future Primary Schol")
        result = detect_duplicate_candidates()
        self.assertEqual(result["candidates_created"], 1)
        pair = SchoolDuplicateCandidate.objects.get()
        self.assertGreaterEqual(pair.score, 62)
        self.assertIn("name_similarity", pair.reasons)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.duplicate_status, "potential")
        self.assertEqual(second.duplicate_status, "potential")

    def test_detection_proposes_once_and_respects_human_decisions(self):
        self._school("Sunrise Academy Primary")
        self._school("Sunrise Academy Primry")
        detect_duplicate_candidates()
        pair = SchoolDuplicateCandidate.objects.get()
        pair.resolved = True
        pair.resolution = "not_duplicate"
        pair.save(update_fields=["resolved", "resolution", "updated_at"])
        result = detect_duplicate_candidates()
        self.assertEqual(result["candidates_created"], 0)
        self.assertEqual(SchoolDuplicateCandidate.objects.count(), 1)

    def test_a_human_not_duplicate_status_is_never_flipped_back(self):
        cleared = self._school("Cleared Twin Primary", duplicate_status="not_duplicate")
        self._school("Cleared Twin Primry")
        detect_duplicate_candidates()
        cleared.refresh_from_db()
        self.assertEqual(cleared.duplicate_status, "not_duplicate")

    def test_unrelated_names_are_not_proposed(self):
        self._school("Saint Kizito Primary")
        self._school("Mountain View Secondary")
        result = detect_duplicate_candidates()
        self.assertEqual(result["candidates_created"], 0)


class CapacityQueueTests(QueueFixture):
    def _staff(self, email):
        user = User.objects.create_user(
            email=email,
            name=email.split("@")[0],
            roles=["CCEO"],
            active_role="CCEO",
            password="test-password",
            is_active=True,
        )
        return StaffProfile.objects.create(user=user, title="CCEO")

    def test_over_capacity_uses_the_governed_limit(self):
        staff = self._staff("over@dq.test")
        StaffSupportCapacity.objects.create(
            staff=staff,
            fy=get_operational_fy(timezone.now()),
            max_direct_schools_supported=1,
            is_active=True,
        )
        for index in range(2):
            school = self._school(f"Cap School {index}")
            StaffSchoolAssignment.objects.create(staff=staff, school_id=school.id)
        over = over_capacity_staff()
        self.assertEqual(len(over), 1)
        self.assertEqual(over[0]["used"], 2)
        self.assertEqual(over[0]["limit"], 1)

    def test_the_default_limit_matches_the_assignment_drawer(self):
        # No capacity row → the same default of 10 the drawer applies.
        staff = self._staff("default@dq.test")
        for index in range(10):
            school = self._school(f"Default School {index}")
            StaffSchoolAssignment.objects.create(staff=staff, school_id=school.id)
        self.assertEqual(over_capacity_staff(), [])


class ScanAndSurfaceTests(QueueFixture):
    def test_scan_all_reconciles_and_reports(self):
        self._school("Scan One Primary")
        self._school("Scan One Primry")
        result = scan_all(batch_size=1)
        self.assertEqual(result["schools"], 2)
        self.assertEqual(result["candidates_created"], 1)
        self.assertGreater(result["created"], 0)
        # duplicate_risk now reflects the proposed pair via the scan.
        self.assertTrue(
            DataQualityIssue.objects.filter(
                issue_type="duplicate_risk", status="open"
            ).exists()
        )

    def test_system_health_carries_the_queue_block(self):
        from apps.system_health.services import report

        self._school("Health Block School")
        data = report()
        self.assertIn("dataQuality", data)
        summary = data["dataQuality"]["summary"]
        self.assertGreater(summary["openIssues"], 0)
        keys = [c["key"] for c in data["dataQuality"]["checks"]]
        self.assertIn("dq_missing_coordinates", keys)
        # Every check leads to an owned queue, never a bare red number.
        for check in data["dataQuality"]["checks"]:
            self.assertTrue(check["resolution_link"])
            self.assertTrue(check["owner"])
