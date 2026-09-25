"""A school is assigned to the same partner once at a time.

Owner, 2026-09-24: "make sure schools can only be assigned to the partner once
... on the live server a user assigned the same school to the partner many
times ... remove the duplicate assignments."

While a partner still has a school waiting to be scheduled, the school is not
handed to that partner again — whichever page, project or activity it comes
from. PartnerAssignment.save refuses it in words; the
uniq_open_partner_school_assignment index refuses what gets past that.
Migration 0027 removed the duplicates already in the data.
"""

from __future__ import annotations

import importlib

from django.apps import apps as app_registry
from django.db import IntegrityError, connection, transaction
from django.test import TestCase

from apps.core.exceptions import ConflictError
from apps.geography.models import District, Region
from apps.notifications.models import Notification
from apps.partners.models import (
    Partner,
    PartnerAssignment,
    PartnerAssignmentWithdrawal,
)
from apps.partners.services import create_assignment
from apps.projects.models import Project
from apps.schools.models import School


class OpenAssignmentFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="Once Region")
        district = District.objects.create(name="Once District", region=region)
        cls.school = School.objects.create(
            school_id="ONCE-1",
            name="Once Primary",
            region=region,
            district=district,
            school_type="client",
        )
        cls.other_school = School.objects.create(
            school_id="ONCE-2",
            name="Twice Primary",
            region=region,
            district=district,
            school_type="client",
        )
        cls.partner = Partner.objects.create(name="Once Partner")
        cls.other_partner = Partner.objects.create(name="Other Partner")

    def handover(self, **over):
        fields = {
            "school": self.school,
            "partner": self.partner,
            "assigning_staff_id": "cceo-1",
            "monitoring_staff_id": "cceo-1",
            "expected_activity_type": "school_visit",
        }
        fields.update(over)
        return create_assignment(**fields)

    def open_rows(self, **filters):
        return PartnerAssignment.objects.filter(
            status__in=PartnerAssignment.UNSCHEDULED_STATUSES, **filters
        )


class OpenAssignmentOnceTest(OpenAssignmentFixture):
    def test_the_same_school_is_not_handed_to_the_same_partner_twice(self):
        self.handover()
        with self.assertRaises(ConflictError) as caught:
            self.handover(expected_activity_type="school_training")
        self.assertIn(
            "Once Primary is already assigned to Once Partner", str(caught.exception)
        )
        self.assertEqual(self.open_rows(school=self.school).count(), 1)

    def test_nor_again_from_a_project(self):
        project = Project.objects.create(name="Once Project", status="active")
        self.handover()
        with self.assertRaises(ConflictError):
            self.handover(project=project)

    def test_another_school_or_another_partner_is_fine(self):
        self.handover()
        self.handover(school=self.other_school)
        self.handover(partner=self.other_partner)
        self.assertEqual(self.open_rows().count(), 3)

    def test_once_scheduled_the_next_piece_of_work_may_follow(self):
        first = self.handover()
        first.status = PartnerAssignment.STATUS_SCHEDULED
        first.save(update_fields=["status"])
        self.handover()
        self.assertEqual(self.open_rows(school=self.school).count(), 1)

    def test_a_returned_handover_does_not_block_the_next(self):
        first = self.handover()
        first.status = PartnerAssignment.STATUS_RETURNED_TO_STAFF
        first.save(update_fields=["status"])
        self.handover()

    def test_core_slots_wait_side_by_side(self):
        """Visit 1 and Visit 2 of a Core package are two slots, not a
        repeat."""
        self.handover(support_type="Visit", visit_number="1", training_number="")
        self.handover(support_type="Visit", visit_number="2", training_number="")
        with self.assertRaises(ConflictError):
            self.handover(support_type="Visit", visit_number="2", training_number=None)

    def test_the_database_refuses_what_gets_past_the_check(self):
        """bulk_create skips save(), as a concurrent second submission
        effectively does."""
        self.handover()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PartnerAssignment.objects.bulk_create(
                    [
                        PartnerAssignment(
                            school=self.school,
                            partner=self.partner,
                            status=PartnerAssignment.STATUS_ASSIGNED,
                        )
                    ]
                )

    def test_has_open_assignment(self):
        self.assertFalse(
            PartnerAssignment.has_open_assignment(self.school, self.partner)
        )
        self.handover()
        self.assertTrue(
            PartnerAssignment.has_open_assignment(self.school, self.partner)
        )
        self.assertFalse(
            PartnerAssignment.has_open_assignment(self.school, self.other_partner)
        )


