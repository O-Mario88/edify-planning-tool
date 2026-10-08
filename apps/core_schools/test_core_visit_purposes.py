"""Core School visits by purpose, trainings from the whole catalogue (owner, 2026-09-15).

* The Core visit drawer asks for a Purpose of Visit (In-school Training,
  Training Follow Up, SSA Support, Donor Visit, …) instead of offering only a
  focus-intervention visit.
* The first Core visit of the fiscal year is SSA Support, linked to data
  collection.
* In-school Training chosen in the visit drawer creates the Core training and
  its companion school visit together, as at a client school.
* Core trainings choose from every training in the catalogue.
* A Training Follow Up names the training followed up, from the trainings the
  school did (at the school, or cluster sessions it attended).
* A cluster training or meeting the school was invited to and attended counts
  as one of its Core trainings.
* A partner handoff is chosen by the same purpose; for In-school Training
  staff choose the course and the partner only dates it.
"""

from __future__ import annotations

import json

from datetime import timedelta

from django.utils import timezone

from django.test import TestCase

from apps.activities.models import Activity, ClusterActivityAttendance
from apps.activity_catalogue.availability import in_school_training_course_options
from apps.activity_catalogue.models import ActivityCatalogueItem
from apps.core_schools.core_planning_services import CorePackageSchedulingService
from apps.core_schools.models import CoreActivitySlot, CorePlan, cslot_id
from apps.core_schools import test_core_planning as _planning
from apps.partners.models import Partner, PartnerAssignment


def _today():
    """The platform's date, read when a test runs rather than when the module
    is imported. A module-level constant went stale when the suite ran across
    midnight in Africa/Nairobi, and the scheduling rules then refused every
    "today" as a day that had passed. Sundays take no scheduling, so a run on a
    Sunday plans for the Monday (every test here failed on 2026-09-27)."""
    day = timezone.localdate()
    while day.weekday() == 6:
        day += timedelta(days=1)
    return day


class _CoreFixture(TestCase):
    """The Core planning fixture, without re-running that module's tests."""

    # Borrowed from the module, not imported as a class: an imported TestCase
    # would be collected here and its 45 tests run twice.
    # The plain fixture function, not the class attribute: that one is
    # freezegun's wrapper (CoreSchoolsPlanningTest freezes its clock so its
    # staff slots fall in the current quarter), and borrowing it alone starts
    # that clock without the tearDown that stops it — silently moving "today"
    # for every test here and in the module that subclasses this fixture.
    setUp = _planning.core_planning_setup
    _staff = _planning.CoreSchoolsPlanningTest._staff
    _school = _planning.CoreSchoolsPlanningTest._school
    _plan = _planning.CoreSchoolsPlanningTest._plan
    _client = _planning.CoreSchoolsPlanningTest._client

    def _slot(self, kind, seq):
        return CoreActivitySlot.objects.get(
            id=cslot_id(self.school.school_id, kind, seq, fy=self.plan.fy)
        )

    def _take_first_visit(self):
        """Stand in for an SSA Support visit already on the calendar."""
        CoreActivitySlot.objects.filter(id=self._slot("v", 1).id).update(
            status="Scheduled"
        )

    def _post_visit(self, **fields):
        payload = {
            "school_id": self.school.school_id,
            "visit_number": "1",
            "scheduled_date": _today().isoformat(),
            "responsible_staff_id": self.cceo_sp.id,
            **fields,
        }
        return self._client(self.cceo).post(
            "/core-schools/schedule-visit/action", payload
        )

    def _completed_in_school_training(self, course, intervention="leadership"):
        return Activity.objects.create(
            activity_type="in_school_training",
            training_course=course,
            activity_name_snapshot=course.display_name,
            school=self.school,
            fy=self.plan.fy,
            status="ia_verified",
            planned_date=_today(),
            focus_intervention=intervention,
            responsible_staff_id=self.cceo_sp.id,
        )


