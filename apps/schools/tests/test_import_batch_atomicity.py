"""import_school_batch must be all-or-nothing: a failure partway through the
row loop (e.g. an unexpected DB error on a later row) must not leave earlier
rows in that batch committed while the batch itself stays stuck at a stale
status — apps.schools.upload_service.import_school_batch wraps the whole
loop in one transaction.atomic() for exactly this reason.
"""

from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School, SchoolImportBatch, SchoolImportRow

User = get_user_model()


class ImportSchoolBatchAtomicityTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Atomic Region")
        self.district = District.objects.create(
            name="Atomic District", region=self.region
        )
        self.ia = User.objects.create_user(
            email="ia-atomic@test.org",
            name="Atomic IA",
            roles=[EdifyRole.IMPACT_ASSESSMENT.value],
            active_role=EdifyRole.IMPACT_ASSESSMENT.value,
            password="password",
            is_active=True,
        )
        self.batch = SchoolImportBatch.objects.create(
            file_name="atomic.csv", uploaded_by=self.ia.id, status="staged"
        )
        SchoolImportRow.objects.create(
            batch=self.batch,
            row_number=1,
            school_id="ATOMIC-1",
            name="Atomic School One",
            district_name=self.district.name,
            status="ready",
        )
        SchoolImportRow.objects.create(
            batch=self.batch,
            row_number=2,
            school_id="ATOMIC-2",
            name="Atomic School Two",
            district_name=self.district.name,
            status="ready",
        )

    def test_bulk_write_failure_rolls_back_the_whole_batch(self):
        from apps.schools.upload_service import import_school_batch

        with patch.object(
            School.objects,
            "bulk_create",
            side_effect=RuntimeError("simulated bulk write failure"),
        ):
            with self.assertRaises(RuntimeError):
                import_school_batch(self.batch, self.ia)

        # A failed bounded write cannot leave a partial batch behind.
        self.assertEqual(
            School.objects.filter(school_id__in=["ATOMIC-1", "ATOMIC-2"]).count(), 0
        )
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.status, "staged")

    def test_batch_with_no_failures_commits_all_rows(self):
        from apps.schools.upload_service import import_school_batch

        result = import_school_batch(self.batch, self.ia)
        self.assertEqual(result["created"], 2)
        self.assertEqual(
            School.objects.filter(school_id__in=["ATOMIC-1", "ATOMIC-2"]).count(), 2
        )
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.status, "imported")
