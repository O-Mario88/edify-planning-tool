from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from datetime import date
from apps.activities.models import (
    Activity,
    ActivityScheduleCostLine,
    ActivityClosure,
    CompletedActivitySnapshot,
    AnalyticsPublishRecord,
)
from apps.core.enums import ActivityType, ActivityStatus
from apps.core.rbac import EdifyRole
from apps.schools.models import School
from apps.geography.models import Region, District
from apps.activities.closure_services import (
    ClosureEligibilityService,
    ActivityClosureService,
    ActivityReopenService,
    AnalyticsPublishingService,
    AuditTrailService,
)

User = get_user_model()


class ActivityClosureSystemTest(TestCase):
    def setUp(self):
        # Create Geography Hierarchy
        self.region = Region.objects.create(name="Central Region")
        self.district = District.objects.create(name="Kampala", region=self.region)
        self.school = School.objects.create(
            name="St. Marys", region=self.region, district=self.district
        )

        # Create activity that is executed (completion_started) but lacking checklist requirements
        self.activity = Activity.objects.create(
            school=self.school,
            delivery_type="staff",
            activity_type=ActivityType.SCHOOL_VISIT,
            status=ActivityStatus.COMPLETED,
            payment_status="pending",
            responsible_staff_id="cceo_user",
            planned_date=date(2026, 7, 2),
        )

        # Create a budget line (so finance cleared and NetSuite checks are triggered)
        self.cost_line = ActivityScheduleCostLine.objects.create(
            activity=self.activity,
            cost_setting_key="transport",
            label="Transport Allowances",
            unit_cost=100000,
            quantity=1,
            amount=100000,
        )

    def test_closure_eligibility_evaluation(self):
        # Initially, missing: Evidence, Salesforce ID, Accounts Cleared, NetSuite ID, Analytics Published
        checklist, blockers = ClosureEligibilityService.evaluate(self.activity)

        self.assertTrue(checklist.activity_executed)
        self.assertFalse(checklist.evidence_uploaded)
        self.assertFalse(checklist.salesforce_id_entered)
        self.assertFalse(checklist.accounts_cleared)
        self.assertFalse(checklist.netsuite_id_entered)

        # Blocker objects must be generated
        blocking_reasons = [b.blocking_reason for b in blockers]
        self.assertIn("Evidence Missing", blocking_reasons)
        self.assertIn("Activity SF ID Missing", blocking_reasons)
        self.assertIn("Accounts not cleared", blocking_reasons)
        self.assertIn("NetSuite ID missing", blocking_reasons)
        self.assertFalse(ClosureEligibilityService.is_eligible(self.activity))

    def test_closure_eligibility_with_all_checks_passed(self):
        # 1. Add Evidence
        from apps.evidence.models import EvidenceRecord

        EvidenceRecord.objects.create(
            activity=self.activity,
            kind="visit_form",
            uri="report.pdf",
            uploaded_by="cceo_user",
        )

        # 2. Add Salesforce ID
        self.activity.salesforce_activity_id = "SF-112233"
        self.activity.status = ActivityStatus.IA_VERIFIED  # Sets IA verified status
        self.activity.save()

        # 3. Add advance disbursement (Clears accounts check)
        from apps.fund_requests.models import Disbursement, NetSuiteExpenseRecord

        Disbursement.objects.create(
            activity=self.activity,
            amount_disbursed=100000,
            disbursed_by="accountant_jane",
            payment_method="Mobile Money",
            payment_reference="REF-8899",
        )

        # 4. Add NetSuite ID
        NetSuiteExpenseRecord.objects.create(
            activity=self.activity,
            netsuite_expense_id="NS-EXP-999",
            expense_date=date(2026, 7, 2),
            amount_entered=100000,
            entered_by="accountant_jane",
        )

        # 5. Add Analytics Publish Record
        AnalyticsPublishRecord.objects.create(
            activity=self.activity, status="published", published_at=timezone.now()
        )

        # 6. Log Audit timeline event
        AuditTrailService.log_event(self.activity, "Started", "cceo_user", "CCEO")

        # Re-evaluate
        checklist, blockers = ClosureEligibilityService.evaluate(self.activity)
        self.assertTrue(ClosureEligibilityService.is_eligible(self.activity))
        self.assertEqual(len(blockers), 0)

        # Perform Closure
        closure = ActivityClosureService.close(self.activity, closed_by="cceo_user")
        self.assertEqual(closure.status, "closed")

        self.activity.refresh_from_db()
        self.assertEqual(self.activity.status, "closed")

        # Verify completed snapshot frozen metrics
        snapshot = CompletedActivitySnapshot.objects.get(activity=self.activity)
        self.assertEqual(snapshot.final_budget_amount, 100000)
        self.assertEqual(snapshot.netsuite_expense_id, "NS-EXP-999")

    def test_close_action_does_not_force_publish_analytics_on_a_failed_attempt(self):
        """close_activity_action must not unconditionally mark analytics
        "published" before checking real eligibility. self.activity (from
        setUp) is missing evidence/SF ID/accounts clearance, so the close
        attempt must fail — and must NOT leave a false published
        AnalyticsPublishRecord behind as a side effect."""
        cceo = User.objects.create_user(
            email="cceo-close@test.org",
            name="Closing CCEO",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="password",
            is_active=True,
        )
        self.client.force_login(cceo)
        # The closure workspace is data-scoped, not just role-gated: a CCEO
        # with no portfolio 404s rather than reaching another region's work.
        # This test is about the analytics side effect of a FAILED close, so
        # give the actor legitimate ownership -- otherwise it would pass for
        # the wrong reason (blocked at the door, never exercising publish).
        self.activity.responsible_staff_id = cceo.id
        self.activity.save(update_fields=["responsible_staff_id"])

        resp = self.client.post(f"/activities/{self.activity.id}/closure/close")
        self.assertIn(resp.status_code, (200, 302))

        self.activity.refresh_from_db()
        self.assertNotEqual(self.activity.status, "closed")
        self.assertFalse(
            AnalyticsPublishRecord.objects.filter(
                activity=self.activity, status="published"
            ).exists()
        )

    def test_publish_if_ready_only_publishes_once_core_requirements_are_met(self):
        """AnalyticsPublishingService.publish_if_ready() is the truthful
        replacement for the old unconditional publish() call."""
        # Not ready yet (setUp's activity is missing evidence/SF ID/etc).
        checklist = AnalyticsPublishingService.publish_if_ready(self.activity)
        self.assertFalse(checklist.analytics_published)
        self.assertFalse(
            AnalyticsPublishRecord.objects.filter(activity=self.activity).exists()
        )

        # Now genuinely satisfy every core requirement.
        from apps.evidence.models import EvidenceRecord
        from apps.fund_requests.models import Disbursement, NetSuiteExpenseRecord

        EvidenceRecord.objects.create(
            activity=self.activity,
            kind="visit_form",
            uri="report.pdf",
            uploaded_by="cceo_user",
        )
        self.activity.salesforce_activity_id = "SF-556677"
        self.activity.status = ActivityStatus.IA_VERIFIED
        self.activity.save()
        Disbursement.objects.create(
            activity=self.activity,
            amount_disbursed=100000,
            disbursed_by="accountant_jane",
            payment_method="Mobile Money",
            payment_reference="REF-5566",
        )
        NetSuiteExpenseRecord.objects.create(
            activity=self.activity,
            netsuite_expense_id="NS-EXP-556",
            expense_date=date(2026, 7, 2),
            amount_entered=100000,
            entered_by="accountant_jane",
        )

        checklist = AnalyticsPublishingService.publish_if_ready(self.activity)
        self.assertTrue(checklist.analytics_published)
        pub = AnalyticsPublishRecord.objects.get(activity=self.activity)
        self.assertEqual(pub.status, "published")

    def test_reopen_workflow(self):
        # Setup a closed activity
        self.activity.salesforce_activity_id = "SF-MOCK-1234"
        self.activity.status = "closed"
        self.activity.save()

        ActivityClosure.objects.create(activity=self.activity, status="closed")
        AnalyticsPublishRecord.objects.create(
            activity=self.activity, status="published", published_at=timezone.now()
        )

        # Reopen activity
        req = ActivityReopenService.reopen(
            activity=self.activity,
            reason="Wrong stamp uploaded",
            category="wrong_evidence",
            user_id="admin_user",
        )

        self.activity.refresh_from_db()
        # wrong_evidence INVALIDATES the achievement: the activity must land in
        # the correction state (which reverses target credit), not ia_verified
        # (which would keep the bad work credited in every target engine).
        self.assertEqual(self.activity.status, "returned_by_ia")
        self.assertEqual(self.activity.ia_verification_status, "returned")
        self.assertEqual(req.category, "wrong_evidence")

        closure = ActivityClosure.objects.get(activity=self.activity)
        self.assertEqual(closure.status, "reopened")

        # Analytics recalculation should be marked
        pub = AnalyticsPublishRecord.objects.get(activity=self.activity)
        self.assertEqual(pub.status, "recalculation_required")

    def test_reopen_for_finance_correction_keeps_credit(self):
        """Non-invalidating categories (finance/audit corrections): the field
        work stands, so the activity stays in the verified (credited) state."""
        self.activity.salesforce_activity_id = "SF-MOCK-1235"
        self.activity.status = "closed"
        self.activity.save()
        ActivityClosure.objects.create(activity=self.activity, status="closed")
        AnalyticsPublishRecord.objects.create(
            activity=self.activity, status="published", published_at=timezone.now()
        )

        ActivityReopenService.reopen(
            activity=self.activity,
            reason="NetSuite reference corrected",
            category="wrong_finance_clearance",
            user_id="admin_user",
        )
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.status, "ia_verified")
