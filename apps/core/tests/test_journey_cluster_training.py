"""Journey 4 — Cluster training, walked end to end.

Journey 4 of the mandate's twenty-two: Eligible schools, Scheduling, Cost,
Attendance, Evidence, Verification, Unique-school and participant analytics.

Its last step names two counting rules that point in **opposite directions**,
which is what makes this journey worth walking rather than reading:

- A school that attends two cluster trainings has had **two** trainings. That
  figure is additive, and deduplicating it would understate the support a
  school received.
- The same two trainings reach **one** unique school. That figure dedupes, and
  summing it would overstate the programme's reach — which is exactly the
  TGT-03 defect this audit already fixed in the milestone engine.

Getting either backwards is a defect, and they live beside each other.

There is a third rule the model states in as many words. The planned
composition of the room (`teachers_per_school` and its siblings) is kept
deliberately apart from what happened (`teachers_attended`), because "storing
a plan in an attendance field is how a planned figure gets read as a verified
one". The completion path says the same: "Actuals — entered by the person who
delivered, never copied from the planned fields (§9.2)."

So this plans a training for a three-school cluster, delivers it to only two
of them with attendance figures that differ from the plan, and then asks each
analytic what it sees.
"""

from __future__ import annotations

import datetime

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.activities.models import Activity
from apps.clusters.models import Cluster
from apps.geography.models import District, Region
from apps.schools.models import School

PLANNED_TEACHERS_PER_SCHOOL = 3
ACTUAL_TEACHERS = 5
ACTUAL_LEADERS = 2


def _person(uid, email, name, role):
    user = User.objects.create(
        id=uid, email=email, name=name, roles=[role], active_role=role, is_active=True
    )
    profile = StaffProfile.objects.create(
        user=user, staff_number=uid.upper(), country="Uganda", title=role
    )
    return user, profile


