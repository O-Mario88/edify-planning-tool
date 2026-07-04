from django.test import TestCase
from django.utils import timezone
from datetime import date
from apps.activities.models import (
    Activity,
    ActivityScheduleCostLine,
    ActivityClosure,
    CompletedActivitySnapshot,
    AnalyticsPublishRecord
)
from apps.core.enums import ActivityType, ActivityStatus
from apps.schools.models import School
from apps.geography.models import Region, District
from apps.activities.closure_services import (
    ClosureEligibilityService,
    ActivityClosureService,
    ActivityReopenService,
    AuditTrailService
)

class ActivityClosureSystemTest(TestCase):
    def setUp(self):
        # Create Geography Hierarchy
        self.region = Region.objects.create(name="Central Region")
        self.district = District.objects.create(name="Kampala", region=self.region)
        self.school = School.objects.create(name="St. Marys", region=self.region, district=self.district)
        
        # Create activity that is executed (completion_started) but lacking checklist requirements
        self.activity = Activity.objects.create(
            school=self.school,
            delivery_type="staff",
            activity_type=ActivityType.SCHOOL_VISIT,
            status=ActivityStatus.COMPLETED,
            payment_status="pending",
            responsible_staff_id="cceo_user",
            planned_date=date(2026, 7, 2)
        )
        
        # Create a budget line (so finance cleared and NetSuite checks are triggered)
        self.cost_line = ActivityScheduleCostLine.objects.create(
            activity=self.activity,
            cost_setting_key="transport",
            label="Transport Allowances",
            unit_cost=100000,
            quantity=1,
            amount=100000
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
            uploaded_by="cceo_user"
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
            payment_reference="REF-8899"
        )
        
        # 4. Add NetSuite ID
        NetSuiteExpenseRecord.objects.create(
            activity=self.activity,
            netsuite_expense_id="NS-EXP-999",
            expense_date=date(2026, 7, 2),
            amount_entered=100000,
            entered_by="accountant_jane"
        )
        
        # 5. Add Analytics Publish Record
        AnalyticsPublishRecord.objects.create(
            activity=self.activity,
            status="published",
            published_at=timezone.now()
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

    def test_reopen_workflow(self):
        # Setup a closed activity
        self.activity.salesforce_activity_id = "SF-MOCK-1234"
        self.activity.status = "closed"
        self.activity.save()
        
        ActivityClosure.objects.create(activity=self.activity, status="closed")
        AnalyticsPublishRecord.objects.create(
            activity=self.activity,
            status="published",
            published_at=timezone.now()
        )
        
        # Reopen activity
        req = ActivityReopenService.reopen(
            activity=self.activity,
            reason="Wrong stamp uploaded",
            category="wrong_evidence",
            user_id="admin_user"
        )
        
        self.activity.refresh_from_db()
        # Should revert to verified and show reopened state
        self.assertEqual(self.activity.status, "ia_verified")
        self.assertEqual(req.category, "wrong_evidence")
        
        closure = ActivityClosure.objects.get(activity=self.activity)
        self.assertEqual(closure.status, "reopened")
        
        # Analytics recalculation should be marked
        pub = AnalyticsPublishRecord.objects.get(activity=self.activity)
        self.assertEqual(pub.status, "recalculation_required")
