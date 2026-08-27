"""CANCEL-01 — the screen that calls work off, and who may use it.

`apps.activities.services.cancel` has always existed and always worked. It
withdraws the cost from every draft funding surface, reverses milestone credit,
deletes advances whose money has not moved, preserves those that have, and
notifies an assigned partner so they do not travel. Journey 8 walks all of
that. What it did not have was a way in: the only door was
`POST /api/activities/<id>/cancel`, generated from the service by the
`_action_view` factory, and no page, drawer or button in the platform posted to
it. A capability with readers and no writers — the same shape this audit keeps
finding, in its third variant: an act with no door.

That mattered because staff whose plans change do one of three things instead,
and all three are worse than cancelling: leave dead work in the plan for ever
(their targets read permanently under-achieved and the attention queues fill
with noise), complete a visit that never happened (which corrupts targets, SSA
analytics and the money trail at once), or ask someone to edit the database
(which the mandate forbids in as many words).

What this fix adds beyond the screen is a mandatory reason. Authority was
left where the platform already put it — see
`CancelAuthorityIsExecutionAuthority` below for the rule that was tried,
measured, and withdrawn.
"""

from __future__ import annotations

import datetime

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import Activity
from apps.core.exceptions import Forbidden
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region
from apps.schools.models import School


class CancelActivityDoor(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Cancel Region")
        cls.district = District.objects.create(
            name="Cancel District", region=cls.region, district_type="primary"
        )
        cls.school = School.objects.create(
            school_id="CANCEL-001",
            name="Cancel School",
            region=cls.region,
            district=cls.district,
            school_type="client",
            enrollment=200,
        )
        cls.cceo = User.objects.create_user(
            email="cancel-cceo@edify.org",
            name="Cancel CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            password="pw-cancel-001",
            is_active=True,
        )
        cls.cceo_staff = StaffProfile.objects.create(
            user=cls.cceo, staff_number="ST-CANCEL-CCEO", country="Uganda"
        )
        StaffSchoolAssignment.objects.create(
            staff=cls.cceo_staff, school_id=cls.school.id
        )
        cls.pl = User.objects.create_user(
            email="cancel-pl@edify.org",
            name="Cancel PL",
            roles=["Program Lead"],
            active_role="Program Lead",
            password="pw-cancel-002",
            is_active=True,
        )
        cls.pl_staff = StaffProfile.objects.create(
            user=cls.pl, staff_number="ST-CANCEL-PL", country="Uganda"
        )

    def setUp(self):
        self.activity = Activity.objects.create(
            school=self.school,
            activity_type="school_visit",
            status="scheduled",
            fy=get_operational_fy(),
            planned_date=timezone.localdate() + datetime.timedelta(days=5),
            responsible_staff_id=str(self.cceo_staff.id),
        )

    def _login(self, user, password):
        self.assertTrue(
            self.client.login(email=user.email, password=password),
            "the fixture user could not log in",
        )

    # ------------------------------------------------------------- the door

    def test_the_plan_offers_a_way_to_cancel(self):
        """The finding itself: before this, nothing rendered a cancel control,
        so the whole capability was unreachable from the product."""
        self._login(self.cceo, "pw-cancel-001")

        response = self.client.get(f"/my-plan/{self.activity.id}/cancel-drawer")

        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn(f"/my-plan/{self.activity.id}/cancel", body)
        self.assertIn("reason", body)

    def test_cancelling_through_the_door_actually_cancels(self):
        self._login(self.cceo, "pw-cancel-001")

        self.client.post(
            f"/my-plan/{self.activity.id}/cancel",
            {"reason": "School closed for the rest of the term."},
        )

        self.activity.refresh_from_db()
        self.assertEqual(
            self.activity.status,
            "cancelled",
            "the cancel endpoint did not cancel the activity",
        )
        self.assertEqual(
            self.activity.last_reason, "School closed for the rest of the term."
        )

    def test_the_door_refuses_a_cancellation_with_no_reason(self):
        """A cancelled activity is a record someone reads later — a Programme
        Lead reviewing a dropped visit, an Accountant chasing an advance
        against work that never happened. `_cancel_or_defer` always STORED the
        reason; nothing required one, so it could be empty in exactly the
        cases that need explaining."""
        self._login(self.cceo, "pw-cancel-001")

        response = self.client.post(
            f"/my-plan/{self.activity.id}/cancel", {"reason": "   "}
        )

        self.assertEqual(response.status_code, 400)
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.status, "scheduled")

    def test_someone_elses_activity_cannot_be_cancelled(self):
        other_school = School.objects.create(
            school_id="CANCEL-OTHER",
            name="Someone Else's School",
            region=self.region,
            district=self.district,
            school_type="client",
            enrollment=100,
        )
        stranger = Activity.objects.create(
            school=other_school,
            activity_type="school_visit",
            status="scheduled",
            fy=get_operational_fy(),
            planned_date=timezone.localdate() + datetime.timedelta(days=5),
            responsible_staff_id="not-this-persons-staff-id",
        )
        self._login(self.cceo, "pw-cancel-001")

        response = self.client.post(
            f"/my-plan/{stranger.id}/cancel", {"reason": "Not mine to cancel."}
        )

        self.assertEqual(response.status_code, 403)
        stranger.refresh_from_db()
        self.assertEqual(stranger.status, "scheduled")


