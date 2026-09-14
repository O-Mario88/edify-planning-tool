"""SSA integrity for Impact Assessment (IA review, owner, 2026-09-13).

Pins the owner's decisions for collection data:

- every SSA — keyed by field staff, by Impact Assessment, imported from a file
  or submitted by a partner — lands pending until a DIFFERENT verifier confirms
  it: an Impact Assessment officer in the school's country, or the Country
  Director for scores Impact Assessment collected;
- a returned SSA carries its reason and tells its collector;
- scores collected on a visit are linked to it, dated by it, and re-keying
  them never mints a duplicate;
- the queue, the import, its result, the upload history and the unmatched
  queue are bounded to the reader's country.
"""

from __future__ import annotations

from datetime import date, datetime

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity
from apps.audit.models import AuditLog
from apps.core.enums import SsaIntervention
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.notifications.models import Notification
from apps.schools.models import (
    SSAImportBatch,
    School,
    UnmatchedSSARecord,
    UploadBatch,
)
from apps.ssa import services
from apps.ssa.models import SsaRecord, SsaScore

LOCMEM = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "ssa-collection-integrity",
    }
}

SCORES = [{"intervention": code, "score": 6.0} for code, _ in SsaIntervention.choices]
HEADERS = (
    "School ID,Assessment Date,Teaching Environment,Financial Health,Christlike Behaviour,"
    "Exposure to the Word of God,Government Requirement,Leadership,"
    "Enrolment Score,Learning Environment"
)


def _user(email, role, country="Uganda", name=None):
    user = User.objects.create_user(
        email=email,
        name=name or email.split("@")[0].title(),
        roles=[role],
        active_role=role,
        password="x",
        is_active=True,
    )
    StaffProfile.objects.create(user=user, title=role, country=country)
    return user


class IntegrityFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ug = Region.objects.create(name="SI Central", country="Uganda")
        cls.ke = Region.objects.create(name="SI Rift", country="Kenya")
        cls.ug_district = District.objects.create(name="SI Wakiso", region=cls.ug)
        cls.ke_district = District.objects.create(name="SI Nakuru", region=cls.ke)
        cls.school = School.objects.create(
            school_id="SI-UG-1",
            name="SI Kampala",
            region=cls.ug,
            district=cls.ug_district,
        )
        cls.ke_school = School.objects.create(
            school_id="SI-KE-1",
            name="SI Nakuru",
            region=cls.ke,
            district=cls.ke_district,
        )
        cls.ia = _user("si-ia@t.org", EdifyRole.IMPACT_ASSESSMENT.value, name="Ida")
        cls.ia2 = _user("si-ia2@t.org", EdifyRole.IMPACT_ASSESSMENT.value, name="Ivan")
        cls.ke_ia = _user("si-ke-ia@t.org", EdifyRole.IMPACT_ASSESSMENT.value, "Kenya")
        cls.cd = _user("si-cd@t.org", EdifyRole.COUNTRY_DIRECTOR.value, name="Dan")
        cls.cceo = _user("si-cceo@t.org", EdifyRole.CCEO.value, name="Cara")
        cls.admin = _user("si-admin@t.org", EdifyRole.ADMIN.value, country="")

    def _record(
        self, school=None, *, keyer=None, collector_type="staff", status="pending", **kw
    ):
        keyer = keyer or self.cceo
        return SsaRecord.objects.create(
            school=school or self.school,
            date_of_ssa=kw.pop("date_of_ssa", date(2026, 5, 1)),
            fy=kw.pop("fy", "2026"),
            quarter="Q3",
            average_score=6.0,
            collector_type=collector_type,
            verification_status=status,
            uploaded_by=keyer.id,
            collected_by_user_id=keyer.id,
            **kw,
        )


