"""Cancelled work leaves a Core package, and the numbering resets.

Owner, 2026-10-08: "the cancelled activities should not remain counting for
example if i scheduled school visits on core school and cancelled, it should
stop counting and the v1 or v2 v3 or v4 should be reset back to the actual
scheduled activities. Apply the same on training, T1, T2, T3, T4 display."

A cancelled visit was no longer counted, but it stayed on its slot: with V1
cancelled and V2 booked the package read "V1 not planned, V2 planned" and the
slot still pointed at the cancelled visit. What is pinned here: the slot goes
back, the work still live reads from the first slot in the order it held
them, finished work keeps what it recorded when it moves, a Partner's waiting
hand-over moves with its slot, and a group training gives its slots back the
same way.
"""

from __future__ import annotations

from datetime import date, timedelta

from apps.activities.models import Activity, ClusterActivityAttendance
from apps.clusters.models import Cluster
from apps.core_schools.core_planning_services import (
    CorePackageSchedulingService,
    package_marks,
)
from apps.core_schools.models import CoreActivitySlot
from apps.core_schools.package_credit import close_gaps

from .test_package_credit import _PackageFixture


def _in(days: int) -> date:
    return date.today() + timedelta(days=days)


class _Marks:
    def marks(self, kind: str) -> list[tuple[str, str]]:
        slots = CoreActivitySlot.objects.filter(
            core_plan=self.plan, activity_type=kind
        ).order_by("sequence_number")
        return [(mark["label"], mark["state"]) for mark in package_marks(slots)]

    def set_status(self, activity, status: str) -> None:
        """A status change saved the way every door saves one."""
        with self.captureOnCommitCallbacks(execute=True):
            activity.status = status
            activity.save(update_fields=["status", "updated_at"])

    def held_by(self, kind: str) -> list:
        return list(
            CoreActivitySlot.objects.filter(core_plan=self.plan, activity_type=kind)
            .order_by("sequence_number")
            .values_list("activity_id", flat=True)
        )


class CancelledVisitsLeaveThePackageTest(_Marks, _PackageFixture):
    def test_cancelling_the_first_visit_makes_the_second_v1(self):
        first = self._activity(on=_in(2))
        second = self._activity("follow_up_visit", on=_in(5))
        self.assertEqual(
            self.marks("visit")[:2], [("V1", "planned"), ("V2", "planned")]
        )

        self.set_status(first, "cancelled")

        self.assertEqual(
            self.marks("visit"),
            [("V1", "planned"), ("V2", "open"), ("V3", "open"), ("V4", "open")],
        )
        self.assertEqual(self.held_by("visit"), [second.id, None, None, None])
        self.assertEqual(self._visits(), 1)
        self.assertFalse(CoreActivitySlot.objects.filter(activity_id=first.id).exists())

    def test_cancelling_the_last_visit_leaves_the_others_where_they_are(self):
        first = self._activity(on=_in(2))
        second = self._activity(on=_in(5))
        third = self._activity(on=_in(8))

        self.set_status(third, "cancelled")

        self.assertEqual(self.held_by("visit"), [first.id, second.id, None, None])
        self.assertEqual(self._visits(), 2)

    def test_the_visits_left_keep_their_order(self):
        first = self._activity(on=_in(2))
        second = self._activity(on=_in(5))
        third = self._activity(on=_in(8))
        fourth = self._activity(on=_in(11))

        self.set_status(second, "cancelled")

        self.assertEqual(self.held_by("visit"), [first.id, third.id, fourth.id, None])
        self.assertEqual(
            self.marks("visit"),
            [("V1", "planned"), ("V2", "planned"), ("V3", "planned"), ("V4", "open")],
        )

    def test_the_next_visit_booked_takes_the_next_number(self):
        first = self._activity(on=_in(2))
        second = self._activity(on=_in(5))
        self.set_status(first, "cancelled")

        third = self._activity(on=_in(9))

        self.assertEqual(self.held_by("visit"), [second.id, third.id, None, None])
        self.assertEqual(self._visits(), 2)

    def test_every_visit_cancelled_leaves_an_empty_package(self):
        visits = [self._activity(on=_in(2 + index)) for index in range(3)]

        for visit in visits:
            self.set_status(visit, "cancelled")

        self.assertEqual({state for _label, state in self.marks("visit")}, {"open"})
        self.assertEqual(self._visits(), 0)

    def test_finished_work_keeps_what_it_recorded_when_it_moves(self):
        first = self._activity(on=_in(2))
        done = self._activity(on=_in(5), status="ia_verified")
        Activity.objects.filter(id=done.id).update(salesforce_activity_id="SVE-0042")
        done.refresh_from_db()
        self.set_status(done, "ia_verified")  # the mirror copies the SF id across
        self.assertEqual(self._slot("v", 2).salesforce_id, "SVE-0042")

        self.set_status(first, "cancelled")

        moved = self._slot("v", 1)
        self.assertEqual(
            (moved.activity_id, moved.salesforce_id, moved.status),
            (done.id, "SVE-0042", "ia_verified"),
        )
        self.assertEqual(self.marks("visit")[0], ("V1", "done"))


