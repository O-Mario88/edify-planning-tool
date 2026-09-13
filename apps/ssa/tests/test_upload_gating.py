"""SSA upload surfaces belong to the uploader (Programme Lead alignment, 2026-09-13).

The upload centre, the template download and the batch preview and result
pages were gated only on the "ssa" page — a reading permission the Programme
Lead, the CCEO, the CD and the RVP all hold — and the batch pages took any id
from the URL. Every one now needs ssa.upload, and a batch opens only for the
person who uploaded it, Impact Assessment and Admin keeping every batch.
"""

from __future__ import annotations

from unittest.mock import patch

from django.test import Client, TestCase

from apps.accounts.models import StaffProfile, User
from apps.core.rbac import EdifyRole
from apps.schools.models import SSAImportBatch


def _user(email, role):
    user = User.objects.create(
        email=email,
        name=email.split("@")[0],
        roles=[role.value],
        active_role=role.value,
        is_active=True,
    )
    StaffProfile.objects.create(user=user, title=role.value)
    return user


class SsaUploadGatingTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pl = _user("gate-pl@t.test", EdifyRole.COUNTRY_PROGRAM_LEAD)
        cls.cceo = _user("gate-cceo@t.test", EdifyRole.CCEO)
        cls.ia = _user("gate-ia@t.test", EdifyRole.IMPACT_ASSESSMENT)
        cls.admin = _user("gate-admin@t.test", EdifyRole.ADMIN)
        cls.admins_batch = SSAImportBatch.objects.create(
            file_name="country.csv", uploaded_by=cls.admin.id, total_rows=0
        )
        cls.cceos_batch = SSAImportBatch.objects.create(
            file_name="mine.csv", uploaded_by=cls.cceo.id, total_rows=0
        )

    def _client(self, user):
        client = Client()
        client.force_login(user)
        return client

    def _urls(self, batch):
        return (
            "/ssa/upload/",
            "/ssa/upload/template",
            f"/ssa/upload/{batch.id}/preview/",
            f"/ssa/upload/{batch.id}/result/",
        )

    def test_a_reader_without_ssa_upload_opens_none_of_them(self):
        client = self._client(self.pl)
        for url in self._urls(self.admins_batch):
            with self.subTest(url=url):
                response = client.get(url)
                self.assertNotEqual(response.status_code, 200)
                self.assertNotIn(
                    "text/csv", response.get("Content-Type", ""), "template leaked"
                )

    def test_impact_assessment_opens_every_batch(self):
        client = self._client(self.ia)
        for url in self._urls(self.admins_batch):
            with self.subTest(url=url):
                self.assertEqual(client.get(url).status_code, 200)

    def test_an_uploader_opens_only_their_own_batch(self):
        client = self._client(self.cceo)
        with patch("apps.frontend.views.ssa_views._may_upload_ssa", return_value=True):
            own = client.get(f"/ssa/upload/{self.cceos_batch.id}/result/")
            other = client.get(f"/ssa/upload/{self.admins_batch.id}/result/")
            other_preview = client.get(f"/ssa/upload/{self.admins_batch.id}/preview/")

        self.assertEqual(own.status_code, 200)
        self.assertEqual(other.status_code, 404)
        self.assertEqual(other_preview.status_code, 404)

    def test_finalising_someone_elses_batch_is_refused(self):
        client = self._client(self.cceo)
        with (
            patch("apps.frontend.views.ssa_views._may_upload_ssa", return_value=True),
            patch("apps.frontend.views.ssa_views.import_ssa_batch") as finalise,
        ):
            response = client.post(f"/ssa/upload/{self.admins_batch.id}/preview/")

        self.assertEqual(response.status_code, 404)
        finalise.assert_not_called()
