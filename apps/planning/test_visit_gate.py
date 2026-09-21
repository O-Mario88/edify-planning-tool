"""The gate counts a school's visits; since 2026-09-21 it refuses none of them.

Owner, 2026-09-21: "can you lift restriction to school visits especially
client school visit. All restrictions. right now it is restricting returning
error and not scheduling."

So what these tests hold is the pair of statements the module now makes:

* the COUNTS are unchanged and still right — which work uses a client school's
  follow-up visit, which is in-school work that never did, how a core school's
  four visits split between staff and partner, and what a live partner
  assignment means. Every page reads those numbers to SHOW where a school's
  visiting has reached;
* and no count is a permission any more. `staff_can_schedule`,
  `partner_can_schedule`, `can_assign_partner` and `can_assign_visit` stay
  open with empty reasons however much of the year's support is already
  scheduled, the `assert_*` helpers return instead of raising, and the drawers
  and queues behind them offer a live button rather than a greyed one with a
  tooltip.

The cap constants are still named and still carry the owner's numbers, because
a count shown without the figure it is counted against says nothing: a Core
Schools row reads "1/2 visits" from them. The tests below therefore count to
CLIENT_VISIT_CAP rather than to a literal, and assert that reaching it changes
what the row says and not what it permits.

The gate (apps.planning.visit_gate) is the one definition the buttons and the
services share, so the tests drive it directly and then check that both
readers agree with it.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSchoolAssignment
from apps.activities.models import Activity
from apps.clusters.models import Cluster
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region, SubCounty
from apps.partners.models import Partner, PartnerAssignment
from apps.planning.visit_gate import (
    CLIENT_VISIT_CAP,
    CORE_PARTNER_VISIT_CAP,
    CORE_STAFF_VISIT_CAP,
    visit_gate,
    visit_gates,
)
from apps.schools.models import School

User = get_user_model()


def _staff(uid, role, name):
    user = User.objects.create(
        id=uid,
        email=f"{uid}@edify.org",
        name=name,
        roles=[role],
        active_role=role,
        is_active=True,
    )
    return user, StaffProfile.objects.create(
        id=f"{uid}-sp", user=user, title=role, country="Uganda"
    )


class _GateFixture:
    """Deliberately not a TestCase: subclassing one test class from another
    makes the parent's tests run a second time under the child's name."""

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="VG Region")
        cls.district = District.objects.create(name="VG District", region=cls.region)
        cls.sub_county = SubCounty.objects.create(name="VG SC", district=cls.district)
        cls.cluster = Cluster.objects.create(
            name="VG Cluster",
            region=cls.region,
            district=cls.district,
            sub_county=cls.sub_county,
            cluster_type="mixed",
            status="active",
        )
        cls.cceo_user, cls.cceo = _staff("vg-cceo", "CCEO", "VG CCEO")
        cls.partner_user = User.objects.create(
            id="vg-partner-user",
            email="vg-partner@edify.org",
            name="VG Partner User",
            roles=["PartnerFieldOfficer"],
            active_role="PartnerFieldOfficer",
            is_active=True,
        )
        cls.partner = Partner.objects.create(
            name="VG Partner Org", user_id=cls.partner_user.id
        )
        cls.fy = get_operational_fy()

    def _school(self, code, school_type="client"):
        school = School.objects.create(
            school_id=code,
            name=f"School {code}",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            school_type=school_type,
            account_owner_id=self.cceo.id,
            cluster_id=self.cluster.id,
            cluster_status="clustered",
        )
        StaffSchoolAssignment.objects.create(staff=self.cceo, school_id=school.id)
        return school

    def _visit(
        self, school, *, delivery="staff", status="scheduled", fy=None, kind=None
    ):
        when = date.today() + timedelta(days=7)
        return Activity.objects.create(
            activity_type=kind
            or ("core_visit" if school.school_type == "core" else "school_visit"),
            delivery_type=delivery,
            status=status,
            fy=fy or self.fy,
            school=school,
            responsible_staff_id=None if delivery == "partner" else self.cceo.id,
            assigned_partner_id=self.partner.id if delivery == "partner" else None,
            planned_date=when,
            scheduled_date=when,
        )

    def _spend_client_visits(self, school, *, delivery="staff", **kw):
        """Use up a client school's whole follow-up allowance.

        The tests below are about the gate closing once the allowance is gone,
        so they say that rather than scheduling a fixed number of visits and
        relying on the cap being what it was when they were written.
        """
        return [
            self._visit(school, delivery=delivery, **kw)
            for _ in range(CLIENT_VISIT_CAP)
        ]

    def _assign(self, school, status=PartnerAssignment.STATUS_PENDING_SCHEDULING, **kw):
        return PartnerAssignment.objects.create(
            school=school,
            partner=self.partner,
            assigning_staff_id=self.cceo.id,
            status=status,
            **kw,
        )


class ClientSchoolVisitAllowanceTest(_GateFixture, TestCase):
    def test_an_unvisited_school_is_open_to_everyone(self):
        gate = visit_gate(self._school("VG-1"))
        self.assertEqual(gate.rule, "client")
        self.assertTrue(gate.staff_can_schedule)
        self.assertTrue(gate.partner_can_schedule)
        self.assertTrue(gate.can_assign_partner)

    def test_spending_the_allowance_counts_it_and_refuses_nothing(self):
        school = self._school("VG-2")
        self._spend_client_visits(school)
        gate = visit_gate(school)
        # The count is the point: the row can say "2 of 2" from it.
        self.assertEqual(gate.staff_visits, CLIENT_VISIT_CAP)
        self.assertEqual(gate.total_visits, CLIENT_VISIT_CAP)
        self.assertEqual(gate.staff_cap, CLIENT_VISIT_CAP)
        # And every door stays open, with nothing to put in a tooltip.
        self.assertTrue(gate.staff_can_schedule)
        self.assertTrue(gate.partner_can_schedule)
        self.assertTrue(gate.can_assign_visit)
        self.assertTrue(gate.can_assign_partner)
        self.assertFalse(gate.staff_locked)
        self.assertEqual(gate.staff_reason, "")
        self.assertEqual(gate.partner_reason, "")
        self.assertEqual(gate.assign_visit_reason, "")

    def test_a_third_visit_past_the_allowance_is_still_open(self):
        """Nothing closes at the cap, so nothing closes past it either."""
        school = self._school("VG-2b")
        self._spend_client_visits(school)
        self._visit(school)
        gate = visit_gate(school)
        self.assertEqual(gate.total_visits, CLIENT_VISIT_CAP + 1)
        self.assertTrue(gate.staff_can_schedule)
        self.assertEqual(gate.staff_reason, "")

    def test_a_partners_visits_are_counted_on_their_own_side(self):
        school = self._school("VG-3")
        self._spend_client_visits(school, delivery="partner")
        gate = visit_gate(school)
        self.assertEqual(gate.partner_visits, CLIENT_VISIT_CAP)
        self.assertEqual(gate.staff_visits, 0)
        self.assertTrue(gate.staff_can_schedule)

    def test_completed_visits_still_count(self):
        school = self._school("VG-4")
        self._spend_client_visits(school, status="completed")
        gate = visit_gate(school)
        self.assertEqual(gate.total_visits, CLIENT_VISIT_CAP)
        self.assertTrue(gate.staff_can_schedule)

    def test_a_cancelled_visit_and_last_years_visit_do_not_count(self):
        school = self._school("VG-5")
        self._visit(school, status="cancelled")
        self._visit(school, fy=str(int(self.fy) - 1))
        gate = visit_gate(school)
        self.assertTrue(gate.staff_can_schedule)
        self.assertEqual(gate.total_visits, 0)

    def test_in_school_work_and_social_visits_are_not_the_visit(self):
        school = self._school("VG-6")
        self._visit(school, kind="in_school_training")
        self._visit(school, kind="in_school_coaching_visit")
        self._visit(school, kind="donor_visit")
        self._visit(school, kind="story_gathering_visit")
        # The companion visit an in-school training pair records.
        companion = self._visit(school, kind="school_visit")
        companion.purpose_type = "in_school_training_delivery_visit"
        companion.save(update_fields=["purpose_type"])
        gate = visit_gate(school)
        self.assertTrue(gate.staff_can_schedule)
        self.assertEqual(gate.total_visits, 0)

    def test_a_follow_up_or_ssa_visit_counts(self):
        school = self._school("VG-6b")
        self._spend_client_visits(
            school, kind="training_follow_up_visit", delivery="partner"
        )
        self.assertEqual(visit_gate(school).partner_visits, CLIENT_VISIT_CAP)
        other = self._school("VG-6c")
        self._spend_client_visits(other, kind="school_visit_ssa_collection")
        self.assertEqual(visit_gate(other).staff_visits, CLIENT_VISIT_CAP)

    def test_a_school_with_a_partner_is_named_not_closed(self):
        """The partner holding a school is worth SAYING on the row.

        Until 2026-09-21 it also locked staff out of the school until the
        partner returned it. It no longer does: `partner_pending` and
        `partner_name` are reported so the row can name who holds it, and
        the buttons stay live beside that.
        """
        school = self._school("VG-7")
        self._assign(school)
        gate = visit_gate(school)
        self.assertEqual(gate.partner_pending, 1)
        self.assertEqual(gate.partner_name, "VG Partner Org")
        self.assertTrue(gate.staff_can_schedule)
        self.assertFalse(gate.staff_locked)
        self.assertEqual(gate.staff_locked_reason, "")
        self.assertTrue(gate.partner_can_schedule)
        self.assertTrue(gate.can_assign_partner)
        self.assertTrue(gate.can_assign_visit)

    def test_a_returned_school_is_no_longer_pending(self):
        school = self._school("VG-8")
        self._assign(school, status=PartnerAssignment.STATUS_RETURNED_TO_STAFF)
        gate = visit_gate(school)
        self.assertEqual(gate.partner_pending, 0)
        self.assertTrue(gate.staff_can_schedule)
        self.assertTrue(gate.can_assign_partner)

    def test_core_trained_schools_follow_the_client_rule_and_champions_neither(self):
        trained = self._school("VG-9", school_type="core_trained")
        champion = self._school("VG-10", school_type="champion")
        self._spend_client_visits(trained, kind="school_visit")
        self._spend_client_visits(champion, kind="school_visit")
        gates = visit_gates([trained, champion])
        # The rule decides what is COUNTED, which is what still differs.
        self.assertEqual(gates[trained.id].rule, "client")
        self.assertEqual(gates[trained.id].total_visits, CLIENT_VISIT_CAP)
        self.assertEqual(gates[champion.id].rule, "none")
        self.assertEqual(gates[champion.id].total_visits, 0)
        self.assertTrue(gates[trained.id].staff_can_schedule)
        self.assertTrue(gates[champion.id].staff_can_schedule)


class CoreSchoolHasTwoStaffAndTwoPartnerVisitsTest(_GateFixture, TestCase):
    def test_the_two_halves_of_the_package_are_counted_and_capped_by_neither(self):
        school = self._school("VG-C1", school_type="core")
        self._visit(school)
        gate = visit_gate(school)
        self.assertEqual(gate.rule, "core")
        self.assertEqual(gate.staff_visits, 1)
        self.assertEqual(gate.staff_cap, CORE_STAFF_VISIT_CAP)
        self.assertTrue(gate.staff_can_schedule)
        self._visit(school)
        gate = visit_gate(school)
        self.assertEqual(gate.staff_visits, CORE_STAFF_VISIT_CAP)
        # The package is full and the Schedule button is still live.
        self.assertTrue(gate.staff_can_schedule)
        self.assertEqual(gate.staff_reason, "")
        self.assertTrue(gate.partner_can_schedule)
        self.assertTrue(gate.can_assign_partner)

    def test_the_partner_half_counts_assigned_slots_as_well_as_scheduled_ones(self):
        school = self._school("VG-C2", school_type="core")
        self._visit(school, delivery="partner")
        self._assign(school, support_type="Visit", visit_number="2")
        gate = visit_gate(school)
        self.assertEqual(gate.partner_visits, 1)
        self.assertEqual(gate.partner_pending, 1)
        self.assertEqual(gate.partner_held_visits, CORE_PARTNER_VISIT_CAP)
        self.assertEqual(gate.partner_cap, CORE_PARTNER_VISIT_CAP)
        # A full partner half no longer closes the Assign button.
        self.assertTrue(gate.can_assign_partner)
        self.assertEqual(gate.assign_reason, "")
        self.assertTrue(gate.partner_can_schedule)
        self.assertTrue(gate.staff_can_schedule)

    def test_the_partners_scheduled_visits_are_counted(self):
        school = self._school("VG-C3", school_type="core")
        self._visit(school, delivery="partner")
        self._visit(school, delivery="partner")
        gate = visit_gate(school)
        self.assertEqual(gate.partner_visits, CORE_PARTNER_VISIT_CAP)
        self.assertTrue(gate.partner_can_schedule)
        self.assertEqual(gate.partner_reason, "")

    def test_a_training_assignment_does_not_use_a_visit_slot(self):
        school = self._school("VG-C4", school_type="core")
        self._assign(school, support_type="Training", training_number="1")
        gate = visit_gate(school)
        self.assertEqual(gate.partner_pending, 0)
        self.assertEqual(gate.partner_pending_trainings, 1)
        self.assertTrue(gate.can_assign_partner)

    def test_trainings_are_counted_apart_and_their_entry_stays_open(self):
        school = self._school("VG-C5", school_type="core")
        self._visit(school)
        self._visit(school)
        gate = visit_gate(school)
        self.assertEqual(gate.staff_trainings, 0)
        self.assertTrue(gate.staff_trainings_open)
        self._visit(school, kind="core_training")
        self._visit(school, kind="core_training")
        gate = visit_gate(school)
        self.assertEqual(gate.staff_trainings, CORE_STAFF_VISIT_CAP)
        # It used to close here. A core school's Training entry now stays
        # open however many have been delivered (owner, 2026-09-21).
        self.assertTrue(gate.staff_trainings_open)


class TheServicesScheduleWhatTheButtonsOfferTest(_GateFixture, TestCase):
    """The two readers of the gate, agreeing that nothing is refused."""

    def _entitlement(self, school, **data):
        from apps.activities.services import _assert_schedule_entitlement

        _assert_schedule_entitlement("school_visit", school, self.fy, data)

    def test_a_visit_past_the_allowance_is_scheduled(self):
        school = self._school("VG-S1")
        self._spend_client_visits(school)
        self._entitlement(school)  # no BadRequest

    def test_the_first_visit_and_in_school_work_pass(self):
        from apps.activities.services import _assert_schedule_entitlement

        school = self._school("VG-S2")
        self._entitlement(school)
        self._visit(school)
        _assert_schedule_entitlement("in_school_training", school, self.fy, {})
        _assert_schedule_entitlement("donor_visit", school, self.fy, {})
        # The training pair's companion visit is the training, not a visit.
        _assert_schedule_entitlement(
            "school_visit",
            school,
            self.fy,
            {"purposeType": "in_school_training_delivery_visit"},
        )

    def test_a_pending_request_neither_uses_the_visit_nor_blocks_approval(self):
        """A request filed before the lift is still decidable, and approving
        it no longer runs into a cap that would refuse it."""
        from apps.activities.services import _assert_schedule_entitlement
        from apps.planning import visit_requests

        school = self._school("VG-S0")
        self._spend_client_visits(school)
        _assert_schedule_entitlement(
            "school_visit", school, self.fy, {}, is_request=True
        )
        request = self._visit(school, status=visit_requests.AWAITING)
        request.approval_owner_id = self.cceo.id
        request.save(update_fields=["approval_owner_id"])
        # The pending request is not one of the counted visits.
        self.assertEqual(visit_gate(school).total_visits, CLIENT_VISIT_CAP)
        approved = visit_requests.approve(request.id, self.cceo_user)
        self.assertEqual(approved.status, "scheduled")
        self.assertEqual(visit_gate(school).total_visits, CLIENT_VISIT_CAP + 1)

    def test_staff_may_schedule_a_school_that_is_with_a_partner(self):
        school = self._school("VG-S3")
        self._assign(school)
        self._entitlement(school)  # no BadRequest

    def test_the_planning_row_keeps_its_buttons_live(self):
        from apps.planning.planning_service import PlanningDashboardService

        visited = self._school("VG-S4")
        self._spend_client_visits(visited)
        handed = self._school("VG-S5")
        self._assign(handed)
        self._school("VG-S6")

        def rows_on(tab):
            return {
                row["schoolId"]: row
                for row in PlanningDashboardService.get_dashboard_data(
                    self.cceo_user,
                    {"fy": self.fy, "tab": tab, "page": 1, "per_page": 50},
                )["schools"]
            }

        # The client tab lists only the schools still to be planned; the
        # visited school sits on the Scheduled tab and the handed-over one on
        # the Partner tab. Which tab a school sits on is a description of
        # where its visiting has reached, and that much has not changed.
        self.assertEqual(sorted(rows_on("client")), ["VG-S6"])
        rows = {**rows_on("scheduled"), **rows_on("partner"), **rows_on("client")}
        self.assertIn("VG-S4", rows, sorted(rows))
        for code in ("VG-S4", "VG-S5", "VG-S6"):
            self.assertTrue(rows[code]["staffCanSchedule"], code)
            self.assertTrue(rows[code]["canAssignPartner"], code)
            self.assertEqual(rows[code]["staffScheduleReason"], "", code)
        # The follow-up purpose is open at the spent school too.
        self.assertTrue(rows["VG-S4"]["followUpVisitOpen"])
        self.assertEqual(rows["VG-S4"]["followUpVisitReason"], "")

    def test_the_planning_page_opens_the_drawer_for_a_partner_held_school(self):
        handed = self._school("VG-S7")
        self._assign(handed)
        self.client.force_login(self.cceo_user)
        response = self.client.get("/planning?tab=partner")
        self.assertEqual(response.status_code, 200, response.get("Location"))
        html = response.content.decode()
        self.assertIn("VG-S7", html)
        self.assertNotIn('data-visit-locked="true"', html)
        self.assertNotIn("Only the partner can schedule it", html)
        response = self.client.get(
            f"/planning/schedule-modal?school_id={handed.school_id}"
        )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertNotIn("Only the partner can schedule it", html)
        self.assertIn('name="purpose_of_visit"', html)

    def test_the_drawers_offer_the_follow_up_purposes_once_it_is_spent(self):
        visited = self._school("VG-S8")
        self._spend_client_visits(visited)
        self.client.force_login(self.cceo_user)
        response = self.client.get(
            f"/planning/schedule-modal?school_id={visited.school_id}"
        )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('name="purpose_of_visit"', html)
        self.assertNotIn('value="training_follow_up" disabled', html)
        self.assertNotIn('value="ssa_support" disabled', html)
        self.assertNotIn('value="in_school_training" disabled', html)
        # And the assign drawer likewise.
        response = self.client.get(
            f"/planning/assign-partner-modal?school_id={visited.school_id}"
        )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertNotIn('value="training_follow_up" disabled', html)
        self.assertNotIn('value="in_school_training" disabled', html)

    def test_the_partner_queue_keeps_schedule_live_once_it_is_spent(self):
        school = self._school("VG-S9")
        self._spend_client_visits(school)
        assignment = self._assign(school)
        self.client.force_login(self.partner_user)
        response = self.client.get("/partner/assigned-schools")
        self.assertEqual(response.status_code, 200, response.get("Location"))
        html = response.content.decode()
        self.assertIn("School VG-S9", html)
        self.assertNotIn('data-visit-locked="true"', html)
        response = self.client.get(
            f"/partner/assignments/{assignment.id}/schedule-drawer"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('name="scheduled_date"', response.content.decode())

    def test_the_partner_service_schedules_a_visit_past_the_allowance(self):
        from apps.activities.services import _partner_schedule_from_assignment

        school = self._school("VG-S10")
        self._spend_client_visits(school)
        assignment = self._assign(school, expected_activity_type="school_visit")
        when = (date.today() + timedelta(days=10)).isoformat()
        created = _partner_schedule_from_assignment(
            assignment.id,
            {"scheduledDate": when, "deliveryContactName": "VG Visitor"},
            self.partner_user,
        )
        self.assertEqual(created["deliveryType"], "partner")
        # Counted on the partner's side, in the fiscal year the visit falls
        # in — which need not be the one the spent allowance sits in, since
        # ten days out can cross the year boundary.
        self.assertEqual(visit_gate(school, created["fy"]).partner_visits, 1)
