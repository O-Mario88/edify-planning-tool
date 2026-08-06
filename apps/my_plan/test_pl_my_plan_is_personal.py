"""My Plan is a personal operating list, not a team queue.

A Program Lead's My Plan must contain the work they will personally do. The
moment a supervised CCEO's activity or a partner's delivery appears in it, the
list stops being a plan and becomes a monitoring dashboard the PL cannot act
on — and team oversight already has its own page.

The one carve-out is deliberate: a partner activity the PL is personally the
managing staff for is the PL's own work, because they are the person who has
to review the evidence and enter the Salesforce id.
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
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.cceo, supervisor=cls.pl
        )

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

    def test_partner_work_the_program_lead_personally_manages_is_in_their_plan(self):
        """The one carve-out: the PL is the managing staff, so it is their work.

        They are the person who reviews the evidence and enters the Salesforce
        id, and that is a task, not oversight.
        """
        mine_to_manage = self._activity(
            responsible_staff_id=None,
            monitored_by_staff_id=self.pl.id,
            assigned_partner_id=self.partner.id,
            delivery_type="partner",
            status="partner_scheduled",
        )

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
