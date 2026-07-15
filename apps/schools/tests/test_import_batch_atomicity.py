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

    def test_failure_on_later_row_rolls_back_earlier_rows_in_the_same_batch(self):
        from apps.schools.upload_service import import_school_batch

        original_create = School.objects.create
        calls = {"n": 0}

        def flaky_create(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("simulated failure on the second row")
            return original_create(*args, **kwargs)

        with patch.object(School.objects, "create", side_effect=flaky_create):
            with self.assertRaises(RuntimeError):
                import_school_batch(self.batch, self.ia)

        # The first row's School would have been created in isolation, but
        # because the second row failed, NOTHING in this batch should be
        # persisted — not a partial batch of one school.
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