class EverySourceLandsPendingTest(IntegrityFixture):
    def _upload(self, principal, collector, **extra):
        return services.upload(
            {
                "schoolId": self.school.school_id,
                "dateOfSsa": extra.pop("when", "2026-05-02"),
                "scores": SCORES,
                "collectorType": collector,
                **extra,
            },
            principal,
        )

    def test_staff_ia_and_partner_keyed_scores_wait_for_a_verifier(self):
        for when, principal, collector, source in (
            ("2026-05-02", self.cceo, "staff", services.SOURCE_STAFF_KEYED),
            ("2026-05-03", self.ia, "ia", services.SOURCE_IA_KEYED),
            ("2026-05-04", self.cceo, "partner", services.SOURCE_PARTNER),
        ):
            with self.subTest(collector=collector):
                result = self._upload(principal, collector, when=when)
                record = SsaRecord.objects.get(id=result["id"])
                self.assertEqual(record.verification_status, "pending")
                self.assertEqual(record.verification_source, source)
                self.assertIsNone(record.verified_by_user_id)
        self.school.refresh_from_db()
        self.assertNotEqual(self.school.current_fy_ssa_status, "done")

    def test_a_file_import_lands_pending_and_blocks_another_countrys_school(self):
        from apps.ssa.upload_service import OUTSIDE_COUNTRY, upload_ssa_file

        scores = ",".join(["6"] * 8)
        body = f"{HEADERS}\nSI-UG-1,2026-05-09,{scores}\nSI-KE-1,2026-05-09,{scores}\n"
        upload_ssa_file(
            SimpleUploadedFile("si.csv", body.encode(), content_type="text/csv"),
            self.ia,
        )
        record = SsaRecord.objects.get(school=self.school)
        self.assertEqual(record.verification_status, "pending")
        self.assertEqual(record.verification_source, services.SOURCE_FILE_IMPORT)
        self.assertEqual(record.collector_type, "ia")
        self.assertFalse(SsaRecord.objects.filter(school=self.ke_school).exists())
        batch = SSAImportBatch.objects.get(uploaded_by=self.ia.id)
        blocked = batch.rows.get(school_id="SI-KE-1")
        self.assertEqual(blocked.status, "blocked")
        self.assertIn(OUTSIDE_COUNTRY, blocked.validation_errors)
        # The confirmation events wait for the confirmation; the import only
        # asks for baselines to be filled.
        from apps.outbox.models import OutboxEvent

        self.assertFalse(
            OutboxEvent.objects.filter(event_type="bt.ssa.confirmed").exists()
        )
        self.assertTrue(
            OutboxEvent.objects.filter(event_type="projects.baselines.capture").exists()
        )


