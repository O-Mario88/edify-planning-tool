"""One copy of a client school visit per school per day.

Owner, 2026-09-26: "a lot of users created duplicate client school visits ...
make sure all the duplicate visits on the same day same month all deleted from
the database just like you did with duplicate assignment to partner."

The first class is the rule the deploy migration applies to the data already
there (apps.activities.duplicate_visits): what is a duplicate, which copy
stays, and what removing a copy withdraws. The second runs that rule against
the schema of migration 0058 itself. The last is the scheduling guard that
stops new copies arriving.
"""

from __future__ import annotations

import datetime
from io import StringIO

from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.activities.duplicate_visits import (
    find_duplicate_client_visits,
    remove_duplicate_client_visits,
)
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.exceptions import BadRequest
from apps.core.fy import get_operational_fy
from apps.evidence.models import EvidenceRecord
from apps.fund_requests.models import AdvanceRequest
from apps.geography.models import District, Region
from apps.notifications.models import Notification
from apps.partners.models import Partner, PartnerAssignment
from apps.planning.test_standard_support_scheduling import (
    StandardSupportBase,
    _at,
    _schedulable_date,
)
from apps.schools.models import School


def _silent(*_args):
    pass


class _DuplicateFixture:
    """Not a TestCase, so its (absent) tests are never collected twice."""

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="DV Region")
        cls.district = District.objects.create(name="DV District", region=cls.region)
        cls.users = {}
        for key in ("one", "two"):
            user = User.objects.create(
                id=f"dv-{key}",
                email=f"dv-{key}@edify.org",
                name=f"DV Officer {key.title()}",
                roles=["CCEO"],
                active_role="CCEO",
                is_active=True,
            )
            cls.users[key] = StaffProfile.objects.create(
                id=f"dv-{key}-sp", user=user, title="CCEO", country="Uganda"
            )
        cls.partner_user = User.objects.create(
            id="dv-partner-user",
            email="dv-partner@edify.org",
            name="DV Partner User",
            roles=["PartnerFieldOfficer"],
            active_role="PartnerFieldOfficer",
            is_active=True,
        )
        cls.partner = Partner.objects.create(
            name="DV Partner Org", user_id=cls.partner_user.id
        )
        cls.day = datetime.date.today() + datetime.timedelta(days=10)

    def _school(self, code, school_type="client"):
        return School.objects.create(
            school_id=code,
            name=f"School {code}",
            region=self.region,
            district=self.district,
            school_type=school_type,
        )

    def _visit(self, school, *, who="one", day=None, kind="school_visit", **extra):
        day = day or self.day
        partner = extra.pop("partner", False)
        fields = {
            "activity_type": kind,
            "status": "partner_scheduled" if partner else "scheduled",
            "fy": get_operational_fy(),
            "school": school,
            "planned_date": day,
            "scheduled_date": _at(day),
            "delivery_type": "partner" if partner else "staff",
            "responsible_staff_id": None if partner else self.users[who].id,
            "assigned_partner_id": self.partner.id if partner else None,
        }
        fields.update(extra)
        return Activity.objects.create(**fields)


