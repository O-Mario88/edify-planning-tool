"""The gate: one staff support visit a year at a client school, and little else.

Owner, 2026-09-28: "lift all restrictions. the only restriction is for client
schools to have one visit from the staff. treat core trained just like client
schools." And, asked what else stays: "staff may plan more core schools visits
but only if the partner has not planned."

So what these tests hold:

* the COUNTS are unchanged — which work uses a client school's follow-up
  visit, which is in-school work that never did, how a core school's visits
  split between staff and partner, and what a live partner assignment means;
* at a CLIENT-rule school (client, and the Programme types) staff visits are
  counted in two pools (owner, later the same day): one support visit a year
  — a Training Follow Up or an In-school Training — closes the support
  purposes (`staff_can_schedule`), and one SSA Support a year closes SSA
  Support (`ssa_can_schedule`); donor, story, invitation and social visits
  have no limit, the row's Schedule button stays live, and the partner side
  is counted but never capped;
* Core Trained and Core Graduate schools may be handed to a partner like
  client schools; Champion schools, which take donor and story visits only,
  may not;
* at a CORE school the package is split 2 + 2 (owner, 2026-09-30, replacing
  2026-09-28's "staff may plan more core visits only if the partner has not
  planned"): staff hold two visits and two trainings, the partner side two of
  each, and donor, story, invitation and social visits are not package work.

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


def _schedulable(day: date) -> date:
    """The first day from ``day`` the calendar policy accepts."""
    from apps.core.calendar_policy import SchedulingPolicyService

    for _ in range(21):
        if SchedulingPolicyService.check(None, day)["status"] != "blocked":
            return day
        day += timedelta(days=1)
    raise AssertionError("no schedulable date within three weeks")


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

    def test_the_one_staff_visit_closes_the_follow_up_purposes_only(self):
        school = self._school("VG-2")
        self._spend_client_visits(school)
        gate = visit_gate(school)
        self.assertEqual(CLIENT_VISIT_CAP, 1)
        self.assertEqual(gate.staff_visits, 1)
        self.assertEqual(gate.staff_cap, 1)
        # The support visit is spent: the follow-up purposes close, with the
        # sentence the drawer and the service both say.
        self.assertFalse(gate.staff_can_schedule)
        self.assertIn("staff support visit", gate.staff_reason)
        # The row's Schedule stays live — donor, story, invitation and social
        # visits and In-school Training never use the visit — and the partner
        # side is untouched.
        self.assertFalse(gate.staff_locked)
        self.assertTrue(gate.partner_can_schedule)
        self.assertTrue(gate.can_assign_visit)
        self.assertTrue(gate.can_assign_partner)

    def test_partner_work_is_counted_and_never_capped(self):
        school = self._school("VG-2b")
        for _ in range(3):
            self._visit(school, delivery="partner")
        self._assign(school)
        gate = visit_gate(school)
        self.assertEqual(gate.partner_visits, 3)
        self.assertTrue(gate.partner_can_schedule)
        self.assertTrue(gate.can_assign_partner)
        # A partner's visits are not the staff's one visit.
        self.assertTrue(gate.staff_can_schedule)

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
        self.assertFalse(gate.staff_can_schedule)

    def test_a_cancelled_visit_and_last_years_visit_do_not_count(self):
        school = self._school("VG-5")
        self._visit(school, status="cancelled")
        self._visit(school, fy=str(int(self.fy) - 1))
        gate = visit_gate(school)
        self.assertTrue(gate.staff_can_schedule)
        self.assertEqual(gate.total_visits, 0)

    def test_outreach_and_the_companion_visit_have_no_limit(self):
        """Owner, 2026-09-28: "donor visits and content gathering can be
        scheduled as many as possible. no limit on those" — and, asked, no
        limit on social visits and invitations either."""
        school = self._school("VG-6")
        for kind in (
            "donor_visit",
            "donor_visit",
            "story_gathering_visit",
            "story_gathering_visit",
            "social_visit",
            "school_invitation",
        ):
            self._visit(school, kind=kind)
        # The companion visit an in-school training pair records.
        companion = self._visit(school, kind="school_visit")
        companion.purpose_type = "in_school_training_delivery_visit"
        companion.save(update_fields=["purpose_type"])
        gate = visit_gate(school)
        self.assertTrue(gate.staff_can_schedule)
        self.assertTrue(gate.ssa_can_schedule)
        self.assertEqual(gate.total_visits, 0)
        self.assertEqual(gate.staff_ssa_visits, 0)

    def test_an_in_school_training_is_the_support_visit(self):
        """ "after the support visits (follow up or in-school training)": one
        in total, so an In-school Training closes the Training Follow Up."""
        for code, kind in (
            ("VG-6d", "in_school_training"),
            ("VG-6e", "in_school_coaching_visit"),
            ("VG-6f", "training_follow_up_visit"),
        ):
            school = self._school(code)
            self._visit(school, kind=kind)
            gate = visit_gate(school)
            self.assertEqual(gate.staff_visits, 1, kind)
            self.assertFalse(gate.staff_can_schedule, kind)
            self.assertTrue(gate.ssa_can_schedule, kind)

    def test_data_collection_is_counted_apart_and_never_closed(self):
        """Owner, 2026-10-02: "allow data collection assignment on every
        school irrespective of whether they have the 1 visit by staff or
        partner because those visits don't count." It was one a year from
        2026-09-28 until then."""
        school = self._school("VG-6b")
        self._visit(school, kind="school_visit_ssa_collection")
        self._visit(school, kind="school_visit_ssa_collection")
        gate = visit_gate(school)
        self.assertEqual(gate.staff_ssa_visits, 2)
        self.assertEqual(gate.staff_visits, 0)
        self.assertTrue(gate.ssa_can_schedule)
        self.assertEqual(gate.ssa_reason, "")
        # It is not the school's visit: the support visit is still open.
        self.assertTrue(gate.staff_can_schedule)
        self._visit(school, kind="training_follow_up_visit")
        gate = visit_gate(school)
        self.assertFalse(gate.staff_can_schedule)
        self.assertTrue(gate.ssa_can_schedule)
        self.assertEqual(gate.staff_ssa_visits, 2)

    def test_partner_follow_up_and_ssa_visits_are_counted_not_capped(self):
        school = self._school("VG-6c")
        self._visit(school, kind="training_follow_up_visit", delivery="partner")
        self._visit(school, kind="school_visit_ssa_collection", delivery="partner")
        gate = visit_gate(school)
        self.assertEqual(gate.partner_visits, 1)
        self.assertEqual(gate.partner_ssa_visits, 1)
        self.assertTrue(gate.staff_can_schedule)
        self.assertTrue(gate.ssa_can_schedule)

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

    def test_every_programme_school_follows_the_client_rule(self):
        """Owner, 2026-09-21: Core Trained, Core Graduate and Champion schools
        "can receive all the activities (visit, trainings) client schools
        should receive". Champion and Core Graduate carried no rule at all
        before, which read as an unlimited entitlement rather than a chosen
        one.

        Owner, 2026-09-28: "treat core trained just like client schools" —
        the one staff support visit a year holds for all three."""
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
            self.assertEqual(gate.total_visits, CLIENT_VISIT_CAP, school.school_type)
            self.assertFalse(gate.staff_can_schedule, school.school_type)

    def test_champion_schools_are_never_assigned_to_a_partner(self):
        """They take donor and story visits only (owner, 2026-09-25), which
        no partner delivers. Core Trained and Core Graduate are planned like
        client schools, partner support included (owner, 2026-09-28)."""
        gate = visit_gate(self._school("VG-P0", school_type="champion"))
        self.assertFalse(gate.can_assign_partner)
        self.assertFalse(gate.partner_can_schedule)
        self.assertIn("never assigned to a partner", gate.assign_reason)
        for index, school_type in enumerate(("core_trained", "core_graduate")):
            school = self._school(f"VG-P{7 + index}", school_type=school_type)
            gate = visit_gate(school)
            self.assertTrue(gate.can_assign_partner, school_type)
            self.assertTrue(gate.partner_can_schedule, school_type)

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


class CoreSchoolPackageSplitTest(_GateFixture, TestCase):
    """Owner, 2026-09-30: a Core package is two staff and two partner visits,
    and two staff and two partner trainings (`apps.core_schools.package_split`
    counts it; the gate reads the same count)."""

    def _core(self, code):
        from apps.core_schools.models import CorePlan, cplan_id
        from apps.core_schools.services import create_package_slots

        school = self._school(code, school_type="core")
        plan = CorePlan.objects.create(
            id=cplan_id(code, fy=self.fy), school_id=code, fy=self.fy, status="Active"
        )
        create_package_slots(plan, code, ["leadership"])
        return school

    def test_staff_stop_at_two_visits_whatever_the_partner_has_planned(self):
        school = self._core("VG-C1")
        self._visit(school)
        gate = visit_gate(school)
        self.assertEqual(gate.rule, "core")
        self.assertEqual(gate.staff_cap, CORE_STAFF_VISIT_CAP)
        self.assertTrue(gate.staff_can_schedule)
        self._visit(school)
        gate = visit_gate(school)
        self.assertEqual(gate.staff_visits, CORE_STAFF_VISIT_CAP)
        self.assertFalse(gate.staff_can_schedule)
        self.assertIn("Staff core visits complete", gate.staff_reason)
        self.assertTrue(gate.partner_can_schedule)
        self.assertTrue(gate.can_assign_partner)

    def test_a_waiting_handover_holds_a_partner_visit(self):
        school = self._core("VG-C2")
        self._assign(school, support_type="Visit", visit_number="3")
        self._visit(school, delivery="partner")
        gate = visit_gate(school)
        self.assertEqual(gate.partner_pending, 1)
        self.assertEqual(gate.partner_held_visits, CORE_PARTNER_VISIT_CAP)
        self.assertFalse(gate.can_assign_visit)
        self.assertTrue(gate.staff_can_schedule)
        # The partner's two trainings are still open, so Assign stays live.
        self.assertTrue(gate.can_assign_partner)

    def test_assign_closes_once_the_partner_half_is_held(self):
        school = self._core("VG-C3")
        for _ in range(CORE_PARTNER_VISIT_CAP):
            self._visit(school, delivery="partner")
        self._assign(school, support_type="Training", training_number="1")
        self._visit(school, delivery="partner", kind="in_school_training")
        gate = visit_gate(school)
        self.assertFalse(gate.can_assign_partner)
        self.assertIn("partner's half", gate.assign_reason)
        # Dating a waiting hand-over is asked at its own door, without itself.
        self.assertTrue(gate.partner_can_schedule)

    def test_a_training_assignment_does_not_use_a_visit_slot(self):
        school = self._core("VG-C4")
        self._assign(school, support_type="Training", training_number="1")
        gate = visit_gate(school)
        self.assertEqual(gate.partner_pending, 0)
        self.assertEqual(gate.partner_pending_trainings, 1)
        self.assertTrue(gate.can_assign_partner)

    def test_trainings_are_split_like_visits(self):
        school = self._core("VG-C5")
        self._visit(school, kind="in_school_training")
        self.assertTrue(visit_gate(school).staff_trainings_open)
        self._visit(school, kind="in_school_training")
        gate = visit_gate(school)
        self.assertEqual(gate.staff_trainings, 2)
        self.assertFalse(gate.staff_trainings_open)
        self.assertTrue(gate.partner_trainings_open)
        self.assertTrue(gate.staff_can_schedule)

    def test_donor_visits_are_not_package_visits(self):
        school = self._core("VG-C6")
        for _ in range(3):
            self._visit(school, kind="donor_visit")
        gate = visit_gate(school)
        self.assertEqual(gate.staff_visits, 0)
        self.assertTrue(gate.staff_can_schedule)


class TheServicesScheduleWhatTheButtonsOfferTest(_GateFixture, TestCase):
    """The two readers of the gate, agreeing on the one staff visit."""

    def _entitlement(self, school, **data):
        from apps.activities.services import _assert_schedule_entitlement

        _assert_schedule_entitlement("school_visit", school, self.fy, data)

    def test_a_second_staff_support_visit_is_refused(self):
        from apps.core.exceptions import BadRequest

        school = self._school("VG-S1")
        self._spend_client_visits(school)
        with self.assertRaises(BadRequest) as ctx:
            self._entitlement(school)
        self.assertIn("staff support visit", str(ctx.exception.detail))
        # A partner's visit, and the next year's, are still open.
        self._entitlement(school, deliveryType="partner")
        from apps.activities.services import _assert_schedule_entitlement

        _assert_schedule_entitlement("school_visit", school, str(int(self.fy) + 1), {})

    def test_after_the_support_visit_ssa_and_outreach_pass(self):
        from apps.activities.services import _assert_schedule_entitlement
        from apps.core.exceptions import BadRequest

        school = self._school("VG-S2")
        self._entitlement(school)
        self._visit(school)
        # The support visit is one in total: an In-school Training is refused
        # after a follow-up, as a follow-up is after an In-school Training.
        with self.assertRaisesMessage(BadRequest, "staff support visit"):
            _assert_schedule_entitlement("in_school_training", school, self.fy, {})
        # Data collection (SSA Support) and donor, story, invitation and
        # social visits without limit (owner, 2026-10-02).
        for _ in range(2):
            _assert_schedule_entitlement(
                "school_visit_ssa_collection", school, self.fy, {}
            )
            self._visit(school, kind="school_visit_ssa_collection")
        for kind in (
            "donor_visit",
            "story_gathering_visit",
            "school_invitation",
            "social_visit",
        ):
            self._visit(school, kind=kind)
            _assert_schedule_entitlement(kind, school, self.fy, {})
        # The training pair's companion visit is the training, not a visit.
        _assert_schedule_entitlement(
            "school_visit",
            school,
            self.fy,
            {"purposeType": "in_school_training_delivery_visit"},
        )

    def test_a_pending_request_does_not_use_the_visit_until_approved(self):
        """A request is not a plan: it uses no visit while it waits, and the
        rule is applied when its owner approves it."""
        from apps.core.exceptions import BadRequest
        from apps.activities.services import _assert_schedule_entitlement
        from apps.planning import visit_requests

        school = self._school("VG-S0")
        # Counted in the year the visit falls in: approving files it there,
        # and from late September `_visit`'s date is in the next fiscal year.
        fy = get_operational_fy(date.today() + timedelta(days=7))
        _assert_schedule_entitlement("school_visit", school, fy, {}, is_request=True)
        first = self._visit(school, status=visit_requests.AWAITING, fy=fy)
        second = self._visit(school, status=visit_requests.AWAITING, fy=fy)
        for request in (first, second):
            request.approval_owner_id = self.cceo.id
            request.save(update_fields=["approval_owner_id"])
        # Pending requests are not counted visits.
        self.assertEqual(visit_gate(school, fy).total_visits, 0)
        approved = visit_requests.approve(first.id, self.cceo_user)
        self.assertEqual(approved.status, "scheduled")
        self.assertEqual(visit_gate(school, fy).total_visits, CLIENT_VISIT_CAP)
        with self.assertRaises(BadRequest):
            visit_requests.approve(second.id, self.cceo_user)

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

        # Every portfolio school stays on the client tab (owner, 2026-09-23):
        # a school with work already planned, or with support handed to a
        # Partner, is still the owner's to plan. Where its work has reached is
        # what the Visit and Training indicators say, not which tab hides it.
        self.assertEqual(sorted(rows_on("client")), ["VG-S4", "VG-S5", "VG-S6"])
        rows = {**rows_on("scheduled"), **rows_on("partner"), **rows_on("client")}
        self.assertIn("VG-S4", rows, sorted(rows))
        for code in ("VG-S4", "VG-S5", "VG-S6"):
            self.assertTrue(rows[code]["staffCanSchedule"], code)
            self.assertTrue(rows[code]["canAssignPartner"], code)
            self.assertEqual(rows[code]["staffScheduleReason"], "", code)
        # The spent school's follow-up purposes close, with the reason; the
        # others stay open.
        self.assertFalse(rows["VG-S4"]["followUpVisitOpen"])
        self.assertIn("staff support visit", rows["VG-S4"]["followUpVisitReason"])
        self.assertTrue(rows["VG-S5"]["followUpVisitOpen"])

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

    def test_the_drawer_greys_the_follow_up_purposes_for_the_spent_year(self):
        import json

        visited = self._school("VG-S8")
        self._spend_client_visits(visited)
        self.client.force_login(self.cceo_user)
        response = self.client.get(
            f"/planning/schedule-modal?school_id={visited.school_id}"
        )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('name="purpose_of_visit"', html)
        # The year the support visit was spent in is carried for the Training
        # Follow Up; SSA Support and every other purpose stay open.
        locks = json.loads(response.context["visit_locks_json"])
        self.assertEqual(set(locks), {"training_follow_up"})
        self.assertIn(self.fy, locks["training_follow_up"])
        self.assertRegex(
            html, r'value="training_follow_up"[^>]*data-visit-locked="true"'
        )
        # In-school Training stays open (owner, 2026-10-06): a universal
        # training is on top of the school's own, so the purpose is not
        # greyed. The year is carried for the Training list instead, which
        # greys every training but the universal one; the save refuses the
        # rest (apps.planning.test_training_entitlement).
        self.assertNotRegex(html, r'value="in_school_training"[^>]*data-visit-locked')
        self.assertNotRegex(html, r'value="in_school_training"[^>]*disabled')
        training_locks = json.loads(response.context["training_locks_json"])
        self.assertEqual(list(training_locks), [self.fy])
        self.assertIn("has had its staff support visit", training_locks[self.fy])
        self.assertIn("data-training-entitlement-used", html)
        self.assertIn(':disabled="isTrainingHeld(activity)"', html)
        self.assertNotRegex(html, r'value="ssa_support"[^>]*data-visit-locked')
        self.assertNotRegex(html, r'value="donor_visit"[^>]*disabled')
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
        # The allowance is counted in the fiscal year the PARTNER's date falls
        # in, so the visits that spend it have to be booked in that same year.
        # Pinning them to today's FY made this test pass for most of the year
        # and fail every late September, when today + 10 days crosses into the
        # next FY and the gate correctly finds an untouched allowance.
        # A day the calendar accepts: today + 10 alone is a Sunday one week in
        # seven, and the partner's booking was refused for it.
        when_on = _schedulable(date.today() + timedelta(days=10))
        self._spend_client_visits(school, fy=get_operational_fy(when_on))
        assignment = self._assign(school, expected_activity_type="school_visit")
        created = _partner_schedule_from_assignment(
            assignment.id,
            {"scheduledDate": when_on.isoformat(), "deliveryContactName": "VG Visitor"},
            self.partner_user,
        )
        self.assertEqual(created["deliveryType"], "partner")
        # Counted on the partner's side, in that same fiscal year — the third
        # visit of a two-visit allowance, and no refusal.
        self.assertEqual(
            visit_gate(school, created["fy"]).partner_visits,
            1,
        )
        self.assertEqual(
            visit_gate(school, created["fy"]).total_visits, CLIENT_VISIT_CAP + 1
        )
