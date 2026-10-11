"""Role briefs: what each role is told, how, and what a brief never carries."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment, User
from apps.activities.models import Activity
from apps.briefs import builder, delivery
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.fund_requests.models import WeeklyFundRequest
from apps.geography.models import District, Region
from apps.notifications.models import Notification
from apps.realtime import jobs
from apps.schools.models import School

# A Monday and the Friday before it, clear of Uganda's public holidays.
MONDAY = date(2026, 10, 12)
FRIDAY = date(2026, 10, 16)
SCHOOL_NAMES = ("Sunrise Primary", "Hillside Primary")
PEOPLE = ("Lead Lena", "Busy Ben", "Idle Ida", "Director Dan")


def _staff(email, name, role, **extra):
    user = User.objects.create(
        email=email,
        name=name,
        roles=[role.value],
        active_role=role.value,
        is_active=True,
        status="active",
        **extra,
    )
    return user, StaffProfile.objects.create(user=user, title=name, country="Uganda")


class BriefFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fy = get_operational_fy(MONDAY)
        region = Region.objects.create(name="Brief Region")
        district = District.objects.create(name="Brief District", region=region)
        cls.lead_user, cls.lead = _staff(
            "br-pl@t.test", "Lead Lena", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        cls.busy_user, cls.busy = _staff("br-busy@t.test", "Busy Ben", EdifyRole.CCEO)
        cls.idle_user, cls.idle = _staff("br-idle@t.test", "Idle Ida", EdifyRole.CCEO)
        cls.director_user, cls.director = _staff(
            "br-cd@t.test", "Director Dan", EdifyRole.COUNTRY_DIRECTOR
        )
        for officer in (cls.busy, cls.idle):
            StaffSupervisorAssignment.objects.create(
                supervisee=officer, supervisor=cls.lead
            )
        cls.schools = [
            School.objects.create(
                school_id=f"BR-{n}",
                name=name,
                region=region,
                district=district,
                account_owner_id=cls.busy.id,
            )
            for n, name in enumerate(SCHOOL_NAMES)
        ]
        # Ben's Tuesday: two visits at two schools. One visit a week overdue.
        for school in cls.schools:
            cls._activity(cls.busy.id, school, MONDAY + timedelta(days=1))
        cls._activity(cls.busy.id, cls.schools[0], MONDAY - timedelta(days=7))
        # Waiting on verification for two days.
        late = cls._activity(
            cls.busy.id,
            cls.schools[1],
            MONDAY - timedelta(days=10),
            status="awaiting_ia_verification",
        )
        Activity.objects.filter(id=late.id).update(
            submitted_to_ia_at=timezone.now() - timedelta(days=2)
        )

    @classmethod
    def _activity(cls, owner, school, planned, *, status="scheduled"):
        return Activity.objects.create(
            activity_type="school_visit",
            school=school,
            responsible_staff_id=owner,
            fy=cls.fy,
            planned_date=planned,
            planned_month=planned.month,
            status=status,
        )

    def line(self, brief, label):
        return next(line for line in brief.lines if line.label == label)

    def assert_no_names(self, brief):
        for word in (*SCHOOL_NAMES, *PEOPLE):
            self.assertNotIn(word, brief.message)
            self.assertNotIn(word, brief.title)


class EveningMessageTest(BriefFixture):
    def test_the_officer_is_told_tomorrow_in_counts(self):
        brief = builder.build(builder.FIELD_EVENING, self.busy_user, MONDAY)
        self.assertEqual(self.line(brief, "Tomorrow").text, "2 activities at 2 schools")
        self.assert_no_names(brief)

    def test_friday_s_message_is_about_monday(self):
        self._activity(self.busy.id, self.schools[0], FRIDAY + timedelta(days=3))
        brief = builder.build(builder.FIELD_EVENING, self.busy_user, FRIDAY)
        self.assertEqual(self.line(brief, "Monday").text, "1 activity at 1 school")

    def test_the_week_s_fund_request_is_named_by_its_state_never_its_sum(self):
        WeeklyFundRequest.objects.create(
            fy=self.fy,
            week_start_date=MONDAY,
            week_end_date=MONDAY + timedelta(days=6),
            responsible_user=self.busy_user.id,
            total_amount=730000,
            status="disbursed",
        )
        brief = builder.build(builder.FIELD_EVENING, self.busy_user, MONDAY)
        self.assertEqual(self.line(brief, "Funds").text, "paid")
        self.assertNotIn("730", brief.message)

    def test_an_officer_with_nothing_tomorrow_gets_no_message(self):
        self.assertIsNone(builder.build(builder.FIELD_EVENING, self.idle_user, MONDAY))


class MondayTeamBriefTest(BriefFixture):
    def test_the_lead_reads_the_team_in_counts(self):
        brief = builder.build(builder.TEAM_MONDAY, self.lead_user, MONDAY)
        self.assertEqual(self.line(brief, "Past due").text, "1 activity")
        self.assertIn("visits planned", self.line(brief, "Team plan").text)
        self.assert_no_names(brief)

    def test_every_link_is_one_the_lead_may_open(self):
        from apps.core.permissions import can_open_url

        brief = builder.build(builder.TEAM_MONDAY, self.lead_user, MONDAY)
        for line in brief.lines:
            if line.url:
                self.assertTrue(can_open_url(self.lead_user, line.url), line.url)


class MorningCountryBriefTest(BriefFixture):
    def test_the_director_reads_plan_and_exceptions(self):
        brief = builder.build(builder.COUNTRY_MORNING, self.director_user, MONDAY)
        self.assertIn("visits planned", self.line(brief, "Plan").text)
        self.assertEqual(self.line(brief, "Past due").text, "1 activity")
        self.assertEqual(
            self.line(brief, "Verification").text, "1 item waiting more than 24 hours"
        )
        self.assertTrue(brief.title.startswith("Morning Country Brief: "))
        self.assert_no_names(brief)

    def test_a_brief_is_built_for_the_role_held_not_the_hat_worn(self):
        self.director_user.active_role = EdifyRole.CCEO.value
        brief = builder.build(builder.COUNTRY_MORNING, self.director_user, MONDAY)
        self.assertEqual(self.line(brief, "Past due").text, "1 activity")
        self.assertEqual(self.director_user.active_role, EdifyRole.CCEO.value)


class RegionalDigestTest(BriefFixture):
    def test_the_regional_lead_reads_the_leads_in_counts(self):
        user, _ = _staff(
            "br-rpl@t.test", "Regional Rae", EdifyRole.REGIONAL_PROGRAM_LEAD
        )
        brief = builder.build(builder.REGIONAL_MONDAY, user, MONDAY)
        self.assertRegex(
            self.line(brief, "Programme Leads").text, r"^\d+ of 1 teams on track$"
        )
        self.assert_no_names(brief)


class DeliveryTest(BriefFixture):
    def notices(self, user, kind):
        return Notification.objects.filter(
            recipient_id=user.id, source_event_type=delivery.event_type(kind)
        )

    def test_the_bell_notice_opens_the_brief_page(self):
        self.assertEqual(jobs._do_evening_briefs(MONDAY), 1)
        notice = self.notices(self.busy_user, builder.FIELD_EVENING).get()
        self.assertEqual(notice.target_route, "/brief?kind=field_evening")
        self.assertEqual(notice.title, "Evening Message: 2 activities at 2 schools")

    def test_a_same_day_rerun_sends_nothing_even_after_archiving(self):
        jobs._do_evening_briefs(MONDAY)
        Notification.objects.update(status="archived")
        self.assertEqual(jobs._do_evening_briefs(MONDAY), 0)

    def test_monday_sends_the_team_brief_and_tuesday_does_not(self):
        jobs._do_morning_briefs(MONDAY + timedelta(days=1))
        self.assertFalse(self.notices(self.lead_user, builder.TEAM_MONDAY).exists())
        jobs._do_morning_briefs(MONDAY)
        self.assertTrue(self.notices(self.lead_user, builder.TEAM_MONDAY).exists())
        self.assertEqual(
            self.notices(self.director_user, builder.COUNTRY_MORNING).count(), 2
        )

    def test_nothing_is_sent_on_a_weekend_or_when_switched_off(self):
        self.assertEqual(jobs._do_evening_briefs(MONDAY - timedelta(days=1)), 0)
        with override_settings(ROLE_BRIEFS_ENABLED=False):
            self.assertEqual(jobs._do_evening_briefs(MONDAY), 0)

    def test_a_person_who_chose_no_brief_gets_none(self):
        User.objects.filter(id=self.busy_user.id).update(brief_channel="off")
        self.assertEqual(jobs._do_evening_briefs(MONDAY), 0)

    def test_a_text_message_goes_only_to_someone_who_chose_it(self):
        User.objects.filter(id=self.busy_user.id).update(
            brief_channel="sms", phone="+256700000001"
        )
        with (
            patch("apps.core.sms.SmsService.is_configured", True),
            patch("apps.core.sms.SmsService.send") as send,
            patch.object(delivery, "is_working_time", return_value=True),
            self.captureOnCommitCallbacks(execute=True),
        ):
            jobs._do_evening_briefs(MONDAY)
        (message,) = [call.args[0] for call in send.call_args_list]
        self.assertEqual(message.to, "+256700000001")
        self.assertIn("Tomorrow: 2 activities at 2 schools.", message.text)
        for name in SCHOOL_NAMES:
            self.assertNotIn(name, message.text)

    def test_nothing_leaves_the_platform_outside_working_hours(self):
        User.objects.filter(id=self.busy_user.id).update(
            brief_channel="sms", phone="+256700000001"
        )
        with (
            patch("apps.core.sms.SmsService.is_configured", True),
            patch("apps.core.sms.SmsService.send") as send,
            patch.object(delivery, "is_working_time", return_value=False),
            self.captureOnCommitCallbacks(execute=True),
        ):
            jobs._do_evening_briefs(MONDAY)
        send.assert_not_called()
        self.assertTrue(self.notices(self.busy_user, builder.FIELD_EVENING).exists())

    def test_working_time_is_a_weekday_between_seven_and_six(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        kampala = ZoneInfo("Africa/Kampala")
        at = lambda *a: datetime(*a, tzinfo=kampala)  # noqa: E731
        self.assertTrue(delivery.is_working_time(at(2026, 10, 12, 7, 0)))
        self.assertFalse(delivery.is_working_time(at(2026, 10, 12, 6, 59)))
        self.assertFalse(delivery.is_working_time(at(2026, 10, 12, 18, 1)))
        self.assertFalse(delivery.is_working_time(at(2026, 10, 11, 10, 0)))
        # Independence Day.
        self.assertFalse(delivery.is_working_time(at(2026, 10, 9, 10, 0)))


class BriefPageTest(BriefFixture):
    def test_the_page_shows_the_brief_and_the_channels(self):
        self.client.force_login(User.objects.get(id=self.lead_user.id))
        response = self.client.get("/brief")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Monday Team Brief")
        self.assertContains(response, 'data-brief-channel="sms"')

    def test_a_channel_the_account_cannot_use_is_refused(self):
        self.client.force_login(User.objects.get(id=self.lead_user.id))
        self.client.post("/brief/channel", {"channel": "sms"})
        self.assertEqual(User.objects.get(id=self.lead_user.id).brief_channel, "app")
        self.client.post("/brief/channel", {"channel": "off"})
        self.assertEqual(User.objects.get(id=self.lead_user.id).brief_channel, "off")

    def test_a_role_with_no_brief_cannot_open_the_page(self):
        user, _ = _staff("br-ia@t.test", "Ivy", EdifyRole.IMPACT_ASSESSMENT)
        self.client.force_login(User.objects.get(id=user.id))
        self.assertIn(self.client.get("/brief").status_code, (302, 403))
