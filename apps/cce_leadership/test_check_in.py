"""The weekly check-in: one officer's week, and last week's agreed actions."""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment, User
from apps.activities.models import Activity
from apps.cce_leadership import check_in
from apps.cce_leadership.models import CceoCoaching
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.fund_requests.models import WeeklyFundRequest
from apps.geography.models import District, Region
from apps.schools.models import School


def _staff(email, name, role):
    user = User.objects.create(
        email=email,
        name=name,
        roles=[role.value],
        active_role=role.value,
        is_active=True,
        status="active",
    )
    return user, StaffProfile.objects.create(user=user, title=name, country="Uganda")


class CheckInFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.today = timezone.localdate()
        cls.start, cls.end = check_in.week_of(cls.today)
        cls.fy = get_operational_fy(cls.today)
        region = Region.objects.create(name="Check Region")
        district = District.objects.create(name="Check District", region=region)
        cls.lead_user, cls.lead = _staff(
            "ci-pl@t.test", "Lead Lena", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        cls.amos_user, cls.amos = _staff("ci-a@t.test", "Amos", EdifyRole.CCEO)
        cls.ben_user, cls.ben = _staff("ci-b@t.test", "Ben", EdifyRole.CCEO)
        for officer in (cls.amos, cls.ben):
            StaffSupervisorAssignment.objects.create(
                supervisee=officer, supervisor=cls.lead
            )
        cls.school = School.objects.create(
            school_id="CI-1",
            name="Sunrise Primary",
            region=region,
            district=district,
            account_owner_id=cls.amos.id,
        )
        # Amos's week: one to do, one delivered, one returned; one long overdue.
        cls._activity(cls.start, "scheduled")
        cls._activity(cls.start, "ia_verified")
        cls._activity(cls.start, "returned_by_pl")
        cls._activity(cls.start - timedelta(days=30), "scheduled")
        WeeklyFundRequest.objects.create(
            fy=cls.fy,
            week_start_date=cls.start,
            week_end_date=cls.end,
            responsible_user=cls.amos_user.id,
            total_amount=500000,
            status="submitted_to_pl",
        )

    @classmethod
    def _activity(cls, planned, status):
        return Activity.objects.create(
            activity_type="school_visit",
            school=cls.school,
            responsible_staff_id=cls.amos.id,
            fy=cls.fy,
            planned_date=planned,
            planned_month=planned.month,
            status=status,
        )

    def figure(self, facts, line):
        return next(f["figure"] for f in facts if f["line"] == line)


class WeekFactsTest(CheckInFixture):
    def test_the_week_is_counted_from_the_officer_s_plan(self):
        facts = check_in.week_facts(self.amos, today=self.today)
        self.assertEqual(self.figure(facts, "Planned this week"), "3 activities")
        self.assertEqual(self.figure(facts, "Delivered this week"), "1 of 3")
        self.assertEqual(self.figure(facts, "Returned for correction"), "1 activity")
        self.assertEqual(
            self.figure(facts, "This week's funds"), "waiting for your Programme Lead"
        )
        self.assertEqual(self.figure(facts, "Leave, this week and next"), "none")

    def test_past_due_is_work_dated_before_today_and_not_done(self):
        facts = check_in.week_facts(self.amos, today=self.today)
        # The month-old visit, and this week's open work once its day passes.
        expected = 1 + (2 if self.today > self.start else 0)
        self.assertEqual(
            self.figure(facts, "Past due"),
            f"{expected} activit{'y' if expected == 1 else 'ies'}",
        )

    def test_an_officer_with_no_work_reads_zeros_not_an_error(self):
        facts = check_in.week_facts(self.ben, today=self.today)
        self.assertEqual(self.figure(facts, "Planned this week"), "0 activities")
        self.assertEqual(
            self.figure(facts, "This week's funds"), "no request this week"
        )


class LastCheckInTest(CheckInFixture):
    def test_next_week_opens_with_what_was_agreed(self):
        self.assertIsNone(check_in.last_check_in(self.amos))
        CceoCoaching.objects.create(
            author_id=self.lead_user.id,
            cceo_staff_id=self.amos.id,
            cceo_user_id=self.amos_user.id,
            kind=check_in.CHECK_IN_KIND,
            held_on=self.today,
            fy=self.fy,
            subject="Weekly check-in",
            agreed_actions="Clear the returned visit by Friday.",
        )
        last = check_in.last_check_in(self.amos)
        self.assertEqual(last["agreed_actions"], "Clear the returned visit by Friday.")
        self.assertEqual(check_in.held_this_week([self.amos, self.ben]), {self.amos.id})


class CheckInPageTest(CheckInFixture):
    def setUp(self):
        self.client.force_login(User.objects.get(id=self.lead_user.id))

    def test_the_lead_walks_the_team_one_officer_at_a_time(self):
        response = self.client.get("/team/check-in")
        self.assertRedirects(
            response, f"/team/check-in/{self.amos.id}", fetch_redirect_response=False
        )
        page = self.client.get(f"/team/check-in/{self.amos.id}")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Planned this week")
        self.assertContains(page, f'href="/team/check-in/{self.ben.id}"')
        self.assertContains(
            page, f"/team/coaching/new?cceo={self.amos.id}&amp;kind=performance_checkin"
        )
        self.assertNotContains(page, "data-check-in-previous")

    def test_a_lead_cannot_open_another_team_s_officer(self):
        _, stranger = _staff("ci-x@t.test", "Stranger", EdifyRole.CCEO)
        response = self.client.get(f"/team/check-in/{stranger.id}")
        self.assertRedirects(response, "/team/coaching", fetch_redirect_response=False)

    def test_the_one_to_ones_table_offers_the_check_in(self):
        response = self.client.get("/team/coaching")
        self.assertContains(response, f"/team/check-in/{self.amos.id}")
