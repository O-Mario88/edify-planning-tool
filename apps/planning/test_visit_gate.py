"""CLIENT_VISIT_CAP follow-up visits a year for a client school; two staff and
two partner visits for a core school; a school handed to a partner is the
partner's to schedule.

Owner, 2026-09-15: "Client school visits: they are supposed to be visited
once in a year, so if a staff or partner has already scheduled it, the
schedule buttons should be disabled. Assigned school to a partner should also
be disabled from staff scheduling — only the partner can schedule it unless
the partner returns the school back to the staff. Core schools should be
scheduled by staff twice for visit and assigned twice to a partner."

The client cap went from one to two on 2026-09-17, so these tests count to
CLIENT_VISIT_CAP rather than to a literal 1: what they are for is that the
gate closes when the allowance is SPENT and that the buttons and the services
agree about when that is, not what the number happens to be.

The gate (apps.planning.visit_gate) is the one definition the greyed buttons
and the refusing services share, so the tests drive it directly and then
check that both readers agree with it.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSchoolAssignment
from apps.activities.models import Activity
from apps.clusters.models import Cluster
from apps.core.exceptions import BadRequest
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

    def test_spending_the_staff_allowance_closes_the_follow_up_visit(self):
        school = self._school("VG-2")
        self._spend_client_visits(school)
        gate = visit_gate(school)
        self.assertFalse(gate.staff_can_schedule)
        self.assertFalse(gate.partner_can_schedule)
        self.assertFalse(gate.can_assign_visit)
        self.assertIn("visits a year", gate.staff_reason)
        self.assertIn("scheduled by staff", gate.staff_reason)
        # The row stays open: in-school training, donor and social visits
        # can still be scheduled or assigned there.
        self.assertFalse(gate.staff_locked)
        self.assertTrue(gate.can_assign_partner)

    def test_a_visit_still_in_hand_leaves_the_row_open(self):
        """The cap is 2 since 2026-09-17, so one visit no longer spends it."""
        school = self._school("VG-2b")
        self._visit(school)
        gate = visit_gate(school)
        self.assertEqual(gate.total_visits, 1)
        self.assertTrue(gate.staff_can_schedule)
        self.assertTrue(gate.partner_can_schedule)

    def test_a_partner_spending_the_allowance_closes_it_too(self):
        school = self._school("VG-3")
        self._spend_client_visits(school, delivery="partner")
        gate = visit_gate(school)
        self.assertFalse(gate.staff_can_schedule)
        self.assertIn("scheduled by a partner", gate.staff_reason)

    def test_completed_visits_still_count_against_the_allowance(self):
        school = self._school("VG-4")
        self._spend_client_visits(school, status="completed")
        self.assertFalse(visit_gate(school).staff_can_schedule)

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

    def test_a_follow_up_or_ssa_visit_counts_against_the_allowance(self):
        school = self._school("VG-6b")
        self._spend_client_visits(
            school, kind="training_follow_up_visit", delivery="partner"
        )
        self.assertFalse(visit_gate(school).staff_can_schedule)
        other = self._school("VG-6c")
        self._spend_client_visits(other, kind="school_visit_ssa_collection")
        self.assertFalse(visit_gate(other).staff_can_schedule)

    def test_a_school_with_a_partner_is_the_partners_to_schedule(self):
        school = self._school("VG-7")
        self._assign(school)
        gate = visit_gate(school)
        self.assertFalse(gate.staff_can_schedule)
        self.assertTrue(gate.staff_locked)
        self.assertIn("VG Partner Org", gate.staff_locked_reason)
        self.assertIn("until they return the school", gate.staff_reason)
        self.assertTrue(gate.partner_can_schedule)
        # The visit is the partner's; an in-school training may still be
        # handed over, so the Assign button itself stays open.
        self.assertTrue(gate.can_assign_partner)
        self.assertFalse(gate.can_assign_visit)
        self.assertIn("already assigned to VG Partner Org", gate.assign_visit_reason)

    def test_a_returned_school_is_the_staffs_again(self):
        school = self._school("VG-8")
        self._assign(school, status=PartnerAssignment.STATUS_RETURNED_TO_STAFF)
        gate = visit_gate(school)
        self.assertTrue(gate.staff_can_schedule)
        self.assertTrue(gate.can_assign_partner)

    def test_every_programme_school_follows_the_client_rule(self):
        """Owner, 2026-09-21: Core Trained, Core Graduate and Champion schools
        "can receive all the activities (visit, trainings) client schools
        should receive". Champion and Core Graduate carried no rule at all
        before, which read as an unlimited entitlement rather than a chosen
        one."""
        schools = [
            self._school("VG-9", school_type="core_trained"),
            self._school("VG-10", school_type="champion"),
            self._school("VG-11", school_type="core_graduate"),
        ]
        for school in schools:
            self._spend_client_visits(school, kind="school_visit")
        gates = visit_gates(schools)
        for school in schools:
            gate = gates[school.id]
            self.assertEqual(gate.rule, "client", school.school_type)
            self.assertFalse(gate.staff_can_schedule, school.school_type)

    def test_a_programme_school_is_never_assigned_to_a_partner(self):
        """The other half of the same instruction: they "cannot be assigned to
        partner", whatever the year's counts say."""
        for index, school_type in enumerate(
            ("core_trained", "champion", "core_graduate")
        ):
            school = self._school(f"VG-P{index}", school_type=school_type)
            gate = visit_gate(school)
            self.assertFalse(gate.can_assign_partner, school_type)
            self.assertFalse(gate.partner_can_schedule, school_type)
            self.assertIn("never assigned to a partner", gate.assign_reason)

    def test_the_partner_creation_door_refuses_a_programme_school(self):
        """The drawers grey the control; the one creation door refuses it, so
        a bulk path or an API client cannot walk around the rule."""
        from apps.core.exceptions import BadRequest
        from apps.partners import services as partner_services

        school = self._school("VG-P9", school_type="champion")
        with self.assertRaises(BadRequest) as ctx:
            partner_services.create_assignment(
                school=school,
                partner=self.partner,
                assigning_staff_id=self.cceo.id,
                assignment_mode="specific_activity",
            )
        self.assertIn("never assigned to a partner", str(ctx.exception.detail))