class CoreVisitPurposeTest(_CoreFixture):
    def test_the_first_visit_drawer_offers_every_purpose(self):
        """The first visit of a package no longer has to be SSA Support.

        It did until 2026-09-17, when the owner asked for the package rules
        to come off: "Lift all FY restriction and package restrictions. Only
        block staff visit schedule after 2 scheduling and block partner
        assignment and schedule after 2 assignment and scheduling." The rule
        also reached further than its own name — a Core TRAINING could not be
        scheduled at all until a VISIT slot was taken — which is how it came
        to the owner's attention.
        """
        html = (
            self._client(self.cceo)
            .get(f"/core-schools/schedule-visit?school_id={self.school.school_id}")
            .content.decode()
        )
        self.assertNotIn("data-core-first-visit", html)
        for value in ("ssa_support", "donor_visit", "in_school_training"):
            self.assertIn(f'value="{value}"', html)

    def test_the_first_visit_may_be_any_purpose(self):
        """A donor visit is booked as itself and takes no package slot (owner,
        2026-09-30: donor, story, invitation and social visits are not package
        work)."""
        response = self._post_visit(purpose_of_visit="donor_visit")
        self.assertEqual(response.status_code, 200, response.content[:300])
        visit = Activity.objects.get(school=self.school, activity_type="donor_visit")
        self.assertEqual(visit.purpose_type, "donor_visit")
        self.assertFalse(CoreActivitySlot.objects.filter(activity_id=visit.id))
        self.assertIsNone(self._slot("v", 1).activity_id)

    def test_ssa_support_still_collects_the_ssa_when_it_is_chosen(self):
        """Data collection is booked as itself and takes no package slot
        (owner, 2026-10-02: "the only visits that count are in-school visits
        and Training Follow Up visits")."""
        response = self._post_visit(purpose_of_visit="ssa_support")
        self.assertEqual(response.status_code, 200, response.content[:300])
        visit = Activity.objects.get(
            school=self.school, activity_type="school_visit_ssa_collection"
        )
        self.assertEqual(visit.purpose_type, "ssa_support")
        self.assertTrue(visit.ssa_collection_expected)
        self.assertIsNone(visit.focus_intervention)
        self.assertFalse(CoreActivitySlot.objects.filter(activity_id=visit.id))
        self.assertIsNone(self._slot("v", 1).activity_id)

    def test_data_collection_is_not_limited_by_the_package(self):
        """Allowed "on every school irrespective of whether they have the 1
        visit by staff or partner": three in a row, and no slot between them."""
        for _ in range(3):
            response = self._post_visit(purpose_of_visit="ssa_support")
            self.assertEqual(response.status_code, 200, response.content[:300])
            Activity.objects.filter(school=self.school).update(
                planned_date=None, scheduled_date=None
            )
        self.assertEqual(
            Activity.objects.filter(
                school=self.school, activity_type="school_visit_ssa_collection"
            ).count(),
            3,
        )
        self.assertFalse(
            CoreActivitySlot.objects.filter(
                core_plan=self.plan, activity_id__isnull=False
            ).exists()
        )

    def test_a_first_visit_posted_without_a_purpose_is_ssa_support(self):
        """Unchanged: the DEFAULT is still SSA Support, it is just not forced."""
        response = self._post_visit()
        self.assertEqual(response.status_code, 200, response.content[:300])
        visit = Activity.objects.get(
            school=self.school, activity_type="school_visit_ssa_collection"
        )
        self.assertEqual(visit.purpose_type, "ssa_support")
        self.assertTrue(visit.ssa_collection_expected)

    def test_after_the_first_visit_every_purpose_and_training_is_offered(self):
        self._take_first_visit()
        html = (
            self._client(self.cceo)
            .get(f"/core-schools/schedule-visit?school_id={self.school.school_id}")
            .content.decode()
        )
        for value in (
            "in_school_training",
            "training_follow_up",
            "ssa_support",
            "donor_visit",
        ):
            self.assertIn(f'value="{value}"', html)
        # Retired (owner, 2026-09-28): In-school Training is that work.
        self.assertNotIn('value="in_school_coaching"', html)
        self.assertNotIn("data-core-first-visit", html)
        response = self._client(self.cceo).get(
            f"/core-schools/schedule-visit?school_id={self.school.school_id}"
        )
        courses = json.loads(response.context["training_courses_json"])
        self.assertEqual(len(courses), len(in_school_training_course_options()))

    def test_a_relationship_visit_needs_no_intervention(self):
        self._take_first_visit()
        response = self._post_visit(purpose_of_visit="donor_visit", visit_number="2")
        self.assertEqual(response.status_code, 200, response.content[:300])
        visit = Activity.objects.get(school=self.school, activity_type="donor_visit")
        self.assertEqual(visit.purpose_type, "donor_visit")
        self.assertIsNone(visit.focus_intervention)
        self.assertFalse(visit.ssa_collection_expected)

    def test_in_school_training_from_the_visit_drawer_creates_training_and_visit(self):
        self._take_first_visit()
        # A course normally delivered to clusters: any catalogue training.
        course = ActivityCatalogueItem.objects.get(stable_code="SCHOOL_LEADERSHIP")
        response = self._post_visit(
            purpose_of_visit="in_school_training",
            training_course_id=course.id,
            training_number="1",
        )
        self.assertEqual(response.status_code, 200, response.content[:300])
        training = Activity.objects.get(
            school=self.school, activity_type="in_school_training"
        )
        self.assertEqual(training.training_course_id, course.id)
        self.assertIsNotNone(training.paired_school_visit_id)
        self.assertEqual(training.paired_school_visit.activity_type, "school_visit")
        self.assertEqual(self._slot("t", 1).activity_id, training.id)
        # The companion visit is not a second package visit.
        self.assertIsNone(self._slot("v", 2).activity_id)
        self.assertFalse(
            Activity.objects.filter(
                school=self.school, activity_type="core_visit"
            ).exists()
        )

    def test_in_school_training_no_longer_waits_for_the_first_visit(self):
        """A training slot is not a visit slot.

        This was refused until 2026-09-17 on a question about VISIT slots, so
        a core school whose package had not started could be given no training
        at all — which is what the owner met as core training scheduling "not
        saving". The two caps that remain are counted per kind.
        """
        course = ActivityCatalogueItem.objects.get(stable_code="SCHOOL_LEADERSHIP")
        response = self._post_visit(
            purpose_of_visit="in_school_training", training_course_id=course.id
        )
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertTrue(
            Activity.objects.filter(
                school=self.school, activity_type="in_school_training"
            ).exists()
        )

    def test_follow_up_lists_the_trainings_the_school_did(self):
        self._take_first_visit()
        course = ActivityCatalogueItem.objects.get(stable_code="SCHOOL_LEADERSHIP")
        own = self._completed_in_school_training(course)
        session = Activity.objects.create(
            activity_type="cluster_training",
            cluster=self.cluster,
            fy=self.plan.fy,
            status="ia_verified",
            planned_date=_today(),
            focus_intervention="teaching_environment",
            attended_school_ids=[self.school.id],
        )
        elsewhere = Activity.objects.create(
            activity_type="cluster_training",
            cluster=self.cluster,
            fy=self.plan.fy,
            status="ia_verified",
            planned_date=_today(),
            focus_intervention="teaching_environment",
            attended_school_ids=[self.other_school.id],
        )
        response = self._client(self.cceo).get(
            f"/core-schools/schedule-visit?school_id={self.school.school_id}"
        )
        ids = {
            row["id"] for row in json.loads(response.context["follow_up_options_json"])
        }
        self.assertEqual(ids, {own.id, session.id})
        self.assertNotIn(elsewhere.id, ids)

        refused = self._post_visit(
            purpose_of_visit="training_follow_up",
            visit_number="2",
            source_activity_id=elsewhere.id,
        )
        self.assertEqual(refused.status_code, 400)
        created = self._post_visit(
            purpose_of_visit="training_follow_up",
            visit_number="2",
            source_activity_id=own.id,
        )
        self.assertEqual(created.status_code, 200, created.content[:300])
        visit = Activity.objects.get(school=self.school, activity_type="core_visit")
        self.assertEqual(visit.follow_up_of_activity_id, own.id)
        self.assertEqual(visit.focus_intervention, "leadership")


