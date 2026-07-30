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
            email="ia@upload.test",
            name="IA Tester",
            roles=[EdifyRole.IMPACT_ASSESSMENT.value],
            active_role=EdifyRole.IMPACT_ASSESSMENT.value,
            password="x",
            is_active=True,
        )
        # A field-staff CCEO named "Aisha Dar" — the upload matches a school's
        # Staff Name to this CCEO (role-aware: only CCEO/PL users auto-link).
        self.cceo = User.objects.create_user(
            email="cceo@upload.test",
            name="Aisha Dar",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="x",
            is_active=True,
        )
        self.staff = StaffProfile.objects.create(user=self.cceo, title="CCEO")
        self._auth(self.ia)

    # ── helpers ──────────────────────────────────────────────────────────
    def _auth(self, user):
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {issue_access_token(user.id, user.active_role)}"
        )

    def _csv(self, body: str, name="schools.csv"):
        return SimpleUploadedFile(name, body.encode("utf-8"), content_type="text/csv")

    def _post(self, file, update_existing=False):
        data = {"file": file}
        if update_existing:
            data["update_existing"] = "true"
        return self.client.post("/api/schools/upload", data, format="multipart")

    def _post_and_import(self, file, update_existing=False):
        res = self._post(file, update_existing=update_existing)
        if res.status_code == 200:
            batch_id = res.json()["upload_batch_id"]
            import_res = self.client.post(f"/api/uploads/{batch_id}/import")
            # Return the combined details or the import response
            return import_res
        return res

    # ── tests ────────────────────────────────────────────────────────────
    def test_exact_template_headers_save_rows(self):
        body = (
            f"{EXACT_HEADERS}\n"
            "Aisha Dar,SCH-1,Gulu Primary,Gulu,Client,320,2026-01-15,+256700000001,Head Teacher,PO Box 1\n"
        )
        res = self._post_and_import(self._csv(body))
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()
        self.assertEqual(data["createdRows"], 1)
        self.assertEqual(data["totalRows"], 1)
        school = School.objects.get(school_id="SCH-1")
        self.assertEqual(school.name, "Gulu Primary")
        self.assertEqual(school.district_id, self.district.id)
        self.assertEqual(school.region_id, self.region.id)
        self.assertEqual(school.enrollment, 320)
        self.assertEqual(school.last_enrollment_date.isoformat(), "2026-01-15")

    def test_header_variations_save_rows(self):
        body = (
            "schoolid,Name,district,Staff Name,Partner Type,enrollment,Last Date of Enrollment\n"
            "SCH-2,Variant Primary,Gulu,Aisha Dar,core,410,2026-02-01\n"
        )
        res = self._post_and_import(self._csv(body))
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()
        self.assertEqual(data["createdRows"], 1)
        school = School.objects.get(school_id="SCH-2")
        self.assertEqual(school.name, "Variant Primary")
        self.assertEqual(school.school_type, "core")
        self.assertEqual(school.enrollment, 410)

    def test_all_current_partner_type_labels_are_imported(self):
        rows = [
            f"Aisha Dar,SCH-TYPE-{index},Type {index} Primary,Gulu,{label},100,,,,"
            for index, label in enumerate(
                ["Champion", "Client", "Core", "Core Graduate", "Core Trained"],
                start=1,
            )
        ]
        res = self._post_and_import(
            self._csv(f"{EXACT_HEADERS}\n" + "\n".join(rows) + "\n")
        )

        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(
            list(
                School.objects.filter(school_id__startswith="SCH-TYPE-")
                .order_by("school_id")
                .values_list("school_type", flat=True)
            ),
            ["champion", "client", "core", "core_graduate", "core_trained"],
        )

    def test_download_template_sub_county_header_is_imported(self):
        from apps.geography.models import SubCounty

        sub_county = SubCounty.objects.create(name="Bardege", district=self.district)
        body = (
            "School ID,School Name,District,Sub County,Staff Name\n"
            "SCH-SC,Sub County Primary,Gulu,Bardege,Aisha Dar\n"
        )
        res = self._post_and_import(self._csv(body))

        self.assertEqual(res.status_code, 200, res.content)
        school = School.objects.get(school_id="SCH-SC")
        self.assertEqual(school.sub_county_id, sub_county.id)

    def test_numeric_uploaded_school_id_is_preserved_without_prefix(self):
        body = (
            "School ID,School Name,District,Staff Name\n"
            "51230,Uploaded ID Primary,Gulu,Aisha Dar\n"
        )
        res = self._post_and_import(self._csv(body))

        self.assertEqual(res.status_code, 200, res.content)
        school = School.objects.get(name="Uploaded ID Primary")
        self.assertEqual(school.school_id, "51230")
        self.assertFalse(school.school_id.startswith("S-"))

    def test_xlsx_saves_rows(self):
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(
            [
                "School ID",
                "School Name",
                "District",
                "Staff Name",
                "Current Partner Type",
                "Enrolment",
            ]
        )
        ws.append(
            ["SCH-XLSX", "Spreadsheet Primary", "Gulu", "Aisha Dar", "Client", 250]
        )
        buf = io.BytesIO()
        wb.save(buf)
        f = SimpleUploadedFile(
            "schools.xlsx",
            buf.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        res = self._post_and_import(f)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["createdRows"], 1)
        self.assertTrue(School.objects.filter(school_id="SCH-XLSX").exists())

    def test_missing_required_values_fail_rows(self):
        body = (
            f"{EXACT_HEADERS}\n"
            "Aisha Dar,,No Id School,Gulu,Client,1,,,,\n"  # missing School ID
            "Aisha Dar,SCH-NO-NAME,,Gulu,Client,1,,,,\n"  # missing Name
            "Aisha Dar,SCH-NO-DIST,Has No District,,Client,1,,,,\n"  # optional District
            "Aisha Dar,SCH-OK,Valid Primary,Gulu,Client,100,,,,\n"  # valid
        )
        res = self._post_and_import(self._csv(body))
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()
        self.assertEqual(data["createdRows"], 2)
        self.assertEqual(data["failedRows"], 2)
        self.assertTrue(School.objects.filter(school_id="SCH-OK").exists())
        incomplete = School.objects.get(school_id="SCH-NO-DIST")
        self.assertIsNone(incomplete.district_id)
        self.assertIsNone(incomplete.region_id)
        self.assertFalse(School.objects.filter(school_id="SCH-NO-NAME").exists())

    def test_unmatched_optional_district_creates_incomplete_profile(self):
        body = f"{EXACT_HEADERS}\nAisha Dar,SCH-BADGEO,Nowhere Primary,Atlantis,Client,1,,,,\n"
        res = self._post_and_import(self._csv(body))

        self.assertEqual(res.status_code, 200, res.content)
        school = School.objects.get(school_id="SCH-BADGEO")
        self.assertIsNone(school.district_id)
        self.assertIsNone(school.region_id)
        self.assertEqual(school.uploaded_district_text, "Atlantis")

    def test_blank_rows_skipped(self):
        body = (
            f"{EXACT_HEADERS}\n"
            "Aisha Dar,SCH-REAL,Real Primary,Gulu,Client,100,,,,\n"
            ",,,,,,,,,\n"  # fully blank
            "\n"
        )
        res = self._post_and_import(self._csv(body))
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()
        self.assertEqual(data["createdRows"], 1)
        self.assertEqual(data["skippedRows"], 1)

    def test_duplicate_then_update_existing(self):
        body = f"{EXACT_HEADERS}\nAisha Dar,SCH-DUP,First Name,Gulu,Client,100,,,,\n"
        self.assertEqual(self._post_and_import(self._csv(body)).status_code, 200)

        # Second upload, same id, no update_existing → duplicate, nothing saved.
        dup_body = (
            f"{EXACT_HEADERS}\nAisha Dar,SCH-DUP,Second Name,Gulu,Client,200,,,,\n"
        )
        res = self._post(self._csv(dup_body))
        self.assertEqual(res.status_code, 422, res.content)
        data = res.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["duplicate_rows"], 1)
        self.assertEqual(School.objects.get(school_id="SCH-DUP").name, "First Name")

        # Third upload, same id, update_existing → updated.
        res2 = self._post_and_import(self._csv(dup_body), update_existing=True)
        self.assertEqual(res2.status_code, 200, res2.content)
        data2 = res2.json()
        self.assertEqual(data2["updatedRows"], 1)
        self.assertEqual(School.objects.get(school_id="SCH-DUP").name, "Second Name")
        self.assertEqual(School.objects.filter(school_id="SCH-DUP").count(), 1)

    def test_only_school_id_and_name_columns_create_incomplete_school(self):
        body = "School ID,School Name\nSCH-MIN,Minimal School\n"
        res = self._post_and_import(self._csv(body))

        self.assertEqual(res.status_code, 200, res.content)
        school = School.objects.get(school_id="SCH-MIN")
        self.assertEqual(school.name, "Minimal School")
        self.assertIsNone(school.district_id)
        self.assertIsNone(school.region_id)
        self.assertIsNone(school.account_owner_id)
        self.assertEqual(school.account_owner_status, "pending")

    def test_missing_school_name_header_blocks_whole_upload(self):
        body = "School ID,District\nSCH-X,Gulu\n"
        res = self._post(self._csv(body))

        self.assertEqual(res.status_code, 400, res.content)
        self.assertIn("School Name", str(res.content))
        self.assertEqual(School.objects.count(), 0)
        self.assertEqual(UploadBatch.objects.count(), 0)

    def test_missing_staff_name_header_is_allowed(self):
        body = "School ID,School Name,District\nSCH-X,No Staff Column,Gulu\n"
        res = self._post_and_import(self._csv(body))

        self.assertEqual(res.status_code, 200, res.content)
        school = School.objects.get(school_id="SCH-X")
        self.assertIsNone(school.account_owner_id)
        self.assertEqual(school.account_owner_status, "pending")

    def test_blank_staff_name_creates_pending_profile(self):
        body = f"{EXACT_HEADERS}\n,SCH-NO-STAFF,No Staff Primary,Gulu,Client,100,,,,\n"
        res = self._post_and_import(self._csv(body))

        self.assertEqual(res.status_code, 200, res.content)
        school = School.objects.get(school_id="SCH-NO-STAFF")
        self.assertIsNone(school.account_owner_id)
        self.assertEqual(school.account_owner_status, "pending")

    def test_account_owner_matched_and_unmatched(self):
        body = (
            f"{EXACT_HEADERS}\n"
            "Aisha Dar,SCH-OWN-1,Owned Primary,Gulu,Client,100,,,,\n"
            "Ghost Person,SCH-OWN-2,Orphan Primary,Gulu,Client,100,,,,\n"
        )
        res = self._post_and_import(self._csv(body))
        self.assertEqual(res.status_code, 200, res.content)
        matched = School.objects.get(school_id="SCH-OWN-1")
        self.assertEqual(matched.account_owner_status, "matched")
        self.assertEqual(matched.account_owner_id, self.staff.id)
        unmatched = School.objects.get(school_id="SCH-OWN-2")
        self.assertEqual(unmatched.account_owner_status, "matched")
        self.assertEqual(unmatched.account_owner_name_raw, "Ghost Person")
        from apps.accounts.models import User

        self.assertTrue(User.objects.filter(name="Ghost Person").exists())

    def test_row_results_persisted(self):
        body = (
            f"{EXACT_HEADERS}\n"
            "Aisha Dar,SCH-RR-1,Good Primary,Gulu,Client,100,,,,\n"
            "Aisha Dar,,Bad Primary,Gulu,Client,100,,,,\n"
        )
        res = self._post(self._csv(body))
        batch_id = res.json()["upload_batch_id"]
        rows = UploadBatchRowResult.objects.filter(upload_batch_id=batch_id)
        self.assertEqual(rows.count(), 2)
        self.assertEqual(rows.filter(status="created").count(), 1)
        self.assertEqual(rows.filter(status="failed").count(), 1)

    def test_blank_current_partner_type_does_not_demote_existing_core_school(self):
        """A re-upload that only touches enrollment (Current Partner Type
        cell left blank) must not silently demote a Core school back to
        Client — map_school_type() defaults blank text to "client", which
        used to defeat the upsert's blank-doesn't-overwrite guard."""
        core_body = (
            f"{EXACT_HEADERS}\nAisha Dar,SCH-CORE,Core Primary,Gulu,Core,100,,,,\n"
        )
        self.assertEqual(self._post_and_import(self._csv(core_body)).status_code, 200)
        self.assertEqual(School.objects.get(school_id="SCH-CORE").school_type, "core")

        # Re-upload with the Current Partner Type column blank.
        partial_body = (
            f"{EXACT_HEADERS}\nAisha Dar,SCH-CORE,Core Primary,Gulu,,150,,,,\n"
        )
        res = self._post_and_import(self._csv(partial_body), update_existing=True)
        self.assertEqual(res.status_code, 200, res.content)
        school = School.objects.get(school_id="SCH-CORE")
        self.assertEqual(school.school_type, "core")
        self.assertEqual(school.enrollment, 150)

    def test_blank_staff_name_reupload_retains_owner_and_updates_other_fields(self):
        """An optional blank Staff Name must not erase an existing owner."""
        owned_body = (
            f"{EXACT_HEADERS}\nAisha Dar,SCH-OWNED,Owned Primary,Gulu,Client,100,,,,\n"
        )
        self.assertEqual(self._post_and_import(self._csv(owned_body)).status_code, 200)
        school = School.objects.get(school_id="SCH-OWNED")
        self.assertEqual(school.account_owner_status, "matched")
        self.assertEqual(school.account_owner_id, self.staff.id)

        # Re-upload with Staff Name blank.
        partial_body = (
            f"{EXACT_HEADERS}\n,SCH-OWNED,Owned Primary,Gulu,Client,150,,,,\n"
        )
        res = self._post_and_import(self._csv(partial_body), update_existing=True)
        self.assertEqual(res.status_code, 200, res.content)
        school = School.objects.get(school_id="SCH-OWNED")
        self.assertEqual(school.account_owner_status, "matched")
        self.assertEqual(school.account_owner_id, self.staff.id)
        self.assertEqual(school.enrollment, 150)

    def test_auto_import_failure_is_recorded_honestly_not_swallowed(self):
        """A failure during the auto-import step used to be stamped
        status="imported" (set before the import even ran) and the raw
        exception propagated uncaught to the caller. Now: the batch is
        marked "failed" with the real error recorded, and the caller gets a
        normal, handleable 400 instead of a bare 500. The recorded error stays
        on the batch for an operator; the response says what failed without
        repeating an internal exception back to the person uploading."""
        from unittest.mock import patch

        from apps.schools.models import UploadBatch

        body = f"{EXACT_HEADERS}\nAisha Dar,SCH-BOOM,Boom Primary,Gulu,Client,100,,,,\n"
        with patch(
            "apps.schools.upload_service.import_school_batch",
            side_effect=RuntimeError("simulated import crash"),
        ):
            res = self._post(self._csv(body))

        self.assertEqual(res.status_code, 400, res.content)
        self.assertFalse(School.objects.filter(school_id="SCH-BOOM").exists())

        # The caller is told the import failed, not what crashed. An arbitrary
        # exception's text can carry a constraint name, a query fragment or a
        # path, and the person uploading a spreadsheet can do nothing with any
        # of it.
        message = res.json()["message"]
        self.assertIn("School import failed", message)
        self.assertNotIn("simulated import crash", message)
        self.assertNotIn("RuntimeError", message)

        # Nothing is swallowed, though: the batch carries the real reason for
        # whoever has to work out what happened.
        batch = UploadBatch.objects.get(file_name="schools.csv")
        self.assertEqual(batch.status, "failed")
        self.assertIn("simulated import crash", batch.error_summary)

    def test_directory_returns_uploaded_rows(self):
        body = f"{EXACT_HEADERS}\nAisha Dar,SCH-DIR,Directory Primary,Gulu,Client,100,,,,\n"
        self.assertEqual(self._post_and_import(self._csv(body)).status_code, 200)
        res = self.client.get("/api/schools?pageSize=200")
        self.assertEqual(res.status_code, 200, res.content)
        ids = [r["schoolId"] for r in res.json()["data"]]
        self.assertIn("SCH-DIR", ids)

    def test_uploads_read_endpoints(self):
        body = f"{EXACT_HEADERS}\nAisha Dar,SCH-RD,Read Primary,Gulu,Client,100,,,,\n"
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