class VerifierAuthorityTest(IntegrityFixture):
    def test_the_collector_and_uploader_may_not_decide_their_own_scores(self):
        record = self._record(keyer=self.ia, collector_type="ia")
        with self.assertRaises(Forbidden):
            services.verify_record(record, self.ia)
        with self.assertRaises(Forbidden):
            services.return_record(record, self.ia, "Typo")
        uploaded = self._record(keyer=self.cceo, date_of_ssa=date(2026, 5, 3))
        uploaded.uploaded_by = self.ia2.id
        uploaded.save()
        with self.assertRaises(Forbidden):
            services.verify_record(uploaded, self.ia2)

    def test_a_second_ia_officer_confirms_and_the_audit_row_names_the_basis(self):
        record = self._record(keyer=self.ia, collector_type="ia")
        services.verify_record(record, self.ia2)
        record.refresh_from_db()
        self.assertEqual(record.verification_status, "confirmed")
        self.assertEqual(record.verified_by_user_id, self.ia2.id)
        row = AuditLog.objects.get(action="ssa_verify", subject_id=record.id)
        self.assertEqual(row.payload["basis"], services.BASIS_IA)

    def test_the_country_director_confirms_only_ia_collected_scores(self):
        ia_scores = self._record(keyer=self.ia, collector_type="ia")
        services.verify_record(ia_scores, self.cd)
        self.assertEqual(
            AuditLog.objects.get(action="ssa_verify", subject_id=ia_scores.id).payload[
                "basis"
            ],
            services.BASIS_CD_FALLBACK,
        )
        staff_scores = self._record(keyer=self.cceo, date_of_ssa=date(2026, 5, 4))
        with self.assertRaises(Forbidden):
            services.verify_record(staff_scores, self.cd)
        with self.assertRaises(Forbidden):
            services.verify_record(
                self._record(date_of_ssa=date(2026, 5, 5)), self.cceo
            )

    def test_another_countrys_verifier_is_refused(self):
        with self.assertRaises(Forbidden):
            services.verify_record(self._record(), self.ke_ia)

    def test_admin_keys_but_never_confirms(self):
        with self.assertRaises(Forbidden):
            services.verify_record(self._record(), self.admin)

    def test_a_return_needs_a_reason_stores_it_and_tells_the_collector(self):
        activity = Activity.objects.create(
            activity_type="school_visit_ssa_collection",
            status="awaiting_ia_verification",
            school=self.school,
            fy="2026",
            planned_date=date(2026, 5, 1),
            responsible_staff_id=self.cceo.staff_profile.id,
        )
        record = self._record(source_activity=activity)
        with self.assertRaises(BadRequest):
            services.return_record(record, self.ia, "  ")
        services.return_record(record, self.ia, "Scores look transposed")
        record.refresh_from_db()
        self.assertEqual(record.verification_status, "returned")
        self.assertEqual(record.return_reason, "Scores look transposed")
        self.assertEqual(record.returned_by_user_id, self.ia.id)
        self.assertIsNotNone(record.returned_at)
        notice = Notification.objects.get(
            recipient_id=self.cceo.id, source_event_type=services.EVENT_SSA_RETURNED
        )
        self.assertEqual(notice.target_route, f"/my-plan/{activity.id}")
        self.assertIn("transposed", notice.body)

    def test_a_return_without_a_visit_opens_the_school_timeline(self):
        record = self._record(keyer=self.ia, collector_type="ia")
        services.return_record(record, self.ia2, "Wrong school")
        notice = Notification.objects.get(recipient_id=self.ia.id)
        self.assertEqual(notice.target_route, f"/schools/{self.school.id}#ssa-timeline")