class CoreTrainingCatalogueTest(_CoreFixture):
    def test_the_training_drawer_lists_every_catalogue_training(self):
        response = self._client(self.cceo).get(
            f"/core-schools/schedule-training?school_id={self.school.school_id}"
        )
        labels = {item["label"] for item in response.context["catalogue_items"]}
        self.assertEqual(
            labels, {item["label"] for item in in_school_training_course_options()}
        )
        self.assertIn("Leadership", labels)

    def test_a_cluster_course_is_scheduled_as_a_core_in_school_training(self):
        course = ActivityCatalogueItem.objects.get(stable_code="SCHOOL_LEADERSHIP")
        response = self._client(self.cceo).post(
            "/core-schools/schedule-training/action",
            {
                "school_id": self.school.school_id,
                "training_number": "1",
                "scheduled_date": _today().isoformat(),
                "catalogue_item_id": course.id,
                "responsible_staff_id": self.cceo_sp.id,
            },
        )
        self.assertEqual(response.status_code, 200, response.content[:300])
        training = Activity.objects.get(school=self.school)
        self.assertEqual(training.activity_type, "in_school_training")
        self.assertEqual(training.training_course_id, course.id)
        self.assertEqual(training.activity_name_snapshot, course.display_name)
        self.assertEqual(self._slot("t", 1).activity_id, training.id)

    def _schedule_training(self, **fields):
        course = ActivityCatalogueItem.objects.get(stable_code="SCHOOL_LEADERSHIP")
        response = self._client(self.cceo).post(
            "/core-schools/schedule-training/action",
            {
                "school_id": self.school.school_id,
                "training_number": "1",
                "scheduled_date": _today().isoformat(),
                "catalogue_item_id": course.id,
                "responsible_staff_id": self.cceo_sp.id,
                **fields,
            },
        )
        self.assertEqual(response.status_code, 200, response.content[:300])
        return Activity.objects.get(school=self.school)

    def test_a_core_training_takes_its_trainings_own_intervention(self):
        """Owner, 2026-10-06: the SSA intervention is the one the Training
        Catalogue links the training to, and a scheduler does not pick
        another. A post naming Christlike Behaviour for a Leadership training
        is saved under Leadership. This reverses the rule of 2026-09-30
        ("leave the users to select any SSA intervention"), which this test
        pinned until then."""
        training = self._schedule_training(focus_intervention="christlike_behaviour")
        self.assertEqual(training.focus_intervention, "leadership")

    def test_a_blank_focus_keeps_the_courses_own_intervention(self):
        training = self._schedule_training(focus_intervention="")
        self.assertEqual(training.focus_intervention, "leadership")

    def test_the_training_drawer_offers_every_intervention(self):
        from apps.core.enums import SsaIntervention

        html = (
            self._client(self.cceo)
            .get(f"/core-schools/schedule-training?school_id={self.school.school_id}")
            .content.decode()
        )
        self.assertIn('name="focus_intervention" x-model="focusIntervention"', html)
        for code in SsaIntervention.values:
            self.assertIn(f'<option value="{code}">', html)


