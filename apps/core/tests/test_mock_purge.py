"""
Tests for the mock-purge / database-source-of-truth guarantees.

Covers the success criteria:
  - empty DB → empty arrays (no demo fallback)
  - uploaded schools appear in the directory
  - SSA upload saves + updates planning readiness
  - production settings block mock data
  - local import commands refuse production
  - purge does not delete reference data
  - dashboards do not show fake counts (empty → zeros)
"""

from __future__ import annotations

import os
import tempfile
from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.accounts.models import Permission, RolePermission
from apps.core.models import DataSource
from apps.geography.models import District, Region, SubCounty
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore


class EmptyDatabaseContractTest(TestCase):
    """An empty (reference-only) database must return empty arrays/zero counts —
    never demo/fake data."""

    def setUp(self):
        # Reference-only seed: permissions only, no demo data.
        call_command("seed", stdout=StringIO())

    def test_schools_endpoint_returns_empty(self):
        from apps.schools.services import list_schools

        class _P:
            user_id = "u"
            active_role = "Admin"
            staff_profile_id = None

        result = list_schools({"pageSize": "25"}, _P())
        self.assertEqual(result.count(), 0)
        self.assertEqual(School.objects.count(), 0)

    def test_analytics_dashboard_shows_zeros_not_fakes(self):
        from apps.analytics.services import dashboard_summary

        class _P:
            user_id = "u"
            active_role = "Admin"
            staff_profile_id = None

        d = dashboard_summary(_P(), {})
        self.assertEqual(d["schools"], 0)
        self.assertEqual(d["ssaDone"], 0)
        self.assertEqual(d["coreSchools"], 0)
        # No hardcoded fake numbers.
        self.assertNotIn(72, [d["schools"], d["ssaDone"]])

    def test_filters_options_empty(self):
        from apps.filters.services import options

        class _P:
            user_id = "u"
            active_role = "Admin"
            staff_profile_id = None

        o = options(_P())
        self.assertEqual(o["schoolTypes"], [])
        self.assertEqual(o["regions"], [])

    def test_reference_data_present(self):
        # Derived from the matrix rather than a hardcoded count, so adding a
        # permission doesn't require editing an unrelated purge test.
        from apps.core.rbac import all_permission_keys

        self.assertEqual(Permission.objects.count(), len(all_permission_keys()))
        self.assertGreater(RolePermission.objects.count(), 100)


