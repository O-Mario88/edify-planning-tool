"""
File-upload tests for the SSA upload endpoint.

Authenticated (IA), isolated test DB. Valid rows save + link to an existing
school and flip its SSA status to done; invalid school ids and missing/non-numeric
scores fail those rows truthfully.
"""
from __future__ import annotations

from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase

from apps.accounts.jwt import issue_access_token
from apps.accounts.models import User
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord


SSA_HEADERS = (
    "School ID,Assessment Date,Teaching & Learning,Financial Health,Christlike Behaviour,"
    "Exposure to the Word of God,Government Requirements & Compliance,Leadership,"
    "Education Technology,Learning Environment"
)
SCORES = "7,6,8,7,5,6,4,7"


class SsaUploadTest(APITestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Northern")
        self.district = District.objects.create(name="Gulu", region=self.region)
        self.school = School.objects.create(
            school_id="SSA-SCH-1", name="SSA Primary", region=self.region, district=self.district,
        )
        self.ia = User.objects.create_user(
            email="ia@ssa.test", name="Aisha Dar",
            roles=[EdifyRole.IMPACT_ASSESSMENT.value],
            active_role=EdifyRole.IMPACT_ASSESSMENT.value,
            password="x", is_active=True,
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_access_token(self.ia.id, self.ia.active_role)}")

    def _csv(self, body, name="ssa.csv"):
        return SimpleUploadedFile(name, body.encode("utf-8"), content_type="text/csv")

    def _post(self, file):
        return self.client.post("/api/ssa/upload", {"file": file}, format="multipart")

    def test_valid_rows_save_and_link(self):
        body = f"{SSA_HEADERS}\nSSA-SCH-1,2026-07-01,{SCORES}\n"
        res = self._post(self._csv(body))
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["created_rows"], 1)
        record = SsaRecord.objects.get(school=self.school)
        self.assertEqual(record.scores.count(), 8)
        self.school.refresh_from_db()
        self.assertEqual(self.school.current_fy_ssa_status, "done")
        self.assertEqual(self.school.planning_readiness, "ready")

    def test_invalid_school_id_fails_row(self):
        body = f"{SSA_HEADERS}\nGHOST-SCHOOL,2026-07-01,{SCORES}\n"
        res = self._post(self._csv(body))
        self.assertEqual(res.status_code, 422, res.content)
        data = res.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["failed_rows"], 1)
        self.assertIn("not in the directory", data["errors"][0]["error"])
        self.assertEqual(SsaRecord.objects.count(), 0)

    def test_missing_score_fails_row(self):
        body = f"{SSA_HEADERS}\nSSA-SCH-1,2026-07-01,7,6,8,7,5,6,4,\n"
        res = self._post(self._csv(body))
        self.assertEqual(res.status_code, 422, res.content)
        data = res.json()
        self.assertEqual(data["failed_rows"], 1)
        self.assertEqual(SsaRecord.objects.count(), 0)

    def test_non_numeric_score_fails_row(self):
        body = f"{SSA_HEADERS}\nSSA-SCH-1,2026-07-01,7,6,8,7,5,6,4,bad\n"
        res = self._post(self._csv(body))
        self.assertEqual(res.status_code, 422, res.content)
        self.assertEqual(res.json()["failed_rows"], 1)
        self.assertEqual(SsaRecord.objects.count(), 0)

    def test_out_of_range_score_fails_row(self):
        body = f"{SSA_HEADERS}\nSSA-SCH-1,2026-07-01,7,6,8,7,5,6,4,99\n"
        res = self._post(self._csv(body))
        self.assertEqual(res.status_code, 422, res.content)
        self.assertEqual(res.json()["failed_rows"], 1)

    def test_missing_intervention_header_blocks_upload(self):
        body = "School ID,Assessment Date,Teaching & Learning\nSSA-SCH-1,2026-07-01,7\n"
        res = self._post(self._csv(body))
        self.assertEqual(res.status_code, 400, res.content)
        self.assertEqual(SsaRecord.objects.count(), 0)

    def test_valid_and_invalid_mixed(self):
        School.objects.create(school_id="SSA-SCH-2", name="Second", region=self.region, district=self.district)
        body = (
            f"{SSA_HEADERS}\n"
            f"SSA-SCH-1,2026-07-01,{SCORES}\n"
            f"GHOST,2026-07-01,{SCORES}\n"
            f"SSA-SCH-2,2026-07-02,{SCORES}\n"
        )
        res = self._post(self._csv(body))
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()
        self.assertEqual(data["created_rows"], 2)
        self.assertEqual(data["failed_rows"], 1)
        self.assertEqual(SsaRecord.objects.count(), 2)