class ClusterSessionCoreCreditTest(_CoreFixture):
    """A group training planned through a cluster counts in the Core package
    of every Core school it counts for (owner, 2026-09-21 and 2026-10-02)."""

    def _session(self, activity_type="cluster_training", invited=None):
        session = Activity.objects.create(
            activity_type=activity_type,
            cluster=self.cluster,
            fy=self.plan.fy,
            status="scheduled",
            planned_date=_today(),
            responsible_staff_id=self.cceo_sp.id,
        )
        for school in invited or []:
            ClusterActivityAttendance.objects.create(
                activity=session, school=school, invited=True
            )
        return session

    def _attend(self, session, schools, status="submitted_to_pl"):
        from apps.activities.services import _sync_cluster_attendance

        session.attended_school_ids = [school.id for school in schools]
        _sync_cluster_attendance(session, session.attended_school_ids)
        session.status = status
        session.save()

    def test_an_invited_school_that_attended_gets_a_training_slot(self):
        session = self._session(invited=[self.school, self.other_school])
        self._attend(session, [self.school])

        slot = self._slot("t", 1)
        self.assertEqual(slot.activity_id, session.id)
        self.assertEqual(slot.status, "submitted_to_pl")
        plan = CorePlan.objects.get(id=self.plan.id)
        self.assertEqual(CorePackageSchedulingService.summary(plan)["trainings"], 1)
        # Invited, not in the room: nothing is credited.
        self.assertFalse(
            CoreActivitySlot.objects.filter(
                school_id=self.other_school.school_id, activity_id=session.id
            ).exists()
        )

        session.status = "ia_verified"
        session.save()
        self.assertEqual(CorePlan.objects.get(id=self.plan.id).trainings_completed, 1)

    def test_one_session_credits_every_core_school_in_the_room(self):
        session = self._session(invited=[self.school, self.other_school])
        self._attend(session, [self.school, self.other_school])
        self.assertEqual(
            CoreActivitySlot.objects.filter(activity_id=session.id).count(), 2
        )
        session.status = "ia_verified"
        session.save()
        self.assertEqual(
            set(
                CoreActivitySlot.objects.filter(activity_id=session.id).values_list(
                    "status", flat=True
                )
            ),
            {"ia_verified"},
        )

    def test_a_school_that_was_not_invited_is_not_credited(self):
        session = self._session(invited=[self.other_school])
        self._attend(session, [self.school, self.other_school])
        self.assertFalse(
            CoreActivitySlot.objects.filter(
                school_id=self.school.school_id, activity_id=session.id
            ).exists()
        )

    def test_a_cluster_meeting_is_not_a_training(self):
        """Owner, 2026-10-02: the package's trainings are in-school trainings
        and group trainings planned through clusters. A meeting fills no
        slot, booked or attended."""
        session = self._session("cluster_meeting", invited=[self.school])
        session.save()
        self.assertIsNone(self._slot("t", 1).activity_id)
        self._attend(session, [self.school])
        self.assertIsNone(self._slot("t", 1).activity_id)

    def test_a_slot_a_meeting_held_before_is_given_back_when_it_is_saved(self):
        session = self._session("cluster_meeting", invited=[self.school])
        slot = self._slot("t", 1)
        CoreActivitySlot.objects.filter(id=slot.id).update(
            activity_id=session.id, status="scheduled", owner="staff"
        )
        session.save()
        slot.refresh_from_db()
        self.assertIsNone(slot.activity_id)
        self.assertEqual(slot.status, "Planned")

    def test_a_third_staff_group_training_fills_no_slot(self):
        """The staff half is two trainings; the other two are assigned to a
        Partner. A group session is not refused over one school: it is on the
        school's history and in no slot."""
        sessions = [self._session(invited=[self.school]) for _ in range(3)]
        for session in sessions:
            session.save()
        self.assertEqual(
            [self._slot("t", n).activity_id for n in (1, 2, 3)],
            [sessions[0].id, sessions[1].id, None],
        )

    def test_the_invitation_holds_the_slot_while_the_session_is_completed(self):
        """Owner, 2026-09-21: a Core School trained through a cluster session
        contributes to its package, and the booking "should move to core
        school training planned table" — so the slot is taken at scheduling,
        on the invitation, and the register only narrows it once submitted.

        This used to assert the opposite: a session mid-completion credited
        nobody, which RELEASED the slot back to the package for as long as
        the register was being entered — the exact window in which the
        scheduler could book a fifth training over it. Holding it on the
        invitation closes that window. What the old name protected is
        unchanged and is pinned by the two tests below: a register entered
        mid-completion decides nothing, and a school that is not in the room
        when it is submitted loses the slot.
        """
        session = self._session(invited=[self.school])
        self._attend(session, [self.school], status="completion_started")
        slot = self._slot("t", 1)
        self.assertEqual(slot.activity_id, session.id)
        self.assertEqual(slot.status, "completion_started")

    def test_a_draft_register_decides_nothing_until_it_is_submitted(self):
        """Mid-completion the slot follows the INVITATION, not the ticks: a
        register still being entered is a draft, so unticking a school there
        must not hand its slot back while the session is still open."""
        session = self._session(invited=[self.school])
        self._attend(session, [], status="completion_started")
        self.assertEqual(self._slot("t", 1).activity_id, session.id)

        # Submitted, and now the register is what counts.
        self._attend(session, [])
        self.assertIsNone(self._slot("t", 1).activity_id)

    def test_a_scheduled_session_takes_the_slot_before_anyone_attends(self):
        """The reading the Core School Trainings Planned table needs: the
        package shows 1/4 planned from the day the session is booked."""
        session = self._session(invited=[self.school])
        session.save()
        slot = self._slot("t", 1)
        self.assertEqual(slot.activity_id, session.id)
        self.assertEqual(slot.status, "scheduled")

    def test_removing_the_school_from_the_register_releases_the_slot(self):
        session = self._session(invited=[self.school])
        self._attend(session, [self.school])
        self.assertEqual(self._slot("t", 1).activity_id, session.id)

        self._attend(session, [])
        slot = self._slot("t", 1)
        self.assertIsNone(slot.activity_id)
        self.assertEqual(slot.status, "Planned")


