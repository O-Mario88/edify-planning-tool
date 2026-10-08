"""What earlier cancellations left behind is put right once.

`apps.activities.cancelled_work`: rows written before a cancellation undid
its scheduling (owner, 2026-10-08) — a Core package slot still pointing at a
cancelled visit, a hand-over still "scheduled by the partner" on a cancelled
activity. Pinned here: the finder names exactly those rows, a dry run changes
nothing, the repair renumbers the package and settles the hand-over, and a
hand-over from a year that has closed is closed rather than handed back.
"""

from __future__ import annotations

from datetime import date, timedelta

from apps.activities import cancelled_work
from apps.activities.models import Activity
from apps.core_schools.models import CoreActivitySlot
from apps.core_schools.test_package_credit import _PackageFixture
from apps.partners.models import PartnerAssignment


def _in(days: int) -> date:
    return date.today() + timedelta(days=days)


class _Left(_PackageFixture):
    def find(self) -> dict:
        return cancelled_work.find(CoreActivitySlot, Activity, PartnerAssignment)

    def cancelled_the_old_way(self, activity) -> None:
        """As the old code left it: the status changes, the slot mirrors it
        and keeps pointing at the activity."""
        Activity.objects.filter(id=activity.id).update(status="cancelled")
        CoreActivitySlot.objects.filter(activity_id=activity.id).update(
            status="cancelled"
        )

    def stuck_handover(self, *, fy=None, **activity_fields):
        activity = Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            fy=fy or self.fy,
            quarter="Q1",
            planned_date=_in(4),
            status="cancelled",
            delivery_type="partner",
            assigned_partner_id=self.partner.id,
            **activity_fields,
        )
        handover = PartnerAssignment.objects.create(
            school=self.school,
            partner=self.partner,
            assigning_staff_id="left-staff",
            expected_activity_type="school_visit",
            status=PartnerAssignment.STATUS_PARTNER_SCHEDULED,
            scheduled_activity=activity,
            scheduled_date=_in(4),
        )
        return activity, handover


class NothingLeftTest(_Left):
    def test_a_database_with_live_work_only_has_nothing_to_repair(self):
        self._activity(on=_in(2))

        self.assertEqual(self.find(), {"slots": [], "handovers": []})
        self.assertEqual(
            cancelled_work.repair(write=True, out=lambda _line: None),
            {"slots": 0, "renumbered": 0, "reopened": 0, "closed": 0, "skipped": 0},
        )


class SlotsLeftOnCancelledWorkTest(_Left):
    def setUp(self):
        super().setUp()
        self.first = self._activity(on=_in(2))
        self.second = self._activity(on=_in(5))
        self.cancelled_the_old_way(self.first)

    def test_the_finder_names_the_slot(self):
        self.assertEqual(self.find()["slots"], [self._slot("v", 1).id])

    def test_a_dry_run_lists_it_and_changes_nothing(self):
        lines: list[str] = []

        report = cancelled_work.repair(write=False, out=lines.append)

        self.assertEqual(report["slots"], 1)
        self.assertIn("given back", "\n".join(lines))
        self.assertEqual(self._slot("v", 1).activity_id, self.first.id)

    def test_the_repair_gives_the_slot_back_and_renumbers(self):
        lines: list[str] = []

        report = cancelled_work.repair(write=True, out=lines.append)

        self.assertEqual((report["slots"], report["renumbered"]), (1, 1))
        self.assertEqual(self._slot("v", 1).activity_id, self.second.id)
        self.assertIsNone(self._slot("v", 2).activity_id)
        self.assertEqual(self._slot("v", 2).status, "Planned")
        self.assertEqual(self._visits(), 1)
        self.assertIn("V2 is now V1", "\n".join(lines))
        # Nothing is left for a second run.
        self.assertEqual(self.find()["slots"], [])


class HandoversLeftOnCancelledActivitiesTest(_Left):
    def test_one_the_partner_had_dated_this_year_waits_again(self):
        activity, handover = self.stuck_handover(partner_date_set_by="partner")
        self.assertEqual(self.find()["handovers"], [handover.id])

        report = cancelled_work.repair(write=True, out=lambda _line: None)

        handover.refresh_from_db()
        self.assertEqual(report["reopened"], 1)
        self.assertEqual(handover.status, PartnerAssignment.STATUS_PENDING_SCHEDULING)
        self.assertIsNone(handover.scheduled_activity_id)
        self.assertEqual(Activity.objects.get(id=activity.id).status, "cancelled")
        self.assertEqual(self.find()["handovers"], [])

    def test_one_from_a_year_that_has_closed_is_closed_with_it(self):
        _activity, handover = self.stuck_handover(
            fy=str(int(self.fy) - 1), partner_date_set_by="partner"
        )

        report = cancelled_work.repair(write=True, out=lambda _line: None)

        handover.refresh_from_db()
        self.assertEqual(report["closed"], 1)
        self.assertEqual(handover.status, PartnerAssignment.STATUS_RETURNED_TO_STAFF)
        self.assertTrue(handover.has_left_partner)

    def test_one_staff_had_booked_is_closed(self):
        _activity, handover = self.stuck_handover(partner_date_set_by="staff")

        report = cancelled_work.repair(write=True, out=lambda _line: None)

        handover.refresh_from_db()
        self.assertEqual(report["closed"], 1)
        self.assertEqual(handover.status, PartnerAssignment.STATUS_RETURNED_TO_STAFF)

    def test_a_dry_run_leaves_the_hand_over_as_it_is(self):
        _activity, handover = self.stuck_handover(partner_date_set_by="partner")

        report = cancelled_work.repair(write=False, out=lambda _line: None)

        handover.refresh_from_db()
        self.assertEqual(report["reopened"], 1)
        self.assertEqual(handover.status, PartnerAssignment.STATUS_PARTNER_SCHEDULED)
