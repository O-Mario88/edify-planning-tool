"""One visit commitment a school a year.

Owner, 2026-10-08, on a brief asking for "a centralized FY-aware School Visit
Planning Eligibility Engine that prevents duplicate operational coverage while
preserving legitimate exceptions such as SSA Support". Asked what closes for
staff at a school a partner holds, the owner chose "support visits only"; asked
how far one commitment a school a year reaches, "staff and partners, fully".

So, at a Client, Core Trained or Core Graduate school, in one financial year:

* a partner holding the school — a hand-over waiting for its date, or a visit
  the partner has dated — closes a staff Training Follow Up and In-school
  Training, for every staff member and at every door;
* a staff support visit closes a hand-over for a visit, and one hand-over
  closes the next, to another partner or the same one;
* SSA Support handed to a partner is kept apart: it closes nothing, a visit
  does not close it, and it is assigned only while the school has no SSA for
  the year;
* donor, story, invitation and social visits and staff SSA Support stay open;
  a Core package keeps its 2 + 2; a withdrawn hand-over lets the school go.

The rule is ``apps.planning.visit_gate``; ``apps.planning.eligibility`` asks
it in the brief's words. These tests drive the gate, then every door that
writes, then the pages, then two connections at once.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch

from django.db import connections
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.activities.models import Activity
from apps.clusters.models import Cluster
from apps.core.exceptions import BadRequest, ConflictError
from apps.core.fy import get_operational_fy
from apps.core.test_seed_utils import ReferenceDataTransactionTestCase
from apps.geography.models import District, Region, SubCounty
from apps.partners import services as partner_services
from apps.partners.models import Partner, PartnerAssignment
from apps.planning import eligibility
from apps.planning.test_visit_gate import _GateFixture
from apps.planning.visit_gate import (
    AVAILABLE,
    CURRENT_FY_SSA_EXISTS,
    PARTNER_VISIT_ASSIGNED,
    SSA_SUPPORT_ELIGIBLE,
    STAFF_VISIT_SCHEDULED,
    visit_gate,
)
from apps.schools.models import School
from apps.ssa.models import SsaRecord

ONE_COMMITMENT_TYPES = ("client", "core_trained", "core_graduate")


def _ssa(school, *, fy=None, status="confirmed", deleted=False):
    record = SsaRecord.objects.create(
        school=school,
        fy=fy or get_operational_fy(),
        quarter="Q1",
        date_of_ssa=timezone.now() - timedelta(days=3),
        verification_status=status,
        uploaded_by="test",
    )
    if deleted:
        record.deleted_at = timezone.now()
        record.save(update_fields=["deleted_at"])
    return record


class _Fixture(_GateFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.other_partner = Partner.objects.create(name="VG Second Partner")

    def _hand_over(self, school, *, partner=None, purpose="training_follow_up", **kw):
        """A hand-over through THE creation door, as every page makes one."""
        return partner_services.create_assignment(
            school=school,
            partner=partner or self.partner,
            assigning_staff_id=self.cceo.id,
            monitoring_staff_id=self.cceo.id,
            purpose_of_visit=purpose,
            expected_activity_type=(
                "school_visit_ssa_collection"
                if purpose == "ssa_support"
                else "training_follow_up_visit"
            ),
            **kw,
        )

    def _entitlement(self, school, kind="training_follow_up_visit", **data):
        from apps.activities.services import _assert_schedule_entitlement

        _assert_schedule_entitlement(kind, school, self.fy, data)


class APartnerHeldSchoolIsClosedToStaffTest(_Fixture, TestCase):
    def test_a_waiting_hand_over_closes_the_staff_support_visit(self):
        for index, school_type in enumerate(ONE_COMMITMENT_TYPES):
            with self.subTest(school_type=school_type):
                school = self._school(f"OC-A{index}", school_type)
                self._assign(school, purpose_of_visit="training_follow_up")
                gate = visit_gate(school)
                # Assigned is enough: the partner has dated nothing.
                self.assertEqual(gate.partner_visits, 0)
                self.assertFalse(gate.staff_can_schedule)
                self.assertEqual(gate.staff_code, PARTNER_VISIT_ASSIGNED)
                self.assertIn("VG Partner Org", gate.staff_reason)
                self.assertIn(f"FY{self.fy}", gate.staff_reason)
                self.assertEqual(gate.lock_label, "Awaiting schedule from partner")
                # The row's Schedule stays live: the other visits are open.
                self.assertFalse(gate.staff_locked)
                self.assertTrue(gate.ssa_can_schedule)

    def test_a_visit_the_partner_has_dated_closes_it_and_names_the_partner(self):
        school = self._school("OC-B")
        self._visit(school, delivery="partner", kind="training_follow_up_visit")
        gate = visit_gate(school)
        self.assertEqual(gate.partner_visits, 1)
        self.assertFalse(gate.staff_can_schedule)
        self.assertEqual(gate.staff_code, PARTNER_VISIT_ASSIGNED)
        self.assertIn("VG Partner Org", gate.staff_reason)

    def test_a_returned_or_withdrawn_hand_over_lets_the_school_go(self):
        school = self._school("OC-C")
        handed = self._assign(school, purpose_of_visit="training_follow_up")
        self.assertFalse(visit_gate(school).staff_can_schedule)
        # A hand-back and a withdrawal both end here.
        handed.status = PartnerAssignment.STATUS_RETURNED_TO_STAFF
        handed.save(update_fields=["status"])
        gate = visit_gate(school)
        self.assertTrue(gate.staff_can_schedule)
        self.assertEqual(gate.staff_code, AVAILABLE)
        self.assertEqual(gate.lock_label, "")
        self.assertTrue(gate.can_assign_visit)

    def test_ssa_support_with_a_partner_closes_nothing(self):
        school = self._school("OC-D")
        self._assign(school, purpose_of_visit="ssa_support")
        self._visit(school, delivery="partner", kind="school_visit_ssa_collection")
        gate = visit_gate(school)
        self.assertTrue(gate.staff_can_schedule)
        self.assertTrue(gate.can_assign_visit)
        self.assertEqual(gate.lock_label, "")

    def test_last_years_partner_visit_does_not_hold_this_year(self):
        school = self._school("OC-E")
        self._visit(
            school,
            delivery="partner",
            kind="training_follow_up_visit",
            fy=str(int(self.fy) - 1),
        )
        self.assertTrue(visit_gate(school).staff_can_schedule)

    def test_the_other_visits_and_staff_ssa_support_stay_open(self):
        school = self._school("OC-F")
        self._assign(school, purpose_of_visit="in_school_training")
        with self.assertRaises(BadRequest) as refused:
            self._entitlement(school)
        self.assertEqual(refused.exception.reason_code, PARTNER_VISIT_ASSIGNED)
        self.assertIn("VG Partner Org", str(refused.exception.detail))
        with self.assertRaises(BadRequest):
            self._entitlement(school, "in_school_training")
        for kind in (
            "school_visit_ssa_collection",
            "donor_visit",
            "story_gathering_visit",
            "school_invitation",
            "social_visit",
        ):
            self._entitlement(school, kind)  # no refusal

    def test_a_core_package_keeps_its_two_and_two(self):
        from apps.core_schools.models import CorePlan, cplan_id
        from apps.core_schools.services import create_package_slots

        school = self._school("OC-G", "core")
        plan = CorePlan.objects.create(
            id=cplan_id("OC-G", fy=self.fy),
            school_id="OC-G",
            fy=self.fy,
            status="Active",
        )
        create_package_slots(plan, "OC-G", ["leadership"])
        self._assign(school, support_type="Visit", visit_number="3")
        gate = visit_gate(school)
        self.assertEqual(gate.rule, "core")
        self.assertFalse(gate.one_commitment)
        self.assertTrue(gate.staff_can_schedule)
        self.assertTrue(gate.can_assign_visit)


class AVisitedOrHeldSchoolIsNotHandedOverAgainTest(_Fixture, TestCase):
    def test_a_staff_visit_closes_the_visit_hand_over(self):
        school = self._school("OC-H")
        self._visit(school, kind="training_follow_up_visit")
        gate = visit_gate(school)
        self.assertFalse(gate.can_assign_visit)
        self.assertEqual(gate.assign_visit_code, STAFF_VISIT_SCHEDULED)
        # SSA Support is still to be collected, so Assign stays live.
        self.assertTrue(gate.can_assign_ssa)
        self.assertTrue(gate.can_assign_partner)
        with self.assertRaises(ConflictError) as refused:
            self._hand_over(school)
        self.assertEqual(refused.exception.reason_code, STAFF_VISIT_SCHEDULED)
        self.assertFalse(PartnerAssignment.objects.filter(school=school).exists())
        with self.assertRaises(ConflictError):
            self._hand_over(school, purpose="in_school_training")

    def test_one_hand_over_closes_the_next_to_any_partner(self):
        school = self._school("OC-I")
        self._hand_over(school)
        gate = visit_gate(school)
        self.assertFalse(gate.can_assign_visit)
        self.assertEqual(gate.assign_visit_code, PARTNER_VISIT_ASSIGNED)
        with self.assertRaises(ConflictError) as refused:
            self._hand_over(school, partner=self.other_partner)
        self.assertEqual(refused.exception.reason_code, PARTNER_VISIT_ASSIGNED)
        self.assertIn("VG Partner Org", str(refused.exception.detail))
        # The same partner is not handed a second visit either.
        with self.assertRaises(ConflictError):
            self._hand_over(school, purpose="in_school_training")
        self.assertEqual(PartnerAssignment.objects.filter(school=school).count(), 1)

    def test_a_withdrawn_school_may_be_handed_over_again(self):
        school = self._school("OC-J")
        first = self._hand_over(school)
        first.status = PartnerAssignment.STATUS_RETURNED_TO_STAFF
        first.save(update_fields=["status"])
        second = self._hand_over(school, partner=self.other_partner)
        self.assertEqual(second.status, PartnerAssignment.STATUS_PENDING_SCHEDULING)

    def test_a_withdrawn_hand_over_is_replaced_unless_other_work_holds_the_school(
        self,
    ):
        from apps.partners.withdrawal_service import _assert_replacement_eligible

        school = self._school("OC-J2")
        first = self._hand_over(school)
        # One for one: the hand-over being replaced is not counted against
        # its own replacement.
        _assert_replacement_eligible(first, self.other_partner.id)
        # A staff visit planned since (a row from before the rule) is other
        # work: the support goes back to planning instead.
        self._visit(school, kind="training_follow_up_visit")
        with self.assertRaises(ConflictError) as refused:
            _assert_replacement_eligible(first, self.other_partner.id)
        self.assertEqual(refused.exception.reason_code, STAFF_VISIT_SCHEDULED)

    def test_work_created_already_carrying_a_partner_is_a_hand_over(self):
        school = self._school("OC-K")
        self._visit(school, kind="training_follow_up_visit")
        with self.assertRaises(ConflictError) as refused:
            self._entitlement(school, deliveryType="partner")
        self.assertEqual(refused.exception.reason_code, STAFF_VISIT_SCHEDULED)

    def test_a_special_projects_hand_over_goes_past_the_rule(self):
        """Owner, 2026-10-05: a project's schools "can be assigned to any
        partner" — the hand-over goes past the school rules, this one too."""
        school = self._school("OC-L")
        self._visit(school, kind="training_follow_up_visit")
        eligibility.assert_handover_eligible(
            school,
            purpose_of_visit="training_follow_up",
            expected_activity_type="training_follow_up_visit",
            past_school_rules=True,
        )
        with self.assertRaises(ConflictError):
            eligibility.assert_handover_eligible(
                school,
                purpose_of_visit="training_follow_up",
                expected_activity_type="training_follow_up_visit",
            )

    def test_a_visit_moved_to_a_partner_is_refused_only_over_other_work(self):
        from apps.activities.services import _assert_move_keeps_one_commitment

        school = self._school("OC-M")
        mine = self._visit(school, kind="training_follow_up_visit")
        # The visit being moved is the school's one commitment, not a second.
        _assert_move_keeps_one_commitment(mine, to_partner=True)
        self._assign(school, purpose_of_visit="training_follow_up")
        with self.assertRaises(ConflictError) as refused:
            _assert_move_keeps_one_commitment(mine, to_partner=True)
        self.assertEqual(refused.exception.reason_code, PARTNER_VISIT_ASSIGNED)

    def test_a_partner_visit_moved_to_staff_is_refused_over_a_staff_visit(self):
        from apps.activities.services import _assert_move_keeps_one_commitment

        school = self._school("OC-N")
        theirs = self._visit(
            school, delivery="partner", kind="training_follow_up_visit"
        )
        _assert_move_keeps_one_commitment(theirs, to_partner=False)
        self._visit(school, kind="training_follow_up_visit")
        with self.assertRaises(BadRequest) as refused:
            _assert_move_keeps_one_commitment(theirs, to_partner=False)
        self.assertEqual(refused.exception.reason_code, STAFF_VISIT_SCHEDULED)


