"""One live assignment per partner per support slot (INT-02).

PartnerAssignment declared no constraints at all. The rule was written twice
in code — withdrawal_service._assert_replacement_eligible checks it on the
replacement path, planning_oversight_health reports the rows that got in
anyway — and enforced by neither the database nor the other creation paths.

The refusal half alone would not be worth much here: the constraint is
partial on two axes and normalises NULL against "", so most of these tests
exist to prove it does NOT fire on the many shapes that are legitimate —
an ordinary handover with no slot, a second partner on a contested slot, and
a replacement following a withdrawal.
"""

from __future__ import annotations

from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.geography.models import District, Region
from apps.partners.models import Partner, PartnerAssignment
from apps.schools.models import School


class PartnerSlotFixture(TestCase):
    """Fixture + helpers shared by the constraint tests and the guard
    tests below."""

    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="Slot Region")
        district = District.objects.create(name="Slot District", region=region)
        cls.school = School.objects.create(
            school_id="SLOT-SCH", name="Slot School", region=region, district=district
        )
        cls.other_school = School.objects.create(
            school_id="SLOT-SCH-2",
            name="Other Slot School",
            region=region,
            district=district,
        )
        cls.partner = Partner.objects.create(name="Partner Alpha")
        cls.other_partner = Partner.objects.create(name="Partner Beta")

    def assert_refused(self, make, *, why):
        with self.assertRaises(IntegrityError, msg=why):
            with transaction.atomic():
                make()

    def assign(self, **over):
        fields = {
            "school": self.school,
            "partner": self.partner,
            "assigning_staff_id": "cceo-1",
            "monitoring_staff_id": "cceo-1",
            "expected_activity_type": "school_visit",
            "status": PartnerAssignment.STATUS_ASSIGNED,
        }
        fields.update(over)
        return PartnerAssignment.objects.create(**fields)


class PartnerSlotConstraintTest(PartnerSlotFixture):
    # ── what it refuses ──────────────────────────────────────────────────
    def test_one_partner_cannot_hold_a_school_slot_twice(self):
        self.assign(support_type="core_visit", visit_number="3")
        self.assert_refused(
            lambda: self.assign(support_type="core_visit", visit_number="3"),
            why="the same organisation entered twice against one entitlement "
            "makes every downstream pairing ambiguous",
        )

    def test_null_and_blank_slot_parts_are_the_same_slot(self):
        """Proves the COALESCE is doing work.

        The Core Schools view writes "" into whichever of visit_number /
        training_number does not apply, while every other creation path
        leaves them NULL. Postgres treats NULLs in a unique index as
        distinct, so without normalising, these two rows would read as
        different slots and the constraint would miss the collision it
        exists to catch.
        """
        self.assign(support_type="core_visit", visit_number=None, training_number=None)
        self.assert_refused(
            lambda: self.assign(
                support_type="core_visit", visit_number="", training_number=""
            ),
            why="NULL and empty string both mean 'this part of the slot is "
            "not used'",
        )

    def test_a_training_slot_collides_on_its_own_number(self):
        self.assign(support_type="Training", training_number="2")
        self.assert_refused(
            lambda: self.assign(support_type="Training", training_number="2"),
            why="training slots are slots too",
        )

    # ── what it must NOT refuse ──────────────────────────────────────────
    def test_two_unslotted_handovers_at_one_school_are_fine(self):
        """A clash needs a slot. Support slots are a Core-package concept;
        ordinary handovers name none, and two of those at one school are two
        different pieces of work — the same carve-out the health check makes.
        """
        first = self.assign()
        second = self.assign()
        self.assertNotEqual(first.id, second.id)

    def test_a_second_partner_on_the_same_slot_is_allowed(self):
        """Deliberately outside the constraint, and the reason is in the
        model comment: two DIFFERENT partners on one slot is a real
        transitional state a human resolves from the Partner Oversight
        board, where planning_oversight_health reports it as
        'duplicate_support_slot_holders'. Constraining it at the database
        would make that finding unreachable and its test unwritable.
        """
        self.assign(support_type="core_visit", visit_number="3")
        contested = self.assign(
            partner=self.other_partner, support_type="core_visit", visit_number="3"
        )
        self.assertEqual(contested.partner_id, self.other_partner.id)

    def test_a_returned_assignment_stops_holding_the_slot(self):
        """Otherwise every reassignment would be blocked by the assignment it
        replaces. withdrawal_service sets exactly this status when a
        withdrawal takes effect.
        """
        released = self.assign(support_type="core_visit", visit_number="3")
        released.status = PartnerAssignment.STATUS_RETURNED_TO_STAFF
        released.save(update_fields=["status"])

        replacement = self.assign(support_type="core_visit", visit_number="3")
        self.assertEqual(replacement.support_type, "core_visit")

    def test_the_same_slot_number_at_a_different_school_is_a_different_slot(self):
        self.assign(support_type="core_visit", visit_number="3")
        elsewhere = self.assign(
            school=self.other_school, support_type="core_visit", visit_number="3"
        )
        self.assertEqual(elsewhere.school_id, self.other_school.id)

    def test_different_visit_numbers_at_one_school_are_different_slots(self):
        """The nine-slot core package is the normal case: one partner holds
        Visit 1 through Visit 4 at the same school."""
        for number in ("1", "2", "3", "4"):
            self.assign(support_type="Visit", visit_number=number)
        self.assertEqual(
            PartnerAssignment.objects.filter(
                school=self.school, partner=self.partner, support_type="Visit"
            ).count(),
            4,
        )

    def test_cluster_assignments_carry_no_school_and_are_unaffected(self):
        """The index requires a school: a cluster-scoped handover has none,
        and the health check skips those rows for the same reason."""
        first = self.assign(school=None, support_type="core_visit", visit_number="3")
        second = self.assign(school=None, support_type="core_visit", visit_number="3")
        self.assertIsNone(first.school_id)
        self.assertIsNone(second.school_id)


