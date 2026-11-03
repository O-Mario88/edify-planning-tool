"""Bulk Upload — School Visits (owner, 2026-11-02; ID-based, 2026-11-03).

Pinned here:

  1. A file needs five columns — planned_activity_id, school_id, visit_sf_id,
     training_sf_id, completed_date — read whatever their case, spacing or
     order; any other column is ignored, so a raw Salesforce / Planning
     Oversight export uploads as it is.
  2. A line names its visit by planned_activity_id alone; its school_id must
     be that visit's school. Nothing is matched by guessing.
  3. Confirming completes each ready line through the visit's own workflow:
     its visit_sf_id and completed_date are recorded and, being from the
     Salesforce export, it is approved at once. Work entered from the drawer
     still waits for its lead.
  4. Completed visits are skipped, never recounted; a line repeated in the
     file is processed once; a file uploaded again changes no total.
  5. A malformed line (an ID missing, both or neither Salesforce ID, a bad
     date, an ID not in Edify) is reported, and the rest of the file still
     completes. The error report lists the IDs Edify does not hold.
  6. Only Impact Assessment and Admin run it.
"""

from __future__ import annotations

from datetime import date, timedelta
from io import BytesIO

import openpyxl
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.activities.models import Activity
from apps.bulk_completion.apply import apply_batch
from apps.bulk_completion.models import BatchStatus, BulkCompletionBatch, RowStatus
from apps.bulk_completion.staging import stage_upload
from apps.core.exceptions import BadRequest
from apps.core.rbac import EdifyRole
from apps.notifications.models import Notification
from apps.pl_review.test_completion_reviews import ReviewFixture, _staff

HEADINGS = "planned_activity_id,school_id,visit_sf_id,training_sf_id,completed_date"


def visit_file(*lines: str, name: str = "visits.csv", headings=HEADINGS):
    body = "\n".join([headings, *lines]) + "\n"
    return SimpleUploadedFile(name, body.encode("utf-8"), content_type="text/csv")


def _sheet_values(response, index=0) -> list:
    sheet = openpyxl.load_workbook(BytesIO(response.content)).worksheets[index]
    return [cell for row in sheet.iter_rows(values_only=True) for cell in row]