class DuplicateClientVisitRuleTest(_DuplicateFixture, TestCase):
    def test_the_same_visit_twice_on_one_day_keeps_the_earliest(self):
        school = self._school("DV-1")
        first = self._visit(school, who="one")
        second = self._visit(school, who="two")

        groups = find_duplicate_client_visits()

        self.assertEqual(len(groups), 1)
        self.assertEqual([c.id for c in groups[0].kept], [first.id])
        self.assertEqual([c.id for c in groups[0].removed], [second.id])
        self.assertEqual(groups[0].day, self.day)

    def test_different_days_kinds_and_school_types_are_not_duplicates(self):
        school = self._school("DV-2")
        self._visit(school)
        self._visit(school, day=self.day + datetime.timedelta(days=1))
        self._visit(school, kind="baseline_ssa_visit")
        core = self._school("DV-2C", school_type="core")
        self._visit(core, kind="core_visit")
        self._visit(core, kind="core_visit")
        # The in-school training's companion visit is the training.
        self._visit(school, purpose_type="in_school_training_delivery_visit")

        self.assertEqual(find_duplicate_client_visits(), [])

    def test_called_off_copies_are_not_counted(self):
        school = self._school("DV-3")
        self._visit(school)
        self._visit(school, status="cancelled")
        self._visit(school, deleted_at=timezone.now())

        self.assertEqual(find_duplicate_client_visits(), [])

    def test_a_delivered_copy_stays_and_every_plan_beside_it_goes(self):
        school = self._school("DV-4")
        plan_a = self._visit(school, who="one")
        done = self._visit(
            school,
            who="two",
            status="completed",
            salesforce_activity_id="SV-DV-4",
        )
        plan_b = self._visit(school, who="two")

        [group] = find_duplicate_client_visits()

        self.assertEqual([c.id for c in group.kept], [done.id])
        self.assertCountEqual([c.id for c in group.removed], [plan_a.id, plan_b.id])

    def test_two_delivered_copies_are_both_left_alone(self):
        school = self._school("DV-5")
        with_evidence = self._visit(school, who="one")
        EvidenceRecord.objects.create(
            activity=with_evidence, uri="dv-5.pdf", kind="visit_form"
        )
        self._visit(school, who="two", execution_started_at=timezone.now())

        self.assertEqual(find_duplicate_client_visits(), [])

    def test_the_partner_handover_copy_is_preferred_over_an_earlier_plan(self):
        school = self._school("DV-6")
        staff_copy = self._visit(school, who="one")
        partner_copy = self._visit(school, partner=True)
        PartnerAssignment.objects.create(
            school=school,
            partner=self.partner,
            assigning_staff_id=self.users["one"].id,
            status=PartnerAssignment.STATUS_SCHEDULED,
            scheduled_activity=partner_copy,
        )

        [group] = find_duplicate_client_visits()

        self.assertEqual([c.id for c in group.kept], [partner_copy.id])
        self.assertEqual([c.id for c in group.removed], [staff_copy.id])

    def test_removing_a_copy_cancels_tombstones_and_withdraws_its_money(self):
        school = self._school("DV-7")
        keeper = self._visit(school, who="one")
        extra = self._visit(school, who="two")
        line = ActivityScheduleCostLine.objects.create(
            activity=extra,
            cost_setting_key="transport",
            label="Transport",
            unit_cost=20000,
            amount=20000,
        )
        AdvanceRequest.objects.create(
            activity=extra, budget_line=line, fy=extra.fy, quarter="Q1", amount=20000
        )
        notice = Notification.objects.create(
            recipient_id=self.users["two"].user_id,
            title="Visit tomorrow",
            body="",
            context_type="Activity",
            context_id=extra.id,
        )

        result = remove_duplicate_client_visits(out=_silent)

        self.assertEqual(result["removed"], [extra.id])
        self.assertFalse(Activity.objects.filter(id=extra.id).exists())
        gone = Activity.all_objects.get(id=extra.id)
        self.assertIsNotNone(gone.deleted_at)
        self.assertEqual(gone.status, "cancelled")
        self.assertIn(keeper.id, gone.last_reason)
        self.assertFalse(AdvanceRequest.objects.filter(activity_id=extra.id).exists())
        notice.refresh_from_db()
        self.assertIsNotNone(notice.resolved_at)
        self.assertEqual(notice.status, "archived")
        # The copy that stays is untouched.
        keeper.refresh_from_db()
        self.assertEqual(keeper.status, "scheduled")
        self.assertIsNone(keeper.deleted_at)
        self.assertEqual(find_duplicate_client_visits(), [])

    def test_a_copy_whose_advance_was_paid_out_is_never_removed(self):
        school = self._school("DV-8")
        self._visit(school, who="one")
        paid = self._visit(school, who="two")
        line = ActivityScheduleCostLine.objects.create(
            activity=paid,
            cost_setting_key="transport",
            label="Transport",
            unit_cost=20000,
            amount=20000,
        )
        AdvanceRequest.objects.create(
            activity=paid,
            budget_line=line,
            fy=paid.fy,
            quarter="Q1",
            amount=20000,
            status="disbursed",
        )

        [group] = find_duplicate_client_visits()
        self.assertEqual([c.id for c in group.kept], [paid.id])
        self.assertEqual(group.kept[0].history, "money moved")

        remove_duplicate_client_visits(out=_silent)
        paid.refresh_from_db()
        self.assertIsNone(paid.deleted_at)
        self.assertEqual(AdvanceRequest.objects.filter(activity=paid).count(), 1)

    def test_the_partner_is_told_when_its_booking_is_the_one_removed(self):
        school = self._school("DV-9")
        self._visit(school, who="one", status="completed", salesforce_activity_id="X")
        self._visit(school, partner=True)

        remove_duplicate_client_visits(out=_silent)

        self.assertTrue(
            Notification.objects.filter(
                recipient_id=self.partner_user.id,
                source_event_type="partner_booking_duplicate_removed",
            ).exists()
        )

    def test_a_copy_that_fails_is_rolled_back_alone(self):
        """The deploy must not stop over one odd row: it stays as it was, the
        output names it, and the other copies are still removed."""
        from unittest.mock import patch

        from apps.activities import services

        school = self._school("DV-11")
        self._visit(school, who="one")
        odd = self._visit(school, who="two")
        fine = self._visit(school, who="two", kind="school_visit")
        real = services._detach_from_daily_visit_batch

        def detach(a):
            if a.id == odd.id:
                raise RuntimeError("batch is inconsistent")
            return real(a)

        lines = []
        with patch.object(services, "_detach_from_daily_visit_batch", detach):
            result = remove_duplicate_client_visits(out=lines.append)

        self.assertEqual(result["removed"], [fine.id])
        self.assertEqual(len(result["failed"]), 1)
        self.assertIn(odd.id, result["failed"][0])
        self.assertTrue(any("NOT removed" in line for line in lines))
        odd.refresh_from_db()
        self.assertEqual(odd.status, "scheduled")
        self.assertIsNone(odd.deleted_at)

    def test_the_command_lists_without_writing_and_removes_with_apply(self):
        school = self._school("DV-10")
        self._visit(school, who="one")
        extra = self._visit(school, who="two")

        out = StringIO()
        call_command("remove_duplicate_client_visits", stdout=out)
        self.assertIn("Would remove 1 duplicate", out.getvalue())
        self.assertIn(extra.id, out.getvalue())
        self.assertTrue(Activity.objects.filter(id=extra.id).exists())

        call_command("remove_duplicate_client_visits", "--apply", stdout=StringIO())
        self.assertFalse(Activity.objects.filter(id=extra.id).exists())

        out = StringIO()
        call_command("remove_duplicate_client_visits", stdout=out)
        self.assertIn("No duplicate client school visits.", out.getvalue())


