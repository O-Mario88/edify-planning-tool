"""NetSuite accountability laws (mandate §4/§15/§17/§18).

NetSuite Code = accountability proof, entered by the RESPONSIBLE USER when
submitting accountability. Activity SF ID = program proof, a different field
entirely. The Accountant final-clears only after IA verification, and an
activity with disbursed money cannot close without its NetSuite Code.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile
from apps.activities.closure_services import (
    ActivityClosureService,
    ClosureEligibilityService,
)
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.exceptions import BadRequest
from apps.core.rbac import EdifyRole
from apps.evidence.models import EvidenceRecord
from apps.fund_requests.advance_service import (
    approve_accountability,
    submit_accountability,
)
from apps.fund_requests.models import AdvanceRequest, AdvanceRequestStatus
from apps.geography.models import District, Region
from apps.schools.models import School

User = get_user_model()


class NetSuiteAccountabilityLawsTest(TestCase):
    def setUp(self):
        region = Region.objects.create(name="NS Region")
        district = District.objects.create(name="NS District", region=region)
        self.school = School.objects.create(
            school_id="NS-SCH", name="NS School", region=region, district=district
        )
        self.cceo = User.objects.create_user(
            email="cceo@ns.org",
            name="Nia CCEO",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="x",
            is_active=True,
        )
        StaffProfile.objects.create(user=self.cceo, title="CCEO")
        self.accountant = User.objects.create_user(
            email="acct@ns.org",
            name="Abe Accountant",
            roles=[EdifyRole.PROGRAM_ACCOUNTANT.value],
            active_role=EdifyRole.PROGRAM_ACCOUNTANT.value,
            password="x",
            is_active=True,
        )

        self.activity = Activity.objects.create(
            school=self.school,
            activity_type="school_visit",
            delivery_type="staff",
            status="completed",
            responsible_staff_id=self.cceo.id,
            fy="2026",
            quarter="Q3",
            scheduled_date=timezone.now(),
            salesforce_activity_id="SV-88112233",  # program proof (SF ID)
        )
        self.line = ActivityScheduleCostLine.objects.create(
            activity=self.activity,
            cost_setting_key="staff_visit_transport_primary",
            label="Transport",
            unit_cost=50_000,
            quantity=1,
            amount=50_000,
            responsible_user=self.cceo.id,
        )
        self.adv = AdvanceRequest.objects.create(
            activity=self.activity,
            budget_line=self.line,
            responsible_user_id=self.cceo.id,
            fy="2026",
            quarter="Q3",
            amount=50_000,
            status=AdvanceRequestStatus.DISBURSED,
            disbursed_amount=50_000,
        )

    # ── §15: accountability requires the NetSuite Code ───────────────────────
    def test_netsuite_code_required_for_accountability_completion(self):
        with self.assertRaises(BadRequest):
            submit_accountability(
                self.adv.id,
                {"amountSpent": 50_000, "amountReturned": 0, "netsuiteId": ""},
                self.cceo,
            )
        self.adv.refresh_from_db()
        self.assertEqual(self.adv.status, AdvanceRequestStatus.DISBURSED)

        submit_accountability(
            self.adv.id,
            {"amountSpent": 50_000, "amountReturned": 0, "netsuiteId": "EXP-2026-771"},
            self.cceo,
        )
        self.adv.refresh_from_db()
        self.assertEqual(self.adv.status, AdvanceRequestStatus.ACCOUNTABILITY_PENDING)
        self.assertEqual(self.adv.accountability_netsuite_id, "EXP-2026-771")

    def test_variance_requires_explanation(self):
        with self.assertRaises(BadRequest):
            submit_accountability(
                self.adv.id,
                {"amountSpent": 30_000, "amountReturned": 0, "netsuiteId": "EXP-1"},
                self.cceo,
            )
        submit_accountability(
            self.adv.id,
            {
                "amountSpent": 30_000,
                "amountReturned": 0,
                "netsuiteId": "EXP-1",
                "varianceNote": "Venue was free; only transport spent.",
            },
            self.cceo,
        )
        self.adv.refresh_from_db()
        self.assertEqual(self.adv.status, AdvanceRequestStatus.ACCOUNTABILITY_PENDING)
        self.assertIn("Venue was free", self.adv.last_note)

    # ── §4/§16: SF ID and NetSuite Code are different proofs ─────────────────
    def test_activity_sf_id_is_separate_from_netsuite_code(self):
        # The activity already carries its program proof (SF ID) — that must
        # NOT satisfy the accountability requirement.
        self.assertTrue(self.activity.salesforce_activity_id)
        with self.assertRaises(BadRequest):
            submit_accountability(
                self.adv.id,
                {"amountSpent": 50_000, "amountReturned": 0},
                self.cceo,
            )
        # And once submitted, the two proofs live on different fields.
        submit_accountability(
            self.adv.id,
            {"amountSpent": 50_000, "amountReturned": 0, "netsuiteId": "EXP-42"},
            self.cceo,
        )
        self.adv.refresh_from_db()
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.salesforce_activity_id, "SV-88112233")
        self.assertEqual(self.adv.accountability_netsuite_id, "EXP-42")
        self.assertNotEqual(
            self.activity.salesforce_activity_id, self.adv.accountability_netsuite_id
        )

    # ── §17: IA verification gates final finance clearance ──────────────────
    def test_accountant_cannot_final_clear_without_ia_verification(self):
        submit_accountability(
            self.adv.id,
            {"amountSpent": 50_000, "amountReturned": 0, "netsuiteId": "EXP-9"},
            self.cceo,
        )
        with self.assertRaises(BadRequest):
            approve_accountability(self.adv.id, self.accountant)
        self.adv.refresh_from_db()
        self.assertEqual(self.adv.status, AdvanceRequestStatus.ACCOUNTABILITY_PENDING)

        self.activity.ia_verification_status = "confirmed"
        self.activity.save(update_fields=["ia_verification_status"])
        approve_accountability(self.adv.id, self.accountant)
        self.adv.refresh_from_db()
        self.assertEqual(self.adv.status, AdvanceRequestStatus.ACCOUNTED)

    # ── §18: no closure without the NetSuite Code when money moved ───────────
    def test_activity_cannot_close_without_netsuite_code_when_accountability_required(
        self,
    ):
        # Meet every OTHER closure requirement: executed, evidence, SF ID, IA.
        EvidenceRecord.objects.create(
            activity=self.activity,
            kind="photo",
            uri="proof.jpg",
            uploaded_by=self.cceo.id,
        )
        self.activity.status = "ia_verified"
        self.activity.ia_verification_status = "confirmed"
        self.activity.save(update_fields=["status", "ia_verification_status"])

        checklist, blockers = ClosureEligibilityService.evaluate(self.activity)
        self.assertFalse(checklist.netsuite_id_entered)
        self.assertFalse(ClosureEligibilityService.is_eligible(self.activity))
        self.assertIn("NetSuite ID missing", [b.blocking_reason for b in blockers])
        with self.assertRaises(ValueError):
            ActivityClosureService.close(self.activity, closed_by=self.accountant.id)

        # Accountability submitted with the code satisfies the NetSuite gate,
        # but the activity must NOT yet be closeable — the accountant has not
        # final-cleared it. Closure requires genuine accountant clearance
        # (mandate §9/§18), not merely a submitted accountability.
        submit_accountability(
            self.adv.id,
            {"amountSpent": 50_000, "amountReturned": 0, "netsuiteId": "EXP-77"},
            self.cceo,
        )
        checklist, _ = ClosureEligibilityService.evaluate(self.activity)
        self.assertTrue(checklist.netsuite_id_entered)
        self.assertFalse(
            checklist.accounts_cleared,
            "accountability_pending must not count as accountant-cleared",
        )
        self.assertFalse(ClosureEligibilityService.is_eligible(self.activity))
        with self.assertRaises(ValueError):
            ActivityClosureService.close(self.activity, closed_by=self.accountant.id)

        # The accountant final-clears (→ ACCOUNTED) → the gate opens.
        from apps.fund_requests.advance_service import approve_accountability

        approve_accountability(self.adv.id, self.accountant)
        checklist, _ = ClosureEligibilityService.evaluate(self.activity)
        self.assertTrue(checklist.accounts_cleared)
        self.assertTrue(ClosureEligibilityService.is_eligible(self.activity))
        closure = ActivityClosureService.close(
            self.activity, closed_by=self.accountant.id
        )
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.status, "closed")
        self.assertIsNotNone(closure)

    # ── audit trail on the final money-closing transitions ───────────────────
    def test_submit_and_approve_accountability_write_audit_log(self):
        """Regression: advance_service.py had zero audit_log calls anywhere —
        the single most financially terminal transition (Accountant final-
        clears to ACCOUNTED) left no audit trail at all."""
        from apps.audit.models import AuditLog

        self.activity.status = "ia_verified"
        self.activity.ia_verification_status = "confirmed"
        self.activity.save(update_fields=["status", "ia_verification_status"])

        submit_accountability(
            self.adv.id,
            {"amountSpent": 50_000, "amountReturned": 0, "netsuiteId": "EXP-AUDIT-1"},
            self.cceo,
        )
        self.assertTrue(
            AuditLog.objects.filter(
                action="advance_request.submit_accountability",
                subject_id=str(self.adv.id),
            ).exists()
        )

        approve_accountability(self.adv.id, self.accountant)
        self.assertTrue(
            AuditLog.objects.filter(
                action="advance_request.approve_accountability",
                subject_id=str(self.adv.id),
            ).exists()
        )
        self.adv.refresh_from_db()
        self.assertEqual(self.adv.status, AdvanceRequestStatus.ACCOUNTED)