class SsaSupportIsAssignedOnlyWithoutTheYearsSsaTest(_Fixture, TestCase):
    def test_no_ssa_this_year_is_eligible_whatever_else_the_school_holds(self):
        school = self._school("OC-P")
        self._visit(school, kind="training_follow_up_visit")
        gate = visit_gate(school)
        self.assertFalse(gate.has_ssa)
        self.assertTrue(gate.can_assign_ssa)
        self.assertEqual(gate.assign_ssa_code, SSA_SUPPORT_ELIGIBLE)
        handed = self._hand_over(school, purpose="ssa_support")
        self.assertTrue(handed.is_data_collection)
        # And beside a partner's visit hand-over at another school.
        held = self._school("OC-P2")
        self._hand_over(held)
        self._hand_over(held, partner=self.other_partner, purpose="ssa_support")

    def test_a_completed_ssa_for_the_year_closes_it(self):
        """Owner, 2026-10-08: having an SSA this year "means the school has
        completed SSA this year (FY2027)" — a confirmed record of the year."""
        school = self._school("OC-Q0")
        _ssa(school, status="confirmed")
        gate = visit_gate(school)
        self.assertTrue(gate.has_ssa)
        self.assertFalse(gate.can_assign_ssa)
        self.assertEqual(gate.assign_ssa_code, CURRENT_FY_SSA_EXISTS)
        self.assertIn(f"has completed its SSA for FY{self.fy}", gate.assign_ssa_reason)
        # A visit is still open to a partner, so Assign stays live.
        self.assertTrue(gate.can_assign_partner)
        with self.assertRaises(ConflictError) as refused:
            self._hand_over(school, purpose="ssa_support")
        self.assertEqual(refused.exception.reason_code, CURRENT_FY_SSA_EXISTS)

    def test_an_ssa_that_is_not_this_years_completed_one_does_not_count(self):
        """Last year's, one still waiting for its verifier, one sent back or
        flagged, and a deleted one: none is the year's completed SSA."""
        last_year = str(int(self.fy) - 1)
        for index, record in enumerate(
            (
                {"fy": last_year},
                {"status": "pending"},
                {"status": "returned"},
                {"status": "flagged"},
                {"deleted": True},
            )
        ):
            with self.subTest(record=record):
                school = self._school(f"OC-R{index}")
                _ssa(school, **record)
                gate = visit_gate(school)
                self.assertFalse(gate.has_ssa)
                self.assertTrue(gate.can_assign_ssa)
                self._hand_over(school, purpose="ssa_support")

    def test_an_ssa_arriving_later_keeps_the_hand_over_already_made(self):
        school = self._school("OC-S")
        handed = self._hand_over(school, purpose="ssa_support")
        _ssa(school)
        handed.refresh_from_db()
        self.assertEqual(handed.status, PartnerAssignment.STATUS_PENDING_SCHEDULING)
        # Closed to a NEW one, to this partner or another.
        with self.assertRaises(ConflictError):
            self._hand_over(school, partner=self.other_partner, purpose="ssa_support")

    def test_it_is_asked_of_a_core_school_too_and_a_project_goes_past_it(self):
        school = self._school("OC-T", "core")
        _ssa(school)
        self.assertFalse(visit_gate(school).can_assign_ssa)
        with self.assertRaises(ConflictError) as refused:
            eligibility.assert_handover_eligible(school, purpose_of_visit="ssa_support")
        self.assertEqual(refused.exception.reason_code, CURRENT_FY_SSA_EXISTS)
        # A Special Project's hand-over goes past the school rules for now
        # (owner, 2026-10-05), this one with the rest.
        eligibility.assert_handover_eligible(
            school, purpose_of_visit="ssa_support", past_school_rules=True
        )

    def test_assign_closes_when_neither_a_visit_nor_ssa_support_is_open(self):
        school = self._school("OC-U")
        self._visit(school, kind="training_follow_up_visit")
        _ssa(school)
        gate = visit_gate(school)
        self.assertFalse(gate.can_assign_partner)
        self.assertEqual(gate.assign_code, STAFF_VISIT_SCHEDULED)
        self.assertIn("staff support visit", gate.assign_reason)
        self.assertIn("has completed its SSA", gate.assign_reason)