class CorePartnerPurposeTest(_CoreFixture):
    def setUp(self):
        super().setUp()
        from apps.core.rbac import EdifyRole

        self.partner_user, _ = self._staff(
            "partner-purpose@core.org", "Purpose Partner", EdifyRole.PARTNER_ADMIN.value
        )
        Partner.objects.filter(id=self.partner.id).update(
            user=self.partner_user, active_status=True
        )

    def _assign(self, **fields):
        return self._client(self.cceo).post(
            "/core-schools/assign-partner/action",
            {
                "school_id": self.school.school_id,
                "partner_id": self.partner.id,
                **fields,
            },
        )

    def _the_years_ssa_is_still_to_be_collected(self):
        """SSA Support goes to a partner only at a school with no SSA for the
        year (owner, 2026-10-08). The fixture's verified SSA becomes last
        year's, which is the school SSA Support is for."""
        from apps.core.fy import get_operational_fy
        from apps.ssa.models import SsaRecord

        fy = get_operational_fy()
        SsaRecord.objects.filter(school=self.school, fy=fy).update(fy=str(int(fy) - 1))

    def test_the_drawer_asks_for_the_purpose_not_a_support_type(self):
        self._take_first_visit()
        html = (
            self._client(self.cceo)
            .get(f"/core-schools/assign-partner?school_id={self.school.school_id}")
            .content.decode()
        )
        self.assertNotIn('name="support_type"', html)
        for value in ("in_school_training", "training_follow_up", "ssa_support"):
            self.assertIn(f'value="{value}"', html)
        self.assertIn('name="source_activity_id"', html)
        self.assertIn('name="training_course_id"', html)

    def test_a_first_partner_visit_may_be_any_purpose(self):
        """The first-visit-is-SSA rule is lifted for handoffs too (2026-09-17).

        The owner met it as "I cannot assign core school to a partner": the
        drawer offered a single purpose and a training handoff was refused.
        """
        allowed = self._assign(purpose_of_visit="training_follow_up")
        self.assertEqual(allowed.status_code, 200, allowed.content[:300])
        PartnerAssignment.objects.filter(school=self.school).delete()
        self._slot("v", 1).__class__.objects.filter(id=self._slot("v", 1).id).update(
            status="Planned", assigned_partner_id=None, assigned_partner_name=None
        )
        # With the year's SSA on record there is nothing to collect.
        refused = self._assign(purpose_of_visit="ssa_support")
        self.assertEqual(refused.status_code, 400)
        self.assertIn(b"has completed its SSA", refused.content)
        self._the_years_ssa_is_still_to_be_collected()
        response = self._assign(purpose_of_visit="ssa_support")
        self.assertEqual(response.status_code, 200, response.content[:300])
        pa = PartnerAssignment.objects.get(school=self.school)
        self.assertEqual(pa.purpose_of_visit, "ssa_support")
        # Data collection is assigned on any school and holds no package
        # slot (owner, 2026-10-02).
        self.assertEqual(pa.support_type, "")
        self.assertEqual(pa.catalogue_item.workflow_kind, "school_visit_ssa_collection")
        self.assertEqual(self._slot("v", 1).status, "Planned")

    def test_data_collection_is_assigned_whatever_the_partner_already_holds(self):
        """With both of the partner's package visits taken, and to the same
        partner whose follow up is still waiting."""
        for _ in range(2):
            self.assertEqual(
                self._assign(purpose_of_visit="training_follow_up").status_code, 200
            )
        refused = self._assign(purpose_of_visit="training_follow_up")
        self.assertEqual(refused.status_code, 400)
        self._the_years_ssa_is_still_to_be_collected()
        response = self._assign(purpose_of_visit="ssa_support")
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertEqual(
            PartnerAssignment.objects.filter(
                school=self.school, purpose_of_visit="ssa_support"
            ).count(),
            1,
        )
        # One open data collection hand-over a partner, as for support.
        again = self._assign(purpose_of_visit="ssa_support")
        self.assertEqual(again.status_code, 400)

    def test_a_follow_up_handoff_names_the_training_followed_up(self):
        self._take_first_visit()
        course = ActivityCatalogueItem.objects.get(stable_code="SCHOOL_LEADERSHIP")
        own = self._completed_in_school_training(course)
        # Where the fiscal year's policy requires a prior training, a follow-up
        # handoff without one is refused (owner, 2026-09-15: governed per FY).
        from apps.core.fy import get_operational_fy
        from apps.planning.models import FiscalYearPlanningPolicy

        FiscalYearPlanningPolicy.objects.filter(fy=get_operational_fy()).update(
            follow_up_visit_requires_prior_training=True
        )
        missing = self._assign(purpose_of_visit="training_follow_up")
        self.assertEqual(missing.status_code, 400)
        response = self._assign(
            purpose_of_visit="training_follow_up", source_activity_id=own.id
        )
        self.assertEqual(response.status_code, 200, response.content[:300])
        pa = PartnerAssignment.objects.get(school=self.school)
        self.assertEqual(pa.source_activity_id, own.id)
        self.assertEqual(pa.focus_intervention, "leadership")
        self.assertEqual(pa.visit_number, "2")

    def test_the_partner_only_dates_an_in_school_training_staff_chose(self):
        from apps.activities.services import partner_schedule

        self._take_first_visit()
        course = ActivityCatalogueItem.objects.get(stable_code="SCHOOL_LEADERSHIP")
        response = self._assign(
            purpose_of_visit="in_school_training", training_course_id=course.id
        )
        self.assertEqual(response.status_code, 200, response.content[:300])
        pa = PartnerAssignment.objects.get(school=self.school)
        self.assertEqual(pa.training_course_id, course.id)
        self.assertEqual(pa.catalogue_item.workflow_kind, "in_school_training")
        self.assertEqual(pa.support_type, "Training")
        self.assertEqual(self._slot("t", 1).status, "Assigned")

        drawer = self._client(self.partner_user).get(
            f"/partner/assignments/{pa.id}/schedule-drawer"
        )
        self.assertContains(drawer, course.display_name)
        self.assertNotContains(drawer, 'name="training_course_id"')

        partner_schedule(
            pa.id,
            {
                "scheduledDate": _today().isoformat(),
                "deliveryContactName": "Field Lead",
            },
            self.partner_user,
        )
        activity = Activity.objects.get(school=self.school)
        self.assertEqual(activity.activity_type, "in_school_training")
        self.assertEqual(activity.training_course_id, course.id)
        self.assertEqual(activity.activity_name_snapshot, course.display_name)
        self.assertEqual(self._slot("t", 1).activity_id, activity.id)

    def test_a_partners_in_school_training_is_priced_as_a_partner_school_visit(self):
        """Owner, 2026-10-01: an in-school training "should be costed as a
        normal visit ... if it is partner it should carry the same partner
        school visit cost", and at a core school it "is the same as the
        in-school training visit for client schools". So here, at a Core
        School, the partner's package visit fetches Core Partner Visit and
        the partner's in-school training fetches the partner school visit
        rate: on the hand-over table, in the schedule drawer and on the
        saved cost line."""
        from apps.activities.models import ActivityScheduleCostLine
        from apps.activities.services import partner_schedule
        from apps.budget.costing_service import active_catalogue
        from apps.budget.models import CostSetting
        from apps.planning import partner_oversight_service as oversight

        card = active_catalogue()
        for key, rate in (
            ("core_partner_visit", 55_000),
            ("client_partner_visit", 41_000),
        ):
            CostSetting.objects.filter(catalogue=card, key=key).update(unit_cost=rate)
        self.assertEqual(oversight.core_partner_visit_rate(), 55_000)
        self.assertEqual(oversight.partner_school_visit_rate(), 41_000)

        def schedule_and_read(amount, **purpose):
            response = self._assign(**purpose)
            self.assertEqual(response.status_code, 200, response.content[:300])
            pa = PartnerAssignment.objects.filter(school=self.school).latest(
                "created_at"
            )
            drawer = self._client(self.partner_user).get(
                f"/partner/assignments/{pa.id}/schedule-drawer"
            )
            self.assertContains(drawer, amount)
            partner_schedule(
                pa.id,
                {
                    "scheduledDate": _today().isoformat(),
                    "deliveryContactName": "Field Lead",
                },
                self.partner_user,
            )
            pa.refresh_from_db()
            return list(
                ActivityScheduleCostLine.objects.filter(
                    activity_id=pa.scheduled_activity_id
                ).values_list("cost_setting_key", "amount")
            )

        self.assertEqual(
            schedule_and_read("55,000", purpose_of_visit="training_follow_up"),
            [("core_partner_visit", 55_000)],
        )
        course = ActivityCatalogueItem.objects.get(stable_code="SCHOOL_LEADERSHIP")
        self.assertEqual(
            schedule_and_read(
                "41,000",
                purpose_of_visit="in_school_training",
                training_course_id=course.id,
            ),
            [("client_partner_visit", 41_000)],
        )

    def test_an_in_school_training_handoff_takes_its_trainings_intervention(self):
        """Owner, 2026-10-06: a training is handed over under the SSA
        intervention the Training Catalogue links it to, whatever the request
        names. This reverses the rule of 2026-09-30 ("the planner chooses the
        focus, not the course"), which this test pinned until then."""
        self._take_first_visit()
        course = ActivityCatalogueItem.objects.get(stable_code="SCHOOL_LEADERSHIP")
        response = self._assign(
            purpose_of_visit="in_school_training",
            training_course_id=course.id,
            focus_intervention="financial_health",
        )
        self.assertEqual(response.status_code, 200, response.content[:300])
        pa = PartnerAssignment.objects.get(school=self.school)
        self.assertEqual(pa.focus_intervention, "leadership")

    def test_the_handoff_drawer_offers_every_intervention_for_a_training(self):
        from apps.core.enums import SsaIntervention

        self._take_first_visit()
        html = (
            self._client(self.cceo)
            .get(f"/core-schools/assign-partner?school_id={self.school.school_id}")
            .content.decode()
        )
        self.assertIn('id="partner_core_training_focus"', html)
        for code in SsaIntervention.values:
            self.assertIn(f'<option value="{code}">', html)
