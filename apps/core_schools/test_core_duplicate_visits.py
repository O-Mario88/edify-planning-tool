"""Duplicate Core School visits on one day (owner, 2026-09-27; lifted 2026-09-28).

The rule below was the owner's on 2026-09-27 and was lifted the next day with
every other scheduling restriction but the client school's one staff visit
("lift all restrictions"). The finder still answers what a duplicate is, for
anyone who shows it; an exact repeat of one submission is still refused by
the identical-activity guard every activity passes.

"No core visits duplicate on the same day. Right new we are planning for next
fy so that is fine but no duplicate visit for the same day same intervention
and same person."

A duplicate is a second live visit at the same Core School, on the same day,
for the same SSA intervention, by the same person — the responsible officer
for staff work, the partner for partner work. Anything that differs in one of
those is separate work, and planning into the next fiscal year is untouched.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase

from apps.activities.duplicate_visits import existing_same_day_core_visit
from apps.activities.models import Activity
from apps.core_schools.test_core_visit_purposes import _CoreFixture, _today
from apps.geography.models import District, Region
from apps.schools.models import School

DAY = date(2026, 10, 6)  # a Tuesday in the next fiscal year: planning it is fine


class WhatCountsAsADuplicateTest(TestCase):
    def setUp(self):
        region = Region.objects.create(name="Dup Region")
        district = District.objects.create(name="Dup District", region=region)
        self.school = School.objects.create(
            school_id="DUP-CORE",
            name="Dup Core Primary",
            school_type="core",
            region=region,
            district=district,
        )

    def _visit(self, **fields):
        defaults = {
            "activity_type": "core_visit",
            "school": self.school,
            "fy": "2027",
            "quarter": "Q1",
            "planned_date": DAY,
            "status": "scheduled",
            "delivery_type": "staff",
            "responsible_staff_id": "officer-a",
            "focus_intervention": "leadership",
        }
        defaults.update(fields)
        return Activity.objects.create(**defaults)

    def _found(self, **kwargs):
        ask = {
            "activity_type": "core_visit",
            "day": DAY,
            "focus_intervention": "leadership",
            "delivery_type": "staff",
            "staff_id": "officer-a",
        }
        ask.update(kwargs)
        return existing_same_day_core_visit(self.school, **ask)

    def test_same_day_same_intervention_same_person_is_a_duplicate(self):
        booked = self._visit()
        self.assertEqual(self._found(), booked)
        # Whatever door booked it: a plain school visit at a core school is
        # the same visit.
        self.assertEqual(self._found(activity_type="school_visit"), booked)

    def test_a_different_day_intervention_or_person_is_separate_work(self):
        self._visit()
        self.assertIsNone(self._found(day=DAY + timedelta(days=1)))
        self.assertIsNone(self._found(focus_intervention="financial_health"))
        self.assertIsNone(self._found(staff_id="officer-b"))
        self.assertIsNone(
            self._found(delivery_type="partner", partner_id="partner-1"),
            "a partner's visit beside the officer's is its own work",
        )

    def test_a_partner_cannot_book_itself_twice_on_one_day(self):
        booked = self._visit(
            delivery_type="partner",
            assigned_partner_id="partner-1",
            responsible_staff_id=None,
        )
        self.assertEqual(
            self._found(delivery_type="partner", partner_id="partner-1"), booked
        )

    def test_ssa_data_gathering_visits_share_no_intervention(self):
        booked = self._visit(focus_intervention=None, purpose_type="ssa_support")
        self.assertEqual(self._found(focus_intervention=None), booked)

    def test_called_off_work_and_the_training_s_companion_are_not_visits(self):
        self._visit(status="cancelled")
        self._visit(
            activity_type="school_visit",
            purpose_type="in_school_training_delivery_visit",
        )
        self.assertIsNone(self._found())

    def test_a_rescheduled_visit_does_not_duplicate_itself(self):
        booked = self._visit()
        self.assertIsNone(self._found(exclude_activity_id=booked.id))

    def test_client_schools_keep_their_own_rule(self):
        self.school.school_type = "client"
        self.school.save(update_fields=["school_type"])
        self._visit(activity_type="follow_up_visit")
        self.assertIsNone(self._found(activity_type="follow_up_visit"))


class TheCoreDrawerRefusesTheSecondCopyTest(_CoreFixture):
    def test_the_same_visit_twice_on_one_day_is_refused(self):
        day = _today() + timedelta(days=1)
        while day.weekday() == 6:
            day += timedelta(days=1)
        fields = {
            "purpose_of_visit": "donor_visit",
            "scheduled_date": day.isoformat(),
        }
        first = self._post_visit(**fields)
        self.assertEqual(first.status_code, 200, first.content[:300])

        second = self._post_visit(**fields)

        # Refused — by the identical-copy guard for an exact repeat, by the
        # core rule for the same visit booked as another type.
        self.assertEqual(second.status_code, 400)
        self.assertIn("already", second.content.decode())
        # A donor visit is booked as itself, not as a core visit (owner,
        # 2026-09-30: not package work).
        self.assertEqual(
            Activity.objects.filter(
                school=self.school, activity_type="donor_visit", planned_date=day
            ).count(),
            1,
        )

    def test_the_service_no_longer_refuses_it(self):
        from apps.activities.duplicate_visits import assert_not_duplicate_core_visit

        Activity.objects.create(
            activity_type="core_visit",
            school=self.school,
            fy=self.plan.fy,
            quarter="Q1",
            planned_date=DAY,
            status="scheduled",
            delivery_type="staff",
            responsible_staff_id=self.cceo_sp.id,
            focus_intervention="leadership",
        )
        kwargs = {
            "activity_type": "school_visit",
            "day": DAY,
            "focus_intervention": "leadership",
            "delivery_type": "staff",
            "staff_id": self.cceo_sp.id,
        }
        self.assertIsNotNone(existing_same_day_core_visit(self.school, **kwargs))
        assert_not_duplicate_core_visit(self.school, **kwargs)  # no BadRequest