class TheEngineAnswersInTheBriefsWordsTest(_Fixture, TestCase):
    def test_one_question_one_structured_answer(self):
        school = self._school("OC-V", "core_trained")
        answer = eligibility.school_planning_eligibility(school)
        self.assertTrue(answer.eligible)
        self.assertEqual(answer.reason, AVAILABLE)
        self.assertEqual(answer.category, "CORE_TRAINED")
        self.assertEqual(answer.fy, self.fy)

        self._hand_over(school)
        answer = eligibility.school_planning_eligibility(
            school, eligibility.STAFF_VISIT
        )
        self.assertFalse(answer.eligible)
        self.assertEqual(answer.reason, PARTNER_VISIT_ASSIGNED)
        self.assertEqual(answer.assigned_to, "VG Partner Org")
        self.assertEqual(answer.assignment_type, eligibility.ASSIGNMENT_NORMAL_VISIT)
        self.assertEqual(answer.as_dict()["assignedTo"], "VG Partner Org")
        self.assertIn("VG Partner Org", answer.message)

        answer = eligibility.school_planning_eligibility(
            school, eligibility.PARTNER_SSA_SUPPORT
        )
        self.assertTrue(answer.eligible)
        self.assertEqual(answer.reason, SSA_SUPPORT_ELIGIBLE)
        self.assertEqual(answer.assignment_type, eligibility.ASSIGNMENT_SSA_SUPPORT)

    def test_a_page_of_schools_is_answered_together(self):
        visited = self._school("OC-W1")
        self._visit(visited, kind="training_follow_up_visit")
        held = self._school("OC-W2")
        self._assign(held, purpose_of_visit="training_follow_up")
        free = self._school("OC-W3")
        answers = eligibility.school_planning_eligibilities([visited, held, free])
        self.assertEqual(
            {
                visited.id: STAFF_VISIT_SCHEDULED,
                held.id: PARTNER_VISIT_ASSIGNED,
                free.id: AVAILABLE,
            },
            {school_id: answer.reason for school_id, answer in answers.items()},
        )

    def test_the_hand_overs_own_purpose_says_what_it_is(self):
        self.assertEqual(
            eligibility.handover_context("ssa_support", "school_visit"),
            eligibility.PARTNER_SSA_SUPPORT,
        )
        self.assertEqual(
            eligibility.handover_context(None, "partner_ssa_collection"),
            eligibility.PARTNER_SSA_SUPPORT,
        )
        self.assertEqual(
            eligibility.handover_context("training_follow_up", "school_visit"),
            eligibility.PARTNER_VISIT,
        )

    def test_the_api_refusal_carries_its_reason(self):
        from apps.core.exceptions import edify_exception_handler

        school = self._school("OC-X")
        self._assign(school, purpose_of_visit="training_follow_up")
        with self.assertRaises(BadRequest) as refused:
            self._entitlement(school)
        response = edify_exception_handler(refused.exception, {})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["reason"], PARTNER_VISIT_ASSIGNED)
        self.assertIn("VG Partner Org", response.data["message"])
        # Any other refusal keeps the envelope it had.
        plain = edify_exception_handler(BadRequest("No."), {})
        self.assertNotIn("reason", plain.data)