class CoreSchoolHasTwoStaffAndTwoPartnerVisitsTest(_GateFixture, TestCase):
    def test_staff_stop_at_two_visits(self):
        school = self._school("VG-C1", school_type="core")
        self._visit(school)
        gate = visit_gate(school)
        self.assertEqual(gate.rule, "core")
        self.assertTrue(gate.staff_can_schedule)
        self._visit(school)
        gate = visit_gate(school)
        self.assertEqual(gate.staff_visits, CORE_STAFF_VISIT_CAP)
        self.assertFalse(gate.staff_can_schedule)
        self.assertIn("Staff core visits complete", gate.staff_reason)
        # The partner's half is untouched.
        self.assertTrue(gate.partner_can_schedule)
        self.assertTrue(gate.can_assign_partner)

    def test_the_partner_half_counts_assigned_slots_as_well_as_scheduled_ones(self):
        school = self._school("VG-C2", school_type="core")
        self._visit(school, delivery="partner")
        self._assign(school, support_type="Visit", visit_number="2")
        gate = visit_gate(school)
        self.assertEqual(gate.partner_visits, 1)
        self.assertEqual(gate.partner_pending, 1)
        self.assertFalse(gate.can_assign_partner)
        self.assertIn("already assigned", gate.assign_reason)
        # The assigned slot is still the partner's to schedule.
        self.assertTrue(gate.partner_can_schedule)
        # Staff are not locked out by a partner assignment at a core school.
        self.assertTrue(gate.staff_can_schedule)

    def test_the_partner_stops_at_two_scheduled_visits(self):
        school = self._school("VG-C3", school_type="core")
        self._visit(school, delivery="partner")
        self._visit(school, delivery="partner")
        gate = visit_gate(school)
        self.assertEqual(gate.partner_visits, CORE_PARTNER_VISIT_CAP)
        self.assertFalse(gate.partner_can_schedule)
        self.assertIn("Partner core visits complete", gate.partner_reason)

    def test_a_training_assignment_does_not_use_a_visit_slot(self):
        school = self._school("VG-C4", school_type="core")
        self._assign(school, support_type="Training", training_number="1")
        gate = visit_gate(school)
        self.assertEqual(gate.partner_pending, 0)
        self.assertEqual(gate.partner_pending_trainings, 1)
        self.assertTrue(gate.can_assign_partner)

    def test_trainings_are_not_visits_and_keep_their_own_entry(self):
        school = self._school("VG-C5", school_type="core")
        self._visit(school)
        self._visit(school)
        gate = visit_gate(school)
        self.assertFalse(gate.staff_can_schedule)
        self.assertTrue(gate.staff_trainings_open)
        self._visit(school, kind="core_training")
        self._visit(school, kind="core_training")
        self.assertFalse(visit_gate(school).staff_trainings_open)