class CancelAuthorityIsExecutionAuthority(TestCase):
    """Who may cancel — and one rule this fix tried to add and withdrew.

    The first version of CANCEL-01 escalated cancellation of FUNDED work to
    the Programme Lead, reasoning by analogy with
    `partners.withdrawal_service.assert_may_withdraw`: "once a partner has
    committed to a date the CCEO must ask their Program Lead."

    The suite refused it, and the suite was right. `_assert_may_execute` cites
    §1B — supervision does not license rescheduling, cancelling, completing or
    stamping someone else's work — so a Programme Lead cannot reach this act
    at all. The two rules together made funded work permanently uncancellable:
    the CCEO newly forbidden, the Programme Lead forbidden all along. The
    financial control the escalation was reaching for already exists
    downstream — the disbursed advance survives cancellation and still has to
    be accounted for (FIN-01, FIN-04, and Journey 8 walks it).

    These tests pin what is actually true, so the next person who has that
    same idea meets a red test and this note rather than a deadlock.
    """

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Authority Region")
        cls.district = District.objects.create(
            name="Authority District", region=cls.region, district_type="primary"
        )
        cls.school = School.objects.create(
            school_id="CANCEL-AUTH",
            name="Authority School",
            region=cls.region,
            district=cls.district,
            school_type="client",
            enrollment=200,
        )
        cls.cceo = User.objects.create_user(
            email="auth-cceo@edify.org",
            name="Authority CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            password="pw-cancel-003",
            is_active=True,
        )
        cls.cceo_staff = StaffProfile.objects.create(
            user=cls.cceo, staff_number="ST-AUTH-CCEO", country="Uganda"
        )
        StaffSchoolAssignment.objects.create(
            staff=cls.cceo_staff, school_id=cls.school.id
        )
        cls.pl = User.objects.create_user(
            email="auth-pl@edify.org",
            name="Authority PL",
            roles=["Program Lead"],
            active_role="Program Lead",
            password="pw-cancel-004",
            is_active=True,
        )
        cls.pl_staff = StaffProfile.objects.create(
            user=cls.pl, staff_number="ST-AUTH-PL", country="Uganda"
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=cls.pl_staff, supervisee=cls.cceo_staff
        )

    def _activity(self):
        return Activity.objects.create(
            school=self.school,
            activity_type="school_visit",
            status="scheduled",
            fy=get_operational_fy(),
            planned_date=timezone.localdate() + datetime.timedelta(days=5),
            responsible_staff_id=str(self.cceo_staff.id),
        )

    def test_the_responsible_cceo_may_cancel_their_own_work(self):
        from apps.activities import services

        activity = self._activity()

        services.cancel(
            str(activity.id), {"reason": "Head teacher transferred."}, self.cceo
        )

        activity.refresh_from_db()
        self.assertEqual(activity.status, "cancelled")

    def test_a_supervising_programme_lead_may_not_cancel_it_for_them(self):
        """§1B, asserted at the act. This is also why the money-based
        escalation described in the class docstring could not work."""
        from apps.activities import services

        activity = self._activity()

        with self.assertRaises(Forbidden):
            services.cancel(
                str(activity.id), {"reason": "Tidying my team's plan."}, self.pl
            )

        activity.refresh_from_db()
        self.assertEqual(activity.status, "scheduled")

    def test_funded_work_is_still_cancellable_by_its_owner(self):
        """The deadlock check. If cancellation ever escalates on money again,
        this test is what says the escalation has to go somewhere reachable."""
        from apps.activities import services
        from apps.activities.models import ActivityScheduleCostLine
        from apps.fund_requests.models import AdvanceRequest, AdvanceRequestStatus

        activity = self._activity()
        line = ActivityScheduleCostLine.objects.create(
            activity=activity,
            cost_setting_key="transport",
            label="Transport",
            unit_cost=50_000,
            quantity=1,
            amount=50_000,
        )
        AdvanceRequest.objects.create(
            activity=activity,
            budget_line=line,
            responsible_user_id=str(self.cceo_staff.id),
            fy=get_operational_fy(),
            quarter="Q1",
            amount=50_000,
            status=AdvanceRequestStatus.DISBURSED,
            disbursed_amount=50_000,
        )

        services.cancel(
            str(activity.id), {"reason": "School closed for the term."}, self.cceo
        )

        activity.refresh_from_db()
        self.assertEqual(
            activity.status,
            "cancelled",
            "funded work could not be cancelled by anyone — a deadlock.",
        )
        self.assertTrue(
            AdvanceRequest.objects.filter(
                activity=activity, status=AdvanceRequestStatus.DISBURSED
            ).exists(),
            "cancelling deleted an advance whose money had already moved.",
        )
