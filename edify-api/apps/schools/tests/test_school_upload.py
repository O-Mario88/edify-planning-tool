"""
File-upload tests for the truthful school onboarding endpoint.

Authenticated (IA), isolated test DB. Proves the spec: exact + variant headers
save rows, XLSX saves rows, missing required values fail those rows, blank rows
are skipped, duplicates are handled (duplicate vs update_existing), the response
counts are truthful, a zero-saved upload returns success=false, and the saved
rows are immediately readable from GET /api/schools.
"""
from __future__ import annotations

import io

from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase

from apps.accounts.jwt import issue_access_token
from apps.accounts.models import StaffProfile, User
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School, UploadBatch, UploadBatchRowResult


EXACT_HEADERS = (
    "Account Owner,School ID,School Name,District,Current Partner Type,"
    "Enrolment,Last Date of Enrolment,Phone,Primary Contact,School Shipping Address"
)


class SchoolUploadTest(APITestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Northern")
        self.district = District.objects.create(name="Gulu", region=self.region)
        self.ia = User.objects.create_user(
            email="ia@upload.test", name="IA Tester",
            roles=[EdifyRole.IMPACT_ASSESSMENT.value],
            active_role=EdifyRole.IMPACT_ASSESSMENT.value,
            password="x", is_active=True,
        )
        # A field-staff CCEO named "Aisha Dar" — the upload matches a school's
        # Staff Name to this CCEO (role-aware: only CCEO/PL users auto-link).
        self.cceo = User.objects.create_user(
            email="cceo@upload.test", name="Aisha Dar",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="x", is_active=True,
        )
        self.staff = StaffProfile.objects.create(user=self.cceo, title="CCEO")
        self._auth(self.ia)

    # ── helpers ──────────────────────────────────────────────────────────
    def _auth(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_access_token(user.id, user.active_role)}")

    def _csv(self, body: str, name="schools.csv"):
        return SimpleUploadedFile(name, body.encode("utf-8"), content_type="text/csv")

    def _post(self, file, update_existing=False):
        data = {"file": file}
        if update_existing:
            data["update_existing"] = "true"
        return self.client.post("/api/schools/upload", data, format="multipart")

    # ── tests ────────────────────────────────────────────────────────────
    def test_exact_template_headers_save_rows(self):
        body = (
            f"{EXACT_HEADERS}\n"
            ",SCH-1,Gulu Primary,Gulu,Client,320,2026-01-15,+256700000001,Head Teacher,PO Box 1\n"
        )
        res = self._post(self._csv(body))
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["created_rows"], 1)
        self.assertEqual(data["total_rows"], 1)
        school = School.objects.get(school_id="SCH-1")
        self.assertEqual(school.name, "Gulu Primary")
        self.assertEqual(school.district_id, self.district.id)
        self.assertEqual(school.region_id, self.region.id)
        self.assertEqual(school.enrollment, 320)
        self.assertEqual(school.last_enrollment_date.isoformat(), "2026-01-15")

    def test_header_variations_save_rows(self):
        body = (
            "schoolid,Name,district,Partner Type,enrollment,Last Date of Enrollment\n"
            "SCH-2,Variant Primary,Gulu,core,410,2026-02-01\n"
        )
        res = self._post(self._csv(body))
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()
        self.assertEqual(data["created_rows"], 1)
        school = School.objects.get(school_id="SCH-2")
        self.assertEqual(school.name, "Variant Primary")
        self.assertEqual(school.school_type, "core")
        self.assertEqual(school.enrollment, 410)

    def test_xlsx_saves_rows(self):
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["School ID", "School Name", "District", "Current Partner Type", "Enrolment"])
        ws.append(["SCH-XLSX", "Spreadsheet Primary", "Gulu", "Client", 250])
        buf = io.BytesIO()
        wb.save(buf)
        f = SimpleUploadedFile(
            "schools.xlsx", buf.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        res = self._post(f)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["created_rows"], 1)
        self.assertTrue(School.objects.filter(school_id="SCH-XLSX").exists())

    def test_missing_required_values_fail_rows(self):
        body = (
            f"{EXACT_HEADERS}\n"
            ",,No Id School,Gulu,Client,1,,,,\n"            # missing School ID
            ",SCH-NO-NAME,,Gulu,Client,1,,,,\n"            # missing Name
            ",SCH-NO-DIST,Has No District,,Client,1,,,,\n"  # missing District
            ",SCH-OK,Valid Primary,Gulu,Client,100,,,,\n"   # valid
        )
        res = self._post(self._csv(body))
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()
        self.assertEqual(data["created_rows"], 1)
        self.assertEqual(data["failed_rows"], 3)
        self.assertEqual(len(data["errors"]), 3)
        self.assertTrue(School.objects.filter(school_id="SCH-OK").exists())
        self.assertFalse(School.objects.filter(school_id="SCH-NO-NAME").exists())

    def test_unmatched_district_fails_row(self):
        body = f"{EXACT_HEADERS}\n,SCH-BADGEO,Nowhere Primary,Atlantis,Client,1,,,,\n"
        res = self._post(self._csv(body))
        self.assertEqual(res.status_code, 422, res.content)
        data = res.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["failed_rows"], 1)
        self.assertIn("Atlantis", data["errors"][0]["error"])

    def test_blank_rows_skipped(self):
        body = (
            f"{EXACT_HEADERS}\n"
            ",SCH-REAL,Real Primary,Gulu,Client,100,,,,\n"
            ",,,,,,,,,\n"  # fully blank
            "\n"
        )
        res = self._post(self._csv(body))
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()
        self.assertEqual(data["created_rows"], 1)
        self.assertEqual(data["skipped_rows"], 1)

    def test_duplicate_then_update_existing(self):
        body = f"{EXACT_HEADERS}\n,SCH-DUP,First Name,Gulu,Client,100,,,,\n"
        self.assertEqual(self._post(self._csv(body)).status_code, 200)

        # Second upload, same id, no update_existing → duplicate, nothing saved.
        dup_body = f"{EXACT_HEADERS}\n,SCH-DUP,Second Name,Gulu,Client,200,,,,\n"
        res = self._post(self._csv(dup_body))
        self.assertEqual(res.status_code, 422, res.content)
        data = res.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["duplicate_rows"], 1)
        self.assertEqual(School.objects.get(school_id="SCH-DUP").name, "First Name")

        # Third upload, same id, update_existing → updated.
        res2 = self._post(self._csv(dup_body), update_existing=True)
        self.assertEqual(res2.status_code, 200, res2.content)
        data2 = res2.json()
        self.assertTrue(data2["success"])
        self.assertEqual(data2["updated_rows"], 1)
        self.assertEqual(School.objects.get(school_id="SCH-DUP").name, "Second Name")
        self.assertEqual(School.objects.filter(school_id="SCH-DUP").count(), 1)

    def test_missing_required_header_blocks_whole_upload(self):
        body = "School ID,School Name\nSCH-X,No District Column\n"
        res = self._post(self._csv(body))
        self.assertEqual(res.status_code, 400, res.content)
        self.assertIn("District", str(res.content))
        self.assertEqual(School.objects.count(), 0)
        self.assertEqual(UploadBatch.objects.count(), 0)

    def test_account_owner_matched_and_unmatched(self):
        body = (
            f"{EXACT_HEADERS}\n"
            "Aisha Dar,SCH-OWN-1,Owned Primary,Gulu,Client,100,,,,\n"
            "Ghost Person,SCH-OWN-2,Orphan Primary,Gulu,Client,100,,,,\n"
        )
        res = self._post(self._csv(body))
        self.assertEqual(res.status_code, 200, res.content)
        matched = School.objects.get(school_id="SCH-OWN-1")
        self.assertEqual(matched.account_owner_status, "matched")
        self.assertEqual(matched.account_owner_id, self.staff.id)
        unmatched = School.objects.get(school_id="SCH-OWN-2")
        self.assertEqual(unmatched.account_owner_status, "unmatched")
        self.assertEqual(unmatched.account_owner_name_raw, "Ghost Person")

    def test_row_results_persisted(self):
        body = (
            f"{EXACT_HEADERS}\n"
            ",SCH-RR-1,Good Primary,Gulu,Client,100,,,,\n"
            ",,Bad Primary,Gulu,Client,100,,,,\n"
        )
        res = self._post(self._csv(body))
        batch_id = res.json()["upload_batch_id"]
        rows = UploadBatchRowResult.objects.filter(upload_batch_id=batch_id)
        self.assertEqual(rows.count(), 2)
        self.assertEqual(rows.filter(status="created").count(), 1)
        self.assertEqual(rows.filter(status="failed").count(), 1)

    def test_directory_returns_uploaded_rows(self):
        body = f"{EXACT_HEADERS}\n,SCH-DIR,Directory Primary,Gulu,Client,100,,,,\n"
        self.assertEqual(self._post(self._csv(body)).status_code, 200)
        res = self.client.get("/api/schools?pageSize=200")
        self.assertEqual(res.status_code, 200, res.content)
        ids = [r["schoolId"] for r in res.json()["data"]]
        self.assertIn("SCH-DIR", ids)

    def test_uploads_read_endpoints(self):
        body = f"{EXACT_HEADERS}\n,SCH-RD,Read Primary,Gulu,Client,100,,,,\n"
        batch_id = self._post(self._csv(body)).json()["upload_batch_id"]

        listing = self.client.get("/api/uploads")
        self.assertEqual(listing.status_code, 200, listing.content)
        self.assertTrue(any(b["id"] == batch_id for b in listing.json()))

        detail = self.client.get(f"/api/uploads/{batch_id}")
        self.assertEqual(detail.status_code, 200, detail.content)
        self.assertEqual(detail.json()["createdRows"], 1)

        rows = self.client.get(f"/api/uploads/{batch_id}/rows")
        self.assertEqual(rows.status_code, 200, rows.content)
        self.assertEqual(rows.json()[0]["schoolId"], "SCH-RD")
