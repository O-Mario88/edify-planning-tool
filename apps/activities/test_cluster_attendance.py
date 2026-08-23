"""A cluster session has to land on the schools that sat in the room.

The session belongs to a cluster, so its `school` FK is null. Every count that
asks "has this school been trained?" by filtering `school_id` misses it — which
is how the same school reads as trained on its profile and as No Training on
the Priority Schools table.
"""

from __future__ import annotations

from datetime import date

from django.test import TestCase
from django.utils import timezone

from apps.activities import cluster_attendance as ca
from apps.activities.models import Activity, ClusterActivityAttendance
from apps.clusters.models import Cluster
from apps.core.exceptions import BadRequest
from apps.geography.models import District, Region
from apps.schools.models import School

FY = "2026"


class ClusterAttendanceTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Central")
        self.district = District.objects.create(
            name="Dist", region=self.region, district_type="primary"
        )
        self.cluster = Cluster.objects.create(
            name="Cluster One", district=self.district, region=self.region
        )
        self.other_cluster = Cluster.objects.create(
            name="Cluster Two", district=self.district, region=self.region
        )

        self.a = self._school("A", self.cluster)
        self.b = self._school("B", self.cluster)
        self.c = self._school("C", self.cluster)
        self.guest = self._school("Guest", self.other_cluster)

        self.training = self._activity("cluster_training")

    def _school(self, sid, cluster):
        return School.objects.create(
            school_id=f"S-{sid}",
            name=f"School {sid}",
            region=self.region,
            district=self.district,
            cluster_id=cluster.id,
            enrollment=100,
        )

    def _activity(self, atype, status="ia_verified"):
        return Activity.objects.create(
            cluster=self.cluster,
            activity_type=atype,
            delivery_type="staff",
            status=status,
            fy=FY,
            quarter="Q3",
            planned_date=date(2026, 4, 10),
            scheduled_date=timezone.make_aware(timezone.datetime(2026, 4, 10, 9, 0)),
            teachers_per_school=3,
            leaders_per_school=1,
            other_per_school=0,
        )


class InvitationTests(ClusterAttendanceTest):
    def test_inviting_creates_a_row_per_school_with_the_shared_composition(self):
        ca.set_invited_schools(self.training, [self.a.id, self.b.id])

        rows = {r.school_id: r for r in self.training.school_attendance.all()}
        self.assertEqual(set(rows), {self.a.id, self.b.id})
        self.assertTrue(all(r.invited and not r.attended for r in rows.values()))
        self.assertEqual(rows[self.a.id].teachers, 3)
        self.assertEqual(rows[self.a.id].leaders, 1)

    def test_only_cluster_members_can_be_invited(self):
        with self.assertRaises(BadRequest):
            ca.set_invited_schools(self.training, [self.a.id, self.guest.id])

    def test_the_expected_head_count_is_derived_from_the_ticks(self):
        ca.set_invited_schools(self.training, [self.a.id, self.b.id, self.c.id])
        # 3 schools x (3 teachers + 1 leader)
        self.assertEqual(ca.expected_participants(self.training), 12)

        ca.set_invited_schools(self.training, [self.a.id])
        self.assertEqual(ca.expected_participants(self.training), 4)

    def test_a_school_is_credited_once_however_often_it_is_sent(self):
        ca.set_invited_schools(self.training, [self.a.id, self.a.id, self.a.id])
        self.assertEqual(self.training.school_attendance.count(), 1)