class SlotMigrationPreCheckTest(PartnerSlotFixture):
    """The guard that runs BEFORE the DDL in migration 0018.

    This is the guard most likely to matter on the real deploy: the health
    check exists because rows like these were already found in the data, so
    the migration has a genuine chance of aborting. When it does, the
    operator must get the school, the partner, the slot, the count and an
    example id — not a bare "could not create unique index".

    Each test drops the index, writes the rows it forbids, and calls the
    guard. The surrounding TestCase transaction rolls the DDL back.
    """

    def setUp(self):
        import importlib

        from django.apps import apps as app_registry

        self.registry = app_registry
        self.migration = importlib.import_module(
            "apps.partners.migrations."
            "0018_partnerassignment_uniq_live_partner_support_slot"
        )

    @staticmethod
    def _drop_index():
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("DROP INDEX uniq_live_partner_support_slot")

    def test_a_doubled_slot_names_the_school_partner_slot_and_a_row(self):
        self._drop_index()
        first = self.assign(support_type="core_visit", visit_number="3")
        self.assign(support_type="core_visit", visit_number="3")

        with self.assertRaises(RuntimeError) as caught:
            self.migration.check_one_live_assignment_per_slot(self.registry, None)

        message = str(caught.exception)
        self.assertIn("uniq_live_partner_support_slot", message)
        self.assertIn("partner_assignment", message)
        self.assertIn(self.school.id, message)
        self.assertIn(self.partner.id, message)
        self.assertIn("core_visit", message)
        self.assertIn("is held 2 times", message)
        self.assertIn(first.id, message)
        self.assertIn("duplicate_support_slot_holders", message)

    def test_the_guard_matches_the_index_predicate_exactly(self):
        """A guard stricter than the index would abort a deploy over rows the
        index accepts. Every shape the index deliberately skips must pass:
        unslotted handovers, a second partner, a released assignment and
        cluster rows with no school.
        """
        self._drop_index()
        self.assign()
        self.assign()
        self.assign(
            partner=self.other_partner, support_type="core_visit", visit_number="3"
        )
        self.assign(support_type="core_visit", visit_number="3")
        released = self.assign(support_type="Training", training_number="1")
        released.status = PartnerAssignment.STATUS_RETURNED_TO_STAFF
        released.save(update_fields=["status"])
        self.assign(support_type="Training", training_number="1")
        self.assign(school=None, support_type="core_visit", visit_number="9")
        self.assign(school=None, support_type="core_visit", visit_number="9")

        self.migration.check_one_live_assignment_per_slot(self.registry, None)