class ThePagesSayWhatTheSaveRefusesTest(_Fixture, TestCase):
    def test_the_planning_row_shows_the_lock_and_keeps_schedule_live(self):
        from apps.planning.planning_service import PlanningDashboardService

        held = self._school("OC-Y1")
        self._assign(held, purpose_of_visit="training_follow_up")
        visited = self._school("OC-Y2")
        self._visit(visited, kind="training_follow_up_visit")
        self._school("OC-Y3")
        rows = {
            row["schoolId"]: row
            for row in PlanningDashboardService.get_dashboard_data(
                self.cceo_user,
                {"fy": self.fy, "tab": "client", "page": 1, "per_page": 50},
            )["schools"]
        }
        self.assertEqual(
            rows["OC-Y1"]["visitLockLabel"], "Awaiting schedule from partner"
        )
        self.assertEqual(rows["OC-Y1"]["visitLockCode"], PARTNER_VISIT_ASSIGNED)
        self.assertIn("VG Partner Org", rows["OC-Y1"]["visitLockReason"])
        self.assertEqual(rows["OC-Y2"]["visitLockLabel"], "Staff visit scheduled")
        self.assertEqual(rows["OC-Y3"]["visitLockLabel"], "Unlocked")
        self.assertEqual(rows["OC-Y3"]["visitLockReason"], "")
        for code in rows:
            self.assertTrue(rows[code]["staffCanSchedule"], code)

        self.client.force_login(self.cceo_user)
        html = self.client.get("/planning?tab=client").content.decode()
        # The Visit Lock column (owner, 2026-10-08), one cell a school.
        self.assertIn('class="school-plan-table__lock">Visit Lock</th>', html)
        self.assertEqual(html.count('<td data-label="Visit Lock"'), 3)
        for state in (
            "awaiting_partner_schedule",
            "staff_visit_scheduled",
            "unlocked",
        ):
            self.assertIn(f'data-visit-lock="{state}"', html)
        self.assertIn("is assigned to VG Partner Org for its support visit", html)
        # The column carries it, so the Visit Plan Status cell no longer does.
        self.assertNotIn("data-visit-closed", html)

    def test_the_schedule_drawer_greys_the_support_purposes_with_the_reason(self):
        import json

        held = self._school("OC-Z1")
        self._assign(held, purpose_of_visit="training_follow_up")
        self.client.force_login(self.cceo_user)
        response = self.client.get(
            f"/planning/schedule-modal?school_id={held.school_id}"
        )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        locks = json.loads(response.context["visit_locks_json"])
        self.assertIn("training_follow_up", locks)
        self.assertIn("VG Partner Org", locks["training_follow_up"][self.fy])
        self.assertRegex(
            html, r'value="training_follow_up"[^>]*data-visit-locked="true"'
        )
        self.assertNotRegex(html, r'value="ssa_support"[^>]*data-visit-locked')
        self.assertNotRegex(html, r'value="donor_visit"[^>]*disabled')

    def test_the_assign_drawer_greys_each_reason_it_would_refuse(self):
        visited = self._school("OC-Z2")
        self._visit(visited, kind="training_follow_up_visit")
        self.client.force_login(self.cceo_user)
        response = self.client.get(
            f"/planning/assign-partner-modal?school_id={visited.school_id}"
        )
        self.assertEqual(response.status_code, 200)
        locks = response.context["purpose_locks"]
        self.assertIn("training_follow_up", locks)
        self.assertNotIn("ssa_support", locks)
        html = response.content.decode()
        self.assertRegex(
            html, r'value="training_follow_up"\s+disabled data-visit-locked="true"'
        )
        self.assertIn("already has its staff support visit", html)

        _ssa(visited)
        response = self.client.get(
            f"/planning/assign-partner-modal?school_id={visited.school_id}"
        )
        # Nothing left to hand over: the door says why instead of opening.
        self.assertContains(response, "has completed its SSA")
        self.assertNotIn("purpose_locks", response.context or {})

    def test_the_bulk_hand_over_names_each_school_it_leaves_out(self):
        free = self._school("OC-Z3")
        visited = self._school("OC-Z4")
        self._visit(visited, kind="training_follow_up_visit")
        assessed = self._school("OC-Z5")
        _ssa(assessed)
        self.client.force_login(self.cceo_user)
        response = self.client.post(
            "/planning/bulk-action",
            {
                "action": "partner",
                "school_ids": [
                    free.school_id,
                    visited.school_id,
                    assessed.school_id,
                ],
                "partner_id": self.partner.id,
                "purpose_of_visit": "ssa_support",
            },
        )
        self.assertEqual(response.status_code, 200, response.content[:400])
        # A visit does not close SSA Support; the year's SSA does.
        handed = set(
            PartnerAssignment.objects.filter(
                partner=self.partner, purpose_of_visit="ssa_support"
            ).values_list("school__school_id", flat=True)
        )
        self.assertEqual(handed, {"OC-Z3", "OC-Z4"})
        html = response.content.decode()
        self.assertIn("School OC-Z5 (ssa completed this year)", html)

    def test_a_day_of_follow_ups_leaves_a_closed_school_out(self):
        from apps.planning.cluster_bulk_scheduling import schedulable_members

        held = self._school("OC-Z6")
        self._assign(held, purpose_of_visit="training_follow_up")
        free = self._school("OC-Z7")
        members = {
            member.school_id: member
            for member in schedulable_members(self.cluster, self.cceo_user).members
        }
        # Tickable for the day's other purposes, and it says why not this one.
        self.assertTrue(members["OC-Z6"].selectable)
        self.assertIn("VG Partner Org", members["OC-Z6"].visit_reason)
        self.assertEqual(members["OC-Z7"].visit_reason, "")

        self.client.force_login(self.cceo_user)
        response = self.client.get(f"/clusters/{self.cluster.id}/bulk-schedule-drawer")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("data-visit-closed", html)
        self.assertIn("No Training Follow Up:", html)
        self.assertEqual(free.school_id, "OC-Z7")