class AttendanceTests(ClusterAttendanceTest):
    def test_attendance_is_confirmed_not_assumed_from_the_invitation(self):
        ca.set_invited_schools(self.training, [self.a.id, self.b.id])

        # Invited is not attended: nothing is credited until someone confirms.
        self.assertEqual(ca.trained_school_ids([self.a.id, self.b.id], fy=FY), set())

        ca.confirm_attendance(self.training, [self.a.id])

        self.assertEqual(
            ca.trained_school_ids([self.a.id, self.b.id], fy=FY), {self.a.id}
        )

    def test_a_school_that_was_never_invited_cannot_be_ticked(self):
        ca.set_invited_schools(self.training, [self.a.id])
        with self.assertRaises(BadRequest):
            ca.confirm_attendance(self.training, [self.a.id, self.c.id])

    def test_unticking_keeps_the_invitation_as_a_record(self):
        ca.set_invited_schools(self.training, [self.a.id])
        ca.confirm_attendance(self.training, [self.a.id])
        ca.confirm_attendance(self.training, [])

        row = self.training.school_attendance.get(school_id=self.a.id)
        self.assertTrue(row.invited)
        self.assertFalse(row.attended)


class GuestSchoolTests(ClusterAttendanceTest):
    def test_a_school_from_another_cluster_is_recorded_with_its_own_numbers(self):
        row = ca.add_guest_school(
            self.training, self.guest.id, teachers=7, leaders=2, other=1
        )

        self.assertTrue(row.is_guest)
        self.assertTrue(row.attended)
        self.assertFalse(row.invited)
        self.assertEqual((row.teachers, row.leaders, row.other), (7, 2, 1))

    def test_a_guest_is_credited_the_training_like_any_other_school(self):
        ca.add_guest_school(self.training, self.guest.id, teachers=7)

        self.assertEqual(ca.trained_school_ids([self.guest.id], fy=FY), {self.guest.id})

    def test_a_guest_was_never_budgeted_for(self):
        ca.set_invited_schools(self.training, [self.a.id])
        ca.add_guest_school(self.training, self.guest.id, teachers=7)

        # 1 invited school x 4, and the guest who turned up adds nothing to
        # the figure the session was priced with.
        self.assertEqual(ca.expected_participants(self.training), 4)

    def test_a_member_school_is_invited_rather_than_added_as_a_guest(self):
        with self.assertRaises(BadRequest):
            ca.add_guest_school(self.training, self.b.id)


class TrainedElsewhereTests(ClusterAttendanceTest):
    def test_a_meeting_attaches_to_the_school_without_counting_as_training(self):
        meeting = self._activity("cluster_meeting")
        ca.set_invited_schools(meeting, [self.a.id])
        ca.confirm_attendance(meeting, [self.a.id])

        self.assertTrue(meeting.school_attendance.filter(school_id=self.a.id).exists())
        self.assertEqual(ca.trained_school_ids([self.a.id], fy=FY), set())

    def test_unverified_cluster_work_credits_nobody(self):
        # "completed" is written only by the demo seeder, so crediting it
        # would credit seed rows. The school arm deliberately keeps the wider
        # vocabulary it already had — see the note on the constants.
        draft = self._activity("cluster_training", status="completed")
        ca.set_invited_schools(draft, [self.a.id])
        ca.confirm_attendance(draft, [self.a.id])

        self.assertEqual(ca.trained_school_ids([self.a.id], fy=FY), set())

    def test_in_school_training_still_counts_through_its_own_school_link(self):
        Activity.objects.create(
            school=self.c,
            activity_type="in_school_training",
            delivery_type="staff",
            status="ia_verified",
            fy=FY,
            quarter="Q3",
            planned_date=date(2026, 4, 10),
        )
        self.assertEqual(ca.trained_school_ids([self.c.id], fy=FY), {self.c.id})

    def test_both_routes_answer_one_question(self):
        ca.set_invited_schools(self.training, [self.a.id])
        ca.confirm_attendance(self.training, [self.a.id])
        Activity.objects.create(
            school=self.b,
            activity_type="training",
            delivery_type="staff",
            status="closed",
            fy=FY,
            quarter="Q3",
            planned_date=date(2026, 4, 10),
        )

        trained = ca.trained_school_ids([self.a.id, self.b.id, self.c.id], fy=FY)
        self.assertEqual(trained, {self.a.id, self.b.id})
