"""Regression tests for the My Plan "Submit for Review" action.

apps.frontend.views.my_plan_views.submit_for_review_action used to write
a.status = "submitted" — a value that does not exist anywhere in
apps.core.enums.ActivityStatus. That fake status then leaked into every
read-site written against it (evidence center tabs, IA queue filters,
next-action computation, etc). The fix routes to the real workflow states:
CCEO completions need PL review first (submitted_to_pl); everyone else's
routes straight to IA verification (awaiting_ia_verification) — mirroring
apps.activities.services.complete()'s existing role-based routing.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.activities.models import Activity
from apps.core.enums import ActivityStatus, ActivityType
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School

User = get_user_model()


class SubmitForReviewActionTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Submit Review Region")
        self.district = District.objects.create(
            name="Submit Review District", region=self.region
        )
        self.school = School.objects.create(
            school_id="SUB-SCH",
            name="Submit Review School",
            region=self.region,
            district=self.district,
        )

    def _make_activity(self, responsible_staff_id):
        return Activity.objects.create(
            school=self.school,
            delivery_type="staff",
            activity_type=ActivityType.SCHOOL_VISIT,
            status=ActivityStatus.COMPLETED,
            responsible_staff_id=responsible_staff_id,
            scheduled_date=timezone.now(),
            salesforce_activity_id="SV-SUBMIT-1",
        )

    def test_cceo_submission_routes_to_pl_review_not_a_fake_status(self):
        cceo = User.objects.create_user(
            email="cceo-submit@test.org",
            name="Submitting CCEO",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="password",
            is_active=True,
        )
        activity = self._make_activity(cceo.id)
        self.client.force_login(cceo)

        resp = self.client.post(f"/activities/{activity.id}/submit/action")
        self.assertIn(resp.status_code, (200, 302))

        activity.refresh_from_db()
        # Must be a real ActivityStatus member — the old code wrote the
        # literal string "submitted", which is not in this enum at all.
        self.assertIn(activity.status, ActivityStatus.values)
        self.assertEqual(activity.status, ActivityStatus.SUBMITTED_TO_PL)
        self.assertNotEqual(activity.status, "submitted")
        self.assertIsNone(activity.submitted_to_ia_at)

    def test_non_cceo_submission_routes_straight_to_ia_verification(self):
        pl = User.objects.create_user(
            email="pl-submit@test.org",
            name="Submitting Program Lead",
            roles=[EdifyRole.COUNTRY_PROGRAM_LEAD.value],
            active_role=EdifyRole.COUNTRY_PROGRAM_LEAD.value,
            password="password",
            is_active=True,
        )
        activity = self._make_activity(pl.id)
        self.client.force_login(pl)

        resp = self.client.post(f"/activities/{activity.id}/submit/action")
        self.assertIn(resp.status_code, (200, 302))

        activity.refresh_from_db()
        self.assertIn(activity.status, ActivityStatus.values)
        self.assertEqual(activity.status, ActivityStatus.AWAITING_IA_VERIFICATION)
        self.assertNotEqual(activity.status, "submitted")
        self.assertIsNotNone(activity.submitted_to_ia_at)

        # The real read-site consumer of this status: the IA verification
        # queue must now actually pick the activity up.
        ia = User.objects.create_user(
            email="ia-submit@test.org",
            name="Verifying IA",
            roles=[EdifyRole.IMPACT_ASSESSMENT.value],
            active_role=EdifyRole.IMPACT_ASSESSMENT.value,
            password="password",
            is_active=True,
        )
        self.client.force_login(ia)
        queue_resp = self.client.get("/ia/verification/")
        self.assertEqual(queue_resp.status_code, 200)
        self.assertContains(queue_resp, activity.id)


class ComputeNextActionPaymentStatusTest(TestCase):
    """Branch 8 of compute_next_action ("View Accounts Status") used to
    require payment_status == "pending" — a value that does not exist in
    apps.core.enums.PaymentStatus and that no code ever writes, so the CTA
    never fired. It must fire for the real pre-clearance states and must
    NOT swallow "disbursed", which belongs to branch 9's accountability CTA.
    """

    def setUp(self):
        self.region = Region.objects.create(name="CTA Region")
        self.district = District.objects.create(name="CTA District", region=self.region)
        self.school = School.objects.create(
            school_id="CTA-SCH",
            name="CTA School",
            region=self.region,
            district=self.district,
        )

    def _verified_activity(self, payment_status):
        return Activity.objects.create(
            school=self.school,
            delivery_type="staff",
            activity_type=ActivityType.SCHOOL_VISIT,
            status="ia_verified",
            ia_verification_status="confirmed",
            payment_status=payment_status,
            responsible_staff_id="cta-user",
            scheduled_date=timezone.now(),
        )

    def test_cta_fires_for_real_pre_clearance_payment_states(self):
        from apps.my_plan.services import compute_next_action

        today = timezone.now().date()
        for state in ("none", "pending_ia", "ia_confirmed"):
            action = compute_next_action(self._verified_activity(state), today)
            self.assertEqual(action["text"], "View Accounts Status", state)

    def test_disbursed_state_is_left_to_the_accountability_branch(self):
        from apps.my_plan.services import compute_next_action

        today = timezone.now().date()
        action = compute_next_action(self._verified_activity("disbursed"), today)
        self.assertNotEqual(action.get("text"), "View Accounts Status")


class MyPlanOwnerNameDisplayTest(TestCase):
    """The My Plan feed's owner/assigned-by display fields used to look up
    Activity.responsible_staff_id in a map keyed only by User.id — but that
    field dominantly holds a StaffProfile CUID (an independent id space), so
    staff-conducted activities silently rendered the generic "Staff" instead
    of the real staff member's name."""

    def setUp(self):
        from apps.accounts.models import StaffProfile

        self.region = Region.objects.create(name="Owner Name Region")
        self.district = District.objects.create(
            name="Owner Name District", region=self.region
        )
        self.school = School.objects.create(
            school_id="OWN-SCH",
            name="Owner Name School",
            region=self.region,
            district=self.district,
        )
        self.cceo = User.objects.create_user(
            email="owner-name-cceo@test.org",
            name="Odette Ownername",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="password",
            is_active=True,
        )
        self.cceo_sp = StaffProfile.objects.create(user=self.cceo, title="CCEO")

    def test_owner_resolves_real_name_from_staff_profile_id(self):
        from apps.my_plan.services import get_frontend_context

        # localdate, not timezone.now().date(): get_frontend_context's own
        # "today" is date.today() (server-local, Africa/Kampala/EAT) --
        # timezone.now() is UTC, which is a different calendar date from
        # 21:00-24:00 UTC (00:00-03:00 EAT) every night.
        today = timezone.localdate()
        from apps.core.fy import get_operational_fy

        Activity.objects.create(
            school=self.school,
            delivery_type="staff",
            activity_type=ActivityType.SCHOOL_VISIT,
            status="scheduled",
            fy=get_operational_fy(),
            responsible_staff_id=self.cceo_sp.id,  # StaffProfile CUID, the dominant case
            planned_date=today,
            scheduled_date=timezone.now(),
        )
        ctx = get_frontend_context(self.cceo, {})
        # upcoming_today's staff-name field shares the same users_map all
        # three display sites read (owner / assigned_by / assigned_partner).
        names = {item.get("assigned_partner") for item in ctx["upcoming_today"]}
        self.assertIn("Odette Ownername", names)
        self.assertNotIn("Staff", names)

    def test_owner_still_resolves_for_raw_user_id_fallback(self):
        """activities.services.create() falls back to the raw User id only
        when the principal has no StaffProfile — model exactly that case."""
        from apps.my_plan.services import get_frontend_context

        today = timezone.localdate()
        from apps.core.fy import get_operational_fy

        no_profile_user = User.objects.create_user(
            email="owner-noprofile@test.org",
            name="Nora Noprofile",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="password",
            is_active=True,
        )
        Activity.objects.create(
            school=self.school,
            delivery_type="staff",
            activity_type=ActivityType.SCHOOL_VISIT,
            status="scheduled",
            fy=get_operational_fy(),
            responsible_staff_id=no_profile_user.id,
            planned_date=today,
            scheduled_date=timezone.now(),
        )
        ctx = get_frontend_context(no_profile_user, {})
        names = {item.get("assigned_partner") for item in ctx["upcoming_today"]}
        self.assertIn("Nora Noprofile", names)