class ASpecialProjectsWorkIsItsTrainingsTest(_Fixture, TestCase):
    """Owner, 2026-10-08: "Special projects are automatically counted on the
    training they are assigned to." A project's work with a partner is not
    the school's visit of the year, so it holds nothing."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from apps.core.enums import SsaIntervention
        from apps.projects.models import Project

        cls.project = Project.objects.create(
            name="OC Learning Project",
            category="pilot",
            status="active",
            intervention=SsaIntervention.LEARNING_ENVIRONMENT,
            target_interventions=[SsaIntervention.LEARNING_ENVIRONMENT],
        )

    def test_a_projects_hand_over_does_not_hold_the_school(self):
        from apps.planning.visit_gate import LOCK_UNLOCKED

        school = self._school("OC-SP1")
        handed = self._assign(
            school, project=self.project, purpose_of_visit="in_school_training"
        )
        self.assertFalse(handed.outside_ssa)
        gate = visit_gate(school)
        # Still counted where it was counted, and holding nothing.
        self.assertEqual(gate.partner_pending, 1)
        self.assertEqual(gate.partner_holding, 0)
        self.assertTrue(gate.staff_can_schedule)
        self.assertTrue(gate.can_assign_visit)
        self.assertEqual(gate.lock_state, LOCK_UNLOCKED)
        self._entitlement(school)  # a staff support visit is planned
        # And the school's own support still goes to a partner beside it.
        self._hand_over(school, partner=self.other_partner)

    def test_a_visit_the_partner_dates_under_a_project_does_not_hold_it(self):
        school = self._school("OC-SP2")
        dated = self._visit(school, delivery="partner", kind="in_school_training")
        dated.project_id = self.project.id
        dated.save(update_fields=["project_id"])
        gate = visit_gate(school)
        self.assertEqual(gate.partner_visits, 1)
        self.assertEqual(gate.partner_holding, 0)
        self.assertTrue(gate.staff_can_schedule)
        self.assertTrue(gate.can_assign_visit)

    def test_the_schools_own_hand_over_still_holds_it_beside_a_projects(self):
        school = self._school("OC-SP3")
        self._assign(
            school, project=self.project, purpose_of_visit="in_school_training"
        )
        self._hand_over(school, partner=self.other_partner)
        gate = visit_gate(school)
        self.assertEqual(gate.partner_holding, 1)
        self.assertFalse(gate.staff_can_schedule)
        self.assertEqual(gate.staff_code, PARTNER_VISIT_ASSIGNED)
        self.assertIn("VG Second Partner", gate.staff_reason)


class ASchoolThatHasClosedIsLockedCompletelyTest(_Fixture, TestCase):
    """Owner, 2026-10-08: "Closed schools are locked completely unless they
    are reopened." """

    def _close(self, school):
        School.objects.filter(pk=school.pk).update(
            operational_status="permanently_closed"
        )
        school.refresh_from_db()
        return school

    def test_every_door_answers_closed_until_the_school_is_reopened(self):
        from apps.planning.visit_gate import (
            LOCK_SCHOOL_CLOSED,
            LOCK_UNLOCKED,
            SCHOOL_CLOSED,
        )

        school = self._close(self._school("OC-CL1"))
        gate = visit_gate(school)
        self.assertTrue(gate.closed)
        for door in (
            gate.staff_can_schedule,
            gate.ssa_can_schedule,
            gate.partner_can_schedule,
            gate.can_assign_partner,
            gate.can_assign_visit,
            gate.can_assign_ssa,
        ):
            self.assertFalse(door)
        # The whole Schedule control, not only the support purposes.
        self.assertTrue(gate.staff_locked)
        self.assertIn("reopen the school", gate.staff_locked_reason)
        self.assertEqual(gate.staff_code, SCHOOL_CLOSED)
        self.assertEqual(gate.assign_code, SCHOOL_CLOSED)
        self.assertEqual(gate.lock_state, LOCK_SCHOOL_CLOSED)
        self.assertEqual(gate.lock_state_label, "School closed")
        for context in eligibility.CONTEXTS:
            answer = eligibility.school_planning_eligibility(school, context)
            self.assertFalse(answer.eligible, context)
            self.assertEqual(answer.reason, SCHOOL_CLOSED, context)

        School.objects.filter(pk=school.pk).update(operational_status="reopened")
        school.refresh_from_db()
        gate = visit_gate(school)
        self.assertFalse(gate.closed)
        self.assertTrue(gate.staff_can_schedule)
        self.assertTrue(gate.can_assign_partner)
        self.assertEqual(gate.lock_state, LOCK_UNLOCKED)

    def test_the_saving_doors_refuse_a_closed_school(self):
        school = self._close(self._school("OC-CL2"))
        with self.assertRaisesMessage(BadRequest, "reopen the school"):
            self._hand_over(school)
        with self.assertRaisesMessage(BadRequest, "reopen the school"):
            self._hand_over(school, purpose="ssa_support")
        with self.assertRaisesMessage(BadRequest, "reopen the school"):
            self._entitlement(school)
        self.assertFalse(PartnerAssignment.objects.filter(school=school).exists())

    def test_its_profile_offers_neither_schedule_nor_assign(self):
        from apps.frontend.views.school_views import _profile_planning_controls

        school = self._close(self._school("OC-CL3"))
        controls = _profile_planning_controls(self.cceo_user, school)
        self.assertFalse(controls["can_schedule"])
        self.assertFalse(controls["can_assign_partner"])


