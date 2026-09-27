"""Core package work counts wherever it was scheduled (owner, 2026-09-27).

"make sure all core planned whether through cluster, or through planning page
core school tab or through core school page all reflect on core school visit
plan and core training plan and counted as V1 or v2 or v3 ... irrespective of
where the visits scheduling or training scheduling is done from. the packages
should be counted."

The package is its slots. These pin that every visit and training at a Core
School takes one — whichever door booked it — that a slot stays counted for
the whole life of its activity, and that a partner's hold on a slot follows
the handover.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from freezegun import freeze_time

from apps.activities.models import Activity
from apps.core.fy import get_operational_fy
from apps.core_schools.core_planning_services import CorePackageSchedulingService
from apps.core_schools.models import CoreActivitySlot, CorePlan, cplan_id, cslot_id
from apps.core_schools.package_credit import (
    credit_school_activity,
    repair_package_links,
)
from apps.core_schools.services import create_package_slots
from apps.geography.models import District, Region
from apps.partners.models import Partner, PartnerAssignment
from apps.schools.models import School

User = get_user_model()


class _PackageFixture(TestCase):
    def setUp(self):
        self.fy = get_operational_fy()
        self.region = Region.objects.create(name="Credit Region")
        self.district = District.objects.create(
            name="Credit District", region=self.region
        )
        self.school = School.objects.create(
            school_id="CRED-1",
            name="Credit Core Primary",
            school_type="core",
            region=self.region,
            district=self.district,
        )
        self.plan = CorePlan.objects.create(
            id=cplan_id("CRED-1", fy=self.fy),
            school_id="CRED-1",
            fy=self.fy,
            status="Active",
        )
        create_package_slots(self.plan, "CRED-1", ["leadership"])
        self.partner = Partner.objects.create(name="Credit Partner", active_status=True)

    def _slot(self, kind, seq):
        return CoreActivitySlot.objects.get(
            id=cslot_id("CRED-1", kind, seq, fy=self.fy)
        )

    def _activity(self, activity_type="school_visit", *, on=None, **fields):
        """Saved the way every door saves one, with its commit hooks run."""
        with self.captureOnCommitCallbacks(execute=True):
            return Activity.objects.create(
                activity_type=activity_type,
                school=self.school,
                fy=fields.pop("fy", self.fy),
                quarter="Q1",
                planned_date=on or date.today() + timedelta(days=3),
                status=fields.pop("status", "scheduled"),
                **fields,
            )

    def _visits(self):
        return CorePackageSchedulingService.summary(self.plan)["visits"]

    def _trainings(self):
        return CorePackageSchedulingService.summary(self.plan)["trainings"]


class WorkFromAnyDoorIsCountedTest(_PackageFixture):
    def test_a_visit_booked_outside_the_core_drawers_takes_V1_then_V2(self):
        """Autopilot, a debrief follow-up, catch-up plans and the API all make
        a plain visit with no slot. Each now counts, in the order booked."""
        first = self._activity(on=date.today() + timedelta(days=2))
        second = self._activity("follow_up_visit", on=date.today() + timedelta(days=5))

        self.assertEqual(self._slot("v", 1).activity_id, first.id)
        self.assertEqual(self._slot("v", 2).activity_id, second.id)
        self.assertEqual(self._visits(), 2)

    def test_an_in_school_training_takes_T1_and_its_companion_visit_takes_none(self):
        training = self._activity("in_school_training")
        companion = self._activity(
            "school_visit", purpose_type="in_school_training_delivery_visit"
        )

        self.assertEqual(self._slot("t", 1).activity_id, training.id)
        self.assertFalse(CoreActivitySlot.objects.filter(activity_id=companion.id))
        self.assertEqual((self._visits(), self._trainings()), (0, 1))

    def test_completed_work_counts_as_completed(self):
        self._activity(status="completed", on=date.today() - timedelta(days=10))

        self.plan.refresh_from_db()
        self.assertEqual(self.plan.visits_completed, 1)
        self.assertEqual(self._slot("v", 1).status, "completed")

    def test_work_a_door_already_linked_keeps_its_own_slot(self):
        """The Core Schools drawer links the slot the planner chose in the same
        transaction; the catch-all runs after commit and must not add a second."""
        with self.captureOnCommitCallbacks(execute=True):
            activity = Activity.objects.create(
                activity_type="core_visit",
                school=self.school,
                fy=self.fy,
                quarter="Q1",
                planned_date=date.today() + timedelta(days=3),
                status="scheduled",
            )
            CoreActivitySlot.objects.filter(id=self._slot("v", 3).id).update(
                activity_id=activity.id, status="Scheduled", owner="staff"
            )

        self.assertEqual(
            list(
                CoreActivitySlot.objects.filter(activity_id=activity.id).values_list(
                    "id", flat=True
                )
            ),
            [self._slot("v", 3).id],
        )

    def test_work_that_is_not_the_package_s_is_left_alone(self):
        from apps.projects.models import Project, ProjectCategory

        project = Project.objects.create(
            name="Reading Project", category=ProjectCategory.INTERVENTION_SPECIFIC
        )
        project_visit = self._activity(project_id=project.id)
        cancelled = self._activity(status="cancelled")
        request = self._activity(status="awaiting_owner_approval")
        last_year = self._activity(fy=str(int(self.fy) - 1))

        for activity in (project_visit, cancelled, request, last_year):
            self.assertFalse(
                CoreActivitySlot.objects.filter(activity_id=activity.id).exists(),
                activity.status,
            )
        self.assertEqual(self._visits(), 0)

    def test_a_client_school_s_visit_takes_no_slot(self):
        self.school.school_type = "client"
        self.school.save(update_fields=["school_type"])
        activity = self._activity()
        self.assertFalse(CoreActivitySlot.objects.filter(activity_id=activity.id))

    def test_a_fifth_visit_is_counted_not_refused(self):
        for day in range(4):
            self._activity(on=date.today() + timedelta(days=day + 1))
        fifth = self._activity(on=date.today() + timedelta(days=9))

        slot = CoreActivitySlot.objects.get(activity_id=fifth.id)
        self.assertEqual((slot.activity_type, slot.sequence_number), ("visit", 5))

    def test_crediting_twice_is_a_no_op(self):
        activity = self._activity()
        self.assertIsNone(credit_school_activity(activity.id))
        self.assertEqual(
            CoreActivitySlot.objects.filter(activity_id=activity.id).count(), 1
        )


class TheSlotStaysCountedTest(_PackageFixture):
    """The mirror copies the activity's status onto its slot. Statuses a live
    activity passes through read as an OPEN slot, so the visit dropped out of
    the count and its number was offered — and taken — again."""

    def test_every_live_status_keeps_the_visit_counted(self):
        activity = self._activity()
        for status in (
            "completion_started",
            "salesforce_id_required",
            "returned_by_ia",
            "assigned_to_partner",
            "awaiting_owner_approval",
        ):
            with self.subTest(status=status):
                activity.status = status
                activity.save()
                self.assertEqual(self._visits(), 1)
                self.assertNotIn(
                    1,
                    CorePackageSchedulingService.available_sequences(
                        self.plan, "visit"
                    ),
                )

    def test_a_planned_activity_does_not_read_as_an_open_slot(self):
        activity = self._activity(status="planned")
        slot = CoreActivitySlot.objects.get(activity_id=activity.id)
        self.assertEqual(slot.status, "Scheduled")
        self.assertEqual(self._visits(), 1)

    def test_a_partner_s_held_visit_is_counted_on_the_row(self):
        """The row said "Visits 1/4 (staff 1/2 · partner 1/2)": the split counted
        the partner's held visit and the total did not."""
        CoreActivitySlot.objects.filter(id=self._slot("v", 2).id).update(
            status="Assigned", assigned_partner_id=self.partner.id, owner="partner"
        )
        self._activity()
        self.assertEqual(self._visits(), 2)

    def test_a_partner_s_held_slot_is_never_handed_to_a_staff_booking(self):
        CoreActivitySlot.objects.filter(id=self._slot("v", 1).id).update(
            status="Assigned", assigned_partner_id=self.partner.id, owner="partner"
        )
        with self.captureOnCommitCallbacks(execute=True):
            slot = CorePackageSchedulingService._free_slot(self.plan, "visit", 1)
        self.assertEqual(slot.sequence_number, 2)