class BulkFixture(ReviewFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.ia_user, cls.ia = _staff(
            "bulk-ia@t.test", "Ida", EdifyRole.IMPACT_ASSESSMENT
        )

    def setUp(self):
        self.done_on = date.today() - timedelta(days=1)

    def _visit(self, owner=None, **extra):
        values = {"status": "scheduled", "planned_date": date.today()}
        values.update(extra)
        return self._completion(owner or self.james.id, **values)

    def _line(self, visit, sf_id, *, school=None, day=None, training_sf=""):
        if school is None:
            school = visit.school.school_id if visit and visit.school_id else ""
        done = day if isinstance(day, str) else (day or self.done_on).isoformat()
        return ",".join([visit.id if visit else "", school, sf_id, training_sf, done])

    def _stage(self, *lines, user=None, name="visits.csv", headings=HEADINGS):
        return stage_upload(
            visit_file(*lines, name=name, headings=headings),
            "visit",
            user or self.ia_user,
        )

    def _statuses(self, batch):
        return list(batch.rows.order_by("row_number").values_list("status", flat=True))

    def _messages(self, batch):
        return list(batch.rows.order_by("row_number").values_list("message", flat=True))


class ConfirmingCompletesAndApprovesUploadedVisits(BulkFixture):
    def test_a_ready_line_links_its_visit_school_and_salesforce_id(self):
        visit = self._visit()
        batch = self._stage(self._line(visit, "SVE-50001"))
        self.assertEqual(self._statuses(batch), [RowStatus.READY])
        visit.refresh_from_db()
        self.assertEqual(visit.status, "scheduled", "nothing changes before confirm")

        apply_batch(batch, self.ia_user)

        visit.refresh_from_db()
        self.assertEqual(visit.salesforce_activity_id, "SVE-50001")
        self.assertEqual(visit.school_id, self.school.id)
        self.assertEqual(visit.actual_delivery_date, self.done_on)
        self.assertEqual(visit.status, "ia_verified")
        self.assertEqual(visit.ia_verification_status, "confirmed")
        self.assertEqual(visit.pl_reviewed_by, self.ia_user.id)
        batch.refresh_from_db()
        self.assertEqual(batch.status, BatchStatus.APPLIED)
        self.assertEqual(self._statuses(batch), [RowStatus.COMPLETED])
        # Approved as it landed: the lead is asked nothing about it.
        self.assertFalse(
            Notification.objects.filter(recipient_id=self.pl_user.id).exists()
        )

    def test_manual_entry_from_the_drawer_still_waits_for_the_lead(self):
        visit = self._visit()
        response = self.as_user(self.james_user).post(
            f"/activities/{visit.id}/salesforce-id/action",
            {"salesforce_id": "SVE-50002"},
            headers={"HX-Request": "true"},
        )
        self.assertEqual(response.status_code, 200, response.content)
        visit.refresh_from_db()
        self.assertEqual(visit.status, "submitted_to_pl")

    def test_visits_of_several_staff_and_schools_complete_together(self):
        mine = [self._visit() for _ in range(3)]
        marys = [self._visit(self.mary.id, school=self.mary_school) for _ in range(3)]
        lines = [self._line(v, f"SVE-6{n:04d}") for n, v in enumerate(mine + marys)]
        batch = apply_batch(self._stage(*lines), self.ia_user)
        self.assertEqual(batch.outcome_counts, {RowStatus.COMPLETED: 6})
        self.assertEqual(
            Activity.objects.filter(
                pk__in=[v.pk for v in mine + marys], status="ia_verified"
            ).count(),
            6,
        )

    def test_a_visit_id_may_be_sv_or_sve(self):
        # Owner, 2026-11-03: "school visit id uses either SVE- or SV-".
        sv, sve = self._visit(), self._visit()
        batch = self._stage(self._line(sv, "SV-00123"), self._line(sve, "SVE-00124"))
        self.assertEqual(self._statuses(batch), [RowStatus.READY, RowStatus.READY])
        apply_batch(batch, self.ia_user)
        sv.refresh_from_db()
        sve.refresh_from_db()
        self.assertEqual(sv.salesforce_activity_id, "SV-00123")
        self.assertEqual(sve.salesforce_activity_id, "SVE-00124")


class ExtraColumnsAreIgnored(BulkFixture):
    def test_a_raw_export_with_extra_columns_in_any_order_is_read(self):
        visit = self._visit()
        headings = (
            "Region,  COMPLETED_DATE ,Visit Owner,Visit SF ID,School Name,"
            "School ID,Training SF ID,Planned Activity ID,Notes"
        )
        line = ",".join(
            [
                "Central",
                self.done_on.isoformat(),
                "James",
                "SVE-50101",
                "Alpha Primary",
                "REV-1",
                "",
                visit.id,
                "went well",
            ]
        )
        batch = self._stage(line, headings=headings)
        self.assertEqual(self._statuses(batch), [RowStatus.READY])
        apply_batch(batch, self.ia_user)
        visit.refresh_from_db()
        self.assertEqual(visit.salesforce_activity_id, "SVE-50101")
        self.assertEqual(visit.status, "ia_verified")

    def test_a_dash_placeholder_gives_way_to_the_column_that_has_the_value(self):
        # The Planning Oversight export has its own "Completed Date" ("—" for
        # open work); the Salesforce date pasted beside it is the one read.
        visit = self._visit()
        headings = "Completed Date,planned_activity_id,school_id,visit_sf_id,"
        headings += "training_sf_id,completed_date"
        line = ",".join(
            ["—", visit.id, "REV-1", "SVE-50102", "", self.done_on.isoformat()]
        )
        batch = self._stage(line, headings=headings)
        self.assertEqual(self._statuses(batch), [RowStatus.READY])
        self.assertEqual(batch.rows.get().completed_on, self.done_on)

    def test_a_missing_required_column_is_named(self):
        with self.assertRaises(BadRequest) as refused:
            self._stage(
                "x,REV-1,SVE-1," + self.done_on.isoformat(),
                headings="planned_activity_id,school_id,visit_sf_id,completed_date",
            )
        self.assertIn("training_sf_id", str(refused.exception.detail))


class CompletedVisitsAreNeverRecounted(BulkFixture):
    def test_a_hundred_lines_with_completed_ones_skip_those_and_count_once(self):
        open_visits = [self._visit() for _ in range(90)]
        done = [
            self._visit(status="ia_verified", salesforce_activity_id=f"SVE-7{n:04d}")
            for n in range(10)
        ]
        lines = [self._line(v, f"SVE-8{n:04d}") for n, v in enumerate(open_visits)]
        lines += [self._line(v, v.salesforce_activity_id) for v in done]
        batch = self._stage(*lines)
        statuses = self._statuses(batch)
        self.assertEqual(statuses.count(RowStatus.READY), 90)
        self.assertEqual(statuses.count(RowStatus.ALREADY_COMPLETED), 10)

        apply_batch(batch, self.ia_user)
        verified = Activity.objects.filter(status="ia_verified").count()
        self.assertEqual(verified, 100)

        again = self._stage(*lines)
        self.assertEqual(set(self._statuses(again)), {RowStatus.ALREADY_COMPLETED})
        apply_batch(again, self.ia_user)
        self.assertEqual(Activity.objects.filter(status="ia_verified").count(), 100)

    def test_the_same_file_again_is_recognised(self):
        visit = self._visit()
        line = self._line(visit, "SVE-50010")
        apply_batch(self._stage(line), self.ia_user)
        again = self._stage(line)
        response = self.as_user(self.ia_user).get(
            f"/uploads/bulk-completion/batch/{again.id}"
        )
        self.assertContains(response, "This file was uploaded before")

    def test_a_line_repeated_in_the_file_is_processed_once(self):
        visit = self._visit()
        line = self._line(visit, "SVE-50011")
        batch = self._stage(line, line)
        self.assertEqual(self._statuses(batch), [RowStatus.READY, RowStatus.DUPLICATE])
        apply_batch(batch, self.ia_user)
        self.assertEqual(
            self._statuses(batch), [RowStatus.COMPLETED, RowStatus.DUPLICATE]
        )

    def test_one_visit_given_two_ids_is_sent_for_review(self):
        visit = self._visit()
        batch = self._stage(
            self._line(visit, "SVE-50012"), self._line(visit, "SVE-50013")
        )
        self.assertEqual(self._statuses(batch), [RowStatus.READY, RowStatus.REVIEW])

    def test_a_cancelled_upload_completes_nothing(self):
        visit = self._visit()
        batch = self._stage(self._line(visit, "SVE-50015"))
        client = self.as_user(self.ia_user)
        client.post(f"/uploads/bulk-completion/batch/{batch.id}/cancel")
        batch.refresh_from_db()
        self.assertEqual(batch.status, BatchStatus.CANCELLED)
        client.post(f"/uploads/bulk-completion/batch/{batch.id}/confirm")
        visit.refresh_from_db()
        self.assertEqual(visit.status, "scheduled")

    def test_confirming_twice_processes_the_file_once(self):
        visit = self._visit()
        batch = self._stage(self._line(visit, "SVE-50014"))
        apply_batch(batch, self.ia_user)
        batch.refresh_from_db()
        stamp = batch.applied_at
        apply_batch(batch, self.ia_user)
        batch.refresh_from_db()
        self.assertEqual(batch.applied_at, stamp)


class MalformedLinesAreReportedNeverGuessed(BulkFixture):
    def test_each_kind_of_malformed_line_is_invalid_with_its_reason(self):
        visit = self._visit()
        future = date.today() + timedelta(days=2)
        cases = [
            (self._line(None, "SVE-50030", school="REV-1"), "planned_activity_id"),
            (self._line(visit, "SVE-50031", school=""), "school_id is missing"),
            (self._line(visit, "SVE-50032", training_sf="TS-50032"), "not both"),
            (self._line(visit, ""), "visit_sf_id or training_sf_id"),
            (self._line(visit, "SVE-50033", day=""), "completed_date is missing"),
            (self._line(visit, "SVE-50034", day="31/31/2026"), "not a date"),
            (self._line(visit, "SVE-50035", day=future), "future"),
            (self._line(visit, "BAD ID"), "Salesforce ID"),
        ]
        batch = self._stage(*[line for line, _why in cases])
        self.assertEqual(set(self._statuses(batch)), {RowStatus.INVALID})
        for message, (_line, why) in zip(self._messages(batch), cases, strict=True):
            self.assertIn(why, message)

    def test_ids_edify_does_not_hold_are_invalid_and_listed_in_the_report(self):
        visit = self._visit()
        unknown = ",".join(
            ["ck-not-a-real-id", "REV-1", "SVE-50040", "", self.done_on.isoformat()]
        )
        batch = self._stage(unknown, self._line(visit, "SVE-50041", school="NOPE-9"))
        self.assertEqual(set(self._statuses(batch)), {RowStatus.INVALID})
        first, second = self._messages(batch)
        self.assertIn("ck-not-a-real-id", first)
        self.assertIn("NOPE-9", second)

        response = self.as_user(self.ia_user).get(
            f"/uploads/bulk-completion/batch/{batch.id}/report"
        )
        workbook = openpyxl.load_workbook(BytesIO(response.content))
        self.assertIn("Missing IDs", workbook.sheetnames)
        missing = list(workbook["Missing IDs"].iter_rows(values_only=True))[1:]
        self.assertIn(("planned_activity_id", "ck-not-a-real-id", "2"), missing)
        self.assertIn(("school_id", "NOPE-9", "3"), missing)

    def test_an_unknown_id_on_a_line_with_another_problem_is_still_listed(self):
        line = ",".join(["ck-gone", "REV-1", "SVE-50046", "", "not a date"])
        batch = self._stage(line)
        self.assertIn("not a date", self._messages(batch)[0])
        from apps.bulk_completion.report import missing_ids

        self.assertEqual(missing_ids(batch), [("planned_activity_id", "ck-gone", "2")])

    def test_a_school_id_that_is_not_the_visits_school_is_sent_for_review(self):
        visit = self._visit()
        batch = self._stage(self._line(visit, "SVE-50042", school="REV-2"))
        self.assertEqual(self._statuses(batch), [RowStatus.REVIEW])
        self.assertIn("REV-1", self._messages(batch)[0])

    def test_a_training_row_is_refused_by_the_visit_upload(self):
        visit = self._visit()
        batch = self._stage(self._line(visit, "", training_sf="TS-50043"))
        self.assertEqual(self._statuses(batch), [RowStatus.INVALID])
        self.assertIn("Trainings upload", self._messages(batch)[0])

    def test_a_training_named_in_the_visit_upload_is_refused(self):
        training = self._visit(activity_type="in_school_training")
        batch = self._stage(self._line(training, "SVE-50044"))
        self.assertEqual(self._statuses(batch), [RowStatus.INVALID])

    def test_an_id_held_by_another_visit_is_sent_for_review(self):
        from apps.activities.salesforce import reserve_salesforce_id

        holder = self._visit()
        reserve_salesforce_id(
            activity=holder,
            raw_value="SVE-50025",
            kind="visit",
            principal=self.james_user,
            entry_source="staff_self_entry",
        )
        other = self._visit()
        batch = self._stage(self._line(other, "SVE-50025"))
        self.assertEqual(self._statuses(batch), [RowStatus.REVIEW])

    def test_partial_success_completes_the_valid_lines_only(self):
        good = self._visit()
        bad = self._visit(planned_date=date.today() + timedelta(days=3))
        batch = self._stage(self._line(good, "SVE-50045"), self._line(bad, ""))
        apply_batch(batch, self.ia_user)
        good.refresh_from_db()
        bad.refresh_from_db()
        self.assertEqual(good.status, "ia_verified")
        self.assertEqual(bad.status, "scheduled")


class OnlyImpactAssessmentAndAdminRunIt(BulkFixture):
    def test_a_cceo_is_refused_every_page(self):
        client = self.as_user(self.james_user)
        for url in (
            "/uploads/bulk-completion/visit",
            "/uploads/bulk-completion/visit/template",
        ):
            self.assertNotEqual(client.get(url).status_code, 200, url)

    def test_impact_assessment_uploads_previews_and_confirms(self):
        visit = self._visit()
        client = self.as_user(self.ia_user)
        self.assertContains(client.get("/uploads"), "Bulk Upload — School Visits")
        page = client.get("/uploads/bulk-completion/visit")
        for heading in HEADINGS.split(","):
            self.assertContains(page, heading)
        response = client.post(
            "/uploads/bulk-completion/visit",
            {"file": visit_file(self._line(visit, "SVE-50050"))},
        )
        batch = BulkCompletionBatch.objects.get()
        self.assertRedirects(
            response,
            f"/uploads/bulk-completion/batch/{batch.id}",
            fetch_redirect_response=False,
        )
        self.assertContains(
            client.get(f"/uploads/bulk-completion/batch/{batch.id}"),
            "Confirm Bulk Completion (1)",
        )
        client.post(f"/uploads/bulk-completion/batch/{batch.id}/confirm")
        visit.refresh_from_db()
        self.assertEqual(visit.status, "ia_verified")

    def test_each_line_shows_its_activity_status_as_my_plan_shows_it(self):
        from django.utils import timezone

        from apps.my_plan.services import get_activity_status_label_and_class

        visit = self._visit()
        batch = self._stage(self._line(visit, "SVE-50070"))
        client = self.as_user(self.ia_user)
        url = f"/uploads/bulk-completion/batch/{batch.id}"
        before, _ = get_activity_status_label_and_class(visit, timezone.localdate())
        page = client.get(url)
        self.assertContains(page, ">Status</th>")
        self.assertNotContains(page, ">Reason</th>")
        self.assertContains(page, f">{before}</span>")

        apply_batch(batch, self.ia_user)
        visit.refresh_from_db()
        after, _ = get_activity_status_label_and_class(visit, timezone.localdate())
        self.assertNotEqual(before, after)
        self.assertContains(client.get(url), f">{after}</span>")

    def test_the_template_has_the_five_columns_prefilled_with_open_visits(self):
        visit = self._visit()
        response = self.as_user(self.ia_user).get(
            "/uploads/bulk-completion/visit/template"
        )
        sheet = openpyxl.load_workbook(BytesIO(response.content)).worksheets[0]
        rows = list(sheet.iter_rows(values_only=True))
        self.assertEqual(list(rows[0]), HEADINGS.split(","))
        self.assertIn((visit.id, "REV-1"), [tuple(row[:2]) for row in rows[1:]])

    def test_the_error_report_lists_the_lines_not_completed(self):
        visit = self._visit()
        batch = self._stage(self._line(visit, "SVE-50071", school="REV-2"))
        response = self.as_user(self.ia_user).get(
            f"/uploads/bulk-completion/batch/{batch.id}/report"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Needs review", _sheet_values(response))

    def test_another_countrys_officer_cannot_open_the_batch(self):
        batch = self._stage(self._line(self._visit(), "SVE-50060"))
        outsider, profile = _staff("bulk-ke@t.test", "Kip", EdifyRole.IMPACT_ASSESSMENT)
        profile.country = "Kenya"
        profile.save(update_fields=["country"])
        response = self.as_user(outsider).get(
            f"/uploads/bulk-completion/batch/{batch.id}"
        )
        self.assertEqual(response.status_code, 404)
