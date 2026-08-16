"""Audit 2026-08 — dynamic reproductions of the two severe findings.

These are written as the audit's *evidence*, so each one states the platform
law it tests and fails loudly when the law is broken. They are kept after
remediation as the regression contract.

AUD-004 (Critical, separation of duties): the Admin role must not be able to
verify work and release money for the same activity. `ADMIN_EXCLUDED_PERMISSIONS`
(apps/core/rbac.py) removes `ia.verify` and `payment.act` from Admin and the DRF
layer honours it — but the HTMX/page layer gates on role membership
(`active_role in ("Accountant", "Admin")`, `can_verify_ia -> role in [...,"Admin"]`),
so the exclusion was enforced on one door and not the other.

AUD-005 (High, partner work must never become personal staff achievement): the
personal ledger excludes partner-delivered activities explicitly
(apps/targets/my_targets.py), but the milestone/Uganda-cascade engine credits
any rule whose `required_executor_type` is blank — 45 of 51 seeded rules — so a
partner delivery could book as a named CCEO's verified achievement.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity
from apps.core.permissions import RolePermissionService
from apps.core.rbac import ADMIN_EXCLUDED_PERMISSIONS, Permission
from apps.geography.models import District, Region
from apps.schools.models import School


def _admin() -> User:
    user = User.objects.create(
        id="audit-admin-1",
        email="audit-admin@edify.org",
        name="Audit Admin",
        roles=["Admin"],
        active_role="Admin",
        is_active=True,
    )
    StaffProfile.objects.create(id="audit-admin-sp", user=user, title="Administrator")
    return user


class AdminSeparationOfDutiesTest(TestCase):
    """AUD-004: the excluded authorities must be unreachable, not merely unlisted."""

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Audit SoD Region")
        cls.district = District.objects.create(
            name="Audit SoD District", region=cls.region
        )
        cls.school = School.objects.create(
            school_id="SCH-AUDIT-SOD-1",
            name="Audit SoD Primary",
            region=cls.region,
            district=cls.district,
        )

    def setUp(self):
        self.admin = _admin()

    def _activity_awaiting_ia(self) -> Activity:
        return Activity.objects.create(
            activity_type="school_visit",
            delivery_type="staff",
            status="awaiting_ia_verification",
            school=self.school,
            responsible_staff_id="audit-field-staff",
            planned_date=date.today(),
            scheduled_date=timezone.now(),
            fy="2027",
            salesforce_activity_id="VS-AUDIT-1",
        )

    def test_the_exclusion_set_still_names_the_two_authorities(self):
        self.assertIn(Permission.IA_VERIFY, ADMIN_EXCLUDED_PERMISSIONS)
        self.assertIn(Permission.PAYMENT_ACT, ADMIN_EXCLUDED_PERMISSIONS)

    def test_admin_cannot_verify_an_activity(self):
        """The authority `ia.verify` is excluded from Admin, so every door that
        performs verification must refuse Admin — not only the DRF one."""
        activity = self._activity_awaiting_ia()

        self.assertFalse(
            RolePermissionService.can_verify_ia(self.admin, activity),
            "can_verify_ia admitted Admin: the page layer is gating on role "
            "membership instead of the ia.verify permission key",
        )

        self.client.force_login(self.admin)
        response = self.client.post(
            f"/ia/verification/{activity.id}/verify",
            {
                "evidence_exists": "on",
                "attendance_valid": "on",
                "correct_school": "on",
                "sf_id_entered": "on",
                "duplicate_check_passed": "on",
            },
        )
        activity.refresh_from_db()
        self.assertEqual(
            activity.status,
            "awaiting_ia_verification",
            f"Admin verified the activity (HTTP {response.status_code}); "
            "separation of duties is broken at the HTMX door",
        )

    def test_admin_cannot_reach_the_disbursement_action(self):
        """`payment.act` is excluded from Admin, so the money-moving endpoints
        must refuse it. Reading the queue is fine; releasing money is not."""
        self.client.force_login(self.admin)
        response = self.client.post(
            "/finance/actions/disburse_advance",
            {"request_id": "nonexistent", "amount": "1000", "method": "mobile_money"},
        )
        self.assertEqual(
            response.status_code,
            403,
            "the disburse endpoint admitted Admin (expected 403 from the "
            "payment.act gate)",
        )


class OperatorSuppliedNamesCannotRunScriptTest(TestCase):
    """AUD-006: a school name is operator input and must never reach an
    executable position.

    The map serialised school/district names with `json.dumps` into a
    `{{ ...|safe }}` slot inside a <script> block. `json.dumps` does not escape
    `</script>`, `|safe` disables autoescaping, and the platform CSP allows
    `'unsafe-inline'` — so a school named with a closing script tag executed in
    the browser of everyone who opened the map. With CSRF_COOKIE_HTTPONLY=False
    that script could read the token and act as the viewer.
    """

    PAYLOAD = '</script><img src=x onerror="window.__xss=1">'

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Audit XSS Region")
        cls.district = District.objects.create(
            name="Audit XSS District", region=cls.region
        )
        School.objects.create(
            school_id="SCH-AUDIT-XSS-1",
            name=cls.PAYLOAD,
            region=cls.region,
            district=cls.district,
            latitude=0.31,
            longitude=32.58,
        )

    def test_a_hostile_school_name_cannot_close_the_script_block(self):
        user = User.objects.create(
            id="audit-map-viewer",
            email="audit-map@edify.org",
            name="Audit Map Viewer",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            is_active=True,
        )
        StaffProfile.objects.create(id="audit-map-sp", user=user, title="CD")
        self.client.force_login(user)

        response = self.client.get("/map")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()

        self.assertNotIn(
            "</script><img",
            body,
            "an operator-supplied school name closed the script block — the "
            "map payload is back on |safe instead of json_script",
        )
        # The school must still be on the page, escaped — otherwise this test
        # would pass on a page that simply stopped rendering any points.
        self.assertIn("school-map-points", body)
        self.assertIn(
            "\\u003C/script\\u003E",
            body,
            "the hostile name never reached the page, so this test proves "
            "nothing about escaping",
        )


class PartnerWorkNeverCreditsStaffTest(TestCase):
    """AUD-005: partner delivery is Partner Contribution, never staff credit."""

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Audit Partner Region")
        cls.district = District.objects.create(
            name="Audit Partner District", region=cls.region
        )
        cls.school = School.objects.create(
            school_id="SCH-AUDIT-PARTNER-1",
            name="Audit Partner Primary",
            region=cls.region,
            district=cls.district,
        )

    def test_a_partner_activity_earns_no_milestone_credit_for_the_named_staff(self):
        from apps.hr.milestone_progress import record_activity_progress
        from apps.hr.models import (
            MilestoneActivityRule,
            MilestoneAllocation,
            MilestonePeriodTarget,
            PriorityMilestone,
            StrategicPriority,
            StrategicPriorityCycle,
        )

        from apps.activity_catalogue.models import ActivityCatalogueItem

        # The reference-data receiver already publishes the live cycles, so
        # reuse rather than collide with the unique financial_year.
        cycle, _ = StrategicPriorityCycle.objects.get_or_create(
            financial_year="2027",
            defaults={"title": "Audit cycle", "country_id": "Uganda"},
        )
        priority = StrategicPriority.objects.create(
            cycle=cycle,
            fy="2027",
            level="country",
            title="Audit partner-credit guard",
            strategic_purpose="Prove partner work never credits staff",
            country_id="Uganda",
        )
        # A DB constraint (active_milestone_must_be_defined) requires an
        # active milestone to carry an approved metric definition.
        from apps.hr.models import MilestoneDefinitionStatus, MilestoneMetricDefinition

        definition = MilestoneMetricDefinition.objects.create(
            metric_key="audit_schools_supported",
            canonical_label="Audit schools supported",
        )
        milestone = PriorityMilestone.objects.create(
            priority=priority,
            metric_definition=definition,
            definition_status=MilestoneDefinitionStatus.APPROVED,
            requires_definition=False,
            code="AUDIT_PARTNER_MILESTONE",
            title="Schools supported",
            source_text="Audit fixture",
            milestone_type="output",
            measurement_type="count",
            progress_source="activity",
            target_value=100,
            target_unit="schools",
            # active defaults to False; the credit engine filters on
            # milestone__active=True, so without this the fixture would never
            # reach the code under test.
            active=True,
        )
        item = ActivityCatalogueItem.objects.create(
            stable_code="AUDIT_PARTNER_ITEM",
            source_name="Audit partner item",
            display_name="Audit partner item",
            activity_type="school_visit",
            delivery_method="school_visit",
            workflow_kind="school_visit",
            status="active",
            partner_delivery_allowed=True,
            salesforce_record_type="VISIT",
            salesforce_expected_prefix="VS-",
            evidence_profile="SCHOOL_VISIT_FORM",
            costing_profile="STAFF_SCHOOL_VISIT",
        )
        # A rule with NO required_executor_type — the shape 45 of the 51
        # seeded rules have, which is what makes this reachable in production.
        MilestoneActivityRule.objects.create(
            milestone=milestone,
            catalogue_item=item,
            counting_basis="UNIQUE_SCHOOLS_SUPPORTED",
        )
        holder = User.objects.create(
            id="audit-cceo-1",
            email="audit-cceo@edify.org",
            name="Audit CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        profile = StaffProfile.objects.create(
            id="audit-cceo-sp", user=holder, title="CCEO"
        )
        today = date.today()
        allocation = MilestoneAllocation.objects.create(
            milestone=milestone,
            allocated_to_type="employee",
            employee=profile,
            allocated_target=10,
            allocation_reason="Audit fixture",
            allocated_by="audit",
            effective_date=today,
            status="approved",
        )
        period = MilestonePeriodTarget.objects.create(
            milestone=milestone,
            allocation=allocation,
            scope="employee",
            employee=profile,
            period_type="month",
            period_start=today.replace(day=1),
            period_end=today.replace(day=1) + timedelta(days=27),
            planned_value=1,
            actual_value=0,
        )

        partner_activity = Activity.objects.create(
            activity_type="school_visit",
            catalogue_item=item,
            delivery_type="partner",
            assigned_partner_id="audit-partner-org",
            # The trap: partner-delivered work still names the staff member
            # who owns the school (230 of 231 partner rows in dev do this).
            responsible_staff_id=profile.id,
            status="ia_verified",
            school=self.school,
            planned_date=today,
            scheduled_date=timezone.now(),
            fy="2027",
        )
        record_activity_progress(partner_activity)

        # The credit MUST exist: partner delivery is real programme work and
        # belongs in the country total. Asserting this first is what stops the
        # test passing tautologically — an earlier draft of this fixture left
        # the milestone inactive, so nothing matched and the "no personal
        # credit" assertion held for the wrong reason.
        from apps.hr.models import MilestoneProgressCredit

        self.assertTrue(
            MilestoneProgressCredit.objects.filter(activity=partner_activity).exists(),
            "the fixture never reached the credit engine, so this test proves "
            "nothing — check milestone.active and the catalogue item",
        )

        period.refresh_from_db()
        self.assertEqual(
            period.actual_value,
            0,
            "partner-delivered work was booked as this CCEO's personal "
            "verified achievement — the milestone engine is missing the "
            "partner exclusion the personal ledger enforces",
        )