class TheVisitGateCountsLinkedVisitsTest(_PackageFixture):
    def test_a_linked_school_visit_is_a_staff_core_visit(self):
        from apps.planning.visit_gate import visit_gate

        self._activity(delivery_type="staff")
        gate = visit_gate(self.school, self.fy)
        self.assertEqual(gate.staff_visits, 1)


class PartnerHandoversHoldTheirSlotTest(_PackageFixture):
    def setUp(self):
        super().setUp()
        self.partner_user = User.objects.create(
            id="cred-partner-user",
            email="cred-partner@edify.org",
            name="Credit Partner User",
            roles=["Partner"],
            active_role="Partner",
            is_active=True,
        )
        self.partner.user_id = self.partner_user.id
        self.partner.save(update_fields=["user_id"])

    def _handover(self, **fields):
        from apps.partners.services import create_assignment

        return create_assignment(
            school=self.school,
            partner=self.partner,
            assigning_staff_id="cred-staff",
            expected_activity_type=fields.pop("expected_activity_type", "school_visit"),
            **fields,
        )

    def test_a_planning_page_handover_holds_the_next_visit(self):
        handover = self._handover()

        slot = self._slot("v", 1)
        self.assertEqual(
            (slot.status, slot.assigned_partner_id), ("Assigned", self.partner.id)
        )
        self.assertEqual(self._visits(), 1)
        # The handover is not rewritten: the once-per-partner rule reads those columns.
        handover.refresh_from_db()
        self.assertFalse(handover.visit_number or handover.support_type)

    def test_the_gate_counts_it_on_the_partner_s_side(self):
        from apps.planning.visit_gate import visit_gate

        self._handover()
        self.assertEqual(visit_gate(self.school, self.fy).partner_pending, 1)

    def test_the_partner_s_dated_visit_takes_the_slot_it_held(self):
        self._activity("school_visit", on=date.today() + timedelta(days=1))  # V1
        handover = self._handover()  # holds V2
        self.assertEqual(self._slot("v", 2).status, "Assigned")

        visit = self._activity(
            delivery_type="partner", assigned_partner_id=self.partner.id
        )
        handover.status = "partner_scheduled"
        handover.scheduled_activity = visit
        handover.save(update_fields=["status", "scheduled_activity", "updated_at"])

        self.assertEqual(self._slot("v", 2).activity_id, visit.id)
        self.assertEqual(self._visits(), 2)

    def test_a_returned_handover_gives_its_slot_back(self):
        from apps.partners.services import return_assignment

        handover = self._handover()
        return_assignment(
            handover.id,
            {
                "reason_category": "school_unavailable",
                "reason": "The school is closed for the whole of that term break.",
            },
            self.partner_user,
        )

        slot = self._slot("v", 1)
        self.assertEqual((slot.status, slot.assigned_partner_id), ("Planned", None))
        self.assertEqual(self._visits(), 0)

    def test_a_core_page_handover_withdrawn_before_scheduling_reopens_its_slot(self):
        from apps.accounts.models import StaffProfile
        from apps.core.rbac import EdifyRole
        from apps.partners import withdrawal_service
        from apps.partners.withdrawal_models import (
            WithdrawalDisposition,
            WithdrawalReason,
        )

        pl = User.objects.create(
            email="cred-pl@edify.org",
            name="Credit PL",
            roles=[EdifyRole.COUNTRY_PROGRAM_LEAD.value],
            active_role=EdifyRole.COUNTRY_PROGRAM_LEAD.value,
            status="active",
            is_active=True,
        )
        StaffProfile.objects.create(user=pl, title="Credit PL")
        handover = self._handover(support_type="Visit", visit_number="3")
        CorePackageSchedulingService.commit_assign(
            self._slot("v", 3),
            partner_id=self.partner.id,
            partner_name=self.partner.name,
        )
        self.assertEqual(self._visits(), 1)

        withdrawal_service.withdraw(
            handover.id,
            {
                "reason_category": WithdrawalReason.NOT_SCHEDULED,
                "partner_facing_reason": "The partner has not scheduled this in time.",
                "disposition": WithdrawalDisposition.RETURN_TO_PLANNING,
            },
            pl,
        )

        self.assertEqual(self._slot("v", 3).status, "Planned")
        self.assertEqual(self._visits(), 0)


