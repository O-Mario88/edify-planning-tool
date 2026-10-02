"""The Core package's 2 + 2 split and what counts toward it (owner, 2026-09-30).

"all scheduling visit or training can contribute to the core school packages
(4 visits and 4 trainings (2 each for staff and the other 2 for partners)".
Asked, the owner chose: the split is enforced at every door, for visits AND
trainings; Special Project work counts; donor, story, invitation and social
visits do not.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase

from apps.activities.models import Activity
from apps.activities.services import _assert_schedule_entitlement
from apps.core.exceptions import BadRequest
from apps.core.fy import get_operational_fy
from apps.core_schools.core_planning_services import CorePackageSchedulingService
from apps.core_schools.models import CoreActivitySlot, CorePlan, cplan_id, cslot_id
from apps.core_schools.package_credit import repair_package_links
from apps.core_schools.package_split import (
    PARTNER,
    STAFF,
    TRAINING,
    VISIT,
    assert_side_open,
    package_split,
)
from apps.core_schools.services import create_package_slots
from apps.geography.models import District, Region
from apps.partners import services as partner_services
from apps.partners.models import Partner, PartnerAssignment
from apps.planning.visit_gate import visit_gate
from apps.schools.models import School


class _SplitFixture(TestCase):
    def setUp(self):
        self.fy = get_operational_fy()
        region = Region.objects.create(name="Split Region")
        district = District.objects.create(name="Split District", region=region)
        self.region, self.district = region, district
        self.school = School.objects.create(
            school_id="SPLIT-1",
            name="Split Core Primary",
            school_type="core",
            region=region,
            district=district,
        )
        self.plan = CorePlan.objects.create(
            id=cplan_id("SPLIT-1", fy=self.fy),
            school_id="SPLIT-1",
            fy=self.fy,
            status="Active",
        )
        create_package_slots(self.plan, "SPLIT-1", ["leadership"])
        self.partner = Partner.objects.create(name="Split Partner", active_status=True)

    def _activity(self, activity_type="school_visit", **fields):
        """Saved the way every door saves one, with its commit hooks run."""
        with self.captureOnCommitCallbacks(execute=True):
            return Activity.objects.create(
                activity_type=activity_type,
                school=self.school,
                fy=fields.pop("fy", self.fy),
                quarter="Q1",
                planned_date=date.today() + timedelta(days=3),
                status=fields.pop("status", "scheduled"),
                **fields,
            )

    def _partner_activity(self, activity_type="school_visit", **fields):
        return self._activity(
            activity_type,
            delivery_type="partner",
            assigned_partner_id=self.partner.id,
            **fields,
        )

    def _handover(self, kind, number):
        return PartnerAssignment.objects.create(
            school=self.school,
            partner=self.partner,
            status=PartnerAssignment.STATUS_PENDING_SCHEDULING,
            support_type="Training" if kind == TRAINING else "Visit",
            visit_number="" if kind == TRAINING else str(number),
            training_number=str(number) if kind == TRAINING else "",
        )

    def _split(self, **exclude):
        return package_split(self.school, self.fy, **exclude)


class SplitCountsEachSideTest(_SplitFixture):
    def test_each_side_holds_two_visits_and_two_trainings(self):
        self._activity()
        self._activity("training_follow_up_visit")
        self._activity("in_school_training")
        self._partner_activity()
        self._partner_activity("in_school_training")

        split = self._split()
        self.assertEqual(
            (
                split.used(VISIT, STAFF),
                split.used(VISIT, PARTNER),
                split.used(TRAINING, STAFF),
                split.used(TRAINING, PARTNER),
            ),
            (2, 1, 1, 1),
        )
        self.assertFalse(split.is_open(VISIT, STAFF))
        self.assertTrue(split.is_open(VISIT, PARTNER))

    def test_a_third_staff_visit_is_refused_and_the_partner_s_half_stays_open(self):
        self._activity()
        self._activity("follow_up_visit")

        with self.assertRaisesMessage(BadRequest, "2 staff core visits"):
            assert_side_open(self.school, VISIT, STAFF)
        assert_side_open(self.school, VISIT, PARTNER)

    def test_a_third_staff_training_is_refused(self):
        """Trainings were uncapped from 2026-09-28; they are split too now."""
        self._activity("in_school_training")
        self._activity("in_school_training")

        with self.assertRaisesMessage(BadRequest, "2 staff core trainings"):
            assert_side_open(self.school, TRAINING, STAFF)

    def test_a_waiting_hand_over_holds_its_place_on_the_partner_side(self):
        self._handover(VISIT, 3)
        self._partner_activity()

        self.assertEqual(self._split().used(VISIT, PARTNER), 2)
        with self.assertRaisesMessage(BadRequest, "2 partner core visits"):
            assert_side_open(self.school, VISIT, PARTNER)

    def test_the_hand_over_being_dated_does_not_count_against_itself(self):
        first = self._handover(VISIT, 3)
        self._handover(VISIT, 4)

        assert_side_open(self.school, VISIT, PARTNER, exclude_assignment_id=first.id)

    def test_a_staff_core_visit_already_over_the_split_is_left_alone(self):
        """Work planned before the rule is never removed; the side just takes
        no more."""
        for _ in range(3):
            self._activity()

        self.assertEqual(self._split().used(VISIT, STAFF), 3)
        self.assertEqual(
            Activity.objects.filter(
                school=self.school, deleted_at__isnull=True
            ).count(),
            3,
        )

    def test_a_group_training_in_a_slot_is_on_the_half_of_who_delivers_it(self):
        # Owner, 2026-10-02: "if a core school is part of a group training, it
        # should be counted in the core package." A cluster meeting is not a
        # training: on neither half, even where an older link still points a
        # slot at it (the deploy repair removes those).
        from apps.clusters.models import Cluster

        cluster = Cluster.objects.create(
            name="Split Cluster", region=self.region, district=self.district
        )
        made = {}
        for sequence, (kind, delivery) in enumerate(
            (
                ("cluster_training", "staff"),
                ("cluster_training", "partner"),
                ("cluster_meeting", "staff"),
            ),
            start=1,
        ):
            session = Activity.objects.create(
                activity_type=kind,
                cluster=cluster,
                fy=self.fy,
                quarter="Q1",
                status="scheduled",
                delivery_type=delivery,
            )
            CoreActivitySlot.objects.filter(
                id=cslot_id("SPLIT-1", "t", sequence, fy=self.fy)
            ).update(activity_id=session.id, status="Scheduled", owner=delivery)
            made[sequence] = session

        self.assertEqual(self._split().used(TRAINING, STAFF), 1)
        self.assertEqual(self._split().used(TRAINING, PARTNER), 1)
        # The session being saved does not count against itself.
        self.assertEqual(
            self._split(exclude_activity_id=made[1].id).used(TRAINING, STAFF), 0
        )

    def test_a_school_with_no_package_has_no_split(self):
        CorePlan.objects.filter(id=self.plan.id).update(status="Archived")
        for _ in range(3):
            self._activity()

        assert_side_open(self.school, VISIT, STAFF)


class WhatCountsTest(_SplitFixture):
    def test_a_donor_visit_takes_no_package_slot_and_has_no_limit(self):
        self._activity()
        self._activity()
        donor = self._activity("donor_visit", purpose_type="donor_visit")

        self.assertFalse(CoreActivitySlot.objects.filter(activity_id=donor.id))
        self.assertEqual(self._split().used(VISIT, STAFF), 2)
        # The staff half is full, and a donor visit is still not refused.
        _assert_schedule_entitlement(
            "donor_visit",
            self.school,
            self.fy,
            {"deliveryType": "staff", "purposeType": "donor_visit"},
        )

    def test_story_invitation_and_social_visits_are_not_package_work(self):
        for activity_type, purpose in (
            ("story_gathering_visit", "story_gathering"),
            ("school_invitation", "school_invitation"),
            ("social_visit", "social_visit"),
        ):
            self._activity(activity_type, purpose_type=purpose)

        self.assertEqual(CorePackageSchedulingService.summary(self.plan)["visits"], 0)

    def test_a_legacy_donor_core_visit_is_not_counted(self):
        """The Core Schools drawer used to book every purpose as a core_visit."""
        self._activity("core_visit", purpose_type="donor_visit")

        self.assertEqual(self._split().used(VISIT, STAFF), 0)

    def test_project_work_at_a_core_school_counts_toward_the_package(self):
        from apps.projects.models import Project, ProjectCategory

        project = Project.objects.create(
            name="Split Project",
            category=ProjectCategory.choices[0][0],
        )
        visit = self._activity(project_id=project.id)
        training = self._activity("in_school_training", project_id=project.id)

        self.assertTrue(CoreActivitySlot.objects.filter(activity_id=visit.id))
        self.assertTrue(CoreActivitySlot.objects.filter(activity_id=training.id))
        split = self._split()
        self.assertEqual(
            (split.used(VISIT, STAFF), split.used(TRAINING, STAFF)), (1, 1)
        )

    def test_the_repair_gives_back_a_slot_a_donor_visit_held(self):
        donor = Activity.objects.create(
            activity_type="core_visit",
            purpose_type="donor_visit",
            school=self.school,
            fy=self.fy,
            quarter="Q1",
            status="scheduled",
        )
        slot_id = cslot_id("SPLIT-1", "v", 1, fy=self.fy)
        CoreActivitySlot.objects.filter(id=slot_id).update(
            activity_id=donor.id, status="Scheduled", owner="staff"
        )

        dry = repair_package_links(apply=False, school_code="SPLIT-1")
        self.assertIn(slot_id, dry["released"])
        self.assertEqual(CoreActivitySlot.objects.get(id=slot_id).activity_id, donor.id)

        repair_package_links(apply=True, school_code="SPLIT-1")
        slot = CoreActivitySlot.objects.get(id=slot_id)
        self.assertIsNone(slot.activity_id)
        self.assertEqual(slot.status, "Planned")


class EveryDoorAsksTest(_SplitFixture):
    def test_the_general_create_path_refuses_a_third_staff_visit(self):
        """Planning, cluster-school drawers, projects, autopilot and the API
        all reach activities.services.create."""
        self._activity()
        self._activity()

        with self.assertRaises(BadRequest):
            _assert_schedule_entitlement(
                "school_visit", self.school, self.fy, {"deliveryType": "staff"}
            )
        _assert_schedule_entitlement(
            "school_visit",
            self.school,
            self.fy,
            {"deliveryType": "partner", "assignedPartnerId": self.partner.id},
        )

    def test_the_core_slot_door_refuses_a_third_partner_training(self):
        self._partner_activity("in_school_training")
        self._handover(TRAINING, 2)

        with self.assertRaisesMessage(BadRequest, "2 partner core trainings"):
            CorePackageSchedulingService.assert_can_schedule(
                plan=self.plan,
                school=self.school,
                activity_type="training",
                sequence_number=3,
                scheduled_for=date.today() + timedelta(days=3),
                is_partner_delivery=True,
            )

    def test_a_partner_hand_over_is_refused_once_the_partner_half_is_taken(self):
        self._handover(VISIT, 1)
        self._partner_activity()

        with self.assertRaisesMessage(BadRequest, "2 partner core visits"):
            partner_services.create_assignment(
                school=self.school,
                partner=Partner.objects.create(
                    name="Second Split Partner", active_status=True
                ),
                support_type="Visit",
                visit_number="3",
            )

    def test_a_partner_hand_over_is_not_refused_over_a_full_package(self):
        """It used to refuse once all 4 + 4 were taken, even with the
        partner's own half empty."""
        for _ in range(2):
            self._activity()
            self._activity("in_school_training")
        CoreActivitySlot.objects.filter(core_plan=self.plan).exclude(
            activity_type="assessment"
        ).update(status="Scheduled")

        slot = CorePackageSchedulingService.assert_can_assign(
            plan=self.plan, school=self.school, activity_type="visit", sequence_number=1
        )
        self.assertEqual(slot.sequence_number, 5)

    def test_moving_staff_work_to_a_partner_needs_room_on_the_partner_side(self):
        """`activities.services.reassign` asks with the moved work left out."""
        self._partner_activity()
        self._partner_activity()
        staff_visit = self._activity()

        with self.assertRaisesMessage(BadRequest, "2 partner core visits"):
            assert_side_open(
                self.school, VISIT, PARTNER, exclude_activity_id=staff_visit.id
            )
        # Back to staff is fine: the staff half holds only the moved visit,
        # which is left out of its own count.
        assert_side_open(self.school, VISIT, STAFF, exclude_activity_id=staff_visit.id)


class GateReadsTheSplitTest(_SplitFixture):
    def test_the_row_greys_what_the_doors_refuse(self):
        self._activity()
        self._activity()
        self._activity("in_school_training")
        self._activity("in_school_training")
        self._handover(VISIT, 3)
        self._partner_activity()

        gate = visit_gate(self.school, self.fy)
        self.assertFalse(gate.staff_can_schedule)
        self.assertFalse(gate.staff_trainings_open)
        self.assertFalse(gate.can_assign_visit)
        # The partner's two trainings are still open, so Assign stays live.
        self.assertTrue(gate.partner_trainings_open)
        self.assertTrue(gate.can_assign_partner)

    def test_an_empty_package_is_open_on_every_side(self):
        gate = visit_gate(self.school, self.fy)
        self.assertTrue(gate.staff_can_schedule)
        self.assertTrue(gate.staff_trainings_open)
        self.assertTrue(gate.can_assign_partner)
        self.assertEqual((gate.staff_cap, gate.partner_cap), (2, 2))
