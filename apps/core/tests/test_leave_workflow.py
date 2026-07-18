from datetime import date, datetime
from django.utils import timezone
from rest_framework.test import APITestCase
from apps.accounts.models import (
    User,
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    Leave,
    LeaveTypePolicy,
    LeaveBalance,
    TemporaryCoverageAssignment,
    PublicHoliday,
)
from apps.schools.models import School
from apps.geography.models import Region, District
from apps.core.scoping import resolve_user_scope
from apps.core.permissions import RolePermissionService
from apps.activities.models import Activity
from apps.activities.services import create
from apps.audit.models import AuditLog
from apps.audit.services import log
from apps.hr.leave_services import (
    WorkingDayCalculator,
    LeaveBalanceService,
    LeaveRequestService,
    LeaveApprovalService,
)


class LeaveWorkflowIntegrationTest(APITestCase):
    def setUp(self):
        # 1. Geography Setup
        self.region = Region.objects.create(name="Central")
        self.district = District.objects.create(name="Kampala", region=self.region)

        # 2. Seed Public Holidays
        PublicHoliday.objects.create(date="2026-10-09", name="Independence Day")

        # 3. Seed Leave Policies
        LeaveTypePolicy.objects.create(
            leave_type="personal_time_off",
            label="Personal Time Off",
            annual_entitlement=21,
            requires_attachment=False,
            approver_role="Program Lead",
            weekends_count=False,
            public_holidays_count=False,
        )
        LeaveTypePolicy.objects.create(
            leave_type="sick_leave",
            label="Sick Leave",
            annual_entitlement=14,
            requires_attachment=True,
            approver_role="Program Lead",
            weekends_count=False,
            public_holidays_count=False,
        )

        # 4. Create Schools
        self.school1 = School.objects.create(
            school_id="S-001",
            name="School One",
            region=self.region,
            district=self.district,
            enrollment=100,
            school_type="client",
        )
        self.school2 = School.objects.create(
            school_id="S-002",
            name="School Two",
            region=self.region,
            district=self.district,
            enrollment=150,
            school_type="client",
        )

        # 5. Create Users & Staff Profiles
        # CCEO-1 (The Cover)
        self.cceo1_user = User.objects.create_user(
            email="cceo1@edify.test",
            name="CCEO One",
            roles=["CCEO"],
            active_role="CCEO",
            password="x",
            is_active=True,
        )
        self.cceo1_profile = StaffProfile.objects.create(
            user=self.cceo1_user, staff_number="SP-001"
        )
        StaffSchoolAssignment.objects.create(
            staff=self.cceo1_profile, school_id=self.school1.id
        )

        # CCEO-2 (The Absentee)
        self.cceo2_user = User.objects.create_user(
            email="cceo2@edify.test",
            name="CCEO Two",
            roles=["CCEO"],
            active_role="CCEO",
            password="x",
            is_active=True,
        )
        self.cceo2_profile = StaffProfile.objects.create(
            user=self.cceo2_user, staff_number="SP-002"
        )
        StaffSchoolAssignment.objects.create(
            staff=self.cceo2_profile, school_id=self.school2.id
        )

        # PL (The Approver)
        self.pl_user = User.objects.create_user(
            email="pl@edify.test",
            name="PL Supervisor",
            roles=["ProgramLead"],
            active_role="ProgramLead",
            password="x",
            is_active=True,
        )
        self.pl_profile = StaffProfile.objects.create(
            user=self.pl_user, staff_number="SP-003"
        )

        # PL supervises CCEO-2
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl_profile, supervisee=self.cceo2_profile
        )

        # Initialize balances for the year 2026
        LeaveBalanceService.initialize_balances_for_staff(self.cceo2_profile, 2026)

    def test_working_day_calculator(self):
        """Verify calculator counts working days, skipping weekends and public holidays."""
        # Oct 8 (Thu) to Oct 12 (Mon) 2026
        # Oct 9 is Independence Day (Holiday)
        # Oct 10 (Sat), Oct 11 (Sun)
        # Expected working days: Oct 8, Oct 12 = 2 days
        days = WorkingDayCalculator.calculate_working_days("2026-10-08", "2026-10-12")
        self.assertEqual(days, 2)

    def test_leave_request_and_approval_flow(self):
        """Verify requesting leave, checking coverage, and PL approval/delegation."""
        # 1. Request leave for CCEO-2 covering CCEO-1
        data = {
            "type": "personal_time_off",
            "start_date": "2026-10-08",
            "end_date": "2026-10-12",
            "covering_staff": self.cceo1_profile.id,
            "coverage_notes": "Call School Two if emergency",
            "emergency_contact": "Jane Doe +25670",
            "reason": "Family vacation",
        }
        leave = LeaveRequestService.request_leave(self.cceo2_profile, data)
        self.assertEqual(leave.status, "pending")
        self.assertEqual(leave.days_charged, 2)

        # Check balance shows pending deduction
        bal = LeaveBalance.objects.get(
            staff=self.cceo2_profile, leave_type="personal_time_off", year=2026
        )
        self.assertEqual(bal.pending, 2)
        self.assertEqual(bal.remaining, 19)

        # 2. PL review / approval
        LeaveApprovalService.approve_request(leave.id, self.pl_user)

        leave.refresh_from_db()
        self.assertEqual(leave.status, "approved")

        # Check balance reflects approved deduction
        bal.refresh_from_db()
        self.assertEqual(bal.pending, 0)
        self.assertEqual(bal.used, 2)
        self.assertEqual(bal.remaining, 19)

        # Verify TemporaryCoverageAssignment was created
        assignment = TemporaryCoverageAssignment.objects.get(leave_request=leave)
        self.assertEqual(assignment.original_staff, self.cceo2_profile)
        self.assertEqual(assignment.covering_staff, self.cceo1_profile)
        self.assertEqual(assignment.status, "active")

    def test_leave_coverage_permission_scoping(self):
        """Verify covering user gets access to absentee's school portfolio and supervisees."""
        # Setup approved coverage assignment
        start_dt = timezone.make_aware(datetime(2026, 10, 8, 8, 0, 0))
        end_dt = timezone.make_aware(datetime(2026, 10, 12, 17, 0, 0))

        leave = Leave.objects.create(
            staff=self.cceo2_profile,
            type="personal_time_off",
            start_date="2026-10-08",
            end_date="2026-10-12",
            days=5,
            days_charged=2,
            status="approved",
        )
        cov = TemporaryCoverageAssignment.objects.create(
            original_staff=self.cceo2_profile,
            covering_staff=self.cceo1_profile,
            leave_request=leave,
            start_datetime=start_dt,
            end_datetime=end_dt,
            scope="full",
            status="active",
        )

        # Mock timezone.now() to be within coverage window
        original_now = timezone.now
        try:
            timezone.now = lambda: timezone.make_aware(datetime(2026, 10, 9, 10, 0, 0))

            # Resolve scope for CCEO-1 (covering CCEO-2)
            scope = resolve_user_scope(self.cceo1_user)
            # CCEO-1 should see their school (School One) AND CCEO-2's school (School Two)
            self.assertIn(self.school1.id, scope.school_ids)
            self.assertIn(self.school2.id, scope.school_ids)

            # Test permission check on school 2 activity
            activity_cceo2 = Activity.objects.create(
                activity_type="school_visit",
                school=self.school2,
                responsible_staff_id=self.cceo2_user.id,
                delivery_type="staff",
                fy=2026,
                quarter=1,
            )
            # CCEO-1 should be allowed to view
            can_view = RolePermissionService.can_view_record(
                self.cceo1_user, activity_cceo2
            )
            self.assertTrue(can_view)
        finally:
            timezone.now = original_now

    def test_coverage_grant_is_audited(self):
        """Approving leave with a covering staff member must write an
        hr.coverage_granted audit event — a coverage grant is a real
        access-delegation event, not just an internal bookkeeping row."""
        leave = Leave.objects.create(
            staff=self.cceo2_profile,
            type="personal_time_off",
            start_date="2026-10-08",
            end_date="2026-10-12",
            days=5,
            days_charged=2,
            status="pending",
            covering_staff=self.cceo1_profile,
        )
        LeaveApprovalService.approve_request(leave.id, self.pl_user)
        entry = (
            AuditLog.objects.filter(action="hr.coverage_granted")
            .order_by("-created_at")
            .first()
        )
        self.assertIsNotNone(entry)
        self.assertEqual(entry.payload["coveringStaffId"], self.cceo1_profile.id)
        self.assertEqual(entry.payload["originalStaffId"], self.cceo2_profile.id)

    def test_revoke_coverage_requires_authorization(self):
        """Audit found any role in the broad leave_coverage page ACL
        (CCEO/RVP/Accountant/IA included) could revoke ANY org-wide coverage
        assignment by id — closing it: only the leave's authorized approver
        (here, the CCEO's supervising PL) or HR/Admin may revoke it."""
        start_dt = timezone.make_aware(datetime(2026, 10, 8, 8, 0, 0))
        end_dt = timezone.make_aware(datetime(2026, 10, 12, 17, 0, 0))
        leave = Leave.objects.create(
            staff=self.cceo2_profile,
            type="personal_time_off",
            start_date="2026-10-08",
            end_date="2026-10-12",
            days=5,
            days_charged=2,
            status="approved",
            covering_staff=self.cceo1_profile,
        )
        cov = TemporaryCoverageAssignment.objects.create(
            original_staff=self.cceo2_profile,
            covering_staff=self.cceo1_profile,
            leave_request=leave,
            start_datetime=start_dt,
            end_datetime=end_dt,
            scope="full",
            status="active",
        )

        # An unrelated CCEO (the covering staff member themselves — no
        # supervisory relationship to the leave) must be rejected.
        self.client.force_login(self.cceo1_user)
        res = self.client.post(f"/leave/coverage/{cov.id}/revoke")
        self.assertEqual(res.status_code, 302)
        cov.refresh_from_db()
        self.assertEqual(cov.status, "active")

        # The CCEO's supervising PL (the authorized approver for this leave)
        # succeeds.
        self.client.force_login(self.pl_user)
        res = self.client.post(f"/leave/coverage/{cov.id}/revoke")
        self.assertEqual(res.status_code, 302)
        cov.refresh_from_db()
        self.assertEqual(cov.status, "revoked")

        entry = AuditLog.objects.filter(action="hr.coverage_revoked").first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.subject_id, cov.id)

    def test_prevent_activity_during_leave(self):
        """Verify scheduling/rescheduling activity during approved leave is blocked."""
        # Create approved leave for CCEO-2 on Oct 8 to Oct 12
        Leave.objects.create(
            staff=self.cceo2_profile,
            type="personal_time_off",
            start_date="2026-10-08",
            end_date="2026-10-12",
            days=5,
            days_charged=2,
            status="approved",
        )

        # Mock central cost costing seed catalog to allow scheduling
        from apps.budget.models import CostCatalogue, CostSetting

        CostCatalogue.objects.all().delete()
        catalogue = CostCatalogue.objects.create(
            label="Default Catalog", fy="2026", is_active=True
        )
        CostSetting.objects.create(
            catalogue=catalogue,
            key="school_visit_cost_per_school_primary",
            label="primary",
            unit_cost=100,
        )
        CostSetting.objects.create(
            catalogue=catalogue,
            key="school_visit_cost_per_school_secondary",
            label="secondary",
            unit_cost=100,
        )
        CostSetting.objects.create(
            catalogue=catalogue,
            key="school_visit_cost_per_school",
            label="general",
            unit_cost=100,
        )

        # Create activity scheduled on Oct 9 (during leave) -> should fail
        from apps.core.exceptions import BadRequest

        with self.assertRaises(BadRequest) as ctx:
            create(
                data={
                    "activityType": "school_visit",
                    "schoolId": self.school2.school_id,
                    "scheduledDate": "2026-10-09",
                    "responsibleStaffId": self.cceo2_user.id,
                },
                principal=self.cceo2_user,
            )
        self.assertIn("approved leave", str(ctx.exception))

    def test_audit_log_coverage_injection(self):
        """Verify audit logs capture coverage context when acting as cover."""
        start_dt = timezone.make_aware(datetime(2026, 10, 8, 8, 0, 0))
        end_dt = timezone.make_aware(datetime(2026, 10, 12, 17, 0, 0))

        leave = Leave.objects.create(
            staff=self.cceo2_profile,
            type="personal_time_off",
            start_date="2026-10-08",
            end_date="2026-10-12",
            days=5,
            days_charged=2,
            status="approved",
        )

        cov = TemporaryCoverageAssignment.objects.create(
            original_staff=self.cceo2_profile,
            covering_staff=self.cceo1_profile,
            leave_request=leave,
            start_datetime=start_dt,
            end_datetime=end_dt,
            scope="full",
            status="active",
        )

        # Mock timezone.now() to be within coverage window
        original_now = timezone.now
        try:
            timezone.now = lambda: timezone.make_aware(datetime(2026, 10, 9, 10, 0, 0))

            # Log action as CCEO-1
            log(
                action="reschedule_activity",
                subject_kind="Activity",
                subject_id="act_123",
                actor_id=self.cceo1_user.id,
                actor_role="CCEO",
                payload={"reason": "Rain"},
            )

            # Retrieve tail log
            audit = AuditLog.objects.order_by("-seq").first()
            self.assertIsNotNone(audit)
            payload = audit.payload
            self.assertIn("acting_for", payload)
            self.assertEqual(payload["acting_for"]["user_id"], self.cceo2_user.id)
            self.assertEqual(payload["reason"], "Leave Coverage")
        finally:
            timezone.now = original_now

    def test_calendar_block_creation(self):
        """Test CalendarBlockService creation."""
        from apps.hr.leave_services import CalendarBlockService

        data = {
            "title": "Easter Weekend",
            "block_type": "PUBLIC_HOLIDAY",
            "start_date": "2026-04-03",
            "end_date": "2026-04-06",
            "country": "Uganda",
            "applies_to_all_roles": True,
        }
        block = CalendarBlockService.create_block(data, self.pl_user.id)
        self.assertEqual(block.title, "Easter Weekend")
        self.assertEqual(block.block_type, "PUBLIC_HOLIDAY")
        self.assertEqual(block.start_date, date(2026, 4, 3))
        self.assertEqual(block.end_date, date(2026, 4, 6))

    def test_public_holiday_service_range(self):
        """Test PublicHolidayService date range resolution."""
        from apps.accounts.models import CalendarBlock
        from apps.hr.leave_services import PublicHolidayService

        # Add a block public holiday
        CalendarBlock.objects.create(
            title="Good Friday",
            block_type="PUBLIC_HOLIDAY",
            start_date="2026-04-03",
            end_date="2026-04-03",
            country="Uganda",
            is_active=True,
        )
        holidays = PublicHolidayService.get_holidays_in_range(
            "2026-04-01", "2026-04-05"
        )
        # Good Friday is a match
        self.assertIn(date(2026, 4, 3), holidays)

    def test_working_day_calculator_excludes_calendar_block_only_holiday(self):
        """A holiday added only via CalendarBlock (e.g. the /public-holidays
        admin surface), with no matching PublicHoliday row, must still be
        excluded from the working-day count — matching what
        PublicHolidayService.get_holidays_in_range (the preview surface)
        already reports as a holiday to skip."""
        from apps.accounts.models import CalendarBlock

        # Nov 2 (Mon) - Nov 6 (Fri) 2026: 5 weekdays, no weekend in range.
        CalendarBlock.objects.create(
            title="Company Founders Day",
            block_type="PUBLIC_HOLIDAY",
            start_date="2026-11-04",
            end_date="2026-11-04",
            country="Uganda",
            is_active=True,
        )
        # Confirm this is NOT a PublicHoliday row (isolates the CalendarBlock path).
        self.assertFalse(PublicHoliday.objects.filter(date="2026-11-04").exists())

        days = WorkingDayCalculator.calculate_working_days("2026-11-02", "2026-11-06")
        self.assertEqual(days, 4)

    def test_leave_request_excludes_calendar_block_only_holiday_from_balance(self):
        """Submitting leave that spans a CalendarBlock-only holiday must
        deduct the same number of days the preview/conflict-detection
        surface showed as excluded, instead of silently overcharging PTO."""
        from apps.accounts.models import CalendarBlock
        from apps.hr.leave_services import PublicHolidayService

        CalendarBlock.objects.create(
            title="Company Founders Day",
            block_type="PUBLIC_HOLIDAY",
            start_date="2026-11-04",
            end_date="2026-11-04",
            country="Uganda",
            is_active=True,
        )

        # Sanity: the preview surface already reports Nov 4 as excluded.
        holidays_shown_in_preview = PublicHolidayService.get_holidays_in_range(
            "2026-11-02", "2026-11-06"
        )
        self.assertIn(date(2026, 11, 4), holidays_shown_in_preview)

        data = {
            "type": "personal_time_off",
            "start_date": "2026-11-02",
            "end_date": "2026-11-06",
            "reason": "Long weekend",
        }
        leave = LeaveRequestService.request_leave(self.cceo2_profile, data)
        # 5 weekdays - 1 CalendarBlock-only holiday (Nov 4) = 4 days charged.
        self.assertEqual(leave.days_charged, 4)

        bal = LeaveBalance.objects.get(
            staff=self.cceo2_profile, leave_type="personal_time_off", year=2026
        )
        self.assertEqual(bal.pending, 4)
        self.assertEqual(bal.remaining, 21 - 4)

    def test_blackout_date_service_range(self):
        """Test BlackoutDateService date range resolution."""
        from apps.accounts.models import CalendarBlock
        from apps.hr.leave_services import BlackoutDateService

        CalendarBlock.objects.create(
            title="Q3 Review",
            block_type="BLACKOUT_DATE",
            start_date="2026-09-01",
            end_date="2026-09-02",
            country="Uganda",
            is_active=True,
        )
        blackouts = BlackoutDateService.get_blackout_dates_in_range(
            "2026-08-30", "2026-09-05"
        )
        self.assertIn(date(2026, 9, 1), blackouts)
        self.assertIn(date(2026, 9, 2), blackouts)

    def test_leave_conflict_detection_activity(self):
        """Test LeaveConflictDetectionService detects activity conflicts."""
        from apps.hr.leave_services import LeaveConflictDetectionService

        # Create an activity for CCEO-2 during leave
        Activity.objects.create(
            activity_type="school_visit",
            school=self.school2,
            responsible_staff_id=self.cceo2_user.id,
            scheduled_date="2026-10-09",
            delivery_type="staff",
            fy=2026,
            quarter=1,
        )
        conflicts = LeaveConflictDetectionService.detect(
            self.cceo2_profile, "2026-10-08", "2026-10-12"
        )
        self.assertTrue(
            any(c["conflict_type"] == "activity_during_leave" for c in conflicts)
        )

    def test_leave_conflict_detection_holiday(self):
        """Test LeaveConflictDetectionService detects holiday overlaps."""
        from apps.hr.leave_services import LeaveConflictDetectionService
        from apps.accounts.models import CalendarBlock

        CalendarBlock.objects.create(
            title="Holiday",
            block_type="PUBLIC_HOLIDAY",
            start_date="2026-10-09",
            end_date="2026-10-09",
            is_active=True,
        )
        conflicts = LeaveConflictDetectionService.detect(
            self.cceo2_profile, "2026-10-08", "2026-10-12"
        )
        self.assertTrue(any(c["conflict_type"] == "public_holiday" for c in conflicts))

    def test_leave_conflict_detection_blackout(self):
        """Test LeaveConflictDetectionService detects blackout overlaps."""
        from apps.hr.leave_services import LeaveConflictDetectionService
        from apps.accounts.models import CalendarBlock

        CalendarBlock.objects.create(
            title="Locked",
            block_type="BLACKOUT_DATE",
            start_date="2026-10-10",
            end_date="2026-10-10",
            is_active=True,
        )
        conflicts = LeaveConflictDetectionService.detect(
            self.cceo2_profile, "2026-10-08", "2026-10-12"
        )
        self.assertTrue(any(c["conflict_type"] == "blackout_date" for c in conflicts))

    def test_leave_conflict_detection_conference(self):
        """Test LeaveConflictDetectionService detects conference overlaps."""
        from apps.hr.leave_services import LeaveConflictDetectionService
        from apps.accounts.models import CalendarBlock

        CalendarBlock.objects.create(
            title="Week-long Conference",
            block_type="STAFF_CONFERENCE",
            start_date="2026-10-08",
            end_date="2026-10-12",
            is_active=True,
        )
        conflicts = LeaveConflictDetectionService.detect(
            self.cceo2_profile, "2026-10-08", "2026-10-12"
        )
        self.assertTrue(
            any(c["conflict_type"] == "staff_conference" for c in conflicts)
        )

    def test_leave_conflict_detection_cover_leave(self):
        """Test LeaveConflictDetectionService detects cover person unavailable on leave."""
        from apps.hr.leave_services import LeaveConflictDetectionService

        # Assign approved leave for CCEO-1 (cover) during the same period
        Leave.objects.create(
            staff=self.cceo1_profile,
            type="personal_time_off",
            start_date="2026-10-08",
            end_date="2026-10-12",
            days=5,
            days_charged=2,
            status="approved",
        )
        conflicts = LeaveConflictDetectionService.detect(
            self.cceo2_profile, "2026-10-08", "2026-10-12", self.cceo1_profile
        )
        self.assertTrue(
            any(c["conflict_type"] == "cover_unavailable" for c in conflicts)
        )

    def test_leave_conflict_detection_cover_workload(self):
        """Test LeaveConflictDetectionService detects cover person high workload."""
        from apps.hr.leave_services import LeaveConflictDetectionService

        # Add 6 activities for CCEO-1 during that range
        for i in range(6):
            Activity.objects.create(
                activity_type="school_visit",
                school=self.school1,
                responsible_staff_id=self.cceo1_user.id,
                scheduled_date="2026-10-08",
                delivery_type="staff",
                fy=2026,
                quarter=1,
            )
        conflicts = LeaveConflictDetectionService.detect(
            self.cceo2_profile, "2026-10-08", "2026-10-12", self.cceo1_profile
        )
        self.assertTrue(
            any(c["conflict_type"] == "high_workload_cover" for c in conflicts)
        )

    def test_planning_availability_sunday(self):
        """Test Sunday is blocked by PlanningAvailabilityService."""
        from apps.hr.leave_services import PlanningAvailabilityService

        res = PlanningAvailabilityService.check(self.cceo2_user, "2026-10-11")  # Sunday
        self.assertEqual(res["status"], "blocked")
        self.assertIn("Sundays", res["blockers"][0])

    def test_planning_availability_leave(self):
        """Test approved leave dates are blocked by PlanningAvailabilityService."""
        from apps.hr.leave_services import PlanningAvailabilityService

        Leave.objects.create(
            staff=self.cceo2_profile,
            type="personal_time_off",
            start_date="2026-10-08",
            end_date="2026-10-08",
            days=1,
            days_charged=1,
            status="approved",
        )
        res = PlanningAvailabilityService.check(self.cceo2_user, "2026-10-08")
        self.assertEqual(res["status"], "blocked")
        self.assertIn("approved leave", res["blockers"][0])

    def test_planning_availability_holiday_blackout(self):
        """Test holiday and blackout dates are blocked by PlanningAvailabilityService."""
        from apps.hr.leave_services import PlanningAvailabilityService
        from apps.accounts.models import CalendarBlock

        CalendarBlock.objects.create(
            title="Blackout",
            block_type="BLACKOUT_DATE",
            start_date="2026-10-08",
            end_date="2026-10-08",
            is_active=True,
        )
        res = PlanningAvailabilityService.check(self.cceo2_user, "2026-10-08")
        self.assertEqual(res["status"], "blocked")
        self.assertIn("blackout date", res["blockers"][0])

    def test_planning_availability_conference_week(self):
        """Test conference weeks block scheduling in PlanningAvailabilityService."""
        from apps.hr.leave_services import PlanningAvailabilityService
        from apps.accounts.models import CalendarBlock

        CalendarBlock.objects.create(
            title="All Staff Conference",
            block_type="STAFF_CONFERENCE",
            start_date="2026-10-08",
            end_date="2026-10-08",
            is_active=True,
        )
        res = PlanningAvailabilityService.check(self.cceo2_user, "2026-10-08")
        self.assertEqual(res["status"], "blocked")
        self.assertIn("Conference", res["blockers"][0])

    def test_team_availability_heatmap(self):
        """Test TeamAvailabilityService.get_4week_heatmap returns status rows."""
        from apps.hr.leave_services import TeamAvailabilityService

        heatmap = TeamAvailabilityService.get_4week_heatmap(self.pl_profile)
        self.assertTrue(len(heatmap) >= 1)
        self.assertEqual(heatmap[0]["staff_name"], self.cceo2_user.name)

    def test_leave_budget_impact_sync(self):
        """Verify LeaveBudgetImpactService updates cost line planned periods and appends description trail."""
        # Setup activity schedule cost lines
        from apps.activities.models import ActivityScheduleCostLine

        act = Activity.objects.create(
            activity_type="school_visit",
            school=self.school2,
            responsible_staff_id=self.cceo2_user.id,
            scheduled_date="2026-10-05",
            delivery_type="staff",
            fy="2026",
            quarter="Q1",
        )
        line = ActivityScheduleCostLine.objects.create(
            activity=act,
            cost_setting_key="transport",
            label="Transport",
            unit_cost=100,
            quantity=1,
            amount=100,
            planned_date="2026-10-05",
            fiscal_year="2026",
            quarter="Q1",
        )
        from apps.hr.leave_services import LeaveBudgetImpactService

        LeaveBudgetImpactService.handle_reschedule(
            act, date(2026, 10, 5), date(2026, 10, 12), "holiday conflict"
        )

        line.refresh_from_db()
        self.assertEqual(line.planned_date, date(2026, 10, 12))
        self.assertIn("Audit: Rescheduled due to holiday conflict", line.description)

    def test_coverage_access_window(self):
        """Test coverage access window begins at 8:00 AM on start date and expires at 5:00 PM on end date."""
        # Request leave for CCEO-2 covering CCEO-1
        data = {
            "type": "personal_time_off",
            "start_date": "2026-10-08",
            "end_date": "2026-10-12",
            "covering_staff": self.cceo1_profile.id,
            "coverage_notes": "Call School Two if emergency",
            "emergency_contact": "Jane Doe +25670",
            "reason": "Family vacation",
        }
        leave = LeaveRequestService.request_leave(self.cceo2_profile, data)
        LeaveApprovalService.approve_request(leave.id, self.pl_user)

        assignment = TemporaryCoverageAssignment.objects.get(leave_request=leave)
        # Verify access window time bounds
        self.assertEqual(timezone.localtime(assignment.start_datetime).hour, 8)
        self.assertEqual(timezone.localtime(assignment.start_datetime).minute, 0)
        self.assertEqual(timezone.localtime(assignment.end_datetime).hour, 17)
        self.assertEqual(timezone.localtime(assignment.end_datetime).minute, 0)

    def test_approver_hierarchy_and_self_approval_protection(self):
        """Verify hierarchical approver scopes and block self-approvals."""
        # Request leave for CCEO-2
        data = {
            "type": "personal_time_off",
            "start_date": "2026-10-08",
            "end_date": "2026-10-12",
            "covering_staff": self.cceo1_profile.id,
            "reason": "PTO",
        }
        leave = LeaveRequestService.request_leave(self.cceo2_profile, data)

        # 1. Self-approval should be rejected
        from apps.core.exceptions import BadRequest

        with self.assertRaises(BadRequest):
            LeaveApprovalService.approve_request(leave.id, self.cceo2_user)

        # 2. Scope checks
        # Supervising PL is authorized
        is_auth = LeaveApprovalService.is_authorized_approver(self.pl_user, leave)
        self.assertTrue(is_auth)

        # CCEO One is NOT authorized (not supervisor, wrong role)
        is_auth_cceo1 = LeaveApprovalService.is_authorized_approver(
            self.cceo1_user, leave
        )
        self.assertFalse(is_auth_cceo1)

    def test_out_of_scope_approver_protection(self):
        """Verify supervisor cannot approve a leave request outside their authorized reporting scope."""
        # Create another PL who does not supervise CCEO-2
        pl2_user = User.objects.create_user(
            email="pl2@edify.test",
            name="PL Two",
            roles=["ProgramLead"],
            active_role="ProgramLead",
            password="x",
            is_active=True,
        )
        pl2_profile = StaffProfile.objects.create(user=pl2_user, staff_number="SP-999")

        data = {
            "type": "personal_time_off",
            "start_date": "2026-10-08",
            "end_date": "2026-10-12",
            "covering_staff": self.cceo1_profile.id,
            "reason": "PTO",
        }
        leave = LeaveRequestService.request_leave(self.cceo2_profile, data)

        # PL2 is not the supervisor -> should raise BadRequest
        from apps.core.exceptions import BadRequest

        with self.assertRaises(BadRequest):
            LeaveApprovalService.approve_request(leave.id, pl2_user)

    def test_review_leave_endpoint_blocks_self_approval(self):
        """apps.hr.services.review_leave backs the parallel, network-reachable
        /api/hr/leave/<id>/approve|reject endpoints. It must block self-
        approval the same way the main LeaveApprovalService path does,
        instead of relying on LEAVE_PLANNER_VIEW alone."""
        from apps.hr.services import review_leave
        from apps.core.exceptions import BadRequest

        hr_user = User.objects.create_user(
            email="hr_reviewer@edify.test",
            name="HR Staffer",
            roles=["HumanResources"],
            active_role="HumanResources",
            password="x",
            is_active=True,
        )
        hr_profile = StaffProfile.objects.create(user=hr_user, staff_number="SP-HR-1")
        LeaveBalanceService.initialize_balances_for_staff(hr_profile, 2026)

        leave = LeaveRequestService.request_leave(
            hr_profile,
            {
                "type": "personal_time_off",
                "start_date": "2026-10-08",
                "end_date": "2026-10-08",
                "reason": "Self-approval attempt",
            },
        )

        with self.assertRaises(BadRequest):
            review_leave(leave.id, "approved", hr_user)

        leave.refresh_from_db()
        self.assertEqual(leave.status, "pending")

    def test_review_leave_endpoint_blocks_out_of_hierarchy_approval(self):
        """review_leave must reject a reviewer who holds LEAVE_PLANNER_VIEW
        (e.g. HR) but has no supervisory authority over the leave owner —
        previously this endpoint let ANY LEAVE_PLANNER_VIEW holder approve
        or reject ANY leave regardless of hierarchy."""
        from apps.hr.services import review_leave
        from apps.core.exceptions import BadRequest

        hr_user = User.objects.create_user(
            email="hr_reviewer2@edify.test",
            name="HR Staffer Two",
            roles=["HumanResources"],
            active_role="HumanResources",
            password="x",
            is_active=True,
        )

        data = {
            "type": "personal_time_off",
            "start_date": "2026-10-08",
            "end_date": "2026-10-12",
            "covering_staff": self.cceo1_profile.id,
            "reason": "PTO",
        }
        leave = LeaveRequestService.request_leave(self.cceo2_profile, data)

        # HR holds LEAVE_PLANNER_VIEW but is not CCEO-2's supervising PL.
        with self.assertRaises(BadRequest):
            review_leave(leave.id, "approved", hr_user)

        leave.refresh_from_db()
        self.assertEqual(leave.status, "pending")

    def test_review_leave_endpoint_allows_authorized_supervisor(self):
        """review_leave must still let the correctly-scoped supervisor (PL)
        approve/reject through this endpoint."""
        from apps.hr.services import review_leave

        data = {
            "type": "personal_time_off",
            "start_date": "2026-10-08",
            "end_date": "2026-10-12",
            "covering_staff": self.cceo1_profile.id,
            "reason": "PTO",
        }
        leave = LeaveRequestService.request_leave(self.cceo2_profile, data)

        result = review_leave(leave.id, "approved", self.pl_user)
        self.assertEqual(result["status"], "approved")
        leave.refresh_from_db()
        self.assertEqual(leave.status, "approved")

    def test_coverage_status_transitions(self):
        """Verify coverage accept/decline state transitions."""
        data = {
            "type": "personal_time_off",
            "start_date": "2026-10-08",
            "end_date": "2026-10-12",
            "covering_staff": self.cceo1_profile.id,
            "reason": "PTO",
        }
        leave = LeaveRequestService.request_leave(self.cceo2_profile, data)
        self.assertEqual(leave.coverage_status, "Awaiting Acceptance")

        # 1. Decline coverage
        LeaveApprovalService.decline_coverage(leave.id, self.cceo1_user)
        leave.refresh_from_db()
        self.assertEqual(leave.coverage_status, "Declined")

        # 2. Accept coverage
        LeaveApprovalService.accept_coverage(leave.id, self.cceo1_user)
        leave.refresh_from_db()
        self.assertEqual(leave.coverage_status, "Accepted")

        # 3. Approve request by PL -> transitions coverage to Approved
        LeaveApprovalService.approve_request(leave.id, self.pl_user)
        leave.refresh_from_db()
        self.assertEqual(leave.coverage_status, "Approved")
        self.assertEqual(leave.status, "approved")

    def test_leave_views_render(self):
        """Test rendering the leave approvals page and the leave impact partial."""
        # Create a leave request
        data = {
            "type": "personal_time_off",
            "start_date": "2026-10-08",
            "end_date": "2026-10-12",
            "covering_staff": self.cceo1_profile.id,
            "reason": "PTO",
        }
        leave = LeaveRequestService.request_leave(self.cceo2_profile, data)

        # Login as PL supervisor
        self.client.force_login(self.pl_user)

        # Request full page
        response = self.client.get(f"/leave/approvals/?id={leave.id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["kpis"]["pending"], 1)
        self.assertContains(response, "0% of pending requests")
        self.assertNotContains(response, "88% of requests")
        self.assertNotContains(response, "2 this wk")
        self.assertNotContains(response, "3 from last wk")

        # Request partial view
        response_partial = self.client.get(f"/leave/approvals/{leave.id}/impact/")
        self.assertEqual(response_partial.status_code, 200)

    def test_requires_attachment_policy_enforced_server_side(self):
        """LeaveTypePolicy.requires_attachment (sick_leave=True in this
        setUp) was previously only enforced by client-side JS. Submitting
        directly to the service without an attachment must now be rejected
        server-side, and providing one must succeed."""
        from apps.core.exceptions import BadRequest

        data = {
            "type": "sick_leave",
            "start_date": "2026-10-08",
            "end_date": "2026-10-08",
            "reason": "Flu",
        }
        with self.assertRaises(BadRequest):
            LeaveRequestService.request_leave(
                self.cceo2_profile, data, attachment_file=None
            )

        # Confirm no orphaned Leave row was created by the rejected attempt.
        self.assertFalse(
            Leave.objects.filter(staff=self.cceo2_profile, type="sick_leave").exists()
        )

        from django.core.files.uploadedfile import SimpleUploadedFile

        note = SimpleUploadedFile(
            "doctor_note.pdf", b"%PDF-1.4 fake", content_type="application/pdf"
        )
        leave = LeaveRequestService.request_leave(
            self.cceo2_profile, data, attachment_file=note
        )
        self.assertEqual(leave.type, "sick_leave")

    def test_expired_coverage_assignment_not_shown_as_active(self):
        """A TemporaryCoverageAssignment whose window closed months ago keeps
        status="active" forever (nothing transitions it to "expired"). The
        Personal Time Off page, its KPI count, and the Leave Tracker's
        coverages list must all exclude it via the datetime window, matching
        the pattern already used for authorization in
        apps.core.permissions / apps.core.scoping."""
        past_leave = Leave.objects.create(
            staff=self.cceo2_profile,
            type="personal_time_off",
            start_date="2026-01-05",
            end_date="2026-01-09",
            days=5,
            status="approved",
            covering_staff=self.cceo1_profile,
        )
        stale_assignment = TemporaryCoverageAssignment.objects.create(
            leave_request=past_leave,
            original_staff=self.cceo2_profile,
            covering_staff=self.cceo1_profile,
            start_datetime=timezone.make_aware(datetime(2026, 1, 5, 8, 0)),
            end_datetime=timezone.make_aware(datetime(2026, 1, 9, 17, 0)),
            status="active",
        )
        self.assertEqual(stale_assignment.status, "active")

        # Personal Time Off page (cceo1 is the covering_staff -> my_coverages).
        self.client.force_login(self.cceo1_user)
        pto_response = self.client.get("/personal-time-off")
        self.assertEqual(pto_response.status_code, 200)
        self.assertNotIn(
            stale_assignment.id, [c.id for c in pto_response.context["my_coverages"]]
        )
        self.assertEqual(pto_response.context["coverage_active_count"], 0)

        # Leave Tracker (HR/PL/CD/RVP/Admin audience).
        self.client.force_login(self.pl_user)
        tracker_response = self.client.get("/leave/tracker")
        self.assertEqual(tracker_response.status_code, 200)
        self.assertNotIn(
            stale_assignment.id, [c.id for c in tracker_response.context["coverages"]]
        )


class LeaveCoveragePagePermissionTest(APITestCase):
    """Scoping gap regression: apps.hr.leave_services.CoverageAssignmentService
    .get_eligible_coverage_staff explicitly builds IA<->IA / IA<->CD coverage
    candidates, but the /leave/coverage page permission table
    (apps.core.navigation.PAGE_PERMISSIONS) excluded ImpactAssessment, so an
    IA staffer covering a colleague could never reach the page to see or
    manage that coverage assignment."""

    def setUp(self):
        self.ia_user = User.objects.create_user(
            email="ia_coverage@edify.test",
            name="IA Staffer",
            roles=["ImpactAssessment"],
            active_role="ImpactAssessment",
            password="x",
            is_active=True,
        )
        StaffProfile.objects.create(user=self.ia_user, staff_number="SP-IA-1")

    def test_ia_role_can_access_leave_coverage_page(self):
        self.client.force_login(self.ia_user)
        response = self.client.get("/leave/coverage")
        self.assertEqual(response.status_code, 200)
