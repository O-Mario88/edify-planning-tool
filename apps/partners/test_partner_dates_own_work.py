"""A partner's work is dated by the partner (owner, 2026-10-05).

"Also partner the date on the partner assignment drawer should change from
target date to assigned date so that the staff cannot schedule for the
partner. Block any potential scheduling for the partner visit."
"""

from __future__ import annotations

from datetime import date, timedelta
from importlib import import_module

from django.apps import apps as django_apps
from django.template.loader import render_to_string
from django.utils import timezone

from apps.accounts.models import User
from apps.activities import services as activity_services
from apps.activities.models import Activity
from apps.core.enums import ExecutorType
from apps.core.exceptions import Forbidden
from apps.core.rbac import EdifyRole
from apps.partners import dating_policy
from apps.partners.models import PartnerAssignment
from apps.partners.services import create_assignment
from apps.planning import partner_oversight_service
from apps.planning.test_partner_oversight import PartnerOversightFixture

clear_target_dates = import_module(
    "apps.partners.migrations.0032_clear_handover_target_dates"
).clear_target_dates


class _Fixture(PartnerOversightFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.partner_user = User.objects.create(
            email="officer@p.test",
            name="Partner Officer",
            roles=[EdifyRole.PARTNER_FIELD_OFFICER.value],
            active_role=EdifyRole.PARTNER_FIELD_OFFICER.value,
            is_active=True,
        )
        cls.partner.user = cls.partner_user
        cls.partner.save(update_fields=["user"])

    def activity(self, *, delivery="partner", status="partner_scheduled", **fields):
        planned = date.today() + timedelta(days=6)
        return Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            fy=self.fy,
            quarter="Q1",
            planned_date=planned,
            planned_month=planned.month,
            scheduled_date=timezone.now() + timedelta(days=6),
            status=status,
            delivery_type=delivery,
            assigned_partner_id=self.partner.id if delivery == "partner" else None,
            monitored_by_staff_id=self.cceo.id,
            responsible_staff_id=None if delivery == "partner" else self.cceo.id,
            **fields,
        )

    @property
    def another_day(self):
        return (date.today() + timedelta(days=9)).isoformat()


class TheRuleTest(_Fixture):
    def test_staff_are_told_who_chooses_the_date_and_what_to_do(self):
        with self.assertRaises(Forbidden) as refused:
            dating_policy.assert_partner_dates_it(self.cceo_user, self.partner.id)

        message = str(refused.exception)
        self.assertIn("Partner X chooses the date", message)
        self.assertIn("Assign the school to the partner", message)
        self.assertIn("withdraw it", message)

    def test_a_program_lead_is_staff_too(self):
        with self.assertRaises(Forbidden):
            dating_policy.assert_partner_dates_it(self.pl_user, self.partner.id)

    def test_the_partner_s_own_user_is_not_refused(self):
        dating_policy.assert_partner_dates_it(self.partner_user, self.partner.id)

    def test_an_agency_edify_booked_is_staff_s_to_move(self):
        booked = self.activity(
            executor_type=ExecutorType.CERTIFIED_PARTNER_AGENCY.value
        )
        self.assertTrue(dating_policy.is_agency_booking(booked))
        activity_services._assert_partner_dates_own_work(booked, self.cceo_user)

    def test_staff_work_is_not_the_rule_s_business(self):
        activity_services._assert_partner_dates_own_work(
            self.activity(delivery="staff", status="scheduled"), self.cceo_user
        )