class MigrationSchemaTest(_DuplicateFixture, TestCase):
    """0058 reads the data through its own historical models; every field and
    relation the rule names has to exist in that state."""

    def test_the_rule_runs_on_the_migration_state(self):
        from django.db.migrations.loader import MigrationLoader

        school = self._school("DV-M")
        self._visit(school, who="one")
        extra = self._visit(school, who="two")
        state = MigrationLoader(connection).project_state(
            ("activities", "0058_remove_duplicate_client_visits")
        )

        [group] = find_duplicate_client_visits(state.apps)

        self.assertEqual([c.id for c in group.removed], [extra.id])


class SameDayVisitGuardTest(StandardSupportBase):
    """Scheduling refuses a second copy of a client visit on one day, whoever
    plans it; the old guard only caught the same owner planning it twice."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.other_user = User.objects.create_user(
            email="standard-cceo-2@edify.org",
            name="Second CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            password="x",
            is_active=True,
        )
        cls.other_staff = StaffProfile.objects.create(
            user=cls.other_user, staff_number="ST-STD-2", country="Uganda"
        )
        StaffSchoolAssignment.objects.create(
            staff=cls.other_staff, school_id=cls.school.id
        )

    def _plan(self, user, day):
        from apps.activities.services import create

        return create(
            {
                "scheduledDate": _at(day).isoformat(),
                "requireCatalogue": True,
                "schoolId": self.school.school_id,
                "catalogueItemId": self.item("STANDARD_SCHOOL_VISIT").id,
                "focusIntervention": "leadership",
                "activityPurposeText": "Coach the head teacher on delegation",
                "visitJustification": "Covering for the owner.",
            },
            user,
        )

    def test_a_second_planner_cannot_book_the_same_visit_that_day(self):
        day = _schedulable_date(room=10)
        self._plan(self.user, day)

        with self.assertRaisesMessage(BadRequest, "already has this visit on"):
            self._plan(self.other_user, day)

    def test_another_day_is_still_open(self):
        day = _schedulable_date(room=10)
        self._plan(self.user, day)
        next_day = day + datetime.timedelta(days=1)
        if next_day.weekday() == 6:
            next_day += datetime.timedelta(days=1)

        self._plan(self.other_user, next_day)

    def test_a_reschedule_cannot_move_onto_a_taken_day(self):
        from apps.activities.services import reschedule

        day = _schedulable_date(room=10)
        self._plan(self.user, day)
        other_day = day + datetime.timedelta(days=1)
        if other_day.weekday() == 6:
            other_day += datetime.timedelta(days=1)
        moved = self._plan(self.user, other_day)

        with self.assertRaisesMessage(BadRequest, "already has this visit on"):
            reschedule(
                moved["id"],
                {"scheduledDate": _at(day).isoformat(), "reason": "Swap"},
                self.user,
            )
