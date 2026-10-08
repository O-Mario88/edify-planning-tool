"""Hand-over governance from the core-school partner audit (owner, 2026-10-01:
"fix all the remaining open").

* A hand-over's status is one of a fixed vocabulary, held by the database
  for every row written from now on (legacy spellings stay valid).
* A partner is handed only the trainings it is recorded as delivering — when
  it records any.
* A project's work goes to the project's own partners, or carries a reason.
"""

from __future__ import annotations

from unittest import mock

from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.core.exceptions import BadRequest
from apps.geography.models import District, Region
from apps.partners import services as partner_services
from apps.partners.capabilities import delivers
from apps.partners.models import Partner, PartnerAssignment, PartnerAssignmentStatus
from apps.schools.models import School


class _Fixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.activity_catalogue.models import ActivityCatalogueItem
        from apps.activity_catalogue.seeding import seed_activity_catalogue

        seed_activity_catalogue(actor_id="test")
        region = Region.objects.create(name="Gov Region")
        district = District.objects.create(name="Gov District", region=region)
        cls.school = School.objects.create(
            school_id="GOV-1",
            name="Governance Primary",
            region=region,
            district=district,
            school_type="client",
        )
        courses = list(
            ActivityCatalogueItem.objects.filter(is_training_course=True).order_by(
                "stable_code"
            )[:2]
        )
        cls.course, cls.other_course = courses
        cls.visit_item = ActivityCatalogueItem.objects.filter(
            is_training_course=False, partner_delivery_allowed=True
        ).first()
        cls.partner = Partner.objects.create(name="Gov Partner", active_status=True)

    def _hand_over(self, partner, **fields):
        return partner_services.create_assignment(
            school=self.school,
            partner=partner,
            assigning_staff_id="gov-staff",
            expected_activity_type="in_school_training",
            purpose_of_visit="in_school_training",
            **fields,
        )


class StatusVocabularyTest(_Fixture):
    def test_the_database_refuses_an_unknown_status(self):
        handover = self._hand_over(self.partner, training_course=self.course)
        self.assertEqual(handover.status, PartnerAssignmentStatus.PENDING_SCHEDULING)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PartnerAssignment.objects.filter(id=handover.id).update(status="bogus")

    def test_the_legacy_spellings_stay_valid(self):
        handover = self._hand_over(self.partner, training_course=self.course)
        for status in (
            "assigned",
            "partner_pending_schedule",
            "scheduled",
            "completed",
            "returned",
            "cancelled",
        ):
            PartnerAssignment.objects.filter(id=handover.id).update(status=status)
        self.assertIn(
            PartnerAssignment.STATUS_COMPLETED, PartnerAssignment.SCHEDULED_STATUSES
        )


class PartnerSkillsTest(_Fixture):
    def test_a_partner_recording_nothing_is_offered_every_course(self):
        self.assertTrue(delivers(self.partner, self.course))
        self._hand_over(self.partner, training_course=self.course)

    def test_a_partner_is_handed_only_the_courses_it_records(self):
        self.partner.activity_codes = [self.course.stable_code]
        self.partner.save(update_fields=["activity_codes"])

        self.assertTrue(delivers(self.partner, self.course))
        self.assertFalse(delivers(self.partner, self.other_course))
        with self.assertRaisesMessage(BadRequest, "is not recorded as delivering"):
            self._hand_over(self.partner, training_course=self.other_course)
        self._hand_over(self.partner, training_course=self.course)

    def test_visits_are_not_narrowed_by_recorded_courses(self):
        self.partner.activity_codes = [self.course.stable_code]
        self.partner.save(update_fields=["activity_codes"])
        self.assertTrue(delivers(self.partner, self.visit_item))


class ProjectPartnerListTest(_Fixture):
    def setUp(self):
        from apps.projects.models import Project

        self.project = Project.objects.create(
            name="Gov Project", category="pilot", status="active"
        )
        self.outsider = Partner.objects.create(name="Gov Outsider", active_status=True)

    def test_set_partners_keeps_exactly_the_ticked_list(self):
        from apps.projects.models import ProjectPartnerAssignment
        from apps.projects.services import set_partners

        set_partners(self.project, [self.partner.id, self.outsider.id])
        set_partners(self.project, [self.partner.id])
        self.assertEqual(
            list(
                ProjectPartnerAssignment.objects.filter(
                    project=self.project
                ).values_list("partner_id", flat=True)
            ),
            [self.partner.id],
        )
        with self.assertRaises(BadRequest):
            set_partners(self.project, ["no-such-partner"])

    @mock.patch(
        "apps.partners.handover_policy.PROJECT_HANDOVERS_KEEP_SCHOOL_RULES", True
    )
    def test_a_partner_outside_the_list_needs_a_reason(self):
        """The rule, held with its switch on: project hand-overs go past it
        for now (owner, 2026-10-05; apps.partners.handover_policy)."""
        from apps.projects.services import set_partners

        set_partners(self.project, [self.partner.id])
        with self.assertRaisesMessage(BadRequest, "is not one of Gov Project"):
            self._hand_over(
                self.outsider, training_course=self.course, project=self.project
            )
        handover = self._hand_over(
            self.outsider,
            training_course=self.course,
            project=self.project,
            override_reason="Covers the district",
        )
        self.assertEqual(handover.override_reason, "Covers the district")
        # With the school rules on, a school one partner holds is not handed
        # to another (owner, 2026-10-08): the outsider lets it go first.
        handover.status = PartnerAssignment.STATUS_RETURNED_TO_STAFF
        handover.save(update_fields=["status"])
        self._hand_over(
            self.partner, training_course=self.other_course, project=self.project
        )

    def test_a_project_with_no_list_takes_any_partner(self):
        self._hand_over(
            self.outsider, training_course=self.course, project=self.project
        )
