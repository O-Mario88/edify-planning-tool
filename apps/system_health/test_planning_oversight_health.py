"""The health checks behind planning oversight.

Each of these describes a way the pages could be quietly wrong. A page that
crashes gets fixed today; a country budget short by one team's cost lines gets
believed, so these are the checks that matter most and they are tested for both
directions — firing when the condition is real, silent when it is not.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment, User
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.partners.models import Partner, PartnerAssignment
from apps.schools.models import School
from apps.system_health import planning_oversight_health as health


class HealthFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fy = get_operational_fy()
        cls.region = Region.objects.create(id="r1", name="Central")
        cls.district = District.objects.create(
            id="d1", name="Kampala", region=cls.region
        )
        cls.school = School.objects.create(
            school_id="s1", name="Alpha", district=cls.district, region=cls.region
        )
        cls.partner = Partner.objects.create(name="Partner X", active_status=True)

        cls.pl_user = User.objects.create(
            email="pl@h.test",
            name="Lead",
            roles=[EdifyRole.COUNTRY_PROGRAM_LEAD.value],
            active_role=EdifyRole.COUNTRY_PROGRAM_LEAD.value,
            is_active=True,
        )
        cls.pl = StaffProfile.objects.create(user=cls.pl_user, title="Lead")
        cls.cceo_user = User.objects.create(
            email="c@h.test",
            name="James",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            is_active=True,
        )
        cls.cceo = StaffProfile.objects.create(user=cls.cceo_user, title="CCEO")
        StaffSupervisorAssignment.objects.create(supervisee=cls.cceo, supervisor=cls.pl)

    def _activity(self, **overrides):
        defaults = dict(
            activity_type="school_visit",
            school=self.school,
            fy=self.fy,
            quarter="Q1",
            planned_date=date.today() + timedelta(days=3),
            status="scheduled",
            responsible_staff_id=self.cceo.id,
        )
        defaults.update(overrides)
        return Activity.objects.create(**defaults)

    def check(self, key) -> dict:
        return next(c for c in health.report()["checks"] if c["key"] == key)


class CleanSystemTest(HealthFixture):
    def test_a_healthy_plan_reports_clean(self):
        activity = self._activity()
        ActivityScheduleCostLine.objects.create(
            activity=activity,
            cost_setting_key="k",
            label="Transport",
            unit_cost=1000,
            quantity=1,
            amount=1000,
        )

        report = health.report()

        self.assertTrue(report["clean"], report["checks"])
        self.assertEqual(report["issueCount"], 0)


class DoubleCountingTest(HealthFixture):
    def test_an_unscheduled_assignment_carrying_cost_is_an_error(self):
        """The condition that would inflate a plan with uncommitted money."""
        activity = self._activity(status="partner_scheduled")
        ActivityScheduleCostLine.objects.create(
            activity=activity,
            cost_setting_key="k",
            label="Transport",
            unit_cost=50_000,
            quantity=1,
            amount=50_000,
        )
        PartnerAssignment.objects.create(
            school=self.school,
            partner=self.partner,
            monitoring_staff_id=self.cceo.id,
            status="assigned",
            scheduled_activity=activity,
        )

        finding = self.check("assignment_costed_before_scheduling")

        self.assertEqual(finding["count"], 1)
        self.assertEqual(finding["severity"], "error")
        self.assertIn("UGX 50,000", finding["examples"][0]["actual"])

    def test_a_scheduled_assignment_with_no_linked_activity_is_reported(self):
        PartnerAssignment.objects.create(
            school=self.school,
            partner=self.partner,
            monitoring_staff_id=self.cceo.id,
            status="partner_scheduled",
        )

        finding = self.check("assignment_missing_scheduled_activity")

        self.assertEqual(finding["count"], 1)
        self.assertIn("repair_partner_assignment_links", finding["route"])


class AttributionTest(HealthFixture):
    def test_work_with_no_owner_is_an_error(self):
        self._activity(responsible_staff_id=None, monitored_by_staff_id=None)

        finding = self.check("activity_without_owner")

        self.assertEqual(finding["count"], 1)
        self.assertEqual(finding["severity"], "error")

    def test_an_owner_with_no_supervisor_is_reported(self):
        orphan_user = User.objects.create(
            email="orphan@h.test",
            name="Orphan",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            is_active=True,
        )
        orphan = StaffProfile.objects.create(user=orphan_user, title="CCEO")
        self._activity(responsible_staff_id=orphan.id)

        finding = self.check("owner_without_supervisor")

        self.assertEqual(finding["count"], 1)
        self.assertIn("Unassigned", finding["examples"][0]["actual"])

    def test_work_owned_by_a_never_activated_account_is_its_own_finding(self):
        """The two need opposite fixes, so they must not be one finding.

        An invited account that was never activated cannot sign in, upload
        evidence or act on an action sent to it. Giving it a supervisor would
        turn the report green and leave the work exactly as stuck.
        """
        invited = User.objects.create(
            email="pending.someone@h.test",
            name="Never Activated",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            is_active=False,
            status="pending_invited",
        )
        profile = StaffProfile.objects.create(user=invited, title="CCEO")
        self._activity(responsible_staff_id=profile.id)

        onboarding = self.check("owner_never_onboarded")
        supervisor = self.check("owner_without_supervisor")

        self.assertEqual(onboarding["count"], 1)
        self.assertEqual(onboarding["severity"], "error")
        self.assertIn("never activated", onboarding["examples"][0]["actual"])
        self.assertIn("staff-setup-queue", onboarding["route"])
        self.assertEqual(
            supervisor["count"],
            0,
            "an unactivated account must not also be reported as unsupervised",
        )

    def test_an_active_owner_missing_a_line_is_still_reported(self):
        """Excluding dormant accounts must not silence the real gap."""
        active = User.objects.create(
            email="active@h.test",
            name="Active No Lead",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            is_active=True,
        )
        profile = StaffProfile.objects.create(user=active, title="CCEO")
        self._activity(responsible_staff_id=profile.id)

        self.assertEqual(self.check("owner_without_supervisor")["count"], 1)
        self.assertEqual(self.check("owner_never_onboarded")["count"], 0)

    def test_a_supervised_owner_is_not_reported(self):
        self._activity()

        self.assertEqual(self.check("owner_without_supervisor")["count"], 0)


class CostTest(HealthFixture):
    def test_scheduled_work_with_no_cost_is_reported(self):
        self._activity()

        finding = self.check("scheduled_without_cost")

        self.assertEqual(finding["count"], 1)
        self.assertIn("risk=scheduled_without_cost", finding["route"])


class FindingShapeTest(HealthFixture):
    def test_every_finding_says_what_was_expected_and_where_to_fix_it(self):
        self._activity(responsible_staff_id=None, monitored_by_staff_id=None)

        for finding in health.report()["checks"]:
            with self.subTest(check=finding["key"]):
                self.assertTrue(finding["label"])
                self.assertTrue(finding["expected"])
                self.assertTrue(finding["route"])
                self.assertIn(finding["severity"], ("error", "warning"))


class AuditCommandTest(HealthFixture):
    def test_the_audit_reports_without_writing(self):
        from io import StringIO

        from django.core.management import call_command

        PartnerAssignment.objects.create(
            school=self.school,
            partner=self.partner,
            monitoring_staff_id=self.cceo.id,
            status="partner_scheduled",
        )

        out = StringIO()
        call_command("audit_planning_oversight", stdout=out)
        output = out.getvalue()

        self.assertIn("HISTORICAL DATA AUDIT", output)
        self.assertIn("Manual review required", output)
        self.assertIn("nothing written", output)
        self.assertTrue(
            PartnerAssignment.objects.filter(scheduled_activity__isnull=True).exists()
        )