class ResolveGeographyTest(APITestCase):
    """Direct coverage for upload_service._resolve_geography().

    This proves the template's Sub County column resolves deterministically,
    including district inference when the sub-county name is unique, without
    reviving the old arbitrary District.objects.first() fallback.
    """

    def setUp(self):
        self.region = Region.objects.create(name="Northern")
        self.gulu = District.objects.create(name="Gulu", region=self.region)
        self.lira = District.objects.create(name="Lira", region=self.region)

    def test_district_name_resolves_directly(self):
        from apps.schools.upload_service import _resolve_geography

        district, sub_county, ambiguous = _resolve_geography("Gulu", "")
        self.assertEqual(district, self.gulu)
        self.assertIsNone(sub_county)
        self.assertEqual(ambiguous, [])

    def test_unique_sub_county_infers_correct_district(self):
        from apps.geography.models import SubCounty
        from apps.schools.upload_service import _resolve_geography

        sc = SubCounty.objects.create(name="Bardege", district=self.gulu)
        district, sub_county, ambiguous = _resolve_geography("", "Bardege")
        self.assertEqual(district, self.gulu)
        self.assertEqual(sub_county, sc)
        self.assertEqual(ambiguous, [])

    def test_ambiguous_sub_county_name_is_reported_not_guessed(self):
        from apps.geography.models import SubCounty
        from apps.schools.upload_service import _resolve_geography

        SubCounty.objects.create(name="Central", district=self.gulu)
        SubCounty.objects.create(name="Central", district=self.lira)
        district, sub_county, ambiguous = _resolve_geography("", "Central")
        self.assertIsNone(district)
        self.assertIsNone(sub_county)
        self.assertEqual(sorted(ambiguous), ["Gulu", "Lira"])

    def test_no_location_info_resolves_to_none_never_an_arbitrary_district(self):
        from apps.schools.upload_service import _resolve_geography

        district, sub_county, ambiguous = _resolve_geography("", "")
        self.assertIsNone(district)
        self.assertIsNone(sub_county)
        self.assertEqual(ambiguous, [])

    def test_unmatched_sub_county_resolves_to_none(self):
        from apps.schools.upload_service import _resolve_geography

        district, sub_county, ambiguous = _resolve_geography("", "Nowhereville")
        self.assertIsNone(district)
        self.assertIsNone(sub_county)
        self.assertEqual(ambiguous, [])
