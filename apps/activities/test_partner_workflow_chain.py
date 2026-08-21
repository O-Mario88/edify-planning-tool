"""The §8–§16 partner delivery chain, pinned end to end.

Partner submits actuals + evidence with NO Salesforce ID (that entry is IA's,
made in the Confirm Salesforce Entry step); IA returns land on
``returned_by_ia`` with the structured correction note; the per-school partner
allowance never counts an assignment's own linked activity against it; and
the extra-allowance grant is an auditable CD/PL/Admin decision.
"""

from datetime import date

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from apps.activities.models import Activity
from apps.activities.services import complete, ia_confirm, ia_return
from apps.core.exceptions import BadRequest, Forbidden
from apps.geography.models import District, Region
from apps.partners.models import Partner, PartnerAssignment
from apps.partners.services import (
    assert_partner_activity_allowance,
    grant_partner_activity_allowance,
)
from apps.schools.models import School


class _P:
    def __init__(self, user, role=None):
        self.user_id = user.id
        self.id = user.id
        self.active_role = role or user.active_role
        self.staff_profile_id = None
        self.country_scope = False


class PartnerWorkflowChainTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.region = Region.objects.create(name="PW Region")
        self.district = District.objects.create(
            name="PW District", region=self.region, district_type="primary"
        )
        self.school = School.objects.create(
            school_id="PW-SCH",
            name="PW School",
            region=self.region,
            district=self.district,
        )
        self.partner_user = User.objects.create(
            id="pw-partner-user",
            email="pw-partner@test.org",
            name="PW Partner Officer",
            roles=["PartnerFieldOfficer"],
            active_role="PartnerFieldOfficer",
            is_active=True,
        )
        self.partner = Partner.objects.create(
            id="pw-partner",
            name="PW Literacy Partner",
            active_status=True,
            user=self.partner_user,
        )
        self.ia_user = User.objects.create(
            id="pw-ia",
            email="pw-ia@test.org",
            name="PW IA",
            roles=["ImpactAssessment"],
            active_role="ImpactAssessment",
            is_active=True,
        )
        self.cd_user = User.objects.create(
            id="pw-cd",
            email="pw-cd@test.org",
            name="PW CD",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            is_active=True,
        )

    def _partner_activity(self, **overrides):
        defaults = dict(
            school=self.school,
            activity_type="in_school_training",
            delivery_type="partner",
            assigned_partner_id=self.partner.id,
            status="completion_started",
            fy="2026",
            quarter="Q4",
            planned_date=date.today(),
            scheduled_date=timezone.now(),
        )
        defaults.update(overrides)
        return Activity.objects.create(**defaults)

    def _evidence(self, activity):
        from apps.evidence.services import record_upload

        # Governed forms are PDF-only by rule.
        record_upload(
            principal=self.partner_user,
            activity_id=activity.id,
            kind="attendance_form",
            file_obj=SimpleUploadedFile(
                "attendance.pdf",
                b"%PDF-1.4 attendance body " + b"x" * 200,
                "application/pdf",
            ),
        )

    # ── §9/§12: the Salesforce ID belongs to IA, not the partner ────────────

    def test_partner_submission_defers_salesforce_to_ia(self):
        a = self._partner_activity()
        self._evidence(a)
        complete(
            a.id,
            {
                "teachersAttended": 10,
                "leadersAttended": 1,
                "actualDeliveryDate": str(date.today()),
                "actualOutcome": "Delivered.",
            },
            _P(self.partner_user),
        )
        a.refresh_from_db()
        self.assertEqual(a.status, "awaiting_ia_verification")
        self.assertFalse(a.salesforce_activity_id)
        self.assertEqual(a.actual_outcome, "Delivered.")

    def test_ia_confirm_requires_and_records_the_salesforce_id(self):
        a = self._partner_activity(status="awaiting_ia_verification")
        self._evidence(a)
        with self.assertRaises(BadRequest):
            ia_confirm(a.id, {}, _P(self.ia_user))
        ia_confirm(a.id, {"salesforceId": "TS-77001122"}, _P(self.ia_user))
        a.refresh_from_db()
        self.assertEqual(a.status, "ia_verified")
        self.assertEqual(a.salesforce_activity_id, "TS-77001122")

    def test_ia_return_uses_the_partner_status_and_structured_note(self):
        a = self._partner_activity(status="awaiting_ia_verification")
        self._evidence(a)
        ia_return(
            a.id,
            {
                "reason": "Photo unclear",
                "correctionFields": "attendance evidence",
                "instruction": "Re-photograph the sheet.",
                "deadline": "2026-08-30",
            },
            _P(self.ia_user),
        )
        a.refresh_from_db()
        self.assertEqual(a.status, "returned_by_ia")
        for fragment in (
            "Photo unclear",
            "attendance evidence",
            "Re-photograph",
            "2026-08-30",
        ):
            self.assertIn(fragment, a.pl_review_note)

    # ── §F: the allowance never counts an assignment's own activity ─────────

    def test_allowance_excludes_the_assignments_own_linked_activity(self):
        a = self._partner_activity(status="completed")
        with self.assertRaises(BadRequest):
            assert_partner_activity_allowance(
                self.partner.id, self.school.id, "in_school_training", "2026"
            )
        # The same count, excluding the assignment's own activity — passes.
        assert_partner_activity_allowance(
            self.partner.id,
            self.school.id,
            "in_school_training",
            "2026",
            exclude_activity_id=a.id,
        )

    def test_allowance_grant_is_auditable_and_role_gated(self):
        self._partner_activity(status="completed")
        with self.assertRaises(Forbidden):
            grant_partner_activity_allowance(
                _P(self.partner_user),
                {
                    "partner_id": self.partner.id,
                    "school_id": self.school.id,
                    "reason": "nope",
                },
            )
        with self.assertRaises(BadRequest):
            grant_partner_activity_allowance(
                _P(self.cd_user),
                {
                    "partner_id": self.partner.id,
                    "school_id": self.school.id,
                    "reason": "",
                },
            )
        grant = grant_partner_activity_allowance(
            _P(self.cd_user),
            {
                "partner_id": self.partner.id,
                "school_id": self.school.id,
                "fy": "2026",
                "reason": "Second SSA support round approved by CD.",
            },
        )
        self.assertEqual(grant.granted_by, self.cd_user.id)
        # The grant opens the second activity.
        assert_partner_activity_allowance(
            self.partner.id, self.school.id, "in_school_training", "2026"
        )

    # ── §10: the IA queue page is IA's, listing only submitted partner work ─

    def test_partner_evidence_queue_lists_submitted_partner_work_for_ia_only(self):
        submitted = self._partner_activity(
            status="awaiting_ia_verification", submitted_to_ia_at=timezone.now()
        )
        self._partner_activity(status="partner_scheduled")  # not submitted
        self.client.force_login(self.ia_user)
        response = self.client.get("/ia/partner-evidence/")
        self.assertEqual(response.status_code, 200)
        listed = {row["a"].id for row in response.context["rows"]}
        self.assertEqual(listed, {submitted.id})
        # A partner cannot open IA's queue.
        self.client.force_login(self.partner_user)
        self.assertNotEqual(self.client.get("/ia/partner-evidence/").status_code, 200)

    # ── §16: the intake and invoice To-Dos derive from state ────────────────

    def test_partner_intake_todo_appears_and_closes_with_the_decision(self):
        from apps.command_center.todo_service import get_todos

        pa = PartnerAssignment.objects.create(
            school=self.school,
            partner=self.partner,
            assigning_staff_id=self.cd_user.id,
            purpose_of_visit="ssa_support",
            expected_activity_type="school_visit",
            status="assigned",
        )
        titles = [t["title"] for t in get_todos(self.partner_user)["todos"]]
        self.assertIn("Schedule or Return Assigned School", titles)
        pa.status = "returned"
        pa.save(update_fields=["status"])
        titles = [t["title"] for t in get_todos(self.partner_user)["todos"]]
        self.assertNotIn("Schedule or Return Assigned School", titles)
