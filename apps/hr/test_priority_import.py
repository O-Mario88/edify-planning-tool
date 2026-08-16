from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.accounts.models import StaffProfile, User
from apps.core.exceptions import Forbidden
from apps.core.rbac import EdifyRole

from .models import (
    MilestoneMetricDefinition,
    PriorityImportStatus,
    StrategicPriority,
)
from .priority_import import commit_priority_batch, stage_priority_file


def _user(role: EdifyRole, email: str):
    user = User.objects.create_user(
        email=email,
        name=email.split("@")[0],
        roles=[role.value],
        active_role=role.value,
        password="test-password",
        is_active=True,
    )
    StaffProfile.objects.create(user=user, title=role.value, country="Uganda")
    return user


class PriorityImportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ia = _user(EdifyRole.IMPACT_ASSESSMENT, "import-ia@test.org")
        cls.cceo = _user(EdifyRole.CCEO, "import-cceo@test.org")
        MilestoneMetricDefinition.objects.create(
            metric_key="test_verified_visits",
            canonical_label="Verified visits",
            canonical_service="tests",
        )

    def _file(self, *, target="12", name="priorities.csv"):
        body = (
            "priority_code,priority_title,milestone_code,milestone_title,"
            "target_value,target_unit,measurement_type,metric_key,allocation_method\n"
            f"P1,School quality,P1-M1,Complete verified visits,{target},visits,"
            "count,test_verified_visits,field_cascade\n"
        )
        return SimpleUploadedFile(name, body.encode(), content_type="text/csv")

    def test_ia_stages_then_commits_an_inactive_draft(self):
        batch, created = stage_priority_file(
            file=self._file(), fy="2027", principal=self.ia
        )
        self.assertTrue(created)
        self.assertEqual(batch.status, PriorityImportStatus.VALIDATED)
        self.assertEqual(batch.invalid_rows, 0)

        commit_priority_batch(batch_id=batch.id, principal=self.ia)

        priority = StrategicPriority.objects.get(
            fy="2027", country_id="Uganda", code="P1"
        )
        self.assertEqual(priority.status, "draft")
        milestone = priority.milestones.get(code="P1-M1")
        self.assertFalse(milestone.active)
        self.assertEqual(milestone.target_value, Decimal("12"))
        batch.refresh_from_db()
        self.assertEqual(batch.status, PriorityImportStatus.COMMITTED)

    def test_same_file_is_idempotent(self):
        first, first_created = stage_priority_file(
            file=self._file(), fy="2027", principal=self.ia
        )
        second, second_created = stage_priority_file(
            file=self._file(), fy="2027", principal=self.ia
        )
        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first.id, second.id)

    def test_bad_target_is_staged_as_blocked_not_committed(self):
        batch, _ = stage_priority_file(
            file=self._file(target="not-a-number"), fy="2027", principal=self.ia
        )
        self.assertEqual(batch.status, PriorityImportStatus.NEEDS_CORRECTION)
        self.assertEqual(batch.invalid_rows, 1)
        self.assertIn(
            "target_value must be a number.", batch.rows.get().validation_errors
        )

    def test_non_ia_cannot_import(self):
        with self.assertRaises(Forbidden):
            stage_priority_file(file=self._file(), fy="2027", principal=self.cceo)

    def test_import_surface_is_available_to_ia(self):
        self.client.force_login(self.ia)
        response = self.client.get("/target-distribution", {"fy": "2027"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Import country priorities")
        self.assertContains(response, "Download template")