class RemoveDuplicatesMigrationTest(OpenAssignmentFixture):
    """Migration 0027 against the shape production is in.

    Each test drops the index, writes the duplicates it forbids (bulk_create,
    past save()'s check), and runs the migration's function. The TestCase
    transaction rolls the DDL back.
    """

    def setUp(self):
        self.migration = importlib.import_module(
            "apps.partners.migrations.0027_remove_duplicate_open_partner_assignments"
        )
        with connection.cursor() as cursor:
            cursor.execute("DROP INDEX uniq_open_partner_school_assignment")

    def raw(self, **over):
        fields = {
            "school": self.school,
            "partner": self.partner,
            "assigning_staff_id": "cceo-1",
            "expected_activity_type": "school_visit",
            "status": PartnerAssignment.STATUS_PENDING_SCHEDULING,
        }
        fields.update(over)
        return PartnerAssignment.objects.bulk_create([PartnerAssignment(**fields)])[0]

    def run_migration(self):
        self.migration.remove_duplicate_open_assignments(app_registry, None)

    def test_repeats_are_removed_and_one_handover_stays(self):
        first = self.raw()
        repeats = [self.raw(status=PartnerAssignment.STATUS_ASSIGNED) for _ in range(4)]
        for row in [first, *repeats]:
            Notification.objects.create(
                recipient_id="partner-user",
                title="New assignment",
                context_type="partner_assignment",
                context_id=row.id,
                source_event_type="partner_scheduled_activity",
                action_required=True,
            )

        self.run_migration()

        self.assertEqual(
            list(self.open_rows(school=self.school).values_list("id", flat=True)),
            [first.id],
            "the earliest handover is the one kept",
        )
        live = Notification.objects.filter(resolved_at__isnull=True)
        self.assertEqual(list(live.values_list("context_id", flat=True)), [first.id])

    def test_the_project_handover_is_preferred(self):
        project = Project.objects.create(name="Keep Project", status="active")
        self.raw()
        in_project = self.raw(project=project)
        self.raw()
        self.run_migration()
        self.assertEqual(
            list(self.open_rows(school=self.school).values_list("id", flat=True)),
            [in_project.id],
        )

    def test_a_handover_with_history_is_never_deleted(self):
        self.raw()
        withdrawn = self.raw()
        PartnerAssignmentWithdrawal.objects.create(
            assignment=withdrawn,
            partner=self.partner,
            school=self.school,
            requested_by="pl-1",
            kind="hold",
            reason_category="other",
            partner_facing_reason="On hold",
            attribution="neutral",
            disposition="return_to_planning",
        )
        self.run_migration()
        self.assertEqual(
            list(self.open_rows(school=self.school).values_list("id", flat=True)),
            [withdrawn.id],
        )
        self.assertTrue(
            PartnerAssignmentWithdrawal.objects.filter(assignment=withdrawn).exists()
        )

    def test_everything_that_is_not_a_repeat_is_left_alone(self):
        keep = {
            self.raw().id,
            self.raw(partner=self.other_partner).id,
            self.raw(school=self.other_school).id,
            self.raw(support_type="Visit", visit_number="1").id,
            self.raw(support_type="Visit", visit_number="2").id,
            self.raw(status=PartnerAssignment.STATUS_SCHEDULED).id,
            self.raw(status=PartnerAssignment.STATUS_SCHEDULED).id,
            self.raw(status=PartnerAssignment.STATUS_RETURNED_TO_STAFF).id,
            self.raw(school=None).id,
            self.raw(school=None).id,
        }
        self.run_migration()
        self.assertEqual(
            set(PartnerAssignment.objects.values_list("id", flat=True)), keep
        )

    def test_the_index_builds_over_the_cleaned_data(self):
        for _ in range(3):
            self.raw()
        self.run_migration()
        # 0027 and 0028 commit separately in a deploy; inside this test's one
        # transaction the deletes' deferred FK checks must be flushed first,
        # or Postgres refuses the CREATE INDEX (the reason for the split).
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        with connection.schema_editor() as editor:
            editor.add_constraint(
                PartnerAssignment,
                next(
                    c
                    for c in PartnerAssignment._meta.constraints
                    if c.name == "uniq_open_partner_school_assignment"
                ),
            )
