"""The oversight pages, exercised through their real routes.

The service tests prove the arithmetic. These prove the things only the page
can be wrong about: who may open it, whose work it shows, and — the rule the
whole design rests on — that supervising somebody's work never comes with the
ability to change it.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from django.test import Client, TestCase

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.partners.models import Partner, PartnerAssignment
from apps.schools.models import School

PL_URL = "/team-planning-oversight/"
CD_URL = "/country-planning-oversight/"


class OversightPageFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fy = get_operational_fy()
        cls.region = Region.objects.create(id="r1", name="Central")
        cls.district = District.objects.create(
            id="d1", name="Kampala", region=cls.region
        )

        cls.pl_user, cls.pl = cls._staff(
            "pl@t.test", "Team Lead", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        cls.james_user, cls.james = cls._staff("james@t.test", "James", EdifyRole.CCEO)
        cls.rival_pl_user, cls.rival_pl = cls._staff(
            "rival@t.test", "Other Lead", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        cls.rival_user, cls.rival = cls._staff(
            "rc@t.test", "Rival CCEO", EdifyRole.CCEO
        )
        cls.cd_user, cls.cd = cls._staff(
            "cd@t.test", "Director", EdifyRole.COUNTRY_DIRECTOR
        )
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.james, supervisor=cls.pl
        )
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.rival, supervisor=cls.rival_pl
        )

        cls.school = cls._school("s1", "Alpha Primary")
        cls.rival_school = cls._school("s2", "Rival Primary")
        StaffSchoolAssignment.objects.create(staff=cls.james, school_id=cls.school.id)
        StaffSchoolAssignment.objects.create(
            staff=cls.rival, school_id=cls.rival_school.id
        )
        cls.partner = Partner.objects.create(name="Partner X", active_status=True)

        cls.james_activity = cls._activity(cls.james, cls.school, cost=75_000)
        cls.rival_activity = cls._activity(cls.rival, cls.rival_school, cost=42_000)

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

    @classmethod
    def _school(cls, school_id, name):
        return School.objects.create(
            school_id=school_id, name=name, district=cls.district, region=cls.region
        )

    @classmethod
    def _activity(cls, owner, school, cost=0):
        planned = date.today() + timedelta(days=5)
        activity = Activity.objects.create(
            activity_type="school_visit",
            school=school,
            fy=cls.fy,
            quarter="Q1",
            planned_date=planned,
            planned_month=planned.month,
            status="scheduled",
            responsible_staff_id=owner.id,
        )
        if cost:
            ActivityScheduleCostLine.objects.create(
                activity=activity,
                cost_setting_key="transport",
                label="Transport",
                unit_cost=cost,
                quantity=1,
                amount=cost,
            )
        return activity

    def as_user(self, user) -> Client:
        client = Client()
        client.force_login(user)
        return client


class RouteAccessTest(OversightPageFixture):
    def test_the_program_lead_page_opens_for_a_program_lead(self):
        response = self.as_user(self.pl_user).get(PL_URL)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Team Planning Oversight")

    def test_the_country_page_opens_for_the_country_director(self):
        response = self.as_user(self.cd_user).get(CD_URL)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Country Planning Oversight")

    def test_a_cceo_cannot_open_either_oversight_page(self):
        client = self.as_user(self.james_user)
        for url in (PL_URL, CD_URL):
            with self.subTest(url=url):
                self.assertNotEqual(client.get(url).status_code, 200)

    def test_a_program_lead_cannot_open_the_country_page(self):
        """Supervising a team is not a country remit."""
        self.assertNotEqual(self.as_user(self.pl_user).get(CD_URL).status_code, 200)

    def test_a_country_director_opens_the_team_page_grouped_by_program_lead(self):
        response = self.as_user(self.cd_user).get(PL_URL)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Programme Lead teams")
        self.assertContains(response, "Team Lead")
        self.assertContains(response, "Other Lead")


class ScopeTest(OversightPageFixture):
    def test_programme_lead_tabs_are_people_not_workflow_statuses(self):
        body = self.as_user(self.pl_user).get(PL_URL).content.decode()

        self.assertIn("My Work", body)
        self.assertIn("James", body)
        for removed in (
            "All Planned Work",
            "Partner Work",
            "Needs Attention",
            ">Completed<",
        ):
            with self.subTest(removed=removed):
                self.assertNotIn(removed, body)

    def test_selecting_a_cceo_opens_staff_and_partner_work_they_manage(self):
        body = (
            self.as_user(self.pl_user)
            .get(PL_URL, {"owner": self.james.id})
            .content.decode()
        )

        self.assertIn("Selected owner", body)
        self.assertIn("Alpha Primary", body)
        self.assertNotIn("Rival Primary", body)

    def test_period_control_offers_week_month_quarter_and_fy(self):
        body = self.as_user(self.pl_user).get(PL_URL).content.decode()

        self.assertIn('name="period"', body)
        self.assertIn('type="week"', body)
        for value in ("week", "month", "quarter", "fy"):
            with self.subTest(value=value):
                self.assertIn(f'<option value="{value}"', body)

    def test_week_period_reaches_the_selected_cceo_rows(self):
        week = self.james_activity.planned_date.strftime("%G-W%V")
        response = self.as_user(self.pl_user).get(
            PL_URL,
            {"owner": self.james.id, "period": "week", "week": week},
        )

        self.assertEqual(response.context["period"], "week")
        self.assertContains(response, "Alpha Primary")

    def test_the_page_shows_supervised_work_and_not_another_team(self):
        body = (
            self.as_user(self.pl_user)
            .get(PL_URL, {"owner": self.james.id})
            .content.decode()
        )

        self.assertIn("Alpha Primary", body)
        self.assertNotIn("Rival Primary", body)

    def test_the_country_page_shows_every_team(self):
        body = self.as_user(self.cd_user).get(CD_URL).content.decode()

        self.assertIn("Team Lead", body)
        self.assertIn("Other Lead", body)

    def test_the_team_expansion_cannot_be_pointed_at_another_team(self):
        """The id in the URL is not trusted; the rows are rebuilt for the caller.

        A Program Lead cannot reach the expansion at all, so the check that
        matters is that the route is gated rather than merely unlinked.
        """
        response = self.as_user(self.pl_user).get(
            f"/country-planning-oversight/team/{self.rival_pl.id}"
        )
        self.assertNotEqual(response.status_code, 200)


class ReadOnlyTest(OversightPageFixture):
    """A Program Lead may supervise a CCEO's activity but never change it."""

    MUTATION_MARKERS = (
        "/activities/{id}/reschedule",
        "/activities/{id}/cancel",
        "/activities/{id}/start",
        "/activities/{id}/complete",
        "/planning/schedule-action",
        "/planning/assign-partner-action",
    )

    def test_the_page_offers_no_control_that_changes_supervised_work(self):
        body = (
            self.as_user(self.pl_user)
            .get(PL_URL, {"owner": self.james.id})
            .content.decode()
        )

        for marker in self.MUTATION_MARKERS:
            route = marker.format(id=self.james_activity.id)
            with self.subTest(route=route):
                self.assertNotIn(route, body)

    def test_the_page_posts_nothing(self):
        """No form the page itself renders submits anything.

        Asked for as an HTMX fragment so the assertion covers the page's own
        markup rather than the shell's chrome — the sign-out form lives in the
        layout and belongs to every page.
        """
        body = (
            self.as_user(self.pl_user)
            .get(PL_URL, headers={"HX-Request": "true"})
            .content.decode()
        )

        posts = re.findall(r'<form[^>]*method=["\']post["\']', body, re.I)
        self.assertEqual(posts, [], "the oversight page must not submit anything")

    def test_the_country_page_posts_nothing(self):
        body = (
            self.as_user(self.cd_user)
            .get(CD_URL, headers={"HX-Request": "true"})
            .content.decode()
        )

        posts = re.findall(r'<form[^>]*method=["\']post["\']', body, re.I)
        self.assertEqual(posts, [])


class MoneyOnThePageTest(OversightPageFixture):
    def test_an_unscheduled_partner_assignment_shows_no_cost(self):
        PartnerAssignment.objects.create(
            school=self.school,
            partner=self.partner,
            assigning_staff_id=self.james.id,
            monitoring_staff_id=self.james.id,
            expected_activity_type="school_visit",
            status="assigned",
        )

        body = (
            self.as_user(self.pl_user)
            .get(PL_URL, {"owner": self.james.id})
            .content.decode()
        )

        self.assertIn("Partner yet to schedule", body)
        self.assertIn("UGX 0", body)

    def test_the_headline_budget_equals_the_cost_lines_in_scope(self):
        body = (
            self.as_user(self.pl_user)
            .get(PL_URL, {"owner": self.james.id})
            .content.decode()
        )

        # James's activity is the only costed work in this PL's scope.
        self.assertIn("UGX 75,000", body)
        self.assertNotIn("42,000", body)
