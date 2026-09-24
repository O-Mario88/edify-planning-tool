"""The Programme Lead's past-due popup, and a plan leaving it when worked on.

Owner, 2026-09-24: "All past due activities planned should popup on the
program leads main dashboard with the button send to {CCEO name} and when they
work on it, it should disappear."
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import Client, TestCase
from django.utils import timezone

from apps.accounts.models import StaffSupervisorAssignment
from apps.activities.models import Activity
from apps.core.rbac import EdifyRole
from apps.my_plan import past_due_service
from apps.my_plan import test_past_due_service as base_fixture
from apps.notifications.models import Notification

POPUP = "/dashboard/past-due-popup"


class _Fixture(TestCase):
    """The past-due fixture (a Lead, their CCEO Charles, past-due work), plus
    a rival team whose work the Lead must never reach.

    The fixture is borrowed, not inherited, so its module's own tests run
    once, where they live.
    """

    _create_staff = base_fixture.PastDueServiceTest.__dict__["_create_staff"]

    @classmethod
    def setUpTestData(cls):
        base_fixture.PastDueServiceTest.__dict__["setUpTestData"].__func__(cls)
        cls.rival_pl_user, cls.rival_pl = cls._create_staff(
            "rival_pl_pd@test.com", "Rita Rival", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        cls.rival_user, cls.rival = cls._create_staff(
            "rival_pd@test.com", "Ronald Rival", EdifyRole.CCEO
        )
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.rival, supervisor=cls.rival_pl
        )
        cls.rival_past_due = Activity.objects.create(
            activity_type="school_visit",
            status="scheduled",
            planned_date=timezone.localdate() - timedelta(days=4),
            school=cls.school,
            responsible_staff_id=cls.rival.id,
            fy=cls.fy,
        )

    def client_for(self, user) -> Client:
        client = Client()
        client.force_login(user)
        return client


class ThePopupListsTheTeamTest(_Fixture):
    def test_the_service_lists_the_team_s_rows_alone(self):
        ctx = past_due_service.get_past_due_dashboard_context(self.pl_user)
        ids = [row["id"] for row in ctx["past_due_team"]]
        self.assertEqual(ids, [self.cceo_past_due_visit.id])
        self.assertEqual(ctx["pl_team_past_due_unsent"], 1)

    def test_the_popup_offers_send_to_the_officer(self):
        response = self.client_for(self.pl_user).get(POPUP)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Past-due team plans")
        self.assertContains(
            response, f'data-past-due-row="{self.cceo_past_due_visit.id}"'
        )
        self.assertContains(response, "Send to Charles")
        # The Lead's own past-due work is theirs to act on, not to send.
        self.assertNotContains(
            response, f'data-past-due-row="{self.pl_past_due_meeting.id}"'
        )

    def test_the_table_pages_in_place(self):
        """Every past-due plan is reachable a page at a time, and a page is
        fetched into the popup's table rather than as a second popup."""
        opened = self.client_for(self.pl_user).get(POPUP)
        self.assertContains(opened, 'data-pager-fragment="/dashboard/past-due-popup"')
        self.assertContains(opened, 'id="pl-past-due-table"')

        page = self.client_for(self.pl_user).get(
            POPUP,
            {"past_due_page": "1"},
            headers={"HX-Request": "true", "HX-Target": "pl-past-due-table"},
        )
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, f'data-past-due-row="{self.cceo_past_due_visit.id}"')
        self.assertNotContains(page, "data-pl-past-due-popup")
        self.assertNotContains(page, 'id="pl-past-due-table"')

    def test_the_main_dashboard_opens_it_while_anything_is_unsent(self):
        response = self.client_for(self.pl_user).get("/dashboard")
        self.assertContains(response, "data-pl-past-due-autoload")
        self.assertContains(response, 'hx-get="/dashboard/past-due-popup"')

    def test_it_does_not_open_once_everything_is_sent(self):
        client = self.client_for(self.pl_user)
        client.post(f"/dashboard/notify-past-due/{self.cceo_past_due_visit.id}/")
        response = client.get("/dashboard")
        self.assertNotContains(response, "data-pl-past-due-autoload")

    def test_a_cceo_has_no_popup(self):
        response = self.client_for(self.cceo_user).get(POPUP)
        self.assertEqual(response.status_code, 403)


class OnlyTheLeadMaySendTest(_Fixture):
    def test_another_team_s_plan_is_refused(self):
        response = self.client_for(self.pl_user).post(
            f"/dashboard/notify-past-due/{self.rival_past_due.id}/"
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            Notification.objects.filter(context_id=self.rival_past_due.id).exists()
        )

    def test_an_officer_cannot_send_to_themselves_or_anyone(self):
        response = self.client_for(self.cceo_user).post(
            f"/dashboard/notify-past-due/{self.cceo_past_due_visit.id}/"
        )
        self.assertEqual(response.status_code, 403)

    def test_work_no_longer_past_due_is_refused(self):
        Activity.objects.filter(id=self.cceo_past_due_visit.id).update(
            planned_date=timezone.localdate() + timedelta(days=3)
        )
        response = self.client_for(self.pl_user).post(
            f"/dashboard/notify-past-due/{self.cceo_past_due_visit.id}/"
        )
        self.assertEqual(response.status_code, 403)


class WorkingOnItClosesItTest(_Fixture):
    def _send(self):
        self.client_for(self.pl_user).post(
            f"/dashboard/notify-past-due/{self.cceo_past_due_visit.id}/"
        )
        return Notification.objects.get(
            context_id=self.cceo_past_due_visit.id,
            source_event_type=past_due_service.OVERDUE_REMINDER_EVENT,
        )

    def test_rescheduling_takes_it_off_the_popup_and_closes_the_notice(self):
        from apps.activities.services import reschedule

        # A cluster meeting: rescheduling a school visit also re-prices its day
        # batch, which needs the district classified — configuration this
        # rule does not depend on.
        meeting = Activity.objects.create(
            activity_type="cluster_meeting",
            status="scheduled",
            planned_date=timezone.localdate() - timedelta(days=2),
            responsible_staff_id=self.cceo.id,
            fy=self.fy,
        )
        Activity.objects.filter(id=self.cceo_past_due_visit.id).update(
            status="cancelled"
        )
        self.client_for(self.pl_user).post(f"/dashboard/notify-past-due/{meeting.id}/")
        notice = Notification.objects.get(
            context_id=meeting.id,
            source_event_type=past_due_service.OVERDUE_REMINDER_EVENT,
        )
        with self.captureOnCommitCallbacks(execute=True):
            reschedule(
                meeting.id,
                {
                    # Ahead, and inside this fiscal year: a reschedule never
                    # carries work across the year boundary.
                    "scheduledDate": min(
                        timezone.localdate() + timedelta(days=1),
                        date(int(self.fy), 9, 30),
                    ).isoformat(),
                    "reason": "School closed for exams",
                },
                self.cceo_user,
            )
        notice.refresh_from_db()
        self.assertIsNotNone(notice.resolved_at)
        ctx = past_due_service.get_past_due_dashboard_context(self.pl_user)
        self.assertEqual(list(ctx["past_due_team"]), [])

    def test_cancelling_closes_the_notice_too(self):
        from apps.activities.services import cancel

        notice = self._send()
        with self.captureOnCommitCallbacks(execute=True):
            cancel(
                self.cceo_past_due_visit.id,
                {"reason": "School merged"},
                self.cceo_user,
            )
        notice.refresh_from_db()
        self.assertIsNotNone(notice.resolved_at)
