"""Country Oversight reads every school a Partner holds (owner, 2026-09-29).

"Country → Program Lead → CCEO → Partner drill-down table is not fetching all
the data ... Staff Planned, Partner Assigned, Partner Scheduled don't have
data and yet the staff planned and assigned to partners."

Two holes, both closed here:

* A handover still waiting for its Partner's date was read only in the fiscal
  year it was made. One made in September for October's work vanished from
  the year being planned — Partner Oversight counts it as assigned today,
  whichever year it was made in (owner, 2026-09-28).
* A planned visit moved onto a Partner becomes an activity awaiting the
  Partner's date (``assigned_to_partner``) with no handover row. It is no plan
  yet, and it was no handover either, so it counted nowhere.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from django.utils import timezone

from apps.partners.models import PartnerAssignment
from apps.planning.test_country_planning_oversight import FY, FY_START, World


def _moment(day):
    return timezone.make_aware(datetime.combine(day, time(9, 0)))


class AnOpenHandoverFromLastYearTest(World):
    def test_it_counts_as_assigned_in_the_year_being_read(self):
        school = self.school("client", self.cceo)
        handover = self.handover(school, self.partner, status="pending_scheduling")
        PartnerAssignment.objects.filter(id=handover.id).update(
            created_at=_moment(FY_START - timedelta(days=3))
        )

        tree = self.tree()
        owner = self.owner_row(tree, self.cceo)

        self.assertEqual(tree.country.partner_assigned, 1)
        self.assertEqual(tree.country.partner_scheduled, 0)
        self.assertEqual(owner.tally.partner_assigned, 1)
        self.assertEqual(owner.partners[self.partner.id].partner_assigned, 1)

    def test_it_is_not_read_into_a_year_before_it_was_made(self):
        school = self.school("client", self.cceo)
        handover = self.handover(school, self.partner)
        PartnerAssignment.objects.filter(id=handover.id).update(
            created_at=_moment(FY_START + timedelta(days=400))
        )

        self.assertEqual(self.tree().country.partner_assigned, 0)

    def test_once_dated_the_activity_it_became_is_the_record(self):
        school = self.school("core", self.cceo)
        activity = self.activity(
            school, "core_visit", status="partner_scheduled", partner=self.partner
        )
        handover = self.handover(
            school,
            self.partner,
            status=PartnerAssignment.STATUS_SCHEDULED,
            scheduled_activity=activity,
        )
        PartnerAssignment.objects.filter(id=handover.id).update(
            created_at=_moment(FY_START - timedelta(days=3))
        )

        t = self.tree().country
        self.assertEqual((t.partner_assigned, t.partner_scheduled), (1, 1))


class AVisitMovedOntoAPartnerTest(World):
    def test_it_counts_as_partner_assigned_not_staff_planned(self):
        school = self.school("core", self.cceo)
        self.activity(
            school,
            "core_visit",
            status="assigned_to_partner",
            owner=self.cceo,
            partner=self.partner,
        )

        tree = self.tree()
        owner = self.owner_row(tree, self.cceo)

        self.assertEqual(tree.country.staff, 0)
        self.assertEqual(tree.country.partner_assigned, 1)
        self.assertEqual(tree.country.partner_scheduled, 0)
        self.assertEqual(owner.partners[self.partner.id].partner_assigned, 1)

    def test_an_undated_one_counts_in_the_year(self):
        school = self.school("core", self.cceo)
        self.activity(
            school,
            "core_visit",
            status="assigned_to_partner",
            on=None,
            partner=self.partner,
        )

        self.assertEqual(self.tree().country.partner_assigned, 1)
        self.assertEqual(
            self.tree(period="quarter", quarter="Q1").country.partner_assigned, 1
        )
        self.assertEqual(
            self.tree(period="quarter", quarter="Q3").country.partner_assigned, 0
        )

    def test_it_is_not_counted_twice_when_a_handover_carries_it(self):
        school = self.school("core", self.cceo)
        activity = self.activity(
            school,
            "core_visit",
            status="assigned_to_partner",
            partner=self.partner,
        )
        self.handover(school, self.partner, source_activity=activity)

        self.assertEqual(self.tree().country.partner_assigned, 1)

    def test_other_years_work_stays_in_its_year(self):
        school = self.school("core", self.cceo)
        self.activity(
            school,
            "core_visit",
            status="assigned_to_partner",
            partner=self.partner,
        )

        self.assertEqual(self.tree(fy=str(int(FY) + 1)).country.partner_assigned, 0)