@freeze_time("2026-05-25")
class PartnerSchedulingNeverTakesABookedSlotTest(TestCase):
    """A Planning-page handover names no slot. Scheduling it read as
    "training" number "1" and took T1 from the training already there, which
    then lost its link and its T1 on My Plan."""

    def setUp(self):
        from apps.accounts.models import StaffProfile
        from apps.core.rbac import EdifyRole
        from apps.geography.models import SubCounty

        region = Region.objects.create(name="Hijack Region")
        district = District.objects.create(name="Hijack District", region=region)
        sub_county = SubCounty.objects.create(name="Hijack Sub", district=district)
        self.school = School.objects.create(
            school_id="HIJ-1",
            name="Hijack Core Primary",
            school_type="core",
            region=region,
            district=district,
            sub_county=sub_county,
            enrollment=300,
        )
        self.plan = CorePlan.objects.create(
            id=cplan_id("HIJ-1", fy="2026"), school_id="HIJ-1", fy="2026"
        )
        create_package_slots(self.plan, "HIJ-1", ["leadership"])
        cceo = User.objects.create_user(
            email="hij-cceo@core.test",
            name="Hijack CCEO",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="pwd",
            is_active=True,
        )
        self.cceo_staff = StaffProfile.objects.create(user=cceo, title="CCEO")
        self.partner_user = User.objects.create_user(
            email="hij-partner@core.test",
            name="Hijack Partner User",
            roles=[EdifyRole.PARTNER_FIELD_OFFICER.value],
            active_role=EdifyRole.PARTNER_FIELD_OFFICER.value,
            password="pwd",
            is_active=True,
        )
        self.partner = Partner.objects.create(
            name="Hijack Partner",
            user=self.partner_user,
            active_status=True,
            contract_status="active",
            source="test",
        )

    def test_an_unnamed_handover_does_not_take_T1_from_a_booked_training(self):
        from apps.activities.services import partner_schedule

        training = Activity.objects.create(
            activity_type="in_school_training",
            school=self.school,
            fy="2026",
            quarter="Q3",
            planned_date=date(2026, 6, 10),
            status="scheduled",
        )
        CoreActivitySlot.objects.filter(id=cslot_id("HIJ-1", "t", 1, fy="2026")).update(
            activity_id=training.id, status="Scheduled", owner="staff"
        )
        handover = PartnerAssignment.objects.create(
            school=self.school,
            partner=self.partner,
            assigning_staff_id=self.cceo_staff.id,
            focus_intervention="leadership",
            expected_activity_type="school_visit",
            status="assigned",
        )

        with self.captureOnCommitCallbacks(execute=True):
            result = partner_schedule(
                handover.id,
                {"scheduledDate": "2026-07-15T10:00:00Z"},
                self.partner_user,
            )

        t1 = CoreActivitySlot.objects.get(id=cslot_id("HIJ-1", "t", 1, fy="2026"))
        self.assertEqual(t1.activity_id, training.id, "T1 stays the training's")
        visit_slot = CoreActivitySlot.objects.get(activity_id=result["id"])
        self.assertEqual(
            (visit_slot.activity_type, visit_slot.sequence_number), ("visit", 1)
        )