class OtherWaysWorkStopsTest(_Marks, _PackageFixture):
    def test_a_deferred_or_rejected_visit_gives_its_slot_back_too(self):
        deferred = self._activity(on=_in(2))
        rejected = self._activity(on=_in(5))
        kept = self._activity(on=_in(8))

        self.set_status(deferred, "deferred")
        self.set_status(rejected, "rejected")

        self.assertEqual(self.held_by("visit"), [kept.id, None, None, None])
        self.assertEqual(self._visits(), 1)

    def test_a_deferred_visit_put_back_on_a_day_takes_the_next_open_slot(self):
        deferred = self._activity(on=_in(2))
        kept = self._activity(on=_in(5))
        self.set_status(deferred, "deferred")
        self.assertEqual(self.held_by("visit"), [kept.id, None, None, None])

        self.set_status(deferred, "rescheduled")

        self.assertEqual(self.held_by("visit"), [kept.id, deferred.id, None, None])


class CancelledTrainingsLeaveThePackageTest(_Marks, _PackageFixture):
    def test_cancelling_the_first_training_makes_the_second_t1(self):
        first = self._activity("in_school_training", on=_in(2))
        second = self._activity("in_school_training", on=_in(6))

        self.set_status(first, "cancelled")

        self.assertEqual(
            self.marks("training"),
            [("T1", "planned"), ("T2", "open"), ("T3", "open"), ("T4", "open")],
        )
        self.assertEqual(self.held_by("training"), [second.id, None, None, None])
        self.assertEqual(self._trainings(), 1)

    def test_an_in_school_training_cancelled_with_its_visit_frees_both(self):
        from apps.accounts.models import StaffProfile, User
        from apps.activities import pairs

        officer = User.objects.create_user(
            email="cancel-pair-admin@edify.org",
            name="Pair Canceller",
            roles=["Admin"],
            active_role="Admin",
            password="x",
            is_active=True,
        )
        StaffProfile.objects.create(user=officer, title="Admin")
        other_visit = self._activity("follow_up_visit", on=_in(1))
        visit = self._activity(
            "school_visit",
            on=_in(4),
            purpose_type="in_school_training_delivery_visit",
        )
        training = self._activity(
            "in_school_training", on=_in(4), paired_school_visit=visit
        )
        later = self._activity("in_school_training", on=_in(9))
        self.assertEqual(self.held_by("visit"), [other_visit.id, visit.id, None, None])
        self.assertEqual(self.held_by("training"), [training.id, later.id, None, None])

        with self.captureOnCommitCallbacks(execute=True):
            pairs.cancel(
                training.id, {"reason": "The school asked to move it."}, officer
            )

        self.assertEqual(self.held_by("visit"), [other_visit.id, None, None, None])
        self.assertEqual(self.held_by("training"), [later.id, None, None, None])
        self.assertEqual((self._visits(), self._trainings()), (1, 1))

    def test_a_cancelled_group_training_gives_its_slot_back(self):
        cluster = Cluster.objects.create(
            name="Cancelled Session Cluster",
            region=self.region,
            district=self.district,
            status="active",
        )
        with self.captureOnCommitCallbacks(execute=True):
            session = Activity.objects.create(
                activity_type="cluster_training",
                cluster=cluster,
                fy=self.fy,
                quarter="Q1",
                planned_date=_in(3),
                status="scheduled",
            )
            ClusterActivityAttendance.objects.create(
                activity=session, school=self.school, invited=True
            )
            session.save()
        own = self._activity("in_school_training", on=_in(8))
        self.assertEqual(self.held_by("training"), [session.id, own.id, None, None])

        self.set_status(session, "cancelled")

        self.assertEqual(self.held_by("training"), [own.id, None, None, None])
        self.assertEqual(
            self.marks("training")[:2], [("T1", "planned"), ("T2", "open")]
        )
        self.assertEqual(self._trainings(), 1)