class VisitLinkedScoresTest(IntegrityFixture):
    def _visit(self, **kw):
        return Activity.objects.create(
            activity_type="school_visit_ssa_collection",
            status=kw.pop("status", "completion_started"),
            school=self.school,
            fy="2026",
            planned_date=kw.pop("planned_date", date(2026, 6, 20)),
            responsible_staff_id=self.cceo.staff_profile.id,
            ssa_collection_expected=True,
            **kw,
        )

    def test_dated_by_the_visit_not_by_the_submission(self):
        started = timezone.make_aware(datetime(2026, 6, 18, 9, 0))
        visit = self._visit(execution_started_at=started)
        self.assertEqual(services.visit_assessment_date(visit), date(2026, 6, 18))
        visit.actual_delivery_date = date(2026, 6, 17)
        self.assertEqual(services.visit_assessment_date(visit), date(2026, 6, 17))
        self.assertEqual(
            services.visit_assessment_date(self._visit()), date(2026, 6, 20)
        )

    def test_re_keying_a_visit_updates_its_record_and_confirmed_scores_are_kept(self):
        visit = self._visit()
        payload = {
            "schoolId": self.school.school_id,
            "dateOfSsa": "2026-06-20",
            "scores": SCORES,
            "sourceActivityId": visit.id,
        }
        first = services.upload(payload, self.cceo)
        record = SsaRecord.objects.get(id=first["id"])
        services.return_record(record, self.ia, "Leadership looks wrong")
        second = services.upload(
            {**payload, "scores": [{**s, "score": 7.0} for s in SCORES]}, self.cceo
        )
        self.assertEqual(second["id"], first["id"])
        record.refresh_from_db()
        self.assertEqual(record.verification_status, "pending")
        self.assertEqual(record.return_reason, "")
        self.assertEqual(SsaRecord.objects.filter(source_activity=visit).count(), 1)
        self.assertEqual(SsaScore.objects.filter(ssa_record=record).count(), 8)
        self.assertEqual(record.average_score, 7.0)

        services.verify_record(record, self.ia)
        with self.assertRaises(BadRequest):
            services.upload(payload, self.cceo)

    def test_the_visit_is_verifiable_while_its_scores_wait_but_not_once_returned(self):
        from apps.activities.ia_services import assert_ssa_visit_is_verifiable

        visit = self._visit(status="awaiting_ia_verification")
        with self.assertRaises(BadRequest):
            assert_ssa_visit_is_verifiable(visit)
        record = self._record(source_activity=visit, date_of_ssa=date(2026, 6, 20))
        assert_ssa_visit_is_verifiable(visit)
        services.return_record(record, self.ia, "Blank form")
        with self.assertRaises(BadRequest):
            assert_ssa_visit_is_verifiable(visit)

    def test_the_completion_drawer_shows_a_refusal_instead_of_an_error_envelope(self):
        visit = self._visit(status="in_progress")
        self._record(date_of_ssa=timezone.make_aware(datetime(2026, 6, 20)))
        self.client.force_login(self.cceo)
        response = self.client.post(
            f"/activities/{visit.id}/ssa-upload/action",
            {f"score_{code}": "6" for code, _ in SsaIntervention.choices},
            HTTP_HX_REQUEST="true",
        )
        self.assertNotEqual(response.status_code, 500)
        self.assertContains(
            response, "already exists", status_code=response.status_code
        )