class ExistingWorkIsBroughtIntoItsPackageTest(_PackageFixture):
    def test_the_repair_links_unlinked_work_oldest_first(self):
        later = Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            fy=self.fy,
            quarter="Q1",
            planned_date=date.today() - timedelta(days=2),
            status="completed",
        )
        earlier = Activity.objects.create(
            activity_type="coaching_visit",
            school=self.school,
            fy=self.fy,
            quarter="Q1",
            planned_date=date.today() - timedelta(days=20),
            status="completed",
        )
        dry = repair_package_links(apply=False)
        self.assertEqual(set(dry["credited"]), {later.id, earlier.id})
        self.assertFalse(CoreActivitySlot.objects.filter(activity_id=later.id))

        repair_package_links(apply=True)

        self.assertEqual(self._slot("v", 1).activity_id, earlier.id)
        self.assertEqual(self._slot("v", 2).activity_id, later.id)
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.visits_completed, 2)

    def test_the_repair_releases_a_slot_no_partner_holds_any_more(self):
        CoreActivitySlot.objects.filter(id=self._slot("v", 4).id).update(
            status="Assigned", assigned_partner_id=self.partner.id, owner="partner"
        )
        report = repair_package_links(apply=True)
        self.assertEqual(report["released"], [self._slot("v", 4).id])
        self.assertEqual(self._slot("v", 4).status, "Planned")
