"""Bulk Upload — Trainings (owner, 2026-11-02; ID-based, 2026-11-03).

Pinned here:

  1. The training file has the visit file's five columns plus
     teachers_trained and school_leaders_trained (owner, 2026-11-03: "count
     columns should be required as well"). One line per participating school.
  2. Lines with the same planned_activity_id and training_sf_id are one
     training: it completes once, every school named is on its register, and
     the counts are the schools' counts added up.
  3. A school named twice is on the register once; uploading the file again
     completes nothing twice and adds no school twice.
  4. A visit row, a missing or bad count, two Salesforce IDs for one training,
     and a school not in Edify are reported, never completed.
  5. An in-school training completes at its own school.
"""

from __future__ import annotations

from django.core.files.uploadedfile import SimpleUploadedFile

from apps.activities.models import ClusterActivityAttendance
from apps.bulk_completion.apply import apply_batch
from apps.bulk_completion.models import RowStatus
from apps.bulk_completion.staging import stage_upload
from apps.bulk_completion.test_bulk_visits import BulkFixture
from apps.core.exceptions import BadRequest
from apps.schools.models import School

HEADINGS = (
    "planned_activity_id,school_id,visit_sf_id,training_sf_id,completed_date,"
    "teachers_trained,school_leaders_trained"
)


