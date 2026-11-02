"""Bulk Upload — School Visits (owner, 2026-11-02).

Pinned here:

  1. A line names its visit by Edify Activity ID, by the Salesforce ID it
     already holds, or by School ID + type + date when that picks out one
     visit; two visits to one school are never duplicates of each other.
  2. Confirming completes each ready line through the visit's own workflow:
     its School Visit ID and completion date are recorded and, being from the
     Salesforce export, it is approved at once — no Programme Lead verifies
     it. Work entered from the drawer still waits for its lead.
  3. Completed visits are skipped, never recounted; a line repeated in the
     file is processed once; a file uploaded again changes no total.
  4. Invalid, missing or ambiguous lines are reported, not guessed, and the
     rest of the file still completes.
  5. Only Impact Assessment and Admin run it.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile

from apps.activities.models import Activity
from apps.bulk_completion.apply import apply_batch
from apps.bulk_completion.models import BatchStatus, BulkCompletionBatch, RowStatus
from apps.bulk_completion.staging import stage_upload
from apps.core.rbac import EdifyRole
from apps.notifications.models import Notification
from apps.pl_review.test_completion_reviews import ReviewFixture, _staff

HEADINGS = "Edify Activity ID,School ID,Scheduled Date,School Visit ID,Completion Date"


def visit_file(*lines: str, name: str = "visits.csv") -> SimpleUploadedFile:
    body = "\n".join([HEADINGS, *lines]) + "\n"
    return SimpleUploadedFile(name, body.encode("utf-8"), content_type="text/csv")


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

    def _line(self, visit, sf_id, *, school="", day=None, scheduled=""):
        return ",".join(
            [
                visit.id if visit else "",
                school,
                scheduled,
                sf_id,
                (day or self.done_on).isoformat(),
            ]
        )

    def _stage(self, *lines, user=None, name="visits.csv"):
        return stage_upload(
            visit_file(*lines, name=name), "visit", user or self.ia_user
        )

    def _statuses(self, batch):
        return list(batch.rows.order_by("row_number").values_list("status", flat=True))


class ConfirmingCompletesAndApprovesUploadedVisits(BulkFixture):
    def test_a_ready_line_completes_its_visit_without_pl_verification(self):
        visit = self._visit()
        batch = self._stage(self._line(visit, "SVE-50001"))
        self.assertEqual(self._statuses(batch), [RowStatus.READY])
        visit.refresh_from_db()
        self.assertEqual(visit.status, "scheduled", "nothing changes before confirm")

        apply_batch(batch, self.ia_user)

        visit.refresh_from_db()
        self.assertEqual(visit.salesforce_activity_id, "SVE-50001")
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


class LinesAreMatchedNeverGuessed(BulkFixture):
    def test_the_salesforce_id_already_saved_finds_its_visit(self):
        visit = self._visit()
        from apps.activities.salesforce import reserve_salesforce_id

        reserve_salesforce_id(
            activity=visit,
            raw_value="SVE-50020",
            kind="visit",
            principal=self.james_user,
            entry_source="staff_self_entry",
        )
        batch = self._stage(self._line(None, "SVE-50020", school="REV-1"))
        row = batch.rows.get()
        self.assertEqual((row.status, row.activity_id), (RowStatus.READY, visit.id))

    def test_one_open_visit_at_the_school_is_matched_by_school_id(self):
        visit = self._visit()
        batch = self._stage(self._line(None, "SVE-50021", school="REV-1"))
        row = batch.rows.get()
        self.assertEqual((row.status, row.activity_id), (RowStatus.READY, visit.id))

    def test_two_visits_to_one_school_are_never_taken_for_each_other(self):
        first = self._visit(planned_date=date.today())
        second = self._visit(planned_date=date.today() + timedelta(days=7))
        ambiguous = self._stage(self._line(None, "SVE-50022", school="REV-1"))
        self.assertEqual(self._statuses(ambiguous), [RowStatus.REVIEW])
        self.assertIn("2 open visits", ambiguous.rows.get().message)

        dated = self._stage(
            self._line(
                None,
                "SVE-50023",
                school="REV-1",
                scheduled=second.planned_date.isoformat(),
            ),
            self._line(
                None,
                "SVE-50024",
                school="REV-1",
                scheduled=first.planned_date.isoformat(),
            ),
        )
        self.assertEqual(
            list(
                dated.rows.order_by("row_number").values_list("status", "activity_id")
            ),
            [(RowStatus.READY, second.id), (RowStatus.READY, first.id)],
        )

    def test_a_missing_visit_id_is_sent_for_review(self):
        visit = self._visit()
        batch = self._stage(self._line(visit, ""))
        row = batch.rows.get()
        self.assertEqual(row.status, RowStatus.REVIEW)
        self.assertIn("School Visit ID is missing", row.message)

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

    def test_unusable_lines_are_invalid(self):
        visit = self._visit()
        future = date.today() + timedelta(days=2)
        batch = self._stage(
            self._line(None, "SVE-50030", school="NOPE-9"),
            self._line(visit, "SVE-50031", day=future),
            self._line(visit, "BAD ID"),
            "ck-not-a-real-id,,,SVE-50032," + self.done_on.isoformat(),
        )
        self.assertEqual(set(self._statuses(batch)), {RowStatus.INVALID})

    def test_a_training_named_in_the_visit_upload_is_refused(self):
        training = self._visit(activity_type="cluster_training")
        batch = self._stage(self._line(training, "SVE-50033"))
        self.assertEqual(self._statuses(batch), [RowStatus.INVALID])

    def test_partial_success_completes_the_valid_lines_only(self):
        good = self._visit()
        bad = self._visit(planned_date=date.today() + timedelta(days=3))
        batch = self._stage(self._line(good, "SVE-50040"), self._line(bad, ""))
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
        template = client.get("/uploads/bulk-completion/visit/template")
        self.assertEqual(template.status_code, 200)
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

    def test_the_template_lists_open_visits_with_their_activity_ids(self):
        visit = self._visit()
        response = self.as_user(self.ia_user).get(
            "/uploads/bulk-completion/visit/template"
        )
        from io import BytesIO

        import openpyxl

        sheet = openpyxl.load_workbook(BytesIO(response.content)).worksheets[0]
        values = [cell for row in sheet.iter_rows(values_only=True) for cell in row]
        self.assertIn(visit.id, values)
        self.assertIn("School Visit ID", values)

    def test_the_error_report_lists_the_lines_not_completed(self):
        visit = self._visit()
        batch = self._stage(self._line(visit, ""))
        response = self.as_user(self.ia_user).get(
            f"/uploads/bulk-completion/batch/{batch.id}/report"
        )
        self.assertEqual(response.status_code, 200)
        from io import BytesIO

        import openpyxl

        sheet = openpyxl.load_workbook(BytesIO(response.content)).active
        values = [cell for row in sheet.iter_rows(values_only=True) for cell in row]
        self.assertIn("Needs review", values)

    def test_another_countrys_officer_cannot_open_the_batch(self):
        batch = self._stage(self._line(self._visit(), "SVE-50060"))
        outsider, profile = _staff("bulk-ke@t.test", "Kip", EdifyRole.IMPACT_ASSESSMENT)
        profile.country = "Kenya"
        profile.save(update_fields=["country"])
        response = self.as_user(outsider).get(
            f"/uploads/bulk-completion/batch/{batch.id}"
        )
        self.assertEqual(response.status_code, 404)
