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
    "School ID,Assessment Date,SSA Year,Teaching Environment,Financial Health,Christlike Behaviour,"
    "Exposure to the Word of God,Government Requirement,Leadership,"
    "Enrolment Score,Learning Environment"
)
SCORES = "last,7,6,8,7,5,6,4,7"


class SsaUploadTest(APITestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Northern")
        self.district = District.objects.create(name="Gulu", region=self.region)
        self.school = School.objects.create(
            school_id="SSA-SCH-1",
            name="SSA Primary",
            region=self.region,
            district=self.district,
        )
        self.ia = User.objects.create_user(
            email="ia@ssa.test",
            name="Aisha Dar",
            roles=[EdifyRole.IMPACT_ASSESSMENT.value],
            active_role=EdifyRole.IMPACT_ASSESSMENT.value,
            password="x",
            is_active=True,
        )
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {issue_access_token(self.ia.id, self.ia.active_role)}"
        )

    def _csv(self, body, name="ssa.csv"):
        return SimpleUploadedFile(name, body.encode("utf-8"), content_type="text/csv")

    def _post(self, file):
        return self.client.post("/api/ssa/upload", {"file": file}, format="multipart")

    def _post_and_import(self, file):
        res = self._post(file)
        if res.status_code == 200:
            batch_id = res.json()["upload_batch_id"]
            import_res = self.client.post(f"/api/uploads/{batch_id}/import")
            return import_res
        return res

    def test_valid_rows_save_and_link(self):
        body = f"{SSA_HEADERS}\nSSA-SCH-1,2026-07-01,{SCORES}\n"
        res = self._post_and_import(self._csv(body))
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()
        self.assertEqual(data["createdRows"], 1)
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
        body = "School ID,Assessment Date,SSA Year,Teaching Environment\nSSA-SCH-1,2026-07-01,last,7\n"
        res = self._post(self._csv(body))
        self.assertEqual(res.status_code, 400, res.content)
        self.assertEqual(SsaRecord.objects.count(), 0)

    def test_valid_and_invalid_mixed(self):
        School.objects.create(
            school_id="SSA-SCH-2",
            name="Second",
            region=self.region,
            district=self.district,
        )
        body = (
            f"{SSA_HEADERS}\n"
            f"SSA-SCH-1,2026-07-01,{SCORES}\n"
            f"GHOST,2026-07-01,{SCORES}\n"
            f"SSA-SCH-2,2026-07-02,{SCORES}\n"
        )
        res = self._post_and_import(self._csv(body))
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()
        self.assertEqual(data["createdRows"], 2)
        self.assertEqual(data["failedRows"], 1)
        self.assertEqual(SsaRecord.objects.count(), 2)


class SsaScoreBandTest(APITestCase):
    """§5 canonical SSA status bands on the 0-10 score:
    Critical 0-4.9 / Warning 5-6.9 / Improving 7-7.9 / Strong 8-10."""

    def test_bands_match_mandate_thresholds(self):
        from apps.core.enums import ssa_score_band

        self.assertEqual(ssa_score_band(None)[0], "No SSA")
        self.assertEqual(ssa_score_band(0.0)[0], "Critical")
        self.assertEqual(ssa_score_band(4.9)[0], "Critical")
        self.assertEqual(ssa_score_band(5.0)[0], "Warning")
        self.assertEqual(ssa_score_band(6.9)[0], "Warning")
        self.assertEqual(ssa_score_band(7.0)[0], "Improving")
        self.assertEqual(ssa_score_band(7.9)[0], "Improving")
        self.assertEqual(ssa_score_band(8.0)[0], "Strong")
        self.assertEqual(ssa_score_band(10.0)[0], "Strong")

    def test_pl_analytics_ssa_band_delegates_to_canonical(self):
        from apps.analytics.pl_analytics_service import ssa_band

        # ssa_band takes a 0-100 percentage; 65% == score 6.5 == Warning.
        self.assertEqual(ssa_band(65.0)[0], "Warning")
        self.assertEqual(ssa_band(75.0)[0], "Improving")
        self.assertEqual(ssa_band(None)[0], "No SSA")