class TheVisitLockColumnTest(_Fixture, TestCase):
    """Owner, 2026-10-08: "Add another column on the planning page and cluster
    school list containing locked and unlocked school visits (Staff visit
    scheduled, or partner visit scheduled if the assigned schools are
    scheduled if not yet scheduled by partner it should be 'Awaiting schedule
    from partner')"."""

    def test_the_column_names_what_holds_the_visit(self):
        from apps.planning.visit_gate import (
            LOCK_NOT_APPLICABLE,
            LOCK_PARTNER_AWAITING,
            LOCK_PARTNER_SCHEDULED,
            LOCK_STAFF_SCHEDULED,
            LOCK_UNLOCKED,
        )

        free = self._school("OC-L1")
        gate = visit_gate(free)
        self.assertEqual(gate.lock_state, LOCK_UNLOCKED)
        self.assertEqual(gate.lock_state_label, "Unlocked")
        self.assertFalse(gate.is_locked)

        visited = self._school("OC-L2")
        self._visit(visited, kind="training_follow_up_visit")
        gate = visit_gate(visited)
        self.assertEqual(gate.lock_state, LOCK_STAFF_SCHEDULED)
        self.assertEqual(gate.lock_state_label, "Staff visit scheduled")

        waiting = self._school("OC-L3")
        self._assign(waiting, purpose_of_visit="training_follow_up")
        gate = visit_gate(waiting)
        self.assertEqual(gate.lock_state, LOCK_PARTNER_AWAITING)
        self.assertEqual(gate.lock_state_label, "Awaiting schedule from partner")

        dated = self._school("OC-L4")
        self._visit(dated, delivery="partner", kind="training_follow_up_visit")
        gate = visit_gate(dated)
        self.assertEqual(gate.lock_state, LOCK_PARTNER_SCHEDULED)
        self.assertEqual(gate.lock_state_label, "Partner visit scheduled")

        # A staff visit and a hand-over both there (rows from before the
        # rule): the staff visit is what the column names.
        both = self._school("OC-L5")
        self._visit(both, kind="training_follow_up_visit")
        self._assign(both, purpose_of_visit="training_follow_up")
        self.assertEqual(visit_gate(both).lock_state, LOCK_STAFF_SCHEDULED)

        # SSA Support with a partner locks nothing.
        collecting = self._school("OC-L6")
        self._assign(collecting, purpose_of_visit="ssa_support")
        self.assertEqual(visit_gate(collecting).lock_state, LOCK_UNLOCKED)

        # A Champion school takes no support visit: nothing to lock or unlock.
        champion = self._school("OC-L7", "champion")
        gate = visit_gate(champion)
        self.assertEqual(gate.lock_state, LOCK_NOT_APPLICABLE)
        self.assertEqual(gate.lock_state_label, "")

    def test_a_core_school_locks_when_staffs_half_of_the_package_is_used(self):
        from apps.core_schools.models import CorePlan, cplan_id
        from apps.core_schools.services import create_package_slots
        from apps.planning.visit_gate import LOCK_PACKAGE_COMPLETE, LOCK_UNLOCKED

        school = self._school("OC-L8", "core")
        plan = CorePlan.objects.create(
            id=cplan_id("OC-L8", fy=self.fy),
            school_id="OC-L8",
            fy=self.fy,
            status="Active",
        )
        create_package_slots(plan, "OC-L8", ["leadership"])
        self._visit(school)
        self.assertEqual(visit_gate(school).lock_state, LOCK_UNLOCKED)
        self._visit(school)
        gate = visit_gate(school)
        self.assertEqual(gate.lock_state, LOCK_PACKAGE_COMPLETE)
        self.assertEqual(gate.lock_state_label, "Staff visits complete")

    def test_the_cluster_school_lists_carry_the_column_too(self):
        waiting = self._school("OC-L9")
        self._assign(waiting, purpose_of_visit="training_follow_up")
        dated = self._school("OC-L10")
        self._visit(dated, delivery="partner", kind="training_follow_up_visit")
        self._school("OC-L11")
        self.client.force_login(self.cceo_user)
        # The cluster's own page, and the list under a cluster on Planning.
        for url in (
            f"/clusters/{self.cluster.id}",
            f"/partials/clusters/{self.cluster.id}/schools",
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200, url)
                html = response.content.decode()
                self.assertIn("Visit Lock</th>", html)
                self.assertEqual(html.count('<td data-label="Visit Lock"'), 3)
                self.assertIn("Awaiting schedule from partner", html)
                self.assertIn("Partner visit scheduled", html)
                self.assertIn('data-visit-lock="unlocked"', html)
                self.assertNotIn("data-visit-closed", html)


