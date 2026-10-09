"""Training ceilings, the training summary and the training's own SSA link.

Owner, 2026-10-06. A training is a Training Catalogue entry linked to one SSA
intervention; a Programme Lead sets how many schools an officer may schedule
for it in a fiscal year; a training is delivered as a Group Training (the
schools invited to a cluster session) or as an In-School Training (one
school); and what is scheduled is counted from the plans themselves, so the
drawers, the summary and the save all read one figure.

What is pinned here: the count and its two deliveries, the ceiling held on
the server (new plans, edits, moves between years and officers), who sees and
sets what, Balance and Excess, the schools behind each figure, the three
cluster meeting types, and that the training's intervention is the catalogue's
whatever a request carries.
"""

from __future__ import annotations

import datetime
import json

from django.test import Client

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.activities import editing
from apps.activities.models import Activity, ClusterActivityAttendance
from apps.activity_catalogue.training_intervention import intervention_for
from apps.audit.models import AuditLog
from apps.clusters.models import Cluster
from apps.core.enums import MeetingKind, SsaIntervention
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.fy import get_operational_fy
from apps.planning import training_ceilings
from apps.planning.models import TrainingCeiling, TrainingCountryCeiling
from apps.planning.services import (
    schedule_cluster_activity,
    schedule_in_school_training_pair,
)
from apps.schools.models import School

from .test_standard_support_scheduling import (
    StandardSupportBase,
    _at,
    _schedulable_date,
)

BACKEND = "apps.accounts.auth_backend.LockoutEnforcingModelBackend"
LEADERSHIP = "SCHOOL_LEADERSHIP"
#: SSA Training: linked to Leadership, as the Leadership course is (owner,
#: 2026-10-06).
IMPROVEMENT = "SSA_TRAINING"
#: A training the catalogue links to no SSA intervention.
ORIENTATION = "NEW_SCHOOL_ORIENTATION"


def _day(offset: int = 0) -> datetime.date:
    """The ``offset``-th schedulable day after ``_schedulable_date()``, in
    its fiscal year. Sundays are stepped over one day at a time, so two
    offsets are never the same date: added to the first day and then moved
    off a Sunday, offsets 1 and 2 were both the Monday whenever the first day
    was a Saturday, and every test that plans on both failed on Wednesdays
    as a duplicate booking."""
    day = _schedulable_date(room=40)
    for _ in range(offset):
        day += datetime.timedelta(days=1)
        while day.weekday() == 6:
            day += datetime.timedelta(days=1)
    return day


class CeilingFixture(StandardSupportBase):
    """One Programme Lead, two officers they supervise, one they do not."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.fy = str(get_operational_fy(_day()))
        cls.pl, cls.pl_staff = cls._person(
            "ceiling-pl@edify.org", "Lead Lydia", "Program Lead"
        )
        cls.mary, cls.mary_staff = cls._person(
            "ceiling-mary@edify.org", "Mary Officer", "CCEO"
        )
        cls.other, cls.other_staff = cls._person(
            "ceiling-other@edify.org", "Outside Officer", "CCEO"
        )
        cls.other_pl, cls.other_pl_staff = cls._person(
            "ceiling-pl2@edify.org", "Lead Lucas", "Program Lead"
        )
        for officer in (cls.staff, cls.mary_staff):
            StaffSupervisorAssignment.objects.create(
                supervisee=officer, supervisor=cls.pl_staff
            )
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.other_staff, supervisor=cls.other_pl_staff
        )
        # John's cluster: enough member schools to pass a ceiling of 20.
        cls.members = [cls.school]
        for index in range(25):
            cls.members.append(cls._member(cls.cluster, cls.staff, f"CEIL-{index:02d}"))
        cls.second_cluster = Cluster.objects.create(
            name="Standard Second Cluster",
            region=cls.region,
            district=cls.district,
            cluster_type="mixed",
            status="active",
        )
        cls.second_members = [
            cls._member(cls.second_cluster, cls.staff, f"SECOND-{index:02d}")
            for index in range(10)
        ]
        cls.mary_cluster = Cluster.objects.create(
            name="Mary Cluster",
            region=cls.region,
            district=cls.district,
            cluster_type="mixed",
            status="active",
        )
        cls.mary_members = [
            cls._member(cls.mary_cluster, cls.mary_staff, f"MARY-{index:02d}")
            for index in range(6)
        ]
        cls.leadership = cls.item(cls, LEADERSHIP)
        cls.improvement = cls.item(cls, IMPROVEMENT)

    @classmethod
    def _person(cls, email, name, role):
        user = User.objects.create_user(
            email=email,
            name=name,
            roles=[role],
            active_role=role,
            password="x",
            is_active=True,
        )
        staff = StaffProfile.objects.create(user=user, country="Uganda")
        return user, staff

    @classmethod
    def _member(cls, cluster, staff, code):
        school = School.objects.create(
            school_id=code,
            name=f"School {code}",
            region=cls.region,
            district=cls.district,
            school_type="client",
            cluster_id=cluster.id,
            cluster_status="clustered",
        )
        StaffSchoolAssignment.objects.create(staff=staff, school_id=school.id)
        return school

    # ── helpers ─────────────────────────────────────────────────────────────
    def ceiling(self, staff=None, training=None, value=20, fy=None):
        return TrainingCeiling.objects.create(
            staff=staff or self.staff,
            training=training or self.leadership,
            fy=fy or self.fy,
            ceiling=value,
        )

    def group(
        self, schools, *, code=LEADERSHIP, user=None, day=0, cluster=None, **extra
    ):
        """A group training scheduled the way the drawer's save schedules it."""
        result = schedule_cluster_activity(
            {
                "activityType": "cluster_training",
                "clusterId": (cluster or self.cluster).id,
                "catalogueItemId": self.item(code).id,
                "scheduledDate": _at(_day(day)).isoformat(),
                "teachersPerSchool": "2",
                "invitedSchoolIds": [s.id for s in schools],
                "deliveryType": "staff",
                **extra,
            },
            user or self.user,
        )
        return Activity.objects.get(id=result["id"])

    def meeting(self, schools, *, kind="", course=None, day=0, **extra):
        payload = {
            "activityType": "cluster_meeting",
            "clusterId": self.cluster.id,
            "catalogueItemId": self.item("STANDARD_CLUSTER_MEETING").id,
            "scheduledDate": _at(_day(day)).isoformat(),
            "leadersPerSchool": "2",
            "invitedSchoolIds": [s.id for s in schools],
            "deliveryType": "staff",
            "purposeType": "operational_admin",
            **extra,
        }
        if kind:
            payload["meetingKind"] = kind
        if course:
            payload["trainingCourseId"] = self.item(course).id
        result = schedule_cluster_activity(payload, self.user)
        return Activity.objects.get(id=result["id"])

    def in_school(self, school, *, code=LEADERSHIP, user=None, staff=None, day=0):
        result = schedule_in_school_training_pair(
            {
                "schoolId": school.school_id,
                "catalogueItemId": self.item(code).id,
                "scheduledDate": _at(_day(day)).isoformat(),
                "responsibleStaffId": (staff or self.staff).id,
                "deliveryType": "staff",
                "executorType": "staff",
                "requireCatalogue": True,
            },
            user or self.user,
        )
        return Activity.objects.get(id=result["id"])

    def counts(self, staff=None, training=None):
        """The two deliveries staff plan, and the schools in all. The schools
        with a Partner are counted beside them
        (apps.planning.test_training_coverage)."""
        counted = training_ceilings.scheduled_count(
            staff or self.staff, (training or self.leadership).id, self.fy
        )
        return {key: counted[key] for key in ("group", "in_school", "total")}

    def invited(self, activity) -> set[str]:
        return set(
            ClusterActivityAttendance.objects.filter(
                activity=activity, invited=True
            ).values_list("school_id", flat=True)
        )

    def client_for(self, user) -> Client:
        client = Client()
        client.force_login(user, backend=BACKEND)
        return client


