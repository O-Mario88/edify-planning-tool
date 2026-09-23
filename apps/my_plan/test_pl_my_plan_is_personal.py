"""My Plan is a personal operating list, not a team queue.

A Program Lead's My Plan must contain the work they will personally do. The
moment a supervised CCEO's activity or a partner's delivery appears in it, the
list stops being a plan and becomes a monitoring dashboard the PL cannot act
on — and team oversight already has its own page.

Partner delivery is never on a staff member's My Plan (owner, 2026-09-23), not
even for the managing staff: the Partner executes it, and staff follow it on
Partner Monitoring — where the managing staff's one task on it, entering the
Salesforce id, is offered on the row. The earlier carve-out that put it on the
manager's list returns only while the Partner-supported school rule is off.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import Activity
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.my_plan import services as my_plan
from apps.partners.models import Partner, PartnerAssignment
from apps.schools.models import School


class PlMyPlanTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fy = get_operational_fy()
        cls.region = Region.objects.create(id="r1", name="Central")
        cls.district = District.objects.create(
            id="d1", name="Kampala", region=cls.region
        )
        cls.pl_user, cls.pl = cls._staff(
            "pl@mp.test", "Mary", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        cls.cceo_user, cls.cceo = cls._staff("james@mp.test", "James", EdifyRole.CCEO)
        StaffSupervisorAssignment.objects.create(supervisee=cls.cceo, supervisor=cls.pl)

        cls.school = School.objects.create(
            school_id="s1", name="School A", district=cls.district, region=cls.region
        )
        StaffSchoolAssignment.objects.create(staff=cls.cceo, school_id=cls.school.id)
        cls.partner = Partner.objects.create(name="Partner X", active_status=True)

    @classmethod
    def _staff(cls, email, name, role):
        user = User.objects.create(
            email=email,
            name=name,
            roles=[role.value],
            active_role=role.value,
            is_active=True,
        )
        return user, StaffProfile.objects.create(user=user, title=name)

    def _activity(self, **overrides):
        planned = date.today() + timedelta(days=4)
        defaults = dict(
            activity_type="school_visit",
            school=self.school,
            fy=self.fy,
            quarter="Q1",
            planned_date=planned,
            planned_month=planned.month,
            status="scheduled",
        )
        defaults.update(overrides)
        return Activity.objects.create(**defaults)

    def plan_ids(self, user) -> set[str]:
        result = my_plan.get(user, {"period": "fy", "fy": self.fy})
        rows = result.get("activities") or result.get("items") or []
        return {row.get("id") for row in rows}

    def test_the_program_lead_sees_their_own_scheduled_work(self):
        mine = self._activity(responsible_staff_id=self.pl.id)

        self.assertIn(mine.id, self.plan_ids(self.pl_user))

    def test_a_supervised_cceos_activity_is_not_in_the_program_leads_plan(self):
        theirs = self._activity(responsible_staff_id=self.cceo.id)

        self.assertNotIn(theirs.id, self.plan_ids(self.pl_user))

    def test_the_my_plan_page_holds_no_supervised_work_either(self):
        """The page's own builder, not only the API feed: it used to add the
        lead's supervisees and offered actions the lead could not take."""
        mine = self._activity(responsible_staff_id=self.pl.id)
        theirs = self._activity(responsible_staff_id=self.cceo.id)

        context = my_plan.get_frontend_context(
            self.pl_user, {"fy": self.fy, "period": "fy"}
        )
        rendered = repr(context)
        self.assertIn(mine.id, rendered)
        self.assertNotIn(theirs.id, rendered)

    def test_partner_work_managed_by_the_cceo_is_not_in_the_program_leads_plan(self):
        """The delivery belongs to the CCEO who has to review its evidence."""
        partner_work = self._activity(
            responsible_staff_id=None,
            monitored_by_staff_id=self.cceo.id,
            assigned_partner_id=self.partner.id,
            delivery_type="partner",
            status="partner_scheduled",
        )

        self.assertNotIn(partner_work.id, self.plan_ids(self.pl_user))

    def test_partner_work_the_program_lead_manages_is_not_in_their_plan(self):
        """Managing a Partner's delivery is monitoring, not executing it."""
        mine_to_manage = self._activity(
            responsible_staff_id=None,
            monitored_by_staff_id=self.pl.id,
            assigned_partner_id=self.partner.id,
            delivery_type="partner",
            status="partner_scheduled",
        )

        self.assertNotIn(mine_to_manage.id, self.plan_ids(self.pl_user))

    def test_the_carve_out_returns_with_the_rule_switched_off(self):
        """Disabling the flag restores the previous display, records untouched."""
        from django.test import override_settings

        mine_to_manage = self._activity(
            responsible_staff_id=None,
            monitored_by_staff_id=self.pl.id,
            assigned_partner_id=self.partner.id,
            delivery_type="partner",
            status="partner_scheduled",
        )

        with override_settings(
            PARTNER_SUPPORTED_SCHOOL_PLANNING_VISIBILITY_ENABLED=False
        ):
            self.assertIn(mine_to_manage.id, self.plan_ids(self.pl_user))

    def test_an_unscheduled_partner_assignment_is_never_in_any_plan(self):
        """It has no activity, so there is nothing anyone can do on a day."""
        PartnerAssignment.objects.create(
            school=self.school,
            partner=self.partner,
            assigning_staff_id=self.cceo.id,
            monitoring_staff_id=self.cceo.id,
            expected_activity_type="school_visit",
            status="assigned",
        )

        for user in (self.pl_user, self.cceo_user):
            with self.subTest(user=user.name):
                self.assertEqual(self.plan_ids(user), set())

    def test_team_leakage_into_the_program_leads_plan_is_zero(self):
        """The requirement stated as one number."""
        self._activity(responsible_staff_id=self.cceo.id)
        self._activity(
            responsible_staff_id=None,
            monitored_by_staff_id=self.cceo.id,
            assigned_partner_id=self.partner.id,
            delivery_type="partner",
            status="partner_scheduled",
        )
        mine = self._activity(responsible_staff_id=self.pl.id)

        self.assertEqual(self.plan_ids(self.pl_user), {mine.id})
