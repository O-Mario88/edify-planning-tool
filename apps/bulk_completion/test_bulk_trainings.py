"""Bulk Upload — Trainings (owner, 2026-11-02).

Pinned here:

  1. A cluster or group training completes once, as one event, and every
     school the upload names as attending is on its register — whether the
     schools are listed on one line or one line per school.
  2. A school named twice for one training is on its register once, and a
     line that adds nothing is a duplicate.
  3. Attendance is required, and so is the list of schools for a cluster
     training; without them the line is sent for review.
  4. An in-school training completes at its own school.
"""

from __future__ import annotations

from django.core.files.uploadedfile import SimpleUploadedFile

from apps.activities.models import ClusterActivityAttendance
from apps.bulk_completion.apply import apply_batch
from apps.bulk_completion.models import RowStatus
from apps.bulk_completion.staging import stage_upload
from apps.bulk_completion.test_bulk_visits import BulkFixture
from apps.schools.models import School

HEADINGS = (
    "Edify Activity ID,School ID,Training ID,Completion Date,Teachers Attended,"
    "School Leaders Attended,Participating School IDs"
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

    def _line(self, training, sf_id, *, teachers="8", leaders="2", schools=""):
        return ",".join(
            [
                training.id,
                "",
                sf_id,
                self.done_on.isoformat(),
                teachers,
                leaders,
                f'"{schools}"',
            ]
        )

    def _stage(self, *lines):
        body = "\n".join([HEADINGS, *lines]) + "\n"
        upload = SimpleUploadedFile("trainings.csv", body.encode(), "text/csv")
        return stage_upload(upload, "training", self.ia_user)

    def _register(self, training):
        return set(
            ClusterActivityAttendance.objects.filter(
                activity=training, attended=True
            ).values_list("school__school_id", flat=True)
        )


class AClusterTrainingCompletesWithItsRegister(TrainingFixture):
    def test_schools_listed_on_one_line_are_all_on_the_register(self):
        training = self._training()
        batch = self._stage(self._line(training, "TS-90001", schools="CLU-A, CLU-B"))
        self.assertEqual(self._statuses(batch), [RowStatus.READY])
        apply_batch(batch, self.ia_user)
        training.refresh_from_db()
        self.assertEqual(training.status, "ia_verified")
        self.assertEqual(training.salesforce_activity_id, "TS-90001")
        self.assertEqual(training.teachers_attended, 8)
        self.assertEqual(self._register(training), {"CLU-A", "CLU-B"})

    def test_one_line_per_school_joins_into_one_completion(self):
        training = self._training()
        batch = self._stage(
            self._line(
                training, "TS-90002", teachers="5", leaders="1", schools="CLU-A"
            ),
            self._line(
                training, "TS-90002", teachers="4", leaders="1", schools="CLU-B"
            ),
        )
        self.assertEqual(self._statuses(batch), [RowStatus.READY, RowStatus.MERGED])
        apply_batch(batch, self.ia_user)
        training.refresh_from_db()
        self.assertEqual(
            (training.teachers_attended, training.leaders_attended), (9, 2)
        )
        self.assertEqual(self._register(training), {"CLU-A", "CLU-B"})
        self.assertEqual(
            self._statuses(batch), [RowStatus.COMPLETED, RowStatus.COMPLETED]
        )

    def test_a_school_named_twice_is_on_the_register_once(self):
        training = self._training()
        batch = self._stage(
            self._line(training, "TS-90003", schools="CLU-A, CLU-A"),
            self._line(training, "TS-90003", schools="CLU-A"),
        )
        self.assertEqual(self._statuses(batch), [RowStatus.READY, RowStatus.DUPLICATE])
        apply_batch(batch, self.ia_user)
        self.assertEqual(
            ClusterActivityAttendance.objects.filter(
                activity=training, school=self.member_a
            ).count(),
            1,
        )


class TrainingLinesNeedTheirAttendance(TrainingFixture):
    def test_a_cluster_training_without_its_schools_is_sent_for_review(self):
        training = self._training()
        batch = self._stage(self._line(training, "TS-90010"))
        row = batch.rows.get()
        self.assertEqual(row.status, RowStatus.REVIEW)
        self.assertIn("Participating School IDs", row.message)

    def test_a_training_without_attendance_is_sent_for_review(self):
        training = self._training()
        batch = self._stage(
            self._line(training, "TS-90011", teachers="", leaders="", schools="CLU-A")
        )
        self.assertEqual(self._statuses(batch), [RowStatus.REVIEW])

    def test_an_unknown_participating_school_is_sent_for_review(self):
        training = self._training()
        batch = self._stage(self._line(training, "TS-90012", schools="CLU-A, NOPE"))
        self.assertIn("NOPE", batch.rows.get().message)

    def test_a_visit_id_is_refused_for_a_training(self):
        training = self._training()
        batch = self._stage(self._line(training, "SVE-90013", schools="CLU-A"))
        self.assertEqual(self._statuses(batch), [RowStatus.INVALID])


class AnInSchoolTrainingCompletesAtItsSchool(TrainingFixture):
    def test_it_completes_with_its_attendance(self):
        training = self._visit(activity_type="in_school_training")
        batch = self._stage(self._line(training, "TS-90020"))
        self.assertEqual(self._statuses(batch), [RowStatus.READY])
        apply_batch(batch, self.ia_user)
        training.refresh_from_db()
        self.assertEqual(training.status, "ia_verified")
        self.assertEqual(training.leaders_attended, 2)