# ── The catalogue: the training and its SSA intervention ────────────────────
class TrainingCarriesItsOwnIntervention(CeilingFixture):
    def test_ssa_training_is_linked_to_leadership(self):
        """Owner, 2026-10-06: "School improvement Planning is actually SSA
        training. can you just link SSA training to Leadership ssa
        intervention and then remove the school improvement planning that i
        proposed earlier". So the catalogue keeps its 21 trainings, SSA
        Training carries the Leadership link, and no School Improvement
        entry is added beside it."""
        from apps.activity_catalogue.models import ActivityCatalogueItem

        self.assertEqual(self.improvement.display_name, "SSA Training")
        self.assertFalse(
            ActivityCatalogueItem.objects.filter(
                stable_code="SCHOOL_IMPROVEMENT_TRAININGS"
            ).exists()
        )
        self.assertEqual(
            ActivityCatalogueItem.objects.filter(is_training_course=True).count(), 21
        )
        self.assertTrue(self.improvement.is_training_course)
        self.assertEqual(self.improvement.status, "active")
        self.assertEqual(
            intervention_for(training_course_id=self.improvement.id),
            SsaIntervention.LEADERSHIP,
        )
        # The existing Leadership intervention, not a second one.
        self.assertEqual(
            intervention_for(training_course_id=self.leadership.id),
            SsaIntervention.LEADERSHIP,
        )
        self.assertEqual(
            len(
                [
                    code
                    for code, _label in SsaIntervention.choices
                    if "leadership" in code
                ]
            ),
            1,
        )

    def test_it_is_offered_wherever_a_training_is_chosen(self):
        from apps.activity_catalogue.availability import (
            CLUSTER,
            in_school_training_course_options,
            training_activity_options,
        )

        for options in (
            training_activity_options(planning_context=CLUSTER, cluster=self.cluster),
            in_school_training_course_options(school=self.school),
        ):
            row = next(o for o in options if o["stableCode"] == IMPROVEMENT)
            self.assertEqual(row["ssaIntervention"], SsaIntervention.LEADERSHIP)
            self.assertEqual(row["ssaInterventionLabel"], "Leadership")

    def test_a_group_training_takes_the_trainings_intervention_whatever_is_posted(self):
        session = self.group(
            self.members[:2],
            code=IMPROVEMENT,
            focusIntervention=SsaIntervention.FINANCIAL_HEALTH,
            purposeIntervention=SsaIntervention.FINANCIAL_HEALTH,
        )

        self.assertEqual(session.catalogue_item_id, self.improvement.id)
        self.assertEqual(session.focus_intervention, SsaIntervention.LEADERSHIP)
        self.assertEqual(session.purpose_intervention, SsaIntervention.LEADERSHIP)

    def test_the_drawers_post_cannot_pair_a_training_with_another_intervention(self):
        response = self.client_for(self.user).post(
            "/planning/schedule-action",
            {
                "cluster_id": self.cluster.id,
                "activity_type": "cluster_training",
                "catalogue_item_id": self.improvement.id,
                "focus_intervention": SsaIntervention.FINANCIAL_HEALTH,
                "scheduled_date": _day().isoformat(),
                "teachers_per_school": "2",
                "invited_school_ids": [self.members[0].id, self.members[1].id],
                "delivery_type": "staff",
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200, response.content)
        session = Activity.objects.get(catalogue_item=self.improvement)
        self.assertEqual(session.focus_intervention, SsaIntervention.LEADERSHIP)

    def test_an_in_school_training_takes_the_trainings_intervention(self):
        training = self.in_school(self.members[1], code=IMPROVEMENT)

        self.assertEqual(training.training_course_id, self.improvement.id)
        self.assertEqual(training.focus_intervention, SsaIntervention.LEADERSHIP)
        self.assertEqual(training.school_id, self.members[1].id)
        self.assertEqual(training.activity_type, "in_school_training")

    def test_a_training_that_is_not_ssa_scored_records_no_intervention(self):
        """An orientation is linked to no intervention, and none is invented
        for it from what a request carries."""
        session = self.group(
            self.members[:2],
            code=ORIENTATION,
            focusIntervention=SsaIntervention.ENROLMENT,
        )

        self.assertEqual(
            intervention_for(training_course_id=session.catalogue_item_id), ""
        )
        self.assertIsNone(session.focus_intervention)

    def test_only_a_training_open_to_any_intervention_offers_the_planner_a_choice(self):
        from apps.activity_catalogue.availability import (
            CLUSTER,
            training_activity_options,
        )
        from apps.activity_catalogue.models import (
            ActivityInterventionMapping,
            MappingMode,
        )

        def options():
            return {
                o["stableCode"]: o
                for o in training_activity_options(planning_context=CLUSTER)
            }

        before = options()
        self.assertFalse(before[LEADERSHIP]["plannerChooses"])
        self.assertFalse(before[ORIENTATION]["plannerChooses"])
        self.assertEqual(before[ORIENTATION]["ssaInterventionLabel"], "Not SSA-scored")

        ActivityInterventionMapping.objects.filter(
            catalogue_item=self.item(ORIENTATION), active=True
        ).update(mapping_mode=MappingMode.ANY_SSA_INTERVENTION)

        self.assertTrue(options()[ORIENTATION]["plannerChooses"])
        session = self.group(
            self.members[:2],
            code=ORIENTATION,
            focusIntervention=SsaIntervention.ENROLMENT,
        )
        self.assertEqual(session.focus_intervention, SsaIntervention.ENROLMENT)

    def test_an_edit_cannot_move_a_training_to_another_intervention(self):
        session = self.group(self.members[:2])

        editing.edit(
            session.id,
            {"focusIntervention": SsaIntervention.FINANCIAL_HEALTH},
            self.user,
        )
        session.refresh_from_db()
        self.assertEqual(session.focus_intervention, SsaIntervention.LEADERSHIP)

        from apps.activities.services import patch_activity

        with self.assertRaises(BadRequest):
            patch_activity(
                session.id,
                {"focusIntervention": SsaIntervention.FINANCIAL_HEALTH},
                self.user,
            )

    def test_an_edit_cannot_give_an_unscored_training_an_intervention(self):
        """The catalogue's answer for an orientation is "none", and an edit
        does not replace it either."""
        from apps.activities.services import patch_activity

        session = self.group(self.members[:2], code=ORIENTATION)

        editing.edit(
            session.id, {"focusIntervention": SsaIntervention.ENROLMENT}, self.user
        )
        session.refresh_from_db()
        self.assertIsNone(session.focus_intervention)
        with self.assertRaises(BadRequest):
            patch_activity(
                session.id, {"focusIntervention": SsaIntervention.ENROLMENT}, self.user
            )

    def test_a_later_catalogue_change_leaves_scheduled_trainings_as_they_were(self):
        """The link is authoritative for what is scheduled next; what was
        scheduled keeps the intervention it was scheduled under."""
        from apps.activity_catalogue.models import ActivityInterventionMapping

        before = self.group(self.members[:2])
        ActivityInterventionMapping.objects.filter(
            catalogue_item=self.leadership, active=True
        ).update(intervention=SsaIntervention.ENROLMENT)

        after = self.group(self.members[2:4], day=1)

        before.refresh_from_db()
        self.assertEqual(before.focus_intervention, SsaIntervention.LEADERSHIP)
        self.assertEqual(after.focus_intervention, SsaIntervention.ENROLMENT)


# ── What is scheduled, counted from the plans ───────────────────────────────
class ScheduledIsCountedFromThePlans(CeilingFixture):
    def test_a_group_training_counts_each_school_named_on_it(self):
        session = self.group(self.members[:5])

        self.assertEqual(self.invited(session), {s.id for s in self.members[:5]})
        self.assertEqual(
            training_ceilings.delivery_of(session), training_ceilings.GROUP
        )
        self.assertEqual(self.counts(), {"group": 5, "in_school": 0, "total": 5})

    def test_an_in_school_training_counts_its_one_school(self):
        training = self.in_school(self.members[1])

        self.assertEqual(
            training_ceilings.delivery_of(training), training_ceilings.IN_SCHOOL
        )
        self.assertEqual(self.counts(), {"group": 0, "in_school": 1, "total": 1})
        # Its companion School Visit is the journey, not a second training.
        self.assertEqual(Activity.objects.filter(school=self.members[1]).count(), 2)

    def test_both_deliveries_are_counted_apart_and_added(self):
        self.group(self.members[:4])
        self.in_school(self.members[10])
        self.in_school(self.members[11], day=1)

        self.assertEqual(self.counts(), {"group": 4, "in_school": 2, "total": 6})

    def test_a_cancelled_plan_gives_its_places_back(self):
        from apps.activities.services import cancel

        session = self.group(self.members[:4])
        self.assertEqual(self.counts()["total"], 4)

        cancel(session.id, {"reason": "Venue lost"}, self.user)

        self.assertEqual(self.counts()["total"], 0)

    def test_another_training_and_another_officer_are_counted_apart(self):
        self.group(self.members[:3])
        self.group(self.members[3:5], code=IMPROVEMENT, day=1)
        self.group(self.mary_members[:2], user=self.mary, cluster=self.mary_cluster)

        self.assertEqual(self.counts()["total"], 3)
        self.assertEqual(self.counts(training=self.improvement)["total"], 2)
        self.assertEqual(self.counts(staff=self.mary_staff)["total"], 2)

    def test_a_school_scheduled_twice_is_one_scheduled_school(self):
        """Each scheduled delivery stays its own record, and a repeat is not
        refused; the school is still one school (owner, 2026-10-08: "some
        are blocking before hitting the ceiling"). It was counted once for
        each session."""
        first = self.group(self.members[:2])
        second = self.group(self.members[:2], day=1)

        self.assertNotEqual(first.id, second.id)
        self.assertEqual(self.counts(), {"group": 2, "in_school": 0, "total": 2})

    def test_a_school_trained_both_ways_is_one_scheduled_school(self):
        self.group(self.members[:2])
        self.in_school(self.members[0])

        self.assertEqual(self.counts(), {"group": 2, "in_school": 1, "total": 2})
        row = training_ceilings.summary_for_staff([self.staff], self.fy)[0]
        self.assertEqual((row.group, row.in_school, row.both, row.total), (2, 1, 1, 2))

    def test_schools_added_in_any_cluster_are_counted_together(self):
        self.group(self.members[:6])
        self.group(self.second_members[:4], cluster=self.second_cluster, day=1)

        self.assertEqual(self.counts(), {"group": 10, "in_school": 0, "total": 10})

    def test_a_school_recorded_at_the_session_without_an_invitation_is_counted(self):
        """Every school added to a training is counted: a walk-in or a guest
        recorded as attending is a school the training reached."""
        session = self.group(self.members[:3])
        ClusterActivityAttendance.objects.create(
            activity=session, school=self.members[7], invited=False, attended=True
        )
        ClusterActivityAttendance.objects.create(
            activity=session,
            school=self.second_members[0],
            invited=False,
            attended=True,
            is_guest=True,
        )

        self.assertEqual(self.counts()["group"], 5)

    def test_one_session_never_holds_a_school_twice(self):
        session = self.group([self.members[0], self.members[0], self.members[1]])

        self.assertEqual(
            ClusterActivityAttendance.objects.filter(activity=session).count(), 2
        )


# ── The ceiling, held on the server ─────────────────────────────────────────
class TheCeilingIsHeld(CeilingFixture):
    def test_twenty_schools_fit_a_ceiling_of_twenty(self):
        self.ceiling(value=20)

        self.group(self.members[:20])

        capacity = training_ceilings.capacity(
            self.staff.id, self.leadership.id, self.fy
        )
        self.assertEqual(capacity["scheduled"], 20)
        self.assertEqual(capacity["ceiling"], 20)
        self.assertEqual(capacity["remaining"], 0)

    def test_the_twenty_first_school_is_refused(self):
        self.ceiling(value=20)

        with self.assertRaises(BadRequest) as refused:
            self.group(self.members[:21])

        self.assertIn("Training ceiling reached", str(refused.exception.detail))
        # Refused whole: no session, and no school attached to one.
        self.assertFalse(
            Activity.objects.filter(activity_type="cluster_training").exists()
        )
        self.assertEqual(self.counts()["total"], 0)

    def test_a_second_drawer_does_not_start_again_from_zero(self):
        self.ceiling(value=20)
        self.group(self.members[:17])

        capacity = training_ceilings.capacity(
            self.staff.id, self.leadership.id, self.fy
        )
        self.assertEqual((capacity["scheduled"], capacity["remaining"]), (17, 3))

        with self.assertRaises(BadRequest):
            self.group(self.members[17:21], day=1)
        self.group(self.members[17:20], day=1)

        self.assertEqual(self.counts()["total"], 20)

    def test_eighteen_of_twenty_leaves_room_for_two(self):
        self.ceiling(value=20)
        self.group(self.members[:18])

        with self.assertRaises(BadRequest):
            self.group(self.members[18:21], day=1)
        self.group(self.members[18:20], day=1)

    def test_an_in_school_training_takes_one_place_and_is_refused_at_the_ceiling(self):
        self.ceiling(value=3)
        self.group(self.members[:2])
        self.in_school(self.members[10])

        with self.assertRaises(BadRequest) as refused:
            self.in_school(self.members[11], day=1)

        self.assertIn("Training ceiling reached", str(refused.exception.detail))
        self.assertFalse(Activity.objects.filter(school=self.members[11]).exists())
        self.assertEqual(self.counts(), {"group": 2, "in_school": 1, "total": 3})

    def test_one_ceiling_holds_the_schools_of_every_cluster(self):
        """Schools are added from any cluster's group training; the ceiling
        is the officer's for the training, not a cluster's."""
        self.ceiling(value=20)
        self.group(self.members[:12])
        self.group(self.second_members[:6], cluster=self.second_cluster, day=1)

        with self.assertRaises(BadRequest) as refused:
            self.group(self.second_members[6:9], cluster=self.second_cluster, day=2)

        message = str(refused.exception.detail)
        self.assertIn("Training ceiling reached", message)
        self.assertIn("only 2 more schools can be added", message)
        self.group(self.second_members[6:8], cluster=self.second_cluster, day=2)
        self.assertEqual(self.counts()["total"], 20)

        with self.assertRaises(BadRequest) as full:
            self.group(self.members[12:13], day=3)
        self.assertIn("no more schools can be added", str(full.exception.detail))

    def test_no_ceiling_is_no_limit(self):
        self.group(self.members[:25])

        capacity = training_ceilings.capacity(
            self.staff.id, self.leadership.id, self.fy
        )
        self.assertFalse(capacity["managed"])
        self.assertIsNone(capacity["remaining"])
        self.assertEqual(capacity["scheduled"], 25)

    def test_a_ceiling_is_one_officers_one_trainings_one_years(self):
        self.ceiling(value=2)

        # Another training, and another officer, are not held by it.
        self.group(self.members[:5], code=IMPROVEMENT)
        self.group(self.mary_members[:5], user=self.mary, cluster=self.mary_cluster)
        with self.assertRaises(BadRequest):
            self.group(self.members[:3], day=1)

    def test_a_training_with_no_school_ticked_is_refused(self):
        """No tick is an answer once the drawer has shown its list: a
        training is not planned for "the whole cluster" with nobody counted."""
        response = self.client_for(self.user).post(
            "/planning/schedule-action",
            {
                "cluster_id": self.cluster.id,
                "activity_type": "cluster_training",
                "catalogue_item_id": self.leadership.id,
                "scheduled_date": _day().isoformat(),
                "teachers_per_school": "2",
                "invited_schools_shown": "1",
                "delivery_type": "staff",
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(
            "Tick the schools this training is for.", response.content.decode()
        )
        self.assertFalse(
            Activity.objects.filter(activity_type="cluster_training").exists()
        )

    def test_under_a_ceiling_a_group_training_names_its_schools(self):
        """A caller that names no school cannot slip a session past the
        ceiling as an uncounted "whole cluster"."""
        payload = {
            "activityType": "cluster_training",
            "clusterId": self.cluster.id,
            "catalogueItemId": self.leadership.id,
            "scheduledDate": _at(_day()).isoformat(),
            "teachersPerSchool": "2",
            "deliveryType": "staff",
        }
        self.ceiling(value=2)

        with self.assertRaises(BadRequest) as refused:
            schedule_cluster_activity(payload, self.user)
        self.assertIn("Tick the schools", str(refused.exception.detail))

        # With no ceiling the older reading stands, as it always has.
        TrainingCeiling.objects.all().delete()
        schedule_cluster_activity(payload, self.user)
        self.assertEqual(self.counts()["total"], 0)

    def test_the_drawers_post_is_refused_above_the_ceiling(self):
        """A request that ticks more than the browser allowed is refused by
        the save, with the reason."""
        self.ceiling(value=2)

        response = self.client_for(self.user).post(
            "/planning/schedule-action",
            {
                "cluster_id": self.cluster.id,
                "activity_type": "cluster_training",
                "catalogue_item_id": self.leadership.id,
                "scheduled_date": _day().isoformat(),
                "teachers_per_school": "2",
                "invited_school_ids": [s.id for s in self.members[:3]],
                "delivery_type": "staff",
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Training ceiling reached", response.content.decode())
        self.assertFalse(
            Activity.objects.filter(activity_type="cluster_training").exists()
        )


class EditingAGroupTraining(CeilingFixture):
    def test_its_own_schools_are_not_counted_against_it(self):
        self.ceiling(value=20)
        session = self.group(self.members[:20])

        # Saved again as it is, at the ceiling: nothing is counted twice.
        editing.edit(
            session.id,
            {"invitedSchoolIds": [s.id for s in self.members[:20]]},
            self.user,
        )

        self.assertEqual(len(self.invited(session)), 20)
        capacity = training_ceilings.capacity(
            self.staff.id, self.leadership.id, self.fy, exclude_activity_id=session.id
        )
        self.assertEqual((capacity["scheduled"], capacity["remaining"]), (0, 20))

    def test_eighteen_of_twenty_takes_two_more_and_not_three(self):
        self.ceiling(value=20)
        session = self.group(self.members[:18])

        with self.assertRaises(BadRequest):
            editing.edit(
                session.id,
                {"invitedSchoolIds": [s.id for s in self.members[:21]]},
                self.user,
            )
        self.assertEqual(len(self.invited(session)), 18)

        editing.edit(
            session.id,
            {"invitedSchoolIds": [s.id for s in self.members[:20]]},
            self.user,
        )
        self.assertEqual(len(self.invited(session)), 20)

    def test_removing_schools_gives_their_places_back(self):
        self.ceiling(value=20)
        session = self.group(self.members[:20])
        with self.assertRaises(BadRequest):
            self.group(self.members[20:22], day=1)

        editing.edit(
            session.id,
            {"invitedSchoolIds": [s.id for s in self.members[:18]]},
            self.user,
        )

        self.assertEqual(self.counts()["total"], 18)
        self.group(self.members[20:22], day=1)
        self.assertEqual(self.counts()["total"], 20)

    def test_a_school_can_be_swapped_at_the_ceiling(self):
        self.ceiling(value=5)
        session = self.group(self.members[:5])

        editing.edit(
            session.id,
            {"invitedSchoolIds": [s.id for s in [*self.members[:4], self.members[9]]]},
            self.user,
        )

        self.assertIn(self.members[9].id, self.invited(session))
        self.assertEqual(self.counts()["total"], 5)

    def test_above_a_lowered_ceiling_it_may_shrink_but_not_grow(self):
        row = self.ceiling(value=20)
        session = self.group(self.members[:10])
        row.ceiling = 6
        row.save()

        editing.edit(
            session.id,
            {"invitedSchoolIds": [s.id for s in self.members[:9]]},
            self.user,
        )
        self.assertEqual(self.counts()["total"], 9)
        with self.assertRaises(BadRequest):
            editing.edit(
                session.id,
                {"invitedSchoolIds": [s.id for s in self.members[:10]]},
                self.user,
            )

    def test_the_edit_drawer_keeps_its_schools_ticked_and_counts_the_rest(self):
        self.ceiling(value=20)
        self.group(self.members[20:23], day=1)
        session = self.group(self.members[:15])

        response = self.client_for(self.user).get(f"/my-plan/{session.id}/edit-drawer")

        self.assertEqual(response.status_code, 200)
        context = response.context
        ticked = [s for s in context["member_schools"] if s["invited"]]
        self.assertEqual(len(ticked), 15)
        capacity = json.loads(context["edit_ceiling_json"])
        # The other session's three; this session's fifteen are its own.
        self.assertEqual((capacity["scheduled"], capacity["remaining"]), (3, 17))
        body = response.content.decode()
        self.assertIn("data-training-ceiling-counter", body)
        self.assertIn(':disabled="isHeld($el)"', body)
        # The training and its intervention are shown, not offered for change.
        self.assertIn("data-edit-training", body)
        self.assertIn('x-if="interventionLocked"', body)
        self.assertTrue(context["edit_training"]["intervention_locked"])


class NamingTheTrainingOnItsProfile(CeilingFixture):
    """Owner, 2026-10-06: "when I go to the training profile, I should be able
    to click edit and then the training field is empty then I click and get a
    dropdown of all the trainings and select the right one for that training."
    """

    def unnamed_group_training(self, schools):
        """A group training planned before trainings named a catalogue entry."""
        session = Activity.objects.create(
            activity_type="cluster_training",
            cluster=self.cluster,
            responsible_staff_id=self.staff.id,
            delivery_type="staff",
            status="scheduled",
            fy=self.fy,
            quarter="Q1",
            planned_date=_day(),
            scheduled_date=_at(_day()),
            teachers_per_school=2,
        )
        for school in schools:
            ClusterActivityAttendance.objects.create(
                activity=session, school=school, invited=True
            )
        return session

    def drawer(self, activity):
        response = self.client_for(self.user).get(f"/my-plan/{activity.id}/edit-drawer")
        self.assertEqual(response.status_code, 200)
        return response

    def save(self, activity, **fields):
        return self.client_for(self.user).post(
            f"/my-plan/{activity.id}/edit", fields, HTTP_HX_REQUEST="true"
        )

    def test_an_unnamed_training_opens_with_an_empty_training_field(self):
        session = self.unnamed_group_training(self.members[:4])

        response = self.drawer(session)

        training = response.context["edit_training"]
        self.assertEqual(training["id"], "")
        self.assertTrue(training["may_change"])
        labels = [option["label"] for option in training["options"]]
        # Every training that is delivered to a cluster, as the Group
        # Training drawer lists them.
        from apps.activity_catalogue.availability import (
            CLUSTER,
            training_activity_options,
        )

        self.assertEqual(
            labels,
            [o["label"] for o in training_activity_options(planning_context=CLUSTER)],
        )
        self.assertGreaterEqual(len(labels), 17)
        self.assertIn("SSA Training", labels)
        self.assertIn("Leadership", labels)
        body = response.content.decode()
        self.assertIn('name="training_course_id"', body)
        self.assertIn('<option value="">Select a training…</option>', body)
        self.assertIn("trainingId: ''", body)
        self.assertIn("No training is named on this plan yet.", body)
        # Until it is named, its schools belong to no training's count.
        self.assertEqual(self.counts()["total"], 0)

    def test_choosing_the_training_names_it_and_brings_its_intervention(self):
        session = self.unnamed_group_training(self.members[:4])

        response = self.save(
            session,
            training_course_id=self.improvement.id,
            invited_schools_shown="1",
            invited_school_ids=[s.id for s in self.members[:4]],
        )

        self.assertEqual(response.status_code, 200, response.content[:300])
        session.refresh_from_db()
        self.assertEqual(session.catalogue_item_id, self.improvement.id)
        self.assertEqual(session.activity_name_snapshot, "SSA Training")
        self.assertEqual(session.focus_intervention, SsaIntervention.LEADERSHIP)
        self.assertEqual(session.activity_type, "cluster_training")
        # Its schools are counted from then on.
        self.assertEqual(self.counts(training=self.improvement)["group"], 4)
        self.assertTrue(
            AuditLog.objects.filter(
                action="activity.training_changed", subject_id=session.id
            ).exists()
        )

    def test_a_named_training_can_be_changed_to_the_right_one(self):
        session = self.group(self.members[:5])
        self.assertEqual(session.activity_name_snapshot, "Leadership")

        editing.edit(session.id, {"trainingCourseId": self.item("TAM_I").id}, self.user)

        session.refresh_from_db()
        self.assertEqual(session.catalogue_item.stable_code, "TAM_I")
        self.assertEqual(session.activity_name_snapshot, "Teaching as Mission (TAM)")
        self.assertEqual(
            session.focus_intervention, SsaIntervention.EXPOSURE_TO_WORD_OF_GOD
        )
        # Its schools moved with it: off Leadership, onto the training chosen.
        self.assertEqual(self.counts()["total"], 0)
        self.assertEqual(self.counts(training=self.item("TAM_I"))["group"], 5)
        self.assertEqual(len(self.invited(session)), 5)

    def test_an_in_school_training_is_renamed_with_its_visit(self):
        training = self.in_school(self.members[3])
        visit = training.paired_school_visit

        editing.edit(training.id, {"trainingCourseId": self.improvement.id}, self.user)

        training.refresh_from_db()
        visit.refresh_from_db()
        self.assertEqual(training.training_course_id, self.improvement.id)
        self.assertEqual(training.activity_name_snapshot, "SSA Training")
        # The workflow that prices and evidences it is untouched.
        self.assertEqual(
            training.catalogue_item.stable_code, "STANDARD_IN_SCHOOL_TRAINING"
        )
        self.assertEqual(training.activity_type, "in_school_training")
        self.assertEqual(visit.focus_intervention, training.focus_intervention)
        self.assertEqual(
            visit.activity_purpose_text,
            "School visit accompanying SSA Training",
        )
        self.assertEqual(
            self.counts(training=self.improvement),
            {"group": 0, "in_school": 1, "total": 1},
        )
        self.assertEqual(self.counts()["total"], 0)

    def test_the_training_chosen_must_have_room_under_its_ceiling(self):
        self.ceiling(training=self.improvement, value=3)
        session = self.group(self.members[:5])

        with self.assertRaises(BadRequest) as refused:
            editing.edit(
                session.id, {"trainingCourseId": self.improvement.id}, self.user
            )
        self.assertIn("Training ceiling reached", str(refused.exception.detail))
        session.refresh_from_db()
        self.assertEqual(session.catalogue_item_id, self.leadership.id)

        # Trimmed to fit in the same save, it moves.
        editing.edit(
            session.id,
            {
                "trainingCourseId": self.improvement.id,
                "invitedSchoolIds": [s.id for s in self.members[:3]],
            },
            self.user,
        )
        session.refresh_from_db()
        self.assertEqual(session.catalogue_item_id, self.improvement.id)
        self.assertEqual(self.counts(training=self.improvement)["group"], 3)

    def test_only_a_training_in_the_catalogue_can_be_chosen(self):
        session = self.group(self.members[:2])

        with self.assertRaises(BadRequest):
            editing.edit(
                session.id,
                {"trainingCourseId": self.item("STANDARD_SCHOOL_VISIT").id},
                self.user,
            )
        with self.assertRaises(BadRequest):
            editing.edit(session.id, {"trainingCourseId": ""}, self.user)

    def test_a_training_already_carried_out_keeps_its_record(self):
        session = self.group(self.members[:2])
        Activity.objects.filter(id=session.id).update(status="ia_verified")

        with self.assertRaises(BadRequest):
            editing.edit(
                session.id, {"trainingCourseId": self.improvement.id}, self.user
            )

        session.refresh_from_db()
        self.assertEqual(session.catalogue_item_id, self.leadership.id)
        self.assertEqual(session.focus_intervention, SsaIntervention.LEADERSHIP)

    def test_a_cluster_meeting_that_is_a_training_can_be_renamed_too(self):
        meeting = self.meeting(
            self.members[:3], kind=MeetingKind.TRAINING, course=LEADERSHIP
        )

        editing.edit(meeting.id, {"trainingCourseId": self.improvement.id}, self.user)

        meeting.refresh_from_db()
        self.assertEqual(meeting.training_course_id, self.improvement.id)
        self.assertEqual(meeting.activity_type, "cluster_meeting")
        self.assertEqual(meeting.catalogue_item.stable_code, "STANDARD_CLUSTER_MEETING")

    def test_the_profile_names_the_training_and_how_it_is_delivered(self):
        client = self.client_for(self.user)
        unnamed = self.unnamed_group_training(self.members[:2])
        group = self.group(self.members[2:4], day=1)
        in_school = self.in_school(self.members[5], code=IMPROVEMENT, day=2)

        page = client.get(f"/my-plan/{unnamed.id}")
        self.assertEqual(
            page.context["training_profile"],
            {"name": "", "delivery": "Group Training"},
        )
        body = page.content.decode()
        self.assertIn("No training named yet", body)
        self.assertIn("choose it with Edit Activity", body)

        self.assertEqual(
            client.get(f"/my-plan/{group.id}").context["training_profile"],
            {"name": "Leadership", "delivery": "Group Training"},
        )
        page = client.get(f"/my-plan/{in_school.id}")
        self.assertEqual(
            page.context["training_profile"],
            {"name": "SSA Training", "delivery": "In-School Training"},
        )
        self.assertIn("data-training-profile", page.content.decode())
        # A school visit is not a training and says nothing about one.
        visit = in_school.paired_school_visit
        self.assertNotIn("training_profile", client.get(f"/my-plan/{visit.id}").context)

    def test_a_plain_meeting_has_no_training_field(self):
        meeting = self.meeting(self.members[:3], kind=MeetingKind.ONLY_MEETING)

        response = self.drawer(meeting)

        self.assertNotIn("edit_training", response.context)
        self.assertNotIn('name="training_course_id"', response.content.decode())

    def test_the_drawer_reads_the_ceiling_of_the_training_being_chosen(self):
        self.ceiling(training=self.improvement, value=9)
        self.group(self.members[10:14], code=IMPROVEMENT, day=1)
        session = self.group(self.members[:5])

        answer = (
            self.client_for(self.user)
            .get(
                "/planning/training-capacity",
                {"activity": session.id, "training": self.improvement.id},
            )
            .json()
        )

        self.assertEqual(
            (answer["ceiling"], answer["scheduled"], answer["remaining"]), (9, 4, 5)
        )


class MovingATraining(CeilingFixture):
    def test_handing_a_training_to_another_officer_asks_their_ceiling(self):
        from apps.activities.services import reassign

        self.ceiling(staff=self.mary_staff, value=2)
        session = self.group(self.members[:3])

        with self.assertRaises(BadRequest) as refused:
            reassign(session.id, {"responsibleStaffId": self.mary_staff.id}, self.user)
        self.assertIn("Training ceiling reached", str(refused.exception.detail))

        session.refresh_from_db()
        self.assertEqual(session.responsible_staff_id, self.staff.id)

    def test_moving_a_training_into_another_year_asks_that_years_ceiling(self):
        next_fy = str(int(self.fy) + 1)
        self.ceiling(value=1, fy=next_fy)
        session = self.group(self.members[:2])

        capacity = training_ceilings.capacity(
            self.staff.id, self.leadership.id, next_fy
        )
        self.assertEqual((capacity["ceiling"], capacity["scheduled"]), (1, 0))
        with self.assertRaises(BadRequest):
            training_ceilings.reserve_for_move(session, fy=next_fy)
        # Within its own year the move asks nothing.
        training_ceilings.reserve_for_move(session, fy=self.fy)


# ── Balance and Excess ──────────────────────────────────────────────────────
class BalanceAndExcess(CeilingFixture):
    def row(self, ceiling, group, in_school=0):
        return training_ceilings.SummaryRow(
            staff_id="s",
            staff_name="John",
            training_id="t",
            training_name="Leadership",
            intervention="Leadership",
            ceiling_id="c",
            ceiling=ceiling,
            group=group,
            in_school=in_school,
        )

    def test_eighteen_of_twenty(self):
        row = self.row(20, 14, 4)
        self.assertEqual((row.total, row.balance, row.excess), (18, 2, 0))
        self.assertEqual(row.state, "available")

    def test_twenty_of_twenty(self):
        row = self.row(20, 16, 4)
        self.assertEqual((row.total, row.balance, row.excess), (20, 0, 0))
        self.assertEqual(row.state, "reached")

    def test_twenty_three_of_twenty_is_excess_never_a_negative_balance(self):
        row = self.row(20, 20, 3)
        self.assertEqual((row.total, row.balance, row.excess), (23, 0, 3))
        self.assertEqual(row.state, "above")

    def test_no_ceiling_has_no_balance_and_no_excess(self):
        row = self.row(None, 7)
        self.assertEqual((row.total, row.balance, row.excess), (7, None, 0))
        self.assertEqual(row.state, "unset")

    def test_each_row_is_flagged_above_below_or_at_its_ceiling(self):
        """The lead reads which training has more schools than it should
        and which has fewer."""
        rows = [
            self.row(20, 20, 3),
            self.row(20, 14, 4),
            self.row(20, 16, 4),
            self.row(None, 7),
        ]

        self.assertEqual(
            [(r.flag, r.flag_tone) for r in rows],
            [
                ("3 above ceiling", "danger"),
                ("2 below ceiling", "warning"),
                ("At ceiling", "success"),
                ("No ceiling set", "neutral"),
            ],
        )
        self.assertEqual(
            training_ceilings.flag_counts(rows),
            {"above": 1, "available": 1, "reached": 1, "unset": 1},
        )

    def test_a_ceiling_lowered_below_what_is_scheduled_reads_as_excess(self):
        """The state the drawers prevent, reached legitimately: the summary
        still reports it, from the plans."""
        row = self.ceiling(value=25)
        self.group(self.members[:20])
        self.in_school(self.members[21], day=1)
        self.in_school(self.members[22], day=2)
        self.in_school(self.members[23], day=3)
        row.ceiling = 20
        row.save()

        (summary,) = training_ceilings.own_summary(self.user, self.fy)

        self.assertEqual(
            (summary.ceiling, summary.group, summary.in_school, summary.total),
            (20, 20, 3, 23),
        )
        self.assertEqual((summary.balance, summary.excess), (0, 3))


# ── Who sets and who sees ───────────────────────────────────────────────────
class SettingACeiling(CeilingFixture):
    def test_a_programme_lead_sets_it_for_an_officer_they_supervise(self):
        row = training_ceilings.set_ceiling(
            self.pl,
            staff_id=self.staff.id,
            training_id=self.leadership.id,
            fy=self.fy,
            ceiling="20",
        )

        self.assertEqual(
            (row.staff_id, row.training_id, row.fy, row.ceiling),
            (self.staff.id, self.leadership.id, self.fy, 20),
        )
        self.assertEqual(row.set_by_role, "Program Lead")

    def test_setting_it_again_changes_it_and_keeps_one_row(self):
        for value in ("20", "30"):
            training_ceilings.set_ceiling(
                self.pl,
                staff_id=self.staff.id,
                training_id=self.leadership.id,
                fy=self.fy,
                ceiling=value,
            )

        self.assertEqual(TrainingCeiling.objects.get().ceiling, 30)
        trail = list(
            AuditLog.objects.filter(action="training_ceiling.set").order_by(
                "created_at"
            )
        )
        self.assertEqual(
            [(t.payload["from"], t.payload["to"]) for t in trail],
            [(None, 20), (20, 30)],
        )

    def test_nobody_else_sets_it(self):
        for who in (self.user, self.mary, self.other_pl):
            with self.subTest(who=who.name), self.assertRaises(Forbidden):
                training_ceilings.set_ceiling(
                    who,
                    staff_id=self.staff.id,
                    training_id=self.leadership.id,
                    fy=self.fy,
                    ceiling="20",
                )
        self.assertFalse(TrainingCeiling.objects.exists())

    def test_a_ceiling_is_a_whole_number_of_schools_for_an_active_training(self):
        for bad in ("", "0", "-3", "2.5", "many"):
            with self.subTest(ceiling=bad), self.assertRaises(BadRequest):
                training_ceilings.set_ceiling(
                    self.pl,
                    staff_id=self.staff.id,
                    training_id=self.leadership.id,
                    fy=self.fy,
                    ceiling=bad,
                )
        with self.assertRaises(BadRequest):
            training_ceilings.set_ceiling(
                self.pl,
                staff_id=self.staff.id,
                training_id=self.item("STANDARD_SCHOOL_VISIT").id,
                fy=self.fy,
                ceiling="5",
            )
        with self.assertRaises(BadRequest):
            training_ceilings.set_ceiling(
                self.pl,
                staff_id=self.staff.id,
                training_id=self.leadership.id,
                fy="1999",
                ceiling="5",
            )

    def test_it_may_be_set_below_what_is_scheduled(self):
        self.group(self.members[:8])

        row = training_ceilings.set_ceiling(
            self.pl,
            staff_id=self.staff.id,
            training_id=self.leadership.id,
            fy=self.fy,
            ceiling="5",
        )

        self.assertEqual(row.ceiling, 5)
        with self.assertRaises(BadRequest):
            self.group(self.members[8:9], day=1)

    def test_removing_it_lifts_the_limit_and_is_recorded(self):
        row = self.ceiling(value=2)
        with self.assertRaises(BadRequest):
            self.group(self.members[:3])
        with self.assertRaises(Forbidden):
            training_ceilings.remove_ceiling(self.other_pl, row.id)

        training_ceilings.remove_ceiling(self.pl, row.id)

        self.group(self.members[:3])
        self.assertTrue(
            AuditLog.objects.filter(action="training_ceiling.removed").exists()
        )

    def test_the_drawer_sets_one_from_the_leads_page(self):
        client = self.client_for(self.pl)

        drawer = client.get("/training-ceilings/set", HTTP_HX_REQUEST="true")
        self.assertEqual(drawer.status_code, 200)
        body = drawer.content.decode()
        self.assertIn(self.staff.user.name, body)
        self.assertIn("Mary Officer", body)
        self.assertNotIn("Outside Officer", body)
        self.assertIn("SSA Training · Leadership", body)

        saved = client.post(
            "/training-ceilings/set",
            {
                "staff_id": self.staff.id,
                "training_id": self.leadership.id,
                "fy": self.fy,
                "ceiling": "20",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(saved.status_code, 200)
        self.assertIn("/team-planning-oversight/?view=trainings", saved["HX-Redirect"])
        row = TrainingCeiling.objects.get()
        self.assertEqual(row.ceiling, 20)

        edited = client.post(
            f"/training-ceilings/{row.id}/edit",
            {"ceiling": "25"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(edited.status_code, 200)
        row.refresh_from_db()
        self.assertEqual(row.ceiling, 25)

        removed = client.post(
            f"/training-ceilings/{row.id}/remove", {}, HTTP_HX_REQUEST="true"
        )
        self.assertEqual(removed.status_code, 200)
        self.assertFalse(TrainingCeiling.objects.exists())

    def test_the_drawer_refuses_an_officer_outside_the_team(self):
        client = self.client_for(self.pl)

        response = client.post(
            "/training-ceilings/set",
            {
                "staff_id": self.other_staff.id,
                "training_id": self.leadership.id,
                "fy": self.fy,
                "ceiling": "20",
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("officers they supervise", response.content.decode())
        self.assertFalse(TrainingCeiling.objects.exists())

    def test_an_officer_cannot_open_the_ceiling_drawer(self):
        response = self.client_for(self.user).get("/training-ceilings/set")

        self.assertIn(response.status_code, (302, 403))
        self.assertFalse(TrainingCeiling.objects.exists())


class WhoSeesTheSummary(CeilingFixture):
    def setUp(self):
        super().setUp()
        self.ceiling(value=20)
        self.ceiling(staff=self.mary_staff, value=25)
        self.ceiling(staff=self.other_staff, value=9)
        self.group(self.members[:14])
        for offset, school in enumerate(self.members[20:24]):
            self.in_school(school, day=offset + 1)
        self.group(self.mary_members[:5], user=self.mary, cluster=self.mary_cluster)

    def test_the_lead_sees_every_officer_they_supervise(self):
        rows = training_ceilings.team_summary(
            training_ceilings.team_profiles(self.pl_staff.id), self.fy
        )

        self.assertEqual(
            [
                (
                    r.staff_name,
                    r.training_name,
                    r.ceiling,
                    r.group,
                    r.in_school,
                    r.total,
                    r.balance,
                    r.excess,
                )
                for r in rows
            ],
            [
                ("Mary Officer", "Leadership", 25, 5, 0, 5, 20, 0),
                ("Standard CCEO", "Leadership", 20, 14, 4, 18, 2, 0),
            ],
        )

    def test_an_officer_sees_only_their_own(self):
        rows = training_ceilings.own_summary(self.user, self.fy)

        self.assertEqual({r.staff_id for r in rows}, {self.staff.id})
        self.assertEqual([(r.ceiling, r.total) for r in rows], [(20, 18)])

    def test_the_summary_costs_the_same_queries_for_one_officer_or_many(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        team = training_ceilings.team_profiles(self.pl_staff.id)
        self.assertEqual(len(team), 2)
        with CaptureQueriesContext(connection) as many:
            rows = training_ceilings.team_summary(team, self.fy)
        with CaptureQueriesContext(connection) as one:
            training_ceilings.team_summary(team[:1], self.fy)

        self.assertEqual(len(rows), 2)
        # Ceilings, group schools, in-school trainings, the trainings a
        # Partner has taken on and the hand-overs still waiting for it,
        # training names, and the catalogue's intervention links when they
        # are not held in memory.
        self.assertLessEqual(len(many), 7)
        self.assertEqual(len(many), len(one))

    def summary_page(self, user, **query):
        return self.client_for(user).get(
            "/team-planning-oversight/", {"view": "trainings", "fy": self.fy, **query}
        )

    def test_the_lead_reads_their_officers_under_planning_oversight(self):
        response = self.summary_page(self.pl)

        self.assertEqual(response.status_code, 200)
        summary = response.context["training_summary"]
        # The Lead first, then the officers they supervise (owner,
        # 2026-10-06: "make sure they are included on the list").
        self.assertEqual(
            [column["name"] for column in summary.columns],
            ["Lead Lydia", "Mary Officer", "Standard CCEO"],
        )
        self.assertTrue(summary.may_set)
        body = response.content.decode()
        # The training, its mode of delivery, the country's three columns,
        # then one "# Schools" column per staff member.
        self.assertIn("Staff and the summary of all their planned trainings", body)
        for heading in (
            "Training Name",
            "Mode of delivery",
            "Total Covered<br>/ Country Ceiling",
            "Staff<br>Planned",
            "Awaiting<br>Partner",
            ">Remaining</th>",
            "# Schools<br>(Mary Officer)",
            "# Schools<br>(Standard CCEO)",
        ):
            self.assertIn(heading, body)
        self.assertNotIn("Outside Officer", body)
        # The capacity button is the lead's; the Country Ceiling is not.
        self.assertIn("data-set-training-ceiling", body)
        self.assertNotIn("data-set-country-ceiling", body)
        self.assertIn("Training Summary", body)

    def test_a_cell_is_the_schools_a_person_has_against_the_number_set(self):
        summary = self.summary_page(self.pl).context["training_summary"]

        row = next(r for r in summary.rows if r.training_id == self.leadership.id)
        self.assertEqual(row.kind, "training")
        self.assertEqual(row.name, "Leadership")
        cells = {cell.staff_id: cell for cell in row.cells}
        john, mary = cells[self.staff.id], cells[self.mary_staff.id]
        self.assertEqual(
            (john.schools, john.limit, john.group, john.in_school), (18, 20, 14, 4)
        )
        self.assertEqual((john.state, john.flag), ("below", "2 below ceiling"))
        self.assertEqual(
            (mary.schools, mary.limit, mary.flag), (5, 25, "20 below ceiling")
        )
        # Scheduled both ways, so both modes are named.
        self.assertIn("In-School Training", row.mode)
        self.assertIn("Group Training", row.mode)
        # A training nobody has planned is not on the table (owner,
        # 2026-10-06: "only appear once it has been planned").
        self.assertEqual([r.name for r in summary.rows], ["Leadership"])
        # The country's own figure: John's 18 and Mary's 5.
        self.assertEqual(
            (row.planned, row.country_ceiling, row.remaining), (23, None, None)
        )
        self.assertEqual(summary.flags, {"above": 0, "below": 2, "reached": 0})

    def test_the_country_readers_get_every_officer_and_set_no_officers_ceiling(self):
        readers = [
            self._person(f"summary-{role.lower()}@edify.org", f"Reader {role}", role)[0]
            for role in ("CountryDirector", "ImpactAssessment", "Admin")
        ]
        for reader in readers:
            with self.subTest(role=reader.active_role):
                response = self.summary_page(reader)

                self.assertEqual(response.status_code, 200)
                summary = response.context["training_summary"]
                names = [column["name"] for column in summary.columns]
                for name in ("Mary Officer", "Standard CCEO", "Outside Officer"):
                    self.assertIn(name, names)
                self.assertFalse(summary.may_set)
                body = response.content.decode()
                self.assertIn("# Schools<br>(Outside Officer)", body)
                # An officer's ceiling is the Programme Lead's: no capacity
                # button, and the save refuses them. The Country Ceiling is
                # Admin's and Impact Assessment's (TheCountryCeiling).
                self.assertNotIn("data-set-training-ceiling", body)
                self.assertEqual(
                    "data-set-country-ceiling" in body,
                    reader.active_role in ("Admin", "ImpactAssessment"),
                )
                with self.assertRaises(Forbidden):
                    training_ceilings.set_ceiling(
                        reader,
                        staff_id=self.staff.id,
                        training_id=self.leadership.id,
                        fy=self.fy,
                        ceiling="5",
                    )
                drawer = self.client_for(reader).get(
                    "/training-ceilings/set", HTTP_HX_REQUEST="true"
                )
                self.assertIn("data-ceiling-no-team", drawer.content.decode())
        self.assertEqual(
            TrainingCeiling.objects.get(
                staff=self.staff, training=self.leadership
            ).ceiling,
            20,
        )

    def test_a_country_reader_narrows_the_table_to_one_leads_team(self):
        cd = self._person("summary-cd2@edify.org", "Reader CD", "CountryDirector")[0]

        summary = self.summary_page(cd, program_lead=self.other_pl_staff.id).context[
            "training_summary"
        ]

        # The Lead's own column, then their officers' (owner, 2026-10-06:
        # the Leads are on the list).
        self.assertEqual(
            [c["name"] for c in summary.columns], ["Lead Lucas", "Outside Officer"]
        )
        self.assertEqual(summary.lead, self.other_pl_staff.id)
        self.assertEqual(
            {name for _id, name in summary.leads}, {"Lead Lydia", "Lead Lucas"}
        )

    def test_an_officer_has_no_planning_oversight_table(self):
        response = self.summary_page(self.user)

        self.assertIn(response.status_code, (302, 403))
        from apps.planning import training_summary

        with self.assertRaises(Forbidden):
            training_summary.for_reader(self.user, self.fy)
        # Their own table is their own column and nobody else's.
        own = training_summary.own(self.user, self.fy)
        self.assertEqual([c["id"] for c in own.columns], [self.staff.id])
        self.assertEqual([r.name for r in own.rows], ["Leadership"])

    def test_my_plan_shows_the_officer_their_own_summary_only(self):
        response = self.client_for(self.user).get(f"/my-plan?period=fy&fy={self.fy}")

        self.assertEqual(response.status_code, 200)
        rows = response.context["my_training_summary"]
        self.assertEqual({r.staff_id for r in rows}, {self.staff.id})
        body = response.content.decode()
        self.assertIn("My training summary", body)
        card = body.split('aria-labelledby="my-training-summary-title"', 1)[1].split(
            "</section>", 1
        )[0]
        self.assertIn("Leadership", card)
        self.assertIn("/training-summary/schools?staff=" + self.staff.id, card)
        self.assertNotIn(self.mary_staff.id, card)
        self.assertNotIn(self.other_staff.id, card)

    def test_each_figure_opens_the_schools_it_counts(self):
        result = training_ceilings.schools_behind(
            self.pl, staff_id=self.staff.id, training_id=self.leadership.id, fy=self.fy
        )

        self.assertEqual(len(result["rows"]), 18)
        by_route = {}
        for row in result["rows"]:
            by_route.setdefault(row.route_label, []).append(row)
        self.assertEqual(len(by_route["Group Training"]), 14)
        self.assertEqual(len(by_route["In-School · Staff"]), 4)
        self.assertEqual(
            {r.cluster for r in by_route["Group Training"]}, {"Standard Cluster"}
        )
        self.assertEqual({r.cluster for r in by_route["In-School · Staff"]}, {""})
        self.assertEqual(
            {r.school_pk for r in result["rows"]},
            {s.id for s in [*self.members[:14], *self.members[20:24]]},
        )

        group_only = training_ceilings.schools_behind(
            self.user,
            staff_id=self.staff.id,
            training_id=self.leadership.id,
            fy=self.fy,
            delivery="group",
        )
        self.assertEqual(len(group_only["rows"]), 14)

    def test_an_officer_cannot_open_another_officers_schools(self):
        with self.assertRaises(Forbidden):
            training_ceilings.schools_behind(
                self.user,
                staff_id=self.mary_staff.id,
                training_id=self.leadership.id,
                fy=self.fy,
            )
        with self.assertRaises(Forbidden):
            training_ceilings.schools_behind(
                self.pl,
                staff_id=self.other_staff.id,
                training_id=self.leadership.id,
                fy=self.fy,
            )

        url = (
            f"/training-summary/schools?staff={self.mary_staff.id}"
            f"&training={self.leadership.id}&fy={self.fy}"
        )
        refused = self.client_for(self.user).get(url, HTTP_HX_REQUEST="true")
        self.assertEqual(refused.status_code, 403)
        self.assertNotIn("School MARY", refused.content.decode())

        allowed = self.client_for(self.pl).get(url, HTTP_HX_REQUEST="true")
        self.assertEqual(allowed.status_code, 200)
        self.assertIn("School MARY-00", allowed.content.decode())

    def test_the_drawers_read_the_same_figure(self):
        client = self.client_for(self.user)

        own = client.get(
            "/planning/training-capacity",
            {"training": self.leadership.id, "date": _day().isoformat()},
        ).json()
        self.assertEqual(
            (own["managed"], own["ceiling"], own["scheduled"], own["remaining"]),
            (True, 20, 18, 2),
        )
        self.assertEqual((own["group"], own["inSchool"]), (14, 4))

        # An officer naming somebody else still reads their own.
        named = client.get(
            "/planning/training-capacity",
            {"training": self.leadership.id, "staff": self.mary_staff.id},
        ).json()
        self.assertEqual(named["scheduled"], 18)

        # The lead, choosing whose session it is, reads that officer's.
        led = (
            self.client_for(self.pl)
            .get(
                "/planning/training-capacity",
                {"training": self.leadership.id, "staff": self.mary_staff.id},
            )
            .json()
        )
        self.assertEqual((led["ceiling"], led["scheduled"]), (25, 5))


class ASchoolTakesOnePlace(CeilingFixture):
    """Owner, 2026-10-08: "look into capacity of schools set per training,
    some are blocking before hitting the ceiling."

    A ceiling is a number of schools, and a school was counted once for each
    session it was on. An officer who trained the same three schools twice
    had six places gone from a ceiling of five, and was refused with two
    schools' room unused. A school is one school, however many sessions of
    the training it is on and however they are delivered.
    """

    def capacity(self, **more):
        return training_ceilings.capacity(
            self.staff.id, self.leadership.id, self.fy, **more
        )

    def test_the_same_schools_on_a_second_session_fit_under_the_ceiling(self):
        self.ceiling(value=5)
        self.group(self.members[:3])

        # Refused before: three already scheduled and three more "selected".
        self.group(self.members[:3], day=1)

        capacity = self.capacity()
        self.assertEqual(
            (capacity["scheduled"], capacity["group"], capacity["remaining"]),
            (3, 3, 2),
        )

    def test_a_full_ceiling_still_takes_a_school_it_already_holds(self):
        self.ceiling(value=3)
        self.group(self.members[:3])

        self.group(self.members[1:3], day=1)
        self.in_school(self.members[0], day=2)

        self.assertEqual(self.capacity()["scheduled"], 3)
        self.assertEqual(self.capacity()["remaining"], 0)

    def test_a_new_school_is_still_refused_at_the_ceiling(self):
        self.ceiling(value=3)
        self.group(self.members[:3])

        with self.assertRaises(BadRequest) as refused:
            self.group([self.members[0], self.members[5]], day=1)

        message = str(refused.exception)
        self.assertIn("Training ceiling reached", message)
        self.assertIn("3 are already covered", message)
        self.assertIn("no more schools can be added", message)

    def test_only_the_new_schools_of_a_session_are_asked_for(self):
        self.ceiling(value=4)
        self.group(self.members[:3])
        # Two of these three are counted already; the third is the fourth.
        self.group(self.members[1:4], day=1)
        self.assertEqual(self.capacity()["scheduled"], 4)

        with self.assertRaises(BadRequest) as refused:
            # Two counted, two new, and no room for either new one.
            self.group(self.members[2:6], day=2)

        self.assertIn("4 are already covered", str(refused.exception))

    def test_the_refusal_names_the_new_schools_not_the_ticks(self):
        self.ceiling(value=4)
        self.group(self.members[:3])

        with self.assertRaises(BadRequest) as refused:
            # Three ticked: one counted already, two new, room for one.
            self.group(self.members[2:5], day=1)

        message = str(refused.exception)
        self.assertIn("only 1 more school can be added and 2 were selected", message)
        self.assertIn("Untick 1 and save again", message)

    def test_growing_a_session_into_schools_already_counted(self):
        self.ceiling(value=4)
        self.group(self.members[:4])
        second = self.group(self.members[:1], day=1)

        with self.captureOnCommitCallbacks(execute=True):
            editing.edit(
                second.id,
                {"invitedSchoolIds": [s.id for s in self.members[:4]]},
                self.user,
            )

        self.assertEqual(self.invited(second), {s.id for s in self.members[:4]})
        self.assertEqual(self.capacity()["scheduled"], 4)

    def test_the_drawer_is_told_which_schools_are_counted(self):
        self.ceiling(value=5)
        first = self.group(self.members[:3])
        second = self.group(self.members[2:4], day=1)

        capacity = self.capacity()
        self.assertEqual(capacity["schoolIds"], sorted(s.id for s in self.members[:4]))
        # The Edit drawer of one session: the other's schools, and only they.
        apart = self.capacity(exclude_activity_id=second.id)
        self.assertEqual(apart["schoolIds"], sorted(s.id for s in self.members[:3]))
        self.assertEqual((apart["scheduled"], apart["remaining"]), (3, 2))
        answer = (
            self.client_for(self.user)
            .get("/planning/training-capacity", {"activity": first.id})
            .json()
        )
        self.assertEqual(answer["schoolIds"], sorted(s.id for s in self.members[2:4]))

    def test_a_school_drawer_is_told_its_school_takes_no_place(self):
        self.ceiling(value=2)
        self.group(self.members[:2])
        client = self.client_for(self.user)

        def answer(school):
            return client.get(
                "/planning/training-capacity",
                {
                    "training": self.leadership.id,
                    "date": _day().isoformat(),
                    "school": school.school_id,
                },
            ).json()

        counted = answer(self.members[0])
        self.assertEqual((counted["remaining"], counted["counted"]), (0, True))
        self.assertEqual(answer(self.members[5])["counted"], False)
        # The Core Schools drawers name the school without changing whose
        # ceiling is read.
        core = client.get(
            "/planning/training-capacity",
            {
                "training": self.leadership.id,
                "date": _day().isoformat(),
                "for_school": self.members[1].school_id,
            },
        ).json()
        self.assertEqual((core["scheduled"], core["counted"]), (2, True))

    def test_the_schools_behind_a_figure_say_which_rows_repeat(self):
        self.group(self.members[:2])
        self.group(self.members[:2], day=1)

        result = training_ceilings.schools_behind(
            self.user,
            staff_id=self.staff.id,
            training_id=self.leadership.id,
            fy=self.fy,
        )

        self.assertEqual(len(result["rows"]), 4)
        self.assertEqual(result["school_count"], 2)
        self.assertEqual(
            [row.repeat for row in result["rows"]], [False, True, False, True]
        )
        self.assertEqual(result["summary"].total, 2)

    def test_the_summary_and_the_country_count_schools(self):
        from apps.planning import training_summary

        self.group(self.members[:3])
        self.group(self.members[:3], day=1)
        self.in_school(self.members[0], day=2)

        country = training_ceilings.country_scheduled(self.fy, "Uganda")
        self.assertEqual(
            country[self.leadership.id],
            {
                "group": 3,
                "in_school": 1,
                "partner": 0,
                "partner_scheduled": 0,
                "awaiting_partner": 0,
                "total": 3,
            },
        )
        row = next(
            r
            for r in training_summary.build([self.staff], self.fy, country="Uganda")
            if r.training_id == self.leadership.id
        )
        self.assertEqual((row.planned, row.cells[0].schools), (3, 3))

    def test_a_training_moved_onto_counts_its_schools_once(self):
        """The Edit drawer's Training field: the session's schools move
        under the new training's ceiling, where one is already counted."""
        self.ceiling(training=self.improvement, value=3)
        self.group(self.members[:3], code=IMPROVEMENT)
        session = self.group(self.members[2:4], day=1)

        with self.assertRaises(BadRequest):
            with self.captureOnCommitCallbacks(execute=True):
                editing.edit(
                    session.id, {"trainingCourseId": self.improvement.id}, self.user
                )
        with self.captureOnCommitCallbacks(execute=True):
            editing.edit(
                session.id,
                {
                    "trainingCourseId": self.improvement.id,
                    "invitedSchoolIds": [s.id for s in self.members[1:3]],
                },
                self.user,
            )

        self.assertEqual(self.counts(training=self.improvement)["total"], 3)


class ProjectTrainingsComeFromSpecialProjects(CeilingFixture):
    """Owner, 2026-10-06: "All training under project should be fetched from
    special project and their numbers added there based on how people have
    added the schools to projects." """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from apps.activity_catalogue.models import ActivityProjectMapping
        from apps.projects.models import (
            Project,
            ProjectSchoolAssignment,
            ProjectStaffCapacity,
        )

        cls.project = Project.objects.create(
            name="Summary Project",
            code="SP-SUMMARY",
            category="intervention_specific",
            status="active",
            intervention="leadership",
        )
        ActivityProjectMapping.objects.create(
            project=cls.project, catalogue_item=cls.item(cls, "TAM_I"), active=True
        )
        # John added three schools himself; an older row names him only as
        # the person who added it; Mary added one.
        for school in cls.members[:3]:
            ProjectSchoolAssignment.objects.create(
                project=cls.project, school=school, assigned_staff=cls.staff
            )
        ProjectSchoolAssignment.objects.create(
            project=cls.project, school=cls.members[3], assigned_by=cls.user.id
        )
        ProjectSchoolAssignment.objects.create(
            project=cls.project,
            school=cls.mary_members[0],
            assigned_staff=cls.mary_staff,
        )
        ProjectStaffCapacity.objects.create(
            project=cls.project, staff=cls.staff, max_schools=6
        )

    def rows(self, profiles):
        from apps.planning import training_summary

        return training_summary.build(profiles, self.fy, country="Uganda")

    def test_a_project_training_is_a_row_of_its_own_from_the_project(self):
        rows = self.rows([self.staff, self.mary_staff])

        row = next(r for r in rows if r.kind == "project")
        self.assertEqual(row.name, "Teaching as Mission (TAM) (Summary Project)")
        self.assertEqual(row.project_id, self.project.id)
        john, mary = row.cells
        # The schools each person added, beside the capacity set for them.
        self.assertEqual(
            (john.schools, john.limit, john.flag), (4, 6, "2 below capacity")
        )
        self.assertEqual(
            (mary.schools, mary.limit, mary.flag), (1, None, "No capacity set")
        )
        # Planned is every school on the project; a project has no Country
        # Ceiling here, its schools being its coordinator's to set.
        self.assertEqual(
            (row.planned, row.country_ceiling, row.remaining), (5, None, None)
        )
        self.assertEqual([r for r in rows if r.kind == "training"], [])

    def test_a_project_s_training_is_never_a_second_row(self):
        """Owner, 2026-10-08: "it is repeating the trainings that are already
        created as project. Can you read only project ... so that there are
        no repeated trainings." A session of the project's training scheduled
        from the Training Catalogue, with no project named, added a plain
        row for the same training above the project's."""
        session = self.group(self.members[6:8], code="TAM_I", day=2)
        self.assertFalse(session.project_id)

        rows = self.rows([self.staff, self.mary_staff])

        self.assertEqual(
            [(r.kind, r.name) for r in rows],
            [("project", "Teaching as Mission (TAM) (Summary Project)")],
        )
        # And the project row still reads the project: the schools added to
        # it, not the two the stray session invited.
        self.assertEqual(rows[0].planned, 5)
        self.assertEqual(rows[0].cells[0].schools, 4)

    def test_a_project_s_training_is_under_no_training_ceiling(self):
        """Its schools are the project's, against the capacity its
        coordinator set: a ceiling left on it from before it became a
        project's training holds nothing back, inside the project or out."""
        tam = self.item("TAM_I")
        self.ceiling(training=tam, value=1)
        session = self.group(self.members[:2], code="TAM_I", projectId=self.project.id)

        self.assertEqual(session.project_id, self.project.id)
        self.assertFalse(training_ceilings.under_ceiling(session))
        self.assertEqual(self.counts(training=tam)["total"], 0)
        # Scheduled with no project named, it is the project's all the same.
        stray = self.group(self.members[4:6], code="TAM_I", day=1)
        self.assertFalse(training_ceilings.under_ceiling(stray))
        self.assertEqual(self.counts(training=tam)["total"], 0)
        capacity = training_ceilings.capacity(self.staff.id, tam.id, self.fy)
        self.assertFalse(capacity["managed"])
        self.assertEqual(capacity["project"], "Summary Project")
        # The officer's own summary does not list it as a training either.
        self.assertEqual(training_ceilings.own_summary(self.user, self.fy), [])

    def test_no_ceiling_is_set_for_a_project_s_training(self):
        tam = self.item("TAM_I")

        self.assertNotIn(
            tam.id, [option["id"] for option in training_ceilings.training_options()]
        )
        self.assertIn(
            self.leadership.id,
            [option["id"] for option in training_ceilings.training_options()],
        )
        with self.assertRaises(BadRequest) as refused:
            training_ceilings.set_ceiling(
                self.pl,
                staff_id=self.staff.id,
                training_id=tam.id,
                fy=self.fy,
                ceiling="5",
            )
        self.assertIn("Summary Project", str(refused.exception))
        self.assertFalse(TrainingCeiling.objects.filter(training=tam).exists())

    def test_a_training_no_live_project_delivers_is_a_training_again(self):
        """Read from the project only while a live project delivers it."""
        from apps.activity_catalogue.models import ActivityProjectMapping

        self.group(self.members[6:8], code="TAM_I", day=2)
        ActivityProjectMapping.objects.filter(project=self.project).update(active=False)

        rows = self.rows([self.staff])

        self.assertEqual(
            [(r.kind, r.name, r.planned) for r in rows],
            [("training", "Teaching as Mission (TAM)", 2)],
        )

    def test_an_officers_own_table_carries_their_project_trainings(self):
        from apps.planning import training_summary

        own = training_summary.own(self.user, self.fy)

        self.assertEqual(
            [(r.kind, r.name) for r in own.rows],
            [("project", "Teaching as Mission (TAM) (Summary Project)")],
        )
        self.assertEqual(own.rows[0].cells[0].schools, 4)

    def test_the_table_links_a_project_number_to_the_projects_schools(self):
        body = (
            self.client_for(self.pl)
            .get(
                f"/team-planning-oversight/?view=trainings&fy={self.fy}",
                HTTP_HX_REQUEST="true",
            )
            .content.decode()
        )

        self.assertIn('data-summary-row="project"', body)
        self.assertIn(f'href="/projects/monitoring?project={self.project.id}"', body)
        self.assertIn("4 / 6", body)


class TheSummaryListsOnlyWhatIsPlanned(CeilingFixture):
    """Owner, 2026-10-06: "I want all trainings hidden from the summary table
    and only appear once it has been planned either through group training,
    in-school training or cluster meeting." """

    def names(self, profiles=None):
        from apps.planning import training_summary

        rows = training_summary.build(
            profiles or [self.staff, self.mary_staff], self.fy, country="Uganda"
        )
        return [row.name for row in rows if row.kind == "training"]

    def test_nothing_is_listed_until_a_school_is_planned(self):
        # Ceilings alone do not put a training on the table.
        self.ceiling(value=20)
        TrainingCountryCeiling.objects.create(
            training=self.leadership, fy=self.fy, country="Uganda", ceiling=100
        )

        self.assertEqual(self.names(), [])

    def test_a_group_training_lists_it(self):
        self.group(self.members[:3])

        self.assertEqual(self.names(), ["Leadership"])

    def test_an_in_school_training_lists_it(self):
        self.in_school(self.members[0], code=IMPROVEMENT)

        self.assertEqual(self.names(), ["SSA Training"])

    def test_a_cluster_meeting_that_is_a_training_lists_it(self):
        self.meeting(self.members[:4], kind=MeetingKind.TRAINING, course=LEADERSHIP)

        self.assertEqual(self.names(), ["Leadership"])

    def test_a_meeting_that_is_only_a_meeting_lists_nothing(self):
        self.meeting(self.members[:4], kind=MeetingKind.ONLY_MEETING)

        self.assertEqual(self.names(), [])

    def test_a_cancelled_plan_takes_it_off_again(self):
        session = self.group(self.members[:3])
        Activity.objects.filter(id=session.id).update(status="cancelled")

        self.assertEqual(self.names(), [])

    def test_it_is_listed_for_every_reader_once_anyone_has_planned_it(self):
        """The country's columns are the country's: a lead whose own officers
        have not planned it still reads what the country has."""
        self.group(self.mary_members[:2], user=self.mary, cluster=self.mary_cluster)

        self.assertEqual(self.names([self.other_staff]), ["Leadership"])

    def test_the_page_says_so_when_nothing_is_planned(self):
        body = (
            self.client_for(self.pl)
            .get("/team-planning-oversight/", {"view": "trainings", "fy": self.fy})
            .content.decode()
        )

        self.assertIn("No training has been planned yet this year.", body)
        self.assertNotIn('data-summary-row="training"', body)


class TheCountryCeiling(CeilingFixture):
    """Owner, 2026-10-06: "The admin IA will set the Country Ceiling and
    Leads will set each staff ceiling. The country ceiling will have COuntry
    Ceiling column, Planned column, Remaining column then the rest of the
    staff columns with their #schools"."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = cls._person("ceiling-admin@edify.org", "Ada Admin", "Admin")[0]
        cls.ia = cls._person(
            "ceiling-ia@edify.org", "Ian Assessor", "ImpactAssessment"
        )[0]
        cls.cd = cls._person(
            "ceiling-cd@edify.org", "Dora Director", "CountryDirector"
        )[0]

    def setUp(self):
        super().setUp()
        self.group(self.members[:14])
        self.group(self.mary_members[:5], user=self.mary, cluster=self.mary_cluster)
        self.in_school(self.members[20])

    def country(self, principal, ceiling="30", training=None, **more):
        return training_ceilings.set_country_ceiling(
            principal,
            training_id=(training or self.leadership).id,
            fy=self.fy,
            ceiling=ceiling,
            **more,
        )

    def row(self, profiles=None):
        from apps.planning import training_summary

        rows = training_summary.build(
            profiles or [self.staff, self.mary_staff], self.fy, country="Uganda"
        )
        return next(r for r in rows if r.training_id == self.leadership.id)

    def page(self, user):
        return self.client_for(user).get(
            "/team-planning-oversight/", {"view": "trainings", "fy": self.fy}
        )

    # ── The three country columns ──────────────────────────────────────────
    def test_planned_is_every_school_the_country_has_planned(self):
        row = self.row()

        # 14 and 5 invited to group trainings, 1 in-school training.
        self.assertEqual(row.planned, 20)
        self.assertEqual([cell.schools for cell in row.cells], [15, 5])
        self.assertEqual(
            training_ceilings.country_scheduled(self.fy, "Uganda")[self.leadership.id],
            {
                "group": 19,
                "in_school": 1,
                "partner": 0,
                "partner_scheduled": 0,
                "awaiting_partner": 0,
                "total": 20,
            },
        )

    def test_planned_is_the_same_whoever_reads_it(self):
        """A lead's columns are their officers; Planned is still the
        country's, schools planned by another lead's officer included."""
        self.in_school(
            self.second_members[0], user=self.other, staff=self.other_staff, day=3
        )
        StaffSchoolAssignment.objects.get_or_create(
            staff=self.other_staff, school_id=self.second_members[0].id
        )

        self.assertEqual(self.row([self.staff, self.mary_staff]).planned, 21)
        self.assertEqual(self.row([self.other_staff]).planned, 21)

    def test_with_no_ceiling_there_is_nothing_remaining_to_read(self):
        row = self.row()

        self.assertIsNone(row.country_ceiling)
        self.assertIsNone(row.remaining)
        self.assertEqual(
            (row.country_state, row.country_flag), ("unset", "No Country Ceiling set")
        )

    def test_remaining_is_the_ceiling_less_what_is_planned(self):
        self.country(self.admin, "30")

        row = self.row()

        self.assertEqual(
            (row.country_ceiling, row.planned, row.remaining), (30, 20, 10)
        )
        self.assertEqual(
            (row.country_state, row.country_flag),
            ("below", "10 remaining under the Country Ceiling"),
        )

    def test_remaining_is_never_below_zero(self):
        self.country(self.admin, "12")

        row = self.row()

        self.assertEqual((row.remaining, row.over), (0, 8))
        self.assertEqual(
            (row.country_state, row.country_tone, row.country_flag),
            ("above", "danger", "8 above the Country Ceiling"),
        )

    def test_at_the_ceiling(self):
        self.country(self.admin, "20")

        row = self.row()

        self.assertEqual(
            (row.remaining, row.over, row.country_state), (0, 0, "reached")
        )

    def test_each_year_and_each_training_has_its_own(self):
        self.country(self.admin, "30")
        self.country(self.admin, "7", training=self.improvement)

        self.assertEqual(self.row().country_ceiling, 30)
        self.assertEqual(
            training_ceilings.country_ceilings(self.fy, "Uganda")[self.improvement.id][
                "ceiling"
            ],
            7,
        )
        self.assertEqual(
            training_ceilings.country_ceilings(str(int(self.fy) + 1), "Uganda"), {}
        )

    # ── Who sets it ────────────────────────────────────────────────────────
    def test_admin_and_impact_assessment_set_it(self):
        first = self.country(self.admin, "30")
        second = self.country(self.ia, "45")

        self.assertEqual(first.id, second.id)
        row = TrainingCountryCeiling.objects.get(training=self.leadership, fy=self.fy)
        self.assertEqual((row.ceiling, row.country), (45, "Uganda"))
        self.assertEqual(row.set_by_role, "ImpactAssessment")
        logged = list(
            AuditLog.objects.filter(action="training_country_ceiling.set").order_by(
                "created_at"
            )
        )
        self.assertEqual(
            [(e.payload["from"], e.payload["to"]) for e in logged],
            [(None, 30), (30, 45)],
        )
        self.assertEqual(logged[-1].payload["training"], "Leadership")

    def test_nobody_else_sets_it(self):
        for principal in (self.cd, self.pl, self.user):
            with self.subTest(role=principal.active_role):
                with self.assertRaisesMessage(
                    Forbidden, "Admin and Impact Assessment set the Country Ceiling."
                ):
                    self.country(principal, "30")
        self.assertFalse(TrainingCountryCeiling.objects.exists())

    def test_a_lead_still_sets_each_officers_ceiling_and_they_do_not(self):
        training_ceilings.set_ceiling(
            self.pl,
            staff_id=self.staff.id,
            training_id=self.leadership.id,
            fy=self.fy,
            ceiling="20",
        )
        for principal in (self.admin, self.ia, self.cd):
            with self.subTest(role=principal.active_role):
                with self.assertRaises(Forbidden):
                    training_ceilings.set_ceiling(
                        principal,
                        staff_id=self.staff.id,
                        training_id=self.leadership.id,
                        fy=self.fy,
                        ceiling="5",
                    )
        self.assertEqual(TrainingCeiling.objects.get(staff=self.staff).ceiling, 20)

    def test_it_is_a_whole_number_of_schools_for_a_real_training(self):
        for bad in ("", "0", "-3", "ten", "2.5"):
            with self.subTest(ceiling=bad):
                with self.assertRaises(BadRequest):
                    self.country(self.admin, bad)
        with self.assertRaises(BadRequest):
            training_ceilings.set_country_ceiling(
                self.admin, training_id="nope", fy=self.fy, ceiling="5"
            )
        with self.assertRaises(BadRequest):
            training_ceilings.set_country_ceiling(
                self.admin, training_id=self.leadership.id, fy="1999", ceiling="5"
            )
        self.assertFalse(TrainingCountryCeiling.objects.exists())

    def test_removing_it_is_logged_and_touches_no_plan(self):
        row = self.country(self.admin, "30")

        with self.assertRaises(Forbidden):
            training_ceilings.remove_country_ceiling(self.cd, row.id)
        detail = training_ceilings.remove_country_ceiling(self.ia, row.id)

        self.assertEqual((detail["from"], detail["to"]), (30, None))
        self.assertFalse(TrainingCountryCeiling.objects.exists())
        self.assertTrue(
            AuditLog.objects.filter(action="training_country_ceiling.removed").exists()
        )
        self.assertEqual(self.row().planned, 20)

    def test_it_is_read_against_and_holds_no_schedule_back(self):
        """An officer's own ceiling is what refuses a save. The country's is
        the number the plans are read against."""
        self.country(self.admin, "5")

        self.group(self.second_members[:3], cluster=self.second_cluster, day=2)

        row = self.row()
        self.assertEqual((row.planned, row.remaining, row.over), (23, 0, 18))

    # ── On the page ────────────────────────────────────────────────────────
    def test_the_table_carries_the_three_country_columns_then_the_staff(self):
        self.country(self.admin, "30")

        body = self.page(self.pl).content.decode()

        headings = [
            "Training Name",
            "Mode of delivery",
            "Total Covered<br>/ Country Ceiling",
            "Staff<br>Planned",
            "Awaiting<br>Partner",
            ">Remaining</th>",
            "# Schools<br>(Mary Officer)",
            "# Schools<br>(Standard CCEO)",
        ]
        places = [body.index(heading) for heading in headings]
        self.assertEqual(places, sorted(places))
        self.assertNotIn("Country Target", body)
        # Owner, 2026-10-09: "get rid of group scheduled, and replace country
        # ceiling with total covered out of the set ceiling".
        self.assertNotIn("Group<br>Scheduled", body)
        # "partner assigned and awaiting partner schedule are duplicate
        # remove one column and leave one": Awaiting Partner stays.
        self.assertNotIn("Partner<br>Assigned", body)
        self.assertNotIn("Country<br>Ceiling", body)
        row = body.split('data-summary-row="training"', 1)[1].split("</tr>", 1)[0]
        for cell, value in (
            ("data-country-ceiling", "30"),
            ("data-country-planned", "20"),
            ("data-country-remaining", "10"),
        ):
            self.assertRegex(row, rf"{cell}>(?:<[^>]+>)*{value}<")
        # "23/1000": the schools covered, then the ceiling, in one cell.
        cell = row.split("data-country-planned", 1)[1].split("</td>", 1)[0]
        self.assertRegex(cell, r"20</strong></span>\s*/ <span data-country-ceiling>30<")

    def test_admin_and_impact_assessment_are_offered_it_on_the_page(self):
        for principal in (self.admin, self.ia):
            with self.subTest(role=principal.active_role):
                response = self.page(principal)

                self.assertEqual(response.status_code, 200)
                body = response.content.decode()
                self.assertIn("data-set-country-ceiling", body)
                self.assertIn("+ Set Country Ceiling", body)
                # An officer's ceiling is still not theirs to set.
                self.assertNotIn("data-set-training-ceiling", body)
                # With none set, the cell offers to set it for that training.
                self.assertIn(
                    f"/training-ceilings/country/set?training={self.leadership.id}",
                    body,
                )

    def test_the_cell_opens_the_ceiling_once_it_is_set(self):
        row = self.country(self.admin, "30")

        body = self.page(self.ia).content.decode()

        self.assertIn(f'hx-get="/training-ceilings/country/{row.id}/edit"', body)

    def test_the_country_director_and_a_lead_read_it(self):
        row = self.country(self.admin, "30")

        for principal in (self.cd, self.pl):
            with self.subTest(role=principal.active_role):
                body = self.page(principal).content.decode()

                self.assertNotIn("data-set-country-ceiling", body)
                self.assertNotIn("/training-ceilings/country/", body)
                self.assertRegex(body, r"data-country-ceiling>30<")
                drawer = self.client_for(principal).get(
                    "/training-ceilings/country/set", HTTP_HX_REQUEST="true"
                )
                self.assertIn("data-country-ceiling-read-only", drawer.content.decode())
                refused = self.client_for(principal).post(
                    "/training-ceilings/country/set",
                    {"training_id": self.leadership.id, "fy": self.fy, "ceiling": "99"},
                    HTTP_HX_REQUEST="true",
                )
                self.assertEqual(refused.status_code, 403)
                self.assertEqual(
                    self.client_for(principal)
                    .post(
                        f"/training-ceilings/country/{row.id}/edit",
                        {"ceiling": "99"},
                        HTTP_HX_REQUEST="true",
                    )
                    .status_code,
                    404,
                )
        self.assertEqual(TrainingCountryCeiling.objects.get().ceiling, 30)

    def test_an_officer_does_not_reach_the_drawer(self):
        response = self.client_for(self.user).get("/training-ceilings/country/set")

        self.assertIn(response.status_code, (302, 403))

    def test_the_drawer_shows_what_is_planned_and_saves(self):
        client = self.client_for(self.admin)

        opened = client.get(
            "/training-ceilings/country/set",
            {"training": self.leadership.id, "fy": self.fy},
            HTTP_HX_REQUEST="true",
        )
        body = opened.content.decode()
        self.assertIn("Set Country Ceiling", body)
        self.assertIn("data-country-ceiling-current", body)
        self.assertIn(
            "<strong>20</strong> (1 staff planned, 0 assigned to a partner, "
            "19 group scheduled)",
            body,
        )
        self.assertIn("Not set", body)

        saved = client.post(
            "/training-ceilings/country/set",
            {"training_id": self.leadership.id, "fy": self.fy, "ceiling": "30"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(
            saved["HX-Redirect"],
            f"/team-planning-oversight/?view=trainings&fy={self.fy}",
        )
        row = TrainingCountryCeiling.objects.get()
        self.assertEqual(row.ceiling, 30)

        edited = client.post(
            f"/training-ceilings/country/{row.id}/edit",
            {"ceiling": "40"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(edited.status_code, 200)
        row.refresh_from_db()
        self.assertEqual(row.ceiling, 40)

        asked = client.get(
            f"/training-ceilings/country/{row.id}/remove", HTTP_HX_REQUEST="true"
        )
        self.assertIn("Remove Country Ceiling", asked.content.decode())
        removed = client.post(
            f"/training-ceilings/country/{row.id}/remove", HTTP_HX_REQUEST="true"
        )
        self.assertEqual(removed.status_code, 200)
        self.assertFalse(TrainingCountryCeiling.objects.exists())

    def test_a_refused_save_says_why_in_the_drawer(self):
        response = self.client_for(self.admin).post(
            "/training-ceilings/country/set",
            {"training_id": self.leadership.id, "fy": self.fy, "ceiling": "0"},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "The Country Ceiling is at least 1 school.", response.content.decode()
        )
        self.assertNotIn("HX-Redirect", response)


# ── Cluster meetings ────────────────────────────────────────────────────────
class ClusterMeetingTypes(CeilingFixture):
    def test_only_meeting_asks_for_no_training_and_takes_no_place(self):
        self.ceiling(value=2)

        meeting = self.meeting(self.members[:6], kind=MeetingKind.ONLY_MEETING)

        self.assertEqual(meeting.activity_type, "cluster_meeting")
        self.assertEqual(meeting.meeting_kind, "only_meeting")
        self.assertIsNone(meeting.training_course_id)
        self.assertFalse(training_ceilings.is_training(meeting))
        self.assertEqual(self.counts()["total"], 0)

    def test_a_cluster_leaders_meeting_is_its_own_type_and_takes_no_place(self):
        self.ceiling(value=2)

        meeting = self.meeting(self.members[:6], kind=MeetingKind.CLUSTER_LEADERS)

        self.assertEqual(meeting.activity_type, "cluster_meeting")
        self.assertEqual(meeting.get_meeting_kind_display(), "Cluster Leaders Meeting")
        self.assertIsNone(training_ceilings.delivery_of(meeting))
        self.assertEqual(self.counts()["total"], 0)

    def test_a_course_sent_with_a_meeting_that_is_not_a_training_is_ignored(self):
        meeting = self.meeting(
            self.members[:3], kind=MeetingKind.ONLY_MEETING, course=LEADERSHIP
        )

        self.assertIsNone(meeting.training_course_id)
        self.assertEqual(self.counts()["total"], 0)

    def test_a_training_meeting_names_its_training_and_takes_its_intervention(self):
        meeting = self.meeting(
            self.members[:4],
            kind=MeetingKind.TRAINING,
            course=IMPROVEMENT,
            focusIntervention=SsaIntervention.FINANCIAL_HEALTH,
        )

        self.assertEqual(meeting.activity_type, "cluster_meeting")
        self.assertEqual(meeting.training_course_id, self.improvement.id)
        self.assertEqual(meeting.focus_intervention, SsaIntervention.LEADERSHIP)
        # It stays a cluster meeting everywhere a meeting is read.
        self.assertEqual(meeting.catalogue_item.stable_code, "STANDARD_CLUSTER_MEETING")
        self.assertEqual(
            self.counts(training=self.improvement),
            {"group": 4, "in_school": 0, "total": 4},
        )

    def test_a_training_meeting_is_held_to_the_ceiling(self):
        self.ceiling(training=self.improvement, value=3)

        with self.assertRaises(BadRequest):
            self.meeting(
                self.members[:4], kind=MeetingKind.TRAINING, course=IMPROVEMENT
            )
        self.meeting(self.members[:3], kind=MeetingKind.TRAINING, course=IMPROVEMENT)

    def test_a_training_meeting_without_a_training_is_refused(self):
        with self.assertRaises(BadRequest):
            self.meeting(self.members[:2], kind=MeetingKind.TRAINING)
        with self.assertRaises(BadRequest):
            self.meeting(self.members[:2], kind="workshop")

    def test_a_meeting_planned_without_a_type_is_still_a_meeting(self):
        meeting = self.meeting(self.members[:2])

        self.assertEqual(meeting.meeting_kind, "")
        self.assertEqual(self.counts()["total"], 0)

    def test_the_drawer_offers_the_three_types_and_the_conditional_training(self):
        body = (
            self.client_for(self.user)
            .get(
                f"/planning/schedule-modal?cluster_id={self.cluster.id}&action=meeting",
                HTTP_HX_REQUEST="true",
            )
            .content.decode()
        )

        self.assertIn('name="meeting_kind"', body)
        for label in ("Training", "Only Meeting", "Cluster Leaders Meeting"):
            self.assertIn(f">{label}</option>", body)
        # The training is asked for only by a Training meeting, under a name
        # that cannot be mistaken for the meeting's own catalogue item.
        self.assertIn("""<template x-if="meetingKind === 'training'">""", body)
        self.assertIn('name="training_course_id"', body)
        self.assertNotIn('name="catalogue_item_id"', body)
        self.assertIn("SSA Training", body)

    def test_the_drawers_post_saves_each_type(self):
        client = self.client_for(self.user)

        def post(day, **extra):
            return client.post(
                "/planning/schedule-action",
                {
                    "cluster_id": self.cluster.id,
                    "activity_type": "cluster_meeting",
                    "purpose_type": "operational_admin",
                    "scheduled_date": _day(day).isoformat(),
                    "leaders_per_school": "2",
                    "invited_school_ids": [s.id for s in self.members[:3]],
                    "delivery_type": "staff",
                    **extra,
                },
                HTTP_HX_REQUEST="true",
            )

        self.assertEqual(post(0, meeting_kind="only_meeting").status_code, 200)
        self.assertEqual(post(1, meeting_kind="cluster_leaders").status_code, 200)
        missing = post(2, meeting_kind="training")
        self.assertEqual(missing.status_code, 400)
        self.assertIn("Select the Training", missing.content.decode())
        self.assertEqual(
            post(
                2,
                meeting_kind="training",
                training_course_id=self.improvement.id,
                focus_intervention=SsaIntervention.ENROLMENT,
            ).status_code,
            200,
        )

        kinds = {
            a.meeting_kind: a
            for a in Activity.objects.filter(activity_type="cluster_meeting")
        }
        self.assertEqual(set(kinds), {"only_meeting", "cluster_leaders", "training"})
        self.assertEqual(kinds["training"].training_course_id, self.improvement.id)
        self.assertEqual(
            kinds["training"].focus_intervention, SsaIntervention.LEADERSHIP
        )
        self.assertEqual(self.counts(training=self.improvement)["group"], 3)


# ── The drawers ─────────────────────────────────────────────────────────────
class TheSchedulingDrawers(CeilingFixture):
    def group_drawer(self, **query) -> str:
        params = {"cluster_id": self.cluster.id, "action": "training", **query}
        response = self.client_for(self.user).get(
            "/planning/schedule-modal", params, HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_the_group_training_drawer_asks_for_the_training_first(self):
        body = self.group_drawer(pick="1")

        training = body.index('id="training_activity"')
        self.assertLess(training, body.index("data-training-ssa-intervention"))
        self.assertLess(
            body.index("data-training-ssa-intervention"),
            body.index('id="cluster-picker"'),
        )
        self.assertLess(
            body.index('id="cluster-picker"'), body.index('name="scheduled_date"')
        )
        self.assertLess(
            body.index('name="scheduled_date"'), body.index('name="invited_school_ids"')
        )
        self.assertIn('name="catalogue_item_id"', body)
        self.assertIn("SSA Training", body)

    def test_its_intervention_is_read_only_and_comes_from_the_training(self):
        body = self.group_drawer()

        self.assertIn("readonly data-linked-intervention", body)
        # Nothing is posted for it: the save reads the catalogue.
        self.assertNotIn('type="hidden" name="focus_intervention"', body)
        self.assertIn("It cannot be changed here.", body)
        # The list of interventions is drawn only for a training the catalogue
        # leaves open to any of them.
        self.assertIn(
            '<template x-if="selectedActivity && selectedActivity.plannerChooses">',
            body,
        )
        options = json.loads(
            body.split("activities: ", 1)[1]
            .split(",\n  activityId", 1)[0]
            .replace("&quot;", '"')
        )
        row = next(o for o in options if o["stableCode"] == IMPROVEMENT)
        self.assertEqual(row["ssaInterventionLabel"], "Leadership")

    def test_changing_the_cluster_keeps_the_training_already_chosen(self):
        body = self.group_drawer(pick="1", catalogue_item_id=self.improvement.id)

        self.assertIn(f"activityId: '{self.improvement.id}'", body)
        self.assertIn(
            'hx-include="#training_activity, #meeting_kind, #meeting_training_course"',
            body,
        )

    def test_the_school_list_is_greyed_at_the_ceiling(self):
        body = self.group_drawer()

        self.assertIn("data-training-ceiling-counter", body)
        self.assertIn(':disabled="isHeld($el)"', body)
        self.assertIn("/planning/training-capacity?", body)

    def test_the_in_school_drawer_asks_for_the_training_before_the_date(self):
        response = self.client_for(self.user).get(
            f"/planning/schedule-modal?school_id={self.school.school_id}",
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertLess(
            body.index('id="training_activity_id"'), body.index('id="scheduled_date"')
        )
        self.assertIn("data-training-ssa-intervention", body)
        self.assertIn("SSA Training", body)
        # One school, the drawer's own: no group school list is forced on it.
        self.assertNotIn('name="invited_school_ids"', body)
        # Schedule is held at the ceiling, and for a training the school has
        # no room for (apps.planning.test_training_entitlement).
        self.assertIn(
            ':disabled="followUpBlocked || trainingBlocked || trainingCeilingFull"',
            body,
        )


class NothingHereIsCalledAllocated(CeilingFixture):
    """ "Allocated" keeps its meaning — a school assigned to a partner or a
    project — and no training surface borrows the word."""

    def test_the_training_surfaces_never_say_allocated(self):
        self.ceiling(value=20)
        self.group(self.members[:3])
        pages = [
            self.client_for(self.pl).get(
                f"/team-planning-oversight/?view=trainings&fy={self.fy}",
                HTTP_HX_REQUEST="true",
            ),
            self.client_for(self.pl).get(
                "/training-ceilings/set", HTTP_HX_REQUEST="true"
            ),
            self.client_for(self.pl).get(
                f"/training-summary/schools?staff={self.staff.id}"
                f"&training={self.leadership.id}&fy={self.fy}",
                HTTP_HX_REQUEST="true",
            ),
        ]
        for response in pages:
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("llocat", response.content.decode().lower())

    def test_a_ceiling_touches_no_partner_or_project_record(self):
        from apps.partners.models import PartnerAssignment
        from apps.projects.models import ProjectSchoolAssignment, ProjectStaffCapacity

        before = (
            PartnerAssignment.objects.count(),
            ProjectSchoolAssignment.objects.count(),
            ProjectStaffCapacity.objects.count(),
        )

        training_ceilings.set_ceiling(
            self.pl,
            staff_id=self.staff.id,
            training_id=self.leadership.id,
            fy=self.fy,
            ceiling="20",
        )
        self.group(self.members[:5])

        self.assertEqual(
            before,
            (
                PartnerAssignment.objects.count(),
                ProjectSchoolAssignment.objects.count(),
                ProjectStaffCapacity.objects.count(),
            ),
        )