class SchoolEnrolmentCountVsSsaScoreTest(APITestCase):
    """2026-07-15 clarification: School Enrolment Count (a headcount, on
    School) and SSA Enrolment Score (a 0-10 performance metric, one of the 8
    SSA interventions) are separate data objects that must never conflate,
    and SSA import must never overwrite the school's enrolment count."""

    def setUp(self):
        self.region = Region.objects.create(name="Enrolment Region")
        self.district = District.objects.create(
            name="Enrolment District", region=self.region
        )
        self.school = School.objects.create(
            school_id="ENR-SCH-1",
            name="Enrolment Test School",
            region=self.region,
            district=self.district,
            enrollment=450,
        )
        self.ia = User.objects.create_user(
            email="ia-enr@ssa.test",
            name="Enrolment IA",
            roles=[EdifyRole.IMPACT_ASSESSMENT.value],
            active_role=EdifyRole.IMPACT_ASSESSMENT.value,
            password="x",
            is_active=True,
        )
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {issue_access_token(self.ia.id, self.ia.active_role)}"
        )

    def _csv(self, body, name="ssa.csv"):
        return SimpleUploadedFile(name, body.encode("utf-8"), content_type="text/csv")

    def _post_and_import(self, file):
        res = self.client.post("/api/ssa/upload", {"file": file}, format="multipart")
        if res.status_code == 200:
            batch_id = res.json()["upload_batch_id"]
            return self.client.post(f"/api/uploads/{batch_id}/import")
        return res

    def test_ssa_enrolment_score_never_overwrites_school_enrollment_count(self):
        """A CSV row's "Enrolment" column (the SSA score, e.g. 6) must not
        touch School.enrollment (the headcount, 450)."""
        body = f"{SSA_HEADERS}\nENR-SCH-1,2026-07-02,{SCORES}\n"
        res = self._post_and_import(self._csv(body))
        self.assertEqual(res.status_code, 200, res.content)
        self.school.refresh_from_db()
        self.assertEqual(self.school.enrollment, 450)

    def test_new_enrollment_column_does_not_overwrite_school_record(self):
        """Even the optional "New Enrolment" headcount column (distinct from
        the SSA score) must not flow into School.enrollment -- SSA import is
        never a write path for the school's enrolment count."""
        headers = (
            "School ID,Assessment Date,SSA Year,New Enrolment,Christlike Behaviour,"
            "Exposure to the Word of God,Financial Health,Leadership,"
            "Government Requirements,Learning Environment,Teacher's Environment,"
            "Enrolment"
        )
        body = f"{headers}\nENR-SCH-1,2026-07-03,last,999,7,6,8,7,5,6,4,7\n"
        res = self._post_and_import(self._csv(body))
        self.assertEqual(res.status_code, 200, res.content)
        self.school.refresh_from_db()
        # School.enrollment must remain exactly what School Directory set —
        # never the CSV's "New Enrolment" value (999).
        self.assertEqual(self.school.enrollment, 450)
        self.assertNotEqual(self.school.enrollment, 999)

    def test_ssa_score_stored_separately_from_school_enrollment(self):
        body = f"{SSA_HEADERS}\nENR-SCH-1,2026-07-04,{SCORES}\n"
        res = self._post_and_import(self._csv(body))
        self.assertEqual(res.status_code, 200, res.content)
        record = SsaRecord.objects.get(school=self.school)
        enrolment_score = record.scores.get(intervention="enrolment").score
        self.school.refresh_from_db()
        # Two entirely different values, on two entirely different models.
        self.assertNotEqual(enrolment_score, self.school.enrollment)
        self.assertLessEqual(enrolment_score, 10)
        self.assertEqual(self.school.enrollment, 450)


class LearnersImpactedUsesSchoolEnrollmentTest(APITestCase):
    """Learners-impacted/reached calculations must aggregate the real school
    headcount (School.enrollment), never any SSA score."""

    def test_analytics_learners_impacted_sums_school_enrollment(self):
        import inspect

        from apps.analytics import services as analytics_services

        source = inspect.getsource(analytics_services)
        # The learners-impacted aggregation must reference the count field...
        self.assertIn('Sum("enrollment")', source)
        # ...and must never aggregate an SSA score field for that purpose.
        self.assertNotIn(
            'learners_impacted = reached_schools.aggregate(total=Sum("score"', source
        )