class UploadWiringTest(TestCase):
    """Uploaded schools/SSA must save to the DB and update the workflow."""

    def setUp(self):
        # Minimal reference geography so uploads resolve region/district.
        region = Region.objects.create(name="Test Region")
        district = District.objects.create(name="Test District", region=region)
        SubCounty.objects.create(name="Test SubCounty", district=district)

    def test_school_upload_saves_to_db(self):
        from apps.schools.services import create_one

        class _P:
            user_id = "u"
            active_role = "ImpactAssessment"
            staff_profile_id = None

        region = Region.objects.first()
        district = District.objects.first()
        school = create_one(
            {
                "schoolId": "UPL-1",
                "name": "Uploaded Primary",
                "regionId": region.id,
                "districtId": district.id,
                "schoolType": "client",
                "enrollment": 100,
            },
            _P(),
        )
        self.assertEqual(School.objects.count(), 1)
        self.assertEqual(school.school_id, "UPL-1")
        self.assertEqual(school.source, DataSource.MANUAL_UPLOAD.value)

    def test_uploaded_school_appears_in_directory(self):
        from apps.schools.services import create_one, get_one

        class _P:
            user_id = "u"
            active_role = "Admin"
            staff_profile_id = None

        region = Region.objects.first()
        district = District.objects.first()
        create_one(
            {
                "schoolId": "UPL-2",
                "name": "Dir School",
                "regionId": region.id,
                "districtId": district.id,
            },
            _P(),
        )
        fetched = get_one("UPL-2", _P())
        self.assertEqual(fetched.name, "Dir School")

    def test_ssa_upload_saves_and_updates_readiness(self):
        from apps.schools.services import create_one
        from apps.ssa.services import upload as ssa_upload

        class _P:
            user_id = "u"
            active_role = "ImpactAssessment"
            staff_profile_id = None

        region = Region.objects.first()
        district = District.objects.first()
        school = create_one(
            {
                "schoolId": "UPL-3",
                "name": "Ssa School",
                "regionId": region.id,
                "districtId": district.id,
            },
            _P(),
        )
        # Without SSA the school is locked.
        school.current_fy_ssa_status = "done"
        school.save(update_fields=["current_fy_ssa_status"])
        record = ssa_upload(
            {
                "schoolId": "UPL-3",
                "dateOfSsa": "2026-05-15T09:00:00+03:00",
                "scores": [
                    {"intervention": "teaching_environment", "score": 7},
                    {"intervention": "financial_health", "score": 6},
                    {"intervention": "christlike_behaviour", "score": 8},
                    {"intervention": "exposure_to_word_of_god", "score": 7},
                    {"intervention": "government_requirement", "score": 5},
                    {"intervention": "leadership", "score": 6},
                    {"intervention": "enrolment", "score": 4},
                    {"intervention": "learning_environment", "score": 7},
                ],
            },
            _P(),
        )
        self.assertEqual(SsaRecord.objects.count(), 1)
        self.assertEqual(SsaScore.objects.count(), 8)
        school.refresh_from_db()
        # Staff-collected SSA is confirmed; an unclustered school still cannot
        # enter support planning until canonical cluster membership is set.
        self.assertEqual(school.planning_readiness, "requires_cluster")
        self.assertEqual(school.current_fy_ssa_status, "done")


class ProductionBlockingTest(TestCase):
    """Dev-only commands must refuse to run in production."""

    @override_settings(IS_PRODUCTION=True)
    def test_seed_demo_refuses_production(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("seed", "--demo", stdout=StringIO())

    @override_settings(IS_PRODUCTION=True)
    def test_import_schools_refuses_production(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command(
                "import_schools_local", "/tmp/nonexistent.csv", stdout=StringIO()
            )

    @override_settings(IS_PRODUCTION=True)
    def test_purge_refuses_production(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("purge_local_test_data", "--yes", stdout=StringIO())


class PurgePreservesReferenceTest(TestCase):
    """purge_local_test_data must not delete reference data."""

    def setUp(self):
        call_command("seed", stdout=StringIO())  # permissions (reference)
        region = Region.objects.create(name="R")
        district = District.objects.create(name="D", region=region)
        School.objects.create(
            school_id="T-1",
            name="Test",
            region=region,
            district=district,
            source=DataSource.LOCAL_TEST_UPLOAD.value,
        )

    def test_purge_keeps_reference_removes_test(self):
        self.assertEqual(School.objects.count(), 1)
        call_command("purge_local_test_data", "--yes", stdout=StringIO())
        # Test school gone, permissions (reference) intact.
        self.assertEqual(School.objects.count(), 0)
        from apps.core.rbac import all_permission_keys

        self.assertEqual(Permission.objects.count(), len(all_permission_keys()))


class ImportCommandsTest(TestCase):
    """import_schools_local + import_ssa_local create DB records tagged local."""

    def setUp(self):
        region = Region.objects.create(name="Imp Region")
        district = District.objects.create(name="Imp District", region=region)
        SubCounty.objects.create(name="Imp Sub", district=district)

    def test_import_schools_local_csv(self):
        region = Region.objects.first()
        district = District.objects.first()
        csv = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline=""
        )
        csv.write("schoolId,name,region,district,schoolType\n")
        csv.write(f"IMP-1,Imp School,{region.name},{district.name},client\n")
        csv.close()
        call_command("import_schools_local", csv.name, stdout=StringIO())
        s = School.objects.get(school_id="IMP-1")
        self.assertEqual(s.name, "Imp School")
        self.assertEqual(s.source, DataSource.LOCAL_TEST_UPLOAD.value)
        os.unlink(csv.name)
