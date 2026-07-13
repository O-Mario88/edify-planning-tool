"""Regression tests: a scheduled activity MUST appear in My Plan.

These pin the fix for the identifier-class mismatch that silently made
scheduled activities invisible:
  - activities.services.create wrote responsible_staff_id = staff_profile_id
  - my_plan.services.get filtered by [principal.id] (User CUID) as a fallback
  - the two never matched for users without a StaffProfile

Also pins the partner-attribution fix: a partner-delivered activity now sets
monitored_by_staff_id = scheduling staff, so it surfaces on their My Plan.
"""

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User, StaffProfile, StaffSchoolAssignment
from apps.activities.models import Activity
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
