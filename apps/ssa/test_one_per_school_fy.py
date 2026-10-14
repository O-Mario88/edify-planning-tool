"""One SSA per school per financial year (owner, 2026-10-14).

The owner's acceptance tests, in order: entry from the School Profile, an
uploaded year greying the button, a previous year leaving it open, two people
racing, the upload skipping years the database holds and rows repeating
each other, the cluster and district reading the new record, a role or a
school outside the scope refused, and the database refusing a second record
written past every check.
"""

from __future__ import annotations

import io
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.audit.models import AuditLog
from apps.clusters.models import Cluster
from apps.core.enums import SsaIntervention
from apps.core.fy import get_fy_date_range
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa import creation
from apps.ssa import services as ssa_services
from apps.ssa.models import SsaRecord, SsaScore

CODES = [code for code, _label in SsaIntervention.choices]


def _user(email, role):
    return User.objects.create_user(
        email=email,
        name=email.split("@")[0].title(),
        roles=[role],
        active_role=role,
        password="x",
        is_active=True,
    )


class OneSsaPerSchoolYearTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="One SSA Region")
        self.district = District.objects.create(
            name="One SSA District", region=self.region
        )
        self.cluster = Cluster.objects.create(
            name="One SSA Cluster", region=self.region, district=self.district
        )
        self.cceo = _user("onessa-cceo@t.org", EdifyRole.CCEO.value)
        self.cceo_sp = StaffProfile.objects.create(user=self.cceo, title="CCEO")
        self.ia = _user("onessa-ia@t.org", EdifyRole.IMPACT_ASSESSMENT.value)
        self.verifier = _user("onessa-ia2@t.org", EdifyRole.IMPACT_ASSESSMENT.value)
        self.fy = creation.current_fy()
        self.last_fy = str(int(self.fy) - 1)
        self.school = self._school("ONE-1", "Hill School")
        self.today = timezone.localdate()

    # ── fixtures ─────────────────────────────────────────────────────────────
    def _school(self, code, name, *, assign=True):
        school = School.objects.create(
            school_id=code,
            name=name,
            region=self.region,
            district=self.district,
            cluster_id=self.cluster.id,
        )
        if assign:
            StaffSchoolAssignment.objects.create(
                staff=self.cceo_sp, school_id=school.id
            )
        return school

    def _record(self, school, fy, status="confirmed", score=6.0):
        start = get_fy_date_range(fy)[0] + timedelta(days=20)
        record = SsaRecord.objects.create(
            school=school,
            date_of_ssa=start,
            fy=fy,
            quarter="Q1",
            average_score=score,
            uploaded_by="seed",
            verification_status=status,
            verification_source=ssa_services.SOURCE_FILE_IMPORT,
        )
        SsaScore.objects.bulk_create(
            SsaScore(ssa_record=record, intervention=code, score=score)
            for code in CODES
        )
        return record

    def _form(self, score="7.4", day=None):
        data = {"date_of_ssa": (day or self.today).isoformat()}
        data.update({f"score_{code}": score for code in CODES})
        return data

    def _profile(self, user=None):
        self.client.force_login(user or self.cceo)
        return self.client.get(f"/schools/{self.school.id}").content.decode()

    def _live(self, school=None):
        return SsaRecord.objects.filter(
            school=school or self.school, fy=self.fy, deleted_at__isnull=True
        )

    # ── Test 1: manual entry from the profile ────────────────────────────────
    def test_1_entry_from_the_profile_saves_and_greys_the_button(self):
        html = self._profile()
        self.assertIn(f'hx-get="/schools/{self.school.id}/ssa-entry"', html)
        self.assertIn(f"No FY{self.fy} SSA", html)
        self.assertNotIn("data-ssa-entry-locked", html)

        drawer = self.client.get(f"/schools/{self.school.id}/ssa-entry")
        self.assertContains(drawer, "Save SSA")
        response = self.client.post(
            f"/schools/{self.school.id}/ssa-entry", self._form()
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("EdifyLive", response.content.decode())

        record = self._live().get()
        self.assertEqual(record.fy, self.fy)
        self.assertEqual(record.average_score, 7.4)
        self.assertEqual(record.verification_status, "pending")
        self.assertEqual(record.collected_by_user_id, self.cceo.id)
        self.assertEqual(record.scores.count(), 8)
        audit = AuditLog.objects.get(action="ssa_create", subject_id=record.id)
        self.assertEqual(audit.actor_role, EdifyRole.CCEO.value)
        self.assertEqual(audit.payload["fy"], self.fy)
        self.assertEqual(audit.payload["channel"], "school_profile")

        html = self._profile()
        self.assertIn("data-ssa-entry-locked", html)
        self.assertIn(f"SSA already entered for FY{self.fy}", html)
        self.assertIn(f"SSA FY{self.fy}: 7.4", html)
        self.assertNotIn(f'hx-get="/schools/{self.school.id}/ssa-entry"', html)

    # ── Test 2: an uploaded year greys it ────────────────────────────────────
    def test_2_an_existing_uploaded_ssa_greys_the_button_and_the_form(self):
        self._record(self.school, self.fy, status="pending", score=6.8)
        html = self._profile()
        self.assertIn("data-ssa-entry-locked", html)
        self.assertIn("Source: File import", html)
        drawer = self.client.get(f"/schools/{self.school.id}/ssa-entry")
        self.assertContains(drawer, "data-ssa-entry-held")
        self.assertNotContains(drawer, "data-ssa-entry-form")

    # ── Test 3: a previous year leaves it open ───────────────────────────────
    def test_3_only_a_previous_year_s_ssa_leaves_the_button_open(self):
        self._record(self.school, self.last_fy)
        html = self._profile()
        self.assertIn(f'hx-get="/schools/{self.school.id}/ssa-entry"', html)
        self.assertNotIn("data-ssa-entry-locked", html)

    def test_a_returned_record_leaves_the_year_free(self):
        self._record(self.school, self.fy, status="returned")
        self.assertIsNone(creation.year_record(self.school, self.fy))
        self.assertNotIn("data-ssa-entry-locked", self._profile())

    # ── Test 4: two people at once ───────────────────────────────────────────
    def test_4_the_second_of_two_saves_is_refused_and_writes_nothing(self):
        self.client.force_login(self.cceo)
        # Both opened the drawer while the year was free.
        self.assertContains(
            self.client.get(f"/schools/{self.school.id}/ssa-entry"), "Save SSA"
        )
        self.client.post(f"/schools/{self.school.id}/ssa-entry", self._form("7.4"))

        self.client.force_login(self.ia)
        response = self.client.post(
            f"/schools/{self.school.id}/ssa-entry", self._form("5.0")
        )
        self.assertContains(
            response,
            f"SSA already exists for this school for FY{self.fy}. "
            "The record was not added.",
        )
        self.assertEqual(self._live().count(), 1)
        self.assertEqual(self._live().get().average_score, 7.4)

    def test_the_service_refuses_a_second_record_whichever_way_it_comes(self):
        payload = {
            "schoolId": self.school.school_id,
            "dateOfSsa": self.today.isoformat(),
            "scores": [{"intervention": c, "score": 6} for c in CODES],
        }
        ssa_services.upload(payload, self.ia)
        with self.assertRaises(creation.SsaAlreadyExists):
            ssa_services.upload(
                {**payload, "dateOfSsa": (self.today - timedelta(days=1)).isoformat()},
                self.ia,
            )
        # The API says it in the same words.
        self.client.force_login(self.ia)
        response = self.client.post(
            "/api/ssa", payload, content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("SSA already exists for this school", response.content.decode())
        self.assertEqual(self._live().count(), 1)

    def test_a_race_past_the_check_is_refused_by_the_database_in_words(self):
        self._record(self.school, self.fy, status="pending")
        with self.assertRaises(creation.SsaAlreadyExists):
            with creation.year_guard(self.fy), transaction.atomic():
                SsaRecord.objects.create(
                    school=self.school,
                    date_of_ssa=timezone.now(),
                    fy=self.fy,
                    quarter="Q1",
                    uploaded_by="race",
                )
        self.assertEqual(self._live().count(), 1)

    def test_confirming_a_returned_record_never_gives_a_year_two(self):
        returned = self._record(self.school, self.fy, status="returned")
        self._record(self.school, self.fy, status="pending")
        with self.assertRaises(creation.SsaAlreadyExists):
            ssa_services.verify_record(returned, self.verifier)
        returned.refresh_from_db()
        self.assertEqual(returned.verification_status, "returned")

    # ── Tests 5, 6 and 12: the upload ────────────────────────────────────────
    def _csv(self, rows):
        header = "School ID,Assessment Date," + ",".join(CODES)
        lines = [header]
        for school_id, day, score in rows:
            lines.append(f"{school_id},{day}," + ",".join([str(score)] * 8))
        upload = io.BytesIO("\n".join(lines).encode())
        upload.name = "ssa.csv"
        return upload

    def test_5_and_10_the_upload_skips_years_the_database_holds(self):
        from apps.ssa.upload_service import upload_ssa_file

        a, b = self.school, self._school("ONE-2", "River School")
        c, d = self._school("ONE-3", "Lake School"), self._school("ONE-4", "Plain")
        self._record(a, self.fy)
        self._record(c, self.fy, status="pending")
        day = self.today.isoformat()
        result = upload_ssa_file(
            self._csv([(s.school_id, day, 7) for s in (a, b, c, d)]), self.ia
        )
        self.assertEqual(result["total_rows"], 4)
        self.assertEqual(result["created_rows"], 2)
        self.assertEqual(result["duplicate_rows"], 2)
        self.assertEqual(len(result["errors"]), 0)
        self.assertIn("Imported: 2", result["message"])
        self.assertIn("Skipped — existing SSA: 2", result["message"])
        self.assertEqual(
            {(r["school_id"], r["reason"]) for r in result["skipped"]},
            {
                (a.school_id, creation.EXISTING_REASON),
                (c.school_id, creation.EXISTING_REASON),
            },
        )
        for school in (a, b, c, d):
            self.assertEqual(self._live(school).count(), 1, school.name)
        self.assertEqual(self._live(a).get().average_score, 6.0)

        # The result page lists the skipped rows.
        self.client.force_login(self.ia)
        from apps.schools.models import SSAImportBatch

        batch = SSAImportBatch.objects.latest("created_at")
        page = self.client.get(f"/ssa/upload/{batch.id}/result/").content.decode()
        self.assertIn("Skipped — SSA already exists", page)
        self.assertIn(a.school_id, page)
        self.assertIn(c.school_id, page)

        # An upload records who, which file and what it did.
        audit = AuditLog.objects.filter(action="ssa_upload").latest("id")
        self.assertEqual(audit.payload["imported"], 2)
        self.assertEqual(audit.payload["skippedExisting"], 2)

    def test_6_a_mixed_file_imports_the_new_skips_the_existing_reports_errors(self):
        from apps.ssa.upload_service import upload_ssa_file

        day = self.today.isoformat()
        new = [self._school(f"NEW-{i}", f"New {i}") for i in range(6)]
        old = [self._school(f"OLD-{i}", f"Old {i}") for i in range(3)]
        for school in old:
            self._record(school, self.fy)
        rows = [(s.school_id, day, 6) for s in new + old]
        rows.append((new[0].school_id, day, 11))  # out of range: an error
        result = upload_ssa_file(self._csv(rows), self.ia)
        self.assertEqual(result["created_rows"], 6)
        self.assertEqual(result["duplicate_rows"], 3)
        self.assertEqual(len(result["errors"]), 1)
        for school in new + old:
            self.assertEqual(self._live(school).count(), 1)

    def test_12_a_file_repeating_a_school_s_year_imports_it_once(self):
        from apps.ssa.upload_service import upload_ssa_file

        day = self.today.isoformat()
        result = upload_ssa_file(
            self._csv(
                [(self.school.school_id, day, 7.2), (self.school.school_id, day, 7.5)]
            ),
            self.ia,
        )
        self.assertEqual(result["created_rows"], 1)
        self.assertEqual(result["duplicate_rows"], 1)
        self.assertEqual(
            result["skipped"][0]["reason"], "Duplicate of row 2 in this file"
        )
        self.assertEqual(self._live().get().average_score, 7.2)

    def test_23_a_year_an_upload_took_greys_the_profile_s_button(self):
        from apps.ssa.upload_service import upload_ssa_file

        self.assertNotIn("data-ssa-entry-locked", self._profile())
        upload_ssa_file(
            self._csv([(self.school.school_id, self.today.isoformat(), 6)]), self.ia
        )
        self.assertIn("data-ssa-entry-locked", self._profile())

    # ── Tests 7 and 8: the cluster and the district read the record ──────────
    def test_7_and_8_cluster_and_district_profiles_read_the_new_record(self):
        from apps.analytics import profile_intelligence as pi

        self.client.force_login(self.cceo)
        self.client.post(f"/schools/{self.school.id}/ssa-entry", self._form("7.4"))
        record = self._live().get()
        # Every SSA counts once a different verifier confirms it (IA review,
        # 2026-09-13); then the cluster and the district read it, with
        # nothing written to either.
        before = pi.build(pi.cluster_scope(self.cluster), self.fy)["ssa"]["current"]
        self.assertIsNone(before)
        ssa_services.verify_record(record, self.verifier)
        cluster = pi.build(pi.cluster_scope(self.cluster), self.fy)
        district = pi.build(pi.district_scope(self.district), self.fy)
        self.assertEqual(cluster["ssa"]["current"], 7.4)
        self.assertEqual(district["ssa"]["current"], 7.4)

    # ── Tests 9 and 19: who may ──────────────────────────────────────────────
    def test_9_another_role_is_refused_and_nothing_is_written(self):
        accountant = _user("onessa-acc@t.org", EdifyRole.PROGRAM_ACCOUNTANT.value)
        self.client.force_login(accountant)
        response = self.client.post(
            f"/schools/{self.school.id}/ssa-entry", self._form()
        )
        self.assertIn(response.status_code, (403, 404))
        self.assertFalse(self._live().exists())
        self.assertNotIn("Enter SSA Score", self._profile(accountant))

    def test_a_school_outside_the_officer_s_scope_is_refused(self):
        stranger = self._school("ONE-9", "Far School", assign=False)
        self.client.force_login(self.cceo)
        response = self.client.post(f"/schools/{stranger.id}/ssa-entry", self._form())
        self.assertIn(response.status_code, (403, 404))
        self.assertFalse(self._live(stranger).exists())

    def test_a_date_outside_the_current_year_is_refused(self):
        self.client.force_login(self.cceo)
        first = get_fy_date_range(self.fy)[0].date()
        response = self.client.post(
            f"/schools/{self.school.id}/ssa-entry",
            self._form(day=first - timedelta(days=1)),
        )
        self.assertContains(response, f"Choose a date in FY{self.fy}")
        self.assertFalse(self._live().exists())

    # ── Test 10: the database itself ─────────────────────────────────────────
    def test_10_the_database_refuses_a_second_live_record_for_a_year(self):
        self._record(self.school, self.fy, status="confirmed")
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._record(self.school, self.fy, status="pending")
        # A returned or deleted record does not hold the year.
        self._record(self.school, self.fy, status="returned")
        self.assertEqual(
            SsaRecord.objects.filter(school=self.school, fy=self.fy).count(), 2
        )