class VerificationQueuePageTest(IntegrityFixture):
    def test_the_queue_lists_only_the_readers_country_and_offers_no_self_decision(self):
        mine = self._record(keyer=self.ia, collector_type="ia")
        theirs = self._record(keyer=self.cceo, date_of_ssa=date(2026, 5, 2))
        self._record(self.ke_school, date_of_ssa=date(2026, 5, 3))
        self.client.force_login(self.ia)
        page = self.client.get("/ssa/verification/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "SI Kampala")
        self.assertNotContains(page, "SI Nakuru")
        body = page.content.decode()
        self.assertIn(f'hx-get="/ssa/verification/{theirs.id}/return-drawer"', body)
        self.assertNotIn(f'hx-get="/ssa/verification/{mine.id}/return-drawer"', body)
        self.assertIn("Your scores: a different verifier confirms them", body)

    def test_posting_another_countrys_record_is_not_found(self):
        foreign = self._record(self.ke_school)
        self.client.force_login(self.ia)
        response = self.client.post(
            "/ssa/verification/", {"record_id": foreign.id, "action": "verify"}
        )
        self.assertEqual(response.status_code, 404)
        foreign.refresh_from_db()
        self.assertEqual(foreign.verification_status, "pending")

    def test_the_return_drawer_posts_a_reason_and_refuses_own_scores(self):
        record = self._record()
        own = self._record(
            keyer=self.ia, collector_type="ia", date_of_ssa=date(2026, 5, 9)
        )
        self.client.force_login(self.ia)
        drawer = self.client.get(f"/ssa/verification/{record.id}/return-drawer")
        self.assertContains(drawer, 'name="reason"')
        refused = self.client.get(f"/ssa/verification/{own.id}/return-drawer")
        self.assertContains(refused, "not waiting for your verification")
        response = self.client.post(
            "/ssa/verification/",
            {"record_id": record.id, "action": "return", "reason": "Dates swapped"},
        )
        self.assertEqual(response.status_code, 302)
        record.refresh_from_db()
        self.assertEqual(record.return_reason, "Dates swapped")
        returned = self.client.get("/ssa/verification/?status=returned")
        self.assertContains(returned, "Dates swapped")

    def test_the_queue_page_cost_does_not_grow_with_its_rows(self):
        self.client.force_login(self.ia)
        self._record(date_of_ssa=date(2026, 4, 1))
        self.client.get("/ssa/verification/")
        with CaptureQueriesContext(connection) as small:
            self.client.get("/ssa/verification/")
        for day in range(2, 14):
            self._record(date_of_ssa=date(2026, 4, day))
        with CaptureQueriesContext(connection) as large:
            self.client.get("/ssa/verification/")
        self.assertEqual(len(large), len(small))


@override_settings(CACHES=LOCMEM)
class UploadResultAndHistoryTest(IntegrityFixture):
    def _import(self, principal, body, name="si.csv"):
        from apps.ssa.upload_service import upload_ssa_file

        upload_ssa_file(
            SimpleUploadedFile(name, body.encode(), content_type="text/csv"), principal
        )
        return SSAImportBatch.objects.filter(uploaded_by=principal.id).latest(
            "created_at"
        )

    def test_the_result_lists_refused_rows_and_links_the_worklist_not_planning(self):
        scores = ",".join(["6"] * 8)
        bad = ",".join(["6"] * 7 + ["11"])
        batch = self._import(
            self.ia,
            f"{HEADERS}\nSI-UG-1,2026-05-09,{scores}\nSI-UG-1,2026-05-10,{bad}\n",
        )
        self.client.force_login(self.ia)
        page = self.client.get(f"/ssa/upload/{batch.id}/result/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Rows not imported")
        self.assertContains(page, "out of range")
        self.assertContains(page, "/ia/dashboard/?view=collection")
        self.assertNotContains(page, "Open Planning Board")

    def test_another_countrys_batch_is_not_found_and_history_is_country_bound(self):
        scores = ",".join(["6"] * 8)
        ug_batch = self._import(
            self.ia, f"{HEADERS}\nSI-UG-1,2026-05-09,{scores}\n", "ug.csv"
        )
        ke_batch = self._import(
            self.ke_ia, f"{HEADERS}\nSI-KE-1,2026-05-09,{scores}\n", "ke.csv"
        )
        self.client.force_login(self.ke_ia)
        self.assertEqual(
            self.client.get(f"/ssa/upload/{ug_batch.id}/result/").status_code, 404
        )
        history = self.client.get("/ssa/upload/history/")
        self.assertContains(history, "ke.csv")
        self.assertNotContains(history, "ug.csv")
        self.assertContains(history, f"/ssa/upload/{ke_batch.id}/result/")
        self.client.force_login(self.cceo)
        self.assertNotEqual(self.client.get("/ssa/upload/history/").status_code, 200)

    def test_history_cost_does_not_grow_with_batches(self):
        scores = ",".join(["6"] * 8)
        self._import(self.ia, f"{HEADERS}\nSI-UG-1,2026-05-09,{scores}\n", "a.csv")
        self.client.force_login(self.ia)
        self.client.get("/ssa/upload/history/")
        with CaptureQueriesContext(connection) as small:
            self.client.get("/ssa/upload/history/")
        for day in range(10, 16):
            self._import(
                self.ia, f"{HEADERS}\nSI-UG-1,2026-05-{day},{scores}\n", f"b{day}.csv"
            )
        with CaptureQueriesContext(connection) as large:
            self.client.get("/ssa/upload/history/")
        self.assertEqual(len(large), len(small))

    def test_school_upload_history_is_country_bound(self):
        UploadBatch.objects.create(
            upload_type="ssa", file_name="kenyan.csv", uploaded_by=self.ke_ia.id
        )
        UploadBatch.objects.create(
            upload_type="ssa", file_name="ugandan.csv", uploaded_by=self.ia2.id
        )
        self.client.force_login(self.ia)
        page = self.client.get("/admin-panel/school-upload-history")
        self.assertContains(page, "ugandan.csv")
        self.assertNotContains(page, "kenyan.csv")


class UnmatchedQueueCountryTest(IntegrityFixture):
    def test_rows_are_placed_by_the_uploaders_country(self):
        ke_batch = SSAImportBatch.objects.create(
            file_name="ke.csv", uploaded_by=self.ke_ia.id, status="imported"
        )
        ug_batch = SSAImportBatch.objects.create(
            file_name="ug.csv", uploaded_by=self.ia2.id, status="imported"
        )
        ke_row = UnmatchedSSARecord.objects.create(
            batch=ke_batch, school_id="GHOST-KE", date_of_ssa="2026-05-01", scores={}
        )
        UnmatchedSSARecord.objects.create(
            batch=ug_batch, school_id="GHOST-UG", date_of_ssa="2026-05-01", scores={}
        )
        self.client.force_login(self.ia)
        page = self.client.get("/ssa/unmatched")
        self.assertContains(page, "GHOST-UG")
        self.assertNotContains(page, "GHOST-KE")
        self.assertNotContains(page, "SI Nakuru (SI-KE-1)")
        response = self.client.post(
            "/ssa/unmatched", {"record_id": ke_row.id, "action": "ignore"}
        )
        self.assertEqual(response.status_code, 404)
        ke_row.refresh_from_db()
        self.assertEqual(ke_row.status, "pending")


class NotificationRouteTest(TestCase):
    def test_returned_scores_open_the_visit_or_the_school(self):
        from apps.notifications.services import NotificationLinkResolver

        self.assertEqual(
            NotificationLinkResolver.resolve("ssa_returned", "Activity", "a1", "CCEO")[
                0
            ],
            "/my-plan/a1",
        )
        self.assertEqual(
            NotificationLinkResolver.resolve(
                "ssa_returned", "School", "s1", "ImpactAssessment"
            )[0],
            "/schools/s1#ssa-timeline",
        )


class ReturnedTodoTest(IntegrityFixture):
    def test_the_collector_is_asked_to_correct_and_the_cd_to_confirm_ia_scores(self):
        from apps.ssa.collection_todos import collection_todos

        today = timezone.localdate()
        record = self._record()
        services.return_record(record, self.ia, "Fix it")
        rows = collection_todos(self.cceo, self.cceo.active_role, today)
        self.assertEqual([r["id"] for r in rows], ["ssa-returned-mine"])
        self.assertEqual(
            rows[0]["action_url"], "/ssa/verification/?status=returned&mine=1"
        )

        self._record(keyer=self.ia, collector_type="ia", date_of_ssa=date(2026, 5, 7))
        self._record(date_of_ssa=date(2026, 5, 8))  # staff scores: IA's to confirm
        cd_rows = collection_todos(self.cd, self.cd.active_role, today)
        self.assertEqual([r["id"] for r in cd_rows], ["ssa-cd-fallback"])
        self.assertIn("Confirm 1 SSA record", cd_rows[0]["title"])

    def test_an_uploader_is_told_about_refused_rows(self):
        from apps.schools.models import SSAImportRow
        from apps.ssa.collection_todos import collection_todos

        batch = SSAImportBatch.objects.create(
            file_name="x.csv", uploaded_by=self.ia.id, status="staged"
        )
        SSAImportRow.objects.create(
            batch=batch, row_number=2, school_id="X", status="blocked", scores={}
        )
        rows = collection_todos(self.ia, self.ia.active_role, timezone.localdate())
        blocked = [r for r in rows if r["id"] == "ssa-import-blocked-mine"]
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0]["action_url"], "/ssa/upload/history/?has_blocked=1")
        self.assertNotIn(
            "ssa-import-blocked-mine",
            [
                r["id"]
                for r in collection_todos(
                    self.ia2, self.ia2.active_role, timezone.localdate()
                )
            ],
        )