class StaffCannotDateItTest(_Fixture):
    def assert_refused(self, call):
        with self.assertRaises(Forbidden) as refused:
            call()
        self.assertIn("chooses the date", str(refused.exception))

    def test_staff_cannot_date_a_hand_over(self):
        handover = self.assign(status="pending_scheduling")

        self.assert_refused(
            lambda: activity_services.partner_schedule(
                handover.id,
                {"scheduledDate": self.another_day, "deliveryContactName": "James"},
                self.cceo_user,
            )
        )

        handover.refresh_from_db()
        self.assertEqual(handover.status, "pending_scheduling")
        self.assertIsNone(handover.scheduled_date)
        self.assertFalse(Activity.objects.exists())

    def test_staff_cannot_date_work_waiting_for_the_partner(self):
        waiting = self.activity(status="assigned_to_partner")
        before = waiting.planned_date

        self.assert_refused(
            lambda: activity_services.partner_schedule(
                waiting.id, {"scheduledDate": self.another_day}, self.cceo_user
            )
        )

        waiting.refresh_from_db()
        self.assertEqual(waiting.planned_date, before)
        self.assertEqual(waiting.status, "assigned_to_partner")

    def test_staff_cannot_move_the_partner_s_day(self):
        scheduled = self.activity()
        before = scheduled.planned_date

        self.assert_refused(
            lambda: activity_services.reschedule(
                scheduled.id,
                {"scheduledDate": self.another_day, "reason": "The head is away."},
                self.cceo_user,
            )
        )

        scheduled.refresh_from_db()
        self.assertEqual(scheduled.planned_date, before)
        self.assertEqual(scheduled.reschedule_count or 0, 0)

    def test_a_dated_staff_visit_does_not_become_the_partner_s_on_that_day(self):
        visit = self.activity(delivery="staff", status="scheduled")

        self.assert_refused(
            lambda: activity_services.reassign(
                visit.id,
                {"deliveryType": "partner", "assignedPartnerId": self.partner.id},
                self.cceo_user,
            )
        )

        visit.refresh_from_db()
        self.assertEqual(visit.delivery_type, "staff")
        self.assertIsNone(visit.assigned_partner_id)


class AHandoverCarriesNoDateTest(_Fixture):
    def test_the_creation_door_stores_no_date(self):
        handover = create_assignment(
            school=self.school,
            partner=self.partner,
            assigning_staff_id=self.cceo.id,
            monitoring_staff_id=self.cceo.id,
            expected_activity_type="school_visit",
            purpose_of_visit="training_follow_up",
            scheduled_date=date.today() + timedelta(days=14),
        )

        handover.refresh_from_db()
        self.assertIsNone(handover.scheduled_date)
        self.assertEqual(handover.status, PartnerAssignment.STATUS_PENDING_SCHEDULING)

    def test_the_assigned_date_is_the_day_it_was_made(self):
        handover = self.assign()

        item = partner_oversight_service.build_item_by_assignment(handover.id)

        self.assertEqual(item.assignment_date, handover.created_at.date())
        self.assertIsNone(item.schedule_by_date)

    def test_a_date_stored_earlier_is_not_read_as_a_deadline(self):
        handover = self.assign(scheduled_date=date.today() - timedelta(days=3))

        item = partner_oversight_service.build_item_by_assignment(handover.id)

        self.assertIsNone(item.schedule_by_date)
        self.assertIsNone(item.activity_date)

    def test_the_drawer_shows_the_assigned_date_and_asks_for_none(self):
        html = render_to_string("partials/partners/_assigned_date.html")

        self.assertIn("Assigned date", html)
        self.assertIn(f"{timezone.localdate():%-d %b %Y}", html)
        self.assertIn("The partner chooses the date of the work", html)
        self.assertNotIn("<input", html)


class TargetDatesAlreadyStoredTest(_Fixture):
    def test_a_waiting_hand_over_loses_its_target_date(self):
        waiting = self.assign(
            status="pending_scheduling",
            scheduled_date=date.today() + timedelta(days=20),
        )
        made = waiting.created_at

        clear_target_dates(django_apps, None)

        waiting.refresh_from_db()
        self.assertIsNone(waiting.scheduled_date)
        self.assertEqual(waiting.created_at, made)
        self.assertEqual(waiting.status, "pending_scheduling")

    def test_work_the_partner_scheduled_keeps_its_date(self):
        handover = self.assign()
        activity = self.schedule(handover)

        clear_target_dates(django_apps, None)

        handover.refresh_from_db()
        self.assertEqual(handover.scheduled_date, activity.planned_date)

    def test_a_hand_back_keeps_what_it_recorded(self):
        returned = self.assign(
            status=PartnerAssignment.STATUS_RETURNED_TO_STAFF,
            scheduled_date=date.today() + timedelta(days=4),
        )

        clear_target_dates(django_apps, None)

        returned.refresh_from_db()
        self.assertIsNotNone(returned.scheduled_date)
