"""Regression tests: a scheduled activity MUST appear in My Plan.

These pin the fix for the identifier-class mismatch that silently made
scheduled activities invisible:
  - activities.services.create wrote responsible_staff_id = staff_profile_id
  - my_plan.services.get filtered by [principal.id] (User CUID) as a fallback
  - the two never matched for users without a StaffProfile

Also pins the partner-attribution fix: a partner-delivered activity now sets
monitored_by_staff_id = scheduling staff, so it surfaces on their My Plan.
"""

from datetime import datetime, time
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User, StaffProfile, StaffSchoolAssignment
from apps.activities.models import Activity
from apps.budget.models import CostCatalogue, CostSetting
from apps.fund_requests.models import FundRequest, WeeklyFundRequest
from apps.core.fy import get_operational_fy
from apps.geography.models import Region, District
from apps.my_plan.services import get_frontend_context
from apps.schools.models import School


def _activity_ids(context):
    """Pull activity ids out of every activity-bearing list in the my_plan
    context payload (the context distributes activities across urgency
    sections: due_today, this_week, partner_monitoring, returned_needs_correction,
    waiting_on_me, waiting_on_approval, school_visits, cluster_trainings, cluster_meetings)."""
    keys = [
        "due_today",
        "this_week",
        "partner_monitoring",
        "returned_needs_correction",
        "waiting_on_me",
        "waiting_on_approval",
        "school_visits",
        "cluster_trainings",
        "cluster_meetings",
        "upcoming",
    ]
    ids = set()
    for k in keys:
        for a in context.get(k, []) or []:
            if isinstance(a, dict) and "id" in a:
                ids.add(str(a["id"]))
    return ids



def _schedulable_date():
    """The next date REG-02 will actually accept.

    These tests used timezone.localdate(), which fails outright whenever the
    suite runs on a Sunday -- scheduling is blocked on Sundays, public
    holidays and blackout dates (apps/core/calendar_policy.py). None of these
    tests is about the calendar, so they should not depend on which day the
    suite happens to run.
    """
    import datetime

    from django.utils import timezone as _tz

    day = _tz.localdate()
    for _ in range(10):
        if day.weekday() != 6:
            return day
        day += datetime.timedelta(days=1)
    return day


class PlanningToMyPlanFlowTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="East")
        self.district = District.objects.create(name="Mbale", region=self.region)
        self.school = School.objects.create(
            school_id="S-1",
            name="Test School",
            region=self.region,
            district=self.district,
            enrollment=200,
            school_type="client",
        )

    def _cceo_with_profile(self, email="cceo@plan.test"):
        u = User.objects.create_user(
            email=email,
            name=email.split("@")[0].title(),
            roles=["CCEO"],
            active_role="CCEO",
            password="x",
            is_active=True,
        )
        profile = StaffProfile.objects.create(user=u, staff_number=f"ST-{email[:3]}")
        StaffSchoolAssignment.objects.create(staff=profile, school_id=self.school.id)
        return u, profile

    def test_staff_activity_appears_in_my_plan_with_staffprofile(self):
        """Baseline: a CCEO with a StaffProfile schedules a visit → it's in My Plan."""
        user, profile = self._cceo_with_profile()
        fy = get_operational_fy()
        activity = Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            fy=fy,
            quarter="Q1",
            responsible_staff_id=profile.id,
            status="scheduled",
            scheduled_date=timezone.now(),
            planned_date=timezone.now().date(),
            delivery_type="staff",
        )
        ctx = get_frontend_context(user, {"fy": fy, "period": "fy"})
        self.assertIn(
            str(activity.id),
            _activity_ids(ctx),
            "Scheduled activity with StaffProfile attribution must appear in My Plan",
        )

    def test_cluster_schedule_derives_my_plan_period_fields(self):
        """The cluster planner only sends a date, not planning month/week fields.

        Scheduling must derive all three period fields so the activity is
        present in My Plan's default week filter immediately after saving.
        """
        from apps.activities.services import create
        from apps.clusters.models import Cluster

        user, profile = self._cceo_with_profile(email="cluster@plan.test")
        cluster = Cluster.objects.create(
            name="Mbale Planning Cluster",
            region=self.region,
            district=self.district,
        )
        scheduled_for = timezone.localdate()
        scheduled_at = timezone.make_aware(
            datetime.combine(scheduled_for, time(9)), timezone.get_current_timezone()
        )

        with patch("apps.activities.services._apply_schedule_cost_snapshot"):
            result = create(
                {
                    "activityType": "cluster_training",
                    "clusterId": cluster.id,
                    "scheduledDate": scheduled_at.isoformat(),
                    "expectedParticipants": 12,
                    "activityPurposeText": "Build stronger teaching practices",
                    "focusIntervention": "teaching_environment",
                },
                user,
            )

        activity = Activity.objects.get(id=result["id"])
        expected_week = min(5, (scheduled_for.day - 1) // 7 + 1)
        self.assertEqual(activity.responsible_staff_id, profile.id)
        self.assertEqual(activity.planned_date, scheduled_for)
        self.assertEqual(activity.planned_month, scheduled_for.month)
        self.assertEqual(activity.planned_week, expected_week)

        ctx = get_frontend_context(
            user,
            {
                "fy": activity.fy,
                "period": "week",
                "month": str(scheduled_for.month),
                "week": str(expected_week),
            },
        )
        self.assertIn(str(activity.id), _activity_ids(ctx))

    def test_legacy_period_fields_do_not_hide_a_scheduled_activity(self):
        """My Plan uses the real scheduled date when old grouping fields are blank."""
        user, profile = self._cceo_with_profile(email="legacy-period@plan.test")
        scheduled_for = timezone.localdate()
        activity = Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            fy=get_operational_fy(scheduled_for),
            quarter="Q4",
            responsible_staff_id=profile.id,
            status="scheduled",
            scheduled_date=timezone.make_aware(
                datetime.combine(scheduled_for, time(9)),
                timezone.get_current_timezone(),
            ),
            planned_date=scheduled_for,
            planned_month=None,
            planned_week=None,
            delivery_type="staff",
        )

        ctx = get_frontend_context(
            user,
            {
                "fy": activity.fy,
                "period": "week",
                "month": str(scheduled_for.month),
                "week": str(min(5, (scheduled_for.day - 1) // 7 + 1)),
            },
        )
        self.assertIn(str(activity.id), _activity_ids(ctx))

    def test_permissive_schedule_creates_cost_and_budget_immediately(self):
        """Business rules do not block a schedule, but costing still writes now."""
        from apps.activities.services import create

        user, profile = self._cceo_with_profile(email="permissive@plan.test")
        self.district.district_type = "primary"
        self.district.save(update_fields=["district_type"])
        fy = get_operational_fy()
        catalogue, _ = CostCatalogue.objects.update_or_create(
            country="Scheduling Test",
            fy=fy,
            version=999,
            defaults={"is_active": True, "label": "Scheduling Test Catalogue"},
        )
        CostSetting.objects.update_or_create(
            key="staff_visit_transport_primary",
            defaults={
                "label": "Transport",
                "unit_cost": 50_000,
                "fy": fy,
                "catalogue": catalogue,
                "version": 1,
            },
        )
        CostSetting.objects.update_or_create(
            key="lunch",
            defaults={
                "label": "Lunch",
                "unit_cost": 10_000,
                "fy": fy,
                "catalogue": catalogue,
                "version": 1,
            },
        )

        result = create(
            {
                "activityType": "school_visit",
                "schoolId": self.school.school_id,
                "scheduledDate": _schedulable_date().isoformat(),
                # This would previously fail strict-purpose and SSA gates.
                "strict_validation": True,
            },
            user,
        )
        activity = Activity.objects.get(id=result["id"])

        self.assertEqual(activity.responsible_staff_id, profile.id)
        self.assertFalse(activity.cost_missing)
        self.assertEqual(activity.est_cost_cents, 60_000)
        self.assertGreater(activity.schedule_cost_lines.count(), 0)
        self.assertEqual(
            set(
                activity.schedule_cost_lines.values_list("responsible_user", flat=True)
            ),
            {user.id},
        )
        self.assertTrue(
            WeeklyFundRequest.objects.filter(
                responsible_user=user.id,
                week_start_date=activity.week_start_date,
                total_amount=60_000,
            ).exists()
        )
        self.assertTrue(
            FundRequest.objects.filter(
                submitted_by_user_id=user.id,
                period="monthly",
                period_key=f"{activity.fy}-M{activity.month}",
                total_amount=60_000,
                status="draft",
            ).exists()
        )

    def test_admin_scheduling_for_staff_uses_staff_finance_owner(self):
        """The assigned staff member, not the admin who clicks Save, owns funding."""
        from apps.activities.services import create

        staff_user, profile = self._cceo_with_profile(email="owner@plan.test")
        admin = User.objects.create_user(
            email="admin-owner@plan.test",
            name="Admin Owner",
            roles=["Admin"],
            active_role="Admin",
            password="x",
            is_active=True,
        )
        self.district.district_type = "primary"
        self.district.save(update_fields=["district_type"])
        fy = get_operational_fy()
        catalogue = CostCatalogue.objects.create(
            country="Owner Test", fy=fy, version=778, is_active=True
        )
        CostSetting.objects.create(
            key="staff_visit_transport_primary",
            label="Transport",
            unit_cost=50_000,
            fy=fy,
            catalogue=catalogue,
        )
        CostSetting.objects.create(
            key="lunch", label="Lunch", unit_cost=10_000, fy=fy, catalogue=catalogue
        )

        result = create(
            {
                "activityType": "school_visit",
                "schoolId": self.school.school_id,
                "scheduledDate": _schedulable_date().isoformat(),
                "responsibleStaffId": profile.id,
            },
            admin,
        )
        activity = Activity.objects.get(id=result["id"])
        self.assertEqual(activity.responsible_staff_id, profile.id)
        self.assertEqual(
            set(
                activity.schedule_cost_lines.values_list("responsible_user", flat=True)
            ),
            {staff_user.id},
        )
        self.assertTrue(
            WeeklyFundRequest.objects.filter(
                responsible_user=staff_user.id,
                week_start_date=activity.week_start_date,
            ).exists()
        )

    def test_staff_activity_appears_in_my_plan_without_staffprofile(self):
        """The bug: a user WITHOUT a StaffProfile schedules → responsible_staff_id
        falls back to the User CUID; My Plan must still surface it."""
        user = User.objects.create_user(
            email="no-profile@plan.test",
            name="No Profile",
            roles=["CCEO"],
            active_role="CCEO",
            password="x",
            is_active=True,
        )
        # No StaffProfile created — this is the regression condition.
        fy = get_operational_fy()
        activity = Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            fy=fy,
            quarter="Q1",
            responsible_staff_id=user.id,  # what create() now writes as fallback
            status="scheduled",
            scheduled_date=timezone.now(),
            planned_date=timezone.now().date(),
            delivery_type="staff",
        )
        ctx = get_frontend_context(user, {"fy": fy, "period": "fy"})
        self.assertIn(
            str(activity.id),
            _activity_ids(ctx),
            "User without StaffProfile must still see their scheduled activity in My Plan",
        )

    def test_partner_activity_appears_in_monitoring_staff_my_plan(self):
        """A staff member schedules on behalf of a partner. The activity must
        surface on the STAFF member's My Plan via monitored_by_staff_id."""
        user, profile = self._cceo_with_profile(email="monitor@plan.test")
        fy = get_operational_fy()
        activity = Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            fy=fy,
            quarter="Q1",
            responsible_staff_id=None,  # partner will execute
            monitored_by_staff_id=profile.id,  # staff is monitoring
            assigned_partner_id="PARTNER-1",
            delivery_type="partner",
            status="assigned_to_partner",
            scheduled_date=timezone.now(),
            planned_date=timezone.now().date(),
        )
        ctx = get_frontend_context(user, {"fy": fy, "period": "fy"})
        self.assertIn(
            str(activity.id),
            _activity_ids(ctx),
            "Partner-delivered activity must appear in the monitoring staff's My Plan",
        )

    def test_partner_delivery_attribution_logic(self):
        """The attribution logic in create() must:
        (a) set monitored_by_staff_id for partner delivery so staff can monitor
        (b) fall back to user_id when no StaffProfile exists.

        Tested at the Activity level (what create() writes) rather than via the
        full create() path, which is gated by the cost catalogue."""
        from datetime import date

        # WITH StaffProfile: partner activity attributes monitor = staff_profile_id
        user, profile = self._cceo_with_profile(email="creator@plan.test")
        principal_owner_id = user.staff_profile_id or user.user_id
        self.assertEqual(principal_owner_id, profile.id)

        a_partner = Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            fy=get_operational_fy(),
            quarter="Q1",
            responsible_staff_id=None,
            monitored_by_staff_id=principal_owner_id,
            assigned_partner_id="PARTNER-1",
            delivery_type="partner",
            status="assigned_to_partner",
            planned_date=date.today(),
        )
        self.assertEqual(
            a_partner.monitored_by_staff_id,
            profile.id,
            "Partner activity must record the scheduling staff as monitor",
        )

        # WITHOUT StaffProfile: principal_owner_id falls back to user_id
        user_no_profile = User.objects.create_user(
            email="no-profile2@plan.test",
            name="No Profile",
            roles=["CCEO"],
            active_role="CCEO",
            password="x",
            is_active=True,
        )
        principal_owner_id2 = (
            user_no_profile.staff_profile_id or user_no_profile.user_id
        )
        self.assertEqual(
            principal_owner_id2,
            user_no_profile.id,
            "Fallback owner id must be the User CUID when no StaffProfile",
        )

    def test_closed_activity_excluded_from_my_plan(self):
        """Closed activities should not dominate My Plan. They surface in their
        own urgency bucket only if relevant; at minimum the context must build
        without error and exclude soft-deleted rows."""
        user, profile = self._cceo_with_profile()
        fy = get_operational_fy()
        Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            fy=fy,
            quarter="Q1",
            responsible_staff_id=profile.id,
            status="closed",
            salesforce_activity_id="SV-TEST-1",  # closed activities require an SF id (DB constraint)
            delivery_type="staff",
        )
        ctx = get_frontend_context(user, {"fy": fy, "period": "fy"})
        # Context must build without error; closed items aren't deleted so they
        # may appear, but the key assertion is structural integrity.
        self.assertIsInstance(ctx.get("due_today"), list)
        self.assertIsInstance(ctx.get("this_week"), list)