class APartnersWaitingHandoverMovesWithItsSlotTest(_Marks, _PackageFixture):
    def _handover(self, **fields):
        from apps.partners.services import create_assignment

        return create_assignment(
            school=self.school,
            partner=self.partner,
            assigning_staff_id="cred-staff",
            expected_activity_type=fields.pop("expected_activity_type", "school_visit"),
            **fields,
        )

    def test_a_slot_held_for_a_partner_moves_down_and_stays_held(self):
        first = self._activity(on=_in(2))  # V1
        self._handover()  # holds V2 for the Partner
        self.assertEqual(self._slot("v", 2).status, "Assigned")

        self.set_status(first, "cancelled")

        held = self._slot("v", 1)
        self.assertEqual(
            (held.status, held.assigned_partner_id, held.owner),
            ("Assigned", self.partner.id, "partner"),
        )
        self.assertEqual(self._slot("v", 2).status, "Planned")
        self.assertEqual(self._visits(), 1)

    def test_a_handover_that_names_its_slot_is_renumbered_with_it(self):
        first = self._activity(on=_in(2))  # V1
        second = self._activity(on=_in(4))  # V2
        handover = self._handover(support_type="Visit", visit_number="3")
        CorePackageSchedulingService.commit_assign(
            self._slot("v", 3),
            partner_id=self.partner.id,
            partner_name=self.partner.name,
        )

        self.set_status(first, "cancelled")

        handover.refresh_from_db()
        self.assertEqual(handover.visit_number, "2")
        self.assertEqual(self._slot("v", 1).activity_id, second.id)
        self.assertEqual(
            (self._slot("v", 2).status, self._slot("v", 2).assigned_partner_id),
            ("Assigned", self.partner.id),
        )
        self.assertEqual(self._slot("v", 3).status, "Planned")


class AReopenedHandoverHoldsASlotAgainTest(_Marks, _PackageFixture):
    """A Partner's dated visit is cancelled: the date is undone, the school
    is still the Partner's, and the package still holds a visit for it."""

    def _dated_by_the_partner(self, **handover_fields):
        from apps.partners.models import PartnerAssignment
        from apps.partners.services import create_assignment

        handover = create_assignment(
            school=self.school,
            partner=self.partner,
            assigning_staff_id="cred-staff",
            expected_activity_type="school_visit",
            **handover_fields,
        )
        visit = self._activity(
            delivery_type="partner",
            assigned_partner_id=self.partner.id,
            partner_date_set_by="partner",
            status="partner_scheduled",
        )
        handover.status = PartnerAssignment.STATUS_PARTNER_SCHEDULED
        handover.scheduled_activity = visit
        handover.save(update_fields=["status", "scheduled_activity", "updated_at"])
        return handover, visit

    def _cancel(self, visit):
        from apps.partners.services import undo_assignment_scheduling

        self.set_status(visit, "cancelled")
        return undo_assignment_scheduling(visit, partner_dated=True)

    def test_the_package_holds_the_visit_for_the_partner_again(self):
        handover, visit = self._dated_by_the_partner()
        self.assertEqual(self._slot("v", 1).activity_id, visit.id)

        outcome = self._cancel(visit)

        handover.refresh_from_db()
        slot = self._slot("v", 1)
        self.assertEqual(outcome, "reopened")
        self.assertEqual(handover.status, "pending_scheduling")
        self.assertEqual(
            (slot.status, slot.activity_id, slot.assigned_partner_id),
            ("Assigned", None, self.partner.id),
        )
        self.assertEqual(self.marks("visit")[0], ("V1", "planned"))
        self.assertEqual(self._visits(), 1)

    def test_one_that_names_its_slot_takes_the_next_open_one_and_its_number(self):
        staff_visit = self._activity(on=_in(1))  # V1
        handover, visit = self._dated_by_the_partner(
            support_type="Visit", visit_number="2"
        )
        self.assertEqual(self.held_by("visit")[:2], [staff_visit.id, visit.id])

        self._cancel(visit)

        handover.refresh_from_db()
        self.assertEqual(handover.visit_number, "2")
        self.assertEqual(
            (self._slot("v", 2).status, self._slot("v", 2).assigned_partner_id),
            ("Assigned", self.partner.id),
        )
        self.assertEqual(self._visits(), 2)


class ClosingGapsTest(_Marks, _PackageFixture):
    def test_a_package_with_no_gap_is_left_alone(self):
        self._activity(on=_in(2))
        self._activity(on=_in(5))

        self.assertEqual(close_gaps(self.plan, "visit"), {})

    def test_a_slot_left_pointing_at_cancelled_work_is_cleared(self):
        """What a database written before this rule holds: the visit is
        cancelled and its slot still names it."""
        first = self._activity(on=_in(2))
        second = self._activity(on=_in(5))
        Activity.objects.filter(id=first.id).update(status="cancelled")
        CoreActivitySlot.objects.filter(activity_id=first.id).update(status="cancelled")

        moves = close_gaps(self.plan, "visit")

        self.assertEqual(moves, {2: 1})
        self.assertEqual(self.held_by("visit"), [second.id, None, None, None])