class ClusterTrainingJourneyTest(TestCase):
    """Plan → deliver to some of the cluster → count two ways at once."""

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="CT Region")
        cls.district = District.objects.create(name="CT District", region=cls.region)
        cls.cluster = Cluster.objects.create(
            name="CT Cluster", region=cls.region, district=cls.district
        )
        cls.schools = [
            School.objects.create(
                school_id=f"CT-SCH-{n}",
                name=f"CT School {n}",
                region=cls.region,
                district=cls.district,
                cluster_id=cls.cluster.id,
                school_type="client",
            )
            for n in (1, 2, 3)
        ]
        cls.cceo, cls.cceo_sp = _person(
            "ct-cceo", "ct-cceo@edify.org", "CT CCEO", "CCEO"
        )
        for school in cls.schools:
            StaffSchoolAssignment.objects.create(staff=cls.cceo_sp, school_id=school.id)

    def _planned_training(self, *, ref: str):
        """A cluster training priced for the whole cluster."""
        return Activity.objects.create(
            activity_type="cluster_training",
            delivery_type="staff",
            status="scheduled",
            fy="2026",
            cluster=self.cluster,
            responsible_staff_id=self.cceo_sp.id,
            scheduled_date=timezone.now() + datetime.timedelta(days=7),
            planned_date=(timezone.now() + datetime.timedelta(days=7)).date(),
            salesforce_activity_id=ref,
            # The PLAN: three teachers from each of the cluster's schools.
            teachers_per_school=PLANNED_TEACHERS_PER_SCHOOL,
            participants_per_school=PLANNED_TEACHERS_PER_SCHOOL,
            cluster_school_count_snapshot=len(self.schools),
            schools_invited=len(self.schools),
        )

    def _deliver(self, activity, *, attending):
        """Complete it through the real service with what ACTUALLY happened."""
        from apps.activities.services import complete, start_completion
        from apps.evidence.models import EvidenceRecord

        start_completion(activity.id, {}, self.cceo)
        # ── 5. Evidence — the platform refuses completion without it ──────
        EvidenceRecord.objects.create(
            activity_id=activity.id,
            kind="cluster_training_report",
            uri=f"journey/{activity.salesforce_activity_id}.pdf",
            original_name="attendance-register.pdf",
            file_size=2048,
            uploaded_by=self.cceo.id,
        )
        complete(
            activity.id,
            {
                "salesforceId": activity.salesforce_activity_id,
                "teachersAttended": ACTUAL_TEACHERS,
                "leadersAttended": ACTUAL_LEADERS,
                "attendedSchoolIds": [s.id for s in attending],
            },
            self.cceo,
        )
        activity.refresh_from_db()
        return activity

    def test_attendance_is_what_happened_not_what_was_planned(self):
        # ── 1-3. Eligible schools, scheduling, cost ───────────────────────
        activity = self._planned_training(ref="TS-CT-0001")
        self.assertEqual(
            activity.teachers_per_school,
            PLANNED_TEACHERS_PER_SCHOOL,
            "the fixture recorded no plan, so 'actuals are not the plan' "
            "would hold over nothing",
        )

        # ── 4. Attendance — two of the three schools came ─────────────────
        attending = self.schools[:2]
        activity = self._deliver(activity, attending=attending)

        self.assertEqual(
            sorted(activity.attended_school_ids),
            sorted(s.id for s in attending),
            "the schools that attended are not the ones recorded",
        )
        self.assertNotIn(
            self.schools[2].id,
            activity.attended_school_ids,
            "a school that did not attend was credited with the training",
        )

        # The rule the model states in as many words: actuals are entered,
        # never copied from the plan.
        self.assertEqual(activity.teachers_attended, ACTUAL_TEACHERS)
        self.assertEqual(activity.leaders_attended, ACTUAL_LEADERS)
        self.assertNotEqual(
            activity.teachers_attended,
            activity.teachers_per_school,
            "the attendance figure equals the planned figure, so a planned "
            "number is being read as a verified one",
        )
        # The plan itself survives — it is what the budget was priced against.
        self.assertEqual(
            activity.teachers_per_school,
            PLANNED_TEACHERS_PER_SCHOOL,
            "recording attendance overwrote the plan the budget was priced on",
        )

    def test_attendance_cannot_credit_a_school_outside_the_cluster(self):
        """The array has no foreign key, so the service is the only guard."""
        outsider = School.objects.create(
            school_id="CT-OUTSIDER",
            name="CT Outsider",
            region=self.region,
            district=self.district,
            school_type="client",
        )
        activity = self._planned_training(ref="TS-CT-0002")
        activity = self._deliver(activity, attending=[self.schools[0], outsider])
        self.assertEqual(
            activity.attended_school_ids,
            [self.schools[0].id],
            "a school outside the cluster was credited with its training",
        )

    def test_two_trainings_count_twice_per_school_and_once_for_reach(self):
        """The two opposite rules, asserted together.

        A test that checked only one of them would pass just as happily
        against a system that applied that rule to both.
        """
        first = self._planned_training(ref="TS-CT-0003")
        self._deliver(first, attending=self.schools[:2])
        second = self._planned_training(ref="TS-CT-0004")
        self._deliver(second, attending=self.schools[:2])

        delivered = Activity.objects.filter(
            cluster=self.cluster, activity_type="cluster_training"
        ).exclude(attended_school_ids=[])

        # Additive: the school received two trainings.
        per_school: dict[str, int] = {}
        for row in delivered.values_list("attended_school_ids", flat=True):
            for school_id in row or []:
                per_school[school_id] = per_school.get(school_id, 0) + 1
        self.assertEqual(
            per_school[self.schools[0].id],
            2,
            "a school that attended two trainings shows fewer than two — "
            "deduplicating this figure understates the support it received",
        )

        # Deduped: the two trainings reached two distinct schools, not four.
        reached = {
            school_id
            for row in delivered.values_list("attended_school_ids", flat=True)
            for school_id in (row or [])
        }
        self.assertEqual(
            len(reached),
            2,
            "two trainings at the same two schools were counted as four "
            "schools reached — this is the TGT-03 shape",
        )
        self.assertNotIn(
            self.schools[2].id,
            reached,
            "a school that attended neither training is counted as reached",
        )

        # Participants sum across sessions: two rooms of five teachers is ten
        # attendances, and collapsing that would lose a session's delivery.
        self.assertEqual(
            sum(a.teachers_attended or 0 for a in delivered),
            ACTUAL_TEACHERS * 2,
            "participant attendances were deduplicated across sessions",
        )
