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
from datetime import date

from django.test import TestCase

from apps.activities.models import Activity, ClusterActivityAttendance
from apps.activity_catalogue.availability import in_school_training_course_options
from apps.activity_catalogue.models import ActivityCatalogueItem
from apps.core_schools.core_planning_services import CorePackageSchedulingService
from apps.core_schools.models import CoreActivitySlot, CorePlan, cslot_id
from apps.core_schools import test_core_planning as _planning
from apps.partners.models import Partner, PartnerAssignment

TODAY = date.today()


class _CoreFixture(TestCase):
    """The Core planning fixture, without re-running that module's tests."""

    # Borrowed from the module, not imported as a class: an imported TestCase
    # would be collected here and its 45 tests run twice.
    setUp = _planning.CoreSchoolsPlanningTest.setUp
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
            "scheduled_date": TODAY.isoformat(),
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
            planned_date=TODAY,
            focus_intervention=intervention,
            responsible_staff_id=self.cceo_sp.id,
        )


class CoreVisitPurposeTest(_CoreFixture):
    def test_first_visit_drawer_offers_only_ssa_support(self):
        html = (
            self._client(self.cceo)
            .get(f"/core-schools/schedule-visit?school_id={self.school.school_id}")
            .content.decode()
        )
        self.assertIn("data-core-first-visit", html)
        self.assertIn('value="ssa_support"', html)
        self.assertNotIn('value="donor_visit"', html)
        self.assertNotIn('value="in_school_training"', html)

    def test_first_visit_must_be_ssa_support(self):
        refused = self._post_visit(purpose_of_visit="donor_visit")
        self.assertEqual(refused.status_code, 400)
        self.assertIn("SSA Support", refused.content.decode())
        self.assertFalse(Activity.objects.filter(school=self.school).exists())

        response = self._post_visit(purpose_of_visit="ssa_support")
        self.assertEqual(response.status_code, 200, response.content[:300])
        visit = Activity.objects.get(school=self.school, activity_type="core_visit")
        self.assertEqual(visit.purpose_type, "ssa_support")
        self.assertTrue(visit.ssa_collection_expected)
        self.assertIsNone(visit.focus_intervention)
        self.assertEqual(self._slot("v", 1).activity_id, visit.id)

    def test_a_first_visit_posted_without_a_purpose_is_ssa_support(self):
        response = self._post_visit()
        self.assertEqual(response.status_code, 200, response.content[:300])
        visit = Activity.objects.get(school=self.school, activity_type="core_visit")
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
            "in_school_coaching",
        ):
            self.assertIn(f'value="{value}"', html)
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
        visit = Activity.objects.get(school=self.school, activity_type="core_visit")
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

    def test_in_school_training_waits_for_the_first_visit(self):
        course = ActivityCatalogueItem.objects.get(stable_code="SCHOOL_LEADERSHIP")
        response = self._post_visit(
            purpose_of_visit="in_school_training", training_course_id=course.id
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Activity.objects.filter(school=self.school).exists())

    def test_follow_up_lists_the_trainings_the_school_did(self):
        self._take_first_visit()
        course = ActivityCatalogueItem.objects.get(stable_code="SCHOOL_LEADERSHIP")
        own = self._completed_in_school_training(course)
        session = Activity.objects.create(
            activity_type="cluster_training",
            cluster=self.cluster,
            fy=self.plan.fy,
            status="ia_verified",
            planned_date=TODAY,
            focus_intervention="teaching_environment",
            attended_school_ids=[self.school.id],
        )
        elsewhere = Activity.objects.create(
            activity_type="cluster_training",
            cluster=self.cluster,
            fy=self.plan.fy,
            status="ia_verified",
            planned_date=TODAY,
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
                "scheduled_date": TODAY.isoformat(),
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


class ClusterSessionCoreCreditTest(_CoreFixture):
    def _session(self, activity_type="cluster_training", invited=None):
        session = Activity.objects.create(
            activity_type=activity_type,
            cluster=self.cluster,
            fy=self.plan.fy,
            status="scheduled",
            planned_date=TODAY,
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

    def test_a_cluster_meeting_counts_too(self):
        session = self._session("cluster_meeting", invited=[self.school])
        self._attend(session, [self.school])
        self.assertEqual(self._slot("t", 1).activity_id, session.id)

    def test_attendance_is_not_credited_before_the_register_is_submitted(self):
        session = self._session(invited=[self.school])
        self._attend(session, [self.school], status="completion_started")
        self.assertIsNone(self._slot("t", 1).activity_id)

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

    def test_the_first_partner_visit_is_ssa_support(self):
        refused = self._assign(purpose_of_visit="training_follow_up")
        self.assertEqual(refused.status_code, 400)
        response = self._assign(purpose_of_visit="ssa_support")
        self.assertEqual(response.status_code, 200, response.content[:300])
        pa = PartnerAssignment.objects.get(school=self.school)
        self.assertEqual(pa.purpose_of_visit, "ssa_support")
        self.assertEqual(pa.support_type, "Visit")
        self.assertEqual(pa.catalogue_item.workflow_kind, "core_visit")
        self.assertEqual(self._slot("v", 1).status, "Assigned")

    def test_a_follow_up_handoff_names_the_training_followed_up(self):
        self._take_first_visit()
        course = ActivityCatalogueItem.objects.get(stable_code="SCHOOL_LEADERSHIP")
        own = self._completed_in_school_training(course)
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
            {"scheduledDate": TODAY.isoformat(), "deliveryContactName": "Field Lead"},
            self.partner_user,
        )
        activity = Activity.objects.get(school=self.school)
        self.assertEqual(activity.activity_type, "in_school_training")
        self.assertEqual(activity.training_course_id, course.id)
        self.assertEqual(activity.activity_name_snapshot, course.display_name)
        self.assertEqual(self._slot("t", 1).activity_id, activity.id)