class TrainingFixture(BulkFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.member_a = School.objects.create(
            school_id="CLU-A",
            name="Cluster A Primary",
            region=cls.region,
            district=cls.district,
            cluster_id=cls.cluster.id,
        )
        cls.member_b = School.objects.create(
            school_id="CLU-B",
            name="Cluster B Primary",
            region=cls.region,
            district=cls.district,
            cluster_id=cls.cluster.id,
        )

    def _training(self, **extra):
        values = {"activity_type": "cluster_training", "school": None}
        values.update(extra)
        return self._visit(cluster=extra.pop("cluster", self.cluster), **values)

    def _line(self, training, sf_id, school, *, teachers="4", leaders="1", visit_sf=""):
        cells = [training.id, school, visit_sf, sf_id, self.done_on.isoformat()]
        return ",".join([*cells, teachers, leaders])

    def _stage(self, *lines, headings=HEADINGS):
        body = "\n".join([headings, *lines]) + "\n"
        upload = SimpleUploadedFile("trainings.csv", body.encode(), "text/csv")
        return stage_upload(upload, "training", self.ia_user)

    def _register(self, training):
        return set(
            ClusterActivityAttendance.objects.filter(
                activity=training, attended=True
            ).values_list("school__school_id", flat=True)
        )


class AMultiSchoolTrainingCompletesOnce(TrainingFixture):
    def test_one_line_per_school_links_every_school_to_one_training(self):
        training = self._training()
        batch = self._stage(
            self._line(training, "TS-90002", "CLU-A", teachers="5", leaders="1"),
            self._line(training, "TS-90002", "CLU-B", teachers="4", leaders="1"),
        )
        self.assertEqual(self._statuses(batch), [RowStatus.READY, RowStatus.MERGED])

        apply_batch(batch, self.ia_user)

        training.refresh_from_db()
        self.assertEqual(training.status, "ia_verified")
        self.assertEqual(training.salesforce_activity_id, "TS-90002")
        self.assertEqual(training.actual_delivery_date, self.done_on)
        self.assertEqual(
            (training.teachers_attended, training.leaders_attended), (9, 2)
        )
        self.assertEqual(self._register(training), {"CLU-A", "CLU-B"})
        self.assertEqual(
            self._statuses(batch), [RowStatus.COMPLETED, RowStatus.COMPLETED]
        )

    def test_uploading_it_again_completes_nothing_and_links_no_school_twice(self):
        training = self._training()
        lines = (
            self._line(training, "TS-90003", "CLU-A"),
            self._line(training, "TS-90003", "CLU-B"),
        )
        apply_batch(self._stage(*lines), self.ia_user)
        training.refresh_from_db()
        counts = (training.teachers_attended, training.leaders_attended)

        again = self._stage(*lines)
        self.assertEqual(
            self._statuses(again), [RowStatus.ALREADY_COMPLETED, RowStatus.DUPLICATE]
        )
        apply_batch(again, self.ia_user)

        training.refresh_from_db()
        self.assertEqual(
            (training.teachers_attended, training.leaders_attended), counts
        )
        self.assertEqual(
            ClusterActivityAttendance.objects.filter(
                activity=training, school__in=(self.member_a, self.member_b)
            ).count(),
            2,
        )

    def test_a_school_named_twice_is_on_the_register_once(self):
        training = self._training()
        batch = self._stage(
            self._line(training, "TS-90004", "CLU-A"),
            self._line(training, "TS-90004", "CLU-A"),
        )
        self.assertEqual(self._statuses(batch), [RowStatus.READY, RowStatus.DUPLICATE])
        apply_batch(batch, self.ia_user)
        self.assertEqual(
            ClusterActivityAttendance.objects.filter(
                activity=training, school=self.member_a
            ).count(),
            1,
        )

    def test_two_training_ids_for_one_training_are_sent_for_review(self):
        training = self._training()
        batch = self._stage(
            self._line(training, "TS-90005", "CLU-A"),
            self._line(training, "TS-90006", "CLU-B"),
        )
        self.assertEqual(self._statuses(batch), [RowStatus.READY, RowStatus.REVIEW])


class TrainingLinesNeedTheirCounts(TrainingFixture):
    def test_a_file_without_the_count_columns_is_refused(self):
        training = self._training()
        line = ",".join(
            [training.id, "CLU-A", "", "TS-90010", self.done_on.isoformat()]
        )
        with self.assertRaises(BadRequest) as refused:
            self._stage(
                line,
                headings=(
                    "planned_activity_id,school_id,visit_sf_id,training_sf_id,"
                    "completed_date"
                ),
            )
        detail = str(refused.exception.detail)
        self.assertIn("teachers_trained", detail)
        self.assertIn("school_leaders_trained", detail)

    def test_a_blank_or_bad_count_is_invalid(self):
        training = self._training()
        cases = [
            (self._line(training, "TS-90011", "CLU-A", teachers=""), "teachers"),
            (self._line(training, "TS-90011", "CLU-A", leaders="x"), "whole number"),
            (self._line(training, "TS-90011", "CLU-A", teachers="-2"), "negative"),
        ]
        batch = self._stage(*[line for line, _why in cases])
        self.assertEqual(set(self._statuses(batch)), {RowStatus.INVALID})
        for message, (_line, why) in zip(self._messages(batch), cases, strict=True):
            self.assertIn(why, message)

    def test_a_training_nobody_attended_is_sent_for_review(self):
        training = self._training()
        batch = self._stage(
            self._line(training, "TS-90012", "CLU-A", teachers="0", leaders="0")
        )
        self.assertEqual(self._statuses(batch), [RowStatus.REVIEW])


class MalformedTrainingLinesAreReported(TrainingFixture):
    def test_a_visit_row_is_refused_by_the_training_upload(self):
        training = self._training()
        batch = self._stage(self._line(training, "", "CLU-A", visit_sf="SVE-90013"))
        self.assertEqual(self._statuses(batch), [RowStatus.INVALID])
        self.assertIn("School Visits upload", self._messages(batch)[0])

    def test_a_visit_id_typed_as_the_training_id_is_refused(self):
        training = self._training()
        batch = self._stage(self._line(training, "SVE-90014", "CLU-A"))
        self.assertEqual(self._statuses(batch), [RowStatus.INVALID])

    def test_an_unknown_participating_school_is_invalid(self):
        training = self._training()
        batch = self._stage(
            self._line(training, "TS-90015", "CLU-A"),
            self._line(training, "TS-90015", "NOPE"),
        )
        self.assertEqual(self._statuses(batch)[1], RowStatus.INVALID)
        self.assertIn("NOPE", self._messages(batch)[1])

    def test_a_visit_named_in_the_training_upload_is_refused(self):
        visit = self._visit()
        batch = self._stage(self._line(visit, "TS-90016", "REV-1"))
        self.assertEqual(self._statuses(batch), [RowStatus.INVALID])


class AnInSchoolTrainingCompletesAtItsSchool(TrainingFixture):
    def test_it_completes_with_its_counts(self):
        training = self._visit(activity_type="in_school_training")
        batch = self._stage(
            self._line(training, "TS-90020", "REV-1", teachers="6", leaders="2")
        )
        self.assertEqual(self._statuses(batch), [RowStatus.READY])
        apply_batch(batch, self.ia_user)
        training.refresh_from_db()
        self.assertEqual(training.status, "ia_verified")
        self.assertEqual(
            (training.teachers_attended, training.leaders_attended), (6, 2)
        )

    def test_another_school_on_an_in_school_training_is_sent_for_review(self):
        training = self._visit(activity_type="in_school_training")
        batch = self._stage(self._line(training, "TS-90021", "REV-2"))
        self.assertEqual(self._statuses(batch), [RowStatus.REVIEW])