class TheOtherPagesAgreeTest(_Fixture, TestCase):
    def test_the_profile_keeps_schedule_open_and_says_why_a_visit_is_closed(self):
        from apps.frontend.views.school_views import _profile_planning_controls

        held = self._school("OC-P1")
        self._assign(held, purpose_of_visit="training_follow_up")
        controls = _profile_planning_controls(self.cceo_user, held)
        # The door stays open for the visits that are not the support visit,
        # as the school's list row keeps it.
        self.assertEqual(controls["schedule_block"], "")
        self.assertEqual(controls["visit_lock"], "Awaiting schedule from partner")
        self.assertIn("VG Partner Org", controls["visit_lock_reason"])
        free = self._school("OC-P2")
        self.assertEqual(
            _profile_planning_controls(self.cceo_user, free)["visit_lock"], ""
        )

    def test_a_core_graduate_row_on_core_schools_shows_the_lock(self):
        from apps.core_schools.lifecycle import programme_rows

        graduate = self._school("OC-P3", "core_graduate")
        self._assign(graduate, purpose_of_visit="training_follow_up")
        champion = self._school("OC-P4", "champion")
        rows = {
            row["school_id"]: row
            for row in programme_rows([graduate, champion], self.fy)
        }
        self.assertEqual(rows["OC-P3"]["visit_lock"], "Awaiting schedule from partner")
        self.assertEqual(rows["OC-P3"]["visit_lock_code"], PARTNER_VISIT_ASSIGNED)
        # A Champion school is planned for donor and story visits only: no
        # support visit to close, so nothing to say.
        self.assertEqual(rows["OC-P4"]["visit_lock"], "")

    def test_the_core_assign_drawer_greys_ssa_support_once_the_ssa_is_in(self):
        school = self._school("OC-P5", "core")
        self.client.force_login(self.cceo_user)
        url = f"/core-schools/assign-partner?school_id={school.school_id}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertEqual(response.context["ssa_support_closed"], "")
        _ssa(school)
        response = self.client.get(url)
        self.assertIn("has completed its SSA", response.context["ssa_support_closed"])
        self.assertRegex(
            response.content.decode(),
            r'value="ssa_support" disabled data-visit-locked="true"',
        )

    def test_a_day_of_follow_ups_is_refused_for_a_closed_school(self):
        from datetime import date

        from apps.planning.cluster_bulk_scheduling import (
            bulk_schedule_cluster_visits,
        )
        from apps.planning.test_visit_gate import _schedulable

        held = self._school("OC-P6")
        self._assign(held, purpose_of_visit="training_follow_up")
        when = _schedulable(date.today() + timedelta(days=5))
        with patch(
            "apps.planning.cluster_bulk_scheduling._assert_follow_up_is_plannable_in_bulk"
        ):
            with self.assertRaisesMessage(BadRequest, "VG Partner Org"):
                bulk_schedule_cluster_visits(
                    self.cluster.id,
                    {
                        "purposeOfVisit": "training_follow_up",
                        "focusIntervention": "leadership",
                        "scheduledDate": when.isoformat(),
                        "schoolIds": [held.id],
                    },
                    self.cceo_user,
                )
        self.assertFalse(
            Activity.objects.filter(school=held, delivery_type="staff").exists()
        )