class TheServicesRefuseWhatTheButtonsGreyOutTest(_GateFixture, TestCase):
    def _entitlement(self, school, **data):
        from apps.activities.services import _assert_schedule_entitlement

        _assert_schedule_entitlement("school_visit", school, self.fy, data)

    def test_a_visit_past_the_allowance_is_refused_with_the_gates_sentence(self):
        school = self._school("VG-S1")
        self._spend_client_visits(school)
        with self.assertRaises(BadRequest) as ctx:
            self._entitlement(school)
        self.assertIn("visits a year", str(ctx.exception.detail))

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

    def test_a_visit_request_neither_uses_the_visit_nor_is_refused_until_approved(
        self,
    ):
        from apps.activities.services import _assert_schedule_entitlement
        from apps.planning import visit_requests

        school = self._school("VG-S0")
        self._spend_client_visits(school)
        # Filing a request at a visited school is allowed…
        _assert_schedule_entitlement(
            "school_visit", school, self.fy, {}, is_request=True
        )
        request = self._visit(school, status=visit_requests.AWAITING)
        request.approval_owner_id = self.cceo.id
        request.save(update_fields=["approval_owner_id"])
        # The pending request is not one of them.
        self.assertEqual(visit_gate(school).total_visits, CLIENT_VISIT_CAP)
        # …but approving it is where the rule bites.
        with self.assertRaises(BadRequest) as ctx:
            visit_requests.approve(request.id, self.cceo_user)
        self.assertIn("visits a year", str(ctx.exception.detail))

    def test_staff_cannot_schedule_a_school_that_is_with_a_partner(self):
        school = self._school("VG-S3")
        self._assign(school)
        with self.assertRaises(BadRequest) as ctx:
            self._entitlement(school)
        self.assertIn("Only the partner can schedule it", str(ctx.exception.detail))

    def test_the_planning_row_greys_the_buttons_with_the_reason(self):
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
        # the Partner tab.
        self.assertEqual(sorted(rows_on("client")), ["VG-S6"])
        rows = {**rows_on("scheduled"), **rows_on("partner"), **rows_on("client")}
        self.assertIn("VG-S4", rows, sorted(rows))
        # Visited: the row stays open for in-school training and social
        # visits; the follow-up purpose is what is used.
        self.assertTrue(rows["VG-S4"]["staffCanSchedule"])
        self.assertFalse(rows["VG-S4"]["followUpVisitOpen"])
        self.assertIn("visits a year", rows["VG-S4"]["followUpVisitReason"])
        self.assertTrue(rows["VG-S4"]["canAssignPartner"])
        # With a partner: the whole row is the partner's.
        self.assertFalse(rows["VG-S5"]["staffCanSchedule"])
        self.assertIn("VG Partner Org", rows["VG-S5"]["staffScheduleReason"])
        self.assertTrue(rows["VG-S5"]["canAssignPartner"])
        self.assertTrue(rows["VG-S6"]["staffCanSchedule"])
        self.assertTrue(rows["VG-S6"]["canAssignPartner"])

    def test_the_planning_page_greys_the_row_of_a_partner_held_school(self):
        handed = self._school("VG-S7")
        self._assign(handed)
        self.client.force_login(self.cceo_user)
        response = self.client.get("/planning?tab=partner")
        self.assertEqual(response.status_code, 200, response.get("Location"))
        html = response.content.decode()
        self.assertIn("VG-S7", html)
        self.assertIn('data-visit-locked="true"', html)
        self.assertIn("Only the partner can schedule it", html)
        response = self.client.get(
            f"/planning/schedule-modal?school_id={handed.school_id}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Only the partner can schedule it", response.content.decode())
        self.assertNotIn('name="purpose_of_visit"', response.content.decode())

    def test_the_drawers_grey_the_follow_up_purposes_once_it_is_spent(self):
        visited = self._school("VG-S8")
        self._spend_client_visits(visited)
        self.client.force_login(self.cceo_user)
        response = self.client.get(
            f"/planning/schedule-modal?school_id={visited.school_id}"
        )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('name="purpose_of_visit"', html)
        self.assertIn("data-visit-locked-reason", html)
        self.assertIn("visits a year", html)
        self.assertIn('value="training_follow_up" disabled', html)
        self.assertIn('value="ssa_support" disabled', html)
        self.assertNotIn('value="in_school_training" disabled', html)
        self.assertNotIn('value="donor_visit" disabled', html)
        # And the assign drawer likewise: an in-school training can still be
        # handed to a partner, the follow-up visit cannot.
        response = self.client.get(
            f"/planning/assign-partner-modal?school_id={visited.school_id}"
        )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('value="training_follow_up" disabled', html)
        self.assertNotIn('value="in_school_training" disabled', html)

    def test_the_partner_queue_greys_schedule_once_it_is_spent(self):
        school = self._school("VG-S9")
        self._spend_client_visits(school)
        assignment = self._assign(school)
        self.client.force_login(self.partner_user)
        response = self.client.get("/partner/assigned-schools")
        self.assertEqual(response.status_code, 200, response.get("Location"))
        html = response.content.decode()
        self.assertIn("School VG-S9", html)
        self.assertIn('data-visit-locked="true"', html)
        self.assertIn("visits a year", html)
        response = self.client.get(
            f"/partner/assignments/{assignment.id}/schedule-drawer"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("visits a year", response.content.decode())
        self.assertNotIn('name="scheduled_date"', response.content.decode())

    def test_the_partner_service_refuses_a_visit_past_the_allowance(self):
        from apps.activities.services import _partner_schedule_from_assignment

        school = self._school("VG-S10")
        # The allowance is counted in the fiscal year the PARTNER's date falls
        # in, so the visits that spend it have to be booked in that same year.
        # Pinning them to today's FY made this test pass for most of the year
        # and fail every late September, when today + 10 days crosses into the
        # next FY and the gate correctly finds an untouched allowance.
        when_on = date.today() + timedelta(days=10)
        self._spend_client_visits(school, fy=get_operational_fy(when_on))
        assignment = self._assign(school, expected_activity_type="school_visit")
        when = when_on.isoformat()
        with self.assertRaises(BadRequest) as ctx:
            _partner_schedule_from_assignment(
                assignment.id,
                {"scheduledDate": when, "deliveryContactName": "VG Visitor"},
                self.partner_user,
            )
        self.assertIn("visits a year", str(ctx.exception.detail))