# ── Two people at once ───────────────────────────────────────────────────────
def _race(calls):
    """Run each call on its own connection, all released at once."""
    barrier = threading.Barrier(len(calls))
    outcomes: list = [None] * len(calls)

    def worker(index: int):
        try:
            barrier.wait(timeout=30)
            outcomes[index] = ("saved", calls[index]())
        except Exception as exc:  # noqa: BLE001 — the refusal IS the result
            outcomes[index] = ("refused", exc)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        list(pool.map(worker, range(len(calls))))
    return outcomes


class TwoPeopleCannotBothBeFirstTest(ReferenceDataTransactionTestCase):
    """TransactionTestCase: the connections have to see each other's commits,
    which one shared outer transaction would hide."""

    def setUp(self):
        self.region = Region.objects.create(name="Commitment Race Region")
        self.district = District.objects.create(
            name="Commitment Race District",
            region=self.region,
            district_type="primary",
        )
        self.sub_county = SubCounty.objects.create(
            name="Commitment Race SC", district=self.district
        )
        self.cluster = Cluster.objects.create(
            name="Commitment Race Cluster",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            cluster_type="mixed",
            status="active",
        )
        self.user = User.objects.create_user(
            email="commitment-race@edify.org",
            name="Race Officer",
            roles=["CCEO"],
            active_role="CCEO",
            password="x",
            is_active=True,
        )
        self.staff = StaffProfile.objects.create(
            user=self.user, staff_number="ST-RACE", country="Uganda"
        )
        self.school = School.objects.create(
            school_id="RACE-OC-1",
            name="Commitment Race School",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            school_type="client",
            enrollment=200,
            account_owner_id=self.staff.id,
            cluster_id=self.cluster.id,
            cluster_status="clustered",
        )
        StaffSchoolAssignment.objects.create(staff=self.staff, school_id=self.school.id)
        self.partners = [
            Partner.objects.create(name=f"Race Partner {index}") for index in (1, 2)
        ]

    def _hand_over(self, partner):
        return partner_services.create_assignment(
            school=School.objects.get(pk=self.school.pk),
            partner=partner,
            assigning_staff_id=self.staff.id,
            monitoring_staff_id=self.staff.id,
            purpose_of_visit="training_follow_up",
            expected_activity_type="training_follow_up_visit",
        )

    def _staff_training(self):
        from apps.activities.services import create
        from apps.activity_catalogue.models import ActivityCatalogueItem
        from apps.planning.test_standard_support_scheduling import (
            _at,
            _schedulable_date,
        )

        item = ActivityCatalogueItem.objects.get(
            stable_code="STANDARD_IN_SCHOOL_TRAINING"
        )
        return create(
            {
                "scheduledDate": _at(_schedulable_date()).isoformat(),
                "requireCatalogue": True,
                "schoolId": self.school.school_id,
                "catalogueItemId": item.id,
                "focusIntervention": "leadership",
                "activityPurposeText": "Race: the school's support visit",
                "teachersAttended": 8,
                "leadersAttended": 2,
            },
            self.user,
        )

    def test_two_partners_handed_one_school_at_once(self):
        first, second = self.partners
        outcomes = _race(
            [lambda: self._hand_over(first), lambda: self._hand_over(second)]
        )
        self.assertEqual(sorted(kind for kind, _ in outcomes), ["refused", "saved"])
        refused = next(result for kind, result in outcomes if kind == "refused")
        self.assertIsInstance(refused, ConflictError)
        self.assertEqual(refused.reason_code, PARTNER_VISIT_ASSIGNED)
        self.assertEqual(
            PartnerAssignment.objects.filter(school=self.school).count(), 1
        )

    def test_a_staff_plan_and_a_hand_over_at_once(self):
        with patch("apps.activities.services._apply_schedule_cost_snapshot"):
            outcomes = _race(
                [self._staff_training, lambda: self._hand_over(self.partners[0])]
            )
        self.assertEqual(
            sorted(kind for kind, _ in outcomes),
            ["refused", "saved"],
            [str(getattr(result, "detail", result)) for _kind, result in outcomes],
        )
        refused = next(result for kind, result in outcomes if kind == "refused")
        self.assertIn(
            refused.reason_code, (STAFF_VISIT_SCHEDULED, PARTNER_VISIT_ASSIGNED)
        )
        staff_visits = Activity.objects.filter(
            school=self.school,
            delivery_type="staff",
            activity_type="in_school_training",
            deleted_at__isnull=True,
        ).count()
        handed = PartnerAssignment.objects.filter(school=self.school).count()
        self.assertEqual(staff_visits + handed, 1)
